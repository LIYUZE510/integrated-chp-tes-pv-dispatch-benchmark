from __future__ import annotations

import argparse
import json

from chp_pv_sim.experiments.config import load_experiment_config
from chp_pv_sim.experiments.engine import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one UC or MPC experiment from a YAML config file.")
    parser.add_argument("--config", required=True, help="Path to YAML config, for example configs/experiments/paper_retained_uc_fw.yaml")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing tagged output artifacts intentionally.")
    args = parser.parse_args()

    cfg = load_experiment_config(args.config)
    artifacts = run_experiment(cfg, overwrite=bool(args.overwrite))

    print("\n=== DONE ===")
    print(f"Dispatch   : {artifacts.dispatch_path}")
    print(f"Summary    : {artifacts.summary_path}")
    print(f"Windows CSV: {artifacts.windows_path}")
    print(f"Validation : {artifacts.validation_path}")
    print("\nValidation summary:")
    print(json.dumps(artifacts.validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
