from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from chp_pv_sim.paths import ROOT, PROCESSED_DIR, ensure_dirs
from chp_pv_sim.models.solver_metrics import extract_solver_diagnostics


SEG_HEAT = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_heat_segments_consistent.parquet"
SEG_POWER = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_power_segments_consistent.parquet"


@dataclass
class Meta:
    scenario: str
    n_hours: int

    # storage
    storage_s_max_mwh: float
    storage_p_ch_max_mw: float
    storage_p_dis_max_mw: float
    eta_ch: float
    eta_dis: float
    loss_per_hour: float
    s_init_mwh: float

    # grid + PV
    grid_export_cap_mw: float
    price_sell: float
    price_buy: float
    pv_scale: float
    e_load_base_mw: float
    e_load_alpha_per_heat: float
    penalty_pv_curt: float
    penalty_chp_curt: float

    # costs
    cost_q: float
    cost_boiler: float
    cost_dump: float
    penalty_under: float
    cycle_cost: float

    # unit commitment
    startup_cost: float
    shutdown_cost: float
    min_up_hours: int
    min_down_hours: int
    on_init: int

    # solver
    time_limit_s: float
    mip_rel_gap: float
    tee: bool
    terminal_soc_target_mwh: Optional[float] = None


def _val(x) -> float:
    return float(pyo.value(x))


def _to_float_series(s: pd.Series, name: str) -> pd.Series:
    out = pd.to_numeric(s, errors="raise").astype(float)
    if out.isna().any():
        raise ValueError(f"{name} has NaNs after numeric conversion.")
    return out


def _configure_highs_solver(solver, *, time_limit_s: float, mip_rel_gap: float, output_flag: bool):
    """
    Robustly set HiGHS options for both legacy/appsi variants.
    """
    for attr in ("options", "highs_options"):
        opts = getattr(solver, attr, None)
        if opts is not None:
            try:
                opts["time_limit"] = float(time_limit_s)
            except Exception:
                pass
            try:
                opts["mip_rel_gap"] = float(mip_rel_gap)
            except Exception:
                pass
            try:
                opts["output_flag"] = bool(output_flag)
            except Exception:
                pass

    cfg = getattr(solver, "config", None)
    if cfg is not None:
        if hasattr(cfg, "time_limit"):
            try:
                cfg.time_limit = float(time_limit_s)
            except Exception:
                pass
        if hasattr(cfg, "mip_rel_gap"):
            try:
                cfg.mip_rel_gap = float(mip_rel_gap)
            except Exception:
                pass
        if hasattr(cfg, "stream_solver"):
            try:
                cfg.stream_solver = bool(output_flag)
            except Exception:
                pass

    return solver


def compute_realized_economics(
    out: pd.DataFrame,
    meta: Meta,
    *,
    solver_objective: Optional[float] = None,
) -> dict[str, Any]:
    """
    Recompute realized weekly economics from the final implemented trajectory.

    We expose *both* conventions explicitly:
      - profit-like objective (the quantity maximized by the Pyomo model)
      - system-cost equivalent = -(profit-like objective)

    Keeping both signs avoids the paper/report ambiguity between
    "maximize net profit" and "minimize total operating cost".
    """
    export_revenue = float(meta.price_sell) * float(out["grid_export_mw"].sum())
    import_cost = float(meta.price_buy) * float(out["grid_import_mw"].sum())

    chp_cost = float(meta.cost_q) * float(out["Q_in_mw"].sum())
    boiler_cost = float(meta.cost_boiler) * float(out["boiler_mw"].sum())
    dump_penalty_cost = float(meta.cost_dump) * float(out["dump_mw"].sum())
    under_penalty_cost = float(meta.penalty_under) * float(out["under_mw"].sum())

    pv_curtailment_penalty_cost = float(meta.penalty_pv_curt) * float(out["pv_curt_mw"].sum())
    chp_curtailment_penalty_cost = float(meta.penalty_chp_curt) * float(out["chp_curt_mw"].sum())
    curtailment_penalty_cost = pv_curtailment_penalty_cost + chp_curtailment_penalty_cost

    storage_cycling_cost = float(meta.cycle_cost) * float((out["ch_mw"] + out["dis_mw"]).sum())
    startup_cost_total = float(meta.startup_cost) * float(out["start"].sum())
    shutdown_cost_total = float(meta.shutdown_cost) * float(out["stop"].sum())

    profit_objective_realized = (
        export_revenue
        - import_cost
        - chp_cost
        - boiler_cost
        - dump_penalty_cost
        - under_penalty_cost
        - storage_cycling_cost
        - pv_curtailment_penalty_cost
        - chp_curtailment_penalty_cost
        - startup_cost_total
        - shutdown_cost_total
    )

    system_cost_realized = -profit_objective_realized

    solver_profit_objective = None
    solver_system_cost_equivalent = None
    diff_profit_vs_solver = None
    diff_system_vs_solver = None
    if solver_objective is not None:
        try:
            if math.isfinite(float(solver_objective)):
                solver_profit_objective = float(solver_objective)
                solver_system_cost_equivalent = -float(solver_objective)
                diff_profit_vs_solver = float(profit_objective_realized) - float(solver_objective)
                diff_system_vs_solver = float(system_cost_realized) - float(solver_system_cost_equivalent)
        except Exception:
            solver_profit_objective = None
            solver_system_cost_equivalent = None
            diff_profit_vs_solver = None
            diff_system_vs_solver = None

    return {
        # explicit sign conventions
        "profit_objective_realized": float(profit_objective_realized),
        "system_cost_realized": float(system_cost_realized),
        "solver_profit_objective": solver_profit_objective,
        "solver_system_cost_equivalent": solver_system_cost_equivalent,
        "difference_profit_realized_minus_solver": diff_profit_vs_solver,
        "difference_system_cost_realized_minus_solver": diff_system_vs_solver,

        # legacy aliases kept for backward compatibility with older report scripts
        "total_objective_realized": float(profit_objective_realized),
        "solver_reported_objective": solver_profit_objective,
        "difference_realized_minus_solver": diff_profit_vs_solver,

        "chp_cost": float(chp_cost),
        "boiler_cost": float(boiler_cost),
        "dump_penalty_cost": float(dump_penalty_cost),
        "pv_curtailment_penalty_cost": float(pv_curtailment_penalty_cost),
        "chp_curtailment_penalty_cost": float(chp_curtailment_penalty_cost),
        "curtailment_penalty_cost": float(curtailment_penalty_cost),
        "under_penalty_cost": float(under_penalty_cost),
        "import_cost": float(import_cost),
        "export_revenue": float(export_revenue),
        "net_grid_cost": float(import_cost - export_revenue),
        "startup_cost": float(startup_cost_total),
        "shutdown_cost": float(shutdown_cost_total),
        "storage_cycling_cost": float(storage_cycling_cost),
        "cycling_cost": float(storage_cycling_cost),
    }


