from __future__ import annotations

import pandas as pd
import pytest

from chp_pv_sim.reports.build_objective_breakdown_table import recover_q_row
from chp_pv_sim.reports.result_catalog import dedupe_catalog, make_mpc_tag


def test_make_mpc_tag_includes_both_eload_and_dump_cost() -> None:
    assert make_mpc_tag(20.0, 5.0) == "mpc_eload20MW_dump5"
    assert make_mpc_tag(12.5, 0.5) == "mpc_eload12p5MW_dump0p5"


def test_dedupe_catalog_rejects_conflicting_duplicate_scenarios() -> None:
    df = pd.DataFrame(
        [
            {
                "file": "dispatch_summary_pv_grid__mpc_eload20MW_dump5__a.json",
                "created_utc": "2026-03-01T00:00:00+00:00",
                "method": "MPC",
                "scenario_name": "week_2023_dec01",
                "e_load_base_mw": 20.0,
                "cost_dump": 5.0,
                "grid_export_cap_mw": 60.0,
                "startup_cost": 5000.0,
                "min_up_hours": 3,
                "min_down_hours": 2,
                "horizon_hours": 48.0,
                "step_hours": 24.0,
                "time_limit_window_s": 120.0,
                "mip_rel_gap": 0.2,
                "boiler_share_pct": 10.0,
                "dump_share_pct": 20.0,
                "E_curt_ratio_pct": 0.0,
                "grid_import_mwh": 0.0,
                "grid_export_mwh": 3000.0,
                "net_export_mwh": 3000.0,
                "objective_profit_like": -100.0,
                "objective_system_cost": 100.0,
                "profit_objective_realized": -100.0,
                "system_cost_realized": 100.0,
                "starts": 1,
                "stops": 0,
            },
            {
                "file": "dispatch_summary_pv_grid__mpc_eload20MW_dump5__b.json",
                "created_utc": "2026-03-02T00:00:00+00:00",
                "method": "MPC",
                "scenario_name": "week_2023_dec01",
                "e_load_base_mw": 20.0,
                "cost_dump": 5.0,
                "grid_export_cap_mw": 60.0,
                "startup_cost": 5000.0,
                "min_up_hours": 3,
                "min_down_hours": 2,
                "horizon_hours": 48.0,
                "step_hours": 24.0,
                "time_limit_window_s": 120.0,
                "mip_rel_gap": 0.2,
                "boiler_share_pct": 10.0,
                "dump_share_pct": 45.26,
                "E_curt_ratio_pct": 0.0,
                "grid_import_mwh": 0.0,
                "grid_export_mwh": 4731.629,
                "net_export_mwh": 4731.629,
                "objective_profit_like": -200.0,
                "objective_system_cost": 200.0,
                "profit_objective_realized": -200.0,
                "system_cost_realized": 200.0,
                "starts": 1,
                "stops": 0,
            },
        ]
    )

    with pytest.raises(RuntimeError):
        dedupe_catalog(df)


def test_recover_q_row_uses_q_equals_kx_plus_b_direction() -> None:
    heat_tbl = pd.DataFrame(
        {
            "temp_label": ["75C"],
            "segment_raw": [1],
            "segment_idx": [1],
            "k": [2.0],
            "b": [10.0],
            "q_lb": [10.0],
            "q_ub": [110.0],
        }
    )
    power_tbl = pd.DataFrame(
        {
            "temp_label": ["75C"],
            "segment_raw": [1],
            "segment_idx": [1],
            "k": [4.0],
            "b": [20.0],
            "q_lb": [20.0],
            "q_ub": [220.0],
        }
    )
    row = pd.Series(
        {
            "Q_chp_mw": 0.0,
            "H_chp_mw": 15.0,   # => Q = 2*15 + 10 = 40
            "E_chp_mw": 5.0,    # => Q = 4*5 + 20 = 40
            "on": 1.0,
            "temp_label": "75C",
            "heat_seg": 1,
            "power_seg": 1,
        }
    )
    assert recover_q_row(row, heat_tbl=heat_tbl, power_tbl=power_tbl) == pytest.approx(40.0)
