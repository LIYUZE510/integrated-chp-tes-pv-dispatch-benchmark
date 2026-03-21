from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from chp_pv_sim.paths import PROCESSED_DIR, ensure_dirs


IN_HEAT = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_heat_segments_consistent.parquet"
IN_POWER = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_power_segments_consistent.parquet"


@dataclass
class SolveResult:
    h_req: float
    feasible: bool
    mismatch_abs: float
    mode: str
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

    if "segment_infeasible" in heat.columns:
        heat = heat[~heat["segment_infeasible"]].copy()
    if "segment_infeasible" in power.columns:
        power = power[~power["segment_infeasible"]].copy()

    # required columns
    need_h = ["temp_label", "segment", "k_hq", "b_hq", "h_lb_eff", "h_ub_eff", "q_lb_eff", "q_ub_eff"]
    need_e = ["temp_label", "segment", "k_eh", "b_eh", "e_lb_eff", "e_ub_eff", "q_lb_eff", "q_ub_eff"]
    for c in need_h:
        if c not in heat.columns:
            raise KeyError(f"heat table missing col: {c}")
    for c in need_e:
        if c not in power.columns:
            raise KeyError(f"power table missing col: {c}")

    # numeric
    for c in ["k_hq", "b_hq", "h_lb_eff", "h_ub_eff", "q_lb_eff", "q_ub_eff"]:
        heat[c] = pd.to_numeric(heat[c], errors="raise")
    for c in ["k_eh", "b_eh", "e_lb_eff", "e_ub_eff", "q_lb_eff", "q_ub_eff"]:
        power[c] = pd.to_numeric(power[c], errors="raise")

    # bounds
    H_max = float(heat["h_ub_eff"].max())
    E_max = float(power["e_ub_eff"].max())
    Q_max = float(max(heat["q_ub_eff"].max(), power["q_ub_eff"].max()))

    # invert line:
    # Heat table numerics imply Q = k_hq * H + b_hq  => H = (Q - b)/k
    heat["a_h"] = 1.0 / heat["k_hq"]
    heat["c_h"] = -heat["b_hq"] / heat["k_hq"]
    # Power: Q = k_eh * E + b_eh => E = (Q - b)/k
    power["a_e"] = 1.0 / power["k_eh"]
    power["c_e"] = -power["b_eh"] / power["k_eh"]

    # Big-M (tight-ish)
    M_H = H_max
    M_E = E_max
    M_Q = Q_max
    M_eq_H = H_max + 50.0
    M_eq_E = E_max + 50.0

    HS = [(r.temp_label, int(r.segment)) for r in heat.itertuples(index=False)]
    ES = [(r.temp_label, int(r.segment)) for r in power.itertuples(index=False)]

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

    m = pyo.ConcreteModel("CHP_single_period_frontier")

    m.T = pyo.Set(initialize=temps)
    m.HS = pyo.Set(initialize=HS, dimen=2)
    m.ES = pyo.Set(initialize=ES, dimen=2)

    m.H = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0.0, H_max))
    m.E = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0.0, E_max))
    m.Q = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0.0, Q_max))

    # OFF mode
    m.y = pyo.Var(m.T, domain=pyo.Binary)
    m.y_off = pyo.Var(domain=pyo.Binary)

    # segment selections
    m.zH = pyo.Var(m.HS, domain=pyo.Binary)
    m.zE = pyo.Var(m.ES, domain=pyo.Binary)

    # Heat mismatch slack (MW)
    m.h_over = pyo.Var(domain=pyo.NonNegativeReals)   # oversupply
    m.h_under = pyo.Var(domain=pyo.NonNegativeReals)  # undersupply

    # Choose either OFF or exactly one temp
    m.one_mode = pyo.Constraint(expr=sum(m.y[t] for t in m.T) + m.y_off == 1)

    # Segment selections tied to temp selection
    def _heat_select_rule(mm, t):
        return sum(mm.zH[tt, s] for (tt, s) in mm.HS if tt == t) == mm.y[t]

    def _power_select_rule(mm, t):
        return sum(mm.zE[tt, s] for (tt, s) in mm.ES if tt == t) == mm.y[t]

    m.heat_select = pyo.Constraint(m.T, rule=_heat_select_rule)
    m.power_select = pyo.Constraint(m.T, rule=_power_select_rule)

    # OFF implies H=E=Q=0 (tighten with <=)
    m.off_H = pyo.Constraint(expr=m.H <= H_max * (1 - m.y_off))
    m.off_E = pyo.Constraint(expr=m.E <= E_max * (1 - m.y_off))
    m.off_Q = pyo.Constraint(expr=m.Q <= Q_max * (1 - m.y_off))

    # Heat balance with slack: H + under - over = H_req
    m.heat_balance = pyo.Constraint(expr=m.H + m.h_under - m.h_over == float(h_req))

    # Heat segment constraints
    def _h_lb(mm, t, s):
        return mm.H >= h_lb[(t, s)] - M_H * (1 - mm.zH[t, s])

    def _h_ub(mm, t, s):
        return mm.H <= h_ub[(t, s)] + M_H * (1 - mm.zH[t, s])

    def _qh_lb(mm, t, s):
        return mm.Q >= qh_lb[(t, s)] - M_Q * (1 - mm.zH[t, s])

    def _qh_ub(mm, t, s):
        return mm.Q <= qh_ub[(t, s)] + M_Q * (1 - mm.zH[t, s])

    def _h_eq_ub(mm, t, s):
        return mm.H - (a_h[(t, s)] * mm.Q + c_h[(t, s)]) <= M_eq_H * (1 - mm.zH[t, s])

    def _h_eq_lb(mm, t, s):
        return mm.H - (a_h[(t, s)] * mm.Q + c_h[(t, s)]) >= -M_eq_H * (1 - mm.zH[t, s])

    m.h_lb_con = pyo.Constraint(m.HS, rule=_h_lb)
    m.h_ub_con = pyo.Constraint(m.HS, rule=_h_ub)
    m.qh_lb_con = pyo.Constraint(m.HS, rule=_qh_lb)
    m.qh_ub_con = pyo.Constraint(m.HS, rule=_qh_ub)
    m.h_eq_ub = pyo.Constraint(m.HS, rule=_h_eq_ub)
    m.h_eq_lb = pyo.Constraint(m.HS, rule=_h_eq_lb)

    # Power segment constraints
    def _e_lb(mm, t, s):
        return mm.E >= e_lb[(t, s)] - M_E * (1 - mm.zE[t, s])

    def _e_ub(mm, t, s):
        return mm.E <= e_ub[(t, s)] + M_E * (1 - mm.zE[t, s])

    def _qe_lb(mm, t, s):
        return mm.Q >= qe_lb[(t, s)] - M_Q * (1 - mm.zE[t, s])

    def _qe_ub(mm, t, s):
        return mm.Q <= qe_ub[(t, s)] + M_Q * (1 - mm.zE[t, s])

    def _e_eq_ub(mm, t, s):
        return mm.E - (a_e[(t, s)] * mm.Q + c_e[(t, s)]) <= M_eq_E * (1 - mm.zE[t, s])

    def _e_eq_lb(mm, t, s):
        return mm.E - (a_e[(t, s)] * mm.Q + c_e[(t, s)]) >= -M_eq_E * (1 - mm.zE[t, s])

    m.e_lb_con = pyo.Constraint(m.ES, rule=_e_lb)
    m.e_ub_con = pyo.Constraint(m.ES, rule=_e_ub)
    m.qe_lb_con = pyo.Constraint(m.ES, rule=_qe_lb)
    m.qe_ub_con = pyo.Constraint(m.ES, rule=_qe_ub)
    m.e_eq_ub = pyo.Constraint(m.ES, rule=_e_eq_ub)
    m.e_eq_lb = pyo.Constraint(m.ES, rule=_e_eq_lb)

    # Objective: prioritize matching heat (huge penalty), then maximize E
    penalty = 1e4
    m.obj = pyo.Objective(expr=m.E - penalty * (m.h_over + m.h_under) - 1e-6 * m.Q, sense=pyo.maximize)

    return m


