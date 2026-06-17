from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pandas as pd
import pytest


try:
    import pyomo.environ  # noqa: F401
except ModuleNotFoundError:
    pyomo_stub = types.ModuleType("pyomo")
    pyomo_environ_stub = types.ModuleType("pyomo.environ")
    pyomo_opt_stub = types.ModuleType("pyomo.opt")

    class _TerminationCondition:
        optimal = "optimal"
        feasible = "feasible"

    pyomo_environ_stub.value = lambda x: x
    pyomo_opt_stub.TerminationCondition = _TerminationCondition
    pyomo_stub.environ = pyomo_environ_stub
    pyomo_stub.opt = pyomo_opt_stub
    sys.modules.setdefault("pyomo", pyomo_stub)
    sys.modules.setdefault("pyomo.environ", pyomo_environ_stub)
    sys.modules.setdefault("pyomo.opt", pyomo_opt_stub)

from chp_pv_sim.experiments import engine
from chp_pv_sim.experiments.config import ExperimentConfig
from chp_pv_sim.experiments.engine import RunArtifacts


def _cfg(tag: str = "resub_2026_test", scenario: str = "tmp_scenario") -> ExperimentConfig:
    return ExperimentConfig.from_dict(
        {
            "run": {
                "scenario": scenario,
                "method": "uc",
                "tag": tag,
            }
        }
    )


def _dispatch() -> pd.DataFrame:
    return pd.DataFrame({"value": [1.0]})


def _windows() -> pd.DataFrame:
    return pd.DataFrame({"window_id": [1], "wallclock_s": [0.0]})


def _write_dummy_outputs(cfg: ExperimentConfig, *, overwrite: bool = False) -> RunArtifacts:
    return engine._write_artifacts(
        cfg=cfg,
        dispatch=_dispatch(),
        summary={"tag": cfg.run.tag, "written": True},
        windows_df=_windows(),
        validation={"pass": True},
        overwrite=overwrite,
    )


def _patch_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    output_csv: str,
    items: list[tuple[str, ExperimentConfig]],
    overwrite: bool = False,
    run_experiment_func=None,
):
    from chp_pv_sim.experiments import run_batch

    batch = type("Batch", (), {"output_csv": output_csv})()
    argv = ["run_batch", "--config", "dummy.yaml"]
    if overwrite:
        argv.append("--overwrite")

    monkeypatch.setattr(engine, "ROOT", tmp_path)
    monkeypatch.setattr(run_batch, "ROOT", tmp_path)
    monkeypatch.setattr(run_batch, "load_batch_config", lambda path: batch)
    monkeypatch.setattr(run_batch, "batch_to_experiment_configs", lambda loaded: items)
    if run_experiment_func is not None:
        monkeypatch.setattr(run_batch, "run_experiment", run_experiment_func)
    monkeypatch.setattr(sys, "argv", argv)
    return run_batch


def test_existing_artifact_conflict_fails_before_any_output_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    cfg = _cfg("frozen_tag")
    paths = engine.experiment_artifact_paths(cfg)
    dispatch_path, summary_path, windows_path, validation_path = paths

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("original summary", encoding="utf-8")

    with pytest.raises(FileExistsError) as excinfo:
        _write_dummy_outputs(cfg)

    assert str(summary_path) in str(excinfo.value)
    assert summary_path.read_text(encoding="utf-8") == "original summary"
    assert not dispatch_path.exists()
    assert not windows_path.exists()
    assert not validation_path.exists()


def test_no_clobber_error_lists_all_conflicts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    cfg = _cfg("frozen_tag")
    paths = engine.experiment_artifact_paths(cfg)
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    for path in paths:
        path.write_text(f"existing {path.name}", encoding="utf-8")

    with pytest.raises(FileExistsError) as excinfo:
        _write_dummy_outputs(cfg)

    message = str(excinfo.value)
    for path in paths:
        assert str(path) in message


def test_explicit_overwrite_permits_replacement_in_temp_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    cfg = _cfg("resub_2026_overwrite")
    paths = engine.experiment_artifact_paths(cfg)
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    for path in paths:
        path.write_text("old content", encoding="utf-8")

    artifacts = _write_dummy_outputs(cfg, overwrite=True)

    assert pd.read_parquet(artifacts.dispatch_path)["value"].tolist() == [1.0]
    assert json.loads(artifacts.summary_path.read_text(encoding="utf-8"))["written"] is True
    assert pd.read_csv(artifacts.windows_path)["window_id"].tolist() == [1]
    assert json.loads(artifacts.validation_path.read_text(encoding="utf-8"))["pass"] is True


def test_new_tag_writes_normally_in_temp_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    cfg = _cfg("resub_2026_new")

    artifacts = _write_dummy_outputs(cfg)

    assert artifacts.dispatch_path.exists()
    assert artifacts.summary_path.exists()
    assert artifacts.windows_path.exists()
    assert artifacts.validation_path.exists()


