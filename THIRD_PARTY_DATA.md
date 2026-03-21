# Third-party data notice

This repository includes public third-party source data, extracted public tables, and derived benchmark artifacts.

Unless a file states otherwise, the MIT License in this repository applies to:

- source code under `src/`, `tests/`, and `tools/`, and
- original repository documentation such as `README.md`, `CONTRIBUTING.md`, and report inventory notes.

The MIT License does **not** automatically replace or supersede the upstream terms of third-party datasets or their derivatives.

## Included public sources

- XAI4HEAT SCADA Dataset 2024 — provenance recorded in `data/raw/xai4heat_scada_v1/manifest.json`
- Data for Modeling Large-scale Coal-Fired CHP Plant in Kazakhstan: Two Cases — provenance recorded in `data/raw/kaz_chpp_v3/manifest.json`
- NASA POWER-based PV availability inputs used by the scenario builder

## Practical guidance

Before redistributing or reusing files under `data/` or `reports/`, check:

1. the manifest and README files under `data/raw/`,
2. the dataset terms from the original providers, and
3. your own downstream publication or repository requirements.

When in doubt, treat benchmark data products and frozen report artifacts as carrying upstream attribution obligations in addition to this repository's code license.
