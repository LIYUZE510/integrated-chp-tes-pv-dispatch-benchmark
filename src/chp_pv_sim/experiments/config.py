from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


VALID_METHODS = {"uc", "mpc"}
VALID_UC_TERMINAL_MODES = {"match_initial", "free"}
VALID_ROLLING_TERMINAL_MODES = {"match_window_initial", "match_week_initial", "free"}
VALID_FINAL_WINDOW_TERMINAL_MODES = {"inherit", "match_window_initial", "match_week_initial", "free"}


@dataclass
class RunSection:
    scenario: str = "week_2023_dec01"
    method: str = "uc"
    tag: str = "baseline_run"
    uc_terminal_soc_mode: str = "match_initial"


@dataclass
class StorageSection:
    s_max_mwh: float = 800.0
    p_ch_max_mw: float = 200.0
    p_dis_max_mw: float = 200.0
    eta_ch: float = 0.95
    eta_dis: float = 0.95
    loss_per_hour: float = 0.001
    s_init_mwh: float = 200.0


@dataclass
class GridSection:
    grid_export_cap_mw: float = 60.0
    price_sell: float = 50.0
    price_buy: float = 70.0
    pv_scale: float = 1.0
    e_load_base_mw: float = 20.0
    e_load_alpha_per_heat: float = 0.0
    penalty_pv_curt: float = 0.1
    penalty_chp_curt: float = 0.0


@dataclass
class CostSection:
    cost_q: float = 15.0
    cost_boiler: float = 60.0
    cost_dump: float = 50.0
    penalty_under: float = 1e6
    cycle_cost: float = 0.01


@dataclass
class CommitmentSection:
    startup_cost: float = 5000.0
    shutdown_cost: float = 0.0
    min_up_hours: int = 3
    min_down_hours: int = 2
    on_init: int = 0


@dataclass
class SolverSection:
    time_limit_s: float = 900.0
    mip_rel_gap: float = 0.2
    tee: bool = False


@dataclass
class RollingSection:
    enabled: bool = False
    horizon_hours: int = 48
    step_hours: int = 24
    window_terminal_soc_mode: str = "match_window_initial"
    final_window_terminal_soc_mode: str = "match_week_initial"


@dataclass
class QCSection:
    residual_tol: float = 1e-5
    bound_tol: float = 1e-5
    overlap_tol_mw: float = 1e-5
    fail_on_violation: bool = False


@dataclass
class ExperimentConfig:
    run: RunSection = field(default_factory=RunSection)
    storage: StorageSection = field(default_factory=StorageSection)
    grid: GridSection = field(default_factory=GridSection)
    cost: CostSection = field(default_factory=CostSection)
    commitment: CommitmentSection = field(default_factory=CommitmentSection)
    solver: SolverSection = field(default_factory=SolverSection)
    rolling: RollingSection = field(default_factory=RollingSection)
    qc: QCSection = field(default_factory=QCSection)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None = None) -> "ExperimentConfig":
        payload = payload or {}
        cfg = cls(
            run=RunSection(**payload.get("run", {})),
            storage=StorageSection(**payload.get("storage", {})),
            grid=GridSection(**payload.get("grid", {})),
            cost=CostSection(**payload.get("cost", {})),
            commitment=CommitmentSection(**payload.get("commitment", {})),
            solver=SolverSection(**payload.get("solver", {})),
            rolling=RollingSection(**payload.get("rolling", {})),
            qc=QCSection(**payload.get("qc", {})),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.run.method not in VALID_METHODS:
            raise ValueError(f"run.method must be one of {sorted(VALID_METHODS)}")
        if self.run.uc_terminal_soc_mode not in VALID_UC_TERMINAL_MODES:
            raise ValueError(
                f"run.uc_terminal_soc_mode must be one of {sorted(VALID_UC_TERMINAL_MODES)}"
            )
        if self.rolling.window_terminal_soc_mode not in VALID_ROLLING_TERMINAL_MODES:
            raise ValueError(
                "rolling.window_terminal_soc_mode must be one of "
                f"{sorted(VALID_ROLLING_TERMINAL_MODES)}"
            )
        if self.rolling.final_window_terminal_soc_mode not in VALID_FINAL_WINDOW_TERMINAL_MODES:
            raise ValueError(
                "rolling.final_window_terminal_soc_mode must be one of "
                f"{sorted(VALID_FINAL_WINDOW_TERMINAL_MODES)}"
            )
        if self.commitment.on_init not in (0, 1):
            raise ValueError("commitment.on_init must be 0 or 1")
        if self.run.method == "uc":
            self.rolling.enabled = False
        else:
            self.rolling.enabled = True
            if self.rolling.horizon_hours < self.rolling.step_hours:
                raise ValueError("For MPC, rolling.horizon_hours must be >= rolling.step_hours")
        if self.storage.s_max_mwh <= 0:
            raise ValueError("storage.s_max_mwh must be positive")
        if self.storage.p_ch_max_mw < 0 or self.storage.p_dis_max_mw < 0:
            raise ValueError("storage charge/discharge power limits must be non-negative")
        if self.solver.time_limit_s <= 0:
            raise ValueError("solver.time_limit_s must be positive")
        if self.solver.mip_rel_gap < 0:
            raise ValueError("solver.mip_rel_gap must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchExperiment:
    name: str
    scenarios: list[str] = field(default_factory=list)
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchConfig:
    defaults: ExperimentConfig
    experiments: list[BatchExperiment]
    output_csv: str = "reports/multiweek_batch_summary.csv"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError(f"YAML at {path} must contain a mapping at the top level.")
    return payload


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    return ExperimentConfig.from_dict(load_yaml(path))


def load_batch_config(path: str | Path) -> BatchConfig:
    payload = load_yaml(path)
    defaults = ExperimentConfig.from_dict(payload.get("defaults", {}))

    experiments_raw = payload.get("experiments", [])
    if not isinstance(experiments_raw, list) or not experiments_raw:
        raise ValueError("Batch config must contain a non-empty 'experiments' list.")

    experiments: list[BatchExperiment] = []
    for raw in experiments_raw:
        if not isinstance(raw, dict):
            raise TypeError("Each item in 'experiments' must be a mapping.")
        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError("Each batch experiment must have a non-empty 'name'.")
        scenarios = raw.get("scenarios", [])
        if scenarios is None:
            scenarios = []
        if not isinstance(scenarios, list):
            raise TypeError(f"Batch experiment '{name}' has non-list 'scenarios'.")
        overrides = {k: v for k, v in raw.items() if k not in {"name", "scenarios"}}
        experiments.append(BatchExperiment(name=name, scenarios=[str(s) for s in scenarios], overrides=overrides))

    output_csv = str(payload.get("output_csv", "reports/multiweek_batch_summary.csv"))
    return BatchConfig(defaults=defaults, experiments=experiments, output_csv=output_csv)


def batch_to_experiment_configs(batch: BatchConfig) -> list[tuple[str, ExperimentConfig]]:
    base = batch.defaults.to_dict()
    configs: list[tuple[str, ExperimentConfig]] = []
    for experiment in batch.experiments:
        merged = deep_merge(base, experiment.overrides)
        scenarios = experiment.scenarios or [merged.get("run", {}).get("scenario", batch.defaults.run.scenario)]
        for scenario in scenarios:
            merged_one = deep_merge(merged, {"run": {"scenario": scenario}})
            cfg = ExperimentConfig.from_dict(merged_one)
            configs.append((experiment.name, cfg))
    return configs
