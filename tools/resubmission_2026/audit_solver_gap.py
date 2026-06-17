from __future__ import annotations

import contextlib
import io
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np
import pandas as pd
import pyomo
import pyomo.environ as pyo
from pyomo.opt import SolverFactory

try:
    import highspy
except Exception:  # pragma: no cover - the audit reports this explicitly.
    highspy = None

from chp_pv_sim.models.chp_week_storage_pv_grid_dispatch import _configure_highs_solver
from chp_pv_sim.models.solver_metrics import extract_solver_diagnostics


GAP_VALUES = (0.2, 0.02, 0.002)
TOY_TIME_LIMIT_S = 10.0

REPRESENTATIVE_FROZEN_FILES = {
    "uc_summary": ROOT
    / "data"
    / "scenarios"
    / "week_2023_dec01"
    / "results"
    / "dispatch_summary_pv_grid__uc_paper_retained_fw.json",
    "uc_windows": ROOT
    / "data"
    / "scenarios"
    / "week_2023_dec01"
    / "results"
    / "solver_windows_pv_grid__uc_paper_retained_fw.csv",
    "mpc_summary": ROOT
    / "data"
    / "scenarios"
    / "week_2023_dec01"
    / "results"
    / "dispatch_summary_pv_grid__mpc_paper_retained_fw.json",
    "mpc_windows": ROOT
    / "data"
    / "scenarios"
    / "week_2023_dec01"
    / "results"
    / "solver_windows_pv_grid__mpc_paper_retained_fw.csv",
}


def _finite_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except Exception:
        return None
    if math.isfinite(out):
        return out
    return None


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return str(value)
    if isinstance(value, Path):
        return str(value.relative_to(ROOT) if value.is_relative_to(ROOT) else value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    return str(value)


def _safe_attr(obj: Any, name: str) -> Any:
    try:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return _jsonable(value)
    except Exception as exc:
        return f"<error reading {name}: {exc!r}>"
    return None


def _get_option_value(highs_model: Any, option_name: str) -> dict[str, Any] | None:
    if highs_model is None or not hasattr(highs_model, "getOptionValue"):
        return None
    try:
        raw = highs_model.getOptionValue(option_name)
    except Exception as exc:
        return {"error": repr(exc)}
    if isinstance(raw, tuple) and len(raw) == 2:
        status, value = raw
        return {"status": str(status), "value": _jsonable(value), "raw": repr(raw)}
    return {"value": _jsonable(raw), "raw": repr(raw)}


def _option_dict(solver: Any, attr: str) -> dict[str, Any] | None:
    opts = getattr(solver, attr, None)
    if opts is None:
        return None
    try:
        return {str(k): _jsonable(v) for k, v in dict(opts).items()}
    except Exception as exc:
        return {"error": repr(exc)}


def _config_snapshot(solver: Any) -> dict[str, Any] | None:
    cfg = getattr(solver, "config", None)
    if cfg is None:
        return None
    fields = [
        "time_limit",
        "mip_rel_gap",
        "stream_solver",
        "load_solution",
        "warmstart",
        "relax_integrality",
    ]
    out: dict[str, Any] = {"class": type(cfg).__module__ + "." + type(cfg).__qualname__}
    for field in fields:
        value = _safe_attr(cfg, field)
        if value is not None:
            out[field] = value
    return out


def solver_option_snapshot(solver: Any) -> dict[str, Any]:
    highs_model = getattr(solver, "_solver_model", None)
    highs_option_names = [
        "mip_rel_gap",
        "time_limit",
        "output_flag",
        "threads",
        "parallel",
        "random_seed",
    ]
    return {
        "solver_class": type(solver).__module__ + "." + type(solver).__qualname__,
        "options": _option_dict(solver, "options"),
        "highs_options": _option_dict(solver, "highs_options"),
        "private_solver_options": _option_dict(solver, "_solver_options"),
        "config": _config_snapshot(solver),
        "underlying_model_class": (
            None if highs_model is None else type(highs_model).__module__ + "." + type(highs_model).__qualname__
        ),
        "underlying_highs_options": {
            name: _get_option_value(highs_model, name) for name in highs_option_names
        }
        if highs_model is not None
        else {},
    }


def set_deterministic_highs_options(solver: Any) -> None:
    for attr in ("options", "highs_options"):
        opts = getattr(solver, attr, None)
        if opts is None:
            continue
        opts["threads"] = 1
        opts["parallel"] = "off"
        opts["random_seed"] = 1


def build_toy_max_mip() -> pyo.ConcreteModel:
    """Small deterministic binary knapsack with a visible 20% gap-tolerance stop."""
    model = pyo.ConcreteModel("solver_gap_audit_toy_max_knapsack")
    model.I = pyo.RangeSet(0, 9)
    model.x = pyo.Var(model.I, domain=pyo.Binary)
    model.capacity = pyo.Constraint(expr=sum((i + 1) * model.x[i] for i in model.I) <= 23)
    model.obj = pyo.Objective(expr=sum((10 + i) * model.x[i] for i in model.I), sense=pyo.maximize)
    return model


def configure_highs(gap: float, *, output_flag: bool) -> Any:
    solver = SolverFactory("appsi_highs")
    _configure_highs_solver(
        solver,
        time_limit_s=TOY_TIME_LIMIT_S,
        mip_rel_gap=float(gap),
        output_flag=bool(output_flag),
    )
    set_deterministic_highs_options(solver)
    return solver


def environment_audit() -> dict[str, Any]:
    solver = SolverFactory("appsi_highs")
    version = None
    try:
        version = solver.version()
    except Exception as exc:
        version = f"<error: {exc!r}>"
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "pyomo": getattr(pyomo, "__version__", None),
        "highspy": {
            "module_version_attr": getattr(highspy, "__version__", None) if highspy is not None else None,
            "module_file": getattr(highspy, "__file__", None) if highspy is not None else None,
            "solver_reported_highs_version": _jsonable(version),
        },
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "appsi_highs": {
            "solver_factory_name": "appsi_highs",
            "available": solver.available(exception_flag=False),
            "solver_class": type(solver).__module__ + "." + type(solver).__qualname__,
            "config_class": (
                None
                if getattr(solver, "config", None) is None
                else type(solver.config).__module__ + "." + type(solver.config).__qualname__
            ),
            "initial_snapshot": solver_option_snapshot(solver),
        },
    }


