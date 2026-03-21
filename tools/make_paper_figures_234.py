# tools/make_paper_figures_234.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


# ---------------------------
# Helpers: robust project root
# ---------------------------
def find_project_root() -> Path:
    """
    Find the project root that contains:
      - data/scenarios
      - reports
    Works even if you run the script from a subfolder.
    """
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    for base in candidates:
        for p in [base] + list(base.parents):
            if (p / "data" / "scenarios").exists() and (p / "reports").exists():
                return p
    raise RuntimeError(
        "Cannot locate project root. Please run from within the repository "
        "that contains 'data/scenarios' and 'reports'."
    )


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def pick_col(df: pd.DataFrame, candidates, required: bool = True) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    if required:
        raise KeyError(f"None of the candidate columns found: {candidates}. Available: {list(df.columns)}")
    return None


def find_latest_summary_json(results_dir: Path) -> Optional[Path]:
    """
    Try to auto-detect the latest dispatch summary json so Fig.2 can reuse
    e_load_base_mw / e_load_alpha_per_heat from your actual simulation runs.
    """
    if not results_dir.exists():
        return None

    patterns = [
        "dispatch_summary_pv_grid.json",
        "dispatch_summary_pv_grid__*.json",
        "dispatch_summary.json",
        "dispatch_summary__*.json",
    ]

    files = []
    for pat in patterns:
        files.extend(list(results_dir.glob(pat)))

    if not files:
        return None

    # pick newest modified time
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def ensure_outdir(root: Path, scenario: str) -> Path:
    out_dir = root / "reports" / "figures" / scenario / "paper"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


# ---------------------------
# Fig.2: Scenario inputs
# ---------------------------
def make_fig2_scenario_inputs(
    root: Path,
    scenario: str,
    e_load_base_mw: Optional[float],
    e_load_alpha_per_heat: Optional[float],
    auto_from_summary: bool = True,
) -> Tuple[Path, Path]:
    scen_dir = root / "data" / "scenarios" / scenario
    heat_path = scen_dir / "heat.parquet"
    pv_path = scen_dir / "pv.parquet"
    manifest_path = scen_dir / "manifest.json"

    if not heat_path.exists():
        raise FileNotFoundError(f"Missing: {heat_path}")
    if not pv_path.exists():
        raise FileNotFoundError(f"Missing: {pv_path}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing: {manifest_path}")

    manifest = read_json(manifest_path)
    h_max_mw = manifest.get("h_max_mw", None)

    # auto-load e_load params from the latest summary file if requested
    if auto_from_summary:
        results_dir = scen_dir / "results"
        latest = find_latest_summary_json(results_dir)
        if latest is not None:
            try:
                summary = read_json(latest)
                scen_cfg = summary.get("scenario", {})
                if e_load_base_mw is None and "e_load_base_mw" in scen_cfg:
                    e_load_base_mw = float(scen_cfg["e_load_base_mw"])
                if e_load_alpha_per_heat is None and "e_load_alpha_per_heat" in scen_cfg:
                    e_load_alpha_per_heat = float(scen_cfg["e_load_alpha_per_heat"])
                print(f"[Fig2] Auto-loaded e_load params from: {latest.name}")
            except Exception as ex:
                print(f"[Fig2] WARNING: failed to parse summary {latest}: {ex}")

    if e_load_base_mw is None:
        e_load_base_mw = 0.0
    if e_load_alpha_per_heat is None:
        e_load_alpha_per_heat = 0.0

    heat = pd.read_parquet(heat_path)
    pv = pd.read_parquet(pv_path)

    # normalize datetime column
    dt_col_heat = pick_col(heat, ["datetime_local", "datetime"], required=True)
    dt_col_pv = pick_col(pv, ["datetime_local", "datetime"], required=True)
    heat[dt_col_heat] = pd.to_datetime(heat[dt_col_heat])
    pv[dt_col_pv] = pd.to_datetime(pv[dt_col_pv])

    # normalize heat demand column
    hd_col = pick_col(
        heat,
        ["heat_demand_mw", "heat_mw", "demand_mw", "heat_demand"],
        required=True,
    )

    # normalize PV column
    pv_col = pick_col(
        pv,
        ["pv_avail_mw", "pv_ac_mw", "pv_mw", "ac_mw", "pv_power_mw"],
        required=True,
    )

    df = (
        heat[[dt_col_heat, hd_col]]
        .rename(columns={dt_col_heat: "datetime_local", hd_col: "heat_demand_mw"})
        .merge(
            pv[[dt_col_pv, pv_col]].rename(columns={dt_col_pv: "datetime_local", pv_col: "pv_avail_mw"}),
            on="datetime_local",
            how="left",
        )
        .sort_values("datetime_local")
        .reset_index(drop=True)
    )

    # exogenous electricity load definition (consistent with your config style)
    df["e_load_mw"] = e_load_base_mw + e_load_alpha_per_heat * df["heat_demand_mw"]

    out_dir = ensure_outdir(root, scenario)
    png_path = out_dir / f"Fig02_ScenarioInputs_{scenario}.png"
    pdf_path = out_dir / f"Fig02_ScenarioInputs_{scenario}.pdf"

    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)

    # (a) Heat demand
    axes[0].plot(df["datetime_local"], df["heat_demand_mw"], label="Heat demand (scaled)")
    if h_max_mw is not None:
        axes[0].axhline(float(h_max_mw), linestyle="--", label=f"CHP heat capacity H_max={float(h_max_mw):.3f} MW")
    axes[0].set_ylabel("Heat (MW)")
    axes[0].set_title(f"Scenario inputs for {scenario} (hourly)")
    axes[0].legend(loc="upper right")

    # (b) PV + exogenous electric load
    axes[1].plot(df["datetime_local"], df["pv_avail_mw"], label="PV available (MW)")
    axes[1].plot(df["datetime_local"], df["e_load_mw"], linestyle="--", label="Exogenous electric load (MW)")
    axes[1].set_ylabel("Power (MW)")
    axes[1].set_xlabel("Datetime")
    axes[1].legend(loc="upper right")

    # nicer x-axis ticks
    axes[1].xaxis.set_major_locator(mdates.DayLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate()

    fig.tight_layout()
    fig.savefig(png_path, dpi=300)
    fig.savefig(pdf_path)
    plt.close(fig)

    print(f"[Fig2] Wrote: {png_path}")
    print(f"[Fig2] Wrote: {pdf_path}")
    print(f"[Fig2] Using e_load_base_mw={e_load_base_mw}, e_load_alpha_per_heat={e_load_alpha_per_heat}")
    print(f"[Fig2] Columns used: heat='{hd_col}', pv='{pv_col}', datetime='{dt_col_heat}'")

    return png_path, pdf_path


# ---------------------------
# Fig.3: System schematic (vector-like with matplotlib)
# ---------------------------
def _add_box(ax, xy, w, h, text, fontsize=10):
    x, y = xy
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        linewidth=1.2,
        facecolor="white",
        edgecolor="black",
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize)
    return box


