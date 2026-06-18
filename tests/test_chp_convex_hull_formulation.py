from __future__ import annotations

import math

import pandas as pd
import pyomo.environ as pyo
import pytest
from pyomo.repn.standard_repn import generate_standard_repn

from chp_pv_sim.experiments.config import ExperimentConfig
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
            },
            {
                "temp_label": "A",
                "segment": 2,
                "k_hq": 10.0,
                "b_hq": 0.0,
                "h_lb_eff": 20.0,
                "h_ub_eff": 30.0,
                "q_lb_eff": 200.0,
                "q_ub_eff": 300.0,
            },
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
            },
            {
                "temp_label": "A",
                "segment": 2,
                "k_eh": 5.0,
                "b_eh": 50.0,
                "e_lb_eff": 30.0,
                "e_ub_eff": 50.0,
                "q_lb_eff": 200.0,
                "q_ub_eff": 300.0,
            },
        ]
    )
    heat["a_h"] = 1.0 / heat["k_hq"]
    heat["c_h"] = -heat["b_hq"] / heat["k_hq"]
    power["a_e"] = 1.0 / power["k_eh"]
    power["c_e"] = -power["b_eh"] / power["k_eh"]
    return heat, power, ["A"]


def _meta(*, formulation: str = "legacy_big_m") -> Meta:
    return Meta(
        scenario="synthetic",
        n_hours=1,
        storage_s_max_mwh=1.0,
        storage_p_ch_max_mw=0.0,
        storage_p_dis_max_mw=0.0,
        eta_ch=1.0,
        eta_dis=1.0,
        loss_per_hour=0.0,
        s_init_mwh=0.0,
        grid_export_cap_mw=5.0,
        price_sell=50.0,
        price_buy=70.0,
        pv_scale=1.0,
        e_load_base_mw=8.0,
        e_load_alpha_per_heat=0.0,
        penalty_pv_curt=0.1,
        penalty_chp_curt=0.0,
        cost_q=1.0,
        cost_boiler=1000.0,
        cost_dump=100.0,
        penalty_under=1_000_000.0,
        cycle_cost=0.01,
        startup_cost=0.0,
        shutdown_cost=0.0,
        min_up_hours=1,
        min_down_hours=1,
        on_init=0,
        time_limit_s=30.0,
        mip_rel_gap=0.0,
        tee=False,
        terminal_soc_target_mwh=None,
        chp_segment_formulation=formulation,
    )


def _model(*, formulation: str = "legacy_big_m") -> pyo.ConcreteModel:
    heat, power, temps = _segments()
    return build_model(
        pd.DatetimeIndex(["2023-01-01 00:00:00"]),
        pd.Series([10.0]),
        pd.Series([0.0]),
        pd.Series([8.0]),
        heat,
        power,
        temps,
        _meta(formulation=formulation),
    )


def _coefficients(expr: pyo.Expression) -> dict[str, float]:
    repn = generate_standard_repn(expr)
    return {var.name: float(coef) for var, coef in zip(repn.linear_vars, repn.linear_coefs)}


def _constraint_violations(model: pyo.ConcreteModel, *, tol: float = 1.0e-8) -> list[str]:
    violations: list[str] = []
    for con in model.component_data_objects(pyo.Constraint, active=True):
        body = pyo.value(con.body)
        if con.lower is not None and body < pyo.value(con.lower) - tol:
            violations.append(con.name)
        if con.upper is not None and body > pyo.value(con.upper) + tol:
            violations.append(con.name)
    return violations


def _set_known_integer_feasible_hull_values(model: pyo.ConcreteModel) -> None:
    model.H[0].set_value(10.0)
    model.E[0].set_value(10.0)
    model.Q[0].set_value(100.0)
    model.y[0, "A"].set_value(1.0)
    model.y_off[0].set_value(0.0)
    model.zH[0, ("A", 1)].set_value(1.0)
    model.zH[0, ("A", 2)].set_value(0.0)
    model.zE[0, ("A", 1)].set_value(1.0)
    model.zE[0, ("A", 2)].set_value(0.0)
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

    model.H_seg_hull[0, ("A", 1)].set_value(10.0)
    model.QH_seg_hull[0, ("A", 1)].set_value(100.0)
    model.H_seg_hull[0, ("A", 2)].set_value(0.0)
    model.QH_seg_hull[0, ("A", 2)].set_value(0.0)
    model.E_seg_hull[0, ("A", 1)].set_value(10.0)
    model.QE_seg_hull[0, ("A", 1)].set_value(100.0)
    model.E_seg_hull[0, ("A", 2)].set_value(0.0)
    model.QE_seg_hull[0, ("A", 2)].set_value(0.0)


def _relax_discrete(model: pyo.ConcreteModel) -> None:
    for var_data in model.component_data_objects(pyo.Var, descend_into=True):
        if var_data.is_binary():
            var_data.domain = pyo.UnitInterval
        elif var_data.is_integer():
            var_data.domain = pyo.Reals


def _solve(model: pyo.ConcreteModel) -> float:
    solver = pyo.SolverFactory("appsi_highs")
    if not solver.available(False):
        pytest.skip("appsi_highs is not available")
    for attr in ("options", "highs_options"):
        opts = getattr(solver, attr, None)
        if opts is not None:
            opts["time_limit"] = 30.0
            opts["output_flag"] = False
            opts["log_to_console"] = False
            opts["threads"] = 1
            opts["parallel"] = "off"
            opts["random_seed"] = 1
    results = solver.solve(model, tee=False)
    assert str(getattr(results.solver, "termination_condition", None)) == "optimal"
    return float(pyo.value(model.obj))