def _result_section_attrs(section: Any) -> dict[str, Any]:
    names = [
        "status",
        "termination_condition",
        "termination_message",
        "message",
        "wallclock_time",
        "time",
        "lower_bound",
        "upper_bound",
        "sense",
        "gap",
        "relative_gap",
        "mip_gap",
        "best_feasible_objective",
        "best_objective_bound",
        "objective",
        "objective_bound",
    ]
    out: dict[str, Any] = {}
    for name in names:
        value = _safe_attr(section, name)
        if value is not None:
            out[name] = value
    return out


def raw_pyomo_result_fields(results: Any) -> dict[str, Any]:
    return {
        "results_class": type(results).__module__ + "." + type(results).__qualname__,
        "solver": _result_section_attrs(getattr(results, "solver", None)),
        "problem": _result_section_attrs(getattr(results, "problem", None)),
    }


def raw_highspy_fields(solver: Any) -> dict[str, Any]:
    highs_model = getattr(solver, "_solver_model", None)
    if highs_model is None:
        return {"available": False}

    info_fields = [
        "objective_function_value",
        "mip_dual_bound",
        "mip_gap",
        "mip_node_count",
        "simplex_iteration_count",
        "ipm_iteration_count",
        "primal_solution_status",
        "dual_solution_status",
    ]
    info_out: dict[str, Any] = {}
    try:
        info = highs_model.getInfo()
        for field in info_fields:
            if hasattr(info, field):
                info_out[field] = _jsonable(getattr(info, field))
    except Exception as exc:
        info_out["error"] = repr(exc)

    status = None
    try:
        status = str(highs_model.getModelStatus())
    except Exception as exc:
        status = f"<error: {exc!r}>"

    return {
        "available": True,
        "model_status": status,
        "info": info_out,
    }


def _problem_bound_fields(results: Any) -> tuple[float | None, float | None, str | None]:
    problem = getattr(results, "problem", None)
    lower = _finite_float(getattr(problem, "lower_bound", None))
    upper = _finite_float(getattr(problem, "upper_bound", None))
    sense_raw = getattr(problem, "sense", None)
    sense = None if sense_raw is None else str(sense_raw).lower()
    return lower, upper, sense


