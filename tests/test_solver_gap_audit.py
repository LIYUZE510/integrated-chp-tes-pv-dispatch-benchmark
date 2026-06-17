from __future__ import annotations

import math
from pathlib import Path

import pytest

from tools.resubmission_2026 import audit_solver_gap as audit


def test_gap_value_propagation_for_requested_values() -> None:
    for gap in audit.GAP_VALUES:
        solved = audit.solve_toy_gap(gap)
        before = solved["pre_solve_option_snapshot"]
        after = solved["post_solve_option_snapshot"]

        assert before["options"]["mip_rel_gap"] == pytest.approx(gap)
        assert before["highs_options"]["mip_rel_gap"] == pytest.approx(gap)
        assert after["underlying_highs_options"]["mip_rel_gap"]["value"] == pytest.approx(gap)
        assert after["underlying_highs_options"]["threads"]["value"] == 1
        assert after["underlying_highs_options"]["parallel"]["value"] == "off"
        assert after["underlying_highs_options"]["random_seed"]["value"] == 1

    loose = audit.solve_toy_gap(0.2)
    assert loose["incumbent_objective"] == pytest.approx(75.0)
    assert loose["best_bound_from_highspy"] == pytest.approx(79.0)
    assert loose["relative_gap_from_highspy_fraction"] == pytest.approx(4.0 / 75.0)
    assert "tolerance: 20%" in loose["captured_solver_log"]


class _Problem:
    def __init__(self, *, lower_bound: float, upper_bound: float, sense: str) -> None:
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.sense = sense


class _Solver:
    status = "ok"
    termination_condition = "maxTimeLimit"


class _Results:
    solver = _Solver()

    def __init__(self, problem: _Problem) -> None:
        self.problem = problem


def test_objective_sense_and_bound_sign_interpretation_with_synthetic_results() -> None:
    max_results = _Results(_Problem(lower_bound=-100.0, upper_bound=30.0, sense="maximize"))
    max_interp = audit.interpret_pyomo_problem_bounds(max_results, objective_value=-100.0)
    assert max_interp["incumbent_objective"] == pytest.approx(-100.0)
    assert max_interp["best_objective_bound"] == pytest.approx(30.0)
    assert max_interp["relative_gap_fraction_from_pyomo_bounds"] == pytest.approx(1.3)

    min_results = _Results(_Problem(lower_bound=80.0, upper_bound=100.0, sense="minimize"))
    min_interp = audit.interpret_pyomo_problem_bounds(min_results, objective_value=100.0)
    assert min_interp["incumbent_objective"] == pytest.approx(100.0)
    assert min_interp["best_objective_bound"] == pytest.approx(80.0)
    assert min_interp["relative_gap_fraction_from_pyomo_bounds"] == pytest.approx(0.2)


def test_solver_metrics_match_maximize_synthetic_case() -> None:
    results = _Results(_Problem(lower_bound=75.0, upper_bound=79.0, sense="maximize"))
    diagnostics = audit.extract_solver_diagnostics(results, wallclock_s=0.1, objective_value=75.0)
    highspy_fields = {
        "info": {
            "objective_function_value": 75.0,
            "mip_dual_bound": 79.0,
            "mip_gap": 4.0 / 75.0,
        }
    }
    interpreted = audit.interpret_pyomo_problem_bounds(results, objective_value=75.0)

    comparison = audit.compare_solver_metrics_to_raw(diagnostics, highspy_fields, interpreted)

    assert diagnostics["best_feasible_objective"] == pytest.approx(75.0)
    assert diagnostics["best_objective_bound"] == pytest.approx(79.0)
    assert diagnostics["achieved_gap_rel"] == pytest.approx(4.0 / 75.0)
    assert diagnostics["achieved_gap_rel_fraction"] == pytest.approx(4.0 / 75.0)
    assert diagnostics["achieved_gap_percent"] == pytest.approx(100.0 * 4.0 / 75.0)
    assert comparison["matches_highspy_incumbent"] is True
    assert comparison["matches_highspy_best_bound"] is True
    assert comparison["matches_highspy_gap"] is True
    assert comparison["issues"] == []


def test_audit_does_not_write_to_frozen_output_paths() -> None:
    existing_paths = [path for path in audit.REPRESENTATIVE_FROZEN_FILES.values() if path.exists()]
    assert existing_paths
    before = {path: _stat_signature(path) for path in existing_paths}

    frozen_audit = audit.audit_frozen_outputs()

    assert frozen_audit
    after = {path: _stat_signature(path) for path in existing_paths}
    assert after == before


def _stat_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)
