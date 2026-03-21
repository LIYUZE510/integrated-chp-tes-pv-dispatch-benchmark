from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from chp_pv_sim.paths import INTERIM_DIR, PROCESSED_DIR, REPORTS_DIR, ensure_dirs


# ----- Input dirs -----
BLOCK_DIR = INTERIM_DIR / "kaz_chpp_v3" / "blocks"
AUTO_DIR = INTERIM_DIR / "kaz_chpp_v3" / "auto_tables"

# ----- Output dirs -----
OUT_ROOT = PROCESSED_DIR / "kaz_chpp_v3"
OUT_SHARED = OUT_ROOT / "shared"
OUT_CASE1 = OUT_ROOT / "case1"
OUT_CASE2 = OUT_ROOT / "case2"

QC_JSON = REPORTS_DIR / "kaz_chpp_params_qc.json"
QC_MD = REPORTS_DIR / "kaz_chpp_params_qc.md"


_num_re = re.compile(r"^\s*[-+]?(?:\d+\.?\d*|\d*\.?\d+)(?:[eE][-+]?\d+)?\s*$")
_m_re = re.compile(r"^m(\d+)$", flags=re.IGNORECASE)
_b_re = re.compile(r"^B(\d+)$", flags=re.IGNORECASE)
_t_re = re.compile(r"^T([12])$", flags=re.IGNORECASE)


def _s(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()


def to_float(x: Any) -> float | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    s = _s(x)
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    s = s.replace(",", ".")
    if _num_re.match(s) is None:
        return None
    try:
        v = float(s)
    except Exception:
        return None
    if not np.isfinite(v):
        return None
    return v


def row_has_keyword(row: pd.Series, kw: str) -> bool:
    kw = kw.lower()
    for v in row.values:
        if v is None:
            continue
        s = _s(v).lower()
        if kw in s:
            return True
    return False


def find_header_row(df: pd.DataFrame, kw: str) -> int:
    for i in range(len(df)):
        if row_has_keyword(df.iloc[i], kw):
            return i
    raise ValueError(f"Could not find header keyword '{kw}' in block.")


def parse_temp_label(label: str) -> tuple[str, float | None]:
    """
    Returns (normalized_label, temp_c).
    Examples:
      '75oС' -> ('75C', 75)
      '90oC' -> ('90C', 90)
      'Kond.regime' -> ('KOND', None)
      '75deg' -> ('75C', 75)
    """
    s = _s(label)
    if s == "" or s.lower() in {"nan"}:
        return ("", None)

    low = s.lower()

    if "kond" in low:
        return ("KOND", None)

    # extract digits
    m = re.search(r"(\d+)", low)
    if m:
        t = float(m.group(1))
        return (f"{int(t)}C", t)

    return (s, None)


def read_block_parquet(name: str) -> pd.DataFrame:
    p = BLOCK_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"Missing block parquet: {p}")
    return pd.read_parquet(p)