def load_segments() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    if not SEG_HEAT.exists() or not SEG_POWER.exists():
        raise FileNotFoundError(
            "Missing turbine segment tables. Ensure these exist:\n"
            f"  - {SEG_HEAT}\n"
            f"  - {SEG_POWER}\n"
            "Run: python -m chp_pv_sim.datasets.kaz_chpp_make_consistent_segments"
        )

    heat = pd.read_parquet(SEG_HEAT)
    power = pd.read_parquet(SEG_POWER)

    temps = sorted(set(heat["temp_label"]).intersection(set(power["temp_label"])))
    if not temps:
        raise RuntimeError("No common temp_label between heat and power segment tables.")

    heat = heat[heat["temp_label"].isin(temps)].copy()
    power = power[power["temp_label"].isin(temps)].copy()

    if "segment_infeasible" in heat.columns:
        heat = heat[~heat["segment_infeasible"]].copy()
    if "segment_infeasible" in power.columns:
        power = power[~power["segment_infeasible"]].copy()

    need_h = ["temp_label", "segment", "k_hq", "b_hq", "h_lb_eff", "h_ub_eff", "q_lb_eff", "q_ub_eff"]
    need_e = ["temp_label", "segment", "k_eh", "b_eh", "e_lb_eff", "e_ub_eff", "q_lb_eff", "q_ub_eff"]
    for c in need_h:
        if c not in heat.columns:
            raise KeyError(f"heat table missing: {c}")
    for c in need_e:
        if c not in power.columns:
            raise KeyError(f"power table missing: {c}")

    for c in ["k_hq", "b_hq", "h_lb_eff", "h_ub_eff", "q_lb_eff", "q_ub_eff"]:
        heat[c] = pd.to_numeric(heat[c], errors="raise")
    for c in ["k_eh", "b_eh", "e_lb_eff", "e_ub_eff", "q_lb_eff", "q_ub_eff"]:
        power[c] = pd.to_numeric(power[c], errors="raise")

    # invert:
    # Heat: Q = k_hq*H + b_hq  => H = (Q-b)/k
    heat["a_h"] = 1.0 / heat["k_hq"]
    heat["c_h"] = -heat["b_hq"] / heat["k_hq"]

    # Power: Q = k_eh*E + b_eh => E = (Q-b)/k
    power["a_e"] = 1.0 / power["k_eh"]
    power["c_e"] = -power["b_eh"] / power["k_eh"]

    return heat, power, temps


