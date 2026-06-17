# Objective and Formulation Audit for 24-hour UC Solver Budget Runs

Date: 2026-06-17

Scope: read-only audit of the three existing 24-hour UC budget runs:

- `resub_2026_budget_uc_anchor24h_gap0p002_t60`
- `resub_2026_budget_uc_anchor24h_gap0p002_t300`
- `resub_2026_budget_uc_anchor24h_gap0p002_t900`

No 60/300/900-second MIPs were rerun. No production Python, existing YAML, existing result artifact, report, frozen output, or model equation was modified. An audit-only helper script was added at `tools/resubmission_2026/objective_formulation_audit.py`.

## Objective Expression

The UC model is built in `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py`. The objective starts at line 517 and has `sense=pyo.maximize` at line 532:

```text
maximize sum_t [
  price_sell * grid_export[t]
  - price_buy * grid_import[t]
  - cost_q * Q[t]
  - cost_boiler * boiler[t]
  - cost_dump * dump[t]
  - penalty_under * under[t]
  - cycle_cost * (ch[t] + dis[t])
  - penalty_pv_curt * pv_curt[t]
  - penalty_chp_curt * chp_curt[t]
  - startup_cost * start[t]
  - shutdown_cost * stop[t]
]
```

Line references:

- Export revenue: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:519`
- Import cost: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:520`
- CHP fuel/steam input cost: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:521`
- Boiler fuel cost: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:522`
- Dump penalty: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:523`
- Unserved heat penalty: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:524`
- Storage cycling cost: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:525`
- PV curtailment penalty: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:526`
- CHP curtailment penalty: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:527`
- Startup and shutdown costs: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:528` and `:529`
- Objective sense: `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:532`

The 24-hour budget configs use hourly time steps, so summing MW over rows gives MWh-equivalent totals. The objective has no additive constant term. It is a profit-like objective: revenue is positive, costs and penalties are negative. The summary reports both signs: `objective_profit_like` and `objective_system_cost_equivalent = -objective_profit_like`; this sign convention is also documented in the economics recomputation function at `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:130` through `:135`.

Common coefficients from the generated config:

| Term | Value | Unit interpretation |
|---|---:|---|
| `price_sell` | 50.0 | revenue per MWh exported |
| `price_buy` | 70.0 | cost per MWh imported |
| `cost_q` | 15.0 | cost per MWh thermal input `Q` |
| `cost_boiler` | 60.0 | cost per MWh boiler heat |
| `cost_dump` | 50.0 | penalty per MWh dumped heat |
| `penalty_under` | 1000000.0 | penalty per MWh unmet heat |
| `cycle_cost` | 0.01 | cost per MWh charge plus discharge |
| `penalty_pv_curt` | 0.1 | penalty per MWh PV curtailment |
| `penalty_chp_curt` | 0.0 | penalty per MWh CHP curtailment |
| `startup_cost` | 5000.0 | cost per start |
| `shutdown_cost` | 0.0 | cost per stop |

## Objective Reconstruction

The audit helper independently recomputed each component from the dispatch parquet files using the objective expression above. It did not call `compute_realized_economics` for the component values.

| Limit s | Export revenue | Import cost | CHP cost | Boiler cost | Dump penalty | Storage cycling | Startup | Reconstructed profit | Summary profit | Residual |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 60 | 24325.474302 | 5089.231431 | 61853.276003 | 18588.004879 | 66.057321 | 10.583863 | 5000.000000 | -66281.679194 | -66281.679194 | 0.000000e+00 |
| 300 | 29749.517196 | 543.804335 | 72704.761041 | 0.000000 | 0.000000 | 12.571347 | 5000.000000 | -48511.619527 | -48511.619527 | 2.182787e-11 |
| 900 | 29958.861058 | 218.584423 | 71088.097393 | 21.153859 | 0.000000 | 9.371106 | 5000.000000 | -46378.345723 | -46378.345723 | 7.275958e-12 |

All three runs had zero under-heat penalty, zero PV curtailment penalty, zero CHP curtailment penalty, and zero shutdown cost. The residuals are floating-point roundoff only. The summary economics fields agree with the independent reconstruction.

## Why Negative Incumbents and Positive Bounds Can Coexist

The objective is maximized profit-like net value. A feasible integer dispatch can have negative profit when fuel, import, startup, and penalty costs exceed export revenue. The solver's best bound for a maximization problem is an upper bound on the best possible profit, and it can be positive even when the best integer incumbent found so far is negative.

This does not imply a sign-swapping defect. The stored diagnostics use `diagnostic_source = highspy_info`; explicit fields and legacy aliases agree:

- `incumbent_objective == best_feasible_objective`
- `best_bound_objective == best_objective_bound`
- `achieved_gap_rel_fraction == achieved_gap_rel`

The relative gap can increase even when the absolute incumbent-bound distance decreases because HiGHS reports a relative gap scaled by the incumbent magnitude. Here:

| Limit s | Incumbent | Best bound | Absolute difference | Relative gap |
|---:|---:|---:|---:|---:|
| 60 | -66281.679194 | 48595.486142 | 114877.165336 | 1.733166 |
| 300 | -48511.619527 | 40134.574775 | 88646.194302 | 1.827319 |
| 900 | -46378.345723 | 34823.549223 | 81201.894946 | 1.750858 |

From 60 to 300 seconds, the absolute distance decreased by 26230.971034, or 22.833930%, but the incumbent magnitude also decreased from 66281.679194 to 48511.619527. The denominator shrank enough that the relative gap increased.

## Objective Conditioning Options

| Change | Dispatch optimum | Solver stopping behavior | Reporting interpretation |
|---|---|---|---|
| Multiply objective by `-1` and switch from maximize to minimize | No change if every coefficient is exactly negated and sense is switched | Relative gap remains essentially the same without constants; signs in logs change | Incumbent becomes positive cost, bound becomes a lower bound on cost |
| Reformulate as minimization of net operating cost | No change if it is exactly `-profit_objective` | No material stopping improvement expected by itself | Easier paper language if results are discussed as costs |
| Add or remove variable-independent constants | No dispatch change | Can change displayed relative gap and gap-based stopping because the denominator shifts while the absolute incumbent-bound difference does not | Reporting-only if not used by solver; dangerous if used to make the displayed relative gap look better |
| Report absolute gap | No dispatch change | No change unless the solver is configured to stop on an absolute gap | Useful diagnostic when incumbent and bound have opposite signs |

Recommendation: do not add artificial constants or objective shifts solely to reduce the displayed relative gap. If reporting is improved, report both relative and absolute gaps.

## LP Relaxation

Command:

```powershell
C:\Users\li\anaconda3\envs\chp_tes_pv_dispatch\python.exe tools\resubmission_2026\objective_formulation_audit.py --lp-time-limit-s 120
```

The helper built the same 24-hour UC model from the `t900` config, relaxed integer and binary variables only, and solved in memory with no experiment artifact writes.

| Metric | Value |
|---|---:|
| LP status / termination | ok / optimal |
| LP wallclock s | 0.356058 |
| Relaxed binaries | 1560 |
| Relaxed general integers | 0 |
| Model variables | 1873 |
| Model constraints | 8758 |
| LP objective | 68543.430362 |
| 900-second incumbent | -46378.345723 |
| 900-second B&B best bound | 34823.549223 |
| LP objective minus 900 incumbent | 114921.776085 |
| LP objective minus 900 best bound | 33719.881139 |

The root LP relaxation is much weaker than the 900-second B&B bound, which means HiGHS cuts and search improved the bound substantially. The remaining large gap is therefore not just a reporting artifact; formulation strength and solver search both matter.

## Formulation Strength Audit

Segment constants from the same model input:

| Constant | Value |
|---|---:|
| `H_max`, `M_H` | 186.154500 |
| `E_max`, `M_E` | 115.740079 |
| `Q_max`, `M_Q` | 485.779815 |
| `M_eq_H` | 236.154500 |
| `M_eq_E` | 165.740079 |
| Heat segments after filtering | 37 |
| Power segments after filtering | 18 |
| Temperature modes | 6 |

### Findings

