# LP Relaxation Anatomy Audit, Tightened 24h UC

This is a read-only audit. It builds the existing tightened UC model in memory, relaxes integer and binary variables, and does not write normal experiment artifacts.

## Root LP

| status | termination | runtime_s | objective | distance from 900s incumbent | relaxed binaries |
| --- | --- | --- | --- | --- | --- |
| ok | optimal | 0.459775 | 29160.059962 | 72656.021090 | 1560 |

900-second incumbent: `-43495.961128`. 900-second best bound: `-625.045785`.

Retained tightened MIP results used for comparison:

| time limit | termination | incumbent | best bound | absolute distance | gap % |
| --- | --- | --- | --- | --- | --- |
| 60 | maxTimeLimit | -45720.881809 | 5833.859036 | 51554.740845 | 112.759726 |
| 300 | maxTimeLimit | -44520.002067 | 4229.177585 | 48749.179653 | 109.499500 |
| 900 | maxTimeLimit | -43495.961128 | -625.045785 | 42870.915343 | 98.562980 |

## Fractional Discrete Families

| family | count | fractional @1e-6 | min | max | sum frac dist | mean frac dist | most fractional |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CHP off selector y_off (on=1-y_off) | 24 | 0 | -0.000000 | -0.000000 | 0.000000 | 0.000000 | present |
| CHP startup start | 24 | 0 | 0.000000 | 1.000000 | 0.000000 | 0.000000 | present |
| CHP shutdown stop | 24 | 0 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | present |
| CHP operating temperature modes y | 144 | 80 | -0.000000 | 0.662146 | 21.333808 | 0.148151 | y[7,125C]=0.473409 at 2023-12-04 06:00:00; y[10,120C]=0.531836 at 2023-12-04 09:00:00; y[15,120C]=0.541516 at 2023-12-04 14:00:00 |
| CHP heat segment selectors zH | 888 | 86 | 0.000000 | 0.662146 | 21.333808 | 0.024025 | zH[10,120C,4]=0.531836 at 2023-12-04 09:00:00; zH[15,120C,4]=0.541516 at 2023-12-04 14:00:00; zH[8,125C,2]=0.458348 at 2023-12-04 07:00:00 |
| CHP power segment selectors zE | 432 | 82 | 0.000000 | 0.662146 | 21.333808 | 0.049384 | zE[7,125C,1]=0.473409 at 2023-12-04 06:00:00; zE[10,120C,1]=0.531836 at 2023-12-04 09:00:00; zE[15,120C,1]=0.541516 at 2023-12-04 14:00:00 |
| Grid import/export direction | 0 | 0 | n/a | n/a | 0.000000 | n/a | absent: current model has no grid-direction binary variable |
| Storage charge direction u_ch | 24 | 7 | 0.000000 | 0.252100 | 1.764699 | 0.073529 | u_ch[1]=0.252100 at 2023-12-04 00:00:00; u_ch[2]=0.252100 at 2023-12-04 01:00:00; u_ch[3]=0.252100 at 2023-12-04 02:00:00 |

## LP-Only Nonphysical Behavior

| metric | value |
| --- | --- |
| simultaneous import/export hours | 0 |
| simultaneous import/export total MWh | 0.000000 |
| simultaneous import/export max MW | 0.000000 |
| simultaneous charge/discharge hours | 0 |
| simultaneous charge/discharge total MWh | 0.000000 |
| simultaneous charge/discharge max MW | 0.000000 |
| fractional commitment hours | 0 |
| mixed temperature-mode hours | 24 |
| max positive temperature modes in one hour | 4 |
| mixed heat-segment hours | 24 |
| max positive heat segments in one hour | 4 |
| mixed power-segment hours | 24 |
| max positive power segments in one hour | 4 |
| CHP curtailment total MWh | 0.000000 |
| CHP curtailment while fractionally offline MWh | 0 |
| PV curtailment total MWh | 0.000000 |
| dump total MWh | 0.000000 |
| undersupply total MWh | 0.000000 |

Top simultaneous import/export rows:

| t | timestamp | import | export | overlap |
| --- | --- | --- | --- | --- |
| none |  |  |  |  |

Top simultaneous charge/discharge rows:

| t | timestamp | charge | discharge | overlap |
| --- | --- | --- | --- | --- |
| none |  |  |  |  |

## Group-Fixing LPs

| case | description | status | runtime_s | LP objective | reduction from root | distance from 900s incumbent | fixed vars | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | CHP commitment/startup/shutdown fixed | ok/optimal | 0.468553 | 29160.059962 | -0.000000 | 72656.021090 | 72 |  |
| B | CHP heat/power segment selectors fixed | ok/optimal | 1.243512 | -43495.370303 | 72655.430265 | 0.590825 | 1320 |  |
| C | Grid direction fixed | not_applicable_absent/not_solved | 0.000000 | 29160.059962 | 0.000000 | 72656.021090 | 0 | No grid-direction binary variable is present in the model or stored dispatch artifacts. |
| D | Storage charge/discharge direction fixed where dispatch is nonzero | ok/optimal | 0.774262 | 29158.940405 | 1.119557 | 72654.901533 | 22 | t=16: storage direction ambiguous because ch=dis=0; t=18: storage direction ambiguous because ch=dis=0 |
| E | All CHP discrete variables fixed | ok/optimal | 1.229095 | -43495.370303 | 72655.430265 | 0.590825 | 1536 |  |
| F | All reproducible discrete variables fixed | ok/optimal | 1.153270 | -43495.370303 | 72655.430265 | 0.590825 | 1558 | t=16: storage direction ambiguous because ch=dis=0; t=18: storage direction ambiguous because ch=dis=0 |

