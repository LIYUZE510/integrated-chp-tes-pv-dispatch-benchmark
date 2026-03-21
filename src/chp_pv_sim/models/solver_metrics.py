from __future__ import annotations

import math
from typing import Any


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


def extract_solver_diagnostics(
    results: Any,
    *,
    wallclock_s: float | None = None,
    objective_value: float | None = None,
) -> dict[str, Any]:
    """
    Best-effort extraction of runtime / gap / bounds from a Pyomo result object.
    Works defensively across legacy and appsi-style HiGHS wrappers.

    Returned keys are JSON-serializable and safe to store in summary files.
    """
    solver_obj = getattr(results, 'solver', None)
    problem_obj = getattr(results, 'problem', None)
    search_space = [results, solver_obj, problem_obj]

    status = None
    termination = None
    message = None
    for obj in search_space:
        if obj is None:
            continue
        try:
            if status is None and hasattr(obj, 'status'):
                status = str(getattr(obj, 'status'))
        except Exception:
            pass
        try:
            if termination is None and hasattr(obj, 'termination_condition'):
                termination = str(getattr(obj, 'termination_condition'))
        except Exception:
            pass
        try:
            if message is None and hasattr(obj, 'message'):
                msg = getattr(obj, 'message')
                if msg is not None:
                    message = str(msg)
        except Exception:
            pass

    reported_runtime_s = _first_nested_attr(
        search_space,
        [
            'wallclock_time', 'wall_clock_time', 'time', 'runtime',
            'user_time', 'solve_time', 'elapsed_time',
        ],
    )

    achieved_gap_rel = _first_nested_attr(
        search_space,
        ['gap', 'relative_gap', 'mip_gap', 'mip_rel_gap', 'relative_mip_gap'],
    )

    best_feasible_obj = _first_nested_attr(
        search_space,
        [
            'best_feasible_objective', 'primal_bound', 'upper_bound',
            'objective', 'incumbent_objective',
        ],
    )
    best_bound = _first_nested_attr(
        search_space,
        [
            'best_objective_bound', 'dual_bound', 'lower_bound',
            'best_bound', 'objective_bound',
        ],
    )

    if best_feasible_obj is None and objective_value is not None:
        best_feasible_obj = _to_float_or_none(objective_value)

    if achieved_gap_rel is None and best_feasible_obj is not None and best_bound is not None:
        denom = max(1.0, abs(best_feasible_obj))
        achieved_gap_rel = abs(best_feasible_obj - best_bound) / denom

    return {
        'status': status,
        'termination': termination,
        'wallclock_s': (_to_float_or_none(wallclock_s) if wallclock_s is not None else None),
        'reported_runtime_s': reported_runtime_s,
        'achieved_gap_rel': achieved_gap_rel,
        'best_feasible_objective': best_feasible_obj,
        'best_objective_bound': best_bound,
        'message': message,
    }
