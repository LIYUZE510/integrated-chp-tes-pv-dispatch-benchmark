from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from chp_pv_sim.experiments.config import ExperimentConfig, QCSection
from chp_pv_sim.models.chp_week_storage_pv_grid_dispatch import (
    Meta,
    build_model,
    compute_realized_economics,
    load_segments,
)
from chp_pv_sim.models.solver_metrics import extract_solver_diagnostics
from chp_pv_sim.paths import ROOT, ensure_dirs


@dataclass
class ScenarioInputs:
    scenario: str
    dt_index: pd.DatetimeIndex
    heat_demand_mw: pd.Series
    pv_avail_mw: pd.Series
    e_load_mw: pd.Series


@dataclass
class RunArtifacts:
    dispatch_path: Path
    summary_path: Path
    windows_path: Path
    validation_path: Path
    summary: dict[str, Any]
    validation: dict[str, Any]


def ensure_no_existing_paths(paths: list[Path], *, context: str, overwrite: bool = False) -> None:
    if overwrite:
        return
    conflicts = [Path(path) for path in paths if Path(path).exists()]
    if not conflicts:
        return
    conflict_lines = "\n".join(f"  - {path}" for path in conflicts)
    raise FileExistsError(
        f"Refusing to overwrite existing {context} file(s):\n"
        f"{conflict_lines}\n"
        "Use --overwrite only when replacing these files is intentional."
    )


def experiment_artifact_paths(cfg: ExperimentConfig) -> list[Path]:
    scen_dir = ROOT / "data" / "scenarios" / cfg.run.scenario
    out_dir = scen_dir / "results"
    return [
        out_dir / f"dispatch_chp_storage_pv_grid__{cfg.run.tag}.parquet",
        out_dir / f"dispatch_summary_pv_grid__{cfg.run.tag}.json",
        out_dir / f"solver_windows_pv_grid__{cfg.run.tag}.csv",
        out_dir / f"dispatch_validation_pv_grid__{cfg.run.tag}.json",
    ]


def _to_float_series(series: pd.Series, name: str) -> pd.Series:
    out = pd.to_numeric(series, errors="raise").astype(float)
    if out.isna().any():
        raise ValueError(f"{name} contains NaN values after numeric conversion.")
    return out


def _val(x: Any) -> float:
    return float(pyo.value(x))


def _configure_highs_solver(
    solver: Any,
    *,
    time_limit_s: float,
    mip_rel_gap: float,
    output_flag: bool,
) -> Any:
    """
    Configure HiGHS for more repeatable time-limited MIP runs.

    Key changes relative to the original version:
    - threads = 1
    - parallel = "off"
    - random_seed = 1
    - presolve = "on"

    These settings do not guarantee identical incumbents in every
    time-limited run, but they reduce run-to-run variability.
    """
    stable_options = {
        "time_limit": float(time_limit_s),
        "mip_rel_gap": float(mip_rel_gap),
        "output_flag": bool(output_flag),
        "log_to_console": bool(output_flag),
        "threads": 1,
        "parallel": "off",
        "random_seed": 1,
        "presolve": "on",
    }

    for attr in ("options", "highs_options"):
        opts = getattr(solver, attr, None)
        if opts is not None:
            for key, val in stable_options.items():
                try:
                    opts[key] = val
                except Exception:
                    pass

    cfg = getattr(solver, "config", None)
    if cfg is not None:
        if hasattr(cfg, "time_limit"):
            try:
                cfg.time_limit = float(time_limit_s)
            except Exception:
                pass
        if hasattr(cfg, "mip_rel_gap"):
            try:
                cfg.mip_rel_gap = float(mip_rel_gap)
            except Exception:
                pass
        if hasattr(cfg, "stream_solver"):
            try:
                cfg.stream_solver = bool(output_flag)
            except Exception:
                pass

    return solver