def build_model(
    dt_index: pd.DatetimeIndex,
    heat_demand_mw: pd.Series,
    pv_avail_mw: pd.Series,
    e_load_mw: pd.Series,
    heat: pd.DataFrame,
    power: pd.DataFrame,
    temps: list[str],
    meta: Meta,
) -> pyo.ConcreteModel:
    N = len(dt_index)
    T = list(range(N))

    H_max = float(heat["h_ub_eff"].max())
    E_max = float(power["e_ub_eff"].max())
    Q_max = float(max(heat["q_ub_eff"].max(), power["q_ub_eff"].max()))

    HS = [(r.temp_label, int(r.segment)) for r in heat.itertuples(index=False)]
    ES = [(r.temp_label, int(r.segment)) for r in power.itertuples(index=False)]

    h_lb: dict[tuple[str, int], float] = {}
    h_ub: dict[tuple[str, int], float] = {}
    qh_lb: dict[tuple[str, int], float] = {}
    qh_ub: dict[tuple[str, int], float] = {}
    a_h: dict[tuple[str, int], float] = {}
    c_h: dict[tuple[str, int], float] = {}
    for r in heat.itertuples(index=False):
        key = (r.temp_label, int(r.segment))
        h_lb[key] = float(r.h_lb_eff)
        h_ub[key] = float(r.h_ub_eff)
        qh_lb[key] = float(r.q_lb_eff)
        qh_ub[key] = float(r.q_ub_eff)
        a_h[key] = float(r.a_h)
        c_h[key] = float(r.c_h)

    e_lb: dict[tuple[str, int], float] = {}
    e_ub: dict[tuple[str, int], float] = {}
    qe_lb: dict[tuple[str, int], float] = {}
    qe_ub: dict[tuple[str, int], float] = {}
    a_e: dict[tuple[str, int], float] = {}
    c_e: dict[tuple[str, int], float] = {}
    for r in power.itertuples(index=False):
        key = (r.temp_label, int(r.segment))
        e_lb[key] = float(r.e_lb_eff)
        e_ub[key] = float(r.e_ub_eff)
        qe_lb[key] = float(r.q_lb_eff)
        qe_ub[key] = float(r.q_ub_eff)
        a_e[key] = float(r.a_e)
        c_e[key] = float(r.c_e)

    HS_by_temp = {tt: [s for (t2, s) in HS if t2 == tt] for tt in temps}
    ES_by_temp = {tt: [s for (t2, s) in ES if t2 == tt] for tt in temps}

    M_H = H_max
    M_E = E_max
    M_Q = Q_max
    M_eq_H = H_max + 50.0
    M_eq_E = E_max + 50.0

    demand = heat_demand_mw.to_numpy(dtype=float)
    pv_av = pv_avail_mw.to_numpy(dtype=float)
    eload = e_load_mw.to_numpy(dtype=float)

    m = pyo.ConcreteModel("CHP_week_storage_PV_grid")
    m.TIME = pyo.Set(initialize=T)
    m.TEMP = pyo.Set(initialize=temps)
    m.HS = pyo.Set(initialize=HS, dimen=2)
    m.ES = pyo.Set(initialize=ES, dimen=2)

    # CHP outputs
    m.H = pyo.Var(m.TIME, domain=pyo.NonNegativeReals, bounds=(0.0, H_max))
    m.E = pyo.Var(m.TIME, domain=pyo.NonNegativeReals, bounds=(0.0, E_max))
    m.Q = pyo.Var(m.TIME, domain=pyo.NonNegativeReals, bounds=(0.0, Q_max))

    # mode
    m.y = pyo.Var(m.TIME, m.TEMP, domain=pyo.Binary)
    m.y_off = pyo.Var(m.TIME, domain=pyo.Binary)
    m.zH = pyo.Var(m.TIME, m.HS, domain=pyo.Binary)
    m.zE = pyo.Var(m.TIME, m.ES, domain=pyo.Binary)

    # unit commitment
    m.on = pyo.Expression(m.TIME, rule=lambda mm, t: 1 - mm.y_off[t])
    m.start = pyo.Var(m.TIME, domain=pyo.Binary)
    m.stop = pyo.Var(m.TIME, domain=pyo.Binary)

    on_init = int(meta.on_init)
    min_up = int(meta.min_up_hours)
    min_down = int(meta.min_down_hours)

    m.startstop = pyo.ConstraintList()
    for t in T:
        if t == 0:
            m.startstop.add(m.start[t] >= m.on[t] - on_init)
            m.startstop.add(m.stop[t] >= on_init - m.on[t])

            m.startstop.add(m.start[t] <= m.on[t])
            m.startstop.add(m.start[t] <= 1 - on_init)
            m.startstop.add(m.stop[t] <= on_init)
            m.startstop.add(m.stop[t] <= 1 - m.on[t])
        else:
            m.startstop.add(m.start[t] >= m.on[t] - m.on[t - 1])
            m.startstop.add(m.stop[t] >= m.on[t - 1] - m.on[t])

            m.startstop.add(m.start[t] <= m.on[t])
            m.startstop.add(m.start[t] <= 1 - m.on[t - 1])
            m.startstop.add(m.stop[t] <= m.on[t - 1])
            m.startstop.add(m.stop[t] <= 1 - m.on[t])

        m.startstop.add(m.start[t] + m.stop[t] <= 1)

    m.minup = pyo.ConstraintList()
    if min_up > 1:
        for k in T:
            for tau in range(min_up):
                if k + tau < N:
                    m.minup.add(m.on[k + tau] >= m.start[k])

    m.mindown = pyo.ConstraintList()
    if min_down > 1:
        for k in T:
            for tau in range(min_down):
                if k + tau < N:
                    m.mindown.add((1 - m.on[k + tau]) >= m.stop[k])

    # storage
    m.S = pyo.Var(range(N + 1), domain=pyo.NonNegativeReals, bounds=(0.0, meta.storage_s_max_mwh))
    m.ch = pyo.Var(m.TIME, domain=pyo.NonNegativeReals, bounds=(0.0, meta.storage_p_ch_max_mw))
    m.dis = pyo.Var(m.TIME, domain=pyo.NonNegativeReals, bounds=(0.0, meta.storage_p_dis_max_mw))
    m.u_ch = pyo.Var(m.TIME, domain=pyo.Binary)

    # boiler / dump / under
    m.boiler = pyo.Var(m.TIME, domain=pyo.NonNegativeReals)
    m.dump = pyo.Var(m.TIME, domain=pyo.NonNegativeReals)
    m.under = pyo.Var(m.TIME, domain=pyo.NonNegativeReals)

    # grid + PV curtail
    m.grid_import = pyo.Var(m.TIME, domain=pyo.NonNegativeReals)
    m.grid_export = pyo.Var(m.TIME, domain=pyo.NonNegativeReals, bounds=(0.0, meta.grid_export_cap_mw))
    m.pv_curt = pyo.Var(m.TIME, domain=pyo.NonNegativeReals)
    m.chp_curt = pyo.Var(m.TIME, domain=pyo.NonNegativeReals)

    # one mode
    m.one_mode = pyo.Constraint(
        m.TIME, rule=lambda mm, t: sum(mm.y[t, tt] for tt in mm.TEMP) + mm.y_off[t] == 1
    )

    # OFF => H/E/Q = 0
    m.off_H = pyo.Constraint(m.TIME, rule=lambda mm, t: mm.H[t] <= H_max * (1 - mm.y_off[t]))
    m.off_E = pyo.Constraint(m.TIME, rule=lambda mm, t: mm.E[t] <= E_max * (1 - mm.y_off[t]))
    m.off_Q = pyo.Constraint(m.TIME, rule=lambda mm, t: mm.Q[t] <= Q_max * (1 - mm.y_off[t]))

    # segment selection tied to temp
    m.heat_select = pyo.Constraint(
        m.TIME,
        m.TEMP,
        rule=lambda mm, t, tt: sum(mm.zH[t, (tt, s)] for s in HS_by_temp[tt]) == mm.y[t, tt],
    )
    m.power_select = pyo.Constraint(
        m.TIME,
        m.TEMP,
        rule=lambda mm, t, tt: sum(mm.zE[t, (tt, s)] for s in ES_by_temp[tt]) == mm.y[t, tt],
    )

    # heat segment constraints
    m.h_lb_con = pyo.Constraint(
        m.TIME, m.HS, rule=lambda mm, t, tt, s: mm.H[t] >= h_lb[(tt, s)] - M_H * (1 - mm.zH[t, (tt, s)])
    )
    m.h_ub_con = pyo.Constraint(
        m.TIME, m.HS, rule=lambda mm, t, tt, s: mm.H[t] <= h_ub[(tt, s)] + M_H * (1 - mm.zH[t, (tt, s)])
    )
    m.qh_lb_con = pyo.Constraint(
        m.TIME, m.HS, rule=lambda mm, t, tt, s: mm.Q[t] >= qh_lb[(tt, s)] - M_Q * (1 - mm.zH[t, (tt, s)])
    )
    m.qh_ub_con = pyo.Constraint(
        m.TIME, m.HS, rule=lambda mm, t, tt, s: mm.Q[t] <= qh_ub[(tt, s)] + M_Q * (1 - mm.zH[t, (tt, s)])
    )
    m.h_eq_ub = pyo.Constraint(
        m.TIME,
        m.HS,
        rule=lambda mm, t, tt, s: mm.H[t] - (a_h[(tt, s)] * mm.Q[t] + c_h[(tt, s)])
        <= M_eq_H * (1 - mm.zH[t, (tt, s)]),
    )
    m.h_eq_lb = pyo.Constraint(
        m.TIME,
        m.HS,
        rule=lambda mm, t, tt, s: mm.H[t] - (a_h[(tt, s)] * mm.Q[t] + c_h[(tt, s)])
        >= -M_eq_H * (1 - mm.zH[t, (tt, s)]),
    )

    # power segment constraints
    m.e_lb_con = pyo.Constraint(
        m.TIME, m.ES, rule=lambda mm, t, tt, s: mm.E[t] >= e_lb[(tt, s)] - M_E * (1 - mm.zE[t, (tt, s)])
    )
    m.e_ub_con = pyo.Constraint(
        m.TIME, m.ES, rule=lambda mm, t, tt, s: mm.E[t] <= e_ub[(tt, s)] + M_E * (1 - mm.zE[t, (tt, s)])
    )
    m.qe_lb_con = pyo.Constraint(
        m.TIME, m.ES, rule=lambda mm, t, tt, s: mm.Q[t] >= qe_lb[(tt, s)] - M_Q * (1 - mm.zE[t, (tt, s)])
    )
    m.qe_ub_con = pyo.Constraint(
        m.TIME, m.ES, rule=lambda mm, t, tt, s: mm.Q[t] <= qe_ub[(tt, s)] + M_Q * (1 - mm.zE[t, (tt, s)])
    )
    m.e_eq_ub = pyo.Constraint(
        m.TIME,
        m.ES,
        rule=lambda mm, t, tt, s: mm.E[t] - (a_e[(tt, s)] * mm.Q[t] + c_e[(tt, s)])
        <= M_eq_E * (1 - mm.zE[t, (tt, s)]),
    )
    m.e_eq_lb = pyo.Constraint(
        m.TIME,
        m.ES,
        rule=lambda mm, t, tt, s: mm.E[t] - (a_e[(tt, s)] * mm.Q[t] + c_e[(tt, s)])
        >= -M_eq_E * (1 - mm.zE[t, (tt, s)]),
    )

    # storage exclusivity
    m.ch_mode = pyo.Constraint(m.TIME, rule=lambda mm, t: mm.ch[t] <= meta.storage_p_ch_max_mw * mm.u_ch[t])
    m.dis_mode = pyo.Constraint(m.TIME, rule=lambda mm, t: mm.dis[t] <= meta.storage_p_dis_max_mw * (1 - mm.u_ch[t]))

    # storage dynamics
    m.S0 = pyo.Constraint(expr=m.S[0] == meta.s_init_mwh)
    if meta.terminal_soc_target_mwh is not None:
        m.Send = pyo.Constraint(expr=m.S[N] == float(meta.terminal_soc_target_mwh))
    m.storage_dyn = pyo.Constraint(
        m.TIME,
        rule=lambda mm, t: mm.S[t + 1]
        == (1 - meta.loss_per_hour) * mm.S[t] + meta.eta_ch * mm.ch[t] - (1.0 / meta.eta_dis) * mm.dis[t],
    )

    # heat balance
    m.heat_bal = pyo.Constraint(
        m.TIME,
        rule=lambda mm, t: mm.H[t] + mm.boiler[t] + mm.dis[t] - mm.ch[t] - mm.dump[t] + mm.under[t] == demand[t],
    )

    # PV curtail <= PV avail
    m.pv_curt_ub = pyo.Constraint(m.TIME, rule=lambda mm, t: mm.pv_curt[t] <= pv_av[t])

    # CHP curtail <= E
    m.chp_curt_ub = pyo.Constraint(m.TIME, rule=lambda mm, t: mm.chp_curt[t] <= mm.E[t])

    # electricity balance
    m.elec_bal = pyo.Constraint(
        m.TIME,
        rule=lambda mm, t: (mm.E[t] - mm.chp_curt[t]) + (pv_av[t] - mm.pv_curt[t]) + mm.grid_import[t]
        - mm.grid_export[t]
        == eload[t],
    )

    # objective (profit-like)
    m.obj = pyo.Objective(
        expr=sum(
            meta.price_sell * m.grid_export[t]
            - meta.price_buy * m.grid_import[t]
            - meta.cost_q * m.Q[t]
            - meta.cost_boiler * m.boiler[t]
            - meta.cost_dump * m.dump[t]
            - meta.penalty_under * m.under[t]
            - meta.cycle_cost * (m.ch[t] + m.dis[t])
            - meta.penalty_pv_curt * m.pv_curt[t]
            - meta.penalty_chp_curt * m.chp_curt[t]
            - meta.startup_cost * m.start[t]
            - meta.shutdown_cost * m.stop[t]
            for t in m.TIME
        ),
        sense=pyo.maximize,
    )

    return m


