from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from chp_pv_sim.paths import ROOT, ensure_dirs


def _backup_move(path: Path) -> None:
    if path.exists():
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = path.with_name(f"{path.stem}__backup_{ts}{path.suffix}")
        path.rename(bak)
        print(f"[backup] {path.name} -> {bak.name}", flush=True)


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--tag", required=True, help="e.g. mpc_eload20MW_dump50")
    args = ap.parse_args()

    res_dir = ROOT / "data" / "scenarios" / args.scenario / "results"
    if not res_dir.exists():
        raise FileNotFoundError(f"Scenario results dir not found: {res_dir}")

    src_sum = res_dir / f"dispatch_summary_pv_grid__{args.tag}.json"
    src_parq = res_dir / f"dispatch_chp_storage_pv_grid__{args.tag}.parquet"

    if not src_sum.exists():
        raise FileNotFoundError(f"Missing: {src_sum}")
    if not src_parq.exists():
        raise FileNotFoundError(f"Missing: {src_parq}")

    dst_sum = res_dir / "dispatch_summary_pv_grid.json"
    dst_parq = res_dir / "dispatch_chp_storage_pv_grid.parquet"

    _backup_move(dst_sum)
    _backup_move(dst_parq)

    shutil.copy2(src_sum, dst_sum)
    shutil.copy2(src_parq, dst_parq)

    print("\n[promoted] Now active files are:")
    print(" -", dst_sum)
    print(" -", dst_parq)
    print("\nYou can now run:")
    print(f"  python -m chp_pv_sim.reports.week_pv_grid_report --scenario {args.scenario}")


if __name__ == "__main__":
    main()