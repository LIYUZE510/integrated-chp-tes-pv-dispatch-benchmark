from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, Any, Optional, Iterable, Tuple

import pandas as pd

from chp_pv_sim.reports.result_catalog import (
    solver_profit_objective,
    solver_system_cost_equivalent,
)


def find_project_root() -> Path:
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    for base in candidates:
        for p in [base] + list(base.parents):
            if (p / "data" / "scenarios").exists() and (p / "reports").exists():
                return p
    raise RuntimeError("Cannot locate project root containing data/scenarios and reports.")


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def pick_col(df: pd.DataFrame, candidates: Iterable[str], required: bool = True) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    if required:
        raise KeyError(f"Missing any of {list(candidates)}; available={list(df.columns)}")
    return None


def get_series(df: pd.DataFrame, col: str) -> pd.Series:
    obj = df[col]
    if isinstance(obj, pd.DataFrame):
        return obj.iloc[:, 0]
    return obj


def to_num(s: pd.Series) -> pd.Series:
    if not isinstance(s, pd.Series):
        raise TypeError("Expected a pandas Series")
    if s.dtype == object:
        s = (
            s.astype(str)
             .str.strip()
             .str.replace("%", "", regex=False)
             .str.replace(",", "", regex=False)
        )
        s = s.replace({"": None, "nan": None, "None": None})
    return pd.to_numeric(s, errors="coerce")


def normalize_temp_label(x: Any) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip().upper()
    s = s.replace(" ", "")
    s = s.replace("DEG", "C")
    s = s.replace("°C", "C")
    s = s.replace("OC", "C")
    s = s.replace("KOND.REGIME", "KOND").replace("KONDREGIME", "KOND")
    return s


def standardize_segments(df: pd.DataFrame, axis: str) -> pd.DataFrame:
    temp_col = pick_col(df, ["temp_label", "temp", "temperature", "tempLabel"], True)
    seg_col = pick_col(df, ["segment", "seg", "segment_id", "seg_id"], False)

    if axis.upper() == "H":
        k_col = pick_col(df, ["k_HQ", "k_hq", "k", "slope"], True)
        b_col = pick_col(df, ["b_HQ", "b_hq", "b", "intercept"], True)
    else:
        k_col = pick_col(df, ["k_EH", "k_eh", "k", "slope"], True)
        b_col = pick_col(df, ["b_EH", "b_eh", "b", "intercept"], True)

    qlb_col = pick_col(df, ["q_lb_eff", "Q_lb_eff", "q_lb", "Q_lb", "q_min"], True)
    qub_col = pick_col(df, ["q_ub_eff", "Q_ub_eff", "q_ub", "Q_ub", "q_max"], True)

    out = pd.DataFrame({
        "temp_label": get_series(df, temp_col).map(normalize_temp_label),
        "k": to_num(get_series(df, k_col)),
        "b": to_num(get_series(df, b_col)),
        "q_lb": to_num(get_series(df, qlb_col)),
        "q_ub": to_num(get_series(df, qub_col)),
    })

    if seg_col is not None:
        out["segment_raw"] = to_num(get_series(df, seg_col))
    else:
        out["segment_raw"] = pd.NA

    out = out.dropna(subset=["temp_label", "k", "b", "q_lb", "q_ub"]).copy()
    out = out[out["q_ub"] >= out["q_lb"]].copy()
    out = out.sort_values(["temp_label", "q_lb", "q_ub"]).reset_index(drop=True)
    out["segment_idx"] = out.groupby("temp_label").cumcount() + 1
    return out


