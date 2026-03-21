from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float('nan')


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _tagged_paths(results_dir: Path, tag: str) -> Tuple[Path, Path]:
    return (
        results_dir / f'dispatch_summary_pv_grid__{tag}.json',
        results_dir / f'dispatch_chp_storage_pv_grid__{tag}.parquet',
    )



def _run(cmd: List[str]) -> None:
    print('\n[RUN]', ' '.join(cmd))
    subprocess.run(cmd, check=True)


def _extract_kpis(summary: Dict[str, Any]) -> Dict[str, Any]:
    totals = summary.get('totals', {}) or {}
    econ = summary.get('economics_realized', {}) or {}

    heat = _safe_float(totals.get('heat_demand_mwh'))
    boiler = _safe_float(totals.get('boiler_mwh'))
    dump = _safe_float(totals.get('dump_mwh'))
    gimp = _safe_float(totals.get('grid_import_mwh'))
    gexp = _safe_float(totals.get('grid_export_mwh'))
    echp = _safe_float(totals.get('E_chp_mwh'))
    echp_curt = _safe_float(totals.get('E_chp_curt_mwh'))

    boiler_share = (boiler / heat * 100.0) if heat > 1e-9 else float('nan')
    dump_share = (dump / heat * 100.0) if heat > 1e-9 else float('nan')
    curtail_ratio = (echp_curt / echp * 100.0) if echp > 1e-9 else float('nan')

    system_cost_realized = econ.get('system_cost_realized')
    if system_cost_realized is None:
        system_cost_realized = summary.get('system_cost_realized')

    return {
        'system_cost_realized': _safe_float(system_cost_realized),
        'boiler_share_pct': boiler_share,
        'dump_share_pct': dump_share,
        'chp_curtailment_ratio_pct': curtail_ratio,
        'grid_import_mwh': gimp,
        'grid_export_mwh': gexp,
        'net_export_mwh': gexp - gimp,
    }


def _copy_scenario_tree(src_dir: Path, dst_dir: Path, *, force: bool) -> None:
    if dst_dir.exists():
        if not force:
            print(f'[SKIP] Clean scenario already exists: {dst_dir.name}')
            return
        print(f'[REMOVE] Existing clean scenario: {dst_dir}')
        shutil.rmtree(dst_dir)

    def _ignore(_dirpath: str, names: List[str]) -> List[str]:
        ignore = []
        if 'results' in names:
            ignore.append('results')
        if '__pycache__' in names:
            ignore.append('__pycache__')
        return ignore

    print(f'[COPY] {src_dir.name} -> {dst_dir.name}')
    shutil.copytree(src_dir, dst_dir, ignore=_ignore)


