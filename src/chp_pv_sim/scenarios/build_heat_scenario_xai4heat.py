from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from chp_pv_sim.paths import ROOT, PROCESSED_DIR, REPORTS_DIR, ensure_dirs


IN_HEAT_DEMAND = PROCESSED_DIR / "xai4heat_heat_demand_substation_hourly.parquet"
IN_TURB_HEAT_SEG = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_heat_segments_consistent.parquet"


@dataclass
class ScenarioMeta:
    name: str
    start: str
    end: str
    substations: list[str]
    quantile: float
    target_utilization: float
    h_max_mw: float
    raw_quantile_mw: float
    heat_scale: float
    pct_hours_over_capacity: float


def parse_dt(s: str, *, is_end: bool) -> pd.Timestamp:
    """
    Accepts:
      - YYYY-MM-DD
      - YYYY-MM-DD HH:MM
      - YYYY-MM-DD HH:MM:SS
    If date-only:
      - start -> 00:00:00
      - end   -> 23:00:00
    """
    ts = pd.to_datetime(s, errors="raise")
    if ts.hour == 0 and ts.minute == 0 and ts.second == 0 and len(s.strip()) <= 10:
        if is_end:
            ts = ts.replace(hour=23, minute=0, second=0)
    return ts


def _format_coverage_table(coverage: pd.DataFrame, substations: list[str]) -> str:
    lines: list[str] = []
    for sid in substations:
        if sid in coverage.index:
            row = coverage.loc[sid]
            lines.append(
                f"  - {sid}: {row['min']} -> {row['max']}  (rows={int(row['count'])})"
            )
        else:
            lines.append(f"  - {sid}: not present in dataset")
    return "\n".join(lines)