def interpret_pyomo_problem_bounds(results: Any, *, objective_value: float | None = None) -> dict[str, Any]:
    lower, upper, sense = _problem_bound_fields(results)
    incumbent = None
    best_bound = None
    if sense is not None and "maximize" in sense:
        incumbent = lower
        best_bound = upper
        convention = "maximize: Pyomo lower_bound is incumbent/primal; upper_bound is dual bound"
    elif sense is not None and "minimize" in sense:
        incumbent = upper
        best_bound = lower
        convention = "minimize: Pyomo upper_bound is incumbent/primal; lower_bound is dual bound"
    else:
        incumbent = _finite_float(objective_value)
        best_bound = None
        convention = "unknown sense: incumbent falls back to objective_value"

    gap = None
    if incumbent is not None and best_bound is not None:
        denom = max(1.0, abs(incumbent))
        gap = abs(best_bound - incumbent) / denom

    return {
        "sense": sense,
        "lower_bound": lower,
        "upper_bound": upper,
        "incumbent_objective": incumbent,
        "best_objective_bound": best_bound,
        "relative_gap_fraction_from_pyomo_bounds": gap,
        "convention": convention,
    }


def compare_solver_metrics_to_raw(
    diagnostics: dict[str, Any],
    highspy_fields: dict[str, Any],
    interpreted_pyomo: dict[str, Any],
) -> dict[str, Any]:
    info = highspy_fields.get("info", {})
    raw_incumbent = _finite_float(info.get("objective_function_value"))
    raw_bound = _finite_float(info.get("mip_dual_bound"))
    raw_gap = _finite_float(info.get("mip_gap"))
    interpreted_incumbent = _finite_float(interpreted_pyomo.get("incumbent_objective"))
    interpreted_bound = _finite_float(interpreted_pyomo.get("best_objective_bound"))

    diag_incumbent = _finite_float(diagnostics.get("best_feasible_objective"))
    diag_bound = _finite_float(diagnostics.get("best_objective_bound"))
    diag_gap = _finite_float(diagnostics.get("achieved_gap_rel"))

    def close(a: float | None, b: float | None, *, tol: float = 1e-9) -> bool:
        if a is None or b is None:
            return a is b
        return math.isclose(a, b, rel_tol=tol, abs_tol=tol)

    issues: list[str] = []
    if raw_incumbent is not None and not close(diag_incumbent, raw_incumbent):
        issues.append("solver_metrics best_feasible_objective does not match HiGHS incumbent objective")
    if raw_bound is not None and not close(diag_bound, raw_bound):
        issues.append("solver_metrics best_objective_bound does not match HiGHS dual/best bound")
    if raw_gap is not None and not close(diag_gap, raw_gap):
        issues.append("solver_metrics achieved_gap_rel does not match HiGHS mip_gap fraction")
    if interpreted_incumbent is not None and not close(diag_incumbent, interpreted_incumbent):
        issues.append("solver_metrics does not use Pyomo problem bounds according to objective sense")
    if interpreted_bound is not None and not close(diag_bound, interpreted_bound):
        issues.append("solver_metrics swaps or mislabels Pyomo problem incumbent/bound fields")

    return {
        "raw_highspy_incumbent_objective": raw_incumbent,
        "raw_highspy_best_bound": raw_bound,
        "raw_highspy_relative_gap_fraction": raw_gap,
        "solver_metrics_best_feasible_objective": diag_incumbent,
        "solver_metrics_best_objective_bound": diag_bound,
        "solver_metrics_achieved_gap_rel": diag_gap,
        "matches_highspy_incumbent": close(diag_incumbent, raw_incumbent),
        "matches_highspy_best_bound": close(diag_bound, raw_bound),
        "matches_highspy_gap": close(diag_gap, raw_gap),
        "issues": issues,
    }


