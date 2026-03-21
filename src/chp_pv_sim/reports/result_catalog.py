from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import numpy as np
import pandas as pd


DEFAULT_KEY_COLUMNS: list[str] = [
    "method",
    "scenario_name",
    "e_load_base_mw",
    "cost_dump",
    "grid_export_cap_mw",
    "startup_cost",
    "min_up_hours",
    "min_down_hours",
    "horizon_hours",
    "step_hours",
    "time_limit_window_s",
    "mip_rel_gap",
]

DEFAULT_COMPARE_COLUMNS: list[str] = [
    "boiler_share_pct",
    "dump_share_pct",
    "E_curt_ratio_pct",
    "grid_import_mwh",
    "grid_export_mwh",
    "net_export_mwh",
    "objective_profit_like",
    "objective_system_cost",
    "profit_objective_realized",
    "system_cost_realized",
    "starts",
    "stops",
]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tag_float(x: float) -> str:
    return f"{float(x):g}".replace("-", "m").replace(".", "p")


def make_mpc_tag(eload: float, dump_cost: float) -> str:
    return f"mpc_eload{_tag_float(eload)}MW_dump{_tag_float(dump_cost)}"


def _get(d: Dict[str, Any], keys: Sequence[str], default: Any = np.nan) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return default


def _as_float(x: Any, default: float = float("nan")) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _as_int(x: Any, default: int = -1) -> int:
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return default
        return int(round(float(x)))
    except Exception:
        return default


def extract_tag(path: Path) -> str:
    name = path.name
    prefix = "dispatch_summary_pv_grid__"
    suffix = ".json"
    if name.startswith(prefix) and name.endswith(suffix):
        return name[len(prefix):-len(suffix)]
    return path.stem


def infer_method(summary: Dict[str, Any], filename: str = "") -> str:
    method = str(summary.get("method", "") or "").strip().lower()
    if method == "rolling_horizon_mpc":
        return "MPC"
    if method in {"full_horizon_uc", "full-week uc", "uc", "full_week_uc"}:
        return "Full-week UC"

    rolling = summary.get("rolling", {})
    if isinstance(rolling, dict) and rolling:
        return "MPC"

    scen = summary.get("scenario", {})
    if not isinstance(scen, dict):
        scen = {}

    low = filename.lower()
    if "mpc" in low:
        return "MPC"
    if "uc" in low:
        return "Full-week UC"

    startup_cost = _as_float(scen.get("startup_cost", np.nan))
    min_up = _as_int(scen.get("min_up_hours", np.nan), default=1)
    min_down = _as_int(scen.get("min_down_hours", np.nan), default=1)
    if startup_cost > 0.0 or min_up > 1 or min_down > 1:
        return "Full-week UC"
    return "Full-week"


def solver_profit_objective(summary: Dict[str, Any]) -> float:
    solver = summary.get("solver", {})
    if not isinstance(solver, dict):
        return float("nan")
    for key in ["objective_profit_like", "objective_implemented", "objective"]:
        v = _as_float(solver.get(key, np.nan))
        if math.isfinite(v):
            return v
    return float("nan")


def solver_system_cost_equivalent(summary: Dict[str, Any]) -> float:
    solver = summary.get("solver", {})
    if isinstance(solver, dict):
        v = _as_float(solver.get("objective_system_cost_equivalent", np.nan))
        if math.isfinite(v):
            return v
    profit = solver_profit_objective(summary)
    return -profit if math.isfinite(profit) else float("nan")


def realized_profit_objective(summary: Dict[str, Any]) -> float:
    econ = summary.get("economics_realized", {})
    if not isinstance(econ, dict):
        return float("nan")
    for key in ["profit_objective_realized", "total_objective_realized"]:
        v = _as_float(econ.get(key, np.nan))
        if math.isfinite(v):
            return v
    return float("nan")


def realized_system_cost(summary: Dict[str, Any]) -> float:
    econ = summary.get("economics_realized", {})
    if isinstance(econ, dict):
        v = _as_float(econ.get("system_cost_realized", np.nan))
        if math.isfinite(v):
            return v
    profit = realized_profit_objective(summary)
    return -profit if math.isfinite(profit) else float("nan")


def scan_summary_files(res_dir: Path, *, include_backups: bool = False, include_live: bool = False) -> list[Path]:
    files: list[Path] = []
    if include_live:
        live = res_dir / "dispatch_summary_pv_grid.json"
        if live.exists():
            files.append(live)

    for p in sorted(res_dir.glob("dispatch_summary_pv_grid__*.json")):
        if not include_backups and "__backup_" in p.name:
            continue
        files.append(p)

    # unique, preserve order
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in files:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    return uniq


def _safe_pct(num: float, den: float) -> float:
    return 100.0 * num / den if den > 1e-9 else float("nan")


