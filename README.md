# Integrated CHP–TES–PV Dispatch Benchmark

![CI](https://github.com/LIYUZE510/integrated-chp-tes-pv-dispatch-benchmark/actions/workflows/ci.yml/badge.svg) ![Release](https://github.com/LIYUZE510/integrated-chp-tes-pv-dispatch-benchmark/actions/workflows/release-package.yml/badge.svg) ![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

> Public-data benchmark for integrated CHP–TES–PV dispatch under grid export constraints, comparing full-horizon unit commitment (UC) and rolling-horizon model predictive control (MPC).

This repository is the paper-aligned open-source release for the study:

**Integrated CHP-TES-PV Dispatch in District Heating under Grid Export Constraints: A Public-Data Benchmark Comparison of Full-Horizon Unit Commitment and Rolling-Horizon MPC**

It packages the cleaned source code, released benchmark scenarios, and frozen manuscript-facing outputs needed to reproduce the submitted workflow from public inputs. The scope is intentionally narrow: this is a reproducible research artifact for the paper, not a general-purpose district-energy software framework.

## Highlights

- End-to-end public-data workflow covering heat-demand reconstruction, CHP feasible-set staging, PV profile generation, benchmark scenario packaging, and dispatch experiments.
- Paper-aligned retained scenarios and canonical `_fw` result tags only, with stale backups, duplicated outputs, and machine-specific leftovers removed.
- Frozen manuscript tables, appendix checks, and figures under `reports/` for direct audit against the submission.
- Lightweight regression tests, including checks that selected paper table values remain aligned with the released benchmark outputs.
- GitHub-ready metadata for public release, including license, contribution guidance, and CI workflows.

## Repository scope

This release keeps the final workflow elements that are still relevant to the manuscript:

- the public-data preprocessing code,
- the benchmark scenario definitions used in the paper,
- the UC and rolling-horizon MPC experiment engine,
- the frozen CSV/Markdown outputs that correspond to the submitted tables and appendix checks, and
- the helper scripts that still belong to the final paper workflow.

It intentionally excludes exploratory prototypes, archive folders, duplicate result tags, editor state, transient caches, and other materials that would add noise to a public repository.

## Repository layout

- `src/chp_pv_sim/` — package source code for datasets, scenarios, models, experiments, and report builders.
- `configs/experiments/` — canonical single-run and batch configurations used by the paper workflow.
- `data/raw/` — public-source manifests plus the released extracted source files needed for traceability.
- `data/processed/` — processed benchmark inputs used by the released scenarios.
- `data/scenarios/` — frozen paper scenarios and retained result artifacts.
- `reports/` — canonical manuscript tables, QC notes, robustness summaries, and released figures.
- `tools/` — paper-facing helper scripts that remain part of the final workflow.
- `tests/` — lightweight regression tests, including paper-table alignment checks.
- `.github/workflows/` — CI and release-artifact workflows for GitHub Actions.

## Paper-aligned benchmark scenarios

The retained scenarios in this release are:

- `week_2023_dec01` — retained-outlier baseline week used for the main benchmark comparison.
- `week_2023_dec01_winsor_p99_fw` — baseline-aligned p99-winsorized outlier-handling sensitivity.
- `week_2021_nov15` and `week_2022_jan17` — additional cross-week validation scenarios.
- `week_2023_dec01_anchor24h_fw` and `week_2023_dec01_anchor48h_fw` — reduced-horizon certification anchors.

Only the canonical `_fw` tags used by the manuscript are kept in this repository snapshot.

## Quick start

### 1. Create the environment

```bash
conda env create -f environment.yml
conda activate chp_tes_pv_dispatch
pip install -e .[dev]
```

If you prefer the fully pinned environment, create it from `environment.lock.yml` instead.

### 2. Run the test suite

```bash
pytest -q
```

### 3. Re-run the retained baseline

Full-horizon UC:

```bash
python -m chp_pv_sim.experiments.run_experiment   --config configs/experiments/paper_retained_uc_fw.yaml
```

Rolling-horizon MPC:

```bash
python -m chp_pv_sim.experiments.run_experiment   --config configs/experiments/paper_retained_mpc_fw.yaml
```

### 4. Re-run the manuscript batches

```bash
python -m chp_pv_sim.experiments.run_batch   --config configs/experiments/batch_paper_baselines_fw.yaml

python -m chp_pv_sim.experiments.run_batch   --config configs/experiments/batch_paper_budget_fw.yaml

python -m chp_pv_sim.experiments.run_batch   --config configs/experiments/batch_paper_eload_fw.yaml

python -m chp_pv_sim.experiments.run_batch   --config configs/experiments/batch_paper_cdump_fw.yaml

python -m chp_pv_sim.experiments.run_batch   --config configs/experiments/batch_exactness_anchor_fw.yaml
```

## Canonical paper outputs

The manuscript-facing frozen outputs are under `reports/`:

- Table 3: `reports/canonical_table34.csv`
- Table 4: `reports/canonical_table4_fw_numeric.csv`
- Table 5: `reports/canonical_table5.csv`
- Table 6: `reports/canonical_table6.csv`
- Table 7: `reports/canonical_table7.csv`
- Table 8: `reports/canonical_table8.csv`
- Table 9: `reports/canonical_table9.csv`
- Appendix A6: `reports/table_A6_real_fw.csv`
- Appendix A7: `reports/table_anchor_exactness_fw.csv`

See `reports/README.md` for the report inventory and naming conventions.

## Reproducibility notes

- The retained baseline and the p99-winsorized sensitivity use the matched operating settings described in the manuscript.
- The low-budget row in Table 6 is represented by the retained baseline, matching the paper text and the released canonical table.
- Regression tests include direct checks for selected values in Table 3, Table 6, and Table 9 so manuscript-facing outputs do not drift silently.
- This repository keeps frozen benchmark artifacts for auditability. Recomputing the full study still requires the full optimization stack and solver environment described by the project configuration files.

## Data provenance and licensing

The workflow is built on public inputs. Source manifests and provenance notes are kept under `data/raw/`.

Code and original repository documentation are released under the MIT License. Third-party public data and derived benchmark artifacts under `data/` and `reports/` may remain subject to their upstream terms. See `THIRD_PARTY_DATA.md` before redistributing or reusing those materials.

## Contributing

Contributions are welcome, but paper alignment comes first. Please read `CONTRIBUTING.md` before opening a pull request, especially if you plan to modify benchmark outputs, report builders, or manuscript-facing tables.

## Repository metadata

- Recommended repository name: `integrated-chp-tes-pv-dispatch-benchmark`
- Repository URL: `https://github.com/LIYUZE510/integrated-chp-tes-pv-dispatch-benchmark`
- Issues: `https://github.com/LIYUZE510/integrated-chp-tes-pv-dispatch-benchmark/issues`
- Releases: `https://github.com/LIYUZE510/integrated-chp-tes-pv-dispatch-benchmark/releases`

## Citation

If you use this repository, cite both the software release and the associated manuscript, together with the upstream public datasets referenced in the paper.

## License

This repository uses the MIT License for source code and original repository documentation. See `LICENSE`.
