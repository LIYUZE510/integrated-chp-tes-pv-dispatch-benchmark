from __future__ import annotations

import pyomo.environ as pyo


def build_milp():
    """
    Minimal MILP:
        min  2x + 3y
        s.t. x + y >= 1
             x,y binary
    Optimal solution: x=1, y=0, obj=2
    """
    m = pyo.ConcreteModel()
    m.x = pyo.Var(domain=pyo.Binary)
    m.y = pyo.Var(domain=pyo.Binary)
    m.obj = pyo.Objective(expr=2 * m.x + 3 * m.y, sense=pyo.minimize)
    m.c1 = pyo.Constraint(expr=m.x + m.y >= 1)
    return m


def main():
    # Prefer APPSI HiGHS (uses highspy). This is what we'll use later for MPC re-solves.
    solver_name = "appsi_highs"
    solver = pyo.SolverFactory(solver_name)

    print(f"SolverFactory('{solver_name}') -> {type(solver)}")
    try:
        avail = solver.available(exception_flag=False)
    except TypeError:
        # some solver plugins use different signature
        avail = solver.available()
    print("Available:", bool(avail), "| raw:", avail)

    if not bool(avail):
        print("\n[FAIL] appsi_highs not available.")
        print("Fix options (try in this order):")
        print("  1) python -m pyomo build-extensions")
        print("  2) conda install -y -c conda-forge highspy highs")
        return

    m = build_milp()

    try:
        res = solver.solve(m)
    except Exception as e:
        print("\n[FAIL] Solve crashed:", repr(e))
        print("Try: python -m pyomo build-extensions")
        return

    # APPSI results object typically has termination_condition, best_feasible_objective, etc.
    term = getattr(res, "termination_condition", None)
    best_obj = getattr(res, "best_feasible_objective", None)

    print("Result type:", type(res))
    print("termination_condition:", term)
    if best_obj is not None:
        print("best_feasible_objective:", best_obj)

    print("Objective value (from model):", pyo.value(m.obj))
    print("x =", pyo.value(m.x), "y =", pyo.value(m.y))
    print("constraint x+y-1 =", pyo.value(m.x + m.y - 1))

    # Basic correctness check
    ok = (abs(pyo.value(m.obj) - 2.0) < 1e-6) and (pyo.value(m.x) == 1) and (pyo.value(m.y) == 0)
    print("Correctness check:", "PASS" if ok else "WARN")


if __name__ == "__main__":
    main()