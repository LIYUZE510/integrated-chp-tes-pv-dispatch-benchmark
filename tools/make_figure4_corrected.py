from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def find_project_root() -> Path:
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    for base in candidates:
        for p in [base] + list(base.parents):
            if (p / 'data' / 'processed').exists() and (p / 'reports').exists():
                return p
    raise RuntimeError(
        "Cannot locate project root containing 'data/processed' and 'reports'. "
        "Please run this script inside the repository."
    )


def ensure_outdir(root: Path, scenario: str) -> Path:
    out_dir = root / 'reports' / 'figures' / scenario / 'paper'
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _normalize_temp_label(x) -> str:
    s = str(x).strip().upper()
    s = s.replace(' ', '')
    s = s.replace('DEG', 'C')
    s = s.replace('°C', 'C')
    s = s.replace('OC', 'C')
    s = s.replace('OС', 'C')
    s = s.replace('ОС', 'C')
    s = s.replace('KOND.REGIME', 'KOND')
    s = s.replace('KONDREGIME', 'KOND')
    return s


def _temp_sort_key(label: str):
    s = _normalize_temp_label(label)
    if s == 'KOND':
        return (1_000_000, s)
    digits = ''.join(ch for ch in s if ch.isdigit())
    if digits:
        return (int(digits), s)
    return (999_999, s)


def _require_any(df: pd.DataFrame, candidates: Iterable[str], name: str) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"Missing {name}. None of {list(candidates)} found. Available: {list(df.columns)}")


def _to_numeric(df: pd.DataFrame, cols: Iterable[str]) -> None:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')


def _load_heat_segments(path: Path) -> pd.DataFrame:
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        raise RuntimeError(
            f"Failed to read {path}. This script requires a parquet engine (usually pyarrow). Original error: {e}"
        ) from e

    temp_col = _require_any(df, ['temp_label', 'temp', 'temperature'], 'heat temp label')
    seg_col = _require_any(df, ['segment', 'seg', 'segment_id'], 'heat segment id')
    k_col = _require_any(df, ['k_hq', 'k_HQ'], 'heat slope k_hq')
    b_col = _require_any(df, ['b_hq', 'b_HQ'], 'heat intercept b_hq')

    qlb_eff_col = _require_any(df, ['q_lb_eff', 'Q_lb_eff', 'q_lb', 'Q_lb'], 'heat q lower bound')
    qub_eff_col = _require_any(df, ['q_ub_eff', 'Q_ub_eff', 'q_ub', 'Q_ub'], 'heat q upper bound')

    hlb_eff_col = None
    hub_eff_col = None
    for c in ['h_lb_eff', 'H_lb_eff']:
        if c in df.columns:
            hlb_eff_col = c
            break
    for c in ['h_ub_eff', 'H_ub_eff']:
        if c in df.columns:
            hub_eff_col = c
            break

    cols_to_num = [k_col, b_col, qlb_eff_col, qub_eff_col]
    if hlb_eff_col:
        cols_to_num.append(hlb_eff_col)
    if hub_eff_col:
        cols_to_num.append(hub_eff_col)
    if 'segment_infeasible' in df.columns:
        pass
    _to_numeric(df, cols_to_num)

    out = pd.DataFrame({
        'temp_label': df[temp_col].map(_normalize_temp_label),
        'segment': pd.to_numeric(df[seg_col], errors='coerce').astype('Int64'),
        'k': pd.to_numeric(df[k_col], errors='coerce'),
        'b': pd.to_numeric(df[b_col], errors='coerce'),
        'q0': pd.to_numeric(df[qlb_eff_col], errors='coerce'),
        'q1': pd.to_numeric(df[qub_eff_col], errors='coerce'),
    })

    if hlb_eff_col and hub_eff_col:
        out['axis0'] = pd.to_numeric(df[hlb_eff_col], errors='coerce')
        out['axis1'] = pd.to_numeric(df[hub_eff_col], errors='coerce')
    else:
        # Correct inverse mapping: Q = k*H + b  => H = (Q - b) / k
        out['axis0'] = (out['q0'] - out['b']) / out['k']
        out['axis1'] = (out['q1'] - out['b']) / out['k']

    if 'segment_infeasible' in df.columns:
        out = out[~df['segment_infeasible'].astype(bool)].copy()

    out = out.dropna(subset=['temp_label', 'segment', 'k', 'b', 'q0', 'q1', 'axis0', 'axis1']).copy()
    out = out[out['q1'] >= out['q0']].copy()
    out = out.sort_values(['temp_label', 'segment', 'q0', 'q1']).reset_index(drop=True)
    return out


