# Outlier-Handling Robustness Audit: 168-Hour Main Case

Generated for resubmission robustness review on `2026-06-19`.

## Purpose

This audit compares the final main winsorized p99 full-week case against the raw retained `week_2023_dec01` scenario that contains the previously identified 944.910244 MW heat-demand outlier.

The model formulation, objective, physical parameters, terminal-SOC policies, and solver gap settings are unchanged. Only the input scenario and output tags differ between the raw robustness configs and the final main winsorized configs.

## Scenario Audit

| Scenario | Path | Records | Max Heat MW | Max e-load MW | Max Heat Timestamp | 944.9 MW Present | Treatment | Metadata |
|---|---|---:|---:|---:|---|---:|---|---|
| `week_2023_dec01` | `data/scenarios/week_2023_dec01` | 168 | 944.910244 | 20.000000 | 2023-12-01 08:00 | true | raw/retained | none |
| `week_2023_dec01_winsor_p99_fw` | `data/scenarios/week_2023_dec01_winsor_p99_fw` | 168 | 158.231325 | 20.000000 | 2023-12-01 08:00 | false | winsorized p99 | threshold 158.231325 MW; old max 944.910244 MW; changed hours `2023-12-01 08:00`, `2023-12-05 07:00` |
| `week_2023_dec01_anchor24h_fw` | `data/scenarios/week_2023_dec01_anchor24h_fw` | 24 | 152.245941 | 20.000000 | 2023-12-04 07:00 | false | anchor subset | not a full-week alternative |
| `week_2023_dec01_anchor48h_fw` | `data/scenarios/week_2023_dec01_anchor48h_fw` | 48 | 163.381081 | 20.000000 | 2023-12-05 07:00 | false | anchor subset | not a full-week alternative |

No removed or clipped full-week alternative was found among prepared scenarios.

## Raw Robustness Configs

| Case | Config | Tag | Scenario | Method | Formulation | Gap | Time Limit |
|---|---|---|---|---|---|---:|---:|
| Raw UC | `configs/experiments/resubmission_2026/outlier_robustness/raw_hull_uc_168h_gap0p002.yaml` | `resub_2026_outlier_raw_hull_uc_168h_gap0p002` | `week_2023_dec01` | UC | `convex_hull` | 0.002 | 900 s |
| Raw MPC | `configs/experiments/resubmission_2026/outlier_robustness/raw_hull_mpc_168h_gap0p002.yaml` | `resub_2026_outlier_raw_hull_mpc_168h_gap0p002` | `week_2023_dec01` | MPC | `convex_hull` | 0.002 | 300 s/window |

MPC uses the established 48-hour look-ahead horizon and 24-hour implementation step. Terminal-SOC policies match the final main case: `match_window_initial`, with final windows using `match_week_initial`.

## Raw Solver Diagnostics

| Case | Status | Termination | Runtime s | Incumbent | Best Bound | Abs. Distance | Gap % |
|---|---|---|---:|---:|---:|---:|---:|
| Raw UC | ok | optimal | 56.630889 | -295204.134355 | -295202.548696 | 1.585660 | 0.000537 |
| Raw MPC w1 | ok | optimal | 8.430690 | -107921.486271 | -107891.397087 | 30.089184 | 0.027881 |
| Raw MPC w2 | ok | optimal | 102.387816 | -72338.204107 | -72201.026644 | 137.177463 | 0.189633 |
| Raw MPC w3 | ok | optimal | 31.721084 | -75493.189274 | -75342.232139 | 150.957135 | 0.199961 |
| Raw MPC w4 | ok | optimal | 18.023219 | -74787.071409 | -74649.043476 | 138.027933 | 0.184561 |
| Raw MPC w5 | ok | optimal | 10.869544 | -74756.996011 | -74755.561113 | 1.434898 | 0.001919 |
| Raw MPC w6 | ok | optimal | 7.490687 | -74990.488932 | -74990.024063 | 0.464870 | 0.000620 |
| Raw MPC w7 | ok | optimal | 3.420542 | -37824.246510 | -37800.939330 | 23.307180 | 0.061620 |

All raw UC/MPC solves reached the requested 0.2% gap tolerance.

## Raw Physical Validation