def parse_heat_segments(df_blk: pd.DataFrame) -> pd.DataFrame:
    # expects columns: excel_row + A..G
    df = df_blk.copy()
    if "excel_row" in df.columns:
        df = df.drop(columns=["excel_row"])

    for col in ["A", "B", "C", "D", "E", "F", "G"]:
        if col not in df.columns:
            raise KeyError(f"heat block missing column {col}. Got: {df.columns.tolist()}")

    hdr = find_header_row(df[["A", "B", "C", "D", "E", "F", "G"]], "k_HQ")
    df = df.iloc[hdr + 1 :].copy()
    df = df.dropna(axis=0, how="all")

    # forward-fill temperature label
    df["temp_label_raw"] = df["A"].astype("string")
    df.loc[df["temp_label_raw"].isna() | (df["temp_label_raw"].str.strip() == ""), "temp_label_raw"] = pd.NA
    df["temp_label_raw"] = df["temp_label_raw"].ffill()

    # numeric cols
    df["k_hq"] = df["B"].map(to_float)
    df["b_hq"] = df["C"].map(to_float)
    df["h_lb"] = df["D"].map(to_float)
    df["h_ub"] = df["E"].map(to_float)
    df["q_lb"] = df["F"].map(to_float)
    df["q_ub"] = df["G"].map(to_float)

    # keep only rows that look like data rows
    df = df.dropna(subset=["k_hq", "b_hq", "h_lb", "h_ub", "q_lb", "q_ub"]).copy()

    # normalize temp
    norm = df["temp_label_raw"].map(lambda x: parse_temp_label(_s(x)))
    df["temp_label"] = [t[0] for t in norm]
    df["temp_c"] = [t[1] for t in norm]

    # IMPORTANT: physical relation from the table is Q = k_HQ * H + b_HQ
    df["q_lb_calc"] = df["k_hq"] * df["h_lb"] + df["b_hq"]
    df["q_ub_calc"] = df["k_hq"] * df["h_ub"] + df["b_hq"]
    df["err_q_lb"] = df["q_lb_calc"] - df["q_lb"]
    df["err_q_ub"] = df["q_ub_calc"] - df["q_ub"]

    # Inverted form (useful later for MILP with Q as decision variable): H = a*Q + c
    df["a_h_from_q"] = 1.0 / df["k_hq"]
    df["c_h_from_q"] = -df["b_hq"] / df["k_hq"]

    # segment ordering by H bounds (x-axis)
    df = df.sort_values(["temp_label", "h_lb", "h_ub"]).reset_index(drop=True)
    df["segment"] = df.groupby("temp_label").cumcount() + 1

    # contiguity checks within temp group
    df["h_lb_next"] = df.groupby("temp_label")["h_lb"].shift(-1)
    df["q_lb_next"] = df.groupby("temp_label")["q_lb"].shift(-1)
    df["h_gap_to_next"] = df["h_lb_next"] - df["h_ub"]
    df["q_gap_to_next"] = df["q_lb_next"] - df["q_ub"]

    return df[
        [
            "temp_label",
            "temp_c",
            "segment",
            "k_hq",
            "b_hq",
            "a_h_from_q",
            "c_h_from_q",
            "h_lb",
            "h_ub",
            "q_lb",
            "q_ub",
            "q_lb_calc",
            "q_ub_calc",
            "err_q_lb",
            "err_q_ub",
            "h_gap_to_next",
            "q_gap_to_next",
        ]
    ]

def parse_power_segments(df_blk: pd.DataFrame) -> pd.DataFrame:
    # expects columns: excel_row + J..P
    df = df_blk.copy()
    if "excel_row" in df.columns:
        df = df.drop(columns=["excel_row"])

    for col in ["J", "K", "L", "M", "N", "O", "P"]:
        if col not in df.columns:
            raise KeyError(f"power block missing column {col}. Got: {df.columns.tolist()}")

    hdr = find_header_row(df[["J", "K", "L", "M", "N", "O", "P"]], "k_EH")
    df = df.iloc[hdr + 1 :].copy()
    df = df.dropna(axis=0, how="all")

    df["temp_label_raw"] = df["J"].astype("string")
    df.loc[df["temp_label_raw"].isna() | (df["temp_label_raw"].str.strip() == ""), "temp_label_raw"] = pd.NA
    df["temp_label_raw"] = df["temp_label_raw"].ffill()

    df["k_eh"] = df["K"].map(to_float)
    df["b_eh"] = df["L"].map(to_float)
    df["e_lb"] = df["M"].map(to_float)
    df["e_ub"] = df["N"].map(to_float)
    df["q_lb"] = df["O"].map(to_float)
    df["q_ub"] = df["P"].map(to_float)

    df = df.dropna(subset=["k_eh", "b_eh", "e_lb", "e_ub", "q_lb", "q_ub"]).copy()

    norm = df["temp_label_raw"].map(lambda x: parse_temp_label(_s(x)))
    df["temp_label"] = [t[0] for t in norm]
    df["temp_c"] = [t[1] for t in norm]

    # IMPORTANT: physical relation from the table is Q = k_EH * E + b_EH
    df["q_lb_calc"] = df["k_eh"] * df["e_lb"] + df["b_eh"]
    df["q_ub_calc"] = df["k_eh"] * df["e_ub"] + df["b_eh"]
    df["err_q_lb"] = df["q_lb_calc"] - df["q_lb"]
    df["err_q_ub"] = df["q_ub_calc"] - df["q_ub"]

    # Inverted form: E = a*Q + c (useful for MILP)
    df["a_e_from_q"] = 1.0 / df["k_eh"]
    df["c_e_from_q"] = -df["b_eh"] / df["k_eh"]

    # segment ordering by E bounds (x-axis)
    df = df.sort_values(["temp_label", "e_lb", "e_ub"]).reset_index(drop=True)
    df["segment"] = df.groupby("temp_label").cumcount() + 1

    # contiguity checks within temp group
    df["e_lb_next"] = df.groupby("temp_label")["e_lb"].shift(-1)
    df["q_lb_next"] = df.groupby("temp_label")["q_lb"].shift(-1)
    df["e_gap_to_next"] = df["e_lb_next"] - df["e_ub"]
    df["q_gap_to_next"] = df["q_lb_next"] - df["q_ub"]

    return df[
        [
            "temp_label",
            "temp_c",
            "segment",
            "k_eh",
            "b_eh",
            "a_e_from_q",
            "c_e_from_q",
            "e_lb",
            "e_ub",
            "q_lb",
            "q_ub",
            "q_lb_calc",
            "q_ub_calc",
            "err_q_lb",
            "err_q_ub",
            "e_gap_to_next",
            "q_gap_to_next",
        ]
     ]


