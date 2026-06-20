# TES-Capacity Sensitivity Audit, 168 h Winsorized Main Case

## Scope

This audit uses the committed winsorized full-week scenario:

`data/scenarios/week_2023_dec01_winsor_p99_fw`

The 1.0x row uses the committed final-main artifacts and was not rerun. New UC/MPC runs were created only for 0.5x and 1.5x TES capacity with the convex-hull CHP segment formulation, `mip_rel_gap: 0.002`, deterministic single-thread HiGHS settings, and the final-main terminal-SOC policies. The 0.5x MPC row uses a follow-up 1200 s/window polishing rerun because the original 300 s/window run left one window above the requested 0.2% MIP tolerance.

## Schema Finding

TES energy capacity is configurable through YAML as `storage.s_max_mwh`. The final-main baseline is `800.0 MWh`, so the sensitivity levels are:

- 0.5x: `400.0 MWh`
- 1.0x: `800.0 MWh`
- 1.5x: `1200.0 MWh`

The field is defined in `src/chp_pv_sim/experiments/config.py`, passed through the experiment engine to model construction, and used in the model as the upper bound on the storage state variable `S`.

The solver settings `threads=1`, `parallel=off`, `random_seed=1`, and `presolve=on` are applied by the experiment engine for these runs.

## Preflight Summary

All four original sensitivity configs validated before solving. Planned artifacts were the newly tagged summary JSON, solver-window CSV, validation JSON, and dispatch Parquet files for each new tag. No planned artifact existed before the runs, and no final-main, exportcap, outlier, pilot, frozen, report, or manuscript path was planned for writing.

The 0.5x MPC polishing config, `resub_2026_tescap_0p5_hull_mpc_168h_gap0p002_t1200`, was validated separately. Its planned artifacts did not exist before the rerun and are distinct from the original 0.5x MPC 300 s/window artifacts.

Compared with the corresponding final-main UC/MPC configs, the only intentional effective differences were:

- `run.tag`
- `storage.s_max_mwh`
- output paths induced by the new tags

## Solver Diagnostics

| TES | method | win | status | termination | runtime_s | incumbent | best bound | abs dist | gap % | req % | formulation | diagnostic |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 0.5x | UC | 1 | ok | optimal | 799.150 | -262747.510921 | -262488.123294 | 259.387626 | 0.098721 | 0.200 | convex_hull | highspy_info |
| 0.5x | MPC | 1 | ok | optimal | 567.567 | -73242.307474 | -73096.480915 | 145.826559 | 0.199102 | 0.200 | convex_hull | highspy_info |
| 0.5x | MPC | 2 | ok | optimal | 100.403 | -73252.460366 | -73106.317408 | 146.142958 | 0.199506 | 0.200 | convex_hull | highspy_info |
| 0.5x | MPC | 3 | ok | optimal | 59.670 | -74847.933558 | -74802.541644 | 45.391914 | 0.060646 | 0.200 | convex_hull | highspy_info |
| 0.5x | MPC | 4 | ok | optimal | 14.777 | -74709.335413 | -74566.596474 | 142.738939 | 0.191059 | 0.200 | convex_hull | highspy_info |
| 0.5x | MPC | 5 | ok | optimal | 20.794 | -74677.151782 | -74603.148310 | 74.003472 | 0.099098 | 0.200 | convex_hull | highspy_info |
| 0.5x | MPC | 6 | ok | optimal | 19.727 | -76366.814709 | -76270.088821 | 96.725888 | 0.126660 | 0.200 | convex_hull | highspy_info |
| 0.5x | MPC | 7 | ok | optimal | 7.802 | -38414.714943 | -38343.509893 | 71.205050 | 0.185359 | 0.200 | convex_hull | highspy_info |
| 1.0x | UC | 1 | ok | optimal | 275.168 | -258690.055995 | -258666.550792 | 23.505204 | 0.009086 | 0.200 | convex_hull | highspy_info |
| 1.0x | MPC | 1 | ok | optimal | 118.204 | -71362.397490 | -71295.521438 | 66.876052 | 0.093713 | 0.200 | convex_hull | highspy_info |
| 1.0x | MPC | 2 | ok | optimal | 192.311 | -73415.613243 | -73268.879361 | 146.733882 | 0.199867 | 0.200 | convex_hull | highspy_info |
| 1.0x | MPC | 3 | ok | optimal | 57.986 | -76388.405893 | -76238.465446 | 149.940447 | 0.196287 | 0.200 | convex_hull | highspy_info |
| 1.0x | MPC | 4 | ok | optimal | 52.483 | -74911.841231 | -74762.131906 | 149.709325 | 0.199847 | 0.200 | convex_hull | highspy_info |
| 1.0x | MPC | 5 | ok | optimal | 21.352 | -74736.415568 | -74735.191795 | 1.223772 | 0.001637 | 0.200 | convex_hull | highspy_info |
| 1.0x | MPC | 6 | ok | optimal | 24.716 | -75005.763202 | -75005.705541 | 0.057661 | 0.000077 | 0.200 | convex_hull | highspy_info |
| 1.0x | MPC | 7 | ok | optimal | 11.176 | -37816.608456 | -37816.376572 | 0.231884 | 0.000613 | 0.200 | convex_hull | highspy_info |
| 1.5x | UC | 1 | ok | optimal | 372.341 | -258265.149960 | -258091.606414 | 173.543546 | 0.067196 | 0.200 | convex_hull | highspy_info |
| 1.5x | MPC | 1 | ok | optimal | 95.102 | -71403.055379 | -71321.828947 | 81.226432 | 0.113758 | 0.200 | convex_hull | highspy_info |
| 1.5x | MPC | 2 | ok | optimal | 18.868 | -69355.614775 | -69355.614775 | 0.000000 | 0.000000 | 0.200 | convex_hull | highspy_info |
| 1.5x | MPC | 3 | ok | optimal | 49.950 | -74954.252448 | -74804.429766 | 149.822682 | 0.199885 | 0.200 | convex_hull | highspy_info |
| 1.5x | MPC | 4 | ok | optimal | 50.202 | -74836.538849 | -74695.437115 | 141.101734 | 0.188547 | 0.200 | convex_hull | highspy_info |
| 1.5x | MPC | 5 | ok | optimal | 32.948 | -74803.901059 | -74802.726513 | 1.174546 | 0.001570 | 0.200 | convex_hull | highspy_info |
| 1.5x | MPC | 6 | ok | optimal | 29.988 | -73614.746458 | -73614.195338 | 0.551119 | 0.000749 | 0.200 | convex_hull | highspy_info |
| 1.5x | MPC | 7 | ok | optimal | 13.594 | -37283.521677 | -37282.932976 | 0.588701 | 0.001579 | 0.200 | convex_hull | highspy_info |