def standardize_dispatch(df: pd.DataFrame) -> pd.DataFrame:
    dt_col = pick_col(df, ["datetime_local", "datetime"], True)

    temp_col = pick_col(df, ["temp_label", "temp"], False)
    heat_seg_col = pick_col(df, ["heat_seg", "heat_segment", "seg_h"], False)
    power_seg_col = pick_col(df, ["power_seg", "power_segment", "seg_e"], False)
    q_col = pick_col(df, ["Q_chp_mw", "Q_mw", "Q_in_mw", "steam_mw"], False)
    on_col = pick_col(df, ["on"], False)
    start_col = pick_col(df, ["start"], False)
    stop_col = pick_col(df, ["stop"], False)

    out = pd.DataFrame({
        "datetime_local": pd.to_datetime(get_series(df, dt_col)),
        "mode": get_series(df, pick_col(df, ["mode"], False)) if pick_col(df, ["mode"], False) else "ON",
        "temp_label": get_series(df, temp_col).map(normalize_temp_label) if temp_col else "",
        "heat_seg": to_num(get_series(df, heat_seg_col)) if heat_seg_col else pd.NA,
        "power_seg": to_num(get_series(df, power_seg_col)) if power_seg_col else pd.NA,
        "H_chp_mw": to_num(get_series(df, pick_col(df, ["H_chp_mw", "chp_heat_mw", "H_mw"], True))),
        "E_chp_mw": to_num(get_series(df, pick_col(df, ["E_chp_mw", "chp_elec_mw", "E_mw"], True))),
        "boiler_mw": to_num(get_series(df, pick_col(df, ["boiler_mw", "B_mw"], False))) if pick_col(df, ["boiler_mw", "B_mw"], False) else 0.0,
        "dump_mw": to_num(get_series(df, pick_col(df, ["dump_mw", "U_mw"], False))) if pick_col(df, ["dump_mw", "U_mw"], False) else 0.0,
        "under_mw": to_num(get_series(df, pick_col(df, ["under_mw", "V_mw"], False))) if pick_col(df, ["under_mw", "V_mw"], False) else 0.0,
        "pv_curt_mw": to_num(get_series(df, pick_col(df, ["pv_curt_mw", "C_pv_mw"], False))) if pick_col(df, ["pv_curt_mw", "C_pv_mw"], False) else 0.0,
        "chp_curt_mw": to_num(get_series(df, pick_col(df, ["chp_curt_mw", "C_chp_mw"], False))) if pick_col(df, ["chp_curt_mw", "C_chp_mw"], False) else 0.0,
        "grid_import_mw": to_num(get_series(df, pick_col(df, ["grid_import_mw", "G_imp_mw"], False))) if pick_col(df, ["grid_import_mw", "G_imp_mw"], False) else 0.0,
        "grid_export_mw": to_num(get_series(df, pick_col(df, ["grid_export_mw", "G_exp_mw"], False))) if pick_col(df, ["grid_export_mw", "G_exp_mw"], False) else 0.0,
        "ch_mw": to_num(get_series(df, pick_col(df, ["ch_mw", "p_ch_mw"], False))) if pick_col(df, ["ch_mw", "p_ch_mw"], False) else 0.0,
        "dis_mw": to_num(get_series(df, pick_col(df, ["dis_mw", "p_dis_mw"], False))) if pick_col(df, ["dis_mw", "p_dis_mw"], False) else 0.0,
    })

    out["Q_chp_mw"] = to_num(get_series(df, q_col)) if q_col else pd.NA

    if on_col:
        out["on"] = to_num(get_series(df, on_col)).fillna(0.0)
    else:
        out["on"] = ((out["H_chp_mw"].fillna(0) > 1e-9) | (out["E_chp_mw"].fillna(0) > 1e-9)).astype(float)

    if start_col:
        out["start"] = to_num(get_series(df, start_col)).fillna(0.0)
    else:
        prev_on = out["on"].shift(1).fillna(0.0)
        out["start"] = ((out["on"] > 0.5) & (prev_on <= 0.5)).astype(float)

    if stop_col:
        out["stop"] = to_num(get_series(df, stop_col)).fillna(0.0)
    else:
        prev_on = out["on"].shift(1).fillna(0.0)
        out["stop"] = ((out["on"] <= 0.5) & (prev_on > 0.5)).astype(float)

    for c in [
        "H_chp_mw", "E_chp_mw", "boiler_mw", "dump_mw", "under_mw",
        "pv_curt_mw", "chp_curt_mw", "grid_import_mw", "grid_export_mw",
        "ch_mw", "dis_mw", "Q_chp_mw", "on", "start", "stop"
    ]:
        out[c] = to_num(out[c]).fillna(0.0)

    return out.sort_values("datetime_local").reset_index(drop=True)


