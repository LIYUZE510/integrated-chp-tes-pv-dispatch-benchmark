from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

from chp_pv_sim.paths import PROCESSED_DIR, ensure_dirs


IN_HEAT = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_heat_segments_consistent.parquet"
IN_POWER = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_power_segments_consistent.parquet"


@dataclass
class SolveResult:
    h_req: float
    feasible: bool
    temp: str | None
    heat_seg: tuple[str, int] | None
    power_seg: tuple[str, int] | None
    H: float | None
    E: float | None
    Q: float | None
    status: str
    termination: str


def _val(x) -> float:
    return float(pyo.value(x))


def build_model(h_req: float, heat: pd.DataFrame, power: pd.DataFrame) -> pyo.ConcreteModel:
    # Use only common temperature labels (exclude KOND automatically)
    temps = sorted(set(heat["temp_label"]).intersection(set(power["temp_label"])))
    if not temps:
        raise RuntimeError("No common temp_label between heat and power segment tables.")

    heat = heat[heat["temp_label"].isin(temps)].copy()
    power = power[power["temp_label"].isin(temps)].copy()

    # Filter any infeasible segments if present (should be none)
    if "segment_infeasible" in heat.columns:
        heat = heat[~heat["segment_infeasible"]].copy()
    if "segment_infeasible" in power.columns:
        power = power[~power["segment_infeasible"]].copy()

    # Required columns
    need_h = ["temp_label", "segment", "k_hq", "b_hq", "h_lb_eff", "h_ub_eff", "q_lb_eff", "q_ub_eff"]
    need_e = ["temp_label", "segment", "k_eh", "b_eh", "e_lb_eff", "e_ub_eff", "q_lb_eff", "q_ub_eff"]
    for c in need_h:
        if c not in heat.columns:
            raise KeyError(f"heat table missing col: {c}")
    for c in need_e:
        if c not in power.columns:
            raise KeyError(f"power table missing col: {c}")

    # Make numeric
    for c in ["k_hq", "b_hq", "h_lb_eff", "h_ub_eff", "q_lb_eff", "q_ub_eff"]:
        heat[c] = pd.to_numeric(heat[c], errors="raise")
    for c in ["k_eh", "b_eh", "e_lb_eff", "e_ub_eff", "q_lb_eff", "q_ub_eff"]:
        power[c] = pd.to_numeric(power[c], errors="raise")

    # Global bounds for tighter big-M
    H_max = float(heat["h_ub_eff"].max())
    E_max = float(power["e_ub_eff"].max())
    Q_max = float(max(heat["q_ub_eff"].max(), power["q_ub_eff"].max()))

    # Derived invert coefficients (H = a_h * Q + c_h ; E = a_e * Q + c_e)
    heat["a_h"] = 1.0 / heat["k_hq"]
    heat["c_h"] = -heat["b_hq"] / heat["k_hq"]
    power["a_e"] = 1.0 / power["k_eh"]
    power["c_e"] = -power["b_eh"] / power["k_eh"]

    a_h_max = float(heat["a_h"].max())
    c_h_min = float(heat["c_h"].min())
    c_h_max = float(heat["c_h"].max())
    a_e_max = float(power["a_e"].max())
    c_e_min = float(power["c_e"].min())
    c_e_max = float(power["c_e"].max())

    # Big-M for equality envelopes (tight but safe)
    M_H = H_max
    M_E = E_max
    M_Q = Q_max
    M_eq_H = max(a_h_max * Q_max + c_h_max, H_max - c_h_min) + 10.0
    M_eq_E = max(a_e_max * Q_max + c_e_max, E_max - c_e_min) + 10.0

    # Index sets
    HS = [(r.temp_label, int(r.segment)) for r in heat.itertuples(index=False)]
    ES = [(r.temp_label, int(r.segment)) for r in power.itertuples(index=False)]

    # Param dicts
    h_lb = {(t, s): float(row["h_lb_eff"]) for (t, s), row in zip(HS, heat.to_dict("records"))}
    h_ub = {(t, s): float(row["h_ub_eff"]) for (t, s), row in zip(HS, heat.to_dict("records"))}
    qh_lb = {(t, s): float(row["q_lb_eff"]) for (t, s), row in zip(HS, heat.to_dict("records"))}
    qh_ub = {(t, s): float(row["q_ub_eff"]) for (t, s), row in zip(HS, heat.to_dict("records"))}
    a_h = {(t, s): float(row["a_h"]) for (t, s), row in zip(HS, heat.to_dict("records"))}
    c_h = {(t, s): float(row["c_h"]) for (t, s), row in zip(HS, heat.to_dict("records"))}

    e_lb = {(t, s): float(row["e_lb_eff"]) for (t, s), row in zip(ES, power.to_dict("records"))}
    e_ub = {(t, s): float(row["e_ub_eff"]) for (t, s), row in zip(ES, power.to_dict("records"))}
    qe_lb = {(t, s): float(row["q_lb_eff"]) for (t, s), row in zip(ES, power.to_dict("records"))}
    qe_ub = {(t, s): float(row["q_ub_eff"]) for (t, s), row in zip(ES, power.to_dict("records"))}
    a_e = {(t, s): float(row["a_e"]) for (t, s), row in zip(ES, power.to_dict("records"))}
    c_e = {(t, s): float(row["c_e"]) for (t, s), row in zip(ES, power.to_dict("records"))}

    # Build model
    m = pyo.ConcreteModel("CHP_single_period")

    m.T = pyo.Set(initialize=temps)
    m.HS = pyo.Set(initialize=HS, dimen=2)
    m.ES = pyo.Set(initialize=ES, dimen=2)

    m.H = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0.0, H_max))
    m.E = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0.0, E_max))
    m.Q = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0.0, Q_max))

    m.y = pyo.Var(m.T, domain=pyo.Binary)          # choose one temperature line
    m.zH = pyo.Var(m.HS, domain=pyo.Binary)        # choose one heat segment under chosen temp
    m.zE = pyo.Var(m.ES, domain=pyo.Binary)        # choose one power segment under chosen temp

    # Exactly one temp line
    m.one_temp = pyo.Constraint(expr=sum(m.y[t] for t in m.T) == 1)

    # Segment selection tied to temperature choice
    def _heat_select_rule(mm, t):
        return sum(mm.zH[tt, s] for (tt, s) in mm.HS if tt == t) == mm.y[t]

    def _power_select_rule(mm, t):
        return sum(mm.zE[tt, s] for (tt, s) in mm.ES if tt == t) == mm.y[t]

    m.heat_select = pyo.Constraint(m.T, rule=_heat_select_rule)
    m.power_select = pyo.Constraint(m.T, rule=_power_select_rule)

    # Heat segment constraints: bounds + H = a_h*Q + c_h
    def _heat_bounds_rule(mm, t, s):
        return mm.H >= h_lb[(t, s)] - M_H * (1 - mm.zH[t, s])

    def _heat_ub_rule(mm, t, s):
        return mm.H <= h_ub[(t, s)] + M_H * (1 - mm.zH[t, s])

    def _heat_q_lb_rule(mm, t, s):
        return mm.Q >= qh_lb[(t, s)] - M_Q * (1 - mm.zH[t, s])

    def _heat_q_ub_rule(mm, t, s):
        return mm.Q <= qh_ub[(t, s)] + M_Q * (1 - mm.zH[t, s])

    def _heat_eq_ub_rule(mm, t, s):
        return mm.H - (a_h[(t, s)] * mm.Q + c_h[(t, s)]) <= M_eq_H * (1 - mm.zH[t, s])

    def _heat_eq_lb_rule(mm, t, s):
        return mm.H - (a_h[(t, s)] * mm.Q + c_h[(t, s)]) >= -M_eq_H * (1 - mm.zH[t, s])

    m.h_lb_con = pyo.Constraint(m.HS, rule=_heat_bounds_rule)
    m.h_ub_con = pyo.Constraint(m.HS, rule=_heat_ub_rule)
    m.qh_lb_con = pyo.Constraint(m.HS, rule=_heat_q_lb_rule)
    m.qh_ub_con = pyo.Constraint(m.HS, rule=_heat_q_ub_rule)
    m.h_eq_ub = pyo.Constraint(m.HS, rule=_heat_eq_ub_rule)
    m.h_eq_lb = pyo.Constraint(m.HS, rule=_heat_eq_lb_rule)

    # Power segment constraints: bounds + E = a_e*Q + c_e
    def _e_lb_rule(mm, t, s):
        return mm.E >= e_lb[(t, s)] - M_E * (1 - mm.zE[t, s])

    def _e_ub_rule(mm, t, s):
        return mm.E <= e_ub[(t, s)] + M_E * (1 - mm.zE[t, s])

    def _qe_lb_rule(mm, t, s):
        return mm.Q >= qe_lb[(t, s)] - M_Q * (1 - mm.zE[t, s])

    def _qe_ub_rule(mm, t, s):
        return mm.Q <= qe_ub[(t, s)] + M_Q * (1 - mm.zE[t, s])

    def _e_eq_ub_rule(mm, t, s):
        return mm.E - (a_e[(t, s)] * mm.Q + c_e[(t, s)]) <= M_eq_E * (1 - mm.zE[t, s])

    def _e_eq_lb_rule(mm, t, s):
        return mm.E - (a_e[(t, s)] * mm.Q + c_e[(t, s)]) >= -M_eq_E * (1 - mm.zE[t, s])

    m.e_lb_con = pyo.Constraint(m.ES, rule=_e_lb_rule)
    m.e_ub_con = pyo.Constraint(m.ES, rule=_e_ub_rule)
    m.qe_lb_con = pyo.Constraint(m.ES, rule=_qe_lb_rule)
    m.qe_ub_con = pyo.Constraint(m.ES, rule=_qe_ub_rule)
    m.e_eq_ub = pyo.Constraint(m.ES, rule=_e_eq_ub_rule)
    m.e_eq_lb = pyo.Constraint(m.ES, rule=_e_eq_lb_rule)

    # Heat requirement (MW or MWh/h)
    m.heat_req = pyo.Constraint(expr=m.H >= float(h_req))

    # Objective: maximize electricity output (with tiny tie-break on Q)
    m.obj = pyo.Objective(expr=m.E - 1e-6 * m.Q, sense=pyo.maximize)

    return m


