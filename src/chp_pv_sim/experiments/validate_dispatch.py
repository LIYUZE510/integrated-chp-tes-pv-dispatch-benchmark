from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from chp_pv_sim.experiments.config import load_experiment_config


def _simple_validation(dispatch: pd.DataFrame, *, export_cap: float, s_max: float, residual_tol: float) -> dict:
    return {
        "heat_balance_residual_abs_max": float(dispatch["heat_balance_residual"].abs().max()),
        "elec_balance_residual_abs_max": float(dispatch["elec_balance_residual"].abs().max()),
        "export_max_mw": float(dispatch["grid_export_mw"].max()),
        "soc_max_mwh": float(max(dispatch["S_mwh"].max(), dispatch["S_next_mwh"].max())),
        "soc_min_mwh": float(min(dispatch["S_mwh"].min(), dispatch["S_next_mwh"].min())),
        "pass": bool(
            dispatch["heat_balance_residual"].abs().max() <= residual_tol
            and dispatch["elec_balance_residual"].abs().max() <= residual_tol
            and dispatch["grid_export_mw"].max() <= export_cap + residual_tol
            and min(dispatch["S_mwh"].min(), dispatch["S_next_mwh"].min()) >= -residual_tol
            and max(dispatch["S_mwh"].max(), dispatch["S_next_mwh"].max()) <= s_max + residual_tol
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Lightweight validator for an existing dispatch parquet file.")
    parser.add_argument("--config", required=True, help="The same YAML config used to generate this run.")
    parser.add_argument("--dispatch", required=True, help="Path to dispatch parquet file.")
    args = parser.parse_args()

    cfg = load_experiment_config(args.config)
    dispatch = pd.read_parquet(Path(args.dispatch))
    result = _simple_validation(
        dispatch,
        export_cap=float(cfg.grid.grid_export_cap_mw),
        s_max=float(cfg.storage.s_max_mwh),
        residual_tol=float(cfg.qc.residual_tol),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