| Case | Pass | Heat Resid. Max | Elec. Resid. Max | Export Max / Cap | SOC Min / Max | Terminal Gap | PV Curt. | CHP Curt. | Dump | Under |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Raw UC | true | 1.776357e-15 | 1.421085e-14 | 60.000000 / 60.000000 | 0.000000 / 800.000000 | 0.000000 | 0.000000 | 35.828030 | 0.000000 | 0.000000 |
| Raw MPC | true | 2.842171e-14 | 1.065814e-13 | 60.000000 / 60.000000 | 116.551702 / 800.000000 | 0.000000 | 0.000000 | 35.828030 | 0.000000 | 0.000000 |

Raw MPC stitching produced 168 implemented rows, 168 unique timestamps, no duplicate or missing hourly timestamps, zero adjacent SOC discontinuity, and 24 implemented records in each of seven windows.

## Raw vs. Winsorized Comparison

| Metric | Raw retained | Winsorized p99 | Raw - Winsor |
|---|---:|---:|---:|
| Max heat MW | 944.910244 | 158.231325 | 786.678919 |
| UC objective | -295204.134355 | -258690.055995 | -36514.078360 |
| MPC implemented objective | -297939.333870 | -262214.245647 | -35725.088223 |
| UC - MPC objective | 2735.199514 | 3524.189651 | -788.990137 |
| UC CHP cost | 377640.933510 | 368491.606103 | 9149.327407 |
| UC export revenue | 129419.489042 | 127386.275076 | 2033.213966 |
| UC startup cost | 5000.000000 | 5000.000000 | 0.000000 |
| UC storage cycling cost | 57.345239 | 56.398779 | 0.946460 |
| UC boiler cost | 33525.344648 | 0.000000 | 33525.344648 |
| UC heat dump MWh | 0.000000 | 0.000000 | 0.000000 |
| UC undersupply MWh | 0.000000 | 0.000000 | 0.000000 |
| MPC CHP cost | 382411.221040 | 373668.828968 | 8742.392072 |
| MPC export revenue | 131308.719994 | 128154.573342 | 3154.146653 |
| MPC startup cost | 5000.000000 | 5000.000000 | 0.000000 |
| MPC storage cycling cost | 60.994136 | 56.548677 | 4.445460 |
| MPC boiler cost | 33525.344648 | 0.000000 | 33525.344648 |
| MPC heat dump MWh | 0.000000 | 0.000000 | 0.000000 |
| MPC undersupply MWh | 0.000000 | 0.000000 | 0.000000 |
| Total solver runtime s | 238.974471 | 753.395087 | -514.420616 |
| UC reached requested gap | true | true | n/a |
| MPC all windows reached requested gap | true | true | n/a |
| UC validation pass | true | true | n/a |
| MPC validation pass | true | true | n/a |

Objective reconstruction residuals were effectively zero:

| Case | Residual |
|---|---:|
| Raw UC realized minus solver | -4.074536e-10 |
| Raw MPC | realized objective only; overlapping window objective not used |
| Winsor UC realized minus solver | -7.275958e-10 |
| Winsor MPC | realized objective only; overlapping window objective not used |

## Interpretation

The 944.910244 MW point materially distorts the economic result. Keeping the point increases the single-week UC operating-cost equivalent by about 36.5k objective units and the MPC operating-cost equivalent by about 35.7k objective units. The main mechanism is a new 33.5k boiler-cost contribution that is absent in the winsorized case, plus higher CHP cost. Physical validation remains clean and no heat undersupply is used, so the effect is not infeasibility; it is an economically large response to a single retained spike.

The qualitative UC-vs-MPC ranking does not change. UC has the higher profit-like objective in both cases:

| Treatment | UC - MPC Objective |
|---|---:|
| Raw retained | 2735.199514 |
| Winsorized p99 | 3524.189651 |

The raw outlier narrows the UC advantage by 788.990137 objective units, but it does not reverse it.

## Manuscript Transparency Wording

Recommended wording:

> The main full-week case uses a p99-winsorized version of the December 2023 scenario because the retained raw profile contains a single 944.9 MW heat-demand spike. The scenario manifest records the winsorization threshold and affected timestamps. As a robustness check, we also solved the raw retained scenario with the same convex-hull formulation and solver tolerances. The raw spike increased both UC and MPC operating-cost equivalents substantially, primarily through boiler use, but did not change the qualitative UC-vs-MPC ranking or physical-validity conclusions.

## Recommendation

Use the winsorized p99 scenario as the primary main case and include the raw retained scenario as an outlier-robustness check. No preprocessing change is indicated by this audit because the raw point is feasible but materially distorts reported economics.
