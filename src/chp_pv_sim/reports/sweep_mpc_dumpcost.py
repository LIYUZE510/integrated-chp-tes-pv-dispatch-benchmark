from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from chp_pv_sim.paths import ROOT, REPORTS_DIR, ensure_dirs
from chp_pv_sim.reports.result_catalog import make_mpc_tag


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))



def _plot(x, y, title: str, ylabel: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.plot(x, y, marker="o")
    ax.set_title(title)
    ax.set_xlabel("cost_dump")
    ax.set_ylabel(ylabel)
    fig.tight_layout()
    fig.savefig(out, dpi=220)
    plt.close(fig)


def _solver_profit_like(solver: Dict[str, Any]) -> float:
    for key in ["objective_profit_like", "objective_implemented", "objective"]:
        try:
            val = float(solver.get(key, np.nan))
            if np.isfinite(val):
                return val
        except Exception:
            pass
    return float("nan")


def _solver_system_cost(solver: Dict[str, Any]) -> float:
    try:
        val = float(solver.get("objective_system_cost_equivalent", np.nan))
        if np.isfinite(val):
            return val
    except Exception:
        pass
    profit = _solver_profit_like(solver)
    return -profit if np.isfinite(profit) else float("nan")


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--eload", type=float, default=20.0)
    ap.add_argument("--dump_costs", default="5,20,50,100")

    # MPC + UC params (keep consistent with your experiments)
    ap.add_argument("--horizon", type=int, default=48)
    ap.add_argument("--step", type=int, default=24)
    ap.add_argument("--time_limit_window", type=float, default=120.0)
    ap.add_argument("--mip_rel_gap", type=float, default=0.2)

    ap.add_argument("--grid_export_cap", type=float, default=60.0)
    ap.add_argument("--startup_cost", type=float, default=5000.0)
    ap.add_argument("--shutdown_cost", type=float, default=0.0)
    ap.add_argument("--min_up", type=int, default=3)
    ap.add_argument("--min_down", type=int, default=2)
    ap.add_argument("--on_init", type=int, default=0, choices=[0, 1])

    ap.add_argument("--price_sell", type=float, default=50.0)
    ap.add_argument("--price_buy", type=float, default=70.0)
    ap.add_argument("--pv_scale", type=float, default=1.0)
    ap.add_argument("--e_load_alpha", type=float, default=0.0)

    ap.add_argument("--penalty_pv_curt", type=float, default=0.1)
    ap.add_argument("--penalty_chp_curt", type=float, default=0.0)

    ap.add_argument("--cost_q", type=float, default=15.0)
    ap.add_argument("--cost_boiler", type=float, default=60.0)
    ap.add_argument("--penalty_under", type=float, default=1e6)
    ap.add_argument("--cycle_cost", type=float, default=0.01)

    ap.add_argument("--s_max", type=float, default=800.0)
    ap.add_argument("--p_ch_max", type=float, default=200.0)
    ap.add_argument("--p_dis_max", type=float, default=200.0)
    ap.add_argument("--eta_ch", type=float, default=0.95)
    ap.add_argument("--eta_dis", type=float, default=0.95)
    ap.add_argument("--loss_per_hour", type=float, default=0.001)
    ap.add_argument("--s_init", type=float, default=200.0)

    ap.add_argument("--tee", action="store_true")
    args = ap.parse_args()

    dump_costs = [float(x.strip()) for x in args.dump_costs.split(",") if x.strip() != ""]
    if not dump_costs:
        raise ValueError("No dump_costs parsed. Example: --dump_costs 5,20,50,100")

    scen_dir = ROOT / "data" / "scenarios" / args.scenario
    res_dir = scen_dir / "results"
    res_dir.mkdir(parents=True, exist_ok=True)


    rows: List[Dict[str, Any]] = []

    print(f"Running dump-cost sweep: scenario={args.scenario}, eload={args.eload}, dump_costs={dump_costs}", flush=True)

    for i, cd in enumerate(dump_costs, start=1):
        tag = make_mpc_tag(args.eload, cd)
        print(f"\n=== [{i}/{len(dump_costs)}] cost_dump={cd} | tag={tag} ===", flush=True)

        cmd = [
            sys.executable, "-m", "chp_pv_sim.models.chp_week_mpc_pv_grid_dispatch",
            "--scenario", args.scenario,
            "--tag", tag,
            "--horizon", str(args.horizon),
            "--step", str(args.step),
            "--time_limit_window", str(args.time_limit_window),
            "--mip_rel_gap", str(args.mip_rel_gap),
            "--grid_export_cap", str(args.grid_export_cap),
            "--startup_cost", str(args.startup_cost),
            "--shutdown_cost", str(args.shutdown_cost),
            "--min_up", str(args.min_up),
            "--min_down", str(args.min_down),
            "--on_init", str(args.on_init),
            "--price_sell", str(args.price_sell),
            "--price_buy", str(args.price_buy),
            "--pv_scale", str(args.pv_scale),
            "--e_load_base", str(args.eload),
            "--e_load_alpha", str(args.e_load_alpha),
            "--penalty_pv_curt", str(args.penalty_pv_curt),
            "--penalty_chp_curt", str(args.penalty_chp_curt),
            "--cost_q", str(args.cost_q),
            "--cost_boiler", str(args.cost_boiler),
            "--cost_dump", str(cd),
            "--penalty_under", str(args.penalty_under),
            "--cycle_cost", str(args.cycle_cost),
            "--s_max", str(args.s_max),
            "--p_ch_max", str(args.p_ch_max),
            "--p_dis_max", str(args.p_dis_max),
            "--eta_ch", str(args.eta_ch),
            "--eta_dis", str(args.eta_dis),
            "--loss_per_hour", str(args.loss_per_hour),
            "--s_init", str(args.s_init),
        ]
        if args.tee:
            cmd.append("--tee")

        subprocess.run(cmd, check=True)

        dst_sum = res_dir / f"dispatch_summary_pv_grid__{tag}.json"
        dst_parq = res_dir / f"dispatch_chp_storage_pv_grid__{tag}.parquet"
        if not dst_sum.exists() or not dst_parq.exists():
           raise FileNotFoundError(f"Missing tagged outputs after run: {dst_sum} or {dst_parq}")
        d = _read_json(dst_sum)
        scen = d.get("scenario", {}) if isinstance(d.get("scenario", {}), dict) else {}
        totals = d.get("totals", {}) if isinstance(d.get("totals", {}), dict) else {}
        qc = d.get("qc", {}) if isinstance(d.get("qc", {}), dict) else {}
        solver = d.get("solver", {}) if isinstance(d.get("solver", {}), dict) else {}

        eload_reported = float(scen.get("e_load_base_mw", args.eload))
        dump_cost_reported = float(scen.get("cost_dump", cd))
        if abs(eload_reported - float(args.eload)) > 1e-9:
            raise RuntimeError(f"Summary mismatch for {tag}: expected e_load_base={args.eload}, got {eload_reported}")
        if abs(dump_cost_reported - float(cd)) > 1e-9:
            raise RuntimeError(f"Summary mismatch for {tag}: expected cost_dump={cd}, got {dump_cost_reported}")

        heat = float(totals.get("heat_demand_mwh", np.nan))
        boiler = float(totals.get("boiler_mwh", np.nan))
        dump = float(totals.get("dump_mwh", np.nan))
        e_chp = float(totals.get("E_chp_mwh", np.nan))
        e_curt = float(totals.get("E_chp_curt_mwh", np.nan))
        gimp = float(totals.get("grid_import_mwh", np.nan))
        gexp = float(totals.get("grid_export_mwh", np.nan))

        rows.append({
            "e_load_base_mw": eload_reported,
            "cost_dump": dump_cost_reported,
            "objective_profit_like": _solver_profit_like(solver),
            "objective_system_cost": _solver_system_cost(solver),
            "boiler_share_pct": 100.0 * boiler / heat if heat > 1e-9 else np.nan,
            "dump_share_pct": 100.0 * dump / heat if heat > 1e-9 else np.nan,
            "E_curt_ratio_pct": 100.0 * e_curt / e_chp if e_chp > 1e-9 else np.nan,
            "grid_import_mwh": gimp,
            "grid_export_mwh": gexp,
            "net_export_mwh": gexp - gimp,
            "hours_export_at_cap": int(qc.get("hours_export_at_cap", -1)) if "hours_export_at_cap" in qc else np.nan,
            "starts": int(qc.get("starts", -1)) if "starts" in qc else np.nan,
            "stops": int(qc.get("stops", -1)) if "stops" in qc else np.nan,
            "summary_file": dst_sum.name,
        })

    df = pd.DataFrame(rows).sort_values("cost_dump").reset_index(drop=True)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = REPORTS_DIR / f"{args.scenario}__sweep_mpc_dumpcost_eload{int(args.eload)}.csv"
    out_md = REPORTS_DIR / f"{args.scenario}__sweep_mpc_dumpcost_eload{int(args.eload)}.md"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    md = []
    md.append(f"# MPC Sweep: cost_dump sensitivity — {args.scenario}\n\n")
    md.append(f"- fixed e_load_base={args.eload} MW\n")
    md.append(f"- horizon={args.horizon}, step={args.step}, time_limit_window={args.time_limit_window}, mip_rel_gap={args.mip_rel_gap}\n\n")
    md.append("## KPI table\n\n")
    show = df[[
        "cost_dump",
        "boiler_share_pct",
        "dump_share_pct",
        "E_curt_ratio_pct",
        "hours_export_at_cap",
        "grid_import_mwh",
        "grid_export_mwh",
        "net_export_mwh",
        "starts",
        "stops",
        "summary_file",
    ]].copy()

    def _fmt_pct(x):
        try:
            return f"{float(x):.2f}%"
        except Exception:
            return str(x)

    for c in ["boiler_share_pct", "dump_share_pct", "E_curt_ratio_pct"]:
        show[c] = show[c].apply(_fmt_pct)
    for c in ["grid_import_mwh", "grid_export_mwh", "net_export_mwh"]:
        show[c] = show[c].apply(lambda v: f"{float(v):.3f}")

    md.append("| " + " | ".join(show.columns) + " |\n")
    md.append("|" + "|".join(["---"] * len(show.columns)) + "|\n")
    for _, r in show.iterrows():
        md.append("| " + " | ".join(str(r[c]) for c in show.columns) + " |\n")
    out_md.write_text("".join(md), encoding="utf-8")

    fig_dir = REPORTS_DIR / "figures" / args.scenario / f"sweep_dumpcost_eload{int(args.eload)}"
    x = df["cost_dump"].to_numpy()
    _plot(x, df["dump_share_pct"].to_numpy(), f"Dump share vs cost_dump (e_load={args.eload}MW)", "Dump share (%)", fig_dir / "01_dump_share_pct.png")
    _plot(x, df["boiler_share_pct"].to_numpy(), f"Boiler share vs cost_dump (e_load={args.eload}MW)", "Boiler share (%)", fig_dir / "02_boiler_share_pct.png")
    _plot(x, df["E_curt_ratio_pct"].to_numpy(), f"E curtail ratio vs cost_dump (e_load={args.eload}MW)", "E curtail ratio (%)", fig_dir / "03_e_curt_ratio_pct.png")
    _plot(x, df["grid_import_mwh"].to_numpy(), f"Grid import vs cost_dump (e_load={args.eload}MW)", "Grid import (MWh)", fig_dir / "04_grid_import_mwh.png")

    print("\nWrote:", out_csv)
    print("Wrote:", out_md)
    print("Wrote figures dir:", fig_dir)
    print("\n=== SWEEP TABLE (preview) ===")
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