def summary_to_row(path: Path) -> Dict[str, Any]:
    summary = read_json(path)
    scen = summary.get("scenario", {})
    if not isinstance(scen, dict):
        scen = {}
    rolling = summary.get("rolling", {})
    if not isinstance(rolling, dict):
        rolling = {}
    totals = summary.get("totals", {})
    if not isinstance(totals, dict):
        totals = {}
    qc = summary.get("qc", {})
    if not isinstance(qc, dict):
        qc = {}

    heat = _as_float(totals.get("heat_demand_mwh", np.nan))
    boiler = _as_float(totals.get("boiler_mwh", np.nan))
    dump = _as_float(totals.get("dump_mwh", np.nan))
    e_chp = _as_float(totals.get("E_chp_mwh", np.nan))
    e_curt = _as_float(totals.get("E_chp_curt_mwh", np.nan))
    gimp = _as_float(totals.get("grid_import_mwh", np.nan))
    gexp = _as_float(totals.get("grid_export_mwh", np.nan))
    pv_av = _as_float(totals.get("pv_avail_mwh", np.nan))
    pv_used = _as_float(totals.get("pv_used_mwh", np.nan))

    return {
        "file": path.name,
        "tag": extract_tag(path),
        "created_utc": str(summary.get("created_utc", "") or ""),
        "method": infer_method(summary, path.name),
        "scenario_name": str(_get(scen, ["scenario"], "") or ""),
        "e_load_base_mw": _as_float(_get(scen, ["e_load_base_mw", "e_load_base"], np.nan)),
        "cost_dump": _as_float(_get(scen, ["cost_dump"], np.nan)),
        "grid_export_cap_mw": _as_float(_get(scen, ["grid_export_cap_mw"], np.nan)),
        "startup_cost": _as_float(_get(scen, ["startup_cost"], np.nan)),
        "min_up_hours": _as_int(_get(scen, ["min_up_hours"], np.nan), default=-1),
        "min_down_hours": _as_int(_get(scen, ["min_down_hours"], np.nan), default=-1),
        "horizon_hours": _as_float(_get(rolling, ["horizon_hours"], _get(scen, ["horizon_hours", "horizon"], np.nan))),
        "step_hours": _as_float(_get(rolling, ["step_hours"], _get(scen, ["step_hours", "step"], np.nan))),
        "time_limit_window_s": _as_float(
            _get(rolling, ["time_limit_window_s"], _get(scen, ["time_limit_window_s", "time_limit_window", "time_limit_s"], np.nan))
        ),
        "mip_rel_gap": _as_float(_get(scen, ["mip_rel_gap"], np.nan)),
        "heat_demand_mwh": heat,
        "boiler_mwh": boiler,
        "boiler_share_pct": _safe_pct(boiler, heat),
        "dump_mwh": dump,
        "dump_share_pct": _safe_pct(dump, heat),
        "E_chp_mwh": e_chp,
        "E_curt_mwh": e_curt,
        "E_curt_ratio_pct": _safe_pct(e_curt, e_chp),
        "pv_avail_mwh": pv_av,
        "pv_used_mwh": pv_used,
        "pv_utilization": (pv_used / pv_av) if pv_av > 1e-9 else float("nan"),
        "grid_import_mwh": gimp,
        "grid_export_mwh": gexp,
        "net_export_mwh": gexp - gimp,
        "hours_export_at_cap": _as_int(qc.get("hours_export_at_cap", np.nan), default=-1),
        "starts": _as_int(qc.get("starts", np.nan), default=-1),
        "stops": _as_int(qc.get("stops", np.nan), default=-1),
        "objective_profit_like": solver_profit_objective(summary),
        "objective_system_cost": solver_system_cost_equivalent(summary),
        "profit_objective_realized": realized_profit_objective(summary),
        "system_cost_realized": realized_system_cost(summary),
    }


def build_result_catalog(
    res_dir: Path,
    *,
    include_backups: bool = False,
    include_live: bool = False,
) -> pd.DataFrame:
    rows = [summary_to_row(p) for p in scan_summary_files(res_dir, include_backups=include_backups, include_live=include_live)]
    return pd.DataFrame(rows)


def dedupe_catalog(
    df: pd.DataFrame,
    *,
    key_columns: Sequence[str] | None = None,
    compare_columns: Sequence[str] | None = None,
    float_atol: float = 1e-6,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    key_columns = list(key_columns or DEFAULT_KEY_COLUMNS)
    compare_columns = [c for c in (compare_columns or DEFAULT_COMPARE_COLUMNS) if c in df.columns]

    missing = [c for c in key_columns if c not in df.columns]
    if missing:
        raise KeyError(f"Missing key columns for dedupe: {missing}")

    work = df.copy()
    if "created_utc" in work.columns:
        work["__created_sort"] = pd.to_datetime(work["created_utc"], errors="coerce")
    else:
        work["__created_sort"] = pd.NaT

    keep_idx: list[int] = []
    problems: list[str] = []

    grouped = work.groupby(key_columns, dropna=False, sort=False)
    for key, grp in grouped:
        grp = grp.sort_values(["__created_sort", "file"], na_position="last")
        if len(grp) == 1:
            keep_idx.append(int(grp.index[-1]))
            continue

        conflict = False
        for col in compare_columns:
            vals = pd.to_numeric(grp[col], errors="coerce")
            finite = vals[np.isfinite(vals.to_numpy(dtype=float))]
            if len(finite) <= 1:
                continue
            if float(finite.max() - finite.min()) > float(float_atol):
                conflict = True
                break

        if conflict:
            key_map = {k: v for k, v in zip(key_columns, key if isinstance(key, tuple) else (key,))}
            cols = [c for c in ["file", *compare_columns] if c in grp.columns]
            problems.append(
                f"Scenario key {key_map} has conflicting duplicate artifacts:\n"
                + grp[cols].to_string(index=False)
            )
            continue

        keep_idx.append(int(grp.index[-1]))

    if problems:
        raise RuntimeError("\n\n".join(problems))

    out = work.loc[sorted(set(keep_idx))].drop(columns=["__created_sort"]).copy()
    out = out.sort_values(key_columns + ["created_utc", "file"], na_position="last").reset_index(drop=True)
    return out
