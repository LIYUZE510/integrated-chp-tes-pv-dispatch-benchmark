from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

# Force non-interactive backend (safe on Windows/VSCode)
import matplotlib
matplotlib.use("Agg")  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from chp_pv_sim.paths import ROOT, REPORTS_DIR, ensure_dirs


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _ensure_datetime_index(df: pd.DataFrame, col: str = "datetime_local") -> pd.DataFrame:
    df = df.copy()
    df[col] = pd.to_datetime(df[col], errors="raise")
    df = df.sort_values(col).set_index(col)
    return df


def _plot_save(fig, outpath: Path) -> None:
    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(outpath, dpi=220)
    plt.close(fig)


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    scenario = args.scenario

    scen_dir = ROOT / "data" / "scenarios" / scenario
    res_dir = scen_dir / "results"

    f_dispatch = res_dir / f"dispatch_chp_storage_pv_grid__{args.tag}.parquet"
    f_summary = res_dir / f"dispatch_summary_pv_grid__{args.tag}.json"
    if not f_dispatch.exists():
        raise FileNotFoundError(f"Missing: {f_dispatch}")
    if not f_summary.exists():
        raise FileNotFoundError(f"Missing: {f_summary}")

    summary = _read_json(f_summary)
    meta = summary.get("scenario", {})
    export_cap = float(meta.get("grid_export_cap_mw", np.nan))
    s_max = float(meta.get("storage_s_max_mwh", np.nan))

    df = pd.read_parquet(f_dispatch)
    df = _ensure_datetime_index(df, "datetime_local")

    # Basic derived series
    df["pv_used_mw"] = df["pv_avail_mw"] - df["pv_curt_mw"]
    df["e_chp_used_mw"] = df["E_chp_mw"] - df["chp_curt_mw"]

    df["heat_net_supply_mw"] = (
        df["H_chp_mw"]
        + df["boiler_mw"]
        + df["dis_mw"]
        - df["ch_mw"]
        - df["dump_mw"]
        + df["under_mw"]
    )

    df["elec_net_supply_mw"] = (
        df["e_chp_used_mw"]
        + df["pv_used_mw"]
        + df["grid_import_mw"]
        - df["grid_export_mw"]
    )

    # -------------------------
    # KPI computations
    # -------------------------
    eps = 1e-6

    kpi = {}
    kpi["scenario"] = scenario
    kpi["tag"] = args.tag
    kpi["hours"] = int(len(df))

    kpi["heat_demand_mwh"] = float(df["heat_demand_mw"].sum())
    kpi["chp_heat_mwh"] = float(df["H_chp_mw"].sum())
    kpi["boiler_heat_mwh"] = float(df["boiler_mw"].sum())
    kpi["storage_charge_mwh"] = float(df["ch_mw"].sum())
    kpi["storage_discharge_mwh"] = float(df["dis_mw"].sum())
    kpi["dump_mwh"] = float(df["dump_mw"].sum())
    kpi["under_mwh"] = float(df["under_mw"].sum())

    kpi["pv_avail_mwh"] = float(df["pv_avail_mw"].sum())
    kpi["pv_used_mwh"] = float(df["pv_used_mw"].sum())
    kpi["pv_curt_mwh"] = float(df["pv_curt_mw"].sum())
    kpi["pv_utilization"] = float(kpi["pv_used_mwh"] / kpi["pv_avail_mwh"]) if kpi["pv_avail_mwh"] > eps else float("nan")

    kpi["e_chp_mwh"] = float(df["E_chp_mw"].sum())
    kpi["e_chp_used_mwh"] = float(df["e_chp_used_mw"].sum())
    kpi["e_chp_curt_mwh"] = float(df["chp_curt_mw"].sum())
    kpi["e_chp_curt_ratio"] = float(kpi["e_chp_curt_mwh"] / kpi["e_chp_mwh"]) if kpi["e_chp_mwh"] > eps else float("nan")

    kpi["grid_export_mwh"] = float(df["grid_export_mw"].sum())
    kpi["grid_import_mwh"] = float(df["grid_import_mw"].sum())

    kpi["heat_balance_abs_max"] = float(np.max(np.abs(df["heat_balance_residual"])))
    kpi["elec_balance_abs_max"] = float(np.max(np.abs(df["elec_balance_residual"])))

    kpi["hours_under_gt_0"] = int((df["under_mw"] > 1e-6).sum())
    kpi["hours_dump_gt_0"] = int((df["dump_mw"] > 1e-6).sum())
    kpi["hours_boiler_gt_0"] = int((df["boiler_mw"] > 1e-6).sum())
    kpi["hours_chp_curt_gt_0"] = int((df["chp_curt_mw"] > 1e-6).sum())
    kpi["hours_export_at_cap"] = int((df["grid_export_mw"] >= (export_cap - 1e-6)).sum()) if np.isfinite(export_cap) else None

    # On/off transitions
    on = (df["mode"].astype(str) == "ON").astype(int)
    starts = int(((on == 1) & (on.shift(1, fill_value=0) == 0)).sum())
    stops = int(((on == 0) & (on.shift(1, fill_value=1) == 1)).sum())
    kpi["hours_on"] = int(on.sum())
    kpi["hours_off"] = int((1 - on).sum())
    kpi["starts"] = starts
    kpi["stops"] = stops

    # Peak hour
    peak_idx = df["heat_demand_mw"].idxmax()
    peak_row = df.loc[peak_idx, [
        "heat_demand_mw", "H_chp_mw", "boiler_mw", "dis_mw", "ch_mw", "dump_mw", "S_mwh",
        "E_chp_mw", "grid_export_mw", "chp_curt_mw", "pv_avail_mw"
    ]]
    kpi["peak_hour"] = {"datetime_local": str(peak_idx), **{k: float(v) for k, v in peak_row.to_dict().items()}}

    # Top 5 heat-demand hours table
    top5 = df.nlargest(5, "heat_demand_mw")[[
        "heat_demand_mw", "H_chp_mw", "boiler_mw", "dis_mw", "ch_mw", "dump_mw", "S_mwh"
    ]].copy()

    # -------------------------
    # Write KPI reports
    # -------------------------
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_json = REPORTS_DIR / f"{scenario}__kpi_pv_grid__{args.tag}.json"
    out_md = REPORTS_DIR / f"{scenario}__kpi_pv_grid__{args.tag}.md"

    out_json.write_text(json.dumps(kpi, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = []
    md_lines.append(f"# KPI Report (PV+Grid) — {scenario} [{args.tag}]\n")
    md_lines.append("## Key checks\n")
    md_lines.append(f"- Heat balance abs max: `{kpi['heat_balance_abs_max']:.3e}`\n")
    md_lines.append(f"- Elec balance abs max: `{kpi['elec_balance_abs_max']:.3e}`\n")
    md_lines.append(f"- Under-supply hours: `{kpi['hours_under_gt_0']}`\n")
    md_lines.append(f"- Boiler hours > 0: `{kpi['hours_boiler_gt_0']}`\n")
    md_lines.append(f"- CHP curtail hours > 0: `{kpi['hours_chp_curt_gt_0']}`\n")
    if kpi["hours_export_at_cap"] is not None:
        md_lines.append(f"- Export-at-cap hours: `{kpi['hours_export_at_cap']}` (cap={export_cap} MW)\n")

    md_lines.append("\n## Energy totals (MWh)\n")
    md_lines.append(f"- Heat demand: `{kpi['heat_demand_mwh']:.3f}`\n")
    md_lines.append(f"- CHP heat: `{kpi['chp_heat_mwh']:.3f}`\n")
    md_lines.append(f"- Boiler heat: `{kpi['boiler_heat_mwh']:.3f}`\n")
    md_lines.append(f"- Dump: `{kpi['dump_mwh']:.3f}`\n")
    md_lines.append(f"- PV avail/used: `{kpi['pv_avail_mwh']:.3f}` / `{kpi['pv_used_mwh']:.3f}` (util={kpi['pv_utilization']:.3%})\n")
    md_lines.append(f"- CHP elec total/curt: `{kpi['e_chp_mwh']:.3f}` / `{kpi['e_chp_curt_mwh']:.3f}` (curt ratio={kpi['e_chp_curt_ratio']:.3%})\n")
    md_lines.append(f"- Grid export/import: `{kpi['grid_export_mwh']:.3f}` / `{kpi['grid_import_mwh']:.3f}`\n")

    md_lines.append("\n## Storage\n")
    md_lines.append(f"- S_max (model): `{s_max}` MWh\n")
    md_lines.append(f"- SOC min/max: `{float(df['S_mwh'].min()):.3f}` / `{float(df['S_mwh'].max()):.3f}` MWh\n")
    md_lines.append(f"- Charge/discharge totals: `{kpi['storage_charge_mwh']:.3f}` / `{kpi['storage_discharge_mwh']:.3f}`\n")

    md_lines.append("\n## Peak hour (max heat demand)\n")
    md_lines.append("```text\n")
    md_lines.append(json.dumps(kpi["peak_hour"], ensure_ascii=False, indent=2))
    md_lines.append("\n```\n")

    md_lines.append("\n## Top-5 heat demand hours\n")
    md_lines.append("```text\n")
    md_lines.append(top5.to_string())
    md_lines.append("\n```\n")

    out_md.write_text("\n".join(md_lines), encoding="utf-8")

    # -------------------------
    # Plots
    # -------------------------
    fig_dir = REPORTS_DIR / "figures" / scenario / args.tag
    fig_dir.mkdir(parents=True, exist_ok=True)

    # 1) Heat balance overlay
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(df.index, df["heat_demand_mw"], label="Heat demand (MW)")
    ax.plot(df.index, df["heat_net_supply_mw"], label="Net heat supply (MW)")
    ax.set_title("Heat Balance Check")
    ax.set_ylabel("MW")
    ax.legend()
    _plot_save(fig, fig_dir / "01_heat_balance.png")

    # 2) Heat components (note: ch_mw and dump_mw are sinks in heat balance)
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(df.index, df["H_chp_mw"], label="CHP heat (MW)")
    ax.plot(df.index, df["boiler_mw"], label="Boiler heat (MW)")
    ax.plot(df.index, df["dis_mw"], label="Storage discharge (MW)")
    ax.plot(df.index, df["ch_mw"], label="Storage charge (MW, sink)")
    ax.plot(df.index, df["dump_mw"], label="Dump (MW, sink)")
    ax.set_title("Heat Supply Components")
    ax.set_ylabel("MW")
    ax.legend(ncol=2)
    _plot_save(fig, fig_dir / "02_heat_components.png")

    # 3) Storage SOC
    fig, ax = plt.subplots(figsize=(13, 3.6))
    ax.plot(df.index, df["S_mwh"], label="Storage energy S (MWh)")
    if np.isfinite(s_max):
        ax.axhline(s_max, linestyle="--", label="S_max (MWh)")
    ax.set_title("Thermal Storage State of Charge")
    ax.set_ylabel("MWh")
    ax.legend()
    _plot_save(fig, fig_dir / "03_storage_soc.png")

    # 4) Electricity flows
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(df.index, df["pv_avail_mw"], label="PV avail (MW)")
    ax.plot(df.index, df["pv_used_mw"], label="PV used (MW)")
    ax.plot(df.index, df["e_chp_used_mw"], label="CHP elec used (MW)")
    ax.plot(df.index, df["grid_export_mw"], label="Grid export (MW)")
    ax.plot(df.index, df["chp_curt_mw"], label="CHP curtail (MW)")
    if np.isfinite(export_cap):
        ax.axhline(export_cap, linestyle="--", label="Export cap (MW)")
    ax.set_title("Electricity Balance (PV + CHP + Grid)")
    ax.set_ylabel("MW")
    ax.legend(ncol=2)
    _plot_save(fig, fig_dir / "04_electricity.png")

    # Terminal prints
    print("Wrote KPI JSON :", out_json)
    print("Wrote KPI MD   :", out_md)
    print("Wrote figures  :", fig_dir)
    print("\n=== QUICK KPI ===")
    print(json.dumps({k: kpi[k] for k in [
        "heat_demand_mwh", "chp_heat_mwh", "boiler_heat_mwh", "dump_mwh",
        "pv_avail_mwh", "pv_used_mwh", "pv_utilization",
        "e_chp_mwh", "e_chp_curt_mwh", "e_chp_curt_ratio",
        "grid_export_mwh", "grid_import_mwh",
        "hours_boiler_gt_0", "hours_chp_curt_gt_0", "hours_export_at_cap",
        "starts", "stops"
    ]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()