def parse_unit_eff(case: int) -> dict[str, pd.DataFrame]:
    # Read extracted block
    blk_name = f"UnitEff_Case_{case}__unit_eff_main__B1_O16.parquet"
    df_blk = read_block_parquet(blk_name)

    # drop excel_row but keep column letters
    df = df_blk.copy()
    if "excel_row" in df.columns:
        df = df.drop(columns=["excel_row"])

    # Find rows
    idx_chp = None
    idx_boilers = None
    for i in range(len(df)):
        if row_has_keyword(df.iloc[i], "av.Eff of CHP"):
            idx_chp = i
        if row_has_keyword(df.iloc[i], "av.Eff of Boilers"):
            idx_boilers = i
    if idx_chp is None or idx_boilers is None:
        raise ValueError(f"Case {case}: cannot locate CHP/Boilers header rows in UnitEff block.")

    # Map m-columns from boiler header row
    m_cols: dict[str, str] = {}
    for col in df.columns:
        v = _s(df.iloc[idx_boilers][col])
        m = _m_re.match(v)
        if m:
            m_cols[col] = f"m{int(m.group(1))}"

    if len(m_cols) == 0:
        raise ValueError(f"Case {case}: could not find any m1..mN labels in UnitEff boiler header row.")

    # CHP average efficiency row -> long table
    chp_rows = []
    for col, mname in m_cols.items():
        val = to_float(df.iloc[idx_chp][col])
        chp_rows.append({"case": case, "m": mname, "chp_eff": val})
    df_chp = pd.DataFrame(chp_rows).sort_values("m").reset_index(drop=True)

    # Boiler rows (Bound B1..B8 are in some column, usually 'C')
    # Identify rows that contain B\d somewhere
    boiler_records = []
    t_records = []
    for i in range(len(df)):
        # search for B\d / T1 T2 in row
        row = df.iloc[i]
        bound = None
        ttag = None
        for col in df.columns:
            v = _s(row[col])
            if _b_re.match(v):
                bound = v.upper()
            if _t_re.match(v):
                ttag = v.upper()

        if bound:
            # boiler_eff is usually in column 'B' (or sometimes first numeric col)
            # We'll pick the first cell in the row that parses to float AND is between 0 and 1.
            boiler_eff = None
            for col in df.columns:
                val = to_float(row[col])
                if val is not None and 0.0 < val < 1.0:
                    boiler_eff = val
                    break

            rec = {"case": case, "bound": bound, "boiler_eff": boiler_eff}
            for col, mname in m_cols.items():
                rec[mname] = to_float(row[col])
            boiler_records.append(rec)

        if ttag:
            rec = {"case": case, "tag": ttag}
            for col, mname in m_cols.items():
                rec[mname] = to_float(row[col])
            t_records.append(rec)

    df_boilers = pd.DataFrame(boiler_records).sort_values("bound").reset_index(drop=True)
    df_t = pd.DataFrame(t_records).sort_values("tag").reset_index(drop=True)

    return {"chp_eff": df_chp, "boilers": df_boilers, "t_params": df_t}


