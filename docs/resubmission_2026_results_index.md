# Resubmission 2026 Results Index

This index aggregates committed resubmission artifacts only. No optimization runs were performed to create these tables.

## Result Hierarchy

| Layer | Purpose | Table |
|---|---|---|
| Main case | Winsorized p99 full-week 168 h UC/MPC comparison | `docs/resubmission_2026_table_main_results.csv` |
| Outlier robustness | Raw retained 944.9 MW outlier versus winsorized p99 | `docs/resubmission_2026_table_outlier_robustness.csv` |
| Export-cap sensitivity | 0, 30, 60, and 90 MW export-cap cases | `docs/resubmission_2026_table_export_cap_sensitivity.csv` |
| TES-capacity sensitivity | 0.5x, 1.0x, and 1.5x thermal storage capacity cases | `docs/resubmission_2026_table_tes_capacity_sensitivity.csv` |

## Main Numerical Conclusions

| Study | Key result |
|---|---|
| Main winsorized p99 | UC objective = -258690.055995; MPC implemented objective = -262214.245647; UC - MPC = 3524.189651. |
| Outlier robustness | Raw retained outlier case remains feasible and valid, but objectives worsen materially: raw UC = -295204.134355 and raw MPC = -297939.333870. The UC - MPC difference narrows to 2735.199514. |
| Export cap | UC remains higher than MPC at 0, 30, 60, and 90 MW. The 60 MW main cap is not binding because the maximum export is 39.866863 MW in the baseline UC/MPC results. |
| TES capacity | Larger TES improves both methods. The baseline 800 MWh case has a UC advantage of 3524.189651; at 400 MWh the polished MPC result is higher by 9.528252 objective units, which is effectively a near tie at this scale; at 1200 MWh the UC advantage is 99.237848. |

## Reproducibility Checklist

### Scenarios

| Scenario | Use |
|---|---|
| `data/scenarios/week_2023_dec01_winsor_p99_fw` | Primary full-week winsorized p99 case; 944.9 MW heat outlier absent. |
| `data/scenarios/week_2023_dec01` | Raw retained robustness case; 944.910244 MW heat outlier present. |

### Solver And Model Settings

All listed runs use `formulation: convex_hull` and a requested relative MIP gap of `0.002` (`0.2%`). UC runs use a 900 s solve limit unless noted by their committed config. MPC runs use the repository rolling convention with a 48 h horizon and 24 h implementation step. The deterministic settings are one thread, parallel off, random seed 1, and presolve on.

The UC and MPC comparisons do not have equal total allowed solver budgets: UC uses one solve, while MPC uses rolling-window solves. This should be stated explicitly in the manuscript as a controlled operational comparison rather than an equal-total-budget solver benchmark.

### Config Files

| Study | Configs |
|---|---|
| Main case | `configs/experiments/resubmission_2026/final_main/main_winsor_p99_hull_uc_168h_gap0p002.yaml`; `configs/experiments/resubmission_2026/final_main/main_winsor_p99_hull_mpc_168h_gap0p002.yaml` |
| Outlier robustness | `configs/experiments/resubmission_2026/outlier_robustness/raw_hull_uc_168h_gap0p002.yaml`; `configs/experiments/resubmission_2026/outlier_robustness/raw_hull_mpc_168h_gap0p002.yaml` |
| Export cap | `configs/experiments/resubmission_2026/sensitivity_export_cap/exportcap_0_hull_uc_168h_gap0p002.yaml`; `configs/experiments/resubmission_2026/sensitivity_export_cap/exportcap_0_hull_mpc_168h_gap0p002.yaml`; `configs/experiments/resubmission_2026/sensitivity_export_cap/exportcap_30_hull_uc_168h_gap0p002.yaml`; `configs/experiments/resubmission_2026/sensitivity_export_cap/exportcap_30_hull_mpc_168h_gap0p002.yaml`; baseline 60 MW uses the main-case configs; `configs/experiments/resubmission_2026/sensitivity_export_cap/exportcap_90_hull_uc_168h_gap0p002.yaml`; `configs/experiments/resubmission_2026/sensitivity_export_cap/exportcap_90_hull_mpc_168h_gap0p002_t600.yaml` |
| TES capacity | `configs/experiments/resubmission_2026/sensitivity_tes_capacity/tescap_0p5_hull_uc_168h_gap0p002.yaml`; `configs/experiments/resubmission_2026/sensitivity_tes_capacity/tescap_0p5_hull_mpc_168h_gap0p002_t1200.yaml`; baseline 1.0x uses the main-case configs; `configs/experiments/resubmission_2026/sensitivity_tes_capacity/tescap_1p5_hull_uc_168h_gap0p002.yaml`; `configs/experiments/resubmission_2026/sensitivity_tes_capacity/tescap_1p5_hull_mpc_168h_gap0p002.yaml` |

### Result Artifact Families

For every tag in the CSV tables, the committed artifacts are the corresponding files under the scenario `results/` directory:

| Artifact | Pattern |
|---|---|
| Dispatch | `dispatch_chp_storage_pv_grid__<tag>.parquet` |
| Summary | `dispatch_summary_pv_grid__<tag>.json` |
| Solver windows | `solver_windows_pv_grid__<tag>.csv` |
| Physical validation | `dispatch_validation_pv_grid__<tag>.json` |

## Manuscript-Ready Interpretation Bullets

- Use the winsorized p99 scenario as the main case because the raw retained week contains a single 944.910244 MW heat-demand point that materially changes the economics. Retain the raw scenario as a robustness check for transparency.
- The raw outlier case is feasible and physically valid, but it introduces large boiler cost and makes both UC and MPC objectives substantially lower. It does not reverse the qualitative UC/MPC ordering.
- Export-cap sensitivity supports 60 MW as the main cap. The 0 MW and 30 MW caps bind and reduce objective value; the 60 MW and 90 MW cases do not materially differ because realized export remains below 60 MW.
- TES-capacity sensitivity shows that storage size matters. Larger TES improves both UC and MPC, while the UC advantage is strongest at the 800 MWh baseline and much smaller at 400 MWh and 1200 MWh.
- Phrase solver outcomes as "within the requested 0.2% MIP tolerance." A solver termination labelled `optimal` in these artifacts means the requested MIP tolerance was reached, not that a zero-gap global proof was obtained.

## Supporting Audit Documents

- `docs/objective_and_formulation_audit_24h.md`
- `docs/lp_relaxation_anatomy_24h.md`
- `docs/final_main_winsor_p99_168h_summary.md`
- `docs/outlier_robustness_168h_summary.md`
- `docs/export_cap_sensitivity_168h_summary.md`
- `docs/tes_capacity_sensitivity_168h_summary.md`

## Known Caveats

- MPC objectives are implemented-interval objectives only; overlapping look-ahead objectives are not summed.
- The export-cap 90 MW MPC row uses the committed 600 s/window polishing run so all windows meet the requested tolerance.
- The 0.5x TES MPC row uses the committed 1200 s/window polishing run so all windows meet the requested tolerance.
