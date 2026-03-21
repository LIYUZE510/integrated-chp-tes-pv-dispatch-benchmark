from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Copy an existing scenario and winsorize heat_demand_mw at its scaled p99 threshold.'
    )
    ap.add_argument('--src', required=True, help='Existing scenario folder name, e.g. week_2023_dec01')
    ap.add_argument('--dst', required=True, help='New scenario folder name, e.g. week_2023_dec01_winsor_p99_fw')
    ap.add_argument('--force', action='store_true', help='Overwrite destination scenario if it already exists')
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    scen_root = root / 'data' / 'scenarios'
    src_dir = scen_root / args.src
    dst_dir = scen_root / args.dst

    if not src_dir.exists():
        raise FileNotFoundError(f'Source scenario does not exist: {src_dir}')

    if dst_dir.exists():
        if not args.force:
            raise FileExistsError(
                f'Destination scenario already exists: {dst_dir}\n'
                'Delete it first or rerun with --force.'
            )
        shutil.rmtree(dst_dir)

    def _ignore(_dirpath: str, names: list[str]) -> list[str]:
        out: list[str] = []
        if 'results' in names:
            out.append('results')
        if '__pycache__' in names:
            out.append('__pycache__')
        return out

    shutil.copytree(src_dir, dst_dir, ignore=_ignore)

    heat_path = dst_dir / 'heat.parquet'
    manifest_path = dst_dir / 'manifest.json'
    if not heat_path.exists():
        raise FileNotFoundError(f'Missing heat.parquet in copied scenario: {heat_path}')

    df = pd.read_parquet(heat_path)
    if 'heat_demand_mw' not in df.columns:
        raise KeyError('heat.parquet must contain heat_demand_mw')
    if 'datetime_local' not in df.columns:
        raise KeyError('heat.parquet must contain datetime_local')

    df['datetime_local'] = pd.to_datetime(df['datetime_local'], errors='raise')
    demand = pd.to_numeric(df['heat_demand_mw'], errors='raise').astype(float)
    threshold = float(demand.quantile(0.99))
    changed_mask = demand > threshold
    changed_hours = df.loc[changed_mask, 'datetime_local'].dt.strftime('%Y-%m-%d %H:%M').tolist()
    n_changed = int(changed_mask.sum())
    old_max = float(demand.max())

    if n_changed > 0:
        df.loc[changed_mask, 'heat_demand_mw'] = threshold

    try:
        df.to_parquet(heat_path, index=False, engine='pyarrow', compression='zstd')
    except Exception:
        df.to_parquet(heat_path, index=False)

    manifest = _read_json(manifest_path)
    manifest['anomaly_handling'] = {
        'method': 'winsorize_scaled_p99_from_existing_scenario',
        'source_scenario': args.src,
        'threshold_mw': threshold,
        'old_max_mw': old_max,
        'n_changed_hours': n_changed,
        'changed_hours': changed_hours,
        'created_utc': datetime.now(tz=timezone.utc).isoformat(),
    }
    _write_json(manifest_path, manifest)

    print('DONE')
    print(f'Source scenario      : {src_dir}')
    print(f'New winsorized folder: {dst_dir}')
    print(f'Winsor threshold MW  : {threshold:.6f}')
    print(f'Changed hours        : {n_changed}')
    if changed_hours:
        print('Changed timestamps   :')
        for x in changed_hours:
            print(f'  - {x}')


if __name__ == '__main__':
    main()
