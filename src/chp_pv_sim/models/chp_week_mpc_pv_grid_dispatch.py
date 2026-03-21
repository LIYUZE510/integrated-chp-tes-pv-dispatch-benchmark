from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from chp_pv_sim.paths import ROOT, ensure_dirs
from chp_pv_sim.models.chp_week_storage_pv_grid_dispatch import (
    Meta,
    load_segments,
    build_model,
    compute_realized_economics,
)
from chp_pv_sim.models.solver_metrics import extract_solver_diagnostics


def _val(x) -> float:
    return float(pyo.value(x))


def _to_float_series(s: pd.Series, name: str) -> pd.Series:
    out = pd.to_numeric(s, errors="raise").astype(float)
    if out.isna().any():
        raise ValueError(f"{name} has NaNs after numeric conversion.")
    return out


def _configure_highs_solver(solver, *, time_limit_s: float, mip_rel_gap: float, output_flag: bool):
    for attr in ("options", "highs_options"):
        opts = getattr(solver, attr, None)
        if opts is not None:
            try:
                opts["time_limit"] = float(time_limit_s)
            except Exception:
                pass
            try:
                opts["mip_rel_gap"] = float(mip_rel_gap)
            except Exception:
                pass
            try:
                opts["output_flag"] = bool(output_flag)
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


def _backup_if_exists(path: Path) -> None:
    if path.exists():
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = path.with_name(f"{path.stem}__backup_{ts}{path.suffix}")
        path.rename(bak)
        print(f"[backup] {path.name} -> {bak.name}", flush=True)


def _ok_termination(term: Any) -> bool:
    if term in (TerminationCondition.optimal, TerminationCondition.feasible):
        return True
    s = str(term).lower()
    return "time" in s


def _extract_rows(
    m: pyo.ConcreteModel,
    dt_index: pd.DatetimeIndex,
    demand: np.ndarray,
    pv_av: np.ndarray,
    eload: np.ndarray,
    n_take: int,
) -> pd.DataFrame:
    rows = []
    temps = list(m.TEMP)

    for t in range(n_take):
        yoff = _val(m.y_off[t])
        on = 1.0 - yoff

        if yoff > 0.5:
            mode = "OFF"
            temp = None
        else:
            mode = "ON"
            temp_vals = {tt: _val(m.y[t, tt]) for tt in temps}
            temp = max(temp_vals, key=temp_vals.get)

        hs = None
        es = None
        if mode == "ON":
            for (tt, s) in m.HS:
                if _val(m.zH[t, (tt, s)]) > 0.5:
                    hs = int(s)
                    break
            for (tt, s) in m.ES:
                if _val(m.zE[t, (tt, s)]) > 0.5:
                    es = int(s)
                    break

        rows.append(
            {
                "datetime_local": dt_index[t],
                "heat_demand_mw": float(demand[t]),
                "pv_avail_mw": float(pv_av[t]),
                "e_load_mw": float(eload[t]),
                "mode": mode,
                "on": float(on),
                "start": float(_val(m.start[t])),
                "stop": float(_val(m.stop[t])),
                "temp_label": temp,
                "heat_seg": hs,
                "power_seg": es,
                "H_chp_mw": _val(m.H[t]),
                "E_chp_mw": _val(m.E[t]),
                "Q_in_mw": _val(m.Q[t]),
                "boiler_mw": _val(m.boiler[t]),
                "dump_mw": _val(m.dump[t]),
                "under_mw": _val(m.under[t]),
                "ch_mw": _val(m.ch[t]),
                "dis_mw": _val(m.dis[t]),
                "S_mwh": _val(m.S[t]),
                "S_next_mwh": _val(m.S[t + 1]),
                "grid_import_mw": _val(m.grid_import[t]),
                "grid_export_mw": _val(m.grid_export[t]),
                "pv_curt_mw": _val(m.pv_curt[t]),
                "chp_curt_mw": _val(m.chp_curt[t]),
            }
        )

    df = pd.DataFrame(rows)
    for c in ["start", "stop", "grid_import_mw"]:
        if c in df.columns:
            df[c] = df[c].clip(lower=0.0)

    heat_resid = (
        df["H_chp_mw"] + df["boiler_mw"] + df["dis_mw"]
        - df["ch_mw"] - df["dump_mw"] + df["under_mw"] - df["heat_demand_mw"]
    )
    elec_resid = (
        (df["E_chp_mw"] - df["chp_curt_mw"])
        + (df["pv_avail_mw"] - df["pv_curt_mw"])
        + df["grid_import_mw"] - df["grid_export_mw"] - df["e_load_mw"]
    )
    df["heat_balance_residual"] = heat_resid
    df["elec_balance_residual"] = elec_resid
    return df


