from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV file: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def _summary_path(scenario: str, tag: str) -> Path:
    return ROOT / "data" / "scenarios" / scenario / "results" / f"dispatch_summary_pv_grid__{tag}.json"


def _validation_path(scenario: str, tag: str) -> Path:
    return ROOT / "data" / "scenarios" / scenario / "results" / f"dispatch_validation_pv_grid__{tag}.json"


def _windows_path(scenario: str, tag: str) -> Path:
    return ROOT / "data" / "scenarios" / scenario / "results" / f"solver_windows_pv_grid__{tag}.csv"


def _format_yesno(x: Any) -> str:
    return "Yes" if bool(x) else "No"


def _safe_get(d: dict[str, Any], *keys: str, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _extract_a6_row(strategy_label: str, scenario: str, tag: str) -> dict[str, Any]:
    summary = _load_json(_summary_path(scenario, tag))
    validation = _load_json(_validation_path(scenario, tag))
    windows = _load_csv(_windows_path(scenario, tag))

    method = _safe_get(summary, "method", default="")
    qc_hours_cap = _safe_get(summary, "qc", "hours_export_at_cap", default=None)

    heat_resid = _safe_get(validation, "metrics", "heat_balance_residual_abs_max", default=None)
    elec_resid = _safe_get(validation, "metrics", "elec_balance_residual_abs_max", default=None)

    if method == "rolling_horizon_mpc":
        achieved_gap = _safe_get(summary, "solver", "achieved_gap_rel_max", default=None)
        runtime_s = _safe_get(summary, "solver", "wallclock_s_total", default=None)
        if "achieved_gap_rel" in windows.columns:
            valid = pd.to_numeric(windows["achieved_gap_rel"], errors="coerce").dropna()
            mean_gap = float(valid.mean()) if len(valid) else None
        else:
            mean_gap = None
    else:
        achieved_gap = _safe_get(summary, "solver", "achieved_gap_rel", default=None)
        runtime_s = _safe_get(summary, "solver", "wallclock_s", default=None)
        mean_gap = None

    return {
        "Strategy": strategy_label,
        "Validation pass": _format_yesno(_safe_get(validation, "pass", default=False)),
        "Heat-balance residual abs max": heat_resid,
        "Electric-balance residual abs max": elec_resid,
        "Hours at export cap": qc_hours_cap,
        "Achieved relative gap": achieved_gap,
        "Mean window relative gap": mean_gap,
        "Runtime (s)": runtime_s,
    }


def _extract_anchor_row(strategy_label: str, scenario: str, tag: str, horizon_h: int) -> dict[str, Any]:
    summary = _load_json(_summary_path(scenario, tag))
    validation = _load_json(_validation_path(scenario, tag))
    windows = _load_csv(_windows_path(scenario, tag))

    method = _safe_get(summary, "method", default="")
    qc_hours_cap = _safe_get(summary, "qc", "hours_export_at_cap", default=None)
    cost = _safe_get(summary, "economics_realized", "system_cost_realized", default=None)

    if method == "rolling_horizon_mpc":
        achieved_gap = _safe_get(summary, "solver", "achieved_gap_rel_max", default=None)
        runtime_s = _safe_get(summary, "solver", "wallclock_s_total", default=None)
        if "achieved_gap_rel" in windows.columns:
            valid = pd.to_numeric(windows["achieved_gap_rel"], errors="coerce").dropna()
            mean_gap = float(valid.mean()) if len(valid) else None
        else:
            mean_gap = None
        termination = " / ".join(sorted(set(map(str, windows["termination"].dropna().tolist()))))
    else:
        achieved_gap = _safe_get(summary, "solver", "achieved_gap_rel", default=None)
        runtime_s = _safe_get(summary, "solver", "wallclock_s", default=None)
        mean_gap = None
        termination = _safe_get(summary, "solver", "termination", default=None)

    return {
        "Scenario": scenario,
        "Horizon (h)": horizon_h,
        "Strategy": strategy_label,
        "Validation pass": _format_yesno(_safe_get(validation, "pass", default=False)),
        "Termination": termination,
        "Achieved relative gap": achieved_gap,
        "Mean window relative gap": mean_gap,
        "Runtime (s)": runtime_s,
        "Realized system cost": cost,
        "Hours at export cap": qc_hours_cap,
    }


def _write_outputs(df: pd.DataFrame, stem: str, title: str) -> None:
    csv_path = ROOT / "reports" / f"{stem}.csv"
    md_path = ROOT / "reports" / f"{stem}.md"

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    with md_path.open("w", encoding="utf-8") as f:
        f.write(title + "\n\n")
        f.write(df.to_markdown(index=False))
        f.write("\n")

    print(f"[OK] Wrote: {csv_path}")
    print(f"[OK] Wrote: {md_path}")
    print(df.to_string(index=False))
    print()


def main() -> None:
    # ---- Table A6 (winsorized true values) ----
    a6 = pd.DataFrame([
        _extract_a6_row("Full-horizon UC", "week_2023_dec01_winsor_p99_fw", "uc_paper_winsor_fw"),
        _extract_a6_row("Rolling MPC", "week_2023_dec01_winsor_p99_fw", "mpc_paper_winsor_fw"),
    ])
    _write_outputs(
        a6,
        "table_A6_real_fw",
        "Table A6. Validation and solver diagnostics for the baseline-aligned p99-winsorized outlier-handling sensitivity of the common-input UC–MPC comparison."
    )

    # ---- Exactness anchor table ----
    anchor = pd.DataFrame([
        _extract_anchor_row("Full-horizon UC", "week_2023_dec01_anchor24h_fw", "uc_anchor24h_fw", 24),
        _extract_anchor_row("Full-horizon UC", "week_2023_dec01_anchor48h_fw", "uc_anchor48h_fw", 48),
        _extract_anchor_row("Rolling MPC", "week_2023_dec01_anchor48h_fw", "mpc_anchor48h_fw", 48),
    ])
    _write_outputs(
        anchor,
        "table_anchor_exactness_fw",
        "Table A7. Reduced-horizon exactness-anchor diagnostics derived from the selected benchmark week."
    )


if __name__ == "__main__":
    main()