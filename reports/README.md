# Reports inventory

This folder keeps the paper-aligned frozen outputs that correspond to the submitted manuscript.

## Canonical manuscript tables

- `canonical_table34.csv` — Table 3 retained-baseline UC vs MPC KPI comparison.
- `canonical_table4_fw_numeric.csv` — Table 4 retained-baseline objective breakdown.
- `canonical_table5.csv` — Table 5 outlier-handling sensitivity.
- `canonical_table6.csv` — Table 6 solver-budget sensitivity. The low-budget row reuses the retained baseline.
- `canonical_table7.csv` — Table 7 MPC sensitivity to exogenous electric base load.
- `canonical_table8.csv` — Table 8 MPC sensitivity to dumping penalty.
- `canonical_table9.csv` — Table 9 additional cross-week validation.
- `table_A6_real_fw.csv` — Appendix Table A6 winsorized-case QC and solver diagnostics.
- `table_anchor_exactness_fw.csv` — Appendix Table A7 reduced-horizon certification anchors.

## Supporting QC and robustness artifacts

- `xai4heat_*` — heat-demand reconstruction reports and QC notes.
- `kaz_chpp_*` — CHP-table staging, extraction, and segment-consistency QC.
- `robustness/outlier_robustness_baseline_aligned.csv` — retained vs p99-winsorized matched-case KPI audit.
- `robustness/outlier_robustness_baseline_aligned.md` — narrative summary of the same audit.
- `robustness/outlier_robustness_cleaning_audit.json` — exact timestamps affected by winsorization.

## Figures

Released manuscript figures are stored under `reports/figures/week_2023_dec01/paper/`.

## File naming guidance

- `canonical_*` files are the manuscript-facing frozen tables.
- `table_*` files are appendix-style exports prepared for paper use.
- `*_qc*` files document data and model consistency checks.
- `robustness/*` keeps only the surviving outlier-handling audit that remains relevant to the manuscript.

Only the canonical, paper-consistent artifacts are kept in this cleaned release.