def parse_rhom_bounds(case: int) -> pd.DataFrame:
    blk_name = f"UnitEff_Case_{case}__rhoM_bounds__C19_O22.parquet"
    df_blk = read_block_parquet(blk_name)
    df = df_blk.copy()
    if "excel_row" in df.columns:
        df = df.drop(columns=["excel_row"])

    # Find row with m labels
    idx_m = None
    m_cols: dict[str, str] = {}
    for i in range(len(df)):
        for col in df.columns:
            v = _s(df.iloc[i][col])
            m = _m_re.match(v)
            if m:
                idx_m = i
                break
        if idx_m is not None:
            break

    if idx_m is None:
        raise ValueError(f"Case {case}: cannot find m1.. labels in rhoM bounds block.")

    for col in df.columns:
        v = _s(df.iloc[idx_m][col])
        m = _m_re.match(v)
        if m:
            m_cols[col] = f"m{int(m.group(1))}"

    # Find rows max/min (any cell == 'max'/'min')
    idx_max = None
    idx_min = None
    for i in range(len(df)):
        row = df.iloc[i].astype(str).str.strip().str.lower()
        if (row == "max").any():
            idx_max = i
        if (row == "min").any():
            idx_min = i

    if idx_max is None or idx_min is None:
        raise ValueError(f"Case {case}: cannot find max/min rows in rhoM bounds block.")

    rows = []
    for col, mname in m_cols.items():
        vmax = to_float(df.iloc[idx_max][col])
        vmin = to_float(df.iloc[idx_min][col])
        rows.append({"case": case, "m": mname, "rhom_min": vmin, "rhom_max": vmax})
    out = pd.DataFrame(rows).sort_values("m").reset_index(drop=True)
    return out


def read_auto_table(sheet_prefix: str, header_row: int) -> pd.DataFrame:
    """
    stage_tables created: {sanitized_sheet}__header{hr}.parquet
    """
    fname = f"{sheet_prefix}__header{header_row}.parquet"
    p = AUTO_DIR / fname
    if not p.exists():
        raise FileNotFoundError(f"Missing auto table: {p}")
    return pd.read_parquet(p)


def qc_segments(df: pd.DataFrame, kind: str) -> dict[str, Any]:
    # kind: "heat" or "power"
    err_cols = ["err_q_lb", "err_q_ub"]

    if kind == "heat":
        gap_cols = ["h_gap_to_next", "q_gap_to_next"]
        axis = "H"
        by_temp = (
            df.groupby("temp_label")
            .agg(segments=("segment", "count"), h_min=("h_lb", "min"), h_max=("h_ub", "max"), q_min=("q_lb", "min"), q_max=("q_ub", "max"))
            .reset_index()
            .to_dict(orient="records")
        )
    else:
        gap_cols = ["e_gap_to_next", "q_gap_to_next"]
        axis = "E"
        by_temp = (
            df.groupby("temp_label")
            .agg(segments=("segment", "count"), e_min=("e_lb", "min"), e_max=("e_ub", "max"), q_min=("q_lb", "min"), q_max=("q_ub", "max"))
            .reset_index()
            .to_dict(orient="records")
        )

    errs = df[err_cols].to_numpy(dtype=float)
    gaps = df[gap_cols].to_numpy(dtype=float)

    max_abs_err = float(np.nanmax(np.abs(errs))) if errs.size else float("nan")
    max_abs_gap = float(np.nanmax(np.abs(gaps))) if gaps.size else float("nan")

    tol_err = 1e-3
    tol_gap = 1e-6

    n_bad_err = int(np.sum(np.abs(errs) > tol_err))
    n_bad_gap = int(np.sum(np.abs(gaps) > tol_gap))

    return {
        "rows": int(len(df)),
        "unique_temp_labels": sorted(df["temp_label"].dropna().unique().tolist()),
        "axis": axis,
        "max_abs_err": max_abs_err,
        "n_err_gt_tol": n_bad_err,
        "tol_err": tol_err,
        "max_abs_gap": max_abs_gap,
        "n_gap_gt_tol": n_bad_gap,
        "tol_gap": tol_gap,
        "by_temp": by_temp,
    }


