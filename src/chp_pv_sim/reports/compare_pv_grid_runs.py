from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from chp_pv_sim.paths import ROOT, REPORTS_DIR, ensure_dirs


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _get(d: Dict[str, Any], path: List[str], default=np.nan):
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _fmt(x: Any, kind: str = "float") -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return ""
    if kind == "int":
        try:
            return str(int(x))
        except Exception:
            return str(x)
    if kind == "pct":
        try:
            return f"{100.0 * float(x):.2f}%"
        except Exception:
            return str(x)
    if kind == "float":
        try:
            return f"{float(x):.3f}"
        except Exception:
            return str(x)
    return str(x)


def _infer_method(d: Dict[str, Any]) -> str:
    if d.get("method") == "rolling_horizon_mpc":
        return "MPC"
    scen = d.get("scenario", {})
    su = float(scen.get("startup_cost", 0.0)) if isinstance(scen, dict) else 0.0
    mu = int(scen.get("min_up_hours", 1)) if isinstance(scen, dict) else 1
    md = int(scen.get("min_down_hours", 1)) if isinstance(scen, dict) else 1
    if su > 0 or mu > 1 or md > 1:
        return "Full-week UC"
    return "Full-week (no UC)"


def _objective(d: Dict[str, Any]) -> float:
    # MPC summary stores objective_implemented, full-week stores objective
    v = _get(d, ["solver", "objective_implemented"], default=np.nan)
    if not (isinstance(v, float) and np.isnan(v)):
        return float(v)
    v2 = _get(d, ["solver", "objective"], default=np.nan)
    try:
        return float(v2)
    except Exception:
        return float("nan")


def _md_table(df: pd.DataFrame) -> str:
    # lightweight markdown table (no tabulate dependency)
    cols = list(df.columns)
    lines = []
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="week_2023_dec01")
    args = ap.parse_args()

    res_dir = ROOT / "data" / "scenarios" / args.scenario / "results"
    if not res_dir.exists():
        raise FileNotFoundError(f"Missing results dir: {res_dir}")

    # grab current + backups
    paths = sorted(res_dir.glob("dispatch_summary_pv_grid*.json"))
    if not paths:
        raise FileNotFoundError(f"No dispatch_summary_pv_grid*.json found in: {res_dir}")

    rows = []
    for p in paths:
        d = _read_json(p)
        scen = d.get("scenario", {}) if isinstance(d.get("scenario", {}), dict) else {}
        totals = d.get("totals", {}) if isinstance(d.get("totals", {}), dict) else {}
        qc = d.get("qc", {}) if isinstance(d.get("qc", {}), dict) else {}

        heat_d = float(totals.get("heat_demand_mwh", np.nan))
        boiler = float(totals.get("boiler_mwh", np.nan))
        dump = float(totals.get("dump_mwh", np.nan))

        e_chp = float(totals.get("E_chp_mwh", np.nan))
        e_curt = float(totals.get("E_chp_curt_mwh", np.nan))

        row = {
            "file": p.name,
            "created_utc": d.get("created_utc", ""),
            "method": _infer_method(d),
            "objective": _objective(d),

            "startup_cost": float(scen.get("startup_cost", np.nan)),
            "min_up": int(scen.get("min_up_hours", 1)) if "min_up_hours" in scen else "",
            "min_down": int(scen.get("min_down_hours", 1)) if "min_down_hours" in scen else "",

            "heat_demand_mwh": heat_d,
            "H_chp_mwh": float(totals.get("H_chp_mwh", np.nan)),
            "boiler_mwh": boiler,
            "boiler_share": boiler / heat_d if heat_d > 1e-9 else np.nan,
            "dump_mwh": dump,
            "dump_share": dump / heat_d if heat_d > 1e-9 else np.nan,

            "pv_used_mwh": float(totals.get("pv_used_mwh", np.nan)),
            "pv_curt_mwh": float(totals.get("pv_curt_mwh", np.nan)),

            "E_chp_mwh": e_chp,
            "E_chp_curt_mwh": e_curt,
            "E_curt_ratio": e_curt / e_chp if e_chp > 1e-9 else np.nan,

            "grid_export_mwh": float(totals.get("grid_export_mwh", np.nan)),
            "hours_export_at_cap": int(qc.get("hours_export_at_cap", np.nan)) if "hours_export_at_cap" in qc else "",
            "starts": int(qc.get("starts", np.nan)) if "starts" in qc else "",
            "stops": int(qc.get("stops", np.nan)) if "stops" in qc else "",
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    # Sort: MPC last (usually current), then by created time
    df["__is_mpc"] = (df["method"] == "MPC").astype(int)
    df = df.sort_values(["__is_mpc", "created_utc", "file"]).drop(columns=["__is_mpc"]).reset_index(drop=True)

    # Write full CSV
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = REPORTS_DIR / f"{args.scenario}__compare_pv_grid_runs.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # Write paper-friendly markdown table (trimmed)
    paper_cols = [
        "method",
        "startup_cost",
        "min_up",
        "min_down",
        "boiler_mwh",
        "boiler_share",
        "dump_mwh",
        "dump_share",
        "E_chp_curt_mwh",
        "E_curt_ratio",
        "hours_export_at_cap",
        "starts",
        "stops",
        "file",
    ]
    paper = df[paper_cols].copy()
    # format
    paper["startup_cost"] = paper["startup_cost"].apply(lambda x: _fmt(x, "float"))
    paper["boiler_mwh"] = paper["boiler_mwh"].apply(lambda x: _fmt(x, "float"))
    paper["dump_mwh"] = paper["dump_mwh"].apply(lambda x: _fmt(x, "float"))
    paper["boiler_share"] = paper["boiler_share"].apply(lambda x: _fmt(x, "pct"))
    paper["dump_share"] = paper["dump_share"].apply(lambda x: _fmt(x, "pct"))
    paper["E_chp_curt_mwh"] = paper["E_chp_curt_mwh"].apply(lambda x: _fmt(x, "float"))
    paper["E_curt_ratio"] = paper["E_curt_ratio"].apply(lambda x: _fmt(x, "pct"))

    out_md = REPORTS_DIR / f"{args.scenario}__compare_pv_grid_runs.md"
    out_md.write_text(
        "# PV+Grid Dispatch Runs Comparison\n\n"
        f"Scenario: `{args.scenario}`\n\n"
        "## Paper-friendly KPI table\n\n"
        + _md_table(paper)
        + "\n\n"
        "## Notes\n"
        "- `boiler_share` and `dump_share` are fractions of heat demand.\n"
        "- `E_curt_ratio` is `E_chp_curt_mwh / E_chp_mwh`.\n"
        "- This table is built by scanning `data/scenarios/<scenario>/results/dispatch_summary_pv_grid*.json`.\n",
        encoding="utf-8",
    )

    print("Wrote:", out_csv)
    print("Wrote:", out_md)
    print("\n=== PAPER TABLE (preview) ===")
    print(paper.to_string(index=False))


if __name__ == "__main__":
    main()