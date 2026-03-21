from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from chp_pv_sim.paths import ROOT, REPORTS_DIR, ensure_dirs


def _load_dispatch(parq: Path) -> pd.DataFrame:
    df = pd.read_parquet(parq)
    if "datetime_local" not in df.columns:
        raise KeyError(f"'datetime_local' column not found in {parq.name}")
    df["datetime_local"] = pd.to_datetime(df["datetime_local"])
    df = df.sort_values("datetime_local").set_index("datetime_local")
    return df


def _col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        s = pd.to_numeric(df[name], errors="coerce")
        return s.fillna(default)
    return pd.Series(default, index=df.index, dtype=float)


def _totals(df: pd.DataFrame) -> Dict[str, float]:
    # MW series are hourly => sum(MW) == MWh
    heat = float(_col(df, "heat_demand_mw").sum())
    h_chp = float(_col(df, "H_chp_mw").sum())
    boiler = float(_col(df, "boiler_mw").sum())
    dump = float(_col(df, "dump_mw").sum())
    under = float(_col(df, "under_mw").sum())

    e_chp = float(_col(df, "E_chp_mw").sum())
    e_curt = float(_col(df, "chp_curt_mw").sum())

    gimp = float(_col(df, "grid_import_mw").sum())
    gexp = float(_col(df, "grid_export_mw").sum())

    pv_av = float(_col(df, "pv_avail_mw").sum())
    pv_curt = float(_col(df, "pv_curt_mw").sum())
    pv_used = pv_av - pv_curt

    return {
        "heat_demand_mwh": heat,
        "H_chp_mwh": h_chp,
        "boiler_mwh": boiler,
        "dump_mwh": dump,
        "under_mwh": under,
        "E_chp_mwh": e_chp,
        "E_curt_mwh": e_curt,
        "grid_import_mwh": gimp,
        "grid_export_mwh": gexp,
        "net_export_mwh": gexp - gimp,
        "pv_avail_mwh": pv_av,
        "pv_used_mwh": pv_used,
    }


def _shares(t: Dict[str, float]) -> Dict[str, float]:
    heat = t["heat_demand_mwh"]
    e = t["E_chp_mwh"]
    return {
        "boiler_share_pct": 100.0 * t["boiler_mwh"] / heat if heat > 1e-9 else np.nan,
        "dump_share_pct": 100.0 * t["dump_mwh"] / heat if heat > 1e-9 else np.nan,
        "E_curt_ratio_pct": 100.0 * t["E_curt_mwh"] / e if e > 1e-9 else np.nan,
        "pv_utilization": t["pv_used_mwh"] / t["pv_avail_mwh"] if t["pv_avail_mwh"] > 1e-9 else np.nan,
    }


