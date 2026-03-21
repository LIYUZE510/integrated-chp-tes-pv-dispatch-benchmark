# Kazakhstan CHPP Turbine Segment Consistency QC

- Generated (UTC): 2026-02-24T06:58:51.416302+00:00

## Heat segments (H)

- rows: 37
- temps: 100C, 110C, 120C, 125C, 75C, 90C
- infeasible segments: 0
- q_lb active segments: 22
- q_ub active segments: 18
- max H_lb shift: 0.964262
- max H_ub shift: 0.00051904

## Power segments (E)

- rows: 22
- temps: 100C, 110C, 120C, 125C, 75C, 90C, KOND
- infeasible segments: 0
- q_lb active segments: 10
- q_ub active segments: 7
- max E_lb shift: 0.187976
- max E_ub shift: 0.000115812

## Worst examples

### Heat (largest lower-bound shifts)

```json
[
  {
    "temp_label": "110C",
    "segment": 1,
    "h_lb": 0.0,
    "h_lb_eff": 0.9642620293272408,
    "h_lb_shift": 0.9642620293272408,
    "q_lb": 38.358,
    "q_lb_eff": 38.358,
    "q_min_line": 37.0494
  },
  {
    "temp_label": "120C",
    "segment": 1,
    "h_lb": 0.0,
    "h_lb_eff": 0.7940310439376164,
    "h_lb_shift": 0.7940310439376164,
    "q_lb": 45.7143,
    "q_lb_eff": 45.7143,
    "q_min_line": 44.5542
  },
  {
    "temp_label": "125C",
    "segment": 1,
    "h_lb": 0.0,
    "h_lb_eff": 0.7726869681449449,
    "h_lb_shift": 0.7726869681449449,
    "q_lb": 49.6552,
    "q_lb_eff": 49.6552,
    "q_min_line": 48.4875
  },
  {
    "temp_label": "90C",
    "segment": 1,
    "h_lb": 0.0,
    "h_lb_eff": 0.757160788704148,
    "h_lb_shift": 0.757160788704148,
    "q_lb": 28.5057,
    "q_lb_eff": 28.5057,
    "q_min_line": 27.6238
  },
  {
    "temp_label": "100C",
    "segment": 1,
    "h_lb": 0.0,
    "h_lb_eff": 0.7322159043771841,
    "h_lb_shift": 0.7322159043771841,
    "q_lb": 33.1034,
    "q_lb_eff": 33.1034,
    "q_min_line": 32.1855
  }
]
```

### Power (largest lower-bound shifts)

```json
[
  {
    "temp_label": "90C",
    "segment": 1,
    "e_lb": 0.0,
    "e_lb_eff": 0.18797646909288923,
    "e_lb_shift": 0.18797646909288923,
    "q_lb": 29.1626,
    "q_lb_eff": 29.1626,
    "q_min_line": 28.4823
  },
  {
    "temp_label": "100C",
    "segment": 1,
    "e_lb": 0.0,
    "e_lb_eff": 0.0634065573520318,
    "e_lb_shift": 0.0634065573520318,
    "q_lb": 34.4171,
    "q_lb_eff": 34.4171,
    "q_min_line": 34.1678
  },
  {
    "temp_label": "90C",
    "segment": 2,
    "e_lb": 23.0771,
    "e_lb_eff": 23.127985701682796,
    "e_lb_shift": 0.050885701682794604,
    "q_lb": 112.184,
    "q_lb_eff": 112.184,
    "q_min_line": 111.98384974300001
  },
  {
    "temp_label": "90C",
    "segment": 3,
    "e_lb": 63.3717,
    "e_lb_eff": 63.371822097589956,
    "e_lb_shift": 0.00012209758995851416,
    "q_lb": 270.476,
    "q_lb_eff": 270.476,
    "q_min_line": 270.475492317
  },
  {
    "temp_label": "KOND",
    "segment": 4,
    "e_lb": 111.217,
    "e_lb_eff": 111.21706999402744,
    "e_lb_shift": 6.999402744156669e-05,
    "q_lb": 399.08,
    "q_lb_eff": 399.08,
    "q_min_line": 399.07961092000005
  }
]
```