def solve_once(h_req: float) -> SolveResult:
    heat = pd.read_parquet(IN_HEAT)
    power = pd.read_parquet(IN_POWER)

    m = build_model(h_req=h_req, heat=heat, power=power)

    solver = pyo.SolverFactory("appsi_highs")
    res = solver.solve(m)

    status = getattr(res.solver, "status", None)
    term = getattr(res.solver, "termination_condition", None)

    status_s = str(status)
    term_s = str(term)

    feasible = term in {TerminationCondition.optimal, TerminationCondition.feasible}

    if not feasible:
        return SolveResult(
            h_req=h_req,
            feasible=False,
            temp=None,
            heat_seg=None,
            power_seg=None,
            H=None,
            E=None,
            Q=None,
            status=status_s,
            termination=term_s,
        )

    # chosen temp
    y_vals = {t: _val(m.y[t]) for t in m.T}
    temp = max(y_vals, key=y_vals.get)

    heat_choice = [(t, s) for (t, s) in m.HS if _val(m.zH[t, s]) > 0.5]
    power_choice = [(t, s) for (t, s) in m.ES if _val(m.zE[t, s]) > 0.5]

    H = _val(m.H)
    E = _val(m.E)
    Q = _val(m.Q)

    return SolveResult(
        h_req=h_req,
        feasible=True,
        temp=temp,
        heat_seg=heat_choice[0] if heat_choice else None,
        power_seg=power_choice[0] if power_choice else None,
        H=H,
        E=E,
        Q=Q,
        status=status_s,
        termination=term_s,
    )


def main() -> None:
    ensure_dirs()

    if not IN_HEAT.exists() or not IN_POWER.exists():
        raise FileNotFoundError("Missing consistent segment tables. Run kaz_chpp_make_consistent_segments first.")

    # You can change these test points; keep within approx [0, 180]
    test_heat_reqs = [50.0, 100.0, 150.0]

    print("Using:")
    print("  -", IN_HEAT)
    print("  -", IN_POWER)

    for h_req in test_heat_reqs:
        print("\n==============================")
        print(f"Test: H_req = {h_req:.3f}")
        r = solve_once(h_req=h_req)
        print("Solver status      :", r.status)
        print("Termination        :", r.termination)
        print("Feasible           :", r.feasible)
        if not r.feasible:
            continue

        print("Chosen temp_label  :", r.temp)
        print("Chosen heat seg    :", r.heat_seg)
        print("Chosen power seg   :", r.power_seg)
        print(f"Solution: H={r.H:.6g}, E={r.E:.6g}, Q={r.Q:.6g}")
        print("Check: H >= H_req  :", r.H >= h_req - 1e-6)


if __name__ == "__main__":
    main()