Case C was not solved as a distinct fixing LP because the model has no grid-direction binary variable and the retained dispatch artifact has no such field.

Case B fixes only `zH` and `zE`; in this retained 900-second schedule every hour is ON, so the existing `heat_select`, `power_select`, and `one_mode` equations make those segment fixes also imply the corresponding temperature-mode and commitment state.

## Remaining Big-M and Binary-Linked Weaknesses

| rank | file/line | constraint | M or formula | scale | assessment | important |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:480-490 | h_eq_ub/lb | M_eq_H = H_max + 50 = 236.154500 | H_max=186.154500, Q_max=485.779815 | loose for inactive heat segment equations because a global additive M relaxes every unselected segment. | yes |
| 2 | src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:518-528 | e_eq_ub/lb | M_eq_E = E_max + 50 = 165.740079 | E_max=115.740079, Q_max=485.779815 | loose for inactive power segment equations and directly tied to the weak segment relaxation. | yes |
| 3 | src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:468-478 | h_lb_con/h_ub_con/qh_lb_con/qh_ub_con | M_H=H_max=186.154500; M_Q=Q_max=485.779815 | segment H ub range up to 186.154500; segment Q ub range up to 485.779815 | global M values are safe but not segment-specific; aggregate tightening helps but does not eliminate fractional mixing. | yes |
| 4 | src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:506-516 | e_lb_con/e_ub_con/qe_lb_con/qe_ub_con | M_E=E_max=115.740079; M_Q=Q_max=485.779815 | segment E ub range up to 115.740079; segment Q ub range up to 485.779815 | global M values are safe but not segment-specific; fractional zE values remain consequential. | yes |
| 5 | src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:447-449 | off_H/off_E/off_Q | H_max=186.154500; E_max=115.740079; Q_max=485.779815 | full CHP capacity | capacity-tight for integer off/on, but permits proportional output under fractional commitment. | yes |
| 6 | src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:544-545 | storage ch_mode/dis_mode | P_ch_max=200.000000; P_dis_max=200.000000 | storage power limits | exact for the binary disjunction; its LP relaxation is the convex hull and still permits simultaneous partial charge/discharge. | moderate |
| 7 | src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:568-570 | chp_curt_on_ub/chp_curt_seg_ub | E_max=115.740079; sum(e_ub*zE) | available CHP electric output | recently tightened; remains tied to fractional zE but no longer has a free global curtailment bound alone. | moderate |
| 8 | src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:432-435,580 | grid_import upper bound and delivery ub | grid_import <= e_load[t] + export_cap; here e_load=20.000000, export_cap=60.000000 | electric load plus export cap | finite and physically derived; no grid direction binary exists. | low to moderate |

## Recommendation

Best-supported next formulation change: **Replace CHP segment big-M equations/bounds with an extended convex-hull or perspective formulation for each selected heat/power segment, preserving the same segment data and integer choices.**

| rank | candidate | integer set preserved | expected LP benefit | complexity | semantic risk |
| --- | --- | --- | --- | --- | --- |
| 1 | Replace CHP segment big-M equations/bounds with an extended convex-hull or perspective formulation for each selected heat/power segment, preserving the same segment data and integer choices. | yes if each existing binary segment choice maps one-to-one to its lifted copy variables and the original H/E/Q are linked as sums of lifted variables. | highest: targets the families with the most fractional selectors and the largest remaining big-M values. | high | medium: indexing and heat/power coupling must be audited carefully, but no objective or physical parameter change is needed. |
| 2 | Add redundant transition equality start[t] - stop[t] == on[t] - on[t-1] with the existing t=0 initial-state analogue. | yes; the existing binary inequalities already imply the equality for all integer schedules. | moderate if fractional start/stop remains active; low implementation cost. | low | low |
| 3 | Introduce explicit grid import/export direction exclusivity. | no for the current mathematical feasible set, although it may match intended physics. | depends on observed simultaneous import/export in the root LP. | medium | medium because it is a physical/modeling change, not a redundant tightening. |
| 4 | Further storage charge/discharge exclusivity strengthening. | not with simple linear cuts beyond ch/P_ch + dis/P_dis <= 1, which is already implied by the existing u_ch formulation. | limited unless a new nonredundant modeling assumption is introduced. | medium | medium to high for any additional restriction. |

Proof outline for the top recommendation: For binary z, the lifted variables for inactive segments are forced to zero; for the active segment they equal the original H/E/Q and satisfy the same affine segment equations and segment bounds. Projecting the lifted formulation onto H/E/Q/z gives exactly the current integer-feasible segment disjunction.

No new formulation was implemented in this audit.
