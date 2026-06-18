from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pyomo.environ as pyo

from chp_pv_sim.experiments.config import load_experiment_config
from chp_pv_sim.experiments.engine import (
    _build_meta,
    _configure_highs_solver,
    _resolve_uc_terminal_target,
    load_scenario_inputs,
)
from chp_pv_sim.models.chp_week_storage_pv_grid_dispatch import build_model, load_segments
from chp_pv_sim.paths import ROOT


SCENARIO = "week_2023_dec01_anchor24h_fw"
TIGHTENED_TAGS = {
    60: "resub_2026_tightened_uc_anchor24h_gap0p002_t60",
    300: "resub_2026_tightened_uc_anchor24h_gap0p002_t300",
    900: "resub_2026_tightened_uc_anchor24h_gap0p002_t900",
}
CONFIG_PATH = (
    ROOT
    / "configs"
    / "experiments"
    / "resubmission_2026"
    / "solver_budget"
    / "resub_2026_tightened_uc_anchor24h_gap0p002_t900.yaml"
)
RESULTS_DIR = ROOT / "data" / "scenarios" / SCENARIO / "results"
DOC_PATH = ROOT / "docs" / "lp_relaxation_anatomy_24h.md"
TOL = 1.0e-6


def _summary_path(tag: str) -> Path:
    return RESULTS_DIR / f"dispatch_summary_pv_grid__{tag}.json"


def _dispatch_path(tag: str) -> Path:
    return RESULTS_DIR / f"dispatch_chp_storage_pv_grid__{tag}.parquet"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _value(obj: Any) -> float:
    return float(pyo.value(obj))


def build_tightened_model() -> tuple[pyo.ConcreteModel, Any, Any, Any, pd.DataFrame, pd.DataFrame]:
    cfg = load_experiment_config(CONFIG_PATH)
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
    return model, cfg, inputs, meta, heat_seg, power_seg


def relax_discrete_variables(model: pyo.ConcreteModel) -> dict[str, int]:
    relaxed_binary = 0
    relaxed_integer = 0
    for var_data in model.component_data_objects(pyo.Var, descend_into=True):
        if var_data.is_binary():
            var_data.domain = pyo.UnitInterval
            relaxed_binary += 1
        elif var_data.is_integer():
            var_data.domain = pyo.Reals
            relaxed_integer += 1
    return {"relaxed_binary": relaxed_binary, "relaxed_integer": relaxed_integer}


def solve_model(model: pyo.ConcreteModel, *, time_limit_s: float) -> dict[str, Any]:
    solver = pyo.SolverFactory("appsi_highs")
    solver = _configure_highs_solver(
        solver,
        time_limit_s=float(time_limit_s),
        mip_rel_gap=0.0,
        output_flag=False,
    )
    t0 = time.perf_counter()
    results = solver.solve(model, tee=False)
    runtime_s = time.perf_counter() - t0
    return {
        "status": str(getattr(results.solver, "status", None)),
        "termination": str(getattr(results.solver, "termination_condition", None)),
        "runtime_s": runtime_s,
        "objective": _value(model.obj),
    }


def _fractional_distance(value: float) -> float:
    return min(abs(value), abs(1.0 - value))


def _timestamp(index: Any, inputs: Any) -> str | None:
    first = index[0] if isinstance(index, tuple) else index
    if isinstance(first, int) and 0 <= first < len(inputs.dt_index):
        return str(inputs.dt_index[first])
    return None


def _index_text(index: Any) -> str:
    if index is None:
        return ""
    if isinstance(index, tuple):
        return ",".join(str(part) for part in index)
    return str(index)


def _component_fractional_summary(
    model: pyo.ConcreteModel,
    inputs: Any,
    *,
    label: str,
    component_name: str | None,
    absent_reason: str | None = None,
) -> dict[str, Any]:
    if component_name is None or not hasattr(model, component_name):
        return {
            "family": label,
            "component": component_name,
            "count": 0,
            "fractional_count": 0,
            "min_value": None,
            "max_value": None,
            "fractional_distance_sum": 0.0,
            "fractional_distance_mean": None,
            "most_fractional": [],
            "status": absent_reason or "absent",
        }

    comp = getattr(model, component_name)
    rows: list[dict[str, Any]] = []
    values: list[float] = []
    for index, var_data in comp.items():
        val = _value(var_data)
        dist = _fractional_distance(val)
        values.append(val)
        rows.append(
            {
                "name": var_data.name,
                "index": _index_text(index),
                "timestamp": _timestamp(index, inputs),
                "value": val,
                "fractional_distance": dist,
            }
        )
    fractional = [row for row in rows if row["fractional_distance"] > TOL]
    top = sorted(fractional, key=lambda row: row["fractional_distance"], reverse=True)[:8]
    return {
        "family": label,
        "component": component_name,
        "count": len(rows),
        "fractional_count": len(fractional),
        "min_value": min(values) if values else None,
        "max_value": max(values) if values else None,
        "fractional_distance_sum": sum(row["fractional_distance"] for row in rows),
        "fractional_distance_mean": (
            sum(row["fractional_distance"] for row in rows) / len(rows) if rows else None
        ),
        "most_fractional": top,
        "status": "present",
    }


