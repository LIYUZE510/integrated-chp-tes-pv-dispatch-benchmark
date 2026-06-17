from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pyomo.environ as pyo

from chp_pv_sim.experiments.config import load_experiment_config
from chp_pv_sim.experiments.engine import (
    _build_meta,
    _configure_highs_solver,
    _resolve_uc_terminal_target,
    load_scenario_inputs,
)
from chp_pv_sim.models.chp_week_storage_pv_grid_dispatch import build_model, load_segments
from chp_pv_sim.paths import ROOT


SCENARIO = "week_2023_dec01_anchor24h_fw"
TAGS_BY_LIMIT = {
    60: "resub_2026_budget_uc_anchor24h_gap0p002_t60",
    300: "resub_2026_budget_uc_anchor24h_gap0p002_t300",
    900: "resub_2026_budget_uc_anchor24h_gap0p002_t900",
}


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _summary_path(tag: str) -> Path:
    return ROOT / "data" / "scenarios" / SCENARIO / "results" / f"dispatch_summary_pv_grid__{tag}.json"


def _dispatch_path(tag: str) -> Path:
    return ROOT / "data" / "scenarios" / SCENARIO / "results" / f"dispatch_chp_storage_pv_grid__{tag}.parquet"


def _validation_path(tag: str) -> Path:
    return ROOT / "data" / "scenarios" / SCENARIO / "results" / f"dispatch_validation_pv_grid__{tag}.json"


