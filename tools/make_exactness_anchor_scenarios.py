from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def _best_window_start(values: np.ndarray, window: int) -> int:
    if len(values) < window:
        raise ValueError(f"Series length {len(values)} is smaller than requested window {window}.")
    kernel = np.ones(window, dtype=float)
    sums = np.convolve(values.astype(float), kernel, mode="valid")
    return int(np.argmax(sums))


def _write_scenario(dst_dir: Path, heat_df: pd.DataFrame, pv_df: pd.DataFrame, manifest: dict) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    heat_df.to_parquet(dst_dir / "heat.parquet", index=False)
    pv_df.to_parquet(dst_dir / "pv.parquet", index=False)
    (dst_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create 24h and 48h exactness-anchor scenarios from an existing weekly scenario.")
    parser.add_argument("--src-scenario", default="week_2023_dec01", help="Source weekly scenario name.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing anchor scenarios if present.")
    args = parser.parse_args()

    src_dir = ROOT / "data" / "scenarios" / args.src_scenario
    heat_path = src_dir / "heat.parquet"
    pv_path = src_dir / "pv.parquet"

    if not heat_path.exists():
        raise FileNotFoundError(f"Missing heat scenario file: {heat_path}")
    if not pv_path.exists():
        raise FileNotFoundError(f"Missing PV scenario file: {pv_path}")

    heat_df = pd.read_parquet(heat_path).copy()
    pv_df = pd.read_parquet(pv_path).copy()

    heat_df["datetime_local"] = pd.to_datetime(heat_df["datetime_local"], errors="raise")
    pv_df["datetime_local"] = pd.to_datetime(pv_df["datetime_local"], errors="raise")

    heat_df = heat_df.sort_values("datetime_local").reset_index(drop=True)
    pv_df = pv_df.sort_values("datetime_local").reset_index(drop=True)

    if not heat_df["datetime_local"].equals(pv_df["datetime_local"]):
        raise ValueError("Heat and PV timestamps do not align exactly in the source scenario.")

    demand = pd.to_numeric(heat_df["heat_demand_mw"], errors="raise").astype(float).to_numpy()

    anchor_defs = [
        (24, f"{args.src_scenario}_anchor24h_fw"),
        (48, f"{args.src_scenario}_anchor48h_fw"),
    ]

    for horizon_h, dst_name in anchor_defs:
        start_idx = _best_window_start(demand, horizon_h)
        end_idx = start_idx + horizon_h

        heat_sub = heat_df.iloc[start_idx:end_idx].copy().reset_index(drop=True)
        pv_sub = pv_df.iloc[start_idx:end_idx].copy().reset_index(drop=True)

        dst_dir = ROOT / "data" / "scenarios" / dst_name
        if dst_dir.exists() and not args.overwrite:
            raise FileExistsError(
                f"Scenario already exists: {dst_dir}\n"
                "Use --overwrite to replace it."
            )

        manifest = {
            "scenario_name": dst_name,
            "derived_from": args.src_scenario,
            "selection_rule": f"highest total heat demand over {horizon_h} consecutive hours",
            "horizon_hours": horizon_h,
            "start_datetime_local": str(heat_sub["datetime_local"].iloc[0]),
            "end_datetime_local": str(heat_sub["datetime_local"].iloc[-1]),
            "n_rows": int(len(heat_sub)),
        }

        _write_scenario(dst_dir, heat_sub, pv_sub, manifest)

        print(f"[OK] Wrote: {dst_dir}")
        print(f"     Horizon : {horizon_h} h")
        print(f"     Start   : {heat_sub['datetime_local'].iloc[0]}")
        print(f"     End     : {heat_sub['datetime_local'].iloc[-1]}")
        print(f"     Heat sum: {heat_sub['heat_demand_mw'].astype(float).sum():.3f} MWh")


if __name__ == "__main__":
    main()