def discrete_family_table(model: pyo.ConcreteModel, inputs: Any) -> list[dict[str, Any]]:
    return [
        _component_fractional_summary(model, inputs, label="CHP off selector y_off (on=1-y_off)", component_name="y_off"),
        _component_fractional_summary(model, inputs, label="CHP startup start", component_name="start"),
        _component_fractional_summary(model, inputs, label="CHP shutdown stop", component_name="stop"),
        _component_fractional_summary(model, inputs, label="CHP operating temperature modes y", component_name="y"),
        _component_fractional_summary(model, inputs, label="CHP heat segment selectors zH", component_name="zH"),
        _component_fractional_summary(model, inputs, label="CHP power segment selectors zE", component_name="zE"),
        _component_fractional_summary(
            model,
            inputs,
            label="Grid import/export direction",
            component_name=None,
            absent_reason="absent: current model has no grid-direction binary variable",
        ),
        _component_fractional_summary(model, inputs, label="Storage charge direction u_ch", component_name="u_ch"),
    ]


def _time_rows(model: pyo.ConcreteModel, inputs: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in model.TIME:
        y_vals = {str(tt): _value(model.y[t, tt]) for tt in model.TEMP}
        zh_vals = {f"{tt}:{s}": _value(model.zH[t, (tt, s)]) for (tt, s) in model.HS}
        ze_vals = {f"{tt}:{s}": _value(model.zE[t, (tt, s)]) for (tt, s) in model.ES}
        rows.append(
            {
                "t": int(t),
                "timestamp": str(inputs.dt_index[int(t)]),
                "y_off": _value(model.y_off[t]),
                "on": 1.0 - _value(model.y_off[t]),
                "start": _value(model.start[t]),
                "stop": _value(model.stop[t]),
                "u_ch": _value(model.u_ch[t]),
                "grid_import": _value(model.grid_import[t]),
                "grid_export": _value(model.grid_export[t]),
                "grid_overlap": min(_value(model.grid_import[t]), _value(model.grid_export[t])),
                "ch": _value(model.ch[t]),
                "dis": _value(model.dis[t]),
                "storage_overlap": min(_value(model.ch[t]), _value(model.dis[t])),
                "chp_curt": _value(model.chp_curt[t]),
                "pv_curt": _value(model.pv_curt[t]),
                "dump": _value(model.dump[t]),
                "under": _value(model.under[t]),
                "mode_positive_count": sum(1 for value in y_vals.values() if value > TOL),
                "mode_fractional_count": sum(1 for value in y_vals.values() if _fractional_distance(value) > TOL),
                "heat_segment_positive_count": sum(1 for value in zh_vals.values() if value > TOL),
                "heat_segment_fractional_count": sum(
                    1 for value in zh_vals.values() if _fractional_distance(value) > TOL
                ),
                "power_segment_positive_count": sum(1 for value in ze_vals.values() if value > TOL),
                "power_segment_fractional_count": sum(
                    1 for value in ze_vals.values() if _fractional_distance(value) > TOL
                ),
                "largest_modes": sorted(y_vals.items(), key=lambda item: item[1], reverse=True)[:4],
                "largest_heat_segments": sorted(zh_vals.items(), key=lambda item: item[1], reverse=True)[:6],
                "largest_power_segments": sorted(ze_vals.items(), key=lambda item: item[1], reverse=True)[:6],
            }
        )
    return rows


def nonphysical_lp_metrics(model: pyo.ConcreteModel, inputs: Any) -> dict[str, Any]:
    rows = _time_rows(model, inputs)

    def top_by(key: str, limit: int = 6) -> list[dict[str, Any]]:
        return [
            row
            for row in sorted(rows, key=lambda item: float(item[key]), reverse=True)[:limit]
            if float(row[key]) > TOL
        ]

    fractional_commitment_hours = [
        row
        for row in rows
        if _fractional_distance(row["y_off"]) > TOL
        or _fractional_distance(row["start"]) > TOL
        or _fractional_distance(row["stop"]) > TOL
    ]
    curtail_fractional_off = [
        row
        for row in rows
        if row["chp_curt"] > TOL and row["y_off"] > TOL and row["y_off"] < 1.0 - TOL
    ]
    return {
        "simultaneous_import_export_hours": sum(1 for row in rows if row["grid_overlap"] > TOL),
        "simultaneous_import_export_total_mwh": sum(row["grid_overlap"] for row in rows),
        "simultaneous_import_export_max_mw": max(row["grid_overlap"] for row in rows),
        "simultaneous_import_export_top": top_by("grid_overlap"),
        "simultaneous_charge_discharge_hours": sum(1 for row in rows if row["storage_overlap"] > TOL),
        "simultaneous_charge_discharge_total_mwh": sum(row["storage_overlap"] for row in rows),
        "simultaneous_charge_discharge_max_mw": max(row["storage_overlap"] for row in rows),
        "simultaneous_charge_discharge_top": top_by("storage_overlap"),
        "fractional_commitment_hours": len(fractional_commitment_hours),
        "fractional_commitment_top": fractional_commitment_hours[:8],
        "mixed_temperature_mode_hours": sum(1 for row in rows if row["mode_positive_count"] > 1),
        "max_positive_temperature_modes": max(row["mode_positive_count"] for row in rows),
        "mixed_temperature_mode_top": sorted(
            rows,
            key=lambda row: (row["mode_positive_count"], row["mode_fractional_count"]),
            reverse=True,
        )[:6],
        "mixed_heat_segment_hours": sum(1 for row in rows if row["heat_segment_positive_count"] > 1),
        "max_positive_heat_segments": max(row["heat_segment_positive_count"] for row in rows),
        "mixed_heat_segment_top": sorted(
            rows,
            key=lambda row: (row["heat_segment_positive_count"], row["heat_segment_fractional_count"]),
            reverse=True,
        )[:6],
        "mixed_power_segment_hours": sum(1 for row in rows if row["power_segment_positive_count"] > 1),
        "max_positive_power_segments": max(row["power_segment_positive_count"] for row in rows),
        "mixed_power_segment_top": sorted(
            rows,
            key=lambda row: (row["power_segment_positive_count"], row["power_segment_fractional_count"]),
            reverse=True,
        )[:6],
        "chp_curtailment_total_mwh": sum(row["chp_curt"] for row in rows),
        "chp_curtailment_while_fractionally_off_hours": len(curtail_fractional_off),
        "chp_curtailment_while_fractionally_off_mwh": sum(row["chp_curt"] for row in curtail_fractional_off),
        "pv_curtailment_total_mwh": sum(row["pv_curt"] for row in rows),
        "dump_total_mwh": sum(row["dump"] for row in rows),
        "dump_hours": sum(1 for row in rows if row["dump"] > TOL),
        "under_total_mwh": sum(row["under"] for row in rows),
        "under_hours": sum(1 for row in rows if row["under"] > TOL),
    }


def _fix_var(var_data: Any, value: float) -> int:
    var_data.fix(float(value))
    return 1


def _fix_commitment(model: pyo.ConcreteModel, schedule: pd.DataFrame) -> dict[str, Any]:
    fixed = 0
    for t, row in schedule.iterrows():
        on = round(float(row["on"]))
        fixed += _fix_var(model.y_off[int(t)], 1.0 - on)
        fixed += _fix_var(model.start[int(t)], round(float(row["start"])))
        fixed += _fix_var(model.stop[int(t)], round(float(row["stop"])))
    return {"fixed": fixed, "skipped": 0, "notes": []}


def _fix_modes(model: pyo.ConcreteModel, schedule: pd.DataFrame) -> dict[str, Any]:
    fixed = 0
    notes: list[str] = []
    for t, row in schedule.iterrows():
        mode = str(row["mode"])
        temp_label = None if pd.isna(row["temp_label"]) else str(row["temp_label"])
        if mode == "OFF":
            for tt in model.TEMP:
                fixed += _fix_var(model.y[int(t), tt], 0.0)
            continue
        if not temp_label:
            notes.append(f"t={t}: missing temp_label for ON row")
            continue
        for tt in model.TEMP:
            fixed += _fix_var(model.y[int(t), tt], 1.0 if str(tt) == temp_label else 0.0)
    return {"fixed": fixed, "skipped": len(notes), "notes": notes}


def _fix_segments(model: pyo.ConcreteModel, schedule: pd.DataFrame) -> dict[str, Any]:
    fixed = 0
    notes: list[str] = []
    for t, row in schedule.iterrows():
        mode = str(row["mode"])
        temp_label = None if pd.isna(row["temp_label"]) else str(row["temp_label"])
        heat_seg = None if pd.isna(row["heat_seg"]) else int(row["heat_seg"])
        power_seg = None if pd.isna(row["power_seg"]) else int(row["power_seg"])
        selected_h = (temp_label, heat_seg)
        selected_e = (temp_label, power_seg)
        if mode != "OFF" and (temp_label is None or heat_seg is None or power_seg is None):
            notes.append(f"t={t}: missing segment selector fields for ON row")
            continue
        for tt, seg in model.HS:
            target = 1.0 if mode != "OFF" and (str(tt), int(seg)) == selected_h else 0.0
            fixed += _fix_var(model.zH[int(t), (tt, seg)], target)
        for tt, seg in model.ES:
            target = 1.0 if mode != "OFF" and (str(tt), int(seg)) == selected_e else 0.0
            fixed += _fix_var(model.zE[int(t), (tt, seg)], target)
    return {"fixed": fixed, "skipped": len(notes), "notes": notes}


def _fix_storage_direction(model: pyo.ConcreteModel, schedule: pd.DataFrame) -> dict[str, Any]:
    fixed = 0
    skipped = 0
    notes: list[str] = []
    for t, row in schedule.iterrows():
        ch = float(row["ch_mw"])
        dis = float(row["dis_mw"])
        if ch > TOL and dis <= TOL:
            fixed += _fix_var(model.u_ch[int(t)], 1.0)
        elif dis > TOL and ch <= TOL:
            fixed += _fix_var(model.u_ch[int(t)], 0.0)
        elif ch <= TOL and dis <= TOL:
            skipped += 1
            notes.append(f"t={t}: storage direction ambiguous because ch=dis=0")
        else:
            skipped += 1
            notes.append(f"t={t}: stored dispatch has simultaneous ch={ch}, dis={dis}")
    return {"fixed": fixed, "skipped": skipped, "notes": notes}


def solve_fixed_case(
    case: str,
    description: str,
    fixers: list[Callable[[pyo.ConcreteModel, pd.DataFrame], dict[str, Any]]],
    *,
    unrestricted_objective: float,
    incumbent_900: float,
    time_limit_s: float,
) -> dict[str, Any]:
    schedule = pd.read_parquet(_dispatch_path(TIGHTENED_TAGS[900]))
    model, _, _, _, _, _ = build_tightened_model()
    relaxed = relax_discrete_variables(model)
    fixed = 0
    skipped = 0
    notes: list[str] = []
    for fixer in fixers:
        result = fixer(model, schedule)
        fixed += int(result["fixed"])
        skipped += int(result["skipped"])
        notes.extend(result["notes"])
    solve = solve_model(model, time_limit_s=time_limit_s)
    obj = float(solve["objective"])
    return {
        "case": case,
        "description": description,
        "status": solve["status"],
        "termination": solve["termination"],
        "runtime_s": solve["runtime_s"],
        "lp_objective": obj,
        "reduction_from_unrestricted_lp": unrestricted_objective - obj,
        "distance_from_900_incumbent": obj - incumbent_900,
        "fixed_variables": fixed,
        "skipped_variables": skipped,
        "notes": notes[:12],
        **relaxed,
    }


def group_fixing_audit(unrestricted_objective: float, incumbent_900: float, *, time_limit_s: float) -> list[dict[str, Any]]:
    cases = [
        ("A", "CHP commitment/startup/shutdown fixed", [_fix_commitment]),
        ("B", "CHP heat/power segment selectors fixed", [_fix_segments]),
        ("D", "Storage charge/discharge direction fixed where dispatch is nonzero", [_fix_storage_direction]),
        ("E", "All CHP discrete variables fixed", [_fix_commitment, _fix_modes, _fix_segments]),
        (
            "F",
            "All reproducible discrete variables fixed",
            [_fix_commitment, _fix_modes, _fix_segments, _fix_storage_direction],
        ),
    ]
    rows = [
        solve_fixed_case(
            case,
            description,
            fixers,
            unrestricted_objective=unrestricted_objective,
            incumbent_900=incumbent_900,
            time_limit_s=time_limit_s,
        )
        for case, description, fixers in cases
    ]
    rows.insert(
        2,
        {
            "case": "C",
            "description": "Grid direction fixed",
            "status": "not_applicable_absent",
            "termination": "not_solved",
            "runtime_s": 0.0,
            "lp_objective": unrestricted_objective,
            "reduction_from_unrestricted_lp": 0.0,
            "distance_from_900_incumbent": unrestricted_objective - incumbent_900,
            "fixed_variables": 0,
            "skipped_variables": 24,
            "notes": ["No grid-direction binary variable is present in the model or stored dispatch artifacts."],
            "relaxed_binary": 0,
            "relaxed_integer": 0,
        },
    )
    return rows


def retained_mip_results() -> list[dict[str, Any]]:
    rows = []
    for seconds, tag in TIGHTENED_TAGS.items():
        summary = _load_json(_summary_path(tag))
        solver = summary["solver"]
        inc = float(solver["incumbent_objective"])
        bound = float(solver["best_bound_objective"])
        rows.append(
            {
                "seconds": seconds,
                "tag": tag,
                "incumbent_objective": inc,
                "best_bound_objective": bound,
                "absolute_bound_distance": bound - inc,
                "gap_percent": float(solver["achieved_gap_percent"]),
                "termination": solver["termination"],
            }
        )
    return rows


def big_m_inventory(meta: Any, heat_seg: pd.DataFrame, power_seg: pd.DataFrame) -> list[dict[str, Any]]:
    h_max = float(heat_seg["h_ub_eff"].max())
    e_max = float(power_seg["e_ub_eff"].max())
    q_max = float(max(heat_seg["q_ub_eff"].max(), power_seg["q_ub_eff"].max()))
    e_load = float(meta.e_load_base_mw)
    return [
        {
            "rank": 1,
            "file_line": "src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:480-490",
            "constraint": "h_eq_ub/lb",
            "m_value_or_formula": f"M_eq_H = H_max + 50 = {h_max + 50.0:.6f}",
            "physical_scale": f"H_max={h_max:.6f}, Q_max={q_max:.6f}",
            "tightness": "loose for inactive heat segment equations because a global additive M relaxes every unselected segment.",
            "still_important_after_tightening": "yes",
        },
        {
            "rank": 2,
            "file_line": "src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:518-528",
            "constraint": "e_eq_ub/lb",
            "m_value_or_formula": f"M_eq_E = E_max + 50 = {e_max + 50.0:.6f}",
            "physical_scale": f"E_max={e_max:.6f}, Q_max={q_max:.6f}",
            "tightness": "loose for inactive power segment equations and directly tied to the weak segment relaxation.",
            "still_important_after_tightening": "yes",
        },
        {
            "rank": 3,
            "file_line": "src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:468-478",
            "constraint": "h_lb_con/h_ub_con/qh_lb_con/qh_ub_con",
            "m_value_or_formula": f"M_H=H_max={h_max:.6f}; M_Q=Q_max={q_max:.6f}",
            "physical_scale": f"segment H ub range up to {h_max:.6f}; segment Q ub range up to {q_max:.6f}",
            "tightness": "global M values are safe but not segment-specific; aggregate tightening helps but does not eliminate fractional mixing.",
            "still_important_after_tightening": "yes",
        },
        {
            "rank": 4,
            "file_line": "src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:506-516",
            "constraint": "e_lb_con/e_ub_con/qe_lb_con/qe_ub_con",
            "m_value_or_formula": f"M_E=E_max={e_max:.6f}; M_Q=Q_max={q_max:.6f}",
            "physical_scale": f"segment E ub range up to {e_max:.6f}; segment Q ub range up to {q_max:.6f}",
            "tightness": "global M values are safe but not segment-specific; fractional zE values remain consequential.",
            "still_important_after_tightening": "yes",
        },
        {
            "rank": 5,
            "file_line": "src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:447-449",
            "constraint": "off_H/off_E/off_Q",
            "m_value_or_formula": f"H_max={h_max:.6f}; E_max={e_max:.6f}; Q_max={q_max:.6f}",
            "physical_scale": "full CHP capacity",
            "tightness": "capacity-tight for integer off/on, but permits proportional output under fractional commitment.",
            "still_important_after_tightening": "yes",
        },
        {
            "rank": 6,
            "file_line": "src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:544-545",
            "constraint": "storage ch_mode/dis_mode",
            "m_value_or_formula": f"P_ch_max={meta.storage_p_ch_max_mw:.6f}; P_dis_max={meta.storage_p_dis_max_mw:.6f}",
            "physical_scale": "storage power limits",
            "tightness": "exact for the binary disjunction; its LP relaxation is the convex hull and still permits simultaneous partial charge/discharge.",
            "still_important_after_tightening": "moderate",
        },
        {
            "rank": 7,
            "file_line": "src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:568-570",
            "constraint": "chp_curt_on_ub/chp_curt_seg_ub",
            "m_value_or_formula": f"E_max={e_max:.6f}; sum(e_ub*zE)",
            "physical_scale": "available CHP electric output",
            "tightness": "recently tightened; remains tied to fractional zE but no longer has a free global curtailment bound alone.",
            "still_important_after_tightening": "moderate",
        },
        {
            "rank": 8,
            "file_line": "src/chp_pv_sim/models/chp_week_storage_pv_grid_dispatch.py:432-435,580",
            "constraint": "grid_import upper bound and delivery ub",
            "m_value_or_formula": f"grid_import <= e_load[t] + export_cap; here e_load={e_load:.6f}, export_cap={meta.grid_export_cap_mw:.6f}",
            "physical_scale": "electric load plus export cap",
            "tightness": "finite and physically derived; no grid direction binary exists.",
            "still_important_after_tightening": "low to moderate",
        },
    ]


def recommendation() -> list[dict[str, Any]]:
    return [
        {
            "rank": 1,
            "candidate": "Replace CHP segment big-M equations/bounds with an extended convex-hull or perspective formulation for each selected heat/power segment, preserving the same segment data and integer choices.",
            "integer_feasible_set_preserved": "yes if each existing binary segment choice maps one-to-one to its lifted copy variables and the original H/E/Q are linked as sums of lifted variables.",
            "proof_outline": "For binary z, the lifted variables for inactive segments are forced to zero; for the active segment they equal the original H/E/Q and satisfy the same affine segment equations and segment bounds. Projecting the lifted formulation onto H/E/Q/z gives exactly the current integer-feasible segment disjunction.",
            "expected_lp_benefit": "highest: targets the families with the most fractional selectors and the largest remaining big-M values.",
            "implementation_complexity": "high",
            "semantic_risk": "medium: indexing and heat/power coupling must be audited carefully, but no objective or physical parameter change is needed.",
        },
        {
            "rank": 2,
            "candidate": "Add redundant transition equality start[t] - stop[t] == on[t] - on[t-1] with the existing t=0 initial-state analogue.",
            "integer_feasible_set_preserved": "yes; the existing binary inequalities already imply the equality for all integer schedules.",
            "proof_outline": "Enumerating binary on[t-1], on[t] pairs gives start/stop as exactly 1/0 for startup, 0/1 for shutdown, and 0/0 otherwise under the current upper/lower bounds.",
            "expected_lp_benefit": "moderate if fractional start/stop remains active; low implementation cost.",
            "implementation_complexity": "low",
            "semantic_risk": "low",
        },
        {
            "rank": 3,
            "candidate": "Introduce explicit grid import/export direction exclusivity.",
            "integer_feasible_set_preserved": "no for the current mathematical feasible set, although it may match intended physics.",
            "proof_outline": "The current model allows simultaneous positive import and export as feasible; adding a direction binary would remove those points.",
            "expected_lp_benefit": "depends on observed simultaneous import/export in the root LP.",
            "implementation_complexity": "medium",
            "semantic_risk": "medium because it is a physical/modeling change, not a redundant tightening.",
        },
        {
            "rank": 4,
            "candidate": "Further storage charge/discharge exclusivity strengthening.",
            "integer_feasible_set_preserved": "not with simple linear cuts beyond ch/P_ch + dis/P_dis <= 1, which is already implied by the existing u_ch formulation.",
            "proof_outline": "Summing ch <= P_ch u and dis <= P_dis(1-u) gives the normalized convex-hull inequality after relaxation.",
            "expected_lp_benefit": "limited unless a new nonredundant modeling assumption is introduced.",
            "implementation_complexity": "medium",
            "semantic_risk": "medium to high for any additional restriction.",
        },
    ]


def build_audit(*, lp_time_limit_s: float) -> dict[str, Any]:
    model, cfg, inputs, meta, heat_seg, power_seg = build_tightened_model()
    relaxed = relax_discrete_variables(model)
    unrestricted_solve = solve_model(model, time_limit_s=lp_time_limit_s)
    family_table = discrete_family_table(model, inputs)
    nonphysical = nonphysical_lp_metrics(model, inputs)
    retained = retained_mip_results()
    incumbent_900 = next(row["incumbent_objective"] for row in retained if row["seconds"] == 900)
    group_rows = group_fixing_audit(
        unrestricted_objective=float(unrestricted_solve["objective"]),
        incumbent_900=float(incumbent_900),
        time_limit_s=lp_time_limit_s,
    )
    return {
        "config_path": str(CONFIG_PATH.relative_to(ROOT)),
        "scenario": SCENARIO,
        "lp_time_limit_s": lp_time_limit_s,
        "root_lp": {
            **unrestricted_solve,
            **relaxed,
            "model_variable_count": int(model.nvariables()),
            "model_constraint_count": int(model.nconstraints()),
            "distance_from_900_incumbent": float(unrestricted_solve["objective"]) - float(incumbent_900),
        },
        "retained_mip_results": retained,
        "fractional_variable_families": family_table,
        "nonphysical_lp_metrics": nonphysical,
        "group_fixing": group_rows,
        "big_m_inventory": big_m_inventory(meta, heat_seg, power_seg),
        "recommendations": recommendation(),
    }


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, str)):
        return str(value)
    try:
        x = float(value)
    except Exception:
        return str(value)
    if not math.isfinite(x):
        return str(value)
    return f"{x:.{digits}f}"


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(out)


