# XAI4HEAT Heat Demand Derivation Report

- Generated (UTC): 2026-02-24T03:39:43.367671+00:00
- Input rows/cols: 68869 / 14
- Output (substation) rows/cols: 68869 / 13
- Output (aggregate) rows/cols: 18137 / 7

## Coverage
- Start: 2019-11-01 07:00:00
- End: 2024-03-31 23:00:00
- Substations: L12, L17, L22, L4, L8
- Heating seasons: 2019, 2020, 2021, 2022, 2023

## Heat demand hourly stats (MWh per hour)
- min=0, p01=0, median=0.14, mean=0.162199, p99=0.53, max=178.36

## Important note
- The dataset adds new substations in later years, so the aggregate across 'all available' substations is not directly comparable across seasons. For a consistent city-zone simulation, we will select a fixed subset of substations in the scenario config.
