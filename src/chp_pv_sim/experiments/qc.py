from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from chp_pv_sim.experiments.config import ExperimentConfig, QCSection


def build_validation_report(
    dispatch: pd.DataFrame,
    *,
    cfg: ExperimentConfig,
    qc: QCSection,
    expected_terminal_soc: float | None,
) -> dict[str, Any]:
    tol = float(qc.residual_tol)
    bound_tol = float(qc.bound_tol)
    overlap_tol = float(qc.overlap_tol_mw)

    negative_cols = [
        "H_chp_mw",
        "E_chp_mw",
        "Q_in_mw",
        "boiler_mw",
        "dump_mw",
        "under_mw",
        "ch_mw",
        "dis_mw",
        "S_mwh",
        "S_next_mwh",
        "grid_import_mw",
        "grid_export_mw",
        "pv_curt_mw",
        "chp_curt_mw",
    ]

    negatives = {}
    for col in negative_cols:
        if col in dispatch.columns:
            min_val = float(dispatch[col].min())
            if min_val < -bound_tol:
                negatives[col] = min_val

    heat_resid_max = float(np.max(np.abs(dispatch["heat_balance_residual"]))) if len(dispatch) else 0.0
    elec_resid_max = float(np.max(np.abs(dispatch["elec_balance_residual"]))) if len(dispatch) else 0.0
    export_max = float(dispatch["grid_export_mw"].max()) if len(dispatch) else 0.0
    soc_min = float(min(dispatch["S_mwh"].min(), dispatch["S_next_mwh"].min())) if len(dispatch) else 0.0
    soc_max = float(max(dispatch["S_mwh"].max(), dispatch["S_next_mwh"].max())) if len(dispatch) else 0.0
    overlap_max = float(np.minimum(dispatch["grid_import_mw"], dispatch["grid_export_mw"]).max()) if len(dispatch) else 0.0

    terminal_soc = float(dispatch["S_next_mwh"].iloc[-1]) if len(dispatch) else None
    terminal_gap = None if expected_terminal_soc is None or terminal_soc is None else float(terminal_soc - expected_terminal_soc)

    issues: list[str] = []
    if heat_resid_max > tol:
        issues.append(f"Heat balance residual too large: {heat_resid_max:.6g} > {tol:.6g}")
    if elec_resid_max > tol:
        issues.append(f"Electric balance residual too large: {elec_resid_max:.6g} > {tol:.6g}")
    if export_max > float(cfg.grid.grid_export_cap_mw) + bound_tol:
        issues.append(
            "Grid export exceeds cap: "
            f"{export_max:.6g} > {float(cfg.grid.grid_export_cap_mw) + bound_tol:.6g}"
        )
    if soc_min < -bound_tol:
        issues.append(f"Storage SOC below zero: {soc_min:.6g}")
    if soc_max > float(cfg.storage.s_max_mwh) + bound_tol:
        issues.append(
            "Storage SOC exceeds upper bound: "
            f"{soc_max:.6g} > {float(cfg.storage.s_max_mwh) + bound_tol:.6g}"
        )
    if overlap_max > overlap_tol:
        issues.append(
            "Import/export overlap larger than tolerance: "
            f"{overlap_max:.6g} > {overlap_tol:.6g}"
        )
    if negatives:
        issues.append(f"Negative values found in non-negative columns: {negatives}")
    if terminal_gap is not None and abs(terminal_gap) > bound_tol:
        issues.append(
            "Terminal SOC mismatch: "
            f"{terminal_gap:.6g} away from target {expected_terminal_soc:.6g}"
        )

    return {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "pass": len(issues) == 0,
        "issues": issues,
        "thresholds": {
            "residual_tol": tol,
            "bound_tol": bound_tol,
            "overlap_tol_mw": overlap_tol,
        },
        "metrics": {
            "heat_balance_residual_abs_max": heat_resid_max,
            "elec_balance_residual_abs_max": elec_resid_max,
            "grid_export_max_mw": export_max,
            "soc_min_mwh": soc_min,
            "soc_max_mwh": soc_max,
            "import_export_overlap_max_mw": overlap_max,
            "terminal_soc_mwh": terminal_soc,
            "expected_terminal_soc_mwh": expected_terminal_soc,
            "terminal_soc_gap_mwh": terminal_gap,
            "negative_nonnegative_columns": negatives,
        },
    }


def summary_row(summary: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    method = summary.get("method", "full_horizon_uc")
    if method == "rolling_horizon_mpc":
        achieved_gap = summary.get("solver", {}).get("achieved_gap_rel_max")
        wallclock = summary.get("solver", {}).get("wallclock_s_total")
    else:
        achieved_gap = summary.get("solver", {}).get("achieved_gap_rel")
        wallclock = summary.get("solver", {}).get("wallclock_s")

    totals = summary.get("totals", {})
    economics = summary.get("economics_realized", {})
    heat_total = float(totals.get("heat_demand_mwh", 0.0) or 0.0)
    boiler = float(totals.get("boiler_mwh", 0.0) or 0.0)
    dump = float(totals.get("dump_mwh", 0.0) or 0.0)
    chp_e_total = float(totals.get("E_chp_mwh", 0.0) or 0.0)
    chp_e_curt = float(totals.get("E_chp_curt_mwh", 0.0) or 0.0)

    return {
        "scenario": summary.get("scenario", {}).get("scenario"),
        "method": method,
        "tag": summary.get("tag"),
        "system_cost_realized": economics.get("system_cost_realized"),
        "profit_objective_realized": economics.get("profit_objective_realized"),
        "boiler_share_pct": (100.0 * boiler / heat_total if heat_total > 0 else None),
        "dump_share_pct": (100.0 * dump / heat_total if heat_total > 0 else None),
        "chp_curtailment_ratio_pct": (100.0 * chp_e_curt / chp_e_total if chp_e_total > 0 else None),
        "grid_export_mwh": totals.get("grid_export_mwh"),
        "grid_import_mwh": totals.get("grid_import_mwh"),
        "solver_gap": achieved_gap,
        "wallclock_s": wallclock,
        "validation_pass": validation.get("pass"),
    }