def solve_toy_gap(gap: float) -> dict[str, Any]:
    model = build_toy_max_mip()
    solver = configure_highs(float(gap), output_flag=True)
    pre_solve_options = solver_option_snapshot(solver)

    log_buffer = io.StringIO()
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(log_buffer):
        results = solver.solve(model, tee=True)
    wallclock_s = time.perf_counter() - t0

    objective = _finite_float(pyo.value(model.obj))
    raw_pyomo = raw_pyomo_result_fields(results)
    raw_highs = raw_highspy_fields(solver)
    diagnostics = extract_solver_diagnostics(results, wallclock_s=wallclock_s, objective_value=objective)
    interpreted = interpret_pyomo_problem_bounds(results, objective_value=objective)
    comparison = compare_solver_metrics_to_raw(diagnostics, raw_highs, interpreted)

    info = raw_highs.get("info", {})
    return {
        "requested_mip_rel_gap": float(gap),
        "requested_gap_as_fraction": float(gap),
        "requested_gap_as_percent": float(gap) * 100.0,
        "termination_condition": raw_pyomo.get("solver", {}).get("termination_condition"),
        "solver_status": raw_pyomo.get("solver", {}).get("status"),
        "incumbent_objective": objective,
        "best_bound_from_highspy": _finite_float(info.get("mip_dual_bound")),
        "relative_gap_from_highspy_fraction": _finite_float(info.get("mip_gap")),
        "relative_gap_from_highspy_percent": (
            None if _finite_float(info.get("mip_gap")) is None else _finite_float(info.get("mip_gap")) * 100.0
        ),
        "runtime_wallclock_s": wallclock_s,
        "pre_solve_option_snapshot": pre_solve_options,
        "post_solve_option_snapshot": solver_option_snapshot(solver),
        "raw_pyomo_result_fields": raw_pyomo,
        "raw_highspy_fields": raw_highs,
        "captured_solver_log": log_buffer.getvalue(),
        "solver_metrics_extraction": diagnostics,
        "objective_sense_interpretation": interpreted,
        "solver_metrics_comparison": comparison,
    }


def option_propagation_audit() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for gap in GAP_VALUES:
        solver = configure_highs(float(gap), output_flag=True)
        out[str(gap)] = {
            "requested_mip_rel_gap": float(gap),
            "requested_gap_as_fraction": float(gap),
            "requested_gap_as_percent": float(gap) * 100.0,
            "after_configure_before_solve": solver_option_snapshot(solver),
        }
    return out


def toy_mip_audit() -> list[dict[str, Any]]:
    return [solve_toy_gap(gap) for gap in GAP_VALUES]


def _extract_solver_config(summary: dict[str, Any]) -> dict[str, Any]:
    config_solver = summary.get("config_used", {}).get("solver", {})
    scenario = summary.get("scenario", {})
    rolling = summary.get("rolling", {})
    return {
        "config_used_solver_mip_rel_gap": _finite_float(config_solver.get("mip_rel_gap")),
        "scenario_mip_rel_gap": _finite_float(scenario.get("mip_rel_gap")),
        "time_limit_s": _finite_float(config_solver.get("time_limit_s") or scenario.get("time_limit_s")),
        "time_limit_window_s": _finite_float(
            config_solver.get("time_limit_window_s")
            or summary.get("config_used", {}).get("rolling", {}).get("time_limit_window_s")
            or rolling.get("time_limit_window_s")
        ),
    }


def _stored_gap_formula(best_feasible: float | None, best_bound: float | None) -> float | None:
    if best_feasible is None or best_bound is None:
        return None
    return abs(best_feasible - best_bound) / max(1.0, abs(best_feasible))


def _correct_max_gap_formula(incumbent: float | None, dual_bound: float | None) -> float | None:
    if incumbent is None or dual_bound is None:
        return None
    return abs(dual_bound - incumbent) / max(1.0, abs(incumbent))