def _candidate_segments(tbl: pd.DataFrame, temp_label: str, seg_hint: Optional[float]) -> pd.DataFrame:
    temp_tbl = tbl[tbl["temp_label"] == temp_label].copy()
    if temp_tbl.empty:
        return temp_tbl

    if seg_hint is None or pd.isna(seg_hint):
        return temp_tbl

    tol = 1e-9
    use = pd.DataFrame()

    if "segment_raw" in temp_tbl.columns:
        m = temp_tbl["segment_raw"].notna() & ((temp_tbl["segment_raw"] - float(seg_hint)).abs() <= tol)
        use = temp_tbl[m]

    if use.empty:
        m = (temp_tbl["segment_idx"] - int(round(float(seg_hint)))).abs() <= tol
        use = temp_tbl[m]

    return use if not use.empty else temp_tbl


def recover_q_row(
    row: pd.Series,
    heat_tbl: pd.DataFrame,
    power_tbl: pd.DataFrame,
    q_tol: float = 1e-3,
) -> float:
    q0 = float(row.get("Q_chp_mw", 0.0))
    if math.isfinite(q0) and q0 > 0:
        return q0

    H = float(row.get("H_chp_mw", 0.0))
    E = float(row.get("E_chp_mw", 0.0))
    on = float(row.get("on", 0.0))
    temp = normalize_temp_label(row.get("temp_label", ""))

    if on <= 0.5 and abs(H) <= 1e-9 and abs(E) <= 1e-9:
        return 0.0
    if temp == "":
        return 0.0

    h_cands = _candidate_segments(heat_tbl, temp, row.get("heat_seg", pd.NA))
    p_cands = _candidate_segments(power_tbl, temp, row.get("power_seg", pd.NA))
    if h_cands.empty and p_cands.empty:
        return 0.0

    best = None
    best_score = float("inf")

    # 1) infer Q from heat side, validate on power side
    for _, h in h_cands.iterrows():
        k = float(h["k"])
        if abs(k) < 1e-12:
            continue
        # raw table relation: Q = k_HQ * H + b_HQ
        qh = k * H + float(h["b"])
        if qh < float(h["q_lb"]) - q_tol or qh > float(h["q_ub"]) + q_tol:
            continue

        if p_cands.empty:
            if 0.0 < best_score:
                best = qh
                best_score = 0.0
            continue

        for _, p in p_cands.iterrows():
            if qh < float(p["q_lb"]) - q_tol or qh > float(p["q_ub"]) + q_tol:
                continue
            kp = float(p["k"])
            if abs(kp) < 1e-12:
                continue
            # raw table relation: Q = k_EH * E + b_EH => E = (Q - b_EH) / k_EH
            e_hat = (qh - float(p["b"])) / kp
            score = abs(E - e_hat)
            if score < best_score:
                best = qh
                best_score = score

    # 2) infer Q from power side, validate on heat side
    for _, p in p_cands.iterrows():
        k = float(p["k"])
        if abs(k) < 1e-12:
            continue
        # raw table relation: Q = k_EH * E + b_EH
        qe = k * E + float(p["b"])
        if qe < float(p["q_lb"]) - q_tol or qe > float(p["q_ub"]) + q_tol:
            continue

        if h_cands.empty:
            if 0.0 < best_score:
                best = qe
                best_score = 0.0
            continue

        for _, h in h_cands.iterrows():
            if qe < float(h["q_lb"]) - q_tol or qe > float(h["q_ub"]) + q_tol:
                continue
            kh = float(h["k"])
            if abs(kh) < 1e-12:
                continue
            # raw table relation: Q = k_HQ * H + b_HQ => H = (Q - b_HQ) / k_HQ
            h_hat = (qe - float(h["b"])) / kh
            score = abs(H - h_hat)
            if score < best_score:
                best = qe
                best_score = score

    if best is None:
        return 0.0
    return max(0.0, float(best))


