# Kazakhstan CHPP Parameters QC Report

- Generated (UTC): 2026-02-24T06:16:25.460654+00:00

## Shared turbine segments

### Heat segments (H = k_HQ * Q + b_HQ)
- rows: 37
- temp labels: 100C, 110C, 120C, 125C, 75C, 90C
- max_abs_err (|H_calc - H_bound|): 1.3086 (tol=0.001)
- n_err_gt_tol: 14
- max_abs_gap (to next segment): 0 (tol=1e-06)
- n_gap_gt_tol: 0

### Power segments (E = k_EH * Q + b_EH)
- rows: 22
- temp labels: 100C, 110C, 120C, 125C, 75C, 90C, KOND
- max_abs_err (|E_calc - E_bound|): 48.0385 (tol=0.001)
- n_err_gt_tol: 11
- max_abs_gap (to next segment): 137.931 (tol=1e-06)
- n_gap_gt_tol: 2

## Unit efficiency tables

- case1: {'chp_eff_rows': 12, 'boiler_rows': 8, 't_params_rows': 2, 'rhom_rows': 12}
- case2: {'chp_eff_rows': 12, 'boiler_rows': 8, 't_params_rows': 2, 'rhom_rows': 12}

## Notes on units
- Sheet name 'Turbine(MW)' indicates E/H segment values are in MW-scale. In hourly simulation (Δt=1h), MW and MWh/h are numerically equivalent.
- Q is labeled as inlet steam energy; we keep it in dataset units and do not convert at this stage.
