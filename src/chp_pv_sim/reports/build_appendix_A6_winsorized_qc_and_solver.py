from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _summary_path(results_dir: Path, tag: str) -> Path:
    return results_dir / f"dispatch_summary_pv_grid__{tag}.json"


def _extract_qc_and_solver(summary: Dict[str, Any]) -> Dict[str, Any]:
    qc = summary.get("qc", {}) or {}
    totals = summary.get("totals", {}) or {}
    solver = summary.get("solver", {}) or {}

    # QC fields
    heat_resid = _safe_float(qc.get("heat_balance_residual_abs_max"))
    elec_resid = _safe_float(qc.get("elec_balance_residual_abs_max"))
    under_mwh = _safe_float(totals.get("under_mwh"))
    starts = _safe_float(qc.get("starts"))
    stops = _safe_float(qc.get("stops"))
    hours_export_at_cap = _safe_float(qc.get("hours_export_at_cap"))

    # Solver fields: UC and MPC have slightly different summary schemas
    termination = solver.get("termination")
    if termination is None and "window_termination_counts" in solver:
        termination = "; ".join(
            f"{k}:{v}" for k, v in (solver.get("window_termination_counts") or {}).items()
        )

    runtime = solver.get("wallclock_s")
    if runtime is None:
        runtime = solver.get("wallclock_s_total")

    gap = solver.get("achieved_gap_rel")
    if gap is None:
        gap = solver.get("achieved_gap_rel_mean")

    gap_max = solver.get("achieved_gap_rel_max")
    if gap_max is None:
        gap_max = gap

    return {
        "heat_balance_residual_abs_max": heat_resid,
        "elec_balance_residual_abs_max": elec_resid,
        "under_mwh": under_mwh,
        "starts": starts,
        "stops": stops,
        "hours_export_at_cap": hours_export_at_cap,
        "termination": termination,
        "achieved_gap_rel": _safe_float(gap),
        "achieved_gap_rel_max": _safe_float(gap_max),
        "runtime_s": _safe_float(runtime),
    }


def _row_for_case(
    scenario_variant: str,
    treatment: str,
    strategy: str,
    summary_path: Path,
) -> Dict[str, Any]:
    summary = _read_json(summary_path)
    out = _extract_qc_and_solver(summary)
    out.update(
        {
            "scenario_variant": scenario_variant,
            "treatment": treatment,
            "strategy": strategy,
            "tag": summary_path.stem.replace("dispatch_summary_pv_grid__", ""),
        }
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build Appendix Table A6: winsorized matched-case QC and solver diagnostics."
    )
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--clean-scenario", default="week_2023_dec01_winsor_p99_fw")
    ap.add_argument("--uc-baseline-tag", default="uc_paper_retained_fw")
    ap.add_argument("--mpc-baseline-tag", default="mpc_paper_retained_fw")
    args = ap.parse_args()

    from chp_pv_sim.paths import ROOT

    base_dir = ROOT / "data" / "scenarios" / args.scenario / "results"
    clean_dir = ROOT / "data" / "scenarios" / args.clean_scenario / "results"

    base_uc = _summary_path(base_dir, args.uc_baseline_tag)
    base_mpc = _summary_path(base_dir, args.mpc_baseline_tag)
    clean_uc = _summary_path(clean_dir, args.uc_baseline_tag)
    clean_mpc = _summary_path(clean_dir, args.mpc_baseline_tag)

    missing = [p for p in [base_uc, base_mpc, clean_uc, clean_mpc] if not p.exists()]
    if missing:
        msg = "Missing summary JSON(s):\n" + "\n".join(str(p) for p in missing)
        raise FileNotFoundError(msg)

    rows = [
        _row_for_case(args.scenario, "retained outlier", "UC", base_uc),
        _row_for_case(args.scenario, "retained outlier", "MPC", base_mpc),
        _row_for_case(args.clean_scenario, "winsorized p99", "UC", clean_uc),
        _row_for_case(args.clean_scenario, "winsorized p99", "MPC", clean_mpc),
    ]

    df = pd.DataFrame(rows)
    df = df[
        [
            "scenario_variant",
            "treatment",
            "strategy",
            "tag",
            "heat_balance_residual_abs_max",
            "elec_balance_residual_abs_max",
            "under_mwh",
            "starts",
            "stops",
            "hours_export_at_cap",
            "termination",
            "achieved_gap_rel",
            "achieved_gap_rel_max",
            "runtime_s",
        ]
    ]

    out_dir = ROOT / "reports" / "robustness"
    _ensure_dir(out_dir)

    csv_path = out_dir / "appendix_A6_winsorized_qc_and_solver.csv"
    md_path = out_dir / "appendix_A6_winsorized_qc_and_solver.md"

    df.to_csv(csv_path, index=False)
    try:
        md_path.write_text(df.to_markdown(index=False), encoding="utf-8")
    except Exception:
        md_path.write_text(df.to_string(index=False), encoding="utf-8")

    print("\n=== Appendix A6 written ===")
    print("CSV:", csv_path)
    print("MD :", md_path)
    print("\nPreview:\n", df.to_string(index=False))


if __name__ == "__main__":
    main()