def _add_arrow(ax, start, end, text=None, fontsize=9, linestyle="-"):
    arr = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.2,
        linestyle=linestyle,
        color="black",
    )
    ax.add_patch(arr)
    if text:
        mx = (start[0] + end[0]) / 2
        my = (start[1] + end[1]) / 2
        ax.text(mx, my, text, ha="center", va="bottom", fontsize=fontsize)
    return arr


def make_fig3_system_model(root: Path, scenario: str) -> Tuple[Path, Path]:
    out_dir = ensure_outdir(root, scenario)
    png_path = out_dir / "Fig03_SystemModel_EnergyFlows.png"
    pdf_path = out_dir / "Fig03_SystemModel_EnergyFlows.pdf"

    fig = plt.figure(figsize=(12, 6))
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Titles
    ax.text(0.5, 0.96, "System model and energy flows (heat and electricity)", ha="center", va="top", fontsize=12)
    ax.text(0.5, 0.90, "Heat domain (top) and electricity domain (bottom)", ha="center", va="top", fontsize=10)

    # Core CHP (middle left, spanning conceptually)
    chp = _add_box(ax, (0.07, 0.42), 0.15, 0.16, "CHP\n(coupled heat & power)", fontsize=9)

    # Heat-side boxes
    boiler = _add_box(ax, (0.28, 0.70), 0.12, 0.12, "Boiler", fontsize=10)
    tes = _add_box(ax, (0.46, 0.68), 0.18, 0.16, "Thermal Storage (TES)\nState: S_t (MWh)", fontsize=9)
    demand_h = _add_box(ax, (0.76, 0.70), 0.16, 0.12, "Heat demand\nD_t", fontsize=10)
    dump = _add_box(ax, (0.70, 0.52), 0.12, 0.10, "Dumping\nU_t", fontsize=9)
    unmet = _add_box(ax, (0.86, 0.52), 0.12, 0.10, "Unmet heat\nV_t", fontsize=9)

    # Electricity-side boxes
    pv = _add_box(ax, (0.28, 0.18), 0.12, 0.12, "PV\nAvail: P^PV_t", fontsize=9)
    load_e = _add_box(ax, (0.52, 0.18), 0.16, 0.12, "Electric load\nL_t", fontsize=10)
    grid = _add_box(ax, (0.76, 0.18), 0.16, 0.12, "Grid\nImport/Export", fontsize=10)
    curt_pv = _add_box(ax, (0.28, 0.06), 0.12, 0.08, "PV curtail\nC^PV_t", fontsize=8)
    curt_chp = _add_box(ax, (0.07, 0.06), 0.15, 0.08, "CHP elec curtail\nC^CHP_t", fontsize=8)

    # CHP input Q_t
    _add_arrow(ax, (0.01, 0.50), (0.07, 0.50), text="Q_t", fontsize=9)

    # CHP heat output H_t to heat demand bus
    _add_arrow(ax, (0.22, 0.56), (0.52, 0.76), text="H_t", fontsize=9)

    # Boiler heat B_t to heat demand
    _add_arrow(ax, (0.40, 0.76), (0.76, 0.76), text="B_t", fontsize=9)

    # TES charge/discharge
    _add_arrow(ax, (0.64, 0.76), (0.76, 0.76), text="p^dis_t", fontsize=9)  # discharge to demand line
    _add_arrow(ax, (0.76, 0.72), (0.64, 0.72), text="p^ch_t", fontsize=9)   # charge from demand line back to TES

    # Dumping from heat line
    _add_arrow(ax, (0.76, 0.70), (0.76, 0.62), text=None, fontsize=9)
    _add_arrow(ax, (0.76, 0.62), (0.76, 0.57), text="U_t", fontsize=9)

    # Unmet heat into demand (deficit compensation)
    _add_arrow(ax, (0.92, 0.62), (0.92, 0.70), text="V_t", fontsize=9)

    # CHP electricity E_t to load
    _add_arrow(ax, (0.22, 0.44), (0.52, 0.24), text="E_t", fontsize=9)

    # PV used to load; PV curtail dashed to curt box
    _add_arrow(ax, (0.40, 0.24), (0.52, 0.24), text="P^PV_t − C^PV_t", fontsize=9)
    _add_arrow(ax, (0.34, 0.18), (0.34, 0.14), text=None, fontsize=9, linestyle="--")
    _add_arrow(ax, (0.34, 0.14), (0.34, 0.10), text="C^PV_t", fontsize=9, linestyle="--")

    # CHP curtail dashed from CHP elec to curt_chp
    _add_arrow(ax, (0.14, 0.42), (0.14, 0.14), text="C^CHP_t", fontsize=9, linestyle="--")

    # Load to grid export and grid import to load
    _add_arrow(ax, (0.68, 0.24), (0.76, 0.24), text="G^exp_t", fontsize=9)
    _add_arrow(ax, (0.76, 0.20), (0.68, 0.20), text="G^imp_t", fontsize=9)

    # Export cap annotation
    ax.text(0.84, 0.32, "Export cap:\nG^exp_t ≤ G^exp_max", ha="center", va="bottom", fontsize=8)

    # Legend-like note
    ax.text(0.99, 0.02, "Flows in MW; storage state S_t in MWh", ha="right", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(png_path, dpi=300)
    fig.savefig(pdf_path)
    plt.close(fig)

    print(f"[Fig3] Wrote: {png_path}")
    print(f"[Fig3] Wrote: {pdf_path}")
    return png_path, pdf_path


# ---------------------------
# Fig.4: CHP piecewise segments from consistent parquet files
# ---------------------------
def _normalize_temp_label(x) -> str:
    """
    Normalize temperature/regime labels to a consistent style:
      75deg, 75oC, 75°C -> 75C
      Kond.regime -> KOND
    """
    s = str(x).strip().upper()
    s = s.replace(" ", "")
    s = s.replace("DEG", "C")
    s = s.replace("°C", "C")
    s = s.replace("OC", "C")
    s = s.replace("OС", "C")   # possible mixed Latin/Cyrillic glyph
    s = s.replace("ОС", "C")   # possible Cyrillic
    s = s.replace("KOND.REGIME", "KOND")
    s = s.replace("KONDREGIME", "KOND")
    return s


def _standardize_segments(df: pd.DataFrame, axis: str) -> pd.DataFrame:
    """
    Standardize the consistent CHP segment parquet into plotting columns:

      temp_label, segment, k, b, q_lb, q_ub, axis

    IMPORTANT:
    We DO NOT rename the whole original DataFrame, because the consistent parquet
    may already contain both q_lb/q_ub and q_lb_eff/q_ub_eff. Renaming would create
    duplicate column names, and then out["q_lb"] becomes a DataFrame instead of Series.
    """

    temp_col = pick_col(df, ["temp_label", "temp", "temperature", "tempLabel"], required=True)
    seg_col = pick_col(df, ["segment", "seg", "segment_id", "seg_id"], required=False)

    if axis.upper() == "H":
        k_col = pick_col(df, ["k_HQ", "k_hq", "k", "slope"], required=True)
        b_col = pick_col(df, ["b_HQ", "b_hq", "b", "intercept"], required=True)
        axis_name = "H"
    else:
        k_col = pick_col(df, ["k_EH", "k_eh", "k", "slope"], required=True)
        b_col = pick_col(df, ["b_EH", "b_eh", "b", "intercept"], required=True)
        axis_name = "E"

    # Prefer the effective bounds if they exist in the consistent parquet
    qlb_col = pick_col(df, ["q_lb_eff", "Q_lb_eff", "q_lb", "Q_lb", "q_min"], required=True)
    qub_col = pick_col(df, ["q_ub_eff", "Q_ub_eff", "q_ub", "Q_ub", "q_max"], required=True)

    # Build a FRESH dataframe so there are never duplicate column names
    out = pd.DataFrame({
        "temp_label": df[temp_col].map(_normalize_temp_label),
        "k": df[k_col],
        "b": df[b_col],
        "q_lb": df[qlb_col],
        "q_ub": df[qub_col],
    })

    # Segment id: use source if available, otherwise rebuild after sorting
    if seg_col is not None and seg_col in df.columns:
        out["segment"] = df[seg_col]
    else:
        out["segment"] = pd.NA

    # Convert to numeric safely
    for c in ["k", "b", "q_lb", "q_ub"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    # Drop incomplete rows
    out = out.dropna(subset=["temp_label", "k", "b", "q_lb", "q_ub"]).copy()

    # Keep only valid intervals
    out = out[out["q_ub"] >= out["q_lb"]].copy()

    # Sort by temperature and lower steam bound
    out = out.sort_values(["temp_label", "q_lb", "q_ub"]).reset_index(drop=True)

    # Rebuild segment numbering for plotting clarity (stable and deterministic)
    out["segment"] = out.groupby("temp_label").cumcount() + 1

    out["axis"] = axis_name
    return out


def make_fig4_chp_segments(
    root: Path,
    scenario: str,
    temp_label: str = "75C",
    include_kond: bool = True,
) -> Tuple[Path, Path]:
    heat_seg_path = root / "data" / "processed" / "kaz_chpp_v3" / "shared" / "turbine_heat_segments_consistent.parquet"
    pow_seg_path = root / "data" / "processed" / "kaz_chpp_v3" / "shared" / "turbine_power_segments_consistent.parquet"

    if not heat_seg_path.exists():
        raise FileNotFoundError(f"Missing: {heat_seg_path}")
    if not pow_seg_path.exists():
        raise FileNotFoundError(f"Missing: {pow_seg_path}")

    heat_df = pd.read_parquet(heat_seg_path)
    pow_df = pd.read_parquet(pow_seg_path)

    heat = _standardize_segments(heat_df, axis="H")
    power = _standardize_segments(pow_df, axis="E")

    # filter
    heat_t = heat[heat["temp_label"] == temp_label].copy()
    power_t = power[power["temp_label"] == temp_label].copy()
    if heat_t.empty:
        raise ValueError(f"No heat segments found for temp_label='{temp_label}'. Available: {sorted(heat['temp_label'].unique())}")
    if power_t.empty:
        raise ValueError(f"No power segments found for temp_label='{temp_label}'. Available: {sorted(power['temp_label'].unique())}")

    kond = power[power["temp_label"].astype(str).str.upper() == "KOND"].copy() if include_kond else pd.DataFrame()

    out_dir = ensure_outdir(root, scenario)
    png_path = out_dir / f"Fig04_CHP_PiecewiseSegments_{temp_label}.png"
    pdf_path = out_dir / f"Fig04_CHP_PiecewiseSegments_{temp_label}.pdf"

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    # Left: H-Q
    ax = axes[0]
    for _, r in heat_t.iterrows():
        q0, q1 = float(r["q_lb"]), float(r["q_ub"])
        k, b = float(r["k"]), float(r["b"])
        h0 = k * q0 + b
        h1 = k * q1 + b
        ax.plot([q0, q1], [h0, h1])
    ax.set_title(f"Heat segments (H–Q), temp={temp_label}")
    ax.set_xlabel("Inlet steam energy Q (MW)")
    ax.set_ylabel("CHP heat H (MW)")
    ax.grid(True, alpha=0.3)

    # Right: E-Q
    ax = axes[1]
    for _, r in power_t.iterrows():
        q0, q1 = float(r["q_lb"]), float(r["q_ub"])
        k, b = float(r["k"]), float(r["b"])
        e0 = k * q0 + b
        e1 = k * q1 + b
        ax.plot([q0, q1], [e0, e1], label=None)
    if include_kond and not kond.empty:
        for _, r in kond.iterrows():
            q0, q1 = float(r["q_lb"]), float(r["q_ub"])
            k, b = float(r["k"]), float(r["b"])
            e0 = k * q0 + b
            e1 = k * q1 + b
            ax.plot([q0, q1], [e0, e1], linestyle="--", label=None)
        ax.text(0.02, 0.98, "Dashed: KOND regime", transform=ax.transAxes, ha="left", va="top", fontsize=8)

    ax.set_title(f"Power segments (E–Q), temp={temp_label}")
    ax.set_xlabel("Inlet steam energy Q (MW)")
    ax.set_ylabel("CHP electricity E (MW)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(png_path, dpi=300)
    fig.savefig(pdf_path)
    plt.close(fig)

    print(f"[Fig4] Wrote: {png_path}")
    print(f"[Fig4] Wrote: {pdf_path}")
    print(f"[Fig4] Using segments from:")
    print(f"       {heat_seg_path}")
    print(f"       {pow_seg_path}")
    print(f"[Fig4] temp_label={temp_label}, include_kond={include_kond}")
    return png_path, pdf_path


# ---------------------------
# CLI
# ---------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate paper figures Fig.2 (inputs), Fig.3 (system schematic), Fig.4 (CHP segments) "
                    "using existing simulation outputs (parquet/json)."
    )
    parser.add_argument("--scenario", required=True, help="Scenario folder name under data/scenarios/, e.g., week_2023_dec01")
    parser.add_argument("--fig", default="all", choices=["2", "3", "4", "all"], help="Which figure to generate")
    parser.add_argument("--temp_label", default="75C", help="Temperature label for Fig.4, e.g., 75C/90C/100C/110C/120C/125C")
    parser.add_argument("--no_kond", action="store_true", help="Disable plotting KOND regime (Fig.4 right panel)")
    parser.add_argument("--e_load_base_mw", type=float, default=None, help="Override exogenous electric base load for Fig.2")
    parser.add_argument("--e_load_alpha_per_heat", type=float, default=None, help="Override heat-coupled load coefficient for Fig.2")
    parser.add_argument("--no_auto_from_summary", action="store_true", help="Do not auto-read e_load params from latest summary json")

    args = parser.parse_args()
    root = find_project_root()

    print(f"[Root] {root}")
    print(f"[Scenario] {args.scenario}")

    if args.fig in ("2", "all"):
        make_fig2_scenario_inputs(
            root=root,
            scenario=args.scenario,
            e_load_base_mw=args.e_load_base_mw,
            e_load_alpha_per_heat=args.e_load_alpha_per_heat,
            auto_from_summary=not args.no_auto_from_summary,
        )
    if args.fig in ("3", "all"):
        make_fig3_system_model(root=root, scenario=args.scenario)
    if args.fig in ("4", "all"):
        make_fig4_chp_segments(
            root=root,
            scenario=args.scenario,
            temp_label=args.temp_label,
            include_kond=not args.no_kond,
        )

    print("[Done]")


if __name__ == "__main__":
    main()