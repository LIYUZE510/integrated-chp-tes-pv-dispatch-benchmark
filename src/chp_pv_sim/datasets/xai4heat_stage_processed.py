from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from chp_pv_sim.paths import RAW_DIR, PROCESSED_DIR, REPORTS_DIR, ensure_dirs


# ---- Dataset meta (for QC report) ----
DOI = "10.17632/2mwc6x6kwb.1"
LICENSE = "CC BY 4.0"
DATASET_URL = "https://data.mendeley.com/datasets/2mwc6x6kwb/1"

RAW_ROOT = RAW_DIR / "xai4heat_scada_v1" / "extracted"
MANIFEST_PATH = RAW_DIR / "xai4heat_scada_v1" / "manifest.json"

OUT_PARQUET = PROCESSED_DIR / "xai4heat_scada_hourly.parquet"
OUT_AREA_PARQUET = PROCESSED_DIR / "xai4heat_heating_area.parquet"
QC_JSON = REPORTS_DIR / "xai4heat_qc.json"
QC_MD = REPORTS_DIR / "xai4heat_qc.md"


EXPECTED_COLS = [
    "t_amb",
    "t_ref",
    "t_sup_prim",
    "t_ret_prim",
    "t_sup_sec",
    "t_ret_sec",
    "delta_e",
]


@dataclass
class SeasonQC:
    heating_season: int
    start: str
    end: str
    n_rows: int
    expected_rows_if_continuous: int
    missing_hours: int
    non_1h_steps: int
    min_step: str | None
    max_step: str | None


@dataclass
class StationQC:
    substation_id: str
    file: str
    n_rows_total: int
    start: str
    end: str
    duplicate_timestamps: int
    n_columns_raw: int
    columns_raw: list[str]
    columns_missing_expected: list[str]
    columns_extra: list[str]
    na_counts: dict[str, int]
    negative_delta_e_rows: int
    seasons: list[SeasonQC]


def _read_csv_robust(path: Path) -> pd.DataFrame:
    """
    Robust CSV read for simple comma-separated files.
    (If delimiter issues occur, we'll escalate explicitly.)
    """
    df = pd.read_csv(path, encoding="utf-8", low_memory=False)
    if df.shape[1] <= 1:
        # try semicolon if needed
        df = pd.read_csv(path, encoding="utf-8", low_memory=False, sep=";")
    return df


def _infer_datetime_col(cols: list[str]) -> str:
    # XAI4HEAT uses "datetime" according to the paper
    if "datetime" in cols:
        return "datetime"
    # fallback heuristic
    lowered = {c.lower(): c for c in cols}
    for key in ["timestamp", "time", "date", "datetime_local"]:
        if key in lowered:
            return lowered[key]
    # last resort: first column
    return cols[0]


def _substation_id_from_filename(path: Path) -> str:
    # xai4heat_scada_L12_processed.csv -> L12
    stem = path.stem
    parts = stem.split("_")
    # find token starting with "L" followed by digits
    for tok in parts:
        if tok.startswith("L") and tok[1:].isdigit():
            return tok
    # fallback
    return stem


def _compute_heating_season(dt: pd.Series) -> pd.Series:
    """
    Heating season defined as Nov 1 -> Apr 1 (cross-year).
    We'll label season by start-year:
      - Nov/Dec 2021 -> season 2021
      - Jan/Feb/Mar/Apr 2022 -> season 2021
    """
    month = dt.dt.month
    year = dt.dt.year
    return pd.Series(np.where(month >= 11, year, year - 1), index=dt.index).astype("int64")


def _qc_by_season(df_station: pd.DataFrame) -> list[SeasonQC]:
    qcs: list[SeasonQC] = []
    for s, g in df_station.groupby("heating_season", sort=True):
        g = g.sort_values("datetime_local")
        ts = g["datetime_local"]
        diffs = ts.diff().dropna()
        non_1h = (diffs != pd.Timedelta(hours=1)).sum()

        # expected rows if continuous hourly from min..max within THIS season slice
        expected = pd.date_range(ts.min(), ts.max(), freq="h")
        missing = len(expected) - len(ts)

        min_step = None if diffs.empty else str(diffs.min())
        max_step = None if diffs.empty else str(diffs.max())

        qcs.append(
            SeasonQC(
                heating_season=int(s),
                start=str(ts.min()),
                end=str(ts.max()),
                n_rows=int(len(ts)),
                expected_rows_if_continuous=int(len(expected)),
                missing_hours=int(missing),
                non_1h_steps=int(non_1h),
                min_step=min_step,
                max_step=max_step,
            )
        )
    return qcs