def _load_power_segments(path: Path) -> pd.DataFrame:
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        raise RuntimeError(
            f"Failed to read {path}. This script requires a parquet engine (usually pyarrow). Original error: {e}"
        ) from e

    temp_col = _require_any(df, ['temp_label', 'temp', 'temperature'], 'power temp label')
    seg_col = _require_any(df, ['segment', 'seg', 'segment_id'], 'power segment id')
    k_col = _require_any(df, ['k_eh', 'k_EH'], 'power slope k_eh')
    b_col = _require_any(df, ['b_eh', 'b_EH'], 'power intercept b_eh')

    qlb_eff_col = _require_any(df, ['q_lb_eff', 'Q_lb_eff', 'q_lb', 'Q_lb'], 'power q lower bound')
    qub_eff_col = _require_any(df, ['q_ub_eff', 'Q_ub_eff', 'q_ub', 'Q_ub'], 'power q upper bound')

    elb_eff_col = None
    eub_eff_col = None
    for c in ['e_lb_eff', 'E_lb_eff']:
        if c in df.columns:
            elb_eff_col = c
            break
    for c in ['e_ub_eff', 'E_ub_eff']:
        if c in df.columns:
            eub_eff_col = c
            break

    cols_to_num = [k_col, b_col, qlb_eff_col, qub_eff_col]
    if elb_eff_col:
        cols_to_num.append(elb_eff_col)
    if eub_eff_col:
        cols_to_num.append(eub_eff_col)
    _to_numeric(df, cols_to_num)

    out = pd.DataFrame({
        'temp_label': df[temp_col].map(_normalize_temp_label),
        'segment': pd.to_numeric(df[seg_col], errors='coerce').astype('Int64'),
        'k': pd.to_numeric(df[k_col], errors='coerce'),
        'b': pd.to_numeric(df[b_col], errors='coerce'),
        'q0': pd.to_numeric(df[qlb_eff_col], errors='coerce'),
        'q1': pd.to_numeric(df[qub_eff_col], errors='coerce'),
    })

    if elb_eff_col and eub_eff_col:
        out['axis0'] = pd.to_numeric(df[elb_eff_col], errors='coerce')
        out['axis1'] = pd.to_numeric(df[eub_eff_col], errors='coerce')
    else:
        # Correct inverse mapping: Q = k*E + b  => E = (Q - b) / k
        out['axis0'] = (out['q0'] - out['b']) / out['k']
        out['axis1'] = (out['q1'] - out['b']) / out['k']

    if 'segment_infeasible' in df.columns:
        out = out[~df['segment_infeasible'].astype(bool)].copy()

    out = out.dropna(subset=['temp_label', 'segment', 'k', 'b', 'q0', 'q1', 'axis0', 'axis1']).copy()
    out = out[out['q1'] >= out['q0']].copy()
    out = out.sort_values(['temp_label', 'segment', 'q0', 'q1']).reset_index(drop=True)
    return out


