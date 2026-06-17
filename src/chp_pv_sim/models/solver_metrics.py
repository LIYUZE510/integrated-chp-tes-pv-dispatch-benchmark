from __future__ import annotations

import math
from typing import Any


GAP_FALLBACK_FORMULA = (
    "abs(best_bound_objective - incumbent_objective) / "
    "max(1.0, abs(incumbent_objective))"
)


def _to_float_or_none(x: Any) -> float | None:
    try:
        if x is None:
            return None
        v = float(x)
        if math.isfinite(v):
            return v
    except Exception:
        return None
    return None


def _finite_nonnegative_or_none(x: Any) -> float | None:
    value = _to_float_or_none(x)
    if value is None or value < 0.0:
        return None
    return value


def _first_attr(obj: Any, names: list[str]) -> float | None:
    for name in names:
        try:
            if hasattr(obj, name):
                v = _to_float_or_none(getattr(obj, name))
                if v is not None:
                    return v
        except Exception:
            pass
    return None


def _first_nested_attr(objs: list[Any], names: list[str]) -> float | None:
    for obj in objs:
        if obj is None:
            continue
        v = _first_attr(obj, names)
        if v is not None:
            return v
    return None


def _first_str_attr(objs: list[Any], names: list[str]) -> str | None:
    for obj in objs:
        if obj is None:
            continue
        for name in names:
            try:
                if hasattr(obj, name):
                    value = getattr(obj, name)
                    if value is not None:
                        return str(value)
            except Exception:
                pass
    return None


def normalize_objective_sense(objective_sense: Any) -> str | None:
    """
    Return 'maximize', 'minimize', or None.

    Numeric handling here is only for Pyomo's objective-sense convention
    (maximize=-1, minimize=1); this function never infers sense from the
    sign of an objective value.
    """
    if objective_sense is None:
        return None
    if isinstance(objective_sense, (int, float)) and math.isfinite(float(objective_sense)):
        if float(objective_sense) < 0:
            return "maximize"
        if float(objective_sense) > 0:
            return "minimize"
    text = str(objective_sense).strip().lower()
    if "max" in text or text == "-1":
        return "maximize"
    if "min" in text or text == "1":
        return "minimize"
    return None


def _problem_objective_sense(problem_obj: Any) -> str | None:
    try:
        if problem_obj is not None and hasattr(problem_obj, "sense"):
            return normalize_objective_sense(getattr(problem_obj, "sense"))
    except Exception:
        return None
    return None


def _pyomo_problem_bounds(problem_obj: Any, objective_sense: str | None) -> tuple[float | None, float | None]:
    lower_bound = _first_attr(problem_obj, ["lower_bound"])
    upper_bound = _first_attr(problem_obj, ["upper_bound"])
    if objective_sense == "maximize":
        return lower_bound, upper_bound
    if objective_sense == "minimize":
        return upper_bound, lower_bound
    return None, None


def _fallback_gap_fraction(incumbent: float | None, best_bound: float | None) -> float | None:
    if incumbent is None or best_bound is None:
        return None
    denominator = max(1.0, abs(float(incumbent)))
    gap = abs(float(best_bound) - float(incumbent)) / denominator
    if math.isfinite(gap):
        return gap
    return None


def _get_highs_model(solver: Any | None) -> Any | None:
    if solver is None:
        return None
    if hasattr(solver, "getInfo"):
        return solver
    for attr in ("_solver_model", "_highs", "highs"):
        try:
            candidate = getattr(solver, attr, None)
            if candidate is not None and hasattr(candidate, "getInfo"):
                return candidate
        except Exception:
            pass
    return None


def _highs_info_fields(solver: Any | None) -> dict[str, float | None]:
    highs_model = _get_highs_model(solver)
    if highs_model is None:
        return {}
    try:
        info = highs_model.getInfo()
    except Exception:
        return {}
    fields = {
        "objective_function_value": None,
        "mip_dual_bound": None,
        "mip_gap": None,
    }
    for name in fields:
        try:
            if hasattr(info, name):
                fields[name] = _to_float_or_none(getattr(info, name))
        except Exception:
            pass
    return fields


def _active_model_objective_sense(model: Any | None) -> str | None:
    if model is None:
        return None
    try:
        import pyomo.environ as pyo

        active = list(model.component_data_objects(pyo.Objective, active=True))
        if active:
            return normalize_objective_sense(active[0].sense)
    except Exception:
        pass
    return None