def solve_once(h_req: float) -> SolveResult:
    heat = pd.read_parquet(IN_HEAT)
    power = pd.read_parquet(IN_POWER)

    m = build_model(h_req=h_req, heat=heat, power=power)

    solver = pyo.SolverFactory("appsi_highs")
    res = solver.solve(m)

    term = getattr(res.solver, "termination_condition", None)
    status = getattr(res.solver, "status", None)

    feasible = term in {TerminationCondition.optimal, TerminationCondition.feasible}

    if not feasible:
        return SolveResult(
            h_req=h_req,
            feasible=False,
            mismatch_abs=float("nan"),
            mode="NA",
            temp=None,
            heat_seg=None,
            power_seg=None,
            H=None,
            E=None,
            Q=None,
            status=str(status),
            termination=str(term),
        )

    yoff = _val(m.y_off)
    if yoff > 0.5:
        mode = "OFF"
        temp = None
    else:
        mode = "ON"
        y_vals = {t: _val(m.y[t]) for t in m.T}
        temp = max(y_vals, key=y_vals.get)

    heat_choice = [(t, s) for (t, s) in m.HS if _val(m.zH[t, s]) > 0.5]
    power_choice = [(t, s) for (t, s) in m.ES if _val(m.zE[t, s]) > 0.5]

    H = _val(m.H)
    E = _val(m.E)
    Q = _val(m.Q)
    mismatch = abs(_val(m.h_over) + _val(m.h_under))

    return SolveResult(
        h_req=h_req,
        feasible=True,
        mismatch_abs=mismatch,
        mode=mode,
        temp=temp,
        heat_seg=heat_choice[0] if heat_choice else None,
        power_seg=power_choice[0] if power_choice else None,
        H=H,
        E=E,
        Q=Q,
        status=str(status),
        termination=str(term),
    )


def main() -> None:
    ensure_dirs()

    if not IN_HEAT.exists() or not IN_POWER.exists():
        raise FileNotFoundError("Missing consistent segment tables. Run kaz_chpp_make_consistent_segments first.")

    test_heat_reqs = [0.0, 10.0, 50.0, 100.0, 150.0, 180.0]

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

        print("Mode               :", r.mode)
        print("Chosen temp_label  :", r.temp)
        print("Chosen heat seg    :", r.heat_seg)
        print("Chosen power seg   :", r.power_seg)
        print(f"Solution: H={r.H:.6g}, E={r.E:.6g}, Q={r.Q:.6g}, mismatch={r.mismatch_abs:.6g}")


if __name__ == "__main__":
    main()