def load_scenario_inputs(cfg: ExperimentConfig) -> ScenarioInputs:
    scen_dir = ROOT / "data" / "scenarios" / cfg.run.scenario
    heat_path = scen_dir / "heat.parquet"
    pv_path = scen_dir / "pv.parquet"

    if not heat_path.exists():
        raise FileNotFoundError(f"Scenario heat file not found: {heat_path}")
    if not pv_path.exists():
        raise FileNotFoundError(
            f"Scenario PV file not found: {pv_path}\n"
            "Please create PV first, or use an existing scenario that already contains pv.parquet."
        )

    heat_df = pd.read_parquet(heat_path)
    pv_df = pd.read_parquet(pv_path)

    heat_df["datetime_local"] = pd.to_datetime(heat_df["datetime_local"], errors="raise")
    pv_df["datetime_local"] = pd.to_datetime(pv_df["datetime_local"], errors="raise")

    heat_df = heat_df.sort_values("datetime_local").reset_index(drop=True)
    pv_df = pv_df.sort_values("datetime_local").reset_index(drop=True)

    if not heat_df["datetime_local"].equals(pv_df["datetime_local"]):
        merged = heat_df.merge(pv_df[["datetime_local", "pv_ac_mw"]], on="datetime_local", how="inner")
        if len(merged) != len(heat_df):
            raise ValueError(
                "Heat and PV timestamps do not align exactly.\n"
                f"heat rows = {len(heat_df)}\n"
                f"pv rows   = {len(pv_df)}\n"
                f"merged    = {len(merged)}"
            )
        heat_df = merged
    else:
        heat_df["pv_ac_mw"] = pv_df["pv_ac_mw"].astype(float)

    dt_index = pd.DatetimeIndex(heat_df["datetime_local"])
    heat_demand = _to_float_series(heat_df["heat_demand_mw"], "heat_demand_mw")
    pv_avail = (_to_float_series(heat_df["pv_ac_mw"], "pv_ac_mw") * float(cfg.grid.pv_scale)).clip(lower=0.0)
    e_load = (
        float(cfg.grid.e_load_base_mw)
        + float(cfg.grid.e_load_alpha_per_heat) * heat_demand
    ).clip(lower=0.0)

    return ScenarioInputs(
        scenario=cfg.run.scenario,
        dt_index=dt_index,
        heat_demand_mw=heat_demand,
        pv_avail_mw=pv_avail,
        e_load_mw=e_load,
    )


def _resolve_uc_terminal_target(cfg: ExperimentConfig) -> float | None:
    mode = cfg.run.uc_terminal_soc_mode
    if mode == "match_initial":
        return float(cfg.storage.s_init_mwh)
    if mode == "free":
        return None
    raise ValueError(f"Unsupported uc terminal SOC mode: {mode}")


def _resolve_window_terminal_target(
    *,
    mode: str,
    current_s0: float,
    week_s0: float,
) -> float | None:
    if mode == "match_window_initial":
        return float(current_s0)
    if mode == "match_week_initial":
        return float(week_s0)
    if mode == "free":
        return None
    raise ValueError(f"Unsupported rolling terminal SOC mode: {mode}")


def _resolve_last_window_terminal_mode(cfg: ExperimentConfig) -> str:
    mode = cfg.rolling.final_window_terminal_soc_mode
    if mode == "inherit":
        return cfg.rolling.window_terminal_soc_mode
    return mode


def _build_meta(
    cfg: ExperimentConfig,
    *,
    n_hours: int,
    s_init_mwh: float,
    on_init: int,
    time_limit_s: float,
    terminal_soc_target_mwh: float | None,
) -> Meta:
    return Meta(
        scenario=cfg.run.scenario,
        n_hours=int(n_hours),
        storage_s_max_mwh=float(cfg.storage.s_max_mwh),
        storage_p_ch_max_mw=float(cfg.storage.p_ch_max_mw),
        storage_p_dis_max_mw=float(cfg.storage.p_dis_max_mw),
        eta_ch=float(cfg.storage.eta_ch),
        eta_dis=float(cfg.storage.eta_dis),
        loss_per_hour=float(cfg.storage.loss_per_hour),
        s_init_mwh=float(s_init_mwh),
        grid_export_cap_mw=float(cfg.grid.grid_export_cap_mw),
        price_sell=float(cfg.grid.price_sell),
        price_buy=float(cfg.grid.price_buy),
        pv_scale=float(cfg.grid.pv_scale),
        e_load_base_mw=float(cfg.grid.e_load_base_mw),
        e_load_alpha_per_heat=float(cfg.grid.e_load_alpha_per_heat),
        penalty_pv_curt=float(cfg.grid.penalty_pv_curt),
        penalty_chp_curt=float(cfg.grid.penalty_chp_curt),
        cost_q=float(cfg.cost.cost_q),
        cost_boiler=float(cfg.cost.cost_boiler),
        cost_dump=float(cfg.cost.cost_dump),
        penalty_under=float(cfg.cost.penalty_under),
        cycle_cost=float(cfg.cost.cycle_cost),
        startup_cost=float(cfg.commitment.startup_cost),
        shutdown_cost=float(cfg.commitment.shutdown_cost),
        min_up_hours=int(cfg.commitment.min_up_hours),
        min_down_hours=int(cfg.commitment.min_down_hours),
        on_init=int(on_init),
        time_limit_s=float(time_limit_s),
        mip_rel_gap=float(cfg.solver.mip_rel_gap),
        tee=bool(cfg.solver.tee),
        terminal_soc_target_mwh=(None if terminal_soc_target_mwh is None else float(terminal_soc_target_mwh)),
    )


