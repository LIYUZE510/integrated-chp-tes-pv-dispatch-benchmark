from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable, Optional, Tuple

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from mpl_toolkits.axes_grid1.inset_locator import inset_axes


# ============================================================
# Root / path helpers
# ============================================================
def find_project_root() -> Path:
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    for base in candidates:
        for p in [base] + list(base.parents):
            if (p / "reports").exists() and (p / "data").exists():
                return p
    raise RuntimeError(
        "Cannot locate project root containing both 'reports' and 'data'. "
        "Please run this script inside the repository."
    )


def ensure_outdir(root: Path, scenario: str) -> Path:
    out_dir = root / "reports" / "figures" / scenario / "paper"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


# ============================================================
# Generic IO helpers
# ============================================================
def _read_csv_robust(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_dispatch_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing parquet: {path}")
    df = pd.read_parquet(path)
    if "datetime_local" not in df.columns:
        raise KeyError(f"'datetime_local' column not found in {path.name}")
    df["datetime_local"] = pd.to_datetime(df["datetime_local"])
    return df.sort_values("datetime_local").set_index("datetime_local")


# ============================================================
# Dataframe / column helpers
# ============================================================
def _pick_column(df: pd.DataFrame, candidates: Iterable[str], required: bool = True) -> Optional[str]:
    cols = list(df.columns)
    for c in candidates:
        if c in cols:
            return c
    if required:
        raise KeyError(
            f"None of the candidate columns found: {list(candidates)}. "
            f"Available columns: {cols}"
        )
    return None


def _get_series(df: pd.DataFrame, col: str) -> pd.Series:
    obj = df[col]
    if isinstance(obj, pd.DataFrame):
        for i in range(obj.shape[1]):
            s = obj.iloc[:, i]
            if s.notna().any():
                return s
        return obj.iloc[:, 0]
    return obj


def _to_numeric_series(s: pd.Series) -> pd.Series:
    s = s.copy()
    if s.dtype == object:
        s = (
            s.astype(str)
             .str.strip()
             .str.replace("%", "", regex=False)
             .str.replace(",", "", regex=False)
        )
        s = s.replace({"": None, "nan": None, "None": None})
    return pd.to_numeric(s, errors="coerce")


def _normalize_pct(s: pd.Series) -> pd.Series:
    s = _to_numeric_series(s)
    non_na = s.dropna()
    if len(non_na) == 0:
        return s
    if non_na.abs().max() <= 1.5:
        s = s * 100.0
    return s


def _series(df: pd.DataFrame, candidates: Iterable[str], default: float = 0.0, required: bool = False) -> pd.Series:
    col = _pick_column(df, candidates, required=required)
    if col is None:
        return pd.Series(default, index=df.index, dtype=float)
    s = pd.to_numeric(_get_series(df, col), errors="coerce")
    return s.fillna(default)


def _col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name in df.columns:
        s = pd.to_numeric(_get_series(df, name), errors="coerce")
        return s.fillna(default)
    return pd.Series(default, index=df.index, dtype=float)


# ============================================================
# Plot helpers
# ============================================================
def _save(fig, png_path: Path, pdf_path: Path):
    fig.tight_layout()
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)


def _panel_label(ax, label: str) -> None:
    ax.text(
        0.01,
        0.98,
        label,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.8),
    )


def _zoom_top(series_list: list[pd.Series], min_top: float, pct: float = 99.0, pad: float = 1.15) -> float:
    vals = pd.concat(series_list, axis=0).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(vals) == 0:
        return min_top
    top = float(np.nanpercentile(vals.to_numpy(), pct)) * pad
    return max(min_top, top)


def _style_sensitivity_axes(ax, xlabel: str, ylabel: str, title: str, xticks: Iterable[float]) -> None:
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xticks(list(xticks))
    ax.grid(True, alpha=0.3)


