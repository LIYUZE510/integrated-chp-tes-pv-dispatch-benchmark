# Export-Cap Sensitivity Audit, 168 h Winsorized Main Case

## Scope

This audit uses the committed winsorized full-week scenario:

`data/scenarios/week_2023_dec01_winsor_p99_fw`

The baseline 60 MW cap row uses the committed final-main artifacts and was not rerun. New UC/MPC runs were created only for export caps 0, 30, and 90 MW with the convex-hull CHP segment formulation, `mip_rel_gap: 0.002`, deterministic single-thread solver settings, and the final-main terminal-SOC policies. The cap 90 MPC row uses a follow-up 600 s/window polishing rerun because the original 300 s/window run left one window just above the requested 0.2% MIP tolerance.

## Schema Finding

The export cap is configurable through YAML as `grid.grid_export_cap_mw`. The field is defined in `src/chp_pv_sim/experiments/config.py`, passed through the experiment engine to model construction in `src/chp_pv_sim/experiments/engine.py`, and used in the model as the finite `grid_export` upper bound and export-cap validation limit in `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py`.

Zero export cap is valid under the existing formulation and validation tests.

## Preflight Summary

All six original sensitivity configs validated before solving. Planned artifacts were the newly tagged summary JSON, solver-window CSV, validation JSON, and dispatch Parquet files for each new tag. No planned artifact existed before the runs, and no final-main, outlier, pilot, frozen, report, or manuscript path was planned for writing.

The cap 90 MPC polishing config, `resub_2026_exportcap_90_hull_mpc_168h_gap0p002_t600`, was validated separately. Its planned artifacts did not exist before the rerun and are distinct from the original cap 90 MPC 300 s/window artifacts.

Compared with the final-main configs, the only intentional effective differences were:

- `run.tag`
- `grid.grid_export_cap_mw`
- output paths induced by the new tags

The 60 MW baseline row reuses the committed final-main artifacts.

## Solver Diagnostics

| cap | method | win | status | termination | runtime_s | incumbent | bound | abs_dist | gap_% | req_% | aliases |
|---:|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 0 | UC | 1 | ok | optimal | 329.293 | -382594.246443 | -382518.951190 | 75.295253 | 0.019680 | 0.200 | ok |
| 0 | MPC | 1 | ok | optimal | 14.776 | -71379.765206 | -71296.758370 | 83.006837 | 0.116289 | 0.200 | ok |
| 0 | MPC | 2 | ok | optimal | 232.594 | -94070.477090 | -94023.849621 | 46.627470 | 0.049567 | 0.200 | ok |
| 0 | MPC | 3 | ok | optimal | 11.509 | -130299.432393 | -130235.455363 | 63.977030 | 0.049100 | 0.200 | ok |
| 0 | MPC | 4 | ok | optimal | 10.147 | -132848.734587 | -132800.333410 | 48.401176 | 0.036433 | 0.200 | ok |
| 0 | MPC | 5 | ok | optimal | 9.165 | -126656.633589 | -126595.701399 | 60.932190 | 0.048108 | 0.200 | ok |
| 0 | MPC | 6 | ok | optimal | 8.954 | -133746.243258 | -133639.463706 | 106.779552 | 0.079837 | 0.200 | ok |
| 0 | MPC | 7 | ok | optimal | 4.986 | -70997.456099 | -70957.198511 | 40.257588 | 0.056703 | 0.200 | ok |
| 30 | UC | 1 | ok | optimal | 150.640 | -259147.998090 | -258764.533989 | 383.464100 | 0.147971 | 0.200 | ok |
| 30 | MPC | 1 | ok | optimal | 63.245 | -71321.829180 | -71190.386646 | 131.442533 | 0.184295 | 0.200 | ok |
| 30 | MPC | 2 | ok | optimal | 216.004 | -72837.316655 | -72755.090981 | 82.225674 | 0.112889 | 0.200 | ok |
| 30 | MPC | 3 | ok | optimal | 14.714 | -78743.271784 | -78679.874737 | 63.397047 | 0.080511 | 0.200 | ok |
| 30 | MPC | 4 | ok | optimal | 11.192 | -74809.836632 | -74806.768358 | 3.068274 | 0.004101 | 0.200 | ok |
| 30 | MPC | 5 | ok | optimal | 7.843 | -74779.213672 | -74763.344558 | 15.869115 | 0.021221 | 0.200 | ok |
| 30 | MPC | 6 | ok | optimal | 8.901 | -75316.173134 | -75299.461848 | 16.711286 | 0.022188 | 0.200 | ok |
| 30 | MPC | 7 | ok | optimal | 3.724 | -37818.424964 | -37768.474060 | 49.950904 | 0.132081 | 0.200 | ok |
| 60 | UC | 1 | ok | optimal | 275.168 | -258690.055995 | -258666.550792 | 23.505204 | 0.009086 | 0.200 | ok |
| 60 | MPC | 1 | ok | optimal | 118.204 | -71362.397490 | -71295.521438 | 66.876052 | 0.093713 | 0.200 | ok |
| 60 | MPC | 2 | ok | optimal | 192.311 | -73415.613243 | -73268.879361 | 146.733882 | 0.199867 | 0.200 | ok |
| 60 | MPC | 3 | ok | optimal | 57.986 | -76388.405893 | -76238.465446 | 149.940447 | 0.196287 | 0.200 | ok |
| 60 | MPC | 4 | ok | optimal | 52.483 | -74911.841231 | -74762.131906 | 149.709325 | 0.199847 | 0.200 | ok |
| 60 | MPC | 5 | ok | optimal | 21.352 | -74736.415568 | -74735.191795 | 1.223772 | 0.001637 | 0.200 | ok |
| 60 | MPC | 6 | ok | optimal | 24.716 | -75005.763202 | -75005.705541 | 0.057661 | 0.000077 | 0.200 | ok |
| 60 | MPC | 7 | ok | optimal | 11.176 | -37816.608456 | -37816.376572 | 0.231884 | 0.000613 | 0.200 | ok |
| 90 | UC | 1 | ok | optimal | 553.564 | -258690.055995 | -258666.238616 | 23.817379 | 0.009207 | 0.200 | ok |
| 90 | MPC | 1 | ok | optimal | 56.545 | -71385.904399 | -71275.573987 | 110.330411 | 0.154555 | 0.200 | ok |
| 90 | MPC | 2 | ok | optimal | 208.520 | -72947.555525 | -72801.661117 | 145.894408 | 0.199999 | 0.200 | ok |
| 90 | MPC | 3 | ok | optimal | 12.024 | -74822.802597 | -74788.808202 | 33.994395 | 0.045433 | 0.200 | ok |
| 90 | MPC | 4 | ok | optimal | 10.886 | -74766.206793 | -74766.183336 | 0.023457 | 0.000031 | 0.200 | ok |
| 90 | MPC | 5 | ok | optimal | 9.070 | -74758.246160 | -74735.465892 | 22.780268 | 0.030472 | 0.200 | ok |
| 90 | MPC | 6 | ok | optimal | 9.794 | -75123.878689 | -75064.684460 | 59.194228 | 0.078795 | 0.200 | ok |
| 90 | MPC | 7 | ok | optimal | 3.658 | -37683.134053 | -37648.137759 | 34.996294 | 0.092870 | 0.200 | ok |

