from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from chp_pv_sim.experiments.config import ExperimentConfig
from chp_pv_sim.models.solver_metrics import GAP_FALLBACK_FORMULA, extract_solver_diagnostics
from chp_pv_sim.paths import ROOT


class _Problem:
    def __init__(self, *, lower_bound: Any = None, upper_bound: Any = None, sense: Any = None) -> None:
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.sense = sense


class _SolverSection:
    status = "ok"
    termination_condition = "maxTimeLimit"
    message = "synthetic"


class _Results:
    solver = _SolverSection()

    def __init__(self, problem: _Problem) -> None:
        self.problem = problem


class _HighsInfo:
    objective_function_value = 10.0
    mip_dual_bound = 13.0
    mip_gap = 0.3


class _HighsModel:
    def getInfo(self) -> _HighsInfo:
        return _HighsInfo()


class _HighsSolver:
    _solver_model = _HighsModel()


def test_maximization_nonzero_gap_bounds_are_not_swapped() -> None:
    diagnostics = extract_solver_diagnostics(
        _Results(_Problem(lower_bound=75.0, upper_bound=79.0, sense="maximize")),
        objective_value=75.0,
        objective_sense="maximize",
        requested_gap_rel_fraction=0.2,
    )

    assert diagnostics["objective_sense"] == "maximize"
    assert diagnostics["incumbent_objective"] == pytest.approx(75.0)
    assert diagnostics["best_bound_objective"] == pytest.approx(79.0)
    assert diagnostics["achieved_gap_rel_fraction"] == pytest.approx(4.0 / 75.0)
    assert diagnostics["achieved_gap_rel"] == diagnostics["achieved_gap_rel_fraction"]
    assert diagnostics["best_feasible_objective"] == diagnostics["incumbent_objective"]
    assert diagnostics["best_objective_bound"] == diagnostics["best_bound_objective"]


def test_minimization_nonzero_gap_bounds_are_not_swapped() -> None:
    diagnostics = extract_solver_diagnostics(
        _Results(_Problem(lower_bound=80.0, upper_bound=100.0, sense="minimize")),
        objective_value=100.0,
        objective_sense="minimize",
    )

    assert diagnostics["objective_sense"] == "minimize"
    assert diagnostics["incumbent_objective"] == pytest.approx(100.0)
    assert diagnostics["best_bound_objective"] == pytest.approx(80.0)
    assert diagnostics["achieved_gap_rel_fraction"] == pytest.approx(0.2)


def test_zero_gap_optimal_result_has_zero_fraction_and_percent() -> None:
    diagnostics = extract_solver_diagnostics(
        _Results(_Problem(lower_bound=77.0, upper_bound=77.0, sense="maximize")),
        objective_value=77.0,
        objective_sense="maximize",
    )

    assert diagnostics["achieved_gap_rel_fraction"] == pytest.approx(0.0)
    assert diagnostics["achieved_gap_percent"] == pytest.approx(0.0)


def test_fraction_and_percentage_fields_are_explicit() -> None:
    diagnostics = extract_solver_diagnostics(
        _Results(_Problem(lower_bound=75.0, upper_bound=79.0, sense="maximize")),
        objective_value=75.0,
        objective_sense="maximize",
        requested_gap_rel_fraction=0.002,
    )

    assert diagnostics["achieved_gap_rel_fraction"] == pytest.approx(4.0 / 75.0)
    assert diagnostics["achieved_gap_percent"] == pytest.approx(100.0 * 4.0 / 75.0)
    assert diagnostics["requested_gap_rel_fraction"] == pytest.approx(0.002)
    assert diagnostics["requested_gap_percent"] == pytest.approx(0.2)
    assert diagnostics["gap_formula"] == GAP_FALLBACK_FORMULA


