from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from chp_pv_sim.paths import ROOT, REPORTS_DIR


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _safe(x, default=None):
    return default if x is None else x


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return 'NA'
    return f'{100.0 * float(x):.2f}%'


def _fmt_num(x: float | None, nd: int = 3) -> str:
    if x is None:
        return 'NA'
    return f'{float(x):,.{nd}f}'


def main() -> None:
    ap = argparse.ArgumentParser(description='Build scenario-QC and solver-summary notes/tables for the paper.')
    ap.add_argument('--scenario', required=True)
    ap.add_argument('--uc-tag', default='uc_paper_retained_fw')
    ap.add_argument('--mpc-tag', default='mpc_paper_retained_fw')
    args = ap.parse_args()

    scen_dir = ROOT / 'data' / 'scenarios' / args.scenario
    manifest_path = scen_dir / 'manifest.json'
    heat_path = scen_dir / 'heat.parquet'
    results_dir = scen_dir / 'results'
    uc_path = results_dir / f'dispatch_summary_pv_grid__{args.uc_tag}.json'
    mpc_path = results_dir / f'dispatch_summary_pv_grid__{args.mpc_tag}.json'

    manifest = _read_json(manifest_path)
    uc = _read_json(uc_path)
    mpc = _read_json(mpc_path)

    heat = pd.read_parquet(heat_path)
    heat['datetime_local'] = pd.to_datetime(heat['datetime_local'])
    peak_idx = heat['heat_demand_mw'].idxmax()
    peak = heat.loc[peak_idx]

    h_max = float(manifest['scenario']['h_max_mw'])
    p99 = float(manifest['basic_stats']['heat_demand_mw']['p99'])
    h_max_ratio = float(peak['heat_demand_mw']) / h_max if h_max > 0 else None
    p99_ratio = float(peak['heat_demand_mw']) / p99 if p99 > 0 else None
    over_cap = heat['heat_demand_mw'] > h_max

    qc_row = {
        'scenario': args.scenario,
        'quantile_used_for_scaling': float(manifest['scenario']['quantile']),
        'target_utilization_at_quantile': float(manifest['scenario']['target_utilization']),
        'h_max_mw': h_max,
        'scaled_p99_mw': p99,
        'scaled_max_mw': float(peak['heat_demand_mw']),
        'max_to_p99_ratio': p99_ratio,
        'max_to_hmax_ratio': h_max_ratio,
        'hours_over_hmax': int(over_cap.sum()),
        'pct_hours_over_hmax': float(over_cap.mean() * 100.0),
        'peak_datetime_local': str(peak['datetime_local']),
        'peak_heat_raw_mw': float(peak['heat_demand_raw_mw']),
        'heat_scale': float(peak['heat_scale']),
    }

    solver_rows = []
    solver_rows.append({
        'strategy': 'Full-horizon UC',
        'case_tag': args.uc_tag,
        'time_limit_s': uc.get('scenario', {}).get('time_limit_s'),
        'target_mip_rel_gap': uc.get('scenario', {}).get('mip_rel_gap'),
        'status': uc.get('solver', {}).get('status'),
        'termination': uc.get('solver', {}).get('termination'),
        'achieved_gap_rel': uc.get('solver', {}).get('achieved_gap_rel'),
        'wallclock_s': uc.get('solver', {}).get('wallclock_s'),
        'reported_runtime_s': uc.get('solver', {}).get('reported_runtime_s'),
    })
    solver_rows.append({
        'strategy': 'Rolling MPC (aggregate)',
        'case_tag': args.mpc_tag,
        'time_limit_s': mpc.get('rolling', {}).get('time_limit_window_s'),
        'target_mip_rel_gap': mpc.get('scenario', {}).get('mip_rel_gap'),
        'status': 'windowed',
        'termination': json.dumps(mpc.get('solver', {}).get('window_termination_counts', {}), ensure_ascii=False),
        'achieved_gap_rel': mpc.get('solver', {}).get('achieved_gap_rel_max'),
        'wallclock_s': mpc.get('solver', {}).get('wallclock_s_total'),
        'reported_runtime_s': mpc.get('solver', {}).get('reported_runtime_s_total'),
    })

    windows = mpc.get('windows', [])
    for w in windows:
        solver_rows.append({
            'strategy': f'Rolling MPC window {w.get("window_id")}',
            'case_tag': args.mpc_tag,
            'time_limit_s': mpc.get('rolling', {}).get('time_limit_window_s'),
            'target_mip_rel_gap': mpc.get('scenario', {}).get('mip_rel_gap'),
            'status': w.get('status'),
            'termination': w.get('termination'),
            'achieved_gap_rel': w.get('achieved_gap_rel'),
            'wallclock_s': w.get('wallclock_s'),
            'reported_runtime_s': w.get('reported_runtime_s'),
        })

    qc_df = pd.DataFrame([qc_row])
    solver_df = pd.DataFrame(solver_rows)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    qc_csv = REPORTS_DIR / f'{args.scenario}__scenario_qc_summary.csv'
    solver_csv = REPORTS_DIR / f'{args.scenario}__solver_summary_main_cases.csv'
    md_path = REPORTS_DIR / f'{args.scenario}__scenario_qc_and_solver_summary.md'

    qc_df.to_csv(qc_csv, index=False, encoding='utf-8-sig')
    solver_df.to_csv(solver_csv, index=False, encoding='utf-8-sig')

    stress_note = (
        f"The selected week is intentionally scaled to the 0.99 quantile rather than to the maximum. "
        f"In the current scenario, the CHP heat-capacity proxy is {_fmt_num(h_max, 3)} MW, while the scaled 99th percentile is {_fmt_num(p99, 3)} MW and the maximum hour reaches {_fmt_num(float(peak['heat_demand_mw']), 3)} MW at {peak['datetime_local']}. "
        f"Thus, the extreme hour is about {_fmt_num(p99_ratio, 2)} times the scaled 99th percentile and {_fmt_num(h_max_ratio, 2)} times the CHP heat-capacity proxy. "
        f"Only {int(over_cap.sum())} out of {len(heat)} hours ({_fmt_num(float(over_cap.mean()*100.0), 3)}%) exceed the CHP heat-capacity proxy, which means that the extreme point is retained as a stress-test outlier but does not determine the scenario scaling. "
        f"Its main effect is local: it amplifies the visual scale of Figures 2 and 6 and contributes to peak-hour boiler need, whereas the matched-case and sensitivity conclusions are still driven by weekly totals, shares, and costs over the full 168 h horizon."
    )

    solver_note = (
        "All reported optimization results correspond to feasible MILP incumbents obtained under fixed computational budgets. "
        "Table-style solver diagnostics should therefore report, at minimum, the prescribed time limit, target relative gap, achieved termination status, achieved relative gap (when available from the solver interface), and measured runtime. "
        "For rolling MPC, it is useful to report both window-level diagnostics and the aggregate runtime across all windows, because the weekly implemented objective is reconstructed from the stitched 168 h dispatch rather than from the non-comparable sum of finite-horizon window objectives."
    )

    md = []
    md.append('# Scenario QC and solver summary\n')
    md.append('## Stress-test / extreme-hour note\n')
    md.append(stress_note + '\n')
    md.append('## Solver-summary note\n')
    md.append(solver_note + '\n')
    md.append('## Scenario QC summary table\n')
    md.append(qc_df.to_markdown(index=False) + '\n')
    md.append('## Solver summary table\n')
    md.append(solver_df.to_markdown(index=False) + '\n')

    md_path.write_text('\n'.join(md), encoding='utf-8')

    print('Wrote:', qc_csv)
    print('Wrote:', solver_csv)
    print('Wrote:', md_path)
    print('\n=== STRESS-TEST NOTE ===\n')
    print(stress_note)
    print('\n=== SOLVER NOTE ===\n')
    print(solver_note)


if __name__ == '__main__':
    main()
