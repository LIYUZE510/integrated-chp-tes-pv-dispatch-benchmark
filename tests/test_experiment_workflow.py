from __future__ import annotations

import pandas as pd

from chp_pv_sim.experiments.config import ExperimentConfig, batch_to_experiment_configs, BatchConfig, BatchExperiment
from chp_pv_sim.experiments.qc import build_validation_report


def test_experiment_config_defaults_uc_disables_rolling() -> None:
    cfg = ExperimentConfig.from_dict(
        {
            "run": {"method": "uc", "tag": "x"},
            "rolling": {"enabled": True, "horizon_hours": 48, "step_hours": 24},
        }
    )
    assert cfg.run.method == "uc"
    assert cfg.rolling.enabled is False


def test_batch_expands_multiple_scenarios() -> None:
    batch = BatchConfig(
        defaults=ExperimentConfig.from_dict(
            {
                "run": {"method": "uc", "tag": "tag0", "scenario": "week_a"},
            }
        ),
        experiments=[
            BatchExperiment(
                name="exp1",
                scenarios=["week_a", "week_b"],
                overrides={"run": {"method": "mpc", "tag": "tag1"}, "rolling": {"horizon_hours": 48, "step_hours": 24}},
            )
        ],
        output_csv="reports/x.csv",
    )
    items = batch_to_experiment_configs(batch)
    assert len(items) == 2
    assert items[0][0] == "exp1"
    assert items[0][1].run.scenario == "week_a"
    assert items[1][1].run.scenario == "week_b"
    assert items[0][1].run.method == "mpc"


def test_validation_report_catches_export_violation() -> None:
    cfg = ExperimentConfig.from_dict(
        {
            "run": {"method": "uc", "tag": "x"},
            "grid": {"grid_export_cap_mw": 60.0},
            "storage": {"s_max_mwh": 100.0},
        }
    )
    df = pd.DataFrame(
        {
            "heat_balance_residual": [0.0, 0.0],
            "elec_balance_residual": [0.0, 0.0],
            "grid_export_mw": [10.0, 70.0],
            "grid_import_mw": [0.0, 0.0],
            "S_mwh": [50.0, 50.0],
            "S_next_mwh": [50.0, 50.0],
            "H_chp_mw": [0.0, 0.0],
            "E_chp_mw": [0.0, 0.0],
            "Q_in_mw": [0.0, 0.0],
            "boiler_mw": [0.0, 0.0],
            "dump_mw": [0.0, 0.0],
            "under_mw": [0.0, 0.0],
            "ch_mw": [0.0, 0.0],
            "dis_mw": [0.0, 0.0],
            "pv_curt_mw": [0.0, 0.0],
            "chp_curt_mw": [0.0, 0.0],
        }
    )
    report = build_validation_report(df, cfg=cfg, qc=cfg.qc, expected_terminal_soc=50.0)
    assert report["pass"] is False
    assert any("Grid export exceeds cap" in issue for issue in report["issues"])