def test_batch_report_conflict_fails_before_any_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg("resub_2026_batch")
    report_path = tmp_path / "reports" / "batch.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("frozen report", encoding="utf-8")
    called = False

    def fake_run_experiment(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("run_experiment should not be called when preflight finds a conflict")

    run_batch = _patch_batch(
        monkeypatch,
        tmp_path,
        output_csv="reports/batch.csv",
        items=[("case", cfg)],
        run_experiment_func=fake_run_experiment,
    )

    with pytest.raises(FileExistsError) as excinfo:
        run_batch.main()

    assert str(report_path) in str(excinfo.value)
    assert called is False
    assert report_path.read_text(encoding="utf-8") == "frozen report"


def test_batch_duplicate_new_tags_fail_before_any_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chp_pv_sim.experiments import run_batch

    cfg_a = _cfg("resub_2026_dup")
    cfg_b = _cfg("resub_2026_dup")
    called = False

    def fake_run_experiment(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("run_experiment should not be called for duplicate planned outputs")

    run_batch = _patch_batch(
        monkeypatch,
        tmp_path,
        output_csv="reports/batch.csv",
        items=[("first", cfg_a), ("second", cfg_b)],
        run_experiment_func=fake_run_experiment,
    )

    with pytest.raises(ValueError) as excinfo:
        run_batch.main()

    message = str(excinfo.value)
    for path in run_batch.experiment_artifact_paths(cfg_a):
        assert run_batch._normalized_planned_path(path) in message
        assert not path.exists()
    assert "first" in message
    assert "second" in message
    assert "resub_2026_dup" in message
    assert called is False
    assert not (tmp_path / "reports" / "batch.csv").exists()


def test_batch_duplicate_detection_ignores_overwrite_and_path_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_a = _cfg("resub_2026_case", scenario="Tmp_Scenario")
    cfg_b = _cfg("resub_2026_case", scenario="tmp_scenario")
    called = False

    def fake_run_experiment(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("--overwrite must not permit duplicate planned outputs")

    run_batch = _patch_batch(
        monkeypatch,
        tmp_path,
        output_csv="reports/batch.csv",
        items=[("upper", cfg_a), ("lower", cfg_b)],
        overwrite=True,
        run_experiment_func=fake_run_experiment,
    )

    with pytest.raises(ValueError) as excinfo:
        run_batch.main()

    message = str(excinfo.value)
    assert run_batch._normalized_planned_path(run_batch.experiment_artifact_paths(cfg_a)[0]) in message
    assert "upper" in message
    assert "lower" in message
    assert called is False
    for path in run_batch.experiment_artifact_paths(cfg_a) + run_batch.experiment_artifact_paths(cfg_b):
        assert not path.exists()
    assert not (tmp_path / "reports" / "batch.csv").exists()


def test_later_batch_artifact_conflict_prevents_all_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_first = _cfg("resub_2026_first")
    cfg_second = _cfg("resub_2026_second")
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    second_summary = engine.experiment_artifact_paths(cfg_second)[1]
    second_summary.parent.mkdir(parents=True, exist_ok=True)
    second_summary.write_text("existing later summary", encoding="utf-8")
    called = False

    def fake_run_experiment(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("no batch item should run when a later item has a conflict")

    run_batch = _patch_batch(
        monkeypatch,
        tmp_path,
        output_csv="reports/batch.csv",
        items=[("first", cfg_first), ("second", cfg_second)],
        run_experiment_func=fake_run_experiment,
    )

    with pytest.raises(FileExistsError) as excinfo:
        run_batch.main()

    assert str(second_summary) in str(excinfo.value)
    assert called is False
    for path in engine.experiment_artifact_paths(cfg_first):
        assert not path.exists()
    assert second_summary.read_text(encoding="utf-8") == "existing later summary"
    assert not (tmp_path / "reports" / "batch.csv").exists()


def test_run_experiment_conflict_fails_before_solver_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    monkeypatch.setattr(engine, "ensure_dirs", lambda: None)
    cfg = _cfg("frozen_tag")
    paths = engine.experiment_artifact_paths(cfg)
    paths[1].parent.mkdir(parents=True, exist_ok=True)
    paths[1].write_text("frozen summary", encoding="utf-8")
    called = False

    def fake_run_uc(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("run_uc should not be called when preflight finds a conflict")

    monkeypatch.setattr(engine, "run_uc", fake_run_uc)

    with pytest.raises(FileExistsError):
        engine.run_experiment(cfg)

    assert called is False
    assert paths[1].read_text(encoding="utf-8") == "frozen summary"


def test_batch_overwrite_replaces_temp_report_and_passes_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _cfg("resub_2026_batch")
    report_path = tmp_path / "reports" / "batch.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("old report", encoding="utf-8")
    overwrite_values: list[bool] = []

    def fake_run_experiment(cfg_arg, *, overwrite: bool = False):
        overwrite_values.append(overwrite)
        return object()

    run_batch = _patch_batch(
        monkeypatch,
        tmp_path,
        output_csv="reports/batch.csv",
        items=[("case", cfg)],
        overwrite=True,
        run_experiment_func=fake_run_experiment,
    )
    monkeypatch.setattr(run_batch, "build_batch_row", lambda artifacts: {"ok": True})

    run_batch.main()

    assert overwrite_values == [True]
    assert "ok" in report_path.read_text(encoding="utf-8")


def test_batch_unique_new_tags_reach_mocked_execution_without_result_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_first = _cfg("resub_2026_unique_first")
    cfg_second = _cfg("resub_2026_unique_second")
    seen_tags: list[str] = []

    def fake_run_experiment(cfg_arg, *, overwrite: bool = False):
        seen_tags.append(cfg_arg.run.tag)
        return object()

    run_batch = _patch_batch(
        monkeypatch,
        tmp_path,
        output_csv="reports/batch.csv",
        items=[("first", cfg_first), ("second", cfg_second)],
        run_experiment_func=fake_run_experiment,
    )
    monkeypatch.setattr(run_batch, "build_batch_row", lambda artifacts: {"ok": True})

    run_batch.main()

    assert seen_tags == ["resub_2026_unique_first", "resub_2026_unique_second"]
    for cfg in (cfg_first, cfg_second):
        for path in engine.experiment_artifact_paths(cfg):
            assert not path.exists()
    assert (tmp_path / "reports" / "batch.csv").exists()
