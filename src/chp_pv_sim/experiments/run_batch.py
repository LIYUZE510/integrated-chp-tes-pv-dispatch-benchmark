from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from chp_pv_sim.experiments.config import batch_to_experiment_configs, load_batch_config
from chp_pv_sim.experiments.engine import (
    build_batch_row,
    ensure_no_existing_paths,
    experiment_artifact_paths,
    run_experiment,
)
from chp_pv_sim.paths import ROOT


def _normalized_planned_path(path: Path) -> str:
    return os.path.normpath(str(Path(path).resolve(strict=False))).casefold()


def _ensure_unique_planned_outputs(planned: list[tuple[Path, str]]) -> None:
    seen: dict[str, list[str]] = {}
    for path, label in planned:
        key = _normalized_planned_path(path)
        seen.setdefault(key, []).append(label)

    duplicates = {key: labels for key, labels in seen.items() if len(labels) > 1}
    if not duplicates:
        return

    lines = []
    for key in sorted(duplicates):
        labels = "; ".join(duplicates[key])
        lines.append(f"  - {key}: {labels}")
    raise ValueError(
        "Duplicate planned batch output path(s) detected before execution:\n"
        + "\n".join(lines)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multiple UC/MPC experiments from one batch YAML file.")
    parser.add_argument("--config", required=True, help="Path to batch YAML config.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing batch and tagged output artifacts intentionally.")
    args = parser.parse_args()

    batch = load_batch_config(args.config)
    items = batch_to_experiment_configs(batch)
    out_path = ROOT / batch.output_csv
    planned_outputs: list[tuple[Path, str]] = [(out_path, f"batch summary ({batch.output_csv})")]
    for name, cfg in items:
        label = f"batch item '{name}' tag '{cfg.run.tag}'"
        planned_outputs.extend((path, label) for path in experiment_artifact_paths(cfg))
    _ensure_unique_planned_outputs(planned_outputs)

    preflight_paths = [path for path, _ in planned_outputs]
    ensure_no_existing_paths(
        preflight_paths,
        context="batch output",
        overwrite=bool(args.overwrite),
    )

    rows = []
    for name, cfg in items:
        print(f"\n=== Running batch item: {name} | scenario={cfg.run.scenario} | method={cfg.run.method} | tag={cfg.run.tag} ===")
        artifacts = run_experiment(cfg, overwrite=bool(args.overwrite))
        row = build_batch_row(artifacts)
        row["batch_name"] = name
        rows.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\n=== BATCH DONE ===")
    print(f"Batch summary CSV: {out_path}")
    if not df.empty:
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
