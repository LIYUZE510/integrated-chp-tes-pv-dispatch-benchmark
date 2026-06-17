from __future__ import annotations

import math

import pandas as pd
import pyomo.environ as pyo
import pytest
from pyomo.repn.standard_repn import generate_standard_repn

from chp_pv_sim.experiments.config import ExperimentConfig
from chp_pv_sim.experiments.qc import build_validation_report
from chp_pv_sim.models.chp_week_storage_pv_grid_dispatch import Meta, build_model


def _segments() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    heat = pd.DataFrame(
        [
            {
                "temp_label": "A",
                "segment": 1,
                "k_hq": 10.0,
                "b_hq": 0.0,
                "h_lb_eff": 10.0,
                "h_ub_eff": 20.0,
                "q_lb_eff": 100.0,
                "q_ub_eff": 200.0,
            }
        ]
    )
    power = pd.DataFrame(
        [
            {
                "temp_label": "A",
                "segment": 1,
                "k_eh": 5.0,
                "b_eh": 50.0,
                "e_lb_eff": 10.0,
                "e_ub_eff": 30.0,
                "q_lb_eff": 100.0,
                "q_ub_eff": 200.0,
            }
        ]
    )
    heat["a_h"] = 1.0 / heat["k_hq"]
    heat["c_h"] = -heat["b_hq"] / heat["k_hq"]
    power["a_e"] = 1.0 / power["k_eh"]
    power["c_e"] = -power["b_eh"] / power["k_eh"]
    return heat, power, ["A"]


def _meta(*, grid_export_cap_mw: float = 5.0) -> Meta:
    return Meta(
        scenario="synthetic",
        n_hours=1,
        storage_s_max_mwh=50.0,
        storage_p_ch_max_mw=20.0,
        storage_p_dis_max_mw=20.0,
        eta_ch=1.0,
        eta_dis=1.0,
        loss_per_hour=0.0,
        s_init_mwh=0.0,
        grid_export_cap_mw=grid_export_cap_mw,
        price_sell=50.0,
        price_buy=70.0,
        pv_scale=1.0,
        e_load_base_mw=8.0,
        e_load_alpha_per_heat=0.0,
        penalty_pv_curt=0.1,
        penalty_chp_curt=0.0,
        cost_q=15.0,
        cost_boiler=60.0,
        cost_dump=50.0,
        penalty_under=1_000_000.0,
        cycle_cost=0.01,
        startup_cost=5000.0,
        shutdown_cost=0.0,
        min_up_hours=1,
        min_down_hours=1,
        on_init=0,
        time_limit_s=60.0,
        mip_rel_gap=0.002,
        tee=False,
        terminal_soc_target_mwh=None,
    )


def _model(*, e_load_mw: float = 8.0, grid_export_cap_mw: float = 5.0) -> pyo.ConcreteModel:
    heat, power, temps = _segments()
    return build_model(
        pd.DatetimeIndex(["2023-01-01 00:00:00"]),
        pd.Series([10.0]),
        pd.Series([0.0]),
        pd.Series([e_load_mw]),
        heat,
        power,
        temps,
        _meta(grid_export_cap_mw=grid_export_cap_mw),
    )


def _set_known_feasible_values(model: pyo.ConcreteModel) -> None:
    model.H[0].set_value(10.0)
    model.E[0].set_value(10.0)
    model.Q[0].set_value(100.0)
    model.y[0, "A"].set_value(1.0)
    model.y_off[0].set_value(0.0)
    model.zH[0, ("A", 1)].set_value(1.0)
    model.zE[0, ("A", 1)].set_value(1.0)
    model.start[0].set_value(1.0)
    model.stop[0].set_value(0.0)
    model.S[0].set_value(0.0)
    model.S[1].set_value(0.0)
    model.ch[0].set_value(0.0)
    model.dis[0].set_value(0.0)
    model.u_ch[0].set_value(0.0)
    model.boiler[0].set_value(0.0)
    model.dump[0].set_value(0.0)
    model.under[0].set_value(0.0)
    model.grid_import[0].set_value(0.0)
    model.grid_export[0].set_value(2.0)
    model.pv_curt[0].set_value(0.0)
    model.chp_curt[0].set_value(0.0)


def _constraint_violations(model: pyo.ConcreteModel, *, tol: float = 1.0e-8) -> list[str]:
    violations: list[str] = []
    for con in model.component_data_objects(pyo.Constraint, active=True):
        body = pyo.value(con.body)
        if con.lower is not None and body < pyo.value(con.lower) - tol:
            violations.append(con.name)
        if con.upper is not None and body > pyo.value(con.upper) + tol:
            violations.append(con.name)
    return violations


def _coefficient_by_var_name(expr: pyo.Expression) -> dict[str, float]:
    repn = generate_standard_repn(expr)
    return {var.name: float(coef) for var, coef in zip(repn.linear_vars, repn.linear_coefs)}


def test_tightening_constraints_exist() -> None:
    model = _model()

    for name in [
        "zH_on_ub",
        "zE_on_ub",
        "h_seg_agg_lb",
        "h_seg_agg_ub",
        "q_heat_seg_agg_lb",
        "q_heat_seg_agg_ub",
        "e_seg_agg_lb",
        "e_seg_agg_ub",
        "q_power_seg_agg_lb",
        "q_power_seg_agg_ub",
        "chp_curt_on_ub",
        "chp_curt_seg_ub",
        "grid_import_delivery_ub",
    ]:
        assert hasattr(model, name)