def _update_run_state(prev_state: int, prev_len: int, on_impl: list[int]) -> tuple[int, int]:
    """
    prev_state: on/off at hour (start_idx-1)
    prev_len  : consecutive hours in that state ending at (start_idx-1)
    on_impl   : on/off for implemented hours in this step
    returns: state_end, len_end
    """
    assert len(on_impl) > 0
    state_end = int(on_impl[-1])

    consec = 0
    for v in reversed(on_impl):
        if int(v) == state_end:
            consec += 1
        else:
            break

    if consec == len(on_impl) and state_end == int(prev_state):
        return state_end, int(prev_len) + len(on_impl)

    return state_end, consec


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--tag", required=True, help="e.g. mpc_paper_retained_fw")

    # rolling horizon
    ap.add_argument("--horizon", type=int, default=48, help="look-ahead horizon (hours)")
    ap.add_argument("--step", type=int, default=24, help="receding step (hours)")
    ap.add_argument(
        "--time-limit-window", "--time_limit_window", "--time-limit-s", "--time_limit_s",
        dest="time_limit_window",
        type=float,
        default=120.0,
        help="seconds per MPC window",
    )
    ap.add_argument(
        "--mip-rel-gap", "--mip_rel_gap",
        dest="mip_rel_gap",
        type=float,
        default=0.20,
        help="relative MIP gap target per window",
    )
    ap.add_argument("--tee", action="store_true")

    # storage
    ap.add_argument("--s_max", type=float, default=800.0)
    ap.add_argument("--p_ch_max", type=float, default=200.0)
    ap.add_argument("--p_dis_max", type=float, default=200.0)
    ap.add_argument("--eta_ch", type=float, default=0.95)
    ap.add_argument("--eta_dis", type=float, default=0.95)
    ap.add_argument("--loss_per_hour", type=float, default=0.001)
    ap.add_argument("--s_init", type=float, default=200.0)

    # grid + pv
    ap.add_argument("--grid_export_cap", type=float, default=60.0)
    ap.add_argument("--price_sell", type=float, default=50.0)
    ap.add_argument("--price_buy", type=float, default=70.0)
    ap.add_argument("--pv_scale", type=float, default=1.0)
    ap.add_argument("--e_load_base", type=float, default=20.0)
    ap.add_argument("--e_load_alpha", type=float, default=0.0)
    ap.add_argument("--penalty_pv_curt", type=float, default=0.1)
    ap.add_argument("--penalty_chp_curt", type=float, default=0.0)

    # costs
    ap.add_argument("--cost_q", type=float, default=15.0)
    ap.add_argument("--cost_boiler", type=float, default=60.0)
    ap.add_argument("--cost_dump", type=float, default=50.0)
    ap.add_argument("--penalty_under", type=float, default=1e6)
    ap.add_argument("--cycle_cost", type=float, default=0.01)

    # UC-like anti-chatter
    ap.add_argument("--startup_cost", type=float, default=5000.0)
    ap.add_argument("--shutdown_cost", type=float, default=0.0)
    ap.add_argument("--min_up", type=int, default=3)
    ap.add_argument("--min_down", type=int, default=2)
    ap.add_argument("--on_init", type=int, default=0, choices=[0, 1])

    args = ap.parse_args()

    if args.horizon < args.step:
        raise ValueError("Require horizon >= step (e.g., 48/24).")

    scen_dir = ROOT / "data" / "scenarios" / args.scenario
    heat_path = scen_dir / "heat.parquet"
    pv_path = scen_dir / "pv.parquet"
    if not heat_path.exists():
        raise FileNotFoundError(f"Missing: {heat_path}")
    if not pv_path.exists():
        raise FileNotFoundError(f"Missing: {pv_path}")

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
                "PV and heat time indexes do not align.\n"
                f"heat rows={len(heat_df)}, pv rows={len(pv_df)}, merged rows={len(merged)}"
            )
        heat_df = merged
    else:
        heat_df["pv_ac_mw"] = pv_df["pv_ac_mw"].astype(float)

    dt_full = pd.DatetimeIndex(heat_df["datetime_local"])
    demand_full = _to_float_series(heat_df["heat_demand_mw"], "heat_demand_mw").to_numpy()
    pv_full = (_to_float_series(heat_df["pv_ac_mw"], "pv_ac_mw") * float(args.pv_scale)).clip(lower=0.0).to_numpy()
    eload_full = (float(args.e_load_base) + float(args.e_load_alpha) * demand_full).clip(min=0.0)

    N = len(dt_full)

    heat_seg, power_seg, temps = load_segments()

    # rolling state before current window start
    prev_state = int(args.on_init)
    prev_len = max(int(args.min_up), int(args.min_down))

    # storage state at window start
    s0 = float(args.s_init)
    s_week_init = float(args.s_init)

    pieces: list[pd.DataFrame] = []
    windows: list[dict[str, Any]] = []

    starts = list(range(0, N, int(args.step)))

    for w, start_idx in enumerate(starts, start=1):
        step_len = min(int(args.step), N - start_idx)
        horizon_end = min(start_idx + int(args.horizon), N)
        horizon_len = horizon_end - start_idx

        dt = dt_full[start_idx:horizon_end]
        demand = demand_full[start_idx:horizon_end].astype(float)
        pv_av = pv_full[start_idx:horizon_end].astype(float)
        eload = eload_full[start_idx:horizon_end].astype(float)

        is_last = horizon_end == N

        prev_state_before = int(prev_state)
        prev_len_before = int(prev_len)

        must_on = 0
        must_off = 0
        if prev_state_before == 1:
            must_on = max(0, int(args.min_up) - int(prev_len_before))
        else:
            must_off = max(0, int(args.min_down) - int(prev_len_before))

        print(
            f"\n[window {w}/{len(starts)}] global[{start_idx}:{horizon_end}) "
            f"horizon={horizon_len} step={step_len} "
            f"S0={s0:.3f} on_init(prev)={prev_state_before} run_len(prev)={prev_len_before} "
            f"must_on={must_on} must_off={must_off} last={is_last}",
            flush=True,
        )

        meta = Meta(
            scenario=args.scenario,
            n_hours=horizon_len,
            storage_s_max_mwh=float(args.s_max),
            storage_p_ch_max_mw=float(args.p_ch_max),
            storage_p_dis_max_mw=float(args.p_dis_max),
            eta_ch=float(args.eta_ch),
            eta_dis=float(args.eta_dis),
            loss_per_hour=float(args.loss_per_hour),
            s_init_mwh=float(s0),
            grid_export_cap_mw=float(args.grid_export_cap),
            price_sell=float(args.price_sell),
            price_buy=float(args.price_buy),
            pv_scale=float(args.pv_scale),
            e_load_base_mw=float(args.e_load_base),
            e_load_alpha_per_heat=float(args.e_load_alpha),
            penalty_pv_curt=float(args.penalty_pv_curt),
            penalty_chp_curt=float(args.penalty_chp_curt),
            cost_q=float(args.cost_q),
            cost_boiler=float(args.cost_boiler),
            cost_dump=float(args.cost_dump),
            penalty_under=float(args.penalty_under),
            cycle_cost=float(args.cycle_cost),
            startup_cost=float(args.startup_cost),
            shutdown_cost=float(args.shutdown_cost),
            min_up_hours=int(args.min_up),
            min_down_hours=int(args.min_down),
            on_init=int(prev_state_before),
            time_limit_s=float(args.time_limit_window),
            mip_rel_gap=float(args.mip_rel_gap),
            tee=bool(args.tee),
            terminal_soc_target_mwh=float(s0),
        )

        m = build_model(dt, pd.Series(demand), pd.Series(pv_av), pd.Series(eload), heat_seg, power_seg, temps, meta)

        # last window: enforce end SOC back to week initial
        if is_last:
            m.Send.deactivate()
            m.Send_target = pyo.Constraint(expr=m.S[horizon_len] == s_week_init)

        # enforce UC obligations at beginning of window
        for t in range(min(must_on, horizon_len)):
            m.y_off[t].fix(0)
        for t in range(min(must_off, horizon_len)):
            m.y_off[t].fix(1)

        solver = pyo.SolverFactory("appsi_highs")
        solver = _configure_highs_solver(
            solver,
            time_limit_s=float(args.time_limit_window),
            mip_rel_gap=float(args.mip_rel_gap),
            output_flag=bool(args.tee),
        )

        _solve_t0 = time.perf_counter()
        res = solver.solve(m, tee=bool(args.tee))
        _solve_wall_s = time.perf_counter() - _solve_t0
        term = getattr(res.solver, "termination_condition", None)
        status = getattr(res.solver, "status", None)

        print(f"[window {w}] status={status} term={term}", flush=True)

        if not _ok_termination(term):
            raise RuntimeError(f"Window {w} failed: status={status}, term={term}")

        df_step = _extract_rows(m, dt, demand, pv_av, eload, step_len)
        df_step["window_id"] = w
        df_step["window_start_idx"] = start_idx
        pieces.append(df_step)

        s0 = float(_val(m.S[step_len]))

        on_impl = [1 if _val(m.y_off[t]) < 0.5 else 0 for t in range(step_len)]
        prev_state, prev_len = _update_run_state(prev_state_before, prev_len_before, on_impl)

        try:
            obj = float(pyo.value(m.obj))
        except Exception:
            obj = float("nan")

        solver_diag = extract_solver_diagnostics(res, wallclock_s=_solve_wall_s, objective_value=obj)

        windows.append(
            {
                "window_id": w,
                "global_start_idx": int(start_idx),
                "global_horizon_end": int(horizon_end),
                "horizon_len": int(horizon_len),
                "step_len": int(step_len),
                "S0_mwh": float(meta.s_init_mwh),
                "S_boundary_mwh": float(s0),
                "on_init_prev": int(prev_state_before),
                "run_len_prev": int(prev_len_before),
                "run_state_end": int(prev_state),
                "run_len_end": int(prev_len),
                "must_on": int(must_on),
                "must_off": int(must_off),
                "status": str(status),
                "termination": str(term),
                "objective_window": obj,
                "wallclock_s": solver_diag.get("wallclock_s"),
                "reported_runtime_s": solver_diag.get("reported_runtime_s"),
                "achieved_gap_rel": solver_diag.get("achieved_gap_rel"),
                "best_feasible_objective": solver_diag.get("best_feasible_objective"),
                "best_objective_bound": solver_diag.get("best_objective_bound"),
                "message": solver_diag.get("message"),
            }
        )

    out = pd.concat(pieces, ignore_index=True)
    out = out.sort_values("datetime_local").reset_index(drop=True)

    # recompute QC on stitched output
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

    meta_full = Meta(
        scenario=args.scenario,
        n_hours=int(N),
        storage_s_max_mwh=float(args.s_max),
        storage_p_ch_max_mw=float(args.p_ch_max),
        storage_p_dis_max_mw=float(args.p_dis_max),
        eta_ch=float(args.eta_ch),
        eta_dis=float(args.eta_dis),
        loss_per_hour=float(args.loss_per_hour),
        s_init_mwh=float(args.s_init),
        grid_export_cap_mw=float(args.grid_export_cap),
        price_sell=float(args.price_sell),
        price_buy=float(args.price_buy),
        pv_scale=float(args.pv_scale),
        e_load_base_mw=float(args.e_load_base),
        e_load_alpha_per_heat=float(args.e_load_alpha),
        penalty_pv_curt=float(args.penalty_pv_curt),
        penalty_chp_curt=float(args.penalty_chp_curt),
        cost_q=float(args.cost_q),
        cost_boiler=float(args.cost_boiler),
        cost_dump=float(args.cost_dump),
        penalty_under=float(args.penalty_under),
        cycle_cost=float(args.cycle_cost),
        startup_cost=float(args.startup_cost),
        shutdown_cost=float(args.shutdown_cost),
        min_up_hours=int(args.min_up),
        min_down_hours=int(args.min_down),
        on_init=int(args.on_init),
        time_limit_s=float(args.time_limit_window),
        mip_rel_gap=float(args.mip_rel_gap),
        tee=bool(args.tee),
    )

    economics = compute_realized_economics(out, meta_full, solver_objective=None)
    window_objective_sum = float(np.nansum([w["objective_window"] for w in windows])) if len(windows) else float("nan")

    wallclock_vals = [float(w["wallclock_s"]) for w in windows if w.get("wallclock_s") is not None]
    reported_runtime_vals = [float(w["reported_runtime_s"]) for w in windows if w.get("reported_runtime_s") is not None]
    gap_vals = [float(w["achieved_gap_rel"]) for w in windows if w.get("achieved_gap_rel") is not None]
    term_counts = {}
    for w in windows:
        key = str(w.get("termination"))
        term_counts[key] = term_counts.get(key, 0) + 1

    summary = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "method": "rolling_horizon_mpc",
        "rolling": {
            "horizon_hours": int(args.horizon),
            "step_hours": int(args.step),
            "time_limit_window_s": float(args.time_limit_window),
        },
        "scenario": asdict(meta_full),
        "windows": windows,
        "solver": {
            "objective_profit_like": float(economics["profit_objective_realized"]),
            "objective_system_cost_equivalent": float(economics["system_cost_realized"]),
            "objective_implemented": float(economics["profit_objective_realized"]),
            "objective_window_sum_profit_like": float(window_objective_sum),
            "objective_window_sum": float(window_objective_sum),
            "objective_window_sum_not_comparable": True,
            "wallclock_s_total": (float(sum(wallclock_vals)) if wallclock_vals else None),
            "reported_runtime_s_total": (float(sum(reported_runtime_vals)) if reported_runtime_vals else None),
            "achieved_gap_rel_max": (float(max(gap_vals)) if gap_vals else None),
            "achieved_gap_rel_mean": (float(sum(gap_vals)/len(gap_vals)) if gap_vals else None),
            "window_termination_counts": term_counts,
        },
        "totals": {
            "heat_demand_mwh": float(out["heat_demand_mw"].sum()),
            "H_chp_mwh": float(out["H_chp_mw"].sum()),
            "E_chp_mwh": float(out["E_chp_mw"].sum()),
            "Q_in_mwh": float(out["Q_in_mw"].sum()),
            "boiler_mwh": float(out["boiler_mw"].sum()),
            "dump_mwh": float(out["dump_mw"].sum()),
            "under_mwh": float(out["under_mw"].sum()),
            "pv_avail_mwh": float(out["pv_avail_mw"].sum()),
            "pv_used_mwh": float((out["pv_avail_mw"] - out["pv_curt_mw"]).sum()),
            "pv_curt_mwh": float(out["pv_curt_mw"].sum()),
            "E_chp_used_mwh": float((out["E_chp_mw"] - out["chp_curt_mw"]).sum()),
            "E_chp_curt_mwh": float(out["chp_curt_mw"].sum()),
            "grid_import_mwh": float(out["grid_import_mw"].sum()),
            "grid_export_mwh": float(out["grid_export_mw"].sum()),
        },
        "qc": {
            "heat_balance_residual_abs_max": float(np.max(np.abs(heat_resid))),
            "elec_balance_residual_abs_max": float(np.max(np.abs(elec_resid))),
            "starts": int((out["start"] > 0.5).sum()),
            "stops": int((out["stop"] > 0.5).sum()),
            "hours_on": int((out["on"] > 0.5).sum()),
            "hours_off": int((out["on"] <= 0.5).sum()),
            "hours_export_at_cap": int((out["grid_export_mw"] >= (float(args.grid_export_cap) - 1e-6)).sum()),
        },
        "economics_realized": economics,
    }

    out_dir = scen_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    dispatch_path = out_dir / f"dispatch_chp_storage_pv_grid__{args.tag}.parquet"
    summary_path = out_dir / f"dispatch_summary_pv_grid__{args.tag}.json"

    out.to_parquet(dispatch_path, index=False, engine="pyarrow", compression="zstd")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nWrote results :", dispatch_path)
    print("Wrote summary :", summary_path)
    print("\n=== MPC QUICK QC ===")
    print(json.dumps(summary["qc"], ensure_ascii=False, indent=2))
    print("\n=== MPC QUICK TOTALS ===")
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    print("\n=== MPC REALIZED ECONOMICS ===")
    print(json.dumps(summary["economics_realized"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()