def _plot(x, ys, labels, title: str, ylabel: str, out: Path, hline: float | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10.5, 4.5))
    for y, lab in zip(ys, labels):
        ax.plot(x, y, label=lab)
    if hline is not None:
        ax.axhline(hline, linestyle="--", linewidth=1.0)
    ax.set_title(title)
    ax.set_xlabel("Time")
    ax.set_ylabel(ylabel)
    ax.legend(ncol=2, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=220)
    plt.close(fig)


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--uc_tag", required=True)
    ap.add_argument("--mpc_tag", required=True)
    ap.add_argument("--grid_export_cap", type=float, default=60.0)
    args = ap.parse_args()

    res_dir = ROOT / "data" / "scenarios" / args.scenario / "results"
    uc_parq = res_dir / f"dispatch_chp_storage_pv_grid__{args.uc_tag}.parquet"
    mpc_parq = res_dir / f"dispatch_chp_storage_pv_grid__{args.mpc_tag}.parquet"

    if not uc_parq.exists():
        raise FileNotFoundError(f"Missing UC parquet: {uc_parq}")
    if not mpc_parq.exists():
        raise FileNotFoundError(f"Missing MPC parquet: {mpc_parq}")

    uc = _load_dispatch(uc_parq)
    mpc = _load_dispatch(mpc_parq)

    # align on common time index
    idx = uc.index.intersection(mpc.index)
    if len(idx) == 0:
        raise RuntimeError("UC and MPC have no overlapping timestamps. Check datetime_local.")
    uc = uc.reindex(idx)
    mpc = mpc.reindex(idx)

    # derived series
    uc_net = _col(uc, "grid_export_mw") - _col(uc, "grid_import_mw")
    mpc_net = _col(mpc, "grid_export_mw") - _col(mpc, "grid_import_mw")

    # quick stats focused on heat_demand ~ 0 hours
    eps = 1e-9
    mask0 = _col(uc, "heat_demand_mw") <= eps  # common index, ok to use UC
    n0 = int(mask0.sum())

    def _avg_on_mask(df: pd.DataFrame, name: str) -> float:
        s = _col(df, name)
        return float(s[mask0].mean()) if n0 > 0 else np.nan

    diag = {
        "n_hours": int(len(idx)),
        "n_hours_heat_demand_zero": n0,
        "avg_H_chp_when_heat0_uc_mw": _avg_on_mask(uc, "H_chp_mw"),
        "avg_H_chp_when_heat0_mpc_mw": _avg_on_mask(mpc, "H_chp_mw"),
        "avg_dump_when_heat0_uc_mw": _avg_on_mask(uc, "dump_mw"),
        "avg_dump_when_heat0_mpc_mw": _avg_on_mask(mpc, "dump_mw"),
        "avg_grid_export_when_heat0_uc_mw": float(_col(uc, "grid_export_mw")[mask0].mean()) if n0 > 0 else np.nan,
        "avg_grid_export_when_heat0_mpc_mw": float(_col(mpc, "grid_export_mw")[mask0].mean()) if n0 > 0 else np.nan,
    }

    t_uc = _totals(uc)
    t_mpc = _totals(mpc)
    s_uc = _shares(t_uc)
    s_mpc = _shares(t_mpc)

    out = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "scenario": args.scenario,
        "uc_tag": args.uc_tag,
        "mpc_tag": args.mpc_tag,
        "uc_totals": t_uc,
        "mpc_totals": t_mpc,
        "uc_shares": s_uc,
        "mpc_shares": s_mpc,
        "diagnostics": diag,
        "delta_mpc_minus_uc": {
            "boiler_mwh": t_mpc["boiler_mwh"] - t_uc["boiler_mwh"],
            "dump_mwh": t_mpc["dump_mwh"] - t_uc["dump_mwh"],
            "net_export_mwh": t_mpc["net_export_mwh"] - t_uc["net_export_mwh"],
            "E_curt_mwh": t_mpc["E_curt_mwh"] - t_uc["E_curt_mwh"],
        },
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_json = REPORTS_DIR / f"{args.scenario}__compare_uc_vs_mpc__eload20_dump50.json"
    out_md = REPORTS_DIR / f"{args.scenario}__compare_uc_vs_mpc__eload20_dump50.md"
    out_json.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    md = []
    md.append(f"# UC vs MPC comparison — {args.scenario}\n\n")
    md.append(f"- UC tag : `{args.uc_tag}`\n")
    md.append(f"- MPC tag: `{args.mpc_tag}`\n\n")
    md.append("## Shares\n\n")
    md.append("| Method | Boiler share | Dump share | CHP E curtail | PV utilization | Net export (MWh) |\n")
    md.append("|---|---:|---:|---:|---:|---:|\n")
    md.append(f"| UC  | {s_uc['boiler_share_pct']:.2f}% | {s_uc['dump_share_pct']:.2f}% | {s_uc['E_curt_ratio_pct']:.2f}% | {s_uc['pv_utilization']:.3f} | {t_uc['net_export_mwh']:.3f} |\n")
    md.append(f"| MPC | {s_mpc['boiler_share_pct']:.2f}% | {s_mpc['dump_share_pct']:.2f}% | {s_mpc['E_curt_ratio_pct']:.2f}% | {s_mpc['pv_utilization']:.3f} | {t_mpc['net_export_mwh']:.3f} |\n")
    md.append("\n## Heat-demand-zero diagnostics\n\n")
    md.append(f"- hours with heat_demand≈0: {n0}/{len(idx)}\n")
    md.append(f"- avg H_chp when heat≈0 (UC): {diag['avg_H_chp_when_heat0_uc_mw']:.3f} MW\n")
    md.append(f"- avg H_chp when heat≈0 (MPC): {diag['avg_H_chp_when_heat0_mpc_mw']:.3f} MW\n")
    md.append(f"- avg dump when heat≈0 (UC): {diag['avg_dump_when_heat0_uc_mw']:.3f} MW\n")
    md.append(f"- avg dump when heat≈0 (MPC): {diag['avg_dump_when_heat0_mpc_mw']:.3f} MW\n")
    out_md.write_text("".join(md), encoding="utf-8")

    # figures
    fig_dir = REPORTS_DIR / "figures" / args.scenario / "compare_uc_vs_mpc__eload20_dump50"
    x = idx

    # 1) Boiler + Dump comparison
    _plot(
        x,
        [
            _col(uc, "boiler_mw"),
            _col(mpc, "boiler_mw"),
            _col(uc, "dump_mw"),
            _col(mpc, "dump_mw"),
        ],
        ["Boiler (UC)", "Boiler (MPC)", "Dump (UC)", "Dump (MPC)"],
        "Heat-side penalties: Boiler vs Dump (UC vs MPC)",
        "MW",
        fig_dir / "01_boiler_dump_uc_vs_mpc.png",
    )

    # 2) CHP heat vs demand
    _plot(
        x,
        [
            _col(uc, "heat_demand_mw"),
            _col(uc, "H_chp_mw"),
            _col(mpc, "H_chp_mw"),
        ],
        ["Heat demand", "H_chp (UC)", "H_chp (MPC)"],
        "CHP heat output vs heat demand",
        "MW",
        fig_dir / "02_heat_demand_vs_Hchp.png",
    )

    # 3) Storage SOC
    _plot(
        x,
        [
            _col(uc, "S_mwh"),
            _col(mpc, "S_mwh"),
        ],
        ["S (UC)", "S (MPC)"],
        "Thermal storage state of charge",
        "MWh",
        fig_dir / "03_storage_soc.png",
    )

    # 4) Grid export with cap
    _plot(
        x,
        [
            _col(uc, "grid_export_mw"),
            _col(mpc, "grid_export_mw"),
        ],
        ["Grid export (UC)", "Grid export (MPC)"],
        "Grid export (cap shown as dashed line)",
        "MW",
        fig_dir / "04_grid_export_cap.png",
        hline=args.grid_export_cap,
    )

    # 5) Net export
    _plot(
        x,
        [
            uc_net,
            mpc_net,
        ],
        ["Net export (UC)", "Net export (MPC)"],
        "Net grid export = export - import",
        "MW",
        fig_dir / "05_net_export.png",
        hline=0.0,
    )

    # 6) CHP electric curtailment
    _plot(
        x,
        [
            _col(uc, "chp_curt_mw"),
            _col(mpc, "chp_curt_mw"),
        ],
        ["CHP curtail (UC)", "CHP curtail (MPC)"],
        "CHP electric curtailment",
        "MW",
        fig_dir / "06_chp_curtail.png",
    )

    print("\nWrote:", out_json)
    print("Wrote:", out_md)
    print("Wrote figures dir:", fig_dir)
    print("\nKey delta (MPC - UC):")
    print(json.dumps(out["delta_mpc_minus_uc"], indent=2))


if __name__ == "__main__":
    main()