# ============================================================
# Figure 6
# ============================================================
def make_fig6_uc_vs_mpc_zoomed(
    root: Path,
    scenario: str,
    uc_tag: str,
    mpc_tag: str,
    grid_export_cap: float = 60.0,
) -> Tuple[Path, Path]:
    res_dir = root / "data" / "scenarios" / scenario / "results"
    uc_parq = res_dir / f"dispatch_chp_storage_pv_grid__{uc_tag}.parquet"
    mpc_parq = res_dir / f"dispatch_chp_storage_pv_grid__{mpc_tag}.parquet"

    uc = _read_dispatch_parquet(uc_parq)
    mpc = _read_dispatch_parquet(mpc_parq)

    idx = uc.index.intersection(mpc.index)
    if len(idx) == 0:
        raise RuntimeError("UC and MPC have no overlapping timestamps. Check datetime_local.")
    uc = uc.reindex(idx)
    mpc = mpc.reindex(idx)

    boiler_uc = _series(uc, ["boiler_mw", "boiler"])
    boiler_mpc = _series(mpc, ["boiler_mw", "boiler"])
    dump_uc = _series(uc, ["dump_mw", "dump"])
    dump_mpc = _series(mpc, ["dump_mw", "dump"])

    heat_demand = _series(uc, ["heat_demand_mw", "heat_demand"], required=True)
    chp_heat_uc = _series(uc, ["H_chp_mw", "chp_heat_mw", "H_mw"], required=True)
    chp_heat_mpc = _series(mpc, ["H_chp_mw", "chp_heat_mw", "H_mw"], required=True)

    gexp_uc = _series(uc, ["grid_export_mw", "grid_export"], required=True)
    gexp_mpc = _series(mpc, ["grid_export_mw", "grid_export"], required=True)

    a_zoom = _zoom_top([boiler_uc, boiler_mpc, dump_uc, dump_mpc], min_top=120.0, pct=99.0, pad=1.15)
    b_zoom = _zoom_top([heat_demand, chp_heat_uc, chp_heat_mpc], min_top=180.0, pct=99.0, pad=1.15)

    a_full = float(pd.concat([boiler_uc, boiler_mpc, dump_uc, dump_mpc]).max()) * 1.05
    b_full = float(pd.concat([heat_demand, chp_heat_uc, chp_heat_mpc]).max()) * 1.05

    out_dir = ensure_outdir(root, scenario)
    png_path = out_dir / "Fig06_UC_vs_MPC_timeseries_zoomed_fw.png"
    pdf_path = out_dir / "Fig06_UC_vs_MPC_timeseries_zoomed_fw.pdf"

    fig, axes = plt.subplots(3, 1, figsize=(11.5, 11.5), sharex=True)

    # (a) Boiler and dump
    l1, = axes[0].plot(idx, boiler_uc, label="Boiler (UC)")
    l2, = axes[0].plot(idx, boiler_mpc, label="Boiler (MPC)")
    l3, = axes[0].plot(idx, dump_uc, label="Dump (UC)")
    l4, = axes[0].plot(idx, dump_mpc, label="Dump (MPC)")
    axes[0].set_ylim(0.0, a_zoom)
    axes[0].set_ylabel("MW")
    axes[0].set_title("Boiler and dumped heat")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(ncol=2, fontsize=9, loc="upper left", bbox_to_anchor=(0.12, 1.02))
    _panel_label(axes[0], "(a)")

    axins_a = inset_axes(axes[0], width="28%", height="45%", loc="upper right", borderpad=1.2)
    axins_a.plot(idx, boiler_uc, color=l1.get_color(), linewidth=1.0)
    axins_a.plot(idx, boiler_mpc, color=l2.get_color(), linewidth=1.0)
    axins_a.plot(idx, dump_uc, color=l3.get_color(), linewidth=1.0)
    axins_a.plot(idx, dump_mpc, color=l4.get_color(), linewidth=1.0)
    axins_a.set_ylim(0.0, a_full)
    axins_a.set_title("Full scale", fontsize=8)
    axins_a.grid(True, alpha=0.2)
    axins_a.tick_params(axis="both", labelsize=7)
    axins_a.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    axins_a.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    # (b) Heat demand and CHP heat
    l5, = axes[1].plot(idx, heat_demand, label="Heat demand")
    l6, = axes[1].plot(idx, chp_heat_uc, label="CHP heat (UC)")
    l7, = axes[1].plot(idx, chp_heat_mpc, label="CHP heat (MPC)")
    axes[1].set_ylim(0.0, b_zoom)
    axes[1].set_ylabel("MW")
    axes[1].set_title("Heat demand and CHP heat output")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(ncol=3, fontsize=9, loc="upper left", bbox_to_anchor=(0.16, 1.02))
    _panel_label(axes[1], "(b)")

    axins_b = inset_axes(axes[1], width="28%", height="45%", loc="upper right", borderpad=1.2)
    axins_b.plot(idx, heat_demand, color=l5.get_color(), linewidth=1.0)
    axins_b.plot(idx, chp_heat_uc, color=l6.get_color(), linewidth=1.0)
    axins_b.plot(idx, chp_heat_mpc, color=l7.get_color(), linewidth=1.0)
    axins_b.set_ylim(0.0, b_full)
    axins_b.set_title("Full scale", fontsize=8)
    axins_b.grid(True, alpha=0.2)
    axins_b.tick_params(axis="both", labelsize=7)
    axins_b.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    axins_b.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    # (c) Grid export with cap
    axes[2].plot(idx, gexp_uc, label="Grid export (UC)")
    axes[2].plot(idx, gexp_mpc, label="Grid export (MPC)")
    axes[2].axhline(grid_export_cap, linestyle="--", linewidth=1.0, label=f"Export cap = {grid_export_cap:g} MW")
    axes[2].set_ylabel("MW")
    axes[2].set_title("Grid export and export-cap saturation")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(ncol=3, fontsize=9)
    _panel_label(axes[2], "(c)")

    axes[2].set_xlabel("Datetime")
    axes[2].xaxis.set_major_locator(mdates.DayLocator())
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate()

    _save(fig, png_path, pdf_path)
    print("[Figure 6] Wrote:", png_path)
    print("[Figure 6] Wrote:", pdf_path)
    return png_path, pdf_path