The 0.5x MPC diagnostics shown above are from the 1200 s/window polishing rerun. Every 0.5x MPC window reached the requested 0.2% tolerance; the maximum window gap is 0.199506%.

## Objective Decomposition

The objective was independently reconstructed from dispatch columns and config economics. Reconstruction residuals against saved summary objectives are roundoff only.

| TES | method | objective | export rev | import cost | CHP cost | boiler cost | startup | storage | penalties | residual |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5x | UC | -262747.510921 | 141194.52 | 23796.11 | 375091.97 | 0.00 | 5000.00 | 53.95 | 0.00e+00 | 5.821e-11 |
| 0.5x | MPC | -262737.982668 | 141245.66 | 23323.36 | 375606.64 | 0.00 | 5000.00 | 53.64 | -1.78e-13 | 0.000e+00 |
| 1.0x | UC | -258690.055995 | 127386.28 | 12528.33 | 368491.61 | 0.00 | 5000.00 | 56.40 | 0.00e+00 | 5.821e-11 |
| 1.0x | MPC | -262214.245647 | 128154.57 | 11643.44 | 373668.83 | 0.00 | 5000.00 | 56.55 | 4.22e-13 | 5.821e-11 |
| 1.5x | UC | -258265.149960 | 113811.29 | 307.30 | 366705.30 | 0.00 | 5000.00 | 63.84 | 2.66e-13 | 2.910e-11 |
| 1.5x | MPC | -258364.387808 | 117736.58 | 2800.00 | 368241.83 | 0.00 | 5000.00 | 59.14 | 0.00e+00 | 0.000e+00 |

## Sensitivity Table

| TES level | TES MWh | UC objective | MPC implemented objective | UC - MPC | UC advantage % of abs(UC) | SOC min-max UC/MPC | throughput MWh UC/MPC | cycling cost UC/MPC | export revenue UC/MPC | CHP cost UC/MPC | both reached requested gap? | validation | UC runtime_s | MPC total runtime_s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|
| 0.5x | 400 | -262747.510921 | -262737.982668 | -9.528252 | -0.004 | -0.0-400.0/0.0-400.0 | 5395.1/5364.3 | 53.95/53.64 | 141194.52/141245.66 | 375091.97/375606.64 | yes | pass | 799.150 | 790.739 |
| 1.0x | 800 | -258690.055995 | -262214.245647 | 3524.189651 | 1.362 | 0.0-800.0/146.6-800.0 | 5639.9/5654.9 | 56.40/56.55 | 127386.28/128154.57 | 368491.61/373668.83 | yes | pass | 275.168 | 478.227 |
| 1.5x | 1200 | -258265.149960 | -258364.387808 | 99.237848 | 0.038 | 0.0-1200.0/154.8-1150.7 | 6384.4/5914.1 | 63.84/59.14 | 113811.29/117736.58 | 366705.30/368241.83 | yes | pass | 372.341 | 290.652 |

