from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from chp_pv_sim.paths import PROCESSED_DIR, REPORTS_DIR, ensure_dirs


IN_HEAT = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_heat_segments.parquet"
IN_POWER = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_power_segments.parquet"

OUT_HEAT = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_heat_segments_consistent.parquet"
OUT_POWER = PROCESSED_DIR / "kaz_chpp_v3" / "shared" / "turbine_power_segments_consistent.parquet"

QC_JSON = REPORTS_DIR / "kaz_chpp_segments_consistency_qc.json"
QC_MD = REPORTS_DIR / "kaz_chpp_segments_consistency_qc.md"


def _require_cols(df: pd.DataFrame, cols: list[str], name: str) -> None:
    miss = [c for c in cols if c not in df.columns]
    if miss:
        raise KeyError(f"{name}: missing columns {miss}. Available: {df.columns.tolist()}")


def make_consistent(
    df: pd.DataFrame,
    *,
    axis: str,
    k_col: str,
    b_col: str,
    axis_lb_col: str,
    axis_ub_col: str,
    q_lb_col: str = "q_lb",
    q_ub_col: str = "q_ub",
    tol: float = 1e-6,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Build effective bounds consistent with the line Q = k*axis + b AND provided axis/Q bounds.

    For k > 0 (true here):
      Q on the line over [axis_lb, axis_ub] spans [q_at_axis_lb, q_at_axis_ub].
      Feasible Q is intersection with [q_lb, q_ub]:
         q_lb_eff = max(q_lb, q_min_line)
         q_ub_eff = min(q_ub, q_max_line)
      Then implied effective axis bounds are:
         axis_lb_eff = (q_lb_eff - b)/k
         axis_ub_eff = (q_ub_eff - b)/k
    """
    df = df.copy()

    _require_cols(df, ["temp_label", "segment", k_col, b_col, axis_lb_col, axis_ub_col, q_lb_col, q_ub_col], f"{axis} segments")

    for c in [k_col, b_col, axis_lb_col, axis_ub_col, q_lb_col, q_ub_col]:
        df[c] = pd.to_numeric(df[c], errors="raise")

    if (df[k_col] <= 0).any():
        bad = df.loc[df[k_col] <= 0, ["temp_label", "segment", k_col]].head(10)
        raise ValueError(f"Expected all {k_col} > 0 for {axis} segments; found non-positive:\n{bad}")

    k = df[k_col].to_numpy(dtype=float)
    b = df[b_col].to_numpy(dtype=float)
    axis_lb = df[axis_lb_col].to_numpy(dtype=float)
    axis_ub = df[axis_ub_col].to_numpy(dtype=float)
    q_lb = df[q_lb_col].to_numpy(dtype=float)
    q_ub = df[q_ub_col].to_numpy(dtype=float)

    q_at_axis_lb = k * axis_lb + b
    q_at_axis_ub = k * axis_ub + b

    q_min_line = np.minimum(q_at_axis_lb, q_at_axis_ub)
    q_max_line = np.maximum(q_at_axis_lb, q_at_axis_ub)

    q_lb_eff = np.maximum(q_lb, q_min_line)
    q_ub_eff = np.minimum(q_ub, q_max_line)

    feasible = q_lb_eff <= (q_ub_eff + 1e-9)

    axis_lb_eff = (q_lb_eff - b) / k
    axis_ub_eff = (q_ub_eff - b) / k

    axis_lb_shift = axis_lb_eff - axis_lb
    axis_ub_shift = axis_ub - axis_ub_eff

    df[f"q_at_{axis.lower()}_lb"] = q_at_axis_lb
    df[f"q_at_{axis.lower()}_ub"] = q_at_axis_ub
    df["q_min_line"] = q_min_line
    df["q_max_line"] = q_max_line

    df["q_lb_eff"] = q_lb_eff
    df["q_ub_eff"] = q_ub_eff
    df[f"{axis.lower()}_lb_eff"] = axis_lb_eff
    df[f"{axis.lower()}_ub_eff"] = axis_ub_eff

    df[f"{axis.lower()}_lb_shift"] = axis_lb_shift
    df[f"{axis.lower()}_ub_shift"] = axis_ub_shift

    df["q_lb_active"] = q_lb > (q_min_line + tol)
    df["q_ub_active"] = q_ub < (q_max_line - tol)
    df["segment_infeasible"] = ~feasible

    qc = {
        "axis": axis,
        "rows": int(len(df)),
        "temps": sorted(df["temp_label"].dropna().unique().tolist()),
        "n_infeasible": int((~feasible).sum()),
        "n_q_lb_active": int(df["q_lb_active"].sum()),
        "n_q_ub_active": int(df["q_ub_active"].sum()),
        "max_axis_lb_shift": float(np.max(axis_lb_shift)),
        "max_axis_ub_shift": float(np.max(axis_ub_shift)),
        "max_q_lb_gap": float(np.max(q_lb_eff - q_lb)),
        "max_q_ub_gap": float(np.max(q_ub - q_ub_eff)),
    }

    df_tmp = df.copy()
    df_tmp["axis_lb_shift_abs"] = np.abs(axis_lb_shift)
    df_tmp["axis_ub_shift_abs"] = np.abs(axis_ub_shift)

    worst_lb = df_tmp.sort_values("axis_lb_shift_abs", ascending=False).head(5)[
        ["temp_label", "segment", axis_lb_col, f"{axis.lower()}_lb_eff", f"{axis.lower()}_lb_shift", "q_lb", "q_lb_eff", "q_min_line"]
    ].to_dict(orient="records")
    worst_ub = df_tmp.sort_values("axis_ub_shift_abs", ascending=False).head(5)[
        ["temp_label", "segment", axis_ub_col, f"{axis.lower()}_ub_eff", f"{axis.lower()}_ub_shift", "q_ub", "q_ub_eff", "q_max_line"]
    ].to_dict(orient="records")

    qc["worst_lb_shift_examples"] = worst_lb
    qc["worst_ub_shift_examples"] = worst_ub

    return df, qc


def main() -> None:
    ensure_dirs()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HEAT.parent.mkdir(parents=True, exist_ok=True)

    if not IN_HEAT.exists() or not IN_POWER.exists():
        raise FileNotFoundError("Missing turbine segment inputs. Run kaz_chpp_build_params first.")

    heat = pd.read_parquet(IN_HEAT)
    power = pd.read_parquet(IN_POWER)

    heat2, qc_h = make_consistent(
        heat,
        axis="H",
        k_col="k_hq",
        b_col="b_hq",
        axis_lb_col="h_lb",
        axis_ub_col="h_ub",
    )
    power2, qc_e = make_consistent(
        power,
        axis="E",
        k_col="k_eh",
        b_col="b_eh",
        axis_lb_col="e_lb",
        axis_ub_col="e_ub",
    )

    heat2.to_parquet(OUT_HEAT, index=False, engine="pyarrow", compression="zstd")
    power2.to_parquet(OUT_POWER, index=False, engine="pyarrow", compression="zstd")

    payload = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "inputs": {"heat": str(IN_HEAT).replace("\\", "/"), "power": str(IN_POWER).replace("\\", "/")},
        "outputs": {"heat": str(OUT_HEAT).replace("\\", "/"), "power": str(OUT_POWER).replace("\\", "/")},
        "qc_heat": qc_h,
        "qc_power": qc_e,
    }

    QC_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = []
    md.append("# Kazakhstan CHPP Turbine Segment Consistency QC\n\n")
    md.append(f"- Generated (UTC): {payload['created_utc']}\n\n")
    md.append("## Heat segments (H)\n\n")
    md.append(f"- rows: {qc_h['rows']}\n")
    md.append(f"- temps: {', '.join(qc_h['temps'])}\n")
    md.append(f"- infeasible segments: {qc_h['n_infeasible']}\n")
    md.append(f"- q_lb active segments: {qc_h['n_q_lb_active']}\n")
    md.append(f"- q_ub active segments: {qc_h['n_q_ub_active']}\n")
    md.append(f"- max H_lb shift: {qc_h['max_axis_lb_shift']:.6g}\n")
    md.append(f"- max H_ub shift: {qc_h['max_axis_ub_shift']:.6g}\n\n")

    md.append("## Power segments (E)\n\n")
    md.append(f"- rows: {qc_e['rows']}\n")
    md.append(f"- temps: {', '.join(qc_e['temps'])}\n")
    md.append(f"- infeasible segments: {qc_e['n_infeasible']}\n")
    md.append(f"- q_lb active segments: {qc_e['n_q_lb_active']}\n")
    md.append(f"- q_ub active segments: {qc_e['n_q_ub_active']}\n")
    md.append(f"- max E_lb shift: {qc_e['max_axis_lb_shift']:.6g}\n")
    md.append(f"- max E_ub shift: {qc_e['max_axis_ub_shift']:.6g}\n\n")

    md.append("## Worst examples\n\n")
    md.append("### Heat (largest lower-bound shifts)\n\n```json\n")
    md.append(json.dumps(qc_h["worst_lb_shift_examples"], ensure_ascii=False, indent=2))
    md.append("\n```\n\n### Power (largest lower-bound shifts)\n\n```json\n")
    md.append(json.dumps(qc_e["worst_lb_shift_examples"], ensure_ascii=False, indent=2))
    md.append("\n```\n")

    QC_MD.write_text("".join(md), encoding="utf-8")

    print("Wrote:")
    print("  -", OUT_HEAT)
    print("  -", OUT_POWER)
    print("  -", QC_JSON)
    print("  -", QC_MD)

    print("\n=== CONSISTENCY QC SUMMARY ===")
    print("Heat QC:", qc_h)
    print("Power QC:", qc_e)
    print("\nNext: use *_consistent.parquet for MILP feasible-set construction.")


if __name__ == "__main__":
    main()