def attach_recovered_q(df: pd.DataFrame, heat_tbl: pd.DataFrame, power_tbl: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    missing = (df["Q_chp_mw"].fillna(0.0) <= 0.0)
    if missing.any():
        df.loc[missing, "Q_chp_mw"] = df.loc[missing].apply(
            lambda row: recover_q_row(row, heat_tbl=heat_tbl, power_tbl=power_tbl),
            axis=1,
        )
    return df


def compute_economics(df: pd.DataFrame, summary: Dict[str, Any]) -> Dict[str, Any]:
    cfg = summary.get("scenario", {})

    cost_q = float(cfg.get("cost_q", 0.0))
    cost_boiler = float(cfg.get("cost_boiler", 0.0))
    cost_dump = float(cfg.get("cost_dump", 0.0))
    penalty_under = float(cfg.get("penalty_under", 0.0))
    cycle_cost = float(cfg.get("cycle_cost", 0.0))
    startup_cost = float(cfg.get("startup_cost", 0.0))
    shutdown_cost = float(cfg.get("shutdown_cost", 0.0))
    price_buy = float(cfg.get("price_buy", cfg.get("price_e_buy", 0.0)))
    price_sell = float(cfg.get("price_sell", cfg.get("price_e", 0.0)))
    penalty_pv_curt = float(cfg.get("penalty_pv_curt", 0.0))
    penalty_chp_curt = float(cfg.get("penalty_chp_curt", 0.0))

    chp_cost = cost_q * df["Q_chp_mw"].sum()
    boiler_cost = cost_boiler * df["boiler_mw"].sum()
    dump_penalty_cost = cost_dump * df["dump_mw"].sum()
    pv_curtailment_penalty_cost = penalty_pv_curt * df["pv_curt_mw"].sum()
    chp_curtailment_penalty_cost = penalty_chp_curt * df["chp_curt_mw"].sum()
    curtailment_penalty_cost = pv_curtailment_penalty_cost + chp_curtailment_penalty_cost
    under_penalty_cost = penalty_under * df["under_mw"].sum()
    cycling_cost_total = cycle_cost * (df["ch_mw"].sum() + df["dis_mw"].sum())
    startup_cost_total = startup_cost * df["start"].sum()
    shutdown_cost_total = shutdown_cost * df["stop"].sum()
    import_cost = price_buy * df["grid_import_mw"].sum()
    export_revenue = price_sell * df["grid_export_mw"].sum()

    profit_objective_realized = (
        export_revenue
        - import_cost
        - chp_cost
        - boiler_cost
        - dump_penalty_cost
        - curtailment_penalty_cost
        - under_penalty_cost
        - cycling_cost_total
        - startup_cost_total
        - shutdown_cost_total
    )
    system_cost_realized = -profit_objective_realized

    solver_profit = solver_profit_objective(summary)
    solver_system = solver_system_cost_equivalent(summary)
    diff_profit = None
    diff_system = None
    if math.isfinite(solver_profit):
        diff_profit = float(profit_objective_realized) - float(solver_profit)
    if math.isfinite(solver_system):
        diff_system = float(system_cost_realized) - float(solver_system)

    return {
        "profit_objective_realized": float(profit_objective_realized),
        "system_cost_realized": float(system_cost_realized),
        "solver_profit_objective": None if not math.isfinite(solver_profit) else float(solver_profit),
        "solver_system_cost_equivalent": None if not math.isfinite(solver_system) else float(solver_system),
        "difference_profit_realized_minus_solver": diff_profit,
        "difference_system_cost_realized_minus_solver": diff_system,

        # legacy aliases for older JSON/report readers
        "solver_reported_objective": None if not math.isfinite(solver_profit) else float(solver_profit),
        "total_objective_realized": float(profit_objective_realized),

        "chp_cost": chp_cost,
        "boiler_cost": boiler_cost,
        "dump_penalty_cost": dump_penalty_cost,
        "pv_curtailment_penalty_cost": pv_curtailment_penalty_cost,
        "chp_curtailment_penalty_cost": chp_curtailment_penalty_cost,
        "curtailment_penalty_cost": curtailment_penalty_cost,
        "under_penalty_cost": under_penalty_cost,
        "cycling_cost": cycling_cost_total,
        "storage_cycling_cost": cycling_cost_total,
        "startup_cost": startup_cost_total,
        "shutdown_cost": shutdown_cost_total,
        "import_cost": import_cost,
        "export_revenue": export_revenue,
        "net_grid_cost": import_cost - export_revenue,
        "q_reconstructed_mwh": float(df["Q_chp_mw"].sum()),
        "boiler_mwh": float(df["boiler_mw"].sum()),
        "dump_mwh": float(df["dump_mw"].sum()),
        "pv_curt_mwh": float(df["pv_curt_mw"].sum()),
        "chp_curt_mwh": float(df["chp_curt_mw"].sum()),
        "grid_import_mwh": float(df["grid_import_mw"].sum()),
        "grid_export_mwh": float(df["grid_export_mw"].sum()),
        "starts": float(df["start"].sum()),
        "stops": float(df["stop"].sum()),
    }


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = []
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for _, row in df.iterrows():
        vals = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                vals.append(f"{v:.3f}")
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def default_result_paths(root: Path, scenario: str, tag: str) -> Tuple[Path, Path]:
    res_dir = root / "data" / "scenarios" / scenario / "results"
    return (
        res_dir / f"dispatch_chp_storage_pv_grid__{tag}.parquet",
        res_dir / f"dispatch_summary_pv_grid__{tag}.json",
    )


def load_case(
    root: Path,
    scenario: str,
    tag: Optional[str],
    parquet_path: Optional[str],
    summary_path: Optional[str],
    heat_tbl: pd.DataFrame,
    power_tbl: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, Any], str]:
    if parquet_path and summary_path:
        pq = Path(parquet_path)
        js = Path(summary_path)
        label = tag or pq.stem
    elif tag:
        pq, js = default_result_paths(root, scenario, tag)
        label = tag
    else:
        raise ValueError("Provide either --*-tag or both explicit --*-parquet and --*-summary paths.")

    if not pq.exists():
        raise FileNotFoundError(f"Missing parquet: {pq}")
    if not js.exists():
        raise FileNotFoundError(f"Missing summary: {js}")

    dispatch_raw = pd.read_parquet(pq)
    summary = read_json(js)
    dispatch = standardize_dispatch(dispatch_raw)
    dispatch = attach_recovered_q(dispatch, heat_tbl=heat_tbl, power_tbl=power_tbl)
    return dispatch, summary, label