def _winsorize_heat_to_scaled_p99(scen_dir: Path) -> Dict[str, Any]:
    heat_path = scen_dir / 'heat.parquet'
    manifest_path = scen_dir / 'manifest.json'
    if not heat_path.exists():
        raise FileNotFoundError(f'Missing heat.parquet in scenario: {heat_path}')

    df = pd.read_parquet(heat_path)
    if 'datetime_local' not in df.columns or 'heat_demand_mw' not in df.columns:
        raise ValueError(
            f'heat.parquet must contain datetime_local and heat_demand_mw. Columns={list(df.columns)}'
        )

    df['datetime_local'] = pd.to_datetime(df['datetime_local'], errors='raise')
    df = df.sort_values('datetime_local').reset_index(drop=True)

    manifest = _read_json(manifest_path) if manifest_path.exists() else {}
    scaled_p99 = None
    for key in ['scaled_p99_mw', 'p99_mw']:
        if key in manifest:
            scaled_p99 = _safe_float(manifest[key])
            break
    if scaled_p99 is None:
        hs = manifest.get('heat_summary', {}) or {}
        for key in ['scaled_p99_mw', 'p99_mw']:
            if key in hs:
                scaled_p99 = _safe_float(hs[key])
                break
    if scaled_p99 is None or not (scaled_p99 == scaled_p99):
        scaled_p99 = float(pd.to_numeric(df['heat_demand_mw'], errors='raise').astype(float).quantile(0.99))

    demand = pd.to_numeric(df['heat_demand_mw'], errors='raise').astype(float)
    old_max = float(demand.max())
    mask = demand > scaled_p99
    changed_times = df.loc[mask, 'datetime_local'].dt.strftime('%Y-%m-%d %H:%M').tolist()
    n_changed = int(mask.sum())

    if n_changed > 0:
        df.loc[mask, 'heat_demand_mw'] = scaled_p99

    try:
        df.to_parquet(heat_path, index=False, engine='pyarrow', compression='zstd')
    except Exception:
        df.to_parquet(heat_path, index=False, engine='pyarrow')

    audit = {
        'method': 'winsorize_scaled_p99',
        'scaled_p99_value_mw': scaled_p99,
        'old_max_mw': old_max,
        'n_changed_hours': n_changed,
        'changed_hours': changed_times,
        'created_utc': datetime.utcnow().isoformat() + 'Z',
    }

    manifest['anomaly_handling'] = audit
    _write_json(manifest_path, manifest)

    print(f'[CLEAN] winsorize_scaled_p99 applied: threshold={scaled_p99:.3f}, changed_hours={n_changed}')
    return audit


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Run a minimal outlier robustness check aligned with the current paper baseline.'
    )
    ap.add_argument('--scenario', default='week_2023_dec01', help='Baseline scenario used in the paper.')
    ap.add_argument('--clean-suffix', default='_winsor_p99_fw', help='Suffix for the cleaned scenario folder.')

    # Baseline case settings (must match the paper baseline)
    ap.add_argument('--e-load', type=float, default=20.0)
    ap.add_argument('--dump-cost', type=float, default=50.0)
    ap.add_argument('--startup-cost', type=float, default=5000.0)
    ap.add_argument('--min-up', type=int, default=3)
    ap.add_argument('--min-down', type=int, default=2)
    ap.add_argument('--horizon', type=int, default=48)
    ap.add_argument('--step', type=int, default=24)
    ap.add_argument('--uc-time-limit', type=int, default=900)
    ap.add_argument('--uc-gap', type=float, default=0.2)
    ap.add_argument('--mpc-window-time', type=int, default=120)
    ap.add_argument('--mpc-gap', type=float, default=0.2)

    # IMPORTANT: baseline tags should match the CURRENT manuscript baseline
    ap.add_argument('--uc-baseline-tag', default='uc_paper_retained_fw')
    ap.add_argument('--mpc-baseline-tag', default='mpc_paper_retained_fw')

    ap.add_argument('--rerun-baseline', action='store_true', help='Re-run baseline UC/MPC instead of reusing the tagged baseline artifacts.')
    ap.add_argument('--force-clean', action='store_true', help='Recreate the cleaned scenario folder from scratch.')
    ap.add_argument('--force-clean-solves', action='store_true', help='Re-run the cleaned scenario solves even if tagged outputs exist.')
    args = ap.parse_args()

    from chp_pv_sim.paths import ROOT

    base_scenario = args.scenario
    clean_scenario = f'{base_scenario}{args.clean_suffix}'

    base_dir = ROOT / 'data' / 'scenarios' / base_scenario
    if not base_dir.exists():
        raise FileNotFoundError(f'Baseline scenario not found: {base_dir}')

    # Baseline tagged artifacts must exist unless user explicitly asks to re-run them.
    base_res_dir = base_dir / 'results'
    base_uc_json, _ = _tagged_paths(base_res_dir, args.uc_baseline_tag)
    base_mpc_json, _ = _tagged_paths(base_res_dir, args.mpc_baseline_tag)
    if (not args.rerun_baseline) and (not base_uc_json.exists() or not base_mpc_json.exists()):
        raise FileNotFoundError(
            'Baseline tagged artifacts were not found. Expected:\n'
            f'  {base_uc_json}\n'
            f'  {base_mpc_json}\n'
            'Either create/copy these baseline tags first, or re-run with --rerun-baseline.'
        )

    clean_dir = ROOT / 'data' / 'scenarios' / clean_scenario
    _copy_scenario_tree(base_dir, clean_dir, force=args.force_clean)
    _winsorize_heat_to_scaled_p99(clean_dir)

    out_dir = ROOT / 'reports' / 'robustness'
    _ensure_dir(out_dir)

    def run_or_load_case(scenario_name: str, strategy: str, rerun: bool) -> Path:
        scen_dir = ROOT / 'data' / 'scenarios' / scenario_name
        res_dir = scen_dir / 'results'
        _ensure_dir(res_dir)

        tag = args.uc_baseline_tag if strategy == 'UC' else args.mpc_baseline_tag
        sum_path, parq_path = _tagged_paths(res_dir, tag)

        if (not rerun) and sum_path.exists():
            print(f'[USE EXISTING] {strategy} {scenario_name}: {sum_path.name}')
            return sum_path

        if strategy == 'UC':
            cmd = [
                sys.executable,
                '-m',
                'chp_pv_sim.models.chp_week_storage_pv_grid_dispatch',
                '--scenario', scenario_name,
                '--tag', tag,
                '--e_load_base', str(args.e_load),
                '--cost_dump', str(args.dump_cost),
                '--startup_cost', str(args.startup_cost),
                '--min_up', str(args.min_up),
                '--min_down', str(args.min_down),
                '--time-limit-s', str(args.uc_time_limit),
                '--mip-rel-gap', str(args.uc_gap),
            ]
            _run(cmd)
            if not sum_path.exists() or not parq_path.exists():
               raise FileNotFoundError(f'After UC run, missing outputs: {sum_path} or {parq_path}')
            return sum_path

        if strategy == 'MPC':
            cmd = [
                sys.executable,
                '-m',
                'chp_pv_sim.models.chp_week_mpc_pv_grid_dispatch',
                '--scenario', scenario_name,
                '--tag', tag,
                '--horizon', str(args.horizon),
                '--step', str(args.step),
                '--e_load_base', str(args.e_load),
                '--cost_dump', str(args.dump_cost),
                '--startup_cost', str(args.startup_cost),
                '--min_up', str(args.min_up),
                '--min_down', str(args.min_down),
                '--time-limit-window', str(args.mpc_window_time),
                '--mip-rel-gap', str(args.mpc_gap),
            ]
            _run(cmd)
            if not sum_path.exists() or not parq_path.exists():
               raise FileNotFoundError(f'After MPC run, missing outputs: {sum_path} or {parq_path}')
            return sum_path

        raise ValueError(f'Unknown strategy: {strategy}')

    # Baseline: by default, REUSE the current paper baseline artifacts.
    base_uc_path = run_or_load_case(base_scenario, 'UC', rerun=args.rerun_baseline)
    base_mpc_path = run_or_load_case(base_scenario, 'MPC', rerun=args.rerun_baseline)

    # Cleaned scenario: run with the SAME settings as the current paper baseline.
    clean_uc_path = run_or_load_case(clean_scenario, 'UC', rerun=args.force_clean_solves)
    clean_mpc_path = run_or_load_case(clean_scenario, 'MPC', rerun=args.force_clean_solves)

    rows = []
    for scenario_variant, treatment, uc_path, mpc_path in [
        (base_scenario, 'retained', base_uc_path, base_mpc_path),
        (clean_scenario, 'winsorized p99', clean_uc_path, clean_mpc_path),
    ]:
        uc_sum = _read_json(uc_path)
        mpc_sum = _read_json(mpc_path)
        rows.append({
            'scenario_variant': scenario_variant,
            'treatment': treatment,
            'strategy': 'UC',
            'tag': args.uc_baseline_tag,
            **_extract_kpis(uc_sum),
        })
        rows.append({
            'scenario_variant': scenario_variant,
            'treatment': treatment,
            'strategy': 'MPC',
            'tag': args.mpc_baseline_tag,
            **_extract_kpis(mpc_sum),
        })

    df = pd.DataFrame(rows)
    df = df[[
        'scenario_variant',
        'treatment',
        'strategy',
        'tag',
        'system_cost_realized',
        'boiler_share_pct',
        'dump_share_pct',
        'chp_curtailment_ratio_pct',
        'grid_import_mwh',
        'grid_export_mwh',
        'net_export_mwh',
    ]]

    csv_path = out_dir / 'outlier_robustness_baseline_aligned.csv'
    md_path = out_dir / 'outlier_robustness_baseline_aligned.md'
    audit_path = out_dir / 'outlier_robustness_cleaning_audit.json'

    df.to_csv(csv_path, index=False)
    try:
        md_path.write_text(df.to_markdown(index=False), encoding='utf-8')
    except Exception:
        md_path.write_text(df.to_string(index=False), encoding='utf-8')

    clean_manifest = _read_json(clean_dir / 'manifest.json') if (clean_dir / 'manifest.json').exists() else {}
    audit = clean_manifest.get('anomaly_handling', {})
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\n=== Outlier robustness (baseline-aligned) written ===')
    print('CSV :', csv_path)
    print('MD  :', md_path)
    print('AUD :', audit_path)
    print('\nPreview:\n', df.to_string(index=False))


if __name__ == '__main__':
    main()