def main() -> None:
    ensure_dirs()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Find files ----
    station_files = sorted(RAW_ROOT.rglob("xai4heat_scada_*_processed.csv"))
    if not station_files:
        raise FileNotFoundError(f"No station CSV files found under {RAW_ROOT}")

    # Heating area filename differs in paper vs your zip, so accept both patterns
    area_candidates = list(RAW_ROOT.rglob("xai4heat_heating_area*.csv")) + list(
        RAW_ROOT.rglob("xai4heat_heating_areas*.csv")
    )
    area_candidates = sorted({p.resolve() for p in area_candidates})
    if not area_candidates:
        raise FileNotFoundError(f"No heating area CSV found under {RAW_ROOT}")
    if len(area_candidates) > 1:
        print("[WARN] Multiple heating area files found, using the first:")
        for p in area_candidates:
            print("  -", p)
    area_path = area_candidates[0]

    print("Station files:")
    for p in station_files:
        print("  -", p.name)
    print("Heating area file:", area_path.name)

    # ---- Read heating area ----
    area_df = _read_csv_robust(area_path)
    area_df.columns = [c.strip() for c in area_df.columns]

    # Expected: substation_id, heating_area_m2 (paper)
    # Your file is xai4heat_heating_area.csv; we normalize columns robustly.
    # Try to locate id + area columns
    col_lower = {c.lower(): c for c in area_df.columns}
    id_col = col_lower.get("substation_id") or col_lower.get("substation") or list(area_df.columns)[0]
    area_col = col_lower.get("heating_area_m2") or col_lower.get("heating_area") or list(area_df.columns)[1]

    area_df = area_df[[id_col, area_col]].copy()
    area_df.columns = ["substation_id", "heating_area_m2"]

    # normalize id formatting (strip, upper)
    area_df["substation_id"] = area_df["substation_id"].astype(str).str.strip().str.upper()
    area_df["heating_area_m2"] = pd.to_numeric(area_df["heating_area_m2"], errors="coerce")

    if area_df["heating_area_m2"].isna().any():
        bad = area_df[area_df["heating_area_m2"].isna()]
        raise ValueError(f"Heating area contains NaN after numeric conversion:\n{bad}")

    # save area parquet
    area_df.sort_values("substation_id").to_parquet(OUT_AREA_PARQUET, index=False, engine="pyarrow", compression="zstd")
    print("Wrote:", OUT_AREA_PARQUET)

    # ---- Process each station ----
    frames: list[pd.DataFrame] = []
    qc_list: list[StationQC] = []

    for fpath in station_files:
        sid = _substation_id_from_filename(fpath).upper()
        df = _read_csv_robust(fpath)
        df.columns = [c.strip() for c in df.columns]

        dt_col = _infer_datetime_col(list(df.columns))
        if dt_col not in df.columns:
            raise KeyError(f"Could not find datetime column in {fpath.name}. Columns: {df.columns.tolist()}")

        # parse datetime (local time CET/CEST without tz info per dataset paper)
        dt = pd.to_datetime(df[dt_col], errors="coerce")
        n_nat = int(dt.isna().sum())
        if n_nat > 0:
            raise ValueError(f"{fpath.name}: datetime parse produced {n_nat} NaT values. Fix parsing explicitly.")

        df = df.drop(columns=[dt_col])
        df.insert(0, "datetime_local", dt)

        # enforce sort
        df = df.sort_values("datetime_local").reset_index(drop=True)

        # duplicates check
        dup = int(df["datetime_local"].duplicated().sum())

        # attach metadata columns
        df.insert(1, "substation_id", sid)

        # numeric conversion: keep everything, but ensure numeric columns are numeric where possible
        # We'll attempt numeric conversion for all non-metadata columns.
        for col in df.columns:
            if col in ("datetime_local", "substation_id"):
                continue
            if df[col].dtype == "object":
                # allow decimal comma just in case
                s = pd.to_numeric(df[col].astype(str).str.replace(",", ".", regex=False), errors="coerce")
                # convert only if we successfully parsed most non-null values
                orig_nonnull = int(df[col].notna().sum())
                conv_nonnull = int(s.notna().sum())
                if orig_nonnull == 0:
                    df[col] = s
                else:
                    if conv_nonnull / max(orig_nonnull, 1) >= 0.95:
                        df[col] = s

        # add heating area
        df = df.merge(area_df, on="substation_id", how="left")
        if df["heating_area_m2"].isna().any():
            raise ValueError(f"{sid}: heating_area_m2 missing after merge. Check heating area file.")

        # add season label
        df["heating_season"] = _compute_heating_season(df["datetime_local"])

        # QC: expected columns vs actual
        raw_cols = [c for c in df.columns if c not in ("datetime_local", "substation_id", "heating_area_m2", "heating_season")]
        missing_expected = sorted([c for c in EXPECTED_COLS if c not in raw_cols])
        extra_cols = sorted([c for c in raw_cols if c not in EXPECTED_COLS])

        # QC: NaN counts
        na_counts = {c: int(df[c].isna().sum()) for c in df.columns}

        # QC: negative delta_e
        neg_delta = 0
        if "delta_e" in df.columns:
            # ensure numeric if possible
            if pd.api.types.is_numeric_dtype(df["delta_e"]):
                neg_delta = int((df["delta_e"] < 0).sum())

        seasons_qc = _qc_by_season(df[["datetime_local", "heating_season"]].copy())

        qc_list.append(
            StationQC(
                substation_id=sid,
                file=fpath.name,
                n_rows_total=int(len(df)),
                start=str(df["datetime_local"].min()),
                end=str(df["datetime_local"].max()),
                duplicate_timestamps=dup,
                n_columns_raw=int(len(raw_cols)),
                columns_raw=sorted(raw_cols),
                columns_missing_expected=missing_expected,
                columns_extra=extra_cols,
                na_counts=na_counts,
                negative_delta_e_rows=neg_delta,
                seasons=seasons_qc,
            )
        )

        frames.append(df)

    # ---- Combine & write parquet ----
    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.sort_values(["substation_id", "datetime_local"]).reset_index(drop=True)

    # Strict schema hints (keep datetime_local as datetime64[ns], substation_id as string)
    all_df["substation_id"] = all_df["substation_id"].astype("string")

    all_df.to_parquet(OUT_PARQUET, index=False, engine="pyarrow", compression="zstd")
    print("Wrote:", OUT_PARQUET)

    # ---- Write QC report ----
    manifest = {}
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    qc_payload: dict[str, Any] = {
        "dataset": {
            "name": "XAI4HEAT SCADA Dataset 2024",
            "doi": DOI,
            "url": DATASET_URL,
            "license": LICENSE,
            "note_datetime": "Recorded as local time (CET/CEST) without timezone info per dataset paper.",
        },
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "raw_manifest": manifest.get("zip", {}),
        "stations": [asdict(q) for q in qc_list],
        "combined": {
            "n_rows": int(len(all_df)),
            "n_columns": int(all_df.shape[1]),
            "start": str(all_df["datetime_local"].min()),
            "end": str(all_df["datetime_local"].max()),
            "substations": sorted(all_df["substation_id"].unique().tolist()),
        },
    }

    QC_JSON.write_text(json.dumps(qc_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote:", QC_JSON)

    # Markdown summary
    lines: list[str] = []
    lines.append("# XAI4HEAT QC Report\n")
    lines.append(f"- DOI: {DOI}\n")
    lines.append(f"- Source: {DATASET_URL}\n")
    lines.append(f"- License: {LICENSE}\n")
    lines.append(f"- Generated (UTC): {qc_payload['created_utc']}\n")
    lines.append("\n## Combined\n")
    lines.append(f"- Rows: {qc_payload['combined']['n_rows']}\n")
    lines.append(f"- Columns: {qc_payload['combined']['n_columns']}\n")
    lines.append(f"- Start: {qc_payload['combined']['start']}\n")
    lines.append(f"- End: {qc_payload['combined']['end']}\n")
    lines.append(f"- Substations: {', '.join(qc_payload['combined']['substations'])}\n")

    lines.append("\n## Per station summary\n")
    lines.append("| substation | rows | start | end | dup_ts | missing_expected_cols | non_1h_steps_total | missing_hours_total |\n")
    lines.append("|---|---:|---|---|---:|---|---:|---:|\n")

    for q in qc_list:
        non_1h_total = sum(s.non_1h_steps for s in q.seasons)
        missing_total = sum(s.missing_hours for s in q.seasons)
        lines.append(
            f"| {q.substation_id} | {q.n_rows_total} | {q.start} | {q.end} | {q.duplicate_timestamps} | "
            f"{', '.join(q.columns_missing_expected) if q.columns_missing_expected else '-'} | "
            f"{non_1h_total} | {missing_total} |\n"
        )

    QC_MD.write_text("".join(lines), encoding="utf-8")
    print("Wrote:", QC_MD)

    # ---- Terminal summary ----
    print("\n=== QUICK QC SUMMARY ===")
    for q in qc_list:
        non_1h_total = sum(s.non_1h_steps for s in q.seasons)
        missing_total = sum(s.missing_hours for s in q.seasons)
        print(
            f"{q.substation_id}: rows={q.n_rows_total}, dup={q.duplicate_timestamps}, "
            f"non_1h_steps={non_1h_total}, missing_hours={missing_total}, "
            f"missing_expected_cols={q.columns_missing_expected or '-'}"
        )

    print("\nNext: we'll inspect the parquet + confirm delta_e semantics for heat demand modeling.")


if __name__ == "__main__":
    main()