def make_figure4(
    root: Path,
    scenario: str,
    temp_labels: Optional[list[str]] = None,
    include_kond_reference: bool = False,
) -> tuple[Path, Path]:
    heat_path = root / 'data' / 'processed' / 'kaz_chpp_v3' / 'shared' / 'turbine_heat_segments_consistent.parquet'
    power_path = root / 'data' / 'processed' / 'kaz_chpp_v3' / 'shared' / 'turbine_power_segments_consistent.parquet'

    heat = _load_heat_segments(heat_path)
    power = _load_power_segments(power_path)

    common_temps = sorted(set(heat['temp_label']).intersection(set(power['temp_label'])), key=_temp_sort_key)
    if not common_temps:
        raise RuntimeError('No common temperature labels found between heat and power tables.')

    if temp_labels:
        wanted = [_normalize_temp_label(t) for t in temp_labels]
        missing = [t for t in wanted if t not in common_temps]
        if missing:
            raise ValueError(f'Requested temp_labels not used by MILP: {missing}. Available common labels: {common_temps}')
        common_temps = wanted

    heat = heat[heat['temp_label'].isin(common_temps)].copy()
    power_common = power[power['temp_label'].isin(common_temps)].copy()
    kond = power[power['temp_label'] == 'KOND'].copy()

    out_dir = ensure_outdir(root, scenario)
    suffix = 'all_common' if temp_labels is None else '_'.join(common_temps)
    png_path = out_dir / f'Fig04_CHP_SegmentEnvelopes_{suffix}.png'
    pdf_path = out_dir / f'Fig04_CHP_SegmentEnvelopes_{suffix}.pdf'

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), sharex=False)
    default_colors = plt.rcParams['axes.prop_cycle'].by_key().get('color', ['C0', 'C1', 'C2', 'C3', 'C4', 'C5'])
    color_map = {temp: default_colors[i % len(default_colors)] for i, temp in enumerate(common_temps)}

    # Left panel: Q-H
    ax = axes[0]
    legend_handles = []
    for temp in common_temps:
        sub = heat[heat['temp_label'] == temp].sort_values(['segment', 'q0', 'q1'])
        color = color_map[temp]
        first = True
        for _, r in sub.iterrows():
            h, = ax.plot([r['q0'], r['q1']], [r['axis0'], r['axis1']], color=color, linewidth=2.0,
                         label=temp if first else None)
            if first:
                legend_handles.append(h)
                first = False
    ax.set_title('Heat-side segment envelopes used in MILP')
    ax.set_xlabel('Q: steam-energy input rate (MW-equivalent)')
    ax.set_ylabel('H: CHP heat output (MW)')
    ax.grid(True, alpha=0.3)

    # Right panel: Q-E
    ax = axes[1]
    for temp in common_temps:
        sub = power_common[power_common['temp_label'] == temp].sort_values(['segment', 'q0', 'q1'])
        color = color_map[temp]
        for _, r in sub.iterrows():
            ax.plot([r['q0'], r['q1']], [r['axis0'], r['axis1']], color=color, linewidth=2.0)

    if include_kond_reference and not kond.empty:
        for _, r in kond.sort_values(['segment', 'q0', 'q1']).iterrows():
            ax.plot([r['q0'], r['q1']], [r['axis0'], r['axis1']], linestyle='--', linewidth=1.5, color='0.3')
        ax.text(0.02, 0.02, 'Dashed: KOND source-data branch (not used in coupled MILP)',
                transform=ax.transAxes, ha='left', va='bottom', fontsize=8,
                bbox=dict(facecolor='white', edgecolor='none', alpha=0.8))

    ax.set_title('Power-side segment envelopes used in MILP')
    ax.set_xlabel('Q: steam-energy input rate (MW-equivalent)')
    ax.set_ylabel('E: CHP electric output (MW)')
    ax.grid(True, alpha=0.3)

    # Publication style: keep the figure number in the paper caption, not inside the image.
    fig.suptitle(
        'Regime-wise CHP segment envelopes derived from processed turbine tables',
        y=0.98,
        fontsize=14,
    )
    fig.legend(
        handles=legend_handles,
        labels=common_temps,
        loc='upper center',
        bbox_to_anchor=(0.5, 0.945),
        ncol=min(len(common_temps), 6),
        frameon=True,
        fontsize=10,
        handlelength=2.2,
        columnspacing=1.2,
    )
    # Reserve explicit top margin for the title + legend so they do not overlap.
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.84])
    fig.savefig(png_path, dpi=300, bbox_inches='tight')
    fig.savefig(pdf_path, bbox_inches='tight')
    plt.close(fig)

    print('[Figure 4] Wrote:', png_path)
    print('[Figure 4] Wrote:', pdf_path)
    print('[Figure 4] Common MILP temp labels:', common_temps)
    print('[Figure 4] KOND plotted as reference only:', include_kond_reference)
    return png_path, pdf_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Redraw Figure 4 from the consistent CHP segment parquet files using the correct inverse mappings.'
    )
    parser.add_argument('--scenario', required=True, help='Scenario folder name used only for output location, e.g. week_2023_dec01')
    parser.add_argument('--temp-labels', default=None,
                        help='Optional comma-separated subset of MILP temperature regimes, e.g. 75C,90C,100C. Default: all common MILP temps.')
    parser.add_argument('--include-kond-reference', action='store_true',
                        help='Overlay the KOND power branch as dashed reference only. It is not part of the coupled MILP.')
    args = parser.parse_args()

    root = find_project_root()
    temp_labels = None
    if args.temp_labels:
        temp_labels = [x.strip() for x in args.temp_labels.split(',') if x.strip()]

    make_figure4(
        root=root,
        scenario=args.scenario,
        temp_labels=temp_labels,
        include_kond_reference=bool(args.include_kond_reference),
    )
    print('[Done]')


if __name__ == '__main__':
    main()