def render_markdown(audit: dict[str, Any]) -> str:
    root = audit["root_lp"]
    retained_900 = next(row for row in audit["retained_mip_results"] if row["seconds"] == 900)
    lines: list[str] = [
        "# LP Relaxation Anatomy Audit, Tightened 24h UC",
        "",
        "This is a read-only audit. It builds the existing tightened UC model in memory, relaxes integer and binary variables, and does not write normal experiment artifacts.",
        "",
        "## Root LP",
        "",
        _markdown_table(
            ["status", "termination", "runtime_s", "objective", "distance from 900s incumbent", "relaxed binaries"],
            [
                [
                    root["status"],
                    root["termination"],
                    _fmt(root["runtime_s"]),
                    _fmt(root["objective"]),
                    _fmt(root["distance_from_900_incumbent"]),
                    root["relaxed_binary"],
                ]
            ],
        ),
        "",
        f"900-second incumbent: `{_fmt(retained_900['incumbent_objective'])}`. 900-second best bound: `{_fmt(retained_900['best_bound_objective'])}`.",
        "",
        "Retained tightened MIP results used for comparison:",
        "",
        _markdown_table(
            ["time limit", "termination", "incumbent", "best bound", "absolute distance", "gap %"],
            [
                [
                    row["seconds"],
                    row["termination"],
                    _fmt(row["incumbent_objective"]),
                    _fmt(row["best_bound_objective"]),
                    _fmt(row["absolute_bound_distance"]),
                    _fmt(row["gap_percent"]),
                ]
                for row in audit["retained_mip_results"]
            ],
        ),
        "",
        "## Fractional Discrete Families",
        "",
        _markdown_table(
            [
                "family",
                "count",
                "fractional @1e-6",
                "min",
                "max",
                "sum frac dist",
                "mean frac dist",
                "most fractional",
            ],
            [
                [
                    row["family"],
                    row["count"],
                    row["fractional_count"],
                    _fmt(row["min_value"]),
                    _fmt(row["max_value"]),
                    _fmt(row["fractional_distance_sum"]),
                    _fmt(row["fractional_distance_mean"]),
                    "; ".join(
                        f"{item['name']}={_fmt(item['value'])} at {item.get('timestamp') or item['index']}"
                        for item in row["most_fractional"][:3]
                    )
                    or row["status"],
                ]
                for row in audit["fractional_variable_families"]
            ],
        ),
        "",
        "## LP-Only Nonphysical Behavior",
        "",
    ]
    metrics = audit["nonphysical_lp_metrics"]
    lines.extend(
        [
            _markdown_table(
                ["metric", "value"],
                [
                    ["simultaneous import/export hours", metrics["simultaneous_import_export_hours"]],
                    ["simultaneous import/export total MWh", _fmt(metrics["simultaneous_import_export_total_mwh"])],
                    ["simultaneous import/export max MW", _fmt(metrics["simultaneous_import_export_max_mw"])],
                    ["simultaneous charge/discharge hours", metrics["simultaneous_charge_discharge_hours"]],
                    ["simultaneous charge/discharge total MWh", _fmt(metrics["simultaneous_charge_discharge_total_mwh"])],
                    ["simultaneous charge/discharge max MW", _fmt(metrics["simultaneous_charge_discharge_max_mw"])],
                    ["fractional commitment hours", metrics["fractional_commitment_hours"]],
                    ["mixed temperature-mode hours", metrics["mixed_temperature_mode_hours"]],
                    ["max positive temperature modes in one hour", metrics["max_positive_temperature_modes"]],
                    ["mixed heat-segment hours", metrics["mixed_heat_segment_hours"]],
                    ["max positive heat segments in one hour", metrics["max_positive_heat_segments"]],
                    ["mixed power-segment hours", metrics["mixed_power_segment_hours"]],
                    ["max positive power segments in one hour", metrics["max_positive_power_segments"]],
                    ["CHP curtailment total MWh", _fmt(metrics["chp_curtailment_total_mwh"])],
                    [
                        "CHP curtailment while fractionally offline MWh",
                        _fmt(metrics["chp_curtailment_while_fractionally_off_mwh"]),
                    ],
                    ["PV curtailment total MWh", _fmt(metrics["pv_curtailment_total_mwh"])],
                    ["dump total MWh", _fmt(metrics["dump_total_mwh"])],
                    ["undersupply total MWh", _fmt(metrics["under_total_mwh"])],
                ],
            ),
            "",
            "Top simultaneous import/export rows:",
            "",
            _markdown_table(
                ["t", "timestamp", "import", "export", "overlap"],
                [
                    [
                        row["t"],
                        row["timestamp"],
                        _fmt(row["grid_import"]),
                        _fmt(row["grid_export"]),
                        _fmt(row["grid_overlap"]),
                    ]
                    for row in metrics["simultaneous_import_export_top"][:6]
                ]
                or [["none", "", "", "", ""]],
            ),
            "",
            "Top simultaneous charge/discharge rows:",
            "",
            _markdown_table(
                ["t", "timestamp", "charge", "discharge", "overlap"],
                [
                    [
                        row["t"],
                        row["timestamp"],
                        _fmt(row["ch"]),
                        _fmt(row["dis"]),
                        _fmt(row["storage_overlap"]),
                    ]
                    for row in metrics["simultaneous_charge_discharge_top"][:6]
                ]
                or [["none", "", "", "", ""]],
            ),
            "",
            "## Group-Fixing LPs",
            "",
            _markdown_table(
                [
                    "case",
                    "description",
                    "status",
                    "runtime_s",
                    "LP objective",
                    "reduction from root",
                    "distance from 900s incumbent",
                    "fixed vars",
                    "notes",
                ],
                [
                    [
                        row["case"],
                        row["description"],
                        row["status"] + "/" + row["termination"],
                        _fmt(row["runtime_s"]),
                        _fmt(row["lp_objective"]),
                        _fmt(row["reduction_from_unrestricted_lp"]),
                        _fmt(row["distance_from_900_incumbent"]),
                        row["fixed_variables"],
                        "; ".join(row["notes"][:2]),
                    ]
                    for row in audit["group_fixing"]
                ],
            ),
            "",
            "Case C was not solved as a distinct fixing LP because the model has no grid-direction binary variable and the retained dispatch artifact has no such field.",
            "",
            "Case B fixes only `zH` and `zE`; in this retained 900-second schedule every hour is ON, so the existing `heat_select`, `power_select`, and `one_mode` equations make those segment fixes also imply the corresponding temperature-mode and commitment state.",
            "",
            "## Remaining Big-M and Binary-Linked Weaknesses",
            "",
            _markdown_table(
                ["rank", "file/line", "constraint", "M or formula", "scale", "assessment", "important"],
                [
                    [
                        row["rank"],
                        row["file_line"],
                        row["constraint"],
                        row["m_value_or_formula"],
                        row["physical_scale"],
                        row["tightness"],
                        row["still_important_after_tightening"],
                    ]
                    for row in audit["big_m_inventory"]
                ],
            ),
            "",
            "## Recommendation",
            "",
        ]
    )
    top = audit["recommendations"][0]
    lines.extend(
        [
            f"Best-supported next formulation change: **{top['candidate']}**",
            "",
            _markdown_table(
                ["rank", "candidate", "integer set preserved", "expected LP benefit", "complexity", "semantic risk"],
                [
                    [
                        row["rank"],
                        row["candidate"],
                        row["integer_feasible_set_preserved"],
                        row["expected_lp_benefit"],
                        row["implementation_complexity"],
                        row["semantic_risk"],
                    ]
                    for row in audit["recommendations"]
                ],
            ),
            "",
            "Proof outline for the top recommendation: " + top["proof_outline"],
            "",
            "No new formulation was implemented in this audit.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only LP relaxation anatomy audit for the tightened 24h UC model.")
    parser.add_argument("--lp-time-limit-s", type=float, default=120.0)
    parser.add_argument("--write-doc", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print the full audit JSON instead of the concise summary.")
    args = parser.parse_args()
    audit = build_audit(lp_time_limit_s=float(args.lp_time_limit_s))
    if args.write_doc:
        DOC_PATH.write_text(render_markdown(audit), encoding="utf-8")
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "root_lp": audit["root_lp"],
                    "fractional_variable_families": audit["fractional_variable_families"],
                    "group_fixing": audit["group_fixing"],
                    "doc_path": str(DOC_PATH.relative_to(ROOT)) if args.write_doc else None,
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
