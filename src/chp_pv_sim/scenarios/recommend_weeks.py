from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from chp_pv_sim.paths import PROCESSED_DIR, REPORTS_DIR, ensure_dirs


IN_HEAT_DEMAND = PROCESSED_DIR / "xai4heat_heat_demand_substation_hourly.parquet"
DEFAULT_SUBSTATIONS = ["L4", "L17", "L12", "L22", "L8"]


def main() -> None:
    ensure_dirs()
    parser = argparse.ArgumentParser(
        description="List complete candidate weeks from the heat-demand dataset."
    )
    parser.add_argument("--substations", nargs="+", default=DEFAULT_SUBSTATIONS)
    parser.add_argument("--out", default=str(REPORTS_DIR / "candidate_weeks.csv"))
    parser.add_argument(
        "--start_after",
        default=None,
        help="Optional lower bound such as 2021-11-08 or 2022-01-01.",
    )
    parser.add_argument(
        "--end_before",
        default=None,
        help="Optional upper bound such as 2024-03-25.",
    )
    args = parser.parse_args()

    if not IN_HEAT_DEMAND.exists():
        raise FileNotFoundError(f"Missing heat-demand file: {IN_HEAT_DEMAND}")

    requested = [s.upper() for s in args.substations]

    df = pd.read_parquet(IN_HEAT_DEMAND)
    df["datetime_local"] = pd.to_datetime(df["datetime_local"], errors="raise")
    df["substation_id"] = df["substation_id"].astype("string").str.upper()
    df = df[df["substation_id"].isin(requested)].copy()
    if df.empty:
        raise ValueError("No rows found for the selected substations.")

    coverage = (
        df.groupby("substation_id")["datetime_local"]
        .agg(["min", "max", "count"])
        .sort_index()
    )
    missing_overall = [sid for sid in requested if sid not in coverage.index]
    if missing_overall:
        raise ValueError(
            f"Some requested substations are absent from the dataset: {missing_overall}"
        )

    common_start = coverage["min"].max()
    common_end = coverage["max"].min()

    if args.start_after is not None:
        common_start = max(common_start, pd.to_datetime(args.start_after))
    if args.end_before is not None:
        common_end = min(common_end, pd.to_datetime(args.end_before))

    if common_end < common_start:
        raise ValueError(
            f"No common coverage remains after filtering. start={common_start}, end={common_end}"
        )

    pivot = (
        df.pivot(index="datetime_local", columns="substation_id", values="heat_mwh")
        .sort_index()
        .reindex(columns=requested)
    )

    full_index = pd.date_range(common_start, common_end, freq="h")
    pivot = pivot.reindex(full_index)

    rows = []
    tmp = pivot.copy()
    tmp["week_start"] = tmp.index.to_period("W-SUN").start_time

    for week_start, group in tmp.groupby("week_start"):
        group = group.sort_index()
        heat_only = group[requested]
        if len(heat_only) != 168:
            continue
        if heat_only.isna().any().any():
            continue

        heat = heat_only.sum(axis=1).astype(float)
        rows.append(
            {
                "week_start": pd.Timestamp(week_start),
                "week_end": pd.Timestamp(week_start) + pd.Timedelta(hours=167),
                "hours": int(len(heat)),
                "mean_mw": float(heat.mean()),
                "std_mw": float(heat.std(ddof=0)),
                "p50_mw": float(heat.quantile(0.50)),
                "p90_mw": float(heat.quantile(0.90)),
                "p95_mw": float(heat.quantile(0.95)),
                "p99_mw": float(heat.quantile(0.99)),
                "max_mw": float(heat.max()),
                "max_over_p99": float(heat.max() / max(heat.quantile(0.99), 1e-9)),
                "n_substations": len(requested),
                "common_coverage_start": pd.Timestamp(common_start),
                "common_coverage_end": pd.Timestamp(common_end),
            }
        )

    out = pd.DataFrame(rows).sort_values("week_start").reset_index(drop=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"Wrote candidate weeks CSV: {out_path}")
    print(f"Requested substations: {requested}")
    print(f"Common coverage      : {common_start} -> {common_end}")
    if out.empty:
        print("No complete 168-hour weeks found under the current filters.")
    else:
        print(out.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