def audit_summary_file(path: Path) -> dict[str, Any]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    solver = summary.get("solver", {})
    windows = summary.get("windows", [])
    solver_config = _extract_solver_config(summary)

    configured_gap = (
        solver_config.get("config_used_solver_mip_rel_gap")
        if solver_config.get("config_used_solver_mip_rel_gap") is not None
        else solver_config.get("scenario_mip_rel_gap")
    )
    objective = _finite_float(
        solver.get("objective_profit_like")
        or solver.get("objective_implemented")
        or solver.get("objective_window_sum_profit_like")
    )
    best_feasible = _finite_float(solver.get("best_feasible_objective"))
    best_bound = _finite_float(solver.get("best_objective_bound"))
    achieved_gap = _finite_float(solver.get("achieved_gap_rel"))
    stored_formula = _stored_gap_formula(best_feasible, best_bound)
    correct_formula = _correct_max_gap_formula(best_bound, best_feasible)

    contradictions: list[str] = []
    if configured_gap is not None and achieved_gap is not None and achieved_gap > configured_gap:
        contradictions.append("stored achieved_gap_rel is greater than configured mip_rel_gap")
    if objective is not None and best_bound is not None and math.isclose(objective, best_bound, rel_tol=1e-9, abs_tol=1e-6):
        contradictions.append("stored best_objective_bound equals the incumbent objective")
    if objective is not None and best_feasible is not None and objective < 0 < best_feasible:
        contradictions.append("stored best_feasible_objective has opposite sign from the feasible incumbent objective")
    if achieved_gap is not None and stored_formula is not None and math.isclose(
        achieved_gap, stored_formula, rel_tol=1e-9, abs_tol=1e-9
    ):
        contradictions.append(
            "stored achieved_gap_rel matches abs(best_feasible_objective - best_objective_bound)"
            " / abs(best_feasible_objective), indicating swapped max-sense fields"
        )

    window_terms = []
    window_gap_values = []
    window_checks = []
    for window in windows:
        w_obj = _finite_float(window.get("objective_window"))
        w_best_feasible = _finite_float(window.get("best_feasible_objective"))
        w_best_bound = _finite_float(window.get("best_objective_bound"))
        w_gap = _finite_float(window.get("achieved_gap_rel"))
        w_formula = _stored_gap_formula(w_best_feasible, w_best_bound)
        w_correct = _correct_max_gap_formula(w_best_bound, w_best_feasible)
        if window.get("termination") is not None:
            window_terms.append(str(window.get("termination")))
        if w_gap is not None:
            window_gap_values.append(w_gap)
        if configured_gap is not None and w_gap is not None and w_gap > configured_gap:
            contradictions.append(f"window {window.get('window_id')} stored achieved_gap_rel is greater than configured mip_rel_gap")
        if w_obj is not None and w_best_bound is not None and math.isclose(
            w_obj, w_best_bound, rel_tol=1e-9, abs_tol=1e-6
        ):
            contradictions.append(f"window {window.get('window_id')} stored best_objective_bound equals objective_window")
        if w_obj is not None and w_best_feasible is not None and w_obj < 0 < w_best_feasible:
            contradictions.append(
                f"window {window.get('window_id')} stored best_feasible_objective has opposite sign from objective_window"
            )
        if w_gap is not None and w_formula is not None and math.isclose(w_gap, w_formula, rel_tol=1e-9, abs_tol=1e-9):
            contradictions.append(
                f"window {window.get('window_id')} stored achieved_gap_rel matches the swapped-field gap formula"
            )
        window_checks.append(
            {
                "window_id": window.get("window_id"),
                "termination": window.get("termination"),
                "objective_window": w_obj,
                "stored_achieved_gap_rel": w_gap,
                "stored_best_feasible_objective": w_best_feasible,
                "stored_best_objective_bound": w_best_bound,
                "stored_gap_formula_fraction": w_formula,
                "max_sense_gap_if_best_feasible_is_dual_bound_fraction": w_correct,
                "best_objective_bound_equals_objective": (
                    None
                    if w_obj is None or w_best_bound is None
                    else math.isclose(w_obj, w_best_bound, rel_tol=1e-9, abs_tol=1e-6)
                ),
                "best_feasible_opposite_sign_from_objective": (
                    None if w_obj is None or w_best_feasible is None else (w_obj < 0 < w_best_feasible)
                ),
            }
        )

    return {
        "path": path,
        "exists": path.exists(),
        "configured_target_gap_fraction": configured_gap,
        "configured_target_gap_percent": None if configured_gap is None else configured_gap * 100.0,
        "termination": solver.get("termination"),
        "window_termination_counts": solver.get("window_termination_counts"),
        "stored_achieved_gap_rel": achieved_gap,
        "stored_achieved_gap_percent_if_fraction": None if achieved_gap is None else achieved_gap * 100.0,
        "stored_gap_rel_max": solver.get("achieved_gap_rel_max"),
        "stored_gap_rel_mean": solver.get("achieved_gap_rel_mean"),
        "stored_incumbent_objective_profit_like": objective,
        "stored_best_feasible_objective": best_feasible,
        "stored_best_objective_bound": best_bound,
        "stored_gap_formula_fraction": stored_formula,
        "max_sense_gap_if_best_feasible_is_dual_bound_fraction": correct_formula,
        "window_terminations": sorted(set(window_terms)),
        "window_gap_min": min(window_gap_values) if window_gap_values else None,
        "window_gap_max": max(window_gap_values) if window_gap_values else None,
        "window_checks": window_checks,
        "contradictions": sorted(set(contradictions)),
    }