def extract_solver_diagnostics(
    results: Any,
    *,
    wallclock_s: float | None = None,
    objective_value: float | None = None,
    objective_sense: Any | None = None,
    requested_gap_rel_fraction: float | None = None,
    solver: Any | None = None,
    model: Any | None = None,
) -> dict[str, Any]:
    """
    Extract JSON-safe solver diagnostics with explicit gap units.

    Relative gaps are fractions. For example:
      - 0.2 is 20%
      - 0.02 is 2%
      - 0.002 is 0.2%

    Preferred source for HiGHS/APPSI is highspy's raw MIP info:
    objective_function_value, mip_dual_bound, and mip_gap. If that is not
    available, Pyomo problem lower/upper bounds are interpreted by objective
    sense. For fallback gap computation the formula is:
    abs(best_bound_objective - incumbent_objective) /
    max(1.0, abs(incumbent_objective)).

    Legacy keys are preserved as aliases:
      - achieved_gap_rel == achieved_gap_rel_fraction
      - best_feasible_objective == incumbent_objective
      - best_objective_bound == best_bound_objective
    """
    solver_obj = getattr(results, "solver", None)
    problem_obj = getattr(results, "problem", None)
    search_space = [results, solver_obj, problem_obj]

    status = _first_str_attr(search_space, ["status"])
    termination = _first_str_attr(search_space, ["termination_condition"])
    message = _first_str_attr(search_space, ["message"])

    reported_runtime_s = _first_nested_attr(
        search_space,
        [
            "wallclock_time",
            "wall_clock_time",
            "time",
            "runtime",
            "user_time",
            "solve_time",
            "elapsed_time",
        ],
    )

    normalized_sense = (
        normalize_objective_sense(objective_sense)
        or _active_model_objective_sense(model)
        or _problem_objective_sense(problem_obj)
    )

    highs_fields = _highs_info_fields(solver)
    incumbent = highs_fields.get("objective_function_value")
    best_bound = highs_fields.get("mip_dual_bound")
    gap_fraction = _finite_nonnegative_or_none(highs_fields.get("mip_gap"))
    gap_formula = "highspy_info.mip_gap" if gap_fraction is not None else None
    diagnostic_source = "highspy_info" if highs_fields else None

    if incumbent is None or best_bound is None:
        pyomo_incumbent, pyomo_bound = _pyomo_problem_bounds(problem_obj, normalized_sense)
        if incumbent is None:
            incumbent = pyomo_incumbent
        if best_bound is None:
            best_bound = pyomo_bound
        if pyomo_incumbent is not None or pyomo_bound is not None:
            diagnostic_source = (
                "pyomo_problem_bounds_by_objective_sense"
                if diagnostic_source is None
                else f"{diagnostic_source}+pyomo_problem_bounds_by_objective_sense"
            )

    if incumbent is None and objective_value is not None:
        incumbent = _to_float_or_none(objective_value)
        if incumbent is not None:
            diagnostic_source = (
                "objective_value_fallback"
                if diagnostic_source is None
                else f"{diagnostic_source}+objective_value_fallback"
            )

    if gap_fraction is None:
        gap_fraction = _fallback_gap_fraction(incumbent, best_bound)
        if gap_fraction is not None:
            gap_formula = GAP_FALLBACK_FORMULA
            diagnostic_source = (
                "fallback_gap_formula"
                if diagnostic_source is None
                else f"{diagnostic_source}+fallback_gap_formula"
            )

    requested_gap = _finite_nonnegative_or_none(requested_gap_rel_fraction)

    return {
        "status": status,
        "termination": termination,
        "wallclock_s": (_to_float_or_none(wallclock_s) if wallclock_s is not None else None),
        "reported_runtime_s": reported_runtime_s,
        "objective_sense": normalized_sense,
        "incumbent_objective": incumbent,
        "best_bound_objective": best_bound,
        "achieved_gap_rel_fraction": gap_fraction,
        "achieved_gap_percent": (None if gap_fraction is None else 100.0 * gap_fraction),
        "requested_gap_rel_fraction": requested_gap,
        "requested_gap_percent": (None if requested_gap is None else 100.0 * requested_gap),
        "diagnostic_source": diagnostic_source,
        "gap_formula": gap_formula,
        # Backward-compatible aliases with corrected semantics.
        "achieved_gap_rel": gap_fraction,
        "best_feasible_objective": incumbent,
        "best_objective_bound": best_bound,
        "message": message,
    }