The cap 90 MPC diagnostics shown above are from the 600 s/window polishing rerun. Every cap 90 MPC window reached the requested 0.2% tolerance; window 2 closed at 0.199999%.

## Objective Decomposition

The objective was independently reconstructed from dispatch columns and config economics. Reconstruction residuals against saved summary objectives are roundoff only.

| cap | method | objective | export rev | import cost | CHP cost | boiler cost | startup | storage | curt/dump/under penalties | residual |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | UC | -382594.246443 | 0.00 | 11200.00 | 366341.74 | 0.00 | 5000.00 | 52.51 | -1.39e-11 | 0.000e+00 |
| 0 | MPC | -385659.948063 | 0.00 | 9704.43 | 370896.08 | 0.00 | 5000.00 | 59.44 | -6.66e-13 | 0.000e+00 |
| 30 | UC | -259147.998090 | 126930.22 | 11284.82 | 369732.44 | 0.00 | 5000.00 | 60.96 | 0.00e+00 | 2.910e-11 |
| 30 | MPC | -261754.908767 | 127488.28 | 9522.12 | 374656.36 | 0.00 | 5000.00 | 64.70 | 7.11e-13 | 2.910e-11 |
| 60 | UC | -258690.055995 | 127386.28 | 12528.33 | 368491.61 | 0.00 | 5000.00 | 56.40 | 0.00e+00 | 5.821e-11 |
| 60 | MPC | -262214.245647 | 128154.57 | 11643.44 | 373668.83 | 0.00 | 5000.00 | 56.55 | 4.22e-13 | 5.821e-11 |
| 90 | UC | -258690.055995 | 127386.28 | 12528.33 | 368491.61 | 0.00 | 5000.00 | 56.40 | 2.22e-12 | 0.000e+00 |
| 90 | MPC | -261954.840827 | 128630.78 | 11969.92 | 373556.86 | 0.00 | 5000.00 | 58.84 | 3.53e-15 | -5.821e-11 |

## Sensitivity Table

| cap MW | UC objective | MPC implemented objective | UC - MPC | UC advantage % of abs(UC) | export max UC/MPC | export revenue UC/MPC | CHP cost UC/MPC | boiler cost UC/MPC | both reached requested gap | validation | UC runtime_s | MPC total runtime_s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|
| 0 | -382594.246443 | -385659.948063 | 3065.701621 | 0.801 | 0.000/0.000 | 0.00/0.00 | 366341.74/370896.08 | 0.00/0.00 | yes | pass | 329.293 | 292.132 |
| 30 | -259147.998090 | -261754.908767 | 2606.910677 | 1.006 | 30.000/30.000 | 126930.22/127488.28 | 369732.44/374656.36 | 0.00/0.00 | yes | pass | 150.640 | 325.623 |
| 60 | -258690.055995 | -262214.245647 | 3524.189651 | 1.362 | 39.867/39.867 | 127386.28/128154.57 | 368491.61/373668.83 | 0.00/0.00 | yes | pass | 275.168 | 478.227 |
| 90 | -258690.055995 | -261954.840827 | 3264.784832 | 1.262 | 39.867/39.577 | 127386.28/128630.78 | 368491.61/373556.86 | 0.00/0.00 | yes | pass | 553.564 | 310.497 |