def audit_windows_file(path: Path) -> dict[str, Any]:
    df = pd.read_csv(path)
    numeric_cols = [
        "objective_window",
        "achieved_gap_rel",
        "best_feasible_objective",
        "best_objective_bound",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    checks = []
    if {"objective_window", "best_feasible_objective", "best_objective_bound", "achieved_gap_rel"}.issubset(df.columns):
        for row in df.itertuples(index=False):
            obj = _finite_float(getattr(row, "objective_window"))
            best_feasible = _finite_float(getattr(row, "best_feasible_objective"))
            best_bound = _finite_float(getattr(row, "best_objective_bound"))
            gap = _finite_float(getattr(row, "achieved_gap_rel"))
            checks.append(
                {
                    "window_id": getattr(row, "window_id", None),
                    "objective_window": obj,
                    "stored_achieved_gap_rel": gap,
                    "stored_best_feasible_objective": best_feasible,
                    "stored_best_objective_bound": best_bound,
                    "stored_gap_formula_fraction": _stored_gap_formula(best_feasible, best_bound),
                    "max_sense_gap_if_best_feasible_is_dual_bound_fraction": _correct_max_gap_formula(
                        best_bound, best_feasible
                    ),
                    "best_objective_bound_equals_objective": (
                        None
                        if obj is None or best_bound is None
                        else math.isclose(obj, best_bound, rel_tol=1e-9, abs_tol=1e-6)
                    ),
                    "best_feasible_opposite_sign_from_objective": (
                        None if obj is None or best_feasible is None else (obj < 0 < best_feasible)
                    ),
                }
            )

    return {
        "path": path,
        "exists": path.exists(),
        "row_count": int(len(df)),
        "terminations": sorted(map(str, df["termination"].dropna().unique().tolist()))
        if "termination" in df.columns
        else [],
        "achieved_gap_rel_min": _finite_float(df["achieved_gap_rel"].min()) if "achieved_gap_rel" in df.columns else None,
        "achieved_gap_rel_max": _finite_float(df["achieved_gap_rel"].max()) if "achieved_gap_rel" in df.columns else None,
        "checks": checks,
    }


def audit_frozen_outputs(paths: dict[str, Path] = REPRESENTATIVE_FROZEN_FILES) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, path in paths.items():
        if not path.exists():
            out[label] = {"path": path, "exists": False}
        elif path.suffix.lower() == ".json":
            out[label] = audit_summary_file(path)
        elif path.suffix.lower() == ".csv":
            out[label] = audit_windows_file(path)
        else:
            out[label] = {"path": path, "exists": True, "skipped": "unsupported suffix"}
    return out


def build_audit() -> dict[str, Any]:
    toy = toy_mip_audit()
    propagation = option_propagation_audit()
    for toy_entry in toy:
        propagation[str(toy_entry["requested_mip_rel_gap"])]["after_toy_solve"] = toy_entry[
            "post_solve_option_snapshot"
        ]

    return {
        "audit_scope": {
            "local_only": True,
            "production_model_modified": False,
            "experiment_yaml_modified": False,
            "frozen_outputs_modified": False,
            "uc_or_mpc_optimization_run": False,
            "toy_mip_only": True,
        },
        "environment": environment_audit(),
        "solver_option_propagation": propagation,
        "toy_mip": toy,
        "frozen_result_read_only_audit": audit_frozen_outputs(),
        "confirmed_interpretation": {
            "mip_rel_gap_units": "fraction",
            "examples": {
                "0.2": "20%",
                "0.02": "2%",
                "0.002": "0.2%",
            },
            "basis": "HiGHS getOptionValue('mip_rel_gap') stores the numeric fraction, and solver logs print tolerances of 20%, 2%, and 0.2% respectively.",
        },
        "solver_metrics_assessment": {
            "current_extractor_is_correct_for_max_sense_bounds": False,
            "details": (
                "For Pyomo appsi_highs maximization results, problem.lower_bound is the incumbent/primal "
                "objective and problem.upper_bound is the dual/best bound. solver_metrics.py currently "
                "checks upper_bound as best_feasible_objective and lower_bound as best_objective_bound, "
                "so max-sense bounds are swapped and achieved_gap_rel uses the wrong denominator."
            ),
        },
        "minimum_recommended_production_fix_not_applied": [
            "Change production configs that intend 0.2% from mip_rel_gap: 0.2 to mip_rel_gap: 0.002.",
            "Update solver diagnostics to interpret Pyomo problem lower/upper bounds by objective sense, or pass the solver object/highspy info into extraction and store HiGHS mip_gap directly.",
            "Preserve existing frozen outputs; regenerate only under new resub_2026_* tags after review.",
        ],
    }


def main() -> None:
    print(json.dumps(_jsonable(build_audit()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
