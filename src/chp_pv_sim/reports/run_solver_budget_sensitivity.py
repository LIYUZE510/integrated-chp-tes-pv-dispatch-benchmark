from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _tagged_paths(results_dir: Path, tag: str) -> Tuple[Path, Path]:
    return (
        results_dir / f"dispatch_summary_pv_grid__{tag}.json",
        results_dir / f"dispatch_chp_storage_pv_grid__{tag}.parquet",
    )


def _run(cmd: list[str]) -> None:
    print("\n[RUN]", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _extract_kpis(summary: Dict[str, Any]) -> Dict[str, Any]:
    totals = summary.get("totals", {}) or {}
    econ = summary.get("economics_realized", {}) or {}
    solver = summary.get("solver", {}) or {}

    heat = _safe_float(totals.get("heat_demand_mwh"))
    boiler = _safe_float(totals.get("boiler_mwh"))
    dump = _safe_float(totals.get("dump_mwh"))
    gimp = _safe_float(totals.get("grid_import_mwh"))
    gexp = _safe_float(totals.get("grid_export_mwh"))

    boiler_share = (boiler / heat * 100.0) if heat > 1e-9 else float("nan")
    dump_share = (dump / heat * 100.0) if heat > 1e-9 else float("nan")

    system_cost_realized = econ.get("system_cost_realized")
    if system_cost_realized is None:
        system_cost_realized = summary.get("system_cost_realized")
    system_cost_realized = _safe_float(system_cost_realized)

    termination = solver.get("termination")
    if termination is None and "window_termination_counts" in solver:
        termination = "; ".join(
            f"{k}:{v}" for k, v in (solver.get("window_termination_counts") or {}).items()
        )

    # UC-style fields
    wallclock = solver.get("wallclock_s")
    gap = solver.get("achieved_gap_rel")

    # MPC-style aggregated fields
    if wallclock is None:
        wallclock = solver.get("wallclock_s_total")
    if gap is None:
        gap = solver.get("achieved_gap_rel_mean")

    gap_max = solver.get("achieved_gap_rel_max")
    if gap_max is None:
        gap_max = gap

    return {
        "system_cost_realized": system_cost_realized,
        "boiler_share_pct": boiler_share,
        "dump_share_pct": dump_share,
        "net_export_mwh": gexp - gimp,
        "termination": termination,
        "achieved_gap_rel": _safe_float(gap),
        "achieved_gap_rel_max": _safe_float(gap_max),
        "wallclock_s": _safe_float(wallclock),
    }


@dataclass(frozen=True)
class BudgetPair:
    label: str
    uc_time_limit_s: int
    mpc_time_limit_window_s: int
    mip_rel_gap: float = 0.2


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run a minimal solver-budget sensitivity experiment for the matched UC/MPC case."
    )
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--e-load", type=float, default=20.0)
    ap.add_argument("--dump-cost", type=float, default=50.0)
    ap.add_argument("--startup-cost", type=float, default=5000.0)
    ap.add_argument("--min-up", type=int, default=3)
    ap.add_argument("--min-down", type=int, default=2)
    ap.add_argument("--horizon", type=int, default=48)
    ap.add_argument("--step", type=int, default=24)
    ap.add_argument("--force", action="store_true", help="Re-run even if tagged outputs already exist")
    args = ap.parse_args()

    from chp_pv_sim.paths import ROOT

    scen_dir = ROOT / "data" / "scenarios" / args.scenario
    res_dir = scen_dir / "results"
    _ensure_dir(res_dir)

    out_dir = ROOT / "reports" / "robustness"
    _ensure_dir(out_dir)

    budgets = [
        BudgetPair(label="low", uc_time_limit_s=900, mpc_time_limit_window_s=120),
        BudgetPair(label="medium", uc_time_limit_s=1800, mpc_time_limit_window_s=300),
        BudgetPair(label="high", uc_time_limit_s=3600, mpc_time_limit_window_s=600),
    ]

    rows: list[Dict[str, Any]] = []
    pair_rows: list[Dict[str, Any]] = []

    for b in budgets:
        if b.label == "low":
            uc_tag = "uc_paper_retained_fw"
            mpc_tag = "mpc_paper_retained_fw"
        else:
            uc_tag = f"uc_eload{int(args.e_load)}MW_dump{int(args.dump_cost)}_T{b.uc_time_limit_s:04d}_gap{str(b.mip_rel_gap).replace('.', 'p')}"
            mpc_tag = f"mpc_eload{int(args.e_load)}MW_dump{int(args.dump_cost)}_Tw{b.mpc_time_limit_window_s:04d}_gap{str(b.mip_rel_gap).replace('.', 'p')}"

        uc_sum_path, uc_parq_path = _tagged_paths(res_dir, uc_tag)
        if b.label == "low":
            if not uc_sum_path.exists() or not uc_parq_path.exists():
                raise FileNotFoundError(
                    f"Low-budget baseline missing. Expected: {uc_sum_path} and {uc_parq_path}"
                )
            print(f"[USE BASELINE] UC low budget -> {uc_sum_path.name}")
        elif args.force or (not uc_sum_path.exists()):
            cmd = [
                sys.executable,
                "-m",
                "chp_pv_sim.models.chp_week_storage_pv_grid_dispatch",
                "--scenario", args.scenario,
                "--tag", uc_tag,
                "--e_load_base", str(args.e_load),
                "--cost_dump", str(args.dump_cost),
                "--startup_cost", str(args.startup_cost),
                "--min_up", str(args.min_up),
                "--min_down", str(args.min_down),
                "--time-limit-s", str(b.uc_time_limit_s),
                "--mip-rel-gap", str(b.mip_rel_gap),
            ]
            _run(cmd)
            if not uc_sum_path.exists() or not uc_parq_path.exists():
                raise FileNotFoundError(f"After UC run, missing outputs: {uc_sum_path} or {uc_parq_path}")
        else:
            print(f"[SKIP] Existing UC artifact: {uc_sum_path.name}")

        mpc_sum_path, mpc_parq_path = _tagged_paths(res_dir, mpc_tag)
        if b.label == "low":
            if not mpc_sum_path.exists() or not mpc_parq_path.exists():
                raise FileNotFoundError(
                    f"Low-budget baseline missing. Expected: {mpc_sum_path} and {mpc_parq_path}"
                )
            print(f"[USE BASELINE] MPC low budget -> {mpc_sum_path.name}")
        elif args.force or (not mpc_sum_path.exists()):
            cmd = [
                sys.executable,
                "-m",
                "chp_pv_sim.models.chp_week_mpc_pv_grid_dispatch",
                "--scenario", args.scenario,
                "--tag", mpc_tag,
                "--horizon", str(args.horizon),
                "--step", str(args.step),
                "--e_load_base", str(args.e_load),
                "--cost_dump", str(args.dump_cost),
                "--startup_cost", str(args.startup_cost),
                "--min_up", str(args.min_up),
                "--min_down", str(args.min_down),
                "--time-limit-window", str(b.mpc_time_limit_window_s),
                "--mip-rel-gap", str(b.mip_rel_gap),
            ]
            _run(cmd)
            if not mpc_sum_path.exists() or not mpc_parq_path.exists():
                raise FileNotFoundError(f"After MPC run, missing outputs: {mpc_sum_path} or {mpc_parq_path}")
        else:
                print(f"[SKIP] Existing MPC artifact: {mpc_sum_path.name}")
        uc_summary = _read_json(uc_sum_path)
        mpc_summary = _read_json(mpc_sum_path)

        uc_kpis = _extract_kpis(uc_summary)
        mpc_kpis = _extract_kpis(mpc_summary)

        rows.append({"strategy": "UC", "budget": b.label, "tag": uc_tag, **uc_kpis})
        rows.append({"strategy": "MPC", "budget": b.label, "tag": mpc_tag, **mpc_kpis})
        pair_rows.append(
            {     
                "budget": b.label,
                "uc_time_limit_s": b.uc_time_limit_s,
                "mpc_window_time_s": b.mpc_time_limit_window_s,
                "uc_system_cost": uc_kpis["system_cost_realized"],
                "mpc_system_cost": mpc_kpis["system_cost_realized"],
                "mpc_lower_cost": bool(mpc_kpis["system_cost_realized"] < uc_kpis["system_cost_realized"]),
                "uc_boiler_share_pct": uc_kpis["boiler_share_pct"],
                "mpc_boiler_share_pct": mpc_kpis["boiler_share_pct"],
                "mpc_lower_boiler_share": bool(mpc_kpis["boiler_share_pct"] < uc_kpis["boiler_share_pct"]),
                "uc_dump_share_pct": uc_kpis["dump_share_pct"],
                "mpc_dump_share_pct": mpc_kpis["dump_share_pct"],
                "mpc_higher_dump_share": bool(mpc_kpis["dump_share_pct"] > uc_kpis["dump_share_pct"]),
                "uc_net_export_mwh": uc_kpis["net_export_mwh"],
                "mpc_net_export_mwh": mpc_kpis["net_export_mwh"],
                "mpc_higher_net_export": bool(mpc_kpis["net_export_mwh"] > uc_kpis["net_export_mwh"]),
                "uc_termination": uc_kpis["termination"],
                "mpc_termination": mpc_kpis["termination"],
                "uc_gap": uc_kpis["achieved_gap_rel"],
                "mpc_gap_mean": mpc_kpis["achieved_gap_rel"],
                "mpc_gap_max": mpc_kpis["achieved_gap_rel_max"],
                "uc_runtime_s": uc_kpis["wallclock_s"],
                "mpc_runtime_s": mpc_kpis["wallclock_s"],
            }
        )

    df_long = pd.DataFrame(rows)
    df_pair = pd.DataFrame(pair_rows)

    long_csv = out_dir / "solver_budget_sensitivity_long.csv"
    long_md = out_dir / "solver_budget_sensitivity_long.md"
    pair_csv = out_dir / "solver_budget_sensitivity_pair_summary.csv"
    pair_md = out_dir / "solver_budget_sensitivity_pair_summary.md"

    df_long.to_csv(long_csv, index=False)
    df_pair.to_csv(pair_csv, index=False)

    try:
        long_md.write_text(df_long.to_markdown(index=False), encoding="utf-8")
        pair_md.write_text(df_pair.to_markdown(index=False), encoding="utf-8")
    except Exception:
        long_md.write_text(df_long.to_string(index=False), encoding="utf-8")
        pair_md.write_text(df_pair.to_string(index=False), encoding="utf-8")

    print("\n=== Solver budget sensitivity written ===")
    print("LONG CSV:", long_csv)
    print("PAIR CSV:", pair_csv)
    print("\nLong preview:\n", df_long.to_string(index=False))
    print("\nPair summary preview:\n", df_pair.to_string(index=False))


if __name__ == "__main__":
    main()