def main() -> None:
    ensure_dirs()
    OUT_SHARED.mkdir(parents=True, exist_ok=True)
    OUT_CASE1.mkdir(parents=True, exist_ok=True)
    OUT_CASE2.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Turbine segment tables (shared) ----
    df_heat_blk = read_block_parquet("Turbine_MW__heat_vs_steam_coeff__A1_G39.parquet")
    df_pow_blk = read_block_parquet("Turbine_MW__power_vs_steam_coeff__J1_P24.parquet")

    heat_seg = parse_heat_segments(df_heat_blk)
    pow_seg = parse_power_segments(df_pow_blk)

    out_heat = OUT_SHARED / "turbine_heat_segments.parquet"
    out_pow = OUT_SHARED / "turbine_power_segments.parquet"

    heat_seg.to_parquet(out_heat, index=False, engine="pyarrow", compression="zstd")
    pow_seg.to_parquet(out_pow, index=False, engine="pyarrow", compression="zstd")

    # ---- UnitEff + rhoM per case ----
    unit1 = parse_unit_eff(case=1)
    rhom1 = parse_rhom_bounds(case=1)
    unit2 = parse_unit_eff(case=2)
    rhom2 = parse_rhom_bounds(case=2)

    unit1["chp_eff"].to_parquet(OUT_CASE1 / "chp_eff_by_m.parquet", index=False, engine="pyarrow", compression="zstd")
    unit1["boilers"].to_parquet(OUT_CASE1 / "boiler_eff_table.parquet", index=False, engine="pyarrow", compression="zstd")
    unit1["t_params"].to_parquet(OUT_CASE1 / "t_params.parquet", index=False, engine="pyarrow", compression="zstd")
    rhom1.to_parquet(OUT_CASE1 / "rhom_bounds.parquet", index=False, engine="pyarrow", compression="zstd")

    unit2["chp_eff"].to_parquet(OUT_CASE2 / "chp_eff_by_m.parquet", index=False, engine="pyarrow", compression="zstd")
    unit2["boilers"].to_parquet(OUT_CASE2 / "boiler_eff_table.parquet", index=False, engine="pyarrow", compression="zstd")
    unit2["t_params"].to_parquet(OUT_CASE2 / "t_params.parquet", index=False, engine="pyarrow", compression="zstd")
    rhom2.to_parquet(OUT_CASE2 / "rhom_bounds.parquet", index=False, engine="pyarrow", compression="zstd")

    # ---- MaxMin and DemEH auto tables (case-specific) ----
    # These were staged earlier; we keep them because they are useful for capacity sanity checks later.
    dem1 = read_auto_table("DemEH_Case_1", header_row=2)
    dem2 = read_auto_table("DemEH_Case_2", header_row=2)
    mm1 = read_auto_table("MaxMin_Case_1", header_row=1)
    mm2 = read_auto_table("MaxMin_Case_2", header_row=1)

    (OUT_CASE1 / "demeh").mkdir(exist_ok=True)
    (OUT_CASE2 / "demeh").mkdir(exist_ok=True)

    dem1.to_parquet(OUT_CASE1 / "demeh" / "demeh_case1.parquet", index=False, engine="pyarrow", compression="zstd")
    dem2.to_parquet(OUT_CASE2 / "demeh" / "demeh_case2.parquet", index=False, engine="pyarrow", compression="zstd")
    mm1.to_parquet(OUT_CASE1 / "maxmin.parquet", index=False, engine="pyarrow", compression="zstd")
    mm2.to_parquet(OUT_CASE2 / "maxmin.parquet", index=False, engine="pyarrow", compression="zstd")

    # ---- QC summary ----
    qc = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "outputs": {
            "shared_heat_segments": str(out_heat).replace("\\", "/"),
            "shared_power_segments": str(out_pow).replace("\\", "/"),
            "case1_dir": str(OUT_CASE1).replace("\\", "/"),
            "case2_dir": str(OUT_CASE2).replace("\\", "/"),
        },
        "segments_heat_qc": qc_segments(heat_seg, kind="heat"),
        "segments_power_qc": qc_segments(pow_seg, kind="power"),
        "unit_eff_case1": {
            "chp_eff_rows": int(len(unit1["chp_eff"])),
            "boiler_rows": int(len(unit1["boilers"])),
            "t_params_rows": int(len(unit1["t_params"])),
            "rhom_rows": int(len(rhom1)),
        },
        "unit_eff_case2": {
            "chp_eff_rows": int(len(unit2["chp_eff"])),
            "boiler_rows": int(len(unit2["boilers"])),
            "t_params_rows": int(len(unit2["t_params"])),
            "rhom_rows": int(len(rhom2)),
        },
        "notes_units": [
            "Sheet name 'Turbine(MW)' indicates E/H segment values are in MW-scale. In hourly simulation (Δt=1h), MW and MWh/h are numerically equivalent.",
            "Q is labeled as inlet steam energy; we keep it in dataset units and do not convert at this stage.",
        ],
    }

    QC_JSON.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")

    md = []
    md.append("# Kazakhstan CHPP Parameters QC Report\n\n")
    md.append(f"- Generated (UTC): {qc['created_utc']}\n\n")

    md.append("## Shared turbine segments\n\n")
    md.append("### Heat segments (raw table relation: Q = k_HQ * H + b_HQ; MILP uses H = (Q - b_HQ) / k_HQ)\n")
    hs = qc["segments_heat_qc"]
    md.append(f"- rows: {hs['rows']}\n")
    md.append(f"- temp labels: {', '.join(hs['unique_temp_labels'])}\n")
    md.append(f"- max_abs_err (|Q_calc - Q_bound|): {hs['max_abs_err']:.6g} (tol={hs['tol_err']})\n")
    md.append(f"- n_err_gt_tol: {hs['n_err_gt_tol']}\n")
    md.append(f"- max_abs_gap (to next segment): {hs['max_abs_gap']:.6g} (tol={hs['tol_gap']})\n")
    md.append(f"- n_gap_gt_tol: {hs['n_gap_gt_tol']}\n\n")

    md.append("### Power segments (raw table relation: Q = k_EH * E + b_EH; MILP uses E = (Q - b_EH) / k_EH)\n")
    ps = qc["segments_power_qc"]
    md.append(f"- rows: {ps['rows']}\n")
    md.append(f"- temp labels: {', '.join(ps['unique_temp_labels'])}\n")
    md.append(f"- max_abs_err (|Q_calc - Q_bound|): {ps['max_abs_err']:.6g} (tol={ps['tol_err']})\n")
    md.append(f"- n_err_gt_tol: {ps['n_err_gt_tol']}\n")
    md.append(f"- max_abs_gap (to next segment): {ps['max_abs_gap']:.6g} (tol={ps['tol_gap']})\n")
    md.append(f"- n_gap_gt_tol: {ps['n_gap_gt_tol']}\n\n")

    md.append("## Unit efficiency tables\n\n")
    md.append(f"- case1: {qc['unit_eff_case1']}\n")
    md.append(f"- case2: {qc['unit_eff_case2']}\n\n")

    md.append("## Notes on units\n")
    for note in qc["notes_units"]:
        md.append(f"- {note}\n")

    QC_MD.write_text("".join(md), encoding="utf-8")

    # ---- Terminal summary ----
    print("Wrote turbine segments:")
    print("  -", out_heat)
    print("  -", out_pow)
    print("Wrote case1 tables under:", OUT_CASE1)
    print("Wrote case2 tables under:", OUT_CASE2)
    print("Wrote QC:")
    print("  -", QC_JSON)
    print("  -", QC_MD)

    print("\n=== QC SUMMARY (must look clean) ===")
    print("Heat segments:", qc["segments_heat_qc"])
    print("Power segments:", qc["segments_power_qc"])
    print("UnitEff case1:", qc["unit_eff_case1"])
    print("UnitEff case2:", qc["unit_eff_case2"])
    print("\nNext: we will build the actual CHP feasible set for MILP (E/H/Q + mode) and run a feasibility MILP test.")


if __name__ == "__main__":
    main()