# ============================================================
# Figure 7 / 8 helper: infer x from tag/batch name
# ============================================================
def _infer_numeric_from_text(text: str, prefix: str) -> Optional[float]:
    text = str(text)
    patterns = [
        rf"{prefix}(\d+)",
        rf"{prefix}_(\d+)",
        rf"{prefix}(\d+)MW",
        rf"{prefix}(\d+)p(\d+)",
        rf"{prefix}_(\d+)p(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            if len(m.groups()) == 1:
                return float(m.group(1))
            if len(m.groups()) == 2:
                return float(f"{m.group(1)}.{m.group(2)}")
    return None


def _infer_eload_from_row(row: pd.Series) -> float:
    for col in ["e_load_base_mw", "e_load_base", "eload_mw"]:
        if col in row.index and pd.notna(row[col]):
            try:
                return float(row[col])
            except Exception:
                pass
    for col in ["tag", "batch_name"]:
        if col in row.index and pd.notna(row[col]):
            v = _infer_numeric_from_text(str(row[col]), "eload")
            if v is not None:
                return v
    raise ValueError(f"Could not infer e-load from row: {row.to_dict()}")


def _infer_cdump_from_row(row: pd.Series) -> float:
    for col in ["cost_dump", "dump_cost", "c_dump", "cdump"]:
        if col in row.index and pd.notna(row[col]):
            try:
                return float(row[col])
            except Exception:
                pass
    for col in ["tag", "batch_name"]:
        if col in row.index and pd.notna(row[col]):
            v = _infer_numeric_from_text(str(row[col]), "cdump")
            if v is not None:
                return v
    raise ValueError(f"Could not infer c_dump from row: {row.to_dict()}")


# ============================================================
# Figure 7
# ============================================================
def make_fig7_eload_sensitivity(
    root: Path,
    scenario: str,
    csv_path: Path,
) -> Tuple[Path, Path]:
    df = _read_csv_robust(csv_path)
    df["eload_mw"] = df.apply(_infer_eload_from_row, axis=1)
    df["boiler_share_pct"] = _normalize_pct(df["boiler_share_pct"])
    df["dump_share_pct"] = _normalize_pct(df["dump_share_pct"])
    if "net_export_mwh" not in df.columns:
        df["net_export_mwh"] = pd.to_numeric(df["grid_export_mwh"], errors="coerce") - pd.to_numeric(df["grid_import_mwh"], errors="coerce")
    df = df.sort_values("eload_mw").reset_index(drop=True)

    out_dir = ensure_outdir(root, scenario)
    png_path = out_dir / "Fig07_MPC_eLoad_sensitivity_fw.png"
    pdf_path = out_dir / "Fig07_MPC_eLoad_sensitivity_fw.pdf"

    fig, axes = plt.subplots(1, 3, figsize=(13, 4))

    axes[0].plot(df["eload_mw"], df["boiler_share_pct"], marker="o")
    _style_sensitivity_axes(
        axes[0],
        xlabel=r"Exogenous electric base load $e_{\mathrm{load}}$ (MW)",
        ylabel="Boiler share (%)",
        title="Boiler share",
        xticks=df["eload_mw"],
    )
    _panel_label(axes[0], "(a)")

    axes[1].plot(df["eload_mw"], df["dump_share_pct"], marker="o")
    _style_sensitivity_axes(
        axes[1],
        xlabel=r"Exogenous electric base load $e_{\mathrm{load}}$ (MW)",
        ylabel="Dump share (%)",
        title="Dump share",
        xticks=df["eload_mw"],
    )
    _panel_label(axes[1], "(b)")

    axes[2].plot(df["eload_mw"], df["net_export_mwh"], marker="o")
    axes[2].axhline(0.0, linestyle="--", linewidth=1.0)
    _style_sensitivity_axes(
        axes[2],
        xlabel=r"Exogenous electric base load $e_{\mathrm{load}}$ (MW)",
        ylabel="Net export (MWh)",
        title="Net grid export",
        xticks=df["eload_mw"],
    )
    _panel_label(axes[2], "(c)")

    _save(fig, png_path, pdf_path)
    print("[Figure 7] Wrote:", png_path)
    print("[Figure 7] Wrote:", pdf_path)
    return png_path, pdf_path


# ============================================================
# Figure 8
# ============================================================
def make_fig8_dumpcost_sensitivity(
    root: Path,
    scenario: str,
    csv_path: Path,
) -> Tuple[Path, Path]:
    df = _read_csv_robust(csv_path)
    df["cdump"] = df.apply(_infer_cdump_from_row, axis=1)
    df["boiler_share_pct"] = _normalize_pct(df["boiler_share_pct"])
    df["dump_share_pct"] = _normalize_pct(df["dump_share_pct"])
    if "net_export_mwh" not in df.columns:
        df["net_export_mwh"] = pd.to_numeric(df["grid_export_mwh"], errors="coerce") - pd.to_numeric(df["grid_import_mwh"], errors="coerce")
    df = df.sort_values("cdump").reset_index(drop=True)

    out_dir = ensure_outdir(root, scenario)
    png_path = out_dir / "Fig08_MPC_dumpcost_sensitivity_fw.png"
    pdf_path = out_dir / "Fig08_MPC_dumpcost_sensitivity_fw.pdf"

    fig, axes = plt.subplots(1, 3, figsize=(13, 4))

    axes[0].plot(df["cdump"], df["dump_share_pct"], marker="o")
    _style_sensitivity_axes(
        axes[0],
        xlabel=r"Dumping penalty $c_{\mathrm{dump}}$",
        ylabel="Dump share (%)",
        title="Dump share",
        xticks=df["cdump"],
    )
    _panel_label(axes[0], "(a)")

    axes[1].plot(df["cdump"], df["boiler_share_pct"], marker="o")
    _style_sensitivity_axes(
        axes[1],
        xlabel=r"Dumping penalty $c_{\mathrm{dump}}$",
        ylabel="Boiler share (%)",
        title="Boiler share",
        xticks=df["cdump"],
    )
    _panel_label(axes[1], "(b)")

    axes[2].plot(df["cdump"], df["net_export_mwh"], marker="o")
    axes[2].axhline(0.0, linestyle="--", linewidth=1.0)
    _style_sensitivity_axes(
        axes[2],
        xlabel=r"Dumping penalty $c_{\mathrm{dump}}$",
        ylabel="Net export (MWh)",
        title="Net grid export",
        xticks=df["cdump"],
    )
    _panel_label(axes[2], "(c)")

    _save(fig, png_path, pdf_path)
    print("[Figure 8] Wrote:", png_path)
    print("[Figure 8] Wrote:", pdf_path)
    return png_path, pdf_path


# ============================================================
# Table 4 from retained baseline summary JSONs
# ============================================================
def _safe_num(x, default: float = 0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except Exception:
        return default


def _econ_block(summary: dict) -> dict:
    er = summary.get("economics_realized", {}) or {}

    chp_cost = _safe_num(er.get("chp_cost"))
    boiler_cost = _safe_num(er.get("boiler_cost"))
    dump_penalty_cost = _safe_num(er.get("dump_penalty_cost"))

    curtailment_total = er.get("curtailment_penalty_cost", None)
    if curtailment_total is None or _safe_num(curtailment_total) == 0.0:
        curtailment_total = (
            _safe_num(er.get("pv_curtailment_penalty_cost"))
            + _safe_num(er.get("chp_curtailment_penalty_cost"))
        )
    curtailment_total = _safe_num(curtailment_total)

    import_cost = _safe_num(er.get("import_cost"))
    export_revenue = _safe_num(er.get("export_revenue"))
    startup_cost = _safe_num(er.get("startup_cost"))
    shutdown_cost = _safe_num(er.get("shutdown_cost"))
    storage_cycling_cost = _safe_num(er.get("storage_cycling_cost", er.get("cycling_cost", 0.0)))
    total_operating_cost = _safe_num(er.get("system_cost_realized"))

    return {
        "Total operating cost": total_operating_cost,
        "CHP cost": chp_cost,
        "Boiler cost": boiler_cost,
        "Dump penalty cost": dump_penalty_cost,
        "Curtailment penalty cost": curtailment_total,
        "Import cost": import_cost,
        "Export revenue": export_revenue,
        "Start-up cost": startup_cost,
        "Shut-down cost": shutdown_cost,
        "Storage cycling cost": storage_cycling_cost,
    }


def _fmt_signed(x: float) -> str:
    if x > 0:
        return f"+{x:,.2f}"
    return f"{x:,.2f}"


def make_table4_from_retained_summaries(
    root: Path,
    scenario: str,
    uc_tag: str,
    mpc_tag: str,
) -> Tuple[Path, Path, Path]:
    res_dir = root / "data" / "scenarios" / scenario / "results"
    uc_json = res_dir / f"dispatch_summary_pv_grid__{uc_tag}.json"
    mpc_json = res_dir / f"dispatch_summary_pv_grid__{mpc_tag}.json"

    uc = _read_json(uc_json)
    mpc = _read_json(mpc_json)

    uc_block = _econ_block(uc)
    mpc_block = _econ_block(mpc)

    metrics = list(uc_block.keys())
    rows = []
    for metric in metrics:
        uc_val = float(uc_block[metric])
        mpc_val = float(mpc_block[metric])
        rows.append(
            {
                "Metric": metric,
                "Full-horizon UC": uc_val,
                "MPC": mpc_val,
                "MPC-UC": mpc_val - uc_val,
            }
        )

    df_num = pd.DataFrame(rows)
    df_fmt = df_num.copy()
    df_fmt["Full-horizon UC"] = df_fmt["Full-horizon UC"].map(lambda x: f"{x:,.2f}")
    df_fmt["MPC"] = df_fmt["MPC"].map(lambda x: f"{x:,.2f}")
    df_fmt["MPC-UC"] = df_fmt["MPC-UC"].map(_fmt_signed)

    out_csv_num = root / "reports" / "canonical_table4_fw_numeric.csv"
    out_csv_fmt = root / "reports" / "canonical_table4_fw_for_paper.csv"
    out_md = root / "reports" / "canonical_table4_fw.md"

    df_num.to_csv(out_csv_num, index=False, encoding="utf-8-sig")
    df_fmt.to_csv(out_csv_fmt, index=False, encoding="utf-8-sig")

    header = ["Metric", "Full-horizon UC", "MPC", "MPC-UC"]
    rows_md = [
        "| " + " | ".join(header) + " |",
        "|---|---:|---:|---:|",
    ]
    for _, r in df_fmt.iterrows():
        rows_md.append(
            f"| {r['Metric']} | {r['Full-horizon UC']} | {r['MPC']} | {r['MPC-UC']} |"
        )
    md = "\n".join(rows_md)
    md_text = (
        "Table 4. Retained-outlier baseline realized weekly operating cost and cost breakdown for the\n"
        "common-input UC-MPC comparison under fixed computational budgets.\n\n"
        f"{md}\n\n"
        "Note: Lower realized operating cost indicates a lower-cost incumbent under the stated computational\n"
        "budgets. MPC-UC is reported in cost units; a negative value therefore indicates an MPC incumbent\n"
        "with lower realized cost than the UC incumbent.\n"
    )
    out_md.write_text(md_text, encoding="utf-8")

    print("[Table 4] Wrote:", out_csv_num)
    print("[Table 4] Wrote:", out_csv_fmt)
    print("[Table 4] Wrote:", out_md)
    print("\n[Table 4 preview]\n")
    print(md_text)
    return out_csv_num, out_csv_fmt, out_md


# ============================================================
# Main CLI
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Table 4 and redraw Figures 6/7/8 from the canonical _fw result set."
    )
    parser.add_argument("--scenario", default="week_2023_dec01", help="Scenario name")
    parser.add_argument("--uc-tag", default="uc_paper_retained_fw", help="UC retained-baseline tag")
    parser.add_argument("--mpc-tag", default="mpc_paper_retained_fw", help="MPC retained-baseline tag")
    parser.add_argument("--table7-csv", default="reports/canonical_table7.csv", help="Path to canonical Table 7 CSV")
    parser.add_argument("--table8-csv", default="reports/canonical_table8.csv", help="Path to canonical Table 8 CSV")
    parser.add_argument("--grid-export-cap", type=float, default=60.0, help="Grid export cap shown in Figure 6")
    parser.add_argument(
        "--only",
        default="all",
        choices=["all", "table4", "fig6", "fig7", "fig8"],
        help="Generate only one artifact or all of them",
    )
    args = parser.parse_args()

    root = find_project_root()
    print("[Root]", root)
    print("[Scenario]", args.scenario)

    table7_csv = Path(args.table7_csv)
    if not table7_csv.is_absolute():
        table7_csv = root / table7_csv

    table8_csv = Path(args.table8_csv)
    if not table8_csv.is_absolute():
        table8_csv = root / table8_csv

    if args.only in ("all", "table4"):
        make_table4_from_retained_summaries(
            root=root,
            scenario=args.scenario,
            uc_tag=args.uc_tag,
            mpc_tag=args.mpc_tag,
        )

    if args.only in ("all", "fig6"):
        make_fig6_uc_vs_mpc_zoomed(
            root=root,
            scenario=args.scenario,
            uc_tag=args.uc_tag,
            mpc_tag=args.mpc_tag,
            grid_export_cap=args.grid_export_cap,
        )

    if args.only in ("all", "fig7"):
        make_fig7_eload_sensitivity(
            root=root,
            scenario=args.scenario,
            csv_path=table7_csv,
        )

    if args.only in ("all", "fig8"):
        make_fig8_dumpcost_sensitivity(
            root=root,
            scenario=args.scenario,
            csv_path=table8_csv,
        )

    print("[Done]")


if __name__ == "__main__":
    main()
