from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from chp_pv_sim.experiments.config import batch_to_experiment_configs, load_batch_config
from chp_pv_sim.experiments.engine import build_batch_row, run_experiment
from chp_pv_sim.paths import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multiple UC/MPC experiments from one batch YAML file.")
    parser.add_argument("--config", required=True, help="Path to batch YAML config.")
    args = parser.parse_args()

    batch = load_batch_config(args.config)
    rows = []
    for name, cfg in batch_to_experiment_configs(batch):
        print(f"\n=== Running batch item: {name} | scenario={cfg.run.scenario} | method={cfg.run.method} | tag={cfg.run.tag} ===")
        artifacts = run_experiment(cfg)
        row = build_batch_row(artifacts)
        row["batch_name"] = name
        rows.append(row)

    out_path = ROOT / batch.output_csv
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n=== BATCH DONE ===")
    print(f"Batch summary CSV: {out_path}")
    if not df.empty:
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