def main() -> None:
    ensure_dirs()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="scenario name, used as folder under data/scenarios/")
    ap.add_argument("--start", required=True, help="start datetime (YYYY-MM-DD or with time)")
    ap.add_argument("--end", required=True, help="end datetime (YYYY-MM-DD or with time), inclusive")
    ap.add_argument("--substations", nargs="+", default=["L4", "L17", "L12", "L22", "L8"])
    ap.add_argument("--quantile", type=float, default=0.99, help="quantile used for scaling (robust vs outliers)")
    ap.add_argument("--target_util", type=float, default=0.85, help="target utilization of CHP H_max at the chosen quantile")
    args = ap.parse_args()

    name = args.name.strip()
    start = parse_dt(args.start, is_end=False)
    end = parse_dt(args.end, is_end=True)
    if end < start:
        raise ValueError("end < start")

    substations = [s.strip().upper() for s in args.substations]
    q = float(args.quantile)
    target_util = float(args.target_util)

    if not (0.5 <= q < 1.0):
        raise ValueError("quantile must be in [0.5, 1.0)")
    if not (0.1 <= target_util <= 1.0):
        raise ValueError("target_util must be in [0.1, 1.0]")

    if not IN_HEAT_DEMAND.exists():
        raise FileNotFoundError(f"Missing: {IN_HEAT_DEMAND}. Run xai4heat_build_heat_demand first.")
    if not IN_TURB_HEAT_SEG.exists():
        raise FileNotFoundError(f"Missing: {IN_TURB_HEAT_SEG}. Run kaz_chpp_make_consistent_segments first.")

    # CHP heat capacity proxy from turbine segment table
    seg = pd.read_parquet(IN_TURB_HEAT_SEG)
    if "h_ub_eff" not in seg.columns:
        raise KeyError("turbine_heat_segments_consistent missing h_ub_eff")
    h_max = float(pd.to_numeric(seg["h_ub_eff"], errors="raise").max())

    df = pd.read_parquet(IN_HEAT_DEMAND)
    df["datetime_local"] = pd.to_datetime(df["datetime_local"], errors="raise")
    df["substation_id"] = df["substation_id"].astype("string").str.upper()

    df = df[df["substation_id"].isin(substations)].copy()
    if df.empty:
        raise ValueError(f"No rows found for substations={substations}")

    coverage = (
        df.groupby("substation_id")["datetime_local"]
        .agg(["min", "max", "count"])
        .sort_index()
    )
    missing_in_dataset = [sid for sid in substations if sid not in coverage.index]
    if missing_in_dataset:
        raise ValueError(
            "Some requested substations do not exist in the dataset.\n"
            f"Missing overall: {missing_in_dataset}\n"
            f"Coverage of requested substations:\n{_format_coverage_table(coverage, substations)}"
        )

    common_start = coverage["min"].max()
    common_end = coverage["max"].min()
    if end < common_start or start > common_end:
        raise ValueError(
            "Selected window lies outside the common coverage window of the requested substations.\n"
            f"Requested window: {start} -> {end}\n"
            f"Common coverage: {common_start} -> {common_end}\n"
            f"Per-substation coverage:\n{_format_coverage_table(coverage, substations)}\n"
            "Pick a week inside the common coverage window or use a different fixed substation set."
        )

    # window filter (inclusive end)
    df = df[(df["datetime_local"] >= start) & (df["datetime_local"] <= end)].copy()
    if df.empty:
        raise ValueError(f"No rows in window [{start}, {end}] for substations={substations}")

    # pivot heat
    if "heat_mwh" not in df.columns:
        raise KeyError("Expected column heat_mwh in xai4heat_heat_demand_substation_hourly.parquet")
    pivot = df.pivot(index="datetime_local", columns="substation_id", values="heat_mwh").sort_index()

    # expected full hourly index
    expected = pd.date_range(start, end, freq="h")

    # Force requested column order and explicit NaNs when a requested station is missing in the window.
    pivot = pivot.reindex(columns=substations)
    pivot = pivot.reindex(expected)

    # missing per substation or missing hours?
    na_counts = pivot[substations].isna().sum()
    if (na_counts > 0).any():
        bad = {k: int(v) for k, v in na_counts[na_counts > 0].to_dict().items()}
        raise ValueError(
            "The selected window does not contain a complete hourly record for every requested substation.\n"
            f"Requested window: {start} -> {end}\n"
            f"Missing hour counts by substation: {bad}\n"
            f"Common coverage of requested substations: {common_start} -> {common_end}\n"
            f"Per-substation coverage:\n{_format_coverage_table(coverage, substations)}\n"
            "Tip: rerun recommend_weeks after the patch; it will now only list weeks with full coverage for all requested substations."
        )

    # aggregated heat in MW (since 1h step: MWh/h == MW numerically)
    heat_raw = pivot.sum(axis=1).astype(float)

    raw_q = float(heat_raw.quantile(q))
    if raw_q <= 0:
        raise ValueError(f"raw_quantile at q={q} is non-positive ({raw_q}); cannot scale.")

    heat_scale = (target_util * h_max) / raw_q
    heat_scaled = heat_raw * heat_scale

    pct_over = float((heat_scaled > h_max).mean() * 100.0)

    # ambient temperature mean (optional, useful later)
    t_amb_mean = df.groupby("datetime_local")["t_amb"].mean().reindex(expected)

    out_dir = ROOT / "data" / "scenarios" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    out_heat = out_dir / "heat.parquet"
    out_manifest = out_dir / "manifest.json"

    out = pd.DataFrame(index=expected)
    out.index.name = "datetime_local"
    out["heat_demand_mw"] = heat_scaled
    out["heat_demand_raw_mw"] = heat_raw
    out["heat_scale"] = heat_scale
    out["t_amb_mean_c"] = t_amb_mean
    out["n_substations"] = len(substations)

    # also keep per-substation raw series (wide)
    for sid in substations:
        out[f"H_{sid}_raw_mw"] = pivot[sid].astype(float)

    out = out.reset_index()
    out.to_parquet(out_heat, index=False, engine="pyarrow", compression="zstd")

    meta = ScenarioMeta(
        name=name,
        start=str(start),
        end=str(end),
        substations=substations,
        quantile=q,
        target_utilization=target_util,
        h_max_mw=h_max,
        raw_quantile_mw=raw_q,
        heat_scale=float(heat_scale),
        pct_hours_over_capacity=pct_over,
    )

    payload: dict[str, Any] = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "inputs": {
            "xai4heat_heat_demand": str(IN_HEAT_DEMAND).replace("\\", "/"),
            "turbine_heat_segments_consistent": str(IN_TURB_HEAT_SEG).replace("\\", "/"),
        },
        "scenario": asdict(meta),
        "outputs": {"heat_parquet": str(out_heat).replace("\\", "/")},
        "coverage": {
            "common_start": str(common_start),
            "common_end": str(common_end),
        },
        "basic_stats": {
            "heat_demand_mw": {
                "min": float(out["heat_demand_mw"].min()),
                "p50": float(out["heat_demand_mw"].median()),
                "p99": float(out["heat_demand_mw"].quantile(0.99)),
                "max": float(out["heat_demand_mw"].max()),
            }
        },
    }

    out_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Wrote scenario heat:", out_heat)
    print("Wrote manifest     :", out_manifest)
    print("\n=== SCENARIO SUMMARY ===")
    print(json.dumps(asdict(meta), ensure_ascii=False, indent=2))
    print("\nScaled heat stats (MW):")
    print(out["heat_demand_mw"].describe(percentiles=[0.5, 0.9, 0.95, 0.99]).to_string())


if __name__ == "__main__":
    main()