@pytest.mark.parametrize("bad_value", [-1.0, float("nan"), float("inf")])
def test_invalid_electric_load_values_are_rejected(bad_value: float) -> None:
    with pytest.raises(ValueError, match="e_load_mw.*position 0"):
        _model(e_load_mw=bad_value)


@pytest.mark.parametrize("bad_value", [-1.0, float("nan"), float("inf")])
def test_invalid_grid_export_cap_values_are_rejected(bad_value: float) -> None:
    with pytest.raises(ValueError, match="grid_export_cap_mw"):
        _model(grid_export_cap_mw=bad_value)


def test_zero_electric_load_is_valid() -> None:
    model = _model(e_load_mw=0.0)

    assert model.grid_import[0].ub == pytest.approx(5.0)


def test_zero_grid_export_cap_is_valid() -> None:
    model = _model(grid_export_cap_mw=0.0)

    assert model.grid_export[0].ub == pytest.approx(0.0)
    assert model.grid_import[0].ub == pytest.approx(8.0)


def test_derived_upper_bounds_are_finite_nonnegative_and_use_model_data() -> None:
    model = _model()

    assert model.grid_import[0].ub == pytest.approx(13.0)
    assert model.chp_curt[0].ub == pytest.approx(30.0)
    for var in [model.grid_import[0], model.chp_curt[0]]:
        assert var.ub is not None
        assert math.isfinite(float(var.ub))
        assert float(var.ub) >= 0.0

    assert _coefficient_by_var_name(model.h_seg_agg_ub[0].body)["zH[0,A,1]"] == pytest.approx(-20.0)
    assert _coefficient_by_var_name(model.q_heat_seg_agg_ub[0].body)["zH[0,A,1]"] == pytest.approx(-200.0)
    assert _coefficient_by_var_name(model.e_seg_agg_ub[0].body)["zE[0,A,1]"] == pytest.approx(-30.0)
    assert _coefficient_by_var_name(model.q_power_seg_agg_ub[0].body)["zE[0,A,1]"] == pytest.approx(-200.0)


def test_commitment_off_forces_segments_and_chp_curtailment_to_zero() -> None:
    model = _model()
    _set_known_feasible_values(model)
    model.y_off[0].set_value(1.0)
    model.y[0, "A"].set_value(0.0)

    model.zH[0, ("A", 1)].set_value(1.0)
    assert "zH_on_ub[0,A,1]" in _constraint_violations(model)
    model.zH[0, ("A", 1)].set_value(0.0)

    model.zE[0, ("A", 1)].set_value(1.0)
    assert "zE_on_ub[0,A,1]" in _constraint_violations(model)
    model.zE[0, ("A", 1)].set_value(0.0)

    model.chp_curt[0].set_value(1.0)
    assert "chp_curt_on_ub[0]" in _constraint_violations(model)


def test_known_integer_feasible_synthetic_point_remains_feasible() -> None:
    model = _model()
    _set_known_feasible_values(model)

    assert _constraint_violations(model) == []


def test_known_infeasible_synthetic_point_remains_infeasible() -> None:
    model = _model()
    _set_known_feasible_values(model)
    model.grid_import[0].set_value(20.0, skip_validation=True)

    violations = _constraint_violations(model)
    assert "elec_bal[0]" in violations
    assert "grid_import_delivery_ub[0]" in violations


def test_objective_expression_is_unchanged_by_tightening_constraints() -> None:
    model = _model()

    coeffs = _coefficient_by_var_name(model.obj.expr)
    assert model.obj.sense == pyo.maximize
    assert coeffs["grid_export[0]"] == pytest.approx(50.0)
    assert coeffs["grid_import[0]"] == pytest.approx(-70.0)
    assert coeffs["Q[0]"] == pytest.approx(-15.0)
    assert coeffs["boiler[0]"] == pytest.approx(-60.0)
    assert coeffs["dump[0]"] == pytest.approx(-50.0)
    assert coeffs["under[0]"] == pytest.approx(-1_000_000.0)
    assert coeffs["ch[0]"] == pytest.approx(-0.01)
    assert coeffs["dis[0]"] == pytest.approx(-0.01)
    assert coeffs["pv_curt[0]"] == pytest.approx(-0.1)
    assert coeffs["start[0]"] == pytest.approx(-5000.0)
    assert "chp_curt[0]" not in coeffs
    assert "stop[0]" not in coeffs


def test_existing_physical_validation_behavior_is_unchanged_for_clean_dispatch() -> None:
    cfg = ExperimentConfig.from_dict(
        {
            "run": {"method": "uc", "tag": "x"},
            "grid": {"grid_export_cap_mw": 60.0},
            "storage": {"s_max_mwh": 100.0},
        }
    )
    dispatch = pd.DataFrame(
        {
            "heat_balance_residual": [0.0],
            "elec_balance_residual": [0.0],
            "grid_export_mw": [10.0],
            "grid_import_mw": [0.0],
            "S_mwh": [50.0],
            "S_next_mwh": [50.0],
            "H_chp_mw": [10.0],
            "E_chp_mw": [8.0],
            "Q_in_mw": [100.0],
            "boiler_mw": [0.0],
            "dump_mw": [0.0],
            "under_mw": [0.0],
            "ch_mw": [0.0],
            "dis_mw": [0.0],
            "pv_curt_mw": [0.0],
            "chp_curt_mw": [0.0],
        }
    )

    report = build_validation_report(dispatch, cfg=cfg, qc=cfg.qc, expected_terminal_soc=50.0)

    assert report["pass"] is True
    assert report["issues"] == []