def main():
    parser = argparse.ArgumentParser(
        description="Build a separate UC vs MPC objective-value and cost-breakdown table from existing result files."
    )
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--uc-tag", default="uc_paper_retained_fw")
    parser.add_argument("--mpc-tag", default="mpc_paper_retained_fw")
    parser.add_argument("--uc-parquet", default=None)
    parser.add_argument("--uc-summary", default=None)
    parser.add_argument("--mpc-parquet", default=None)
    parser.add_argument("--mpc-summary", default=None)
    parser.add_argument("--write-back-summaries", action="store_true")
    args = parser.parse_args()

    root = find_project_root()
    print("[Root]", root)
    print("[Scenario]", args.scenario)

    heat_seg_path = root / "data" / "processed" / "kaz_chpp_v3" / "shared" / "turbine_heat_segments_consistent.parquet"
    pow_seg_path = root / "data" / "processed" / "kaz_chpp_v3" / "shared" / "turbine_power_segments_consistent.parquet"

    heat_tbl = standardize_segments(pd.read_parquet(heat_seg_path), axis="H")
    power_tbl = standardize_segments(pd.read_parquet(pow_seg_path), axis="E")

    uc_df, uc_summary, uc_label = load_case(
        root, args.scenario, args.uc_tag, args.uc_parquet, args.uc_summary, heat_tbl, power_tbl
    )
    mpc_df, mpc_summary, mpc_label = load_case(
        root, args.scenario, args.mpc_tag, args.mpc_parquet, args.mpc_summary, heat_tbl, power_tbl
    )

    uc_econ = compute_economics(uc_df, uc_summary)
    mpc_econ = compute_economics(mpc_df, mpc_summary)

    rows = []
    for strategy, label, econ in [
        ("Full-horizon UC", uc_label, uc_econ),
        ("MPC", mpc_label, mpc_econ),
    ]:
        rows.append({
            "strategy": strategy,
            "case_tag": label,
            "system_cost_realized": econ["system_cost_realized"],
            "profit_objective_realized": econ["profit_objective_realized"],
            "chp_cost": econ["chp_cost"],
            "boiler_cost": econ["boiler_cost"],
            "dump_penalty_cost": econ["dump_penalty_cost"],
            "curtailment_penalty_cost": econ["curtailment_penalty_cost"],
            "import_cost": econ["import_cost"],
            "export_revenue": econ["export_revenue"],
            "startup_cost": econ["startup_cost"],
            "shutdown_cost": econ["shutdown_cost"],
            "cycling_cost": econ["cycling_cost"],
            "under_penalty_cost": econ["under_penalty_cost"],
            "solver_system_cost_equivalent": econ["solver_system_cost_equivalent"],
            "solver_profit_objective": econ["solver_profit_objective"],
        })

    table_df = pd.DataFrame(rows)

    delta = {k: None for k in table_df.columns}
    delta["strategy"] = "MPC - UC"
    delta["case_tag"] = f"{mpc_label} - {uc_label}"

    numeric_cols = [c for c in table_df.columns if c not in {"strategy", "case_tag"}]
    for c in numeric_cols:
        a = pd.to_numeric(pd.Series([table_df.loc[0, c]]), errors="coerce").iloc[0]
        b = pd.to_numeric(pd.Series([table_df.loc[1, c]]), errors="coerce").iloc[0]
        delta[c] = float(b - a) if pd.notna(a) and pd.notna(b) else None

    table_df = pd.concat([table_df, pd.DataFrame([delta])], ignore_index=True)

    report_base = root / "reports" / f"{args.scenario}__table_objective_breakdown_uc_vs_mpc"
    table_df.to_csv(report_base.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    report_base.with_suffix(".md").write_text(md_table(table_df), encoding="utf-8")

    payload = {
        "scenario": args.scenario,
        "uc_tag": uc_label,
        "mpc_tag": mpc_label,
        "uc_economics": uc_econ,
        "mpc_economics": mpc_econ,
        "delta_mpc_minus_uc": {
            k: (mpc_econ[k] - uc_econ[k])
            if isinstance(mpc_econ.get(k), (int, float)) and isinstance(uc_econ.get(k), (int, float))
            else None
            for k in sorted(set(uc_econ.keys()) | set(mpc_econ.keys()))
        },
    }
    write_json(report_base.with_suffix(".json"), payload)

    print("[Wrote]", report_base.with_suffix(".csv"))
    print("[Wrote]", report_base.with_suffix(".md"))
    print("[Wrote]", report_base.with_suffix(".json"))
    print("\n=== OBJECTIVE BREAKDOWN TABLE ===")
    print(table_df.to_string(index=False))

    if args.write_back_summaries:
        uc_summary["economics_realized"] = uc_econ
        mpc_summary["economics_realized"] = mpc_econ

        if args.uc_summary:
            write_json(Path(args.uc_summary), uc_summary)
        else:
            write_json(default_result_paths(root, args.scenario, uc_label)[1], uc_summary)

        if args.mpc_summary:
            write_json(Path(args.mpc_summary), mpc_summary)
        else:
            write_json(default_result_paths(root, args.scenario, mpc_label)[1], mpc_summary)

        print("[Write-back] Updated summary JSON files with economics_realized block.")


if __name__ == "__main__":
    main()