def test_formulation_option_parsing_and_invalid_rejection() -> None:
    cfg = ExperimentConfig.from_dict({"formulation": {"chp_segments": "convex_hull"}})
    assert cfg.formulation.chp_segments == "convex_hull"

    default_cfg = ExperimentConfig.from_dict({})
    assert default_cfg.formulation.chp_segments == "legacy_big_m"

    with pytest.raises(ValueError, match="formulation.chp_segments"):
        ExperimentConfig.from_dict({"formulation": {"chp_segments": "not_a_formulation"}})


def test_convex_hull_constraints_exist_and_legacy_big_m_rows_are_bypassed() -> None:
    hull = _model(formulation="convex_hull")
    legacy = _model(formulation="legacy_big_m")

    for name in [
        "H_seg_hull",
        "QH_seg_hull",
        "E_seg_hull",
        "QE_seg_hull",
        "h_hull_lb",
        "h_hull_ub",
        "h_hull_eq",
        "h_hull_agg",
        "q_heat_hull_agg",
        "e_hull_lb",
        "e_hull_ub",
        "e_hull_eq",
        "e_hull_agg",
        "q_power_hull_agg",
    ]:
        assert hasattr(hull, name)

    assert hasattr(legacy, "h_eq_ub")
    assert not hasattr(hull, "h_eq_ub")
    assert not hasattr(hull, "e_eq_ub")


def test_inactive_segment_copies_are_forced_to_zero() -> None:
    model = _model(formulation="convex_hull")
    _set_known_integer_feasible_hull_values(model)

    assert _constraint_violations(model) == []

    model.H_seg_hull[0, ("A", 2)].set_value(1.0)
    assert "h_hull_ub[0,A,2]" in _constraint_violations(model)
    model.H_seg_hull[0, ("A", 2)].set_value(0.0)

    model.QE_seg_hull[0, ("A", 2)].set_value(1.0)
    assert "qe_hull_ub[0,A,2]" in _constraint_violations(model)


def test_scaled_bounds_affine_equations_and_aggregation_use_segment_data() -> None:
    model = _model(formulation="convex_hull")

    h_ub_coeffs = _coefficients(model.h_hull_ub[0, "A", 1].body)
    assert h_ub_coeffs["H_seg_hull[0,A,1]"] == pytest.approx(1.0)
    assert h_ub_coeffs["zH[0,A,1]"] == pytest.approx(-20.0)

    qh_lb_coeffs = _coefficients(model.qh_hull_lb[0, "A", 1].body)
    assert qh_lb_coeffs["QH_seg_hull[0,A,1]"] == pytest.approx(-1.0)
    assert qh_lb_coeffs["zH[0,A,1]"] == pytest.approx(100.0)

    e_eq_coeffs = _coefficients(model.e_hull_eq[0, "A", 1].body)
    assert e_eq_coeffs["E_seg_hull[0,A,1]"] == pytest.approx(1.0)
    assert e_eq_coeffs["QE_seg_hull[0,A,1]"] == pytest.approx(-0.2)
    assert e_eq_coeffs["zE[0,A,1]"] == pytest.approx(10.0)

    h_agg_coeffs = _coefficients(model.h_hull_agg[0].body)
    assert h_agg_coeffs["H[0]"] == pytest.approx(1.0)
    assert h_agg_coeffs["H_seg_hull[0,A,1]"] == pytest.approx(-1.0)
    assert h_agg_coeffs["H_seg_hull[0,A,2]"] == pytest.approx(-1.0)

    q_power_agg_coeffs = _coefficients(model.q_power_hull_agg[0].body)
    assert q_power_agg_coeffs["Q[0]"] == pytest.approx(1.0)
    assert q_power_agg_coeffs["QE_seg_hull[0,A,1]"] == pytest.approx(-1.0)
    assert q_power_agg_coeffs["QE_seg_hull[0,A,2]"] == pytest.approx(-1.0)


def test_known_integer_feasible_point_lifts_into_convex_hull_formulation() -> None:
    model = _model(formulation="convex_hull")
    _set_known_integer_feasible_hull_values(model)

    assert _constraint_violations(model) == []


def test_objective_expression_and_physical_balances_are_unchanged() -> None:
    legacy = _model(formulation="legacy_big_m")
    hull = _model(formulation="convex_hull")

    assert _coefficients(hull.obj.expr) == _coefficients(legacy.obj.expr)
    assert _coefficients(hull.heat_bal[0].body) == _coefficients(legacy.heat_bal[0].body)
    assert _coefficients(hull.elec_bal[0].body) == _coefficients(legacy.elec_bal[0].body)

    assert all("seg_hull" not in name for name in _coefficients(hull.obj.expr))


def test_tiny_horizon_legacy_and_convex_hull_integer_optima_agree() -> None:
    legacy = _model(formulation="legacy_big_m")
    hull = _model(formulation="convex_hull")

    assert _solve(hull) == pytest.approx(_solve(legacy), abs=1.0e-6)


def test_convex_hull_lp_bound_is_no_worse_than_legacy_big_m_lp_bound() -> None:
    legacy = _model(formulation="legacy_big_m")
    hull = _model(formulation="convex_hull")
    _relax_discrete(legacy)
    _relax_discrete(hull)

    legacy_bound = _solve(legacy)
    hull_bound = _solve(hull)

    assert hull_bound <= legacy_bound + 1.0e-6
    assert math.isfinite(hull_bound)