| Area | File and line | Current formulation | Status | Why it may weaken relaxation | Safe strengthening option | Feasible-set risk |
|---|---|---|---|---|---|---|
| Big-M segment bounds | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:320` to `:324`, `:431` to `:479` | Global `M_H`, `M_E`, `M_Q`, `M_eq_H`, `M_eq_E` deactivate all segment bound/equality constraints. | Confirmed | Fractional `zH`/`zE` can partially relax many inactive segment constraints at once. Global M values are valid but loose. | Replace or supplement with disaggregated bounds such as `H <= sum h_ub[z] * zH`, `H >= sum h_lb[z] * zH`, and analogous `Q`/`E` bounds. Consider per-segment tight M values for equality rows. | Low if bounds are derived directly from segment data; medium for equality M values unless carefully proven. |
| Separate heat and power segment choices | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:419` to `:427`, `:431` to `:479` | Heat segment binaries `zH` and power segment binaries `zE` are selected separately under the same temperature mode, linked only through common `Q`. | Confirmed | LP relaxation can mix heat and power segment convex combinations that do not represent a tight joint CHP feasible region in `(H,E,Q)`. | Build a joint heat-power segment formulation over compatible segment pairs, or introduce disaggregated segment flow variables with a convex-hull perspective formulation. | Medium to high; must verify the intended physical feasible region before replacing the formulation. |
| On/off and output linking | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:342` to `:350`, `:409` to `:416` | `on = 1 - y_off`; output limits use global `H/E/Q <= max * on`; detailed segment bounds are big-M rows. | Confirmed | Fractional `on` can still support fractional output and fractional startup cost. Big-M segment rows then allow additional relaxation freedom. | Add perspective-style aggregate inequalities using selected segment bounds: `H <= sum h_ub*zH`, `Q <= sum qh_ub*zH`, `E <= sum e_ub*zE`, plus lower-bound analogs where valid. | Low if inequalities are implied by active segment definitions. |
| Startup/shutdown logic | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:356` to `:375` | Standard transition inequalities define `start` and `stop` from `on[t] - on[t-1]`, with `start + stop <= 1`. | Confirmed | Correct for integer logic, but LP relaxation allows fractional starts/stops and fractional startup cost. | Keep current logic for correctness. Potentially add known initial run-length constraints if such data exists. | Low for valid initial-history constraints; otherwise can change assumptions. |
| Minimum up/down constraints | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:377` to `:389` | Disaggregated min-up/min-down rows enforce future status only while `k + tau < N`. | Confirmed | Starts near the end of the horizon are not forced to satisfy a full post-horizon run. This is common but weakens finite-horizon commitment. | Add terminal commitment carry-over constraints or terminal penalties when a post-horizon state is meaningful. | Medium; it changes boundary assumptions unless downstream commitment state is modeled. |
| Grid import/export exclusivity | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:403` to `:404`, `:509` to `:513` | Import is nonnegative and unbounded above; export is bounded by the export cap. No import/export binary exclusivity is present. | Confirmed | With `price_buy > price_sell`, simultaneous import/export is economically dominated and validation shows near-zero overlap, but explicit import bounds are still loose. | Add safe upper bound `grid_import[t] <= e_load[t] + grid_export_cap_mw`; avoid adding a new exclusivity binary unless simultaneous flow appears in optimal solutions. | Low for the import upper bound; high for a new binary because it adds complexity and may slow solves. |
| Storage charge/discharge exclusivity | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:392` to `:395`, `:482` to `:484` | Binary `u_ch` enforces charge or discharge mode. | Confirmed | The LP relaxation allows fractional mode. However, the projected relaxation over `(ch, dis)` is already the convex hull `ch/P_ch + dis/P_dis <= 1`. | No obvious linear strengthening for this substructure without adding physics-specific cuts. Keep as is unless simultaneous charge/discharge appears in integer results. | Low to keep; uncertain for extra cuts. |
| Export cap | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:404` | `grid_export` has bound `(0, grid_export_cap_mw)`. | Confirmed strong | This is already a direct variable bound and validation passed. | No change recommended. | None. |
| Segment variable count | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:284` to `:285`, `:342` to `:345` | Per hour: 6 temperature binaries, 1 off binary, 37 heat-segment binaries, 18 power-segment binaries. | Confirmed | The 24-hour model has 1560 binaries; many are segment-selection binaries with weak big-M relaxations. | Prefer convex-hull or SOS2-like segment formulations if the piecewise functions are ordered and compatible. | Medium; requires validation against current segment semantics. |
| Loose continuous variable bounds | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:398` to `:406` | `boiler`, `dump`, `under`, `grid_import`, `pv_curt`, and `chp_curt` are declared without explicit upper bounds, though some later constraints imply bounds. | Confirmed | Missing upper bounds can enlarge presolved rows and weaken LP/cut generation. | Add implied bounds where exact: `pv_curt <= pv_av` already exists at `:503`; `chp_curt <= E_max`; `grid_import <= e_load + export_cap`. Be cautious with `boiler`, `dump`, and `under`, whose finite bounds may be dominance-based rather than strictly implied. | Low for exact implied bounds; medium for dominance-based caps. |
| Heat under/dump/boiler slack interaction | `src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:397` to `:400`, `:497` to `:500` | Boiler, dump, and under are all nonnegative and tied through heat balance. | Suspected performance issue | Positive boiler and dump can offset each other in the feasible region, although costs make large simultaneous values unattractive in optimal solutions. | If needed, add dominance-based caps or complementarity-inspired valid inequalities after proving they do not cut off economically relevant optima. | Medium; can remove feasible but dominated points, so treat as performance-only. |

## Ranked Next Steps

Correctness fixes:

1. No objective sign or diagnostic sign correctness defect was found in these outputs.
2. No physical validation failure was found.
3. If production documentation says the UC objective is "cost minimization", update wording to state either profit maximization or system cost equivalent. This is reporting/documentation, not a model equation fix.

Formulation-performance improvements:

1. Add implied segment aggregate bounds (`H`, `E`, `Q` against selected segment lower/upper bounds). This is the safest likely strengthening.
2. Add exact upper bounds for `grid_import` and `chp_curt`; keep existing `pv_curt <= pv_av`.
3. Investigate a joint heat-power CHP convex-hull formulation. This has the largest potential impact but also the largest validation burden.
4. Revisit finite-horizon terminal commitment assumptions for min-up/min-down if end effects are material.

Solver-option tuning:

1. Try HiGHS cut, heuristic, and MIP emphasis options only after the safer bound-tightening experiments, so performance changes can be attributed cleanly.
2. Consider a modest longer 24-hour run only after testing formulation tightening, because the LP relaxation evidence points to structural weakness.

Reporting-only improvements:

1. Report absolute gap alongside relative gap whenever incumbent and bound have opposite signs.
2. Keep reporting `requested_gap_rel_fraction` and `requested_gap_percent`.
3. Do not shift the objective by constants to make the displayed relative gap smaller.

Evidence-based recommendation: investigate formulation strength first, especially segment big-M and missing implied bounds, before moving to a 168-hour run.