The cap 90 MPC objective is unchanged from the original 300 s/window run to roundoff, but the table uses the 600 s/window polishing rerun so the requested tolerance is met for every MPC window.

## Physical Validation

| cap | method | pass | heat resid | elec resid | overlap | export max/cap | SOC min/max | init/final/gap | PV curt | CHP curt | dump | under |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | UC | true | 2.842e-14 | 7.105e-15 | 0.000e+00 | 0.000/0 | 0.000/800.000 | 200.000/200.000/0.000e+00 | 0.000 | 2455.566 | -2.771e-13 | 0.000e+00 |
| 0 | MPC | true | 5.258e-13 | 1.776e-14 | 0.000e+00 | 0.000/0 | 0.000/800.000 | 200.000/200.000/0.000e+00 | 0.000 | 2446.923 | -1.332e-14 | 0.000e+00 |
| 30 | UC | true | 1.776e-15 | 9.024e-13 | -0.000e+00 | 30.000/30 | 0.000/800.000 | 200.000/200.000/0.000e+00 | 0.000 | 5.519 | 0.000e+00 | 0.000e+00 |
| 30 | MPC | true | 1.421e-14 | 5.539e-12 | 5.129e-15 | 30.000/30 | 135.461/800.000 | 200.000/200.000/0.000e+00 | 0.000 | 0.000 | 1.421e-14 | 0.000e+00 |
| 60 | UC | true | 2.842e-14 | 2.842e-14 | 2.370e-09 | 39.867/60 | 0.000/800.000 | 200.000/200.000/0.000e+00 | 0.000 | 0.000 | 0.000e+00 | 0.000e+00 |
| 60 | MPC | true | 1.421e-14 | 2.135e-09 | 2.383e-12 | 39.867/60 | 146.613/800.000 | 200.000/200.000/0.000e+00 | 0.000 | 0.000 | 8.438e-15 | 0.000e+00 |
| 90 | UC | true | 1.563e-13 | 1.990e-13 | 2.842e-14 | 39.867/90 | 0.000/800.000 | 200.000/200.000/0.000e+00 | 0.000 | 0.000 | 4.441e-14 | 0.000e+00 |
| 90 | MPC | true | 3.482e-12 | 3.553e-14 | 3.682e-14 | 39.577/90 | 135.461/800.000 | 200.000/200.000/0.000e+00 | 0.000 | 0.000 | 7.064e-17 | 0.000e+00 |

Standalone `validate_dispatch` also passed for every new UC/MPC dispatch.

## MPC Stitching

| cap | records | unique timestamps | missing/duplicate | max SOC boundary gap | commitment transition violations | min up/down violations |
|---:|---:|---:|---|---:|---:|---:|
| 0 | 168 | 168 | no | 0.000e+00 | 0 | 0 |
| 30 | 168 | 168 | no | 0.000e+00 | 0 | 0 |
| 60 | 168 | 168 | no | 0.000e+00 | 0 | 0 |
| 90 | 168 | 168 | no | 0.000e+00 | 0 | 0 |

## Interpretation

The 0 MW cap is strongly binding and materially lowers both UC and MPC objectives because export revenue is unavailable and CHP electrical curtailment is high. The 30 MW cap remains binding and is close to the 60 MW objective, but still slightly worse for UC.

The 60 MW cap is not binding in either final-main schedule: the maximum observed export is about 39.867 MW. Raising the cap to 90 MW does not improve the UC objective at all and does not materially change the export maximum. This supports using 60 MW as the main-case cap because it is above the economically used export level for the winsorized case while still being a concrete network constraint.

UC remains better than MPC at every tested cap. The UC-minus-MPC objective differences are positive across all rows: 3065.702 at 0 MW, 2606.911 at 30 MW, 3524.190 at 60 MW, and 3264.785 at 90 MW. The qualitative UC-vs-MPC ranking is therefore robust to these export-cap levels.

For manuscript reporting, note that the cap 90 MPC sensitivity row used a longer 600 s/window polishing budget to meet the same 0.2% MIP tolerance reached by the other rows. The implemented objective did not change from the original 300 s/window cap 90 MPC run.

## Recommendation

Keep 60 MW as the main-case export cap and include this as a sensitivity analysis. No main-cap change is supported by the evidence: 60 MW is nonbinding relative to the observed 39.867 MW maximum export, while lower caps demonstrate the expected degradation under tighter export constraints.