## Physical Validation

| TES | method | pass | heat resid | elec resid | overlap | export max/cap | SOC min/max | init/final/gap | SOC at cap hrs | SOC at zero hrs | PV curt | CHP curt | dump | under |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5x | UC | true | 3.553e-15 | 6.040e-14 | 9.431e-14 | 42.095/60 | -0.000/400.000 | 200.000/200.000/0.000e+00 | 7 | 7 | 0.000 | 0.000 | 0.000e+00 | 0.000e+00 |
| 0.5x | MPC | true | 7.105e-14 | 1.137e-13 | 4.459e-14 | 42.095/60 | 0.000/400.000 | 200.000/200.000/0.000e+00 | 7 | 7 | 0.000 | 0.000 | -3.553e-15 | 0.000e+00 |
| 1.0x | UC | true | 2.842e-14 | 2.842e-14 | 2.370e-09 | 39.867/60 | 0.000/800.000 | 200.000/200.000/0.000e+00 | 2 | 5 | 0.000 | 0.000 | 0.000e+00 | 0.000e+00 |
| 1.0x | MPC | true | 1.421e-14 | 2.135e-09 | 2.383e-12 | 39.867/60 | 146.613/800.000 | 200.000/200.000/0.000e+00 | 4 | 0 | 0.000 | 0.000 | 8.438e-15 | 0.000e+00 |
| 1.5x | UC | true | 2.842e-14 | 7.105e-15 | 2.842e-14 | 39.867/60 | 0.000/1200.000 | 200.000/200.000/0.000e+00 | 2 | 3 | 0.000 | 0.000 | 5.329e-15 | 0.000e+00 |
| 1.5x | MPC | true | 1.421e-14 | 1.918e-12 | 9.292e-14 | 39.867/60 | 154.849/1150.655 | 200.000/200.000/0.000e+00 | 0 | 0 | 0.000 | 0.000 | 0.000e+00 | 0.000e+00 |

Standalone `validate_dispatch` also passed for every new TES-capacity dispatch.

## MPC Stitching

| TES | records | unique timestamps | missing/duplicate | max SOC boundary gap | commitment transition violations | min up/down violations |
|---|---:|---:|---|---:|---:|---:|
| 0.5x | 168 | 168 | no | 0.000e+00 | 0 | 0 |
| 1.0x | 168 | 168 | no | 0.000e+00 | 0 | 0 |
| 1.5x | 168 | 168 | no | 0.000e+00 | 0 | 0 |

## Interpretation

Larger TES improves the observed objective for both methods. UC improves strongly from 0.5x to 1.0x and modestly from 1.0x to 1.5x. MPC improves from 0.5x to 1.0x and further at 1.5x.

UC has the better implemented objective at the 1.0x baseline and at 1.5x. At 0.5x, the polished MPC result is slightly better than UC by 9.528 objective units, which is effectively a near tie relative to the roughly 263k objective scale. At 1.5x, the observed UC advantage is only 99.238 objective units, so it should not be overinterpreted as a large performance difference.

TES capacity is binding in the observed schedules. The 0.5x case reaches both zero and the 400 MWh upper bound. The 1.0x baseline reaches the 800 MWh upper bound in both UC and MPC, and UC also reaches zero. The 1.5x UC schedule reaches 1200 MWh while the 1.5x MPC schedule reaches 1150.655 MWh, so additional storage is still used, especially by UC.

The baseline 800 MWh capacity is reasonable as a central case: it is physically active and binding, lower capacity materially worsens objectives, and higher capacity produces incremental benefit without changing the qualitative picture from the baseline. It should be presented as a chosen scenario parameter, not as an optimized design size.

## Recommendation

Include TES capacity as a sensitivity result. Do not change the baseline TES capacity based on this audit alone. The sensitivity supports the statement that storage capacity materially affects both methods, while the UC-vs-MPC ranking is strong in the baseline case but not uniform across every TES-capacity perturbation.
