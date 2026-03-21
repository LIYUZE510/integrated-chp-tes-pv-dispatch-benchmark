from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import pandas as pd

from chp_pv_sim.paths import PROCESSED_DIR, REPORTS_DIR, ensure_dirs


IN_SCADA = PROCESSED_DIR / "xai4heat_scada_hourly.parquet"

OUT_SUBSTATION = PROCESSED_DIR / "xai4heat_heat_demand_substation_hourly.parquet"
OUT_AGG = PROCESSED_DIR / "xai4heat_heat_demand_aggregate_hourly.parquet"

OUT_REPORT_JSON = REPORTS_DIR / "xai4heat_heat_demand_report.json"
OUT_REPORT_MD = REPORTS_DIR / "xai4heat_heat_demand_report.md"


REQUIRED_COLS = [
    "datetime_local",
    "substation_id",
    "delta_e",
    "heating_area_m2",
    "heating_season",
    "t_amb",
]


def main() -> None:
    ensure_dirs()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if not IN_SCADA.exists():
        raise FileNotFoundError(f"Missing input parquet: {IN_SCADA}. Run xai4heat_stage_processed first.")

    df = pd.read_parquet(IN_SCADA)

    # ---- Basic schema checks ----
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise KeyError(f"Input parquet missing required columns: {missing}\nAvailable: {df.columns.tolist()}")

    # Ensure types
    df["datetime_local"] = pd.to_datetime(df["datetime_local"], errors="raise")
    df["substation_id"] = df["substation_id"].astype("string")

    # delta_e must be numeric
    df["delta_e"] = pd.to_numeric(df["delta_e"], errors="raise")
    df["heating_area_m2"] = pd.to_numeric(df["heating_area_m2"], errors="raise")
    df["heating_season"] = pd.to_numeric(df["heating_season"], errors="raise").astype("int64")
    df["t_amb"] = pd.to_numeric(df["t_amb"], errors="coerce")

    # ---- Physical sanity gates (high standard) ----
    # delta_e is transmitted heat energy (kWh) per hour; should be >= 0 in processed dataset.
    neg = int((df["delta_e"] < 0).sum())
    if neg > 0:
        bad = df.loc[df["delta_e"] < 0, ["datetime_local", "substation_id", "delta_e"]].head(10)
        raise ValueError(f"Found {neg} negative delta_e rows. Example:\n{bad}")

    # heating_area must be positive
    nonpos_area = int((df["heating_area_m2"] <= 0).sum())
    if nonpos_area > 0:
        bad = df.loc[df["heating_area_m2"] <= 0, ["substation_id", "heating_area_m2"]].drop_duplicates().head(10)
        raise ValueError(f"Found {nonpos_area} non-positive heating_area_m2 rows. Example:\n{bad}")

    # ---- Derive heat demand features ----
    # delta_e is energy in kWh for the 1-hour interval.
    df["heat_kwh"] = df["delta_e"]
    df["heat_mwh"] = df["heat_kwh"] / 1000.0

    # Area-normalized intensity (kWh per hour per m2)
    df["heat_kwh_per_m2"] = df["heat_kwh"] / df["heating_area_m2"]

    # Keep a clean substation-level dataset
    keep_cols = [
        "datetime_local",
        "substation_id",
        "heating_season",
        "heating_area_m2",
        "t_amb",
        "heat_kwh",
        "heat_mwh",
        "heat_kwh_per_m2",
        # keep original temperatures too (useful later for explainability & diagnostics)
        "t_ref",
        "t_sup_prim",
        "t_ret_prim",
        "t_sup_sec",
        "t_ret_sec",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]  # robust if schema changes

    sub_df = df[keep_cols].sort_values(["substation_id", "datetime_local"]).reset_index(drop=True)
    sub_df.to_parquet(OUT_SUBSTATION, index=False, engine="pyarrow", compression="zstd")

    # ---- Aggregate (sum across substations present at each hour) ----
    # NOTE: number of substations changes across years (L8/L12/L22 start later),
    # so the aggregate across "all available" substations is not directly comparable across seasons.
    agg = (
        sub_df.groupby("datetime_local", as_index=False)
        .agg(
            heat_kwh_total=("heat_kwh", "sum"),
            heat_mwh_total=("heat_mwh", "sum"),
            heating_area_m2_total=("heating_area_m2", "sum"),
            t_amb_mean=("t_amb", "mean"),
            n_substations=("substation_id", "nunique"),
        )
        .sort_values("datetime_local")
        .reset_index(drop=True)
    )
    agg["heat_kwh_per_m2_total"] = agg["heat_kwh_total"] / agg["heating_area_m2_total"]
    agg.to_parquet(OUT_AGG, index=False, engine="pyarrow", compression="zstd")

    # ---- Report (paper-friendly) ----
    report = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "input": {"path": str(IN_SCADA), "rows": int(len(df)), "cols": int(df.shape[1])},
        "substation_output": {"path": str(OUT_SUBSTATION), "rows": int(len(sub_df)), "cols": int(sub_df.shape[1])},
        "aggregate_output": {"path": str(OUT_AGG), "rows": int(len(agg)), "cols": int(agg.shape[1])},
        "coverage": {
            "start": str(sub_df["datetime_local"].min()),
            "end": str(sub_df["datetime_local"].max()),
            "substations": sorted(sub_df["substation_id"].unique().tolist()),
            "heating_seasons": sorted(sub_df["heating_season"].unique().tolist()),
        },
        "sanity": {"negative_delta_e_rows": neg, "nonpositive_area_rows": nonpos_area},
        "stats": {
            "heat_mwh_hourly": {
                "min": float(sub_df["heat_mwh"].min()),
                "p01": float(sub_df["heat_mwh"].quantile(0.01)),
                "median": float(sub_df["heat_mwh"].median()),
                "p99": float(sub_df["heat_mwh"].quantile(0.99)),
                "max": float(sub_df["heat_mwh"].max()),
                "mean": float(sub_df["heat_mwh"].mean()),
            }
        },
    }

    OUT_REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = []
    md_lines.append("# XAI4HEAT Heat Demand Derivation Report\n\n")
    md_lines.append(f"- Generated (UTC): {report['created_utc']}\n")
    md_lines.append(f"- Input rows/cols: {report['input']['rows']} / {report['input']['cols']}\n")
    md_lines.append(f"- Output (substation) rows/cols: {report['substation_output']['rows']} / {report['substation_output']['cols']}\n")
    md_lines.append(f"- Output (aggregate) rows/cols: {report['aggregate_output']['rows']} / {report['aggregate_output']['cols']}\n\n")

    md_lines.append("## Coverage\n")
    md_lines.append(f"- Start: {report['coverage']['start']}\n")
    md_lines.append(f"- End: {report['coverage']['end']}\n")
    md_lines.append(f"- Substations: {', '.join(report['coverage']['substations'])}\n")
    md_lines.append(f"- Heating seasons: {', '.join(map(str, report['coverage']['heating_seasons']))}\n\n")

    md_lines.append("## Heat demand hourly stats (MWh per hour)\n")
    s = report["stats"]["heat_mwh_hourly"]
    md_lines.append(f"- min={s['min']:.6g}, p01={s['p01']:.6g}, median={s['median']:.6g}, mean={s['mean']:.6g}, p99={s['p99']:.6g}, max={s['max']:.6g}\n\n")

    md_lines.append("## Important note\n")
    md_lines.append(
        "- The dataset adds new substations in later years, so the aggregate across 'all available' substations is not directly comparable across seasons. "
        "For a consistent city-zone simulation, we will select a fixed subset of substations in the scenario config.\n"
    )

    OUT_REPORT_MD.write_text("".join(md_lines), encoding="utf-8")

    # ---- Terminal summary ----
    print("Wrote:", OUT_SUBSTATION)
    print("Wrote:", OUT_AGG)
    print("Wrote:", OUT_REPORT_JSON)
    print("Wrote:", OUT_REPORT_MD)
    print("\nCoverage:", report["coverage"])
    print("\nHourly heat_mwh stats:", report["stats"]["heat_mwh_hourly"])
    print("\nNext: we will download and stage the coal-fired CHP plant parameter dataset (Kazakhstan CHPP).")


if __name__ == "__main__":
    main()