def _extract_dispatch_rows(
    model: pyo.ConcreteModel,
    *,
    dt_index: pd.DatetimeIndex,
    demand: np.ndarray,
    pv_av: np.ndarray,
    eload: np.ndarray,
    n_take: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    temps = list(model.TEMP)

    for t in range(n_take):
        yoff = _val(model.y_off[t])
        on = 1.0 - yoff

        if yoff > 0.5:
            mode = "OFF"
            temp_label = None
        else:
            mode = "ON"
            temp_vals = {tt: _val(model.y[t, tt]) for tt in temps}
            temp_label = max(temp_vals, key=temp_vals.get)

        heat_seg = None
        power_seg = None
        if mode == "ON":
            for (tt, seg) in model.HS:
                if _val(model.zH[t, (tt, seg)]) > 0.5:
                    heat_seg = int(seg)
                    break
            for (tt, seg) in model.ES:
                if _val(model.zE[t, (tt, seg)]) > 0.5:
                    power_seg = int(seg)
                    break

        rows.append(
            {
                "datetime_local": dt_index[t],
                "heat_demand_mw": float(demand[t]),
                "pv_avail_mw": float(pv_av[t]),
                "e_load_mw": float(eload[t]),
                "mode": mode,
                "on": float(on),
                "start": float(_val(model.start[t])),
                "stop": float(_val(model.stop[t])),
                "temp_label": temp_label,
                "heat_seg": heat_seg,
                "power_seg": power_seg,
                "H_chp_mw": _val(model.H[t]),
                "E_chp_mw": _val(model.E[t]),
                "Q_in_mw": _val(model.Q[t]),
                "boiler_mw": _val(model.boiler[t]),
                "dump_mw": _val(model.dump[t]),
                "under_mw": _val(model.under[t]),
                "ch_mw": _val(model.ch[t]),
                "dis_mw": _val(model.dis[t]),
                "S_mwh": _val(model.S[t]),
                "S_next_mwh": _val(model.S[t + 1]),
                "grid_import_mw": _val(model.grid_import[t]),
                "grid_export_mw": _val(model.grid_export[t]),
                "pv_curt_mw": _val(model.pv_curt[t]),
                "chp_curt_mw": _val(model.chp_curt[t]),
            }
        )

    out = pd.DataFrame(rows)
    for c in ["start", "stop", "grid_import_mw"]:
        if c in out.columns:
            out[c] = out[c].clip(lower=0.0)

    heat_resid = (
        out["H_chp_mw"] + out["boiler_mw"] + out["dis_mw"]
        - out["ch_mw"] - out["dump_mw"] + out["under_mw"] - out["heat_demand_mw"]
    )
    elec_resid = (
        (out["E_chp_mw"] - out["chp_curt_mw"])
        + (out["pv_avail_mw"] - out["pv_curt_mw"])
        + out["grid_import_mw"] - out["grid_export_mw"] - out["e_load_mw"]
    )
    out["heat_balance_residual"] = heat_resid
    out["elec_balance_residual"] = elec_resid
    return out


def _solve_model(model: pyo.ConcreteModel, *, time_limit_s: float, mip_rel_gap: float, tee: bool) -> tuple[Any, float]:
    solver = pyo.SolverFactory("appsi_highs")
    solver = _configure_highs_solver(
        solver,
        time_limit_s=float(time_limit_s),
        mip_rel_gap=float(mip_rel_gap),
        output_flag=bool(tee),
    )
    t0 = time.perf_counter()
    results = solver.solve(model, tee=bool(tee))
    wallclock_s = time.perf_counter() - t0
    return results, wallclock_s


def _termination_ok(term: Any) -> bool:
    if term in (TerminationCondition.optimal, TerminationCondition.feasible):
        return True
    return "time" in str(term).lower()


def _update_run_state(prev_state: int, prev_len: int, on_impl: list[int]) -> tuple[int, int]:
    state_end = int(on_impl[-1])
    consec = 0
    for val in reversed(on_impl):
        if int(val) == state_end:
            consec += 1
        else:
            break
    if consec == len(on_impl) and state_end == int(prev_state):
        return state_end, int(prev_len) + len(on_impl)
    return state_end, consec


def _build_validation_report(
    dispatch: pd.DataFrame,
    *,
    cfg: ExperimentConfig,
    qc: QCSection,
    expected_terminal_soc: float | None,
) -> dict[str, Any]:
    tol = float(qc.residual_tol)
    bound_tol = float(qc.bound_tol)
    overlap_tol = float(qc.overlap_tol_mw)

    negative_cols = [
        "H_chp_mw",
        "E_chp_mw",
        "Q_in_mw",
        "boiler_mw",
        "dump_mw",
        "under_mw",
        "ch_mw",
        "dis_mw",
        "S_mwh",
        "S_next_mwh",
        "grid_import_mw",
        "grid_export_mw",
        "pv_curt_mw",
        "chp_curt_mw",
    ]

    negatives = {}
    for col in negative_cols:
        if col in dispatch.columns:
            min_val = float(dispatch[col].min())
            if min_val < -bound_tol:
                negatives[col] = min_val

    heat_resid_max = float(np.max(np.abs(dispatch["heat_balance_residual"]))) if len(dispatch) else 0.0
    elec_resid_max = float(np.max(np.abs(dispatch["elec_balance_residual"]))) if len(dispatch) else 0.0
    export_max = float(dispatch["grid_export_mw"].max()) if len(dispatch) else 0.0
    soc_min = float(min(dispatch["S_mwh"].min(), dispatch["S_next_mwh"].min())) if len(dispatch) else 0.0
    soc_max = float(max(dispatch["S_mwh"].max(), dispatch["S_next_mwh"].max())) if len(dispatch) else 0.0
    overlap_max = float(np.minimum(dispatch["grid_import_mw"], dispatch["grid_export_mw"]).max()) if len(dispatch) else 0.0

    terminal_soc = float(dispatch["S_next_mwh"].iloc[-1]) if len(dispatch) else None
    terminal_gap = None if expected_terminal_soc is None or terminal_soc is None else float(terminal_soc - expected_terminal_soc)

    issues: list[str] = []
    if heat_resid_max > tol:
        issues.append(f"Heat balance residual too large: {heat_resid_max:.6g} > {tol:.6g}")
    if elec_resid_max > tol:
        issues.append(f"Electric balance residual too large: {elec_resid_max:.6g} > {tol:.6g}")
    if export_max > float(cfg.grid.grid_export_cap_mw) + bound_tol:
        issues.append(
            "Grid export exceeds cap: "
            f"{export_max:.6g} > {float(cfg.grid.grid_export_cap_mw) + bound_tol:.6g}"
        )
    if soc_min < -bound_tol:
        issues.append(f"Storage SOC below zero: {soc_min:.6g}")
    if soc_max > float(cfg.storage.s_max_mwh) + bound_tol:
        issues.append(
            "Storage SOC exceeds upper bound: "
            f"{soc_max:.6g} > {float(cfg.storage.s_max_mwh) + bound_tol:.6g}"
        )
    if overlap_max > overlap_tol:
        issues.append(
            "Import/export overlap larger than tolerance: "
            f"{overlap_max:.6g} > {overlap_tol:.6g}"
        )
    if negatives:
        issues.append(f"Negative values found in non-negative columns: {negatives}")
    if terminal_gap is not None and abs(terminal_gap) > bound_tol:
        issues.append(
            "Terminal SOC mismatch: "
            f"{terminal_gap:.6g} away from target {expected_terminal_soc:.6g}"
        )

    return {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "pass": len(issues) == 0,
        "issues": issues,
        "thresholds": {
            "residual_tol": tol,
            "bound_tol": bound_tol,
            "overlap_tol_mw": overlap_tol,
        },
        "metrics": {
            "heat_balance_residual_abs_max": heat_resid_max,
            "elec_balance_residual_abs_max": elec_resid_max,
            "grid_export_max_mw": export_max,
            "soc_min_mwh": soc_min,
            "soc_max_mwh": soc_max,
            "import_export_overlap_max_mw": overlap_max,
            "terminal_soc_mwh": terminal_soc,
            "expected_terminal_soc_mwh": expected_terminal_soc,
            "terminal_soc_gap_mwh": terminal_gap,
            "negative_nonnegative_columns": negatives,
        },
    }


def _summary_row(summary: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    method = summary.get("method", "full_horizon_uc")
    if method == "rolling_horizon_mpc":
        achieved_gap = summary.get("solver", {}).get("achieved_gap_rel_max")
        wallclock = summary.get("solver", {}).get("wallclock_s_total")
    else:
        achieved_gap = summary.get("solver", {}).get("achieved_gap_rel")
        wallclock = summary.get("solver", {}).get("wallclock_s")

    totals = summary.get("totals", {})
    economics = summary.get("economics_realized", {})
    heat_total = float(totals.get("heat_demand_mwh", 0.0) or 0.0)
    boiler = float(totals.get("boiler_mwh", 0.0) or 0.0)
    dump = float(totals.get("dump_mwh", 0.0) or 0.0)
    chp_e_total = float(totals.get("E_chp_mwh", 0.0) or 0.0)
    chp_e_curt = float(totals.get("E_chp_curt_mwh", 0.0) or 0.0)

    return {
        "scenario": summary.get("scenario", {}).get("scenario"),
        "method": method,
        "tag": summary.get("tag"),
        "system_cost_realized": economics.get("system_cost_realized"),
        "profit_objective_realized": economics.get("profit_objective_realized"),
        "boiler_share_pct": (100.0 * boiler / heat_total if heat_total > 0 else None),
        "dump_share_pct": (100.0 * dump / heat_total if heat_total > 0 else None),
        "chp_curtailment_ratio_pct": (100.0 * chp_e_curt / chp_e_total if chp_e_total > 0 else None),
        "grid_export_mwh": totals.get("grid_export_mwh"),
        "grid_import_mwh": totals.get("grid_import_mwh"),
        "solver_gap": achieved_gap,
        "wallclock_s": wallclock,
        "validation_pass": validation.get("pass"),
    }


def _write_artifacts(
    *,
    cfg: ExperimentConfig,
    dispatch: pd.DataFrame,
    summary: dict[str, Any],
    windows_df: pd.DataFrame,
    validation: dict[str, Any],
    overwrite: bool = False,
) -> RunArtifacts:
    scen_dir = ROOT / "data" / "scenarios" / cfg.run.scenario
    out_dir = scen_dir / "results"
    dispatch_path, summary_path, windows_path, validation_path = experiment_artifact_paths(cfg)
    ensure_no_existing_paths(
        [dispatch_path, summary_path, windows_path, validation_path],
        context="experiment artifact",
        overwrite=overwrite,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    dispatch.to_parquet(dispatch_path, index=False, engine="pyarrow", compression="zstd")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    windows_df.to_csv(windows_path, index=False, encoding="utf-8-sig")
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")

    return RunArtifacts(
        dispatch_path=dispatch_path,
        summary_path=summary_path,
        windows_path=windows_path,
        validation_path=validation_path,
        summary=summary,
        validation=validation,
    )


def run_uc(cfg: ExperimentConfig, *, overwrite: bool = False) -> RunArtifacts:
    inputs = load_scenario_inputs(cfg)
    heat_seg, power_seg, temps = load_segments()
    terminal_target = _resolve_uc_terminal_target(cfg)
    meta = _build_meta(
        cfg,
        n_hours=len(inputs.dt_index),
        s_init_mwh=float(cfg.storage.s_init_mwh),
        on_init=int(cfg.commitment.on_init),
        time_limit_s=float(cfg.solver.time_limit_s),
        terminal_soc_target_mwh=terminal_target,
    )

    model = build_model(
        inputs.dt_index,
        inputs.heat_demand_mw,
        inputs.pv_avail_mw,
        inputs.e_load_mw,
        heat_seg,
        power_seg,
        temps,
        meta,
    )

    results, wallclock_s = _solve_model(
        model,
        time_limit_s=float(cfg.solver.time_limit_s),
        mip_rel_gap=float(cfg.solver.mip_rel_gap),
        tee=bool(cfg.solver.tee),
    )
    term = getattr(results.solver, "termination_condition", None)
    status = getattr(results.solver, "status", None)
    if not _termination_ok(term):
        raise RuntimeError(f"UC solve failed: status={status}, termination={term}")

    dispatch = _extract_dispatch_rows(
        model,
        dt_index=inputs.dt_index,
        demand=inputs.heat_demand_mw.to_numpy(dtype=float),
        pv_av=inputs.pv_avail_mw.to_numpy(dtype=float),
        eload=inputs.e_load_mw.to_numpy(dtype=float),
        n_take=len(inputs.dt_index),
    )

    try:
        obj_val = float(pyo.value(model.obj))
    except Exception:
        obj_val = float("nan")

    solver_diag = extract_solver_diagnostics(results, wallclock_s=wallclock_s, objective_value=obj_val)
    economics = compute_realized_economics(dispatch, meta, solver_objective=obj_val)

    summary = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "method": "full_horizon_uc",
        "tag": cfg.run.tag,
        "config_used": cfg.to_dict(),
        "scenario": asdict(meta),
        "solver": {
            "status": str(status),
            "termination": str(term),
            "objective_profit_like": obj_val,
            "objective_system_cost_equivalent": (-obj_val if math.isfinite(obj_val) else None),
            "wallclock_s": solver_diag.get("wallclock_s"),
            "reported_runtime_s": solver_diag.get("reported_runtime_s"),
            "achieved_gap_rel": solver_diag.get("achieved_gap_rel"),
            "best_feasible_objective": solver_diag.get("best_feasible_objective"),
            "best_objective_bound": solver_diag.get("best_objective_bound"),
            "message": solver_diag.get("message"),
        },
        "totals": {
            "heat_demand_mwh": float(dispatch["heat_demand_mw"].sum()),
            "H_chp_mwh": float(dispatch["H_chp_mw"].sum()),
            "E_chp_mwh": float(dispatch["E_chp_mw"].sum()),
            "Q_in_mwh": float(dispatch["Q_in_mw"].sum()),
            "boiler_mwh": float(dispatch["boiler_mw"].sum()),
            "dump_mwh": float(dispatch["dump_mw"].sum()),
            "under_mwh": float(dispatch["under_mw"].sum()),
            "pv_avail_mwh": float(dispatch["pv_avail_mw"].sum()),
            "pv_used_mwh": float((dispatch["pv_avail_mw"] - dispatch["pv_curt_mw"]).sum()),
            "pv_curt_mwh": float(dispatch["pv_curt_mw"].sum()),
            "E_chp_used_mwh": float((dispatch["E_chp_mw"] - dispatch["chp_curt_mw"]).sum()),
            "E_chp_curt_mwh": float(dispatch["chp_curt_mw"].sum()),
            "grid_import_mwh": float(dispatch["grid_import_mw"].sum()),
            "grid_export_mwh": float(dispatch["grid_export_mw"].sum()),
        },
        "qc": {
            "heat_balance_residual_abs_max": float(np.max(np.abs(dispatch["heat_balance_residual"]))),
            "elec_balance_residual_abs_max": float(np.max(np.abs(dispatch["elec_balance_residual"]))),
            "starts": int((dispatch["start"] > 0.5).sum()),
            "stops": int((dispatch["stop"] > 0.5).sum()),
            "hours_on": int((dispatch["on"] > 0.5).sum()),
            "hours_off": int((dispatch["on"] <= 0.5).sum()),
            "hours_export_at_cap": int((dispatch["grid_export_mw"] >= (float(cfg.grid.grid_export_cap_mw) - 1e-6)).sum()),
        },
        "economics_realized": economics,
    }

    validation = _build_validation_report(
        dispatch,
        cfg=cfg,
        qc=cfg.qc,
        expected_terminal_soc=terminal_target,
    )
    summary["validation"] = validation

    windows_df = pd.DataFrame(
        [
            {
                "window_id": 1,
                "global_start_idx": 0,
                "global_horizon_end": len(inputs.dt_index),
                "horizon_len": len(inputs.dt_index),
                "step_len": len(inputs.dt_index),
                "S0_mwh": float(cfg.storage.s_init_mwh),
                "S_boundary_mwh": float(dispatch["S_next_mwh"].iloc[-1]),
                "status": str(status),
                "termination": str(term),
                "objective_window": obj_val,
                "wallclock_s": solver_diag.get("wallclock_s"),
                "reported_runtime_s": solver_diag.get("reported_runtime_s"),
                "achieved_gap_rel": solver_diag.get("achieved_gap_rel"),
                "best_feasible_objective": solver_diag.get("best_feasible_objective"),
                "best_objective_bound": solver_diag.get("best_objective_bound"),
                "message": solver_diag.get("message"),
            }
        ]
    )

    return _write_artifacts(
        cfg=cfg,
        dispatch=dispatch,
        summary=summary,
        windows_df=windows_df,
        validation=validation,
        overwrite=overwrite,
    )


def run_mpc(cfg: ExperimentConfig, *, overwrite: bool = False) -> RunArtifacts:
    inputs = load_scenario_inputs(cfg)
    heat_seg, power_seg, temps = load_segments()
    N = len(inputs.dt_index)

    prev_state = int(cfg.commitment.on_init)
    prev_len = max(int(cfg.commitment.min_up_hours), int(cfg.commitment.min_down_hours))
    week_s0 = float(cfg.storage.s_init_mwh)
    current_s0 = float(cfg.storage.s_init_mwh)

    pieces: list[pd.DataFrame] = []
    windows: list[dict[str, Any]] = []
    starts = list(range(0, N, int(cfg.rolling.step_hours)))

    for window_id, start_idx in enumerate(starts, start=1):
        step_len = min(int(cfg.rolling.step_hours), N - start_idx)
        horizon_end = min(start_idx + int(cfg.rolling.horizon_hours), N)
        horizon_len = horizon_end - start_idx
        is_last = horizon_end == N

        dt = inputs.dt_index[start_idx:horizon_end]
        demand = inputs.heat_demand_mw.iloc[start_idx:horizon_end].reset_index(drop=True)
        pv_av = inputs.pv_avail_mw.iloc[start_idx:horizon_end].reset_index(drop=True)
        eload = inputs.e_load_mw.iloc[start_idx:horizon_end].reset_index(drop=True)

        must_on = 0
        must_off = 0
        if prev_state == 1:
            must_on = max(0, int(cfg.commitment.min_up_hours) - int(prev_len))
        else:
            must_off = max(0, int(cfg.commitment.min_down_hours) - int(prev_len))

        terminal_mode = cfg.rolling.window_terminal_soc_mode
        if is_last:
            terminal_mode = _resolve_last_window_terminal_mode(cfg)
        terminal_target = _resolve_window_terminal_target(
            mode=terminal_mode,
            current_s0=float(current_s0),
            week_s0=float(week_s0),
        )

        meta = _build_meta(
            cfg,
            n_hours=horizon_len,
            s_init_mwh=float(current_s0),
            on_init=int(prev_state),
            time_limit_s=float(cfg.solver.time_limit_s),
            terminal_soc_target_mwh=terminal_target,
        )

        model = build_model(dt, demand, pv_av, eload, heat_seg, power_seg, temps, meta)

        for t in range(min(must_on, horizon_len)):
            model.y_off[t].fix(0)
        for t in range(min(must_off, horizon_len)):
            model.y_off[t].fix(1)

        results, wallclock_s = _solve_model(
            model,
            time_limit_s=float(cfg.solver.time_limit_s),
            mip_rel_gap=float(cfg.solver.mip_rel_gap),
            tee=bool(cfg.solver.tee),
        )
        term = getattr(results.solver, "termination_condition", None)
        status = getattr(results.solver, "status", None)
        if not _termination_ok(term):
            raise RuntimeError(
                f"MPC window {window_id} failed: status={status}, termination={term}"
            )

        df_step = _extract_dispatch_rows(
            model,
            dt_index=dt,
            demand=demand.to_numpy(dtype=float),
            pv_av=pv_av.to_numpy(dtype=float),
            eload=eload.to_numpy(dtype=float),
            n_take=step_len,
        )
        df_step["window_id"] = window_id
        df_step["window_start_idx"] = start_idx
        pieces.append(df_step)

        try:
            obj_val = float(pyo.value(model.obj))
        except Exception:
            obj_val = float("nan")
        solver_diag = extract_solver_diagnostics(results, wallclock_s=wallclock_s, objective_value=obj_val)

        current_s0 = float(_val(model.S[step_len]))
        on_impl = [1 if _val(model.y_off[t]) < 0.5 else 0 for t in range(step_len)]
        prev_state, prev_len = _update_run_state(prev_state, prev_len, on_impl)

        windows.append(
            {
                "window_id": window_id,
                "global_start_idx": int(start_idx),
                "global_horizon_end": int(horizon_end),
                "horizon_len": int(horizon_len),
                "step_len": int(step_len),
                "S0_mwh": float(meta.s_init_mwh),
                "S_boundary_mwh": float(current_s0),
                "must_on": int(must_on),
                "must_off": int(must_off),
                "window_terminal_soc_mode": terminal_mode,
                "window_terminal_soc_target_mwh": terminal_target,
                "status": str(status),
                "termination": str(term),
                "objective_window": obj_val,
                "wallclock_s": solver_diag.get("wallclock_s"),
                "reported_runtime_s": solver_diag.get("reported_runtime_s"),
                "achieved_gap_rel": solver_diag.get("achieved_gap_rel"),
                "best_feasible_objective": solver_diag.get("best_feasible_objective"),
                "best_objective_bound": solver_diag.get("best_objective_bound"),
                "message": solver_diag.get("message"),
            }
        )

    dispatch = pd.concat(pieces, ignore_index=True).sort_values("datetime_local").reset_index(drop=True)
    windows_df = pd.DataFrame(windows)
    full_meta = _build_meta(
        cfg,
        n_hours=N,
        s_init_mwh=float(cfg.storage.s_init_mwh),
        on_init=int(cfg.commitment.on_init),
        time_limit_s=float(cfg.solver.time_limit_s),
        terminal_soc_target_mwh=_resolve_window_terminal_target(
            mode=_resolve_last_window_terminal_mode(cfg),
            current_s0=float(cfg.storage.s_init_mwh),
            week_s0=float(cfg.storage.s_init_mwh),
        ),
    )
    economics = compute_realized_economics(dispatch, full_meta, solver_objective=None)

    wallclock_vals = [float(x) for x in windows_df["wallclock_s"].dropna().tolist()] if not windows_df.empty else []
    runtime_vals = [float(x) for x in windows_df["reported_runtime_s"].dropna().tolist()] if not windows_df.empty else []
    gap_vals = [float(x) for x in windows_df["achieved_gap_rel"].dropna().tolist()] if not windows_df.empty else []
    term_counts = windows_df["termination"].value_counts(dropna=False).to_dict() if not windows_df.empty else {}
    window_objective_sum = float(np.nansum(windows_df["objective_window"].to_numpy(dtype=float))) if not windows_df.empty else float("nan")

    final_mode = _resolve_last_window_terminal_mode(cfg)
    expected_terminal = _resolve_window_terminal_target(
        mode=final_mode,
        current_s0=float(cfg.storage.s_init_mwh),
        week_s0=float(cfg.storage.s_init_mwh),
    )
    validation = _build_validation_report(
        dispatch,
        cfg=cfg,
        qc=cfg.qc,
        expected_terminal_soc=expected_terminal,
    )

    summary = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "method": "rolling_horizon_mpc",
        "tag": cfg.run.tag,
        "config_used": cfg.to_dict(),
        "rolling": {
            "horizon_hours": int(cfg.rolling.horizon_hours),
            "step_hours": int(cfg.rolling.step_hours),
            "window_terminal_soc_mode": cfg.rolling.window_terminal_soc_mode,
            "final_window_terminal_soc_mode": cfg.rolling.final_window_terminal_soc_mode,
        },
        "scenario": asdict(full_meta),
        "windows": windows,
        "solver": {
            "objective_profit_like": float(economics["profit_objective_realized"]),
            "objective_system_cost_equivalent": float(economics["system_cost_realized"]),
            "objective_window_sum_profit_like": float(window_objective_sum),
            "objective_window_sum_not_comparable": True,
            "wallclock_s_total": (float(sum(wallclock_vals)) if wallclock_vals else None),
            "reported_runtime_s_total": (float(sum(runtime_vals)) if runtime_vals else None),
            "achieved_gap_rel_max": (float(max(gap_vals)) if gap_vals else None),
            "achieved_gap_rel_mean": (float(sum(gap_vals) / len(gap_vals)) if gap_vals else None),
            "window_termination_counts": term_counts,
        },
        "totals": {
            "heat_demand_mwh": float(dispatch["heat_demand_mw"].sum()),
            "H_chp_mwh": float(dispatch["H_chp_mw"].sum()),
            "E_chp_mwh": float(dispatch["E_chp_mw"].sum()),
            "Q_in_mwh": float(dispatch["Q_in_mw"].sum()),
            "boiler_mwh": float(dispatch["boiler_mw"].sum()),
            "dump_mwh": float(dispatch["dump_mw"].sum()),
            "under_mwh": float(dispatch["under_mw"].sum()),
            "pv_avail_mwh": float(dispatch["pv_avail_mw"].sum()),
            "pv_used_mwh": float((dispatch["pv_avail_mw"] - dispatch["pv_curt_mw"]).sum()),
            "pv_curt_mwh": float(dispatch["pv_curt_mw"].sum()),
            "E_chp_used_mwh": float((dispatch["E_chp_mw"] - dispatch["chp_curt_mw"]).sum()),
            "E_chp_curt_mwh": float(dispatch["chp_curt_mw"].sum()),
            "grid_import_mwh": float(dispatch["grid_import_mw"].sum()),
            "grid_export_mwh": float(dispatch["grid_export_mw"].sum()),
        },
        "qc": {
            "heat_balance_residual_abs_max": float(np.max(np.abs(dispatch["heat_balance_residual"]))),
            "elec_balance_residual_abs_max": float(np.max(np.abs(dispatch["elec_balance_residual"]))),
            "starts": int((dispatch["start"] > 0.5).sum()),
            "stops": int((dispatch["stop"] > 0.5).sum()),
            "hours_on": int((dispatch["on"] > 0.5).sum()),
            "hours_off": int((dispatch["on"] <= 0.5).sum()),
            "hours_export_at_cap": int((dispatch["grid_export_mw"] >= (float(cfg.grid.grid_export_cap_mw) - 1e-6)).sum()),
        },
        "economics_realized": economics,
        "validation": validation,
    }

    return _write_artifacts(
        cfg=cfg,
        dispatch=dispatch,
        summary=summary,
        windows_df=windows_df,
        validation=validation,
        overwrite=overwrite,
    )


def run_experiment(cfg: ExperimentConfig, *, overwrite: bool = False) -> RunArtifacts:
    ensure_dirs()
    cfg.validate()
    ensure_no_existing_paths(
        experiment_artifact_paths(cfg),
        context="experiment artifact",
        overwrite=overwrite,
    )
    if cfg.run.method == "uc":
        artifacts = run_uc(cfg, overwrite=overwrite)
    elif cfg.run.method == "mpc":
        artifacts = run_mpc(cfg, overwrite=overwrite)
    else:
        raise ValueError(f"Unsupported method: {cfg.run.method}")

    if bool(cfg.qc.fail_on_violation) and not bool(artifacts.validation.get("pass")):
        raise RuntimeError(
            "Run finished but validation failed. See validation JSON for details: "
            f"{artifacts.validation_path}"
        )
    return artifacts


def build_batch_row(artifacts: RunArtifacts) -> dict[str, Any]:
    return _summary_row(artifacts.summary, artifacts.validation)
