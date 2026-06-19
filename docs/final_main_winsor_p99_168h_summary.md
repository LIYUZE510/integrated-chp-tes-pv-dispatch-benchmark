# Final Main 168-Hour Winsorized Convex-Hull Results

Generated for the resubmission final main case on `2026-06-19`.

## Case Definition

| Field | UC | MPC |
|---|---|---|
| Config | `configs/experiments/resubmission_2026/final_main/main_winsor_p99_hull_uc_168h_gap0p002.yaml` | `configs/experiments/resubmission_2026/final_main/main_winsor_p99_hull_mpc_168h_gap0p002.yaml` |
| Tag | `resub_2026_final_main_winsor_p99_hull_uc_168h_gap0p002` | `resub_2026_final_main_winsor_p99_hull_mpc_168h_gap0p002` |
| Scenario | `week_2023_dec01_winsor_p99_fw` | `week_2023_dec01_winsor_p99_fw` |
| Method | UC | MPC |
| Formulation | `convex_hull` | `convex_hull` |
| MIP gap tolerance | `0.002` / `0.2%` | `0.002` / `0.2%` |
| Time limit | 900 s | 300 s per window |
| Rolling horizon | n/a | 48 h horizon, 24 h implemented step |
| Terminal SOC policy | match initial | match window initial; final windows match week initial |

The selected scenario has 168 hourly records. The original 944.910244 MW heat outlier is absent; the scenario manifest records p99 winsorization to 158.231325 MW at `2023-12-01 08:00` and `2023-12-05 07:00`.

## Solver Diagnostics

| Case | Status | Termination | Runtime s | Incumbent | Best bound | Abs. distance | Gap frac. | Gap % | Source |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| UC | ok | optimal | 275.167962 | -258690.055995 | -258666.550792 | 23.505204 | 0.000090862 | 0.009086 | highspy_info |
| MPC w1 | ok | optimal | 118.203554 | -71362.397490 | -71295.521438 | 66.876052 | 0.000937133 | 0.093713 | highspy_info |
| MPC w2 | ok | optimal | 192.311264 | -73415.613243 | -73268.879361 | 146.733882 | 0.001998674 | 0.199867 | highspy_info |
| MPC w3 | ok | optimal | 57.986033 | -76388.405893 | -76238.465446 | 149.940447 | 0.001962869 | 0.196287 | highspy_info |
| MPC w4 | ok | optimal | 52.483138 | -74911.841231 | -74762.131906 | 149.709325 | 0.001998473 | 0.199847 | highspy_info |
| MPC w5 | ok | optimal | 21.351656 | -74736.415568 | -74735.191795 | 1.223772 | 0.000016375 | 0.001637 | highspy_info |
| MPC w6 | ok | optimal | 24.715858 | -75005.763202 | -75005.705541 | 0.057661 | 0.000000769 | 0.000077 | highspy_info |
| MPC w7 | ok | optimal | 11.175621 | -37816.608456 | -37816.376572 | 0.231884 | 0.000006132 | 0.000613 | highspy_info |

All explicit diagnostic fields agree with legacy aliases. Reported gaps recompute from stored incumbent and bound values.

## Physical Validation

| Case | Pass | Heat resid. max | Elec. resid. max | Import/export overlap | Export max / cap | SOC min / max | Initial / final SOC | Terminal gap | PV curt. | CHP curt. | Dump | Under |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| UC | true | 0.000000000000 | 0.000000000000 | 0.000000002370 | 39.866863 / 60.000000 | 0.000000 / 800.000000 | 200.000000 / 200.000000 | 0.000000000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| MPC | true | 0.000000000000 | 0.000000002135 | 0.000000000002 | 39.866863 / 60.000000 | 146.613316 / 800.000000 | 200.000000 / 200.000000 | 0.000000000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |

## MPC Stitching

| Check | Result |
|---|---:|
| Implemented rows | 168 |
| Unique timestamps | 168 |
| Duplicate timestamps | 0 |
| Missing/irregular hourly gaps | 0 |
| Maximum adjacent SOC discontinuity | 0.000000000000e+00 |
| Commitment transition violations | 0 |
| Min-up/min-down stitched violations | 0 |
| Implemented records per window | `{1: 24, 2: 24, 3: 24, 4: 24, 5: 24, 6: 24, 7: 24}` |

| Boundary | Summary SOC gap | Dispatch SOC gap | Previous boundary SOC | Next window S0 |
|---|---:|---:|---:|---:|
| 1->2 | 0.000000000000e+00 | 0.000000000000e+00 | 455.906094419795 | 455.906094419795 |
| 2->3 | 0.000000000000e+00 | 0.000000000000e+00 | 618.913369418516 | 618.913369418516 |
| 3->4 | 0.000000000000e+00 | 0.000000000000e+00 | 513.091499373314 | 513.091499373314 |
| 4->5 | 0.000000000000e+00 | 0.000000000000e+00 | 405.227959737023 | 405.227959737023 |
| 5->6 | 0.000000000000e+00 | 0.000000000000e+00 | 361.810539715079 | 361.810539715079 |
| 6->7 | 0.000000000000e+00 | 0.000000000000e+00 | 220.019650591047 | 220.019650591047 |

The implemented trajectory certifies timestamp continuity, SOC continuity, commitment transitions, and stitched min-up/min-down compliance. Non-implemented look-ahead intervals and internal pre-window run-length counters are not independently certifiable from the retained dispatch alone beyond the stored `must_on`/`must_off` window fields and implemented rows.

## Objective Reconciliation

| Case | Reconstructed objective | Summary objective | Residual | Export revenue | Import cost | CHP fuel cost | Startup | Storage cycling |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| UC | -258690.055995499 | -258690.055995499 | 0.000000000000 | 127386.275076 | 12528.326190 | 368491.606103 | 5000.000000 | 56.398779 |
| MPC | -262214.245646979 | -262214.245646979 | 0.000000000000 | 128154.573342 | 11643.441344 | 373668.828968 | 5000.000000 | 56.548677 |

`UC - MPC objective = 3524.189651479130`, which is `1.362321268%` of `abs(UC objective)`. Since the objective is maximized, UC has the higher realized objective for this final main case. The overlapping MPC look-ahead objective sum is not used for this comparison.

## Solver Budget Fairness

| Item | Value |
|---|---:|
| UC allowed budget | 900 s |
| UC actual runtime | 275.167962 s |
| MPC allowed budget | 2100 s |
| MPC actual runtime | 478.227125 s |
| Equal per-solve budget | no |
| Equal total allowed budget | no |

Suggested paper phrasing: report this as a main-case deterministic UC/MPC outcome under method-appropriate budgets, not as a fair solver-speed comparison. State that UC used one 900 s full-horizon solve, while MPC used seven rolling solves with 300 s per window, so total allowed solver time differs.