def _config_path(seconds: int) -> Path:
    return (
        ROOT
        / "configs"
        / "experiments"
        / "resubmission_2026"
        / "solver_budget"
        / f"resub_2026_budget_uc_anchor24h_gap0p002_t{seconds}.yaml"
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reconstruct_components(dispatch: pd.DataFrame, config_used: dict[str, Any]) -> dict[str, float]:
    grid = config_used["grid"]
    cost = config_used["cost"]
    commitment = config_used["commitment"]

    export_revenue = float(grid["price_sell"]) * float(dispatch["grid_export_mw"].sum())
    import_cost = float(grid["price_buy"]) * float(dispatch["grid_import_mw"].sum())
    chp_cost = float(cost["cost_q"]) * float(dispatch["Q_in_mw"].sum())
    boiler_cost = float(cost["cost_boiler"]) * float(dispatch["boiler_mw"].sum())
    dump_penalty_cost = float(cost["cost_dump"]) * float(dispatch["dump_mw"].sum())
    under_penalty_cost = float(cost["penalty_under"]) * float(dispatch["under_mw"].sum())
    storage_cycling_cost = float(cost["cycle_cost"]) * float((dispatch["ch_mw"] + dispatch["dis_mw"]).sum())
    pv_curtailment_penalty_cost = float(grid["penalty_pv_curt"]) * float(dispatch["pv_curt_mw"].sum())
    chp_curtailment_penalty_cost = float(grid["penalty_chp_curt"]) * float(dispatch["chp_curt_mw"].sum())
    startup_cost = float(commitment["startup_cost"]) * float(dispatch["start"].sum())
    shutdown_cost = float(commitment["shutdown_cost"]) * float(dispatch["stop"].sum())

    profit_objective = (
        export_revenue
        - import_cost
        - chp_cost
        - boiler_cost
        - dump_penalty_cost
        - under_penalty_cost
        - storage_cycling_cost
        - pv_curtailment_penalty_cost
        - chp_curtailment_penalty_cost
        - startup_cost
        - shutdown_cost
    )

    return {
        "export_revenue": export_revenue,
        "import_cost": import_cost,
        "chp_cost": chp_cost,
        "boiler_cost": boiler_cost,
        "dump_penalty_cost": dump_penalty_cost,
        "under_penalty_cost": under_penalty_cost,
        "storage_cycling_cost": storage_cycling_cost,
        "pv_curtailment_penalty_cost": pv_curtailment_penalty_cost,
        "chp_curtailment_penalty_cost": chp_curtailment_penalty_cost,
        "startup_cost": startup_cost,
        "shutdown_cost": shutdown_cost,
        "profit_objective_reconstructed": profit_objective,
        "system_cost_reconstructed": -profit_objective,
    }


def reconstruct_budget_runs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seconds, tag in TAGS_BY_LIMIT.items():
        summary = _load_json(_summary_path(tag))
        validation = _load_json(_validation_path(tag))
        dispatch = pd.read_parquet(_dispatch_path(tag))
        components = reconstruct_components(dispatch, summary["config_used"])
        solver = summary["solver"]
        economics = summary["economics_realized"]

        rows.append(
            {
                "seconds": seconds,
                "tag": tag,
                **components,
                "summary_objective_profit_like": _finite_float(solver.get("objective_profit_like")),
                "summary_system_cost_equivalent": _finite_float(solver.get("objective_system_cost_equivalent")),
                "economics_profit_objective_realized": _finite_float(economics.get("profit_objective_realized")),
                "economics_system_cost_realized": _finite_float(economics.get("system_cost_realized")),
                "reconstruction_minus_summary_profit": (
                    components["profit_objective_reconstructed"] - float(solver["objective_profit_like"])
                ),
                "reconstruction_minus_economics_profit": (
                    components["profit_objective_reconstructed"] - float(economics["profit_objective_realized"])
                ),
                "incumbent_objective": _finite_float(solver.get("incumbent_objective")),
                "best_bound_objective": _finite_float(solver.get("best_bound_objective")),
                "achieved_gap_rel_fraction": _finite_float(solver.get("achieved_gap_rel_fraction")),
                "validation_pass": bool(validation.get("pass")),
            }
        )
    return rows


def inspect_model_constants() -> dict[str, Any]:
    heat_seg, power_seg, temps = load_segments()
    h_max = float(heat_seg["h_ub_eff"].max())
    e_max = float(power_seg["e_ub_eff"].max())
    q_max = float(max(heat_seg["q_ub_eff"].max(), power_seg["q_ub_eff"].max()))

    return {
        "temperature_modes": list(temps),
        "heat_segment_count": int(len(heat_seg)),
        "power_segment_count": int(len(power_seg)),
        "heat_segments_by_temp": {
            str(k): int(v) for k, v in heat_seg.groupby("temp_label")["segment"].count().to_dict().items()
        },
        "power_segments_by_temp": {
            str(k): int(v) for k, v in power_seg.groupby("temp_label")["segment"].count().to_dict().items()
        },
        "H_max": h_max,
        "E_max": e_max,
        "Q_max": q_max,
        "M_H": h_max,
        "M_E": e_max,
        "M_Q": q_max,
        "M_eq_H": h_max + 50.0,
        "M_eq_E": e_max + 50.0,
        "heat_bounds": {
            "h_lb_min": float(heat_seg["h_lb_eff"].min()),
            "h_ub_max": h_max,
            "q_lb_min": float(heat_seg["q_lb_eff"].min()),
            "q_ub_max": float(heat_seg["q_ub_eff"].max()),
        },
        "power_bounds": {
            "e_lb_min": float(power_seg["e_lb_eff"].min()),
            "e_ub_max": e_max,
            "q_lb_min": float(power_seg["q_lb_eff"].min()),
            "q_ub_max": float(power_seg["q_ub_eff"].max()),
        },
    }


def build_uc_model_from_config(config_path: Path) -> pyo.ConcreteModel:
    cfg = load_experiment_config(config_path)
    inputs = load_scenario_inputs(cfg)
    heat_seg, power_seg, temps = load_segments()
    terminal_target = _resolve_uc_terminal_target(cfg)
    meta = _build_meta(
        cfg,
        n_hours=len(inputs.dt_index),
        s_init_mwh=float(cfg.storage.s_init_mwh),
        on_init=int(cfg.commitment.on_init),
        time_limit_s=float(cfg.solver.time_limit_s),
        terminal_soc_target_mwh=terminal_target,
    )
    return build_model(
        inputs.dt_index,
        inputs.heat_demand_mw,
        inputs.pv_avail_mw,
        inputs.e_load_mw,
        heat_seg,
        power_seg,
        temps,
        meta,
    )


def variable_bound_audit(model: pyo.ConcreteModel) -> dict[str, Any]:
    by_component: dict[str, dict[str, Any]] = {}
    for var_component in model.component_objects(pyo.Var, active=True):
        missing_lb = 0
        missing_ub = 0
        count = 0
        binary = 0
        integer = 0
        for data in var_component.values():
            count += 1
            if data.lb is None:
                missing_lb += 1
            if data.ub is None:
                missing_ub += 1
            if data.is_binary():
                binary += 1
            elif data.is_integer():
                integer += 1
        by_component[var_component.local_name] = {
            "count": count,
            "binary": binary,
            "integer": integer,
            "missing_lb": missing_lb,
            "missing_ub": missing_ub,
        }
    return by_component


def relax_integer_variables(model: pyo.ConcreteModel) -> dict[str, int]:
    relaxed_binary = 0
    relaxed_integer = 0
    for var_data in model.component_data_objects(pyo.Var, descend_into=True):
        if var_data.is_binary():
            var_data.domain = pyo.UnitInterval
            relaxed_binary += 1
        elif var_data.is_integer():
            var_data.domain = pyo.Reals
            relaxed_integer += 1
    return {"relaxed_binary": relaxed_binary, "relaxed_integer": relaxed_integer}


def solve_lp_relaxation(time_limit_s: float) -> dict[str, Any]:
    model = build_uc_model_from_config(_config_path(900))
    before_bounds = variable_bound_audit(model)
    relaxed = relax_integer_variables(model)
    solver = pyo.SolverFactory("appsi_highs")
    solver = _configure_highs_solver(solver, time_limit_s=time_limit_s, mip_rel_gap=0.0, output_flag=False)

    t0 = time.perf_counter()
    results = solver.solve(model, tee=False)
    wallclock_s = time.perf_counter() - t0

    return {
        "status": str(getattr(results.solver, "status", None)),
        "termination": str(getattr(results.solver, "termination_condition", None)),
        "wallclock_s": wallclock_s,
        "objective_sense": "maximize",
        "lp_relaxation_objective": float(pyo.value(model.obj)),
        **relaxed,
        "model_variable_count": int(model.nvariables()),
        "model_constraint_count": int(model.nconstraints()),
        "variable_bound_audit_before_relaxation": before_bounds,
    }


def build_audit(include_lp: bool, lp_time_limit_s: float) -> dict[str, Any]:
    out = {
        "budget_run_reconstruction": reconstruct_budget_runs(),
        "model_constants": inspect_model_constants(),
    }
    if include_lp:
        out["lp_relaxation"] = solve_lp_relaxation(lp_time_limit_s)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit objective reconstruction and LP relaxation for the 24h budget runs.")
    parser.add_argument("--skip-lp", action="store_true", help="Only reconstruct existing results; do not solve the LP relaxation.")
    parser.add_argument("--lp-time-limit-s", type=float, default=120.0, help="LP relaxation solver time limit in seconds.")
    args = parser.parse_args()
    print(json.dumps(build_audit(not args.skip_lp, float(args.lp_time_limit_s)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