def solve_dispatch(
    scenario: str,
    *,
    s_max: float,
    p_ch_max: float,
    p_dis_max: float,
    eta_ch: float,
    eta_dis: float,
    loss_per_hour: float,
    s_init: float,
    grid_export_cap: float,
    price_sell: float,
    price_buy: float,
    pv_scale: float,
    e_load_base: float,
    e_load_alpha: float,
    penalty_pv_curt: float,
    penalty_chp_curt: float,
    cost_q: float,
    cost_boiler: float,
    cost_dump: float,
    penalty_under: float,
    cycle_cost: float,
    startup_cost: float,
    shutdown_cost: float,
    min_up: int,
    min_down: int,
    on_init: int,
    time_limit_s: float,
    mip_rel_gap: float,
    tee: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    ensure_dirs()

    scen_dir = ROOT / "data" / "scenarios" / scenario
    heat_path = scen_dir / "heat.parquet"
    pv_path = scen_dir / "pv.parquet"
    if not heat_path.exists():
        raise FileNotFoundError(f"Missing: {heat_path}")
    if not pv_path.exists():
        raise FileNotFoundError(f"Missing: {pv_path} (run PV step first)")

    heat_df = pd.read_parquet(heat_path)
    pv_df = pd.read_parquet(pv_path)

    heat_df["datetime_local"] = pd.to_datetime(heat_df["datetime_local"], errors="raise")
    pv_df["datetime_local"] = pd.to_datetime(pv_df["datetime_local"], errors="raise")

    heat_df = heat_df.sort_values("datetime_local").reset_index(drop=True)
    pv_df = pv_df.sort_values("datetime_local").reset_index(drop=True)

    if not heat_df["datetime_local"].equals(pv_df["datetime_local"]):
        merged = heat_df.merge(pv_df[["datetime_local", "pv_ac_mw"]], on="datetime_local", how="inner")
        if len(merged) != len(heat_df):
            raise ValueError(
                "PV and heat time indexes do not align.\n"
                f"heat rows={len(heat_df)}, pv rows={len(pv_df)}, merged rows={len(merged)}"
            )
        heat_df = merged
    else:
        heat_df["pv_ac_mw"] = pv_df["pv_ac_mw"].astype(float)

    dt_index = pd.DatetimeIndex(heat_df["datetime_local"])
    heat_demand = _to_float_series(heat_df["heat_demand_mw"], "heat_demand_mw")

    pv_avail = _to_float_series(heat_df["pv_ac_mw"], "pv_ac_mw") * float(pv_scale)
    pv_avail = pv_avail.clip(lower=0.0)

    e_load = (float(e_load_base) + float(e_load_alpha) * heat_demand).clip(lower=0.0)

    heat_seg, power_seg, temps = load_segments()

    meta = Meta(
        scenario=scenario,
        n_hours=len(dt_index),
        storage_s_max_mwh=float(s_max),
        storage_p_ch_max_mw=float(p_ch_max),
        storage_p_dis_max_mw=float(p_dis_max),
        eta_ch=float(eta_ch),
        eta_dis=float(eta_dis),
        loss_per_hour=float(loss_per_hour),
        s_init_mwh=float(s_init),
        grid_export_cap_mw=float(grid_export_cap),
        price_sell=float(price_sell),
        price_buy=float(price_buy),
        pv_scale=float(pv_scale),
        e_load_base_mw=float(e_load_base),
        e_load_alpha_per_heat=float(e_load_alpha),
        penalty_pv_curt=float(penalty_pv_curt),
        penalty_chp_curt=float(penalty_chp_curt),
        cost_q=float(cost_q),
        cost_boiler=float(cost_boiler),
        cost_dump=float(cost_dump),
        penalty_under=float(penalty_under),
        cycle_cost=float(cycle_cost),
        startup_cost=float(startup_cost),
        shutdown_cost=float(shutdown_cost),
        min_up_hours=int(min_up),
        min_down_hours=int(min_down),
        on_init=int(on_init),
        time_limit_s=float(time_limit_s),
        mip_rel_gap=float(mip_rel_gap),
        tee=bool(tee),
        terminal_soc_target_mwh=float(s_init),
    )

    print(
        f"Building MILP (PV+grid+UC) for scenario='{scenario}' hours={len(dt_index)} "
        f"(min_up={min_up}, min_down={min_down}, startup_cost={startup_cost}) ...",
        flush=True,
    )
    m = build_model(dt_index, heat_demand, pv_avail, e_load, heat_seg, power_seg, temps, meta)
    print(f"MILP size: vars={m.nvariables()}, cons={m.nconstraints()}", flush=True)

    solver = pyo.SolverFactory("appsi_highs")
    solver = _configure_highs_solver(
        solver,
        time_limit_s=float(time_limit_s),
        mip_rel_gap=float(mip_rel_gap),
        output_flag=bool(tee),
    )

    print(f"Solving with HiGHS: time_limit={time_limit_s}s, mip_rel_gap={mip_rel_gap}", flush=True)
    _solve_t0 = time.perf_counter()
    res = solver.solve(m, tee=bool(tee))
    _solve_wall_s = time.perf_counter() - _solve_t0

    term = getattr(res.solver, "termination_condition", None)
    status = getattr(res.solver, "status", None)
    term_str = str(term)
    status_str = str(status)

    ok_terms = {TerminationCondition.optimal, TerminationCondition.feasible}
    for name in ("maxTimeLimit", "maxTime"):
        tc = getattr(TerminationCondition, name, None)
        if tc is not None:
            ok_terms.add(tc)

    if term not in ok_terms and "time" not in term_str.lower():
        raise RuntimeError(f"Solver failed: status={status_str}, termination={term_str}")

    if "time" in term_str.lower():
        print(f"Reached time-related termination ({term_str}); using incumbent.", flush=True)

    # extract results
    N = len(dt_index)
    rows = []
    for t in range(N):
        yoff = _val(m.y_off[t])
        on = 1.0 - yoff

        if yoff > 0.5:
            mode = "OFF"
            temp = None
        else:
            mode = "ON"
            temp_vals = {tt: _val(m.y[t, tt]) for tt in m.TEMP}
            temp = max(temp_vals, key=temp_vals.get)

        hs = None
        es = None
        if mode == "ON":
            for (tt, s) in m.HS:
                if _val(m.zH[t, (tt, s)]) > 0.5:
                    hs = int(s)
                    break
            for (tt, s) in m.ES:
                if _val(m.zE[t, (tt, s)]) > 0.5:
                    es = int(s)
                    break

        rows.append(
            {
                "datetime_local": dt_index[t],
                "heat_demand_mw": float(heat_demand.iloc[t]),
                "pv_avail_mw": float(pv_avail.iloc[t]),
                "e_load_mw": float(e_load.iloc[t]),
                "mode": mode,
                "on": float(on),
                "start": _val(m.start[t]),
                "stop": _val(m.stop[t]),
                "temp_label": temp,
                "heat_seg": hs,
                "power_seg": es,
                "H_chp_mw": _val(m.H[t]),
                "E_chp_mw": _val(m.E[t]),
                "Q_in_mw": _val(m.Q[t]),
                "boiler_mw": _val(m.boiler[t]),
                "dump_mw": _val(m.dump[t]),
                "under_mw": _val(m.under[t]),
                "ch_mw": _val(m.ch[t]),
                "dis_mw": _val(m.dis[t]),
                "S_mwh": _val(m.S[t]),
                "S_next_mwh": _val(m.S[t + 1]),
                "grid_import_mw": _val(m.grid_import[t]),
                "grid_export_mw": _val(m.grid_export[t]),
                "pv_curt_mw": _val(m.pv_curt[t]),
                "chp_curt_mw": _val(m.chp_curt[t]),
            }
        )

    out = pd.DataFrame(rows)

    heat_resid = (
        out["H_chp_mw"]
        + out["boiler_mw"]
        + out["dis_mw"]
        - out["ch_mw"]
        - out["dump_mw"]
        + out["under_mw"]
        - out["heat_demand_mw"]
    )
    out["heat_balance_residual"] = heat_resid

    elec_resid = (
        (out["E_chp_mw"] - out["chp_curt_mw"])
        + (out["pv_avail_mw"] - out["pv_curt_mw"])
        + out["grid_import_mw"]
        - out["grid_export_mw"]
        - out["e_load_mw"]
    )
    out["elec_balance_residual"] = elec_resid

    try:
        obj_val = float(pyo.value(m.obj))
    except Exception:
        obj_val = float("nan")

    starts = int((out["start"] > 0.5).sum())
    stops = int((out["stop"] > 0.5).sum())
    hours_on = int((out["on"] > 0.5).sum())
    hours_off = int((out["on"] <= 0.5).sum())
    export_cap = float(meta.grid_export_cap_mw)
    hours_export_at_cap = int((out["grid_export_mw"] >= (export_cap - 1e-6)).sum())

    economics = compute_realized_economics(out, meta, solver_objective=obj_val)
    solver_diag = extract_solver_diagnostics(res, wallclock_s=_solve_wall_s, objective_value=obj_val)

    summary = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "scenario": asdict(meta),
        "solver": {
            "status": status_str,
            "termination": term_str,
            "objective_profit_like": obj_val,
            "objective_system_cost_equivalent": (-obj_val if math.isfinite(obj_val) else None),
            "objective": obj_val,
            "wallclock_s": solver_diag.get("wallclock_s"),
            "reported_runtime_s": solver_diag.get("reported_runtime_s"),
            "achieved_gap_rel": solver_diag.get("achieved_gap_rel"),
            "best_feasible_objective": solver_diag.get("best_feasible_objective"),
            "best_objective_bound": solver_diag.get("best_objective_bound"),
            "message": solver_diag.get("message"),
        },
        "totals": {
            "heat_demand_mwh": float(out["heat_demand_mw"].sum()),
            "H_chp_mwh": float(out["H_chp_mw"].sum()),
            "E_chp_mwh": float(out["E_chp_mw"].sum()),
            "Q_in_mwh": float(out["Q_in_mw"].sum()),
            "boiler_mwh": float(out["boiler_mw"].sum()),
            "dump_mwh": float(out["dump_mw"].sum()),
            "under_mwh": float(out["under_mw"].sum()),
            "pv_avail_mwh": float(out["pv_avail_mw"].sum()),
            "pv_used_mwh": float((out["pv_avail_mw"] - out["pv_curt_mw"]).sum()),
            "pv_curt_mwh": float(out["pv_curt_mw"].sum()),
            "E_chp_used_mwh": float((out["E_chp_mw"] - out["chp_curt_mw"]).sum()),
            "E_chp_curt_mwh": float(out["chp_curt_mw"].sum()),
            "grid_import_mwh": float(out["grid_import_mw"].sum()),
            "grid_export_mwh": float(out["grid_export_mw"].sum()),
        },
        "qc": {
            "heat_balance_residual_abs_max": float(np.max(np.abs(heat_resid))),
            "elec_balance_residual_abs_max": float(np.max(np.abs(elec_resid))),
            "hours_under_gt_0": int((out["under_mw"] > 1e-6).sum()),
            "hours_dump_gt_0": int((out["dump_mw"] > 1e-6).sum()),
            "hours_pv_curt_gt_0": int((out["pv_curt_mw"] > 1e-6).sum()),
            "hours_chp_curt_gt_0": int((out["chp_curt_mw"] > 1e-6).sum()),
            "hours_export_at_cap": hours_export_at_cap,
            "hours_on": hours_on,
            "hours_off": hours_off,
            "starts": starts,
            "stops": stops,
        },
        "economics_realized": economics,
    }

    return out, summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--tag", required=True, help="e.g. uc_paper_retained_fw")

    # storage
    ap.add_argument("--s_max", type=float, default=800.0)
    ap.add_argument("--p_ch_max", type=float, default=200.0)
    ap.add_argument("--p_dis_max", type=float, default=200.0)
    ap.add_argument("--eta_ch", type=float, default=0.95)
    ap.add_argument("--eta_dis", type=float, default=0.95)
    ap.add_argument("--loss_per_hour", type=float, default=0.001)
    ap.add_argument("--s_init", type=float, default=200.0)

    # grid + PV
    ap.add_argument("--grid_export_cap", type=float, default=60.0, help="MW export limit")
    ap.add_argument("--price_sell", type=float, default=50.0, help="$/MWh revenue for export")
    ap.add_argument("--price_buy", type=float, default=70.0, help="$/MWh cost for import")
    ap.add_argument("--pv_scale", type=float, default=1.0, help="scale pv_avail_mw")
    ap.add_argument("--e_load_base", type=float, default=20.0, help="MW constant electricity load")
    ap.add_argument("--e_load_alpha", type=float, default=0.0, help="MW per MW_heat")
    ap.add_argument("--penalty_pv_curt", type=float, default=0.1)
    ap.add_argument("--penalty_chp_curt", type=float, default=0.0)

    # costs
    ap.add_argument("--cost_q", type=float, default=15.0)
    ap.add_argument("--cost_boiler", type=float, default=60.0)
    ap.add_argument("--cost_dump", type=float, default=50.0)
    ap.add_argument("--penalty_under", type=float, default=1e6)
    ap.add_argument("--cycle_cost", type=float, default=0.01)

    # unit commitment
    ap.add_argument("--startup_cost", type=float, default=5000.0, help="$/start")
    ap.add_argument("--shutdown_cost", type=float, default=0.0, help="$/stop")
    ap.add_argument("--min_up", type=int, default=3, help="minimum ON duration (hours)")
    ap.add_argument("--min_down", type=int, default=2, help="minimum OFF duration (hours)")
    ap.add_argument("--on_init", type=int, default=0, choices=[0, 1], help="initial on-state at t=0")

    # solver (robust aliases)
    ap.add_argument(
        "--time-limit-s", "--time_limit_s", "--time-limit", "--time_limit",
        dest="time_limit_s",
        type=float,
        default=900.0,
        help="HiGHS time limit in seconds (default: 3600).",
    )
    ap.add_argument(
        "--mip-rel-gap", "--mip_rel_gap", "--mip-gap", "--mip_gap",
        dest="mip_rel_gap",
        type=float,
        default=0.2,
        help="Relative MIP gap target (default: 0.05).",
    )
    ap.add_argument("--tee", action="store_true")
    args = ap.parse_args()

    ensure_dirs()

    out, summary = solve_dispatch(
        args.scenario,
        s_max=args.s_max,
        p_ch_max=args.p_ch_max,
        p_dis_max=args.p_dis_max,
        eta_ch=args.eta_ch,
        eta_dis=args.eta_dis,
        loss_per_hour=args.loss_per_hour,
        s_init=args.s_init,
        grid_export_cap=args.grid_export_cap,
        price_sell=args.price_sell,
        price_buy=args.price_buy,
        pv_scale=args.pv_scale,
        e_load_base=args.e_load_base,
        e_load_alpha=args.e_load_alpha,
        penalty_pv_curt=args.penalty_pv_curt,
        penalty_chp_curt=args.penalty_chp_curt,
        cost_q=args.cost_q,
        cost_boiler=args.cost_boiler,
        cost_dump=args.cost_dump,
        penalty_under=args.penalty_under,
        cycle_cost=args.cycle_cost,
        startup_cost=args.startup_cost,
        shutdown_cost=args.shutdown_cost,
        min_up=args.min_up,
        min_down=args.min_down,
        on_init=args.on_init,
        time_limit_s=args.time_limit_s,
        mip_rel_gap=args.mip_rel_gap,
        tee=args.tee,
    )

    scen_dir = ROOT / "data" / "scenarios" / args.scenario
    out_dir = scen_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"dispatch_chp_storage_pv_grid__{args.tag}.parquet"
    sum_path = out_dir / f"dispatch_summary_pv_grid__{args.tag}.json"

    out.to_parquet(out_path, index=False, engine="pyarrow", compression="zstd")
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Wrote results :", out_path)
    print("Wrote summary :", sum_path)

    print("\n=== DISPATCH SUMMARY (PV+GRID+UC) ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\nHead:")
    cols = [
        "datetime_local",
        "heat_demand_mw",
        "pv_avail_mw",
        "e_load_mw",
        "mode",
        "on",
        "start",
        "stop",
        "temp_label",
        "H_chp_mw",
        "E_chp_mw",
        "grid_export_mw",
        "pv_curt_mw",
        "chp_curt_mw",
        "boiler_mw",
        "S_mwh",
        "heat_balance_residual",
        "elec_balance_residual",
    ]
    print(out[cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()