def test_missing_or_nonfinite_bounds_are_safe() -> None:
    diagnostics = extract_solver_diagnostics(
        _Results(_Problem(lower_bound=float("inf"), upper_bound=float("nan"), sense="maximize")),
        objective_value=5.0,
        objective_sense="maximize",
    )

    assert diagnostics["incumbent_objective"] == pytest.approx(5.0)
    assert diagnostics["best_bound_objective"] is None
    assert diagnostics["achieved_gap_rel_fraction"] is None
    assert diagnostics["achieved_gap_percent"] is None


def test_near_zero_incumbent_uses_safe_denominator() -> None:
    diagnostics = extract_solver_diagnostics(
        _Results(_Problem(lower_bound=1e-12, upper_bound=1.0, sense="maximize")),
        objective_value=1e-12,
        objective_sense="maximize",
    )

    assert math.isfinite(diagnostics["achieved_gap_rel_fraction"])
    assert diagnostics["achieved_gap_rel_fraction"] == pytest.approx(1.0 - 1e-12)
    assert diagnostics["gap_formula"] == GAP_FALLBACK_FORMULA


def test_raw_highs_fields_are_preferred_over_pyomo_fallback_fields() -> None:
    diagnostics = extract_solver_diagnostics(
        _Results(_Problem(lower_bound=-999.0, upper_bound=-998.0, sense="maximize")),
        objective_value=-999.0,
        objective_sense="maximize",
        solver=_HighsSolver(),
    )

    assert diagnostics["incumbent_objective"] == pytest.approx(10.0)
    assert diagnostics["best_bound_objective"] == pytest.approx(13.0)
    assert diagnostics["achieved_gap_rel_fraction"] == pytest.approx(0.3)
    assert diagnostics["gap_formula"] == "highspy_info.mip_gap"
    assert diagnostics["diagnostic_source"] == "highspy_info"


def test_legacy_keys_remain_available_with_corrected_semantics() -> None:
    diagnostics = extract_solver_diagnostics(
        _Results(_Problem(lower_bound=75.0, upper_bound=79.0, sense="maximize")),
        objective_value=75.0,
        objective_sense="maximize",
    )

    assert diagnostics["achieved_gap_rel"] == diagnostics["achieved_gap_rel_fraction"]
    assert diagnostics["best_feasible_objective"] == diagnostics["incumbent_objective"]
    assert diagnostics["best_objective_bound"] == diagnostics["best_bound_objective"]


@pytest.mark.parametrize("gap", [-0.1, 1.00001, float("inf"), float("nan"), "not-a-number"])
def test_config_validation_rejects_invalid_mip_rel_gap_values(gap: Any) -> None:
    with pytest.raises(ValueError, match="solver.mip_rel_gap must be a finite fraction"):
        ExperimentConfig.from_dict({"solver": {"mip_rel_gap": gap}})


@pytest.mark.parametrize("gap", [0.0, 0.2, 0.02, 0.002, 1.0, "0.002"])
def test_config_validation_accepts_fractional_mip_rel_gap_values(gap: Any) -> None:
    cfg = ExperimentConfig.from_dict({"solver": {"mip_rel_gap": gap}})
    assert cfg.solver.mip_rel_gap == pytest.approx(float(gap))


def test_solver_metrics_and_config_validation_do_not_write_frozen_files() -> None:
    frozen_paths = [
        ROOT
        / "data"
        / "scenarios"
        / "week_2023_dec01"
        / "results"
        / "dispatch_summary_pv_grid__uc_paper_retained_fw.json",
        ROOT
        / "data"
        / "scenarios"
        / "week_2023_dec01"
        / "results"
        / "solver_windows_pv_grid__mpc_paper_retained_fw.csv",
    ]
    existing_paths = [path for path in frozen_paths if path.exists()]
    assert existing_paths
    before = {path: _stat_signature(path) for path in existing_paths}

    ExperimentConfig.from_dict({"solver": {"mip_rel_gap": 0.002}})
    extract_solver_diagnostics(
        _Results(_Problem(lower_bound=75.0, upper_bound=79.0, sense="maximize")),
        objective_value=75.0,
        objective_sense="maximize",
    )

    after = {path: _stat_signature(path) for path in existing_paths}
    assert after == before


def _stat_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)
