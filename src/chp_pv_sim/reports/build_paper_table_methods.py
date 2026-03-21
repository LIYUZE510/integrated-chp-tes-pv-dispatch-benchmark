from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from chp_pv_sim.paths import ROOT, REPORTS_DIR, ensure_dirs
from chp_pv_sim.reports.result_catalog import build_result_catalog, dedupe_catalog


def _pct(x: float) -> float:
    return 100.0 * float(x)


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument(
        "--keep",
        default="",
        help="optional, comma-separated substrings to keep (case-insensitive). "
             "Example: --keep mpc_eload20MW_dump5,mpc_eload20MW_dump50",
    )
    ap.add_argument("--limit", type=int, default=0, help="0 means no limit")
    ap.add_argument("--include-backups", action="store_true", help="also scan __backup_*.json artifacts")
    ap.add_argument("--include-live", action="store_true", help="also scan dispatch_summary_pv_grid.json")
    args = ap.parse_args()

    scen_dir = ROOT / "data" / "scenarios" / args.scenario
    res_dir = scen_dir / "results"
    if not res_dir.exists():
        raise FileNotFoundError(f"Results dir not found: {res_dir}")

    df = build_result_catalog(res_dir, include_backups=args.include_backups, include_live=args.include_live)
    if df.empty:
        raise FileNotFoundError(
            f"No summary JSON files found under {res_dir}. "
            "Expected tagged files like dispatch_summary_pv_grid__mpc_eload20MW_dump5.json"
        )

    keep_tokens = [t.strip().lower() for t in args.keep.split(",") if t.strip()]
    if keep_tokens:
        mask = df["file"].astype(str).str.lower().map(lambda s: any(tok in s for tok in keep_tokens))
        df = df[mask].copy()
        if df.empty:
            raise RuntimeError(f"No rows left after --keep={keep_tokens}")

    # This is the guardrail that catches the exact reviewer issue:
    # same scenario key but inconsistent KPI values across artifacts.
    df = dedupe_catalog(df)

    df = df.sort_values(["method", "e_load_base_mw", "cost_dump", "created_utc", "file"], na_position="last").reset_index(drop=True)
    if args.limit and args.limit > 0:
        df = df.head(args.limit)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = REPORTS_DIR / f"{args.scenario}__paper_table_methods.csv"
    out_md = REPORTS_DIR / f"{args.scenario}__paper_table_methods.md"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    show = df[[
        "method",
        "e_load_base_mw",
        "cost_dump",
        "boiler_share_pct",
        "dump_share_pct",
        "E_curt_ratio_pct",
        "grid_import_mwh",
        "grid_export_mwh",
        "net_export_mwh",
        "hours_export_at_cap",
        "starts",
        "stops",
        "objective_system_cost",
        "file",
    ]].copy()

    def _fmt_pct(v):
        try:
            return f"{float(v):.2f}%"
        except Exception:
            return str(v)

    for c in ["boiler_share_pct", "dump_share_pct", "E_curt_ratio_pct"]:
        show[c] = show[c].apply(_fmt_pct)
    for c in ["grid_import_mwh", "grid_export_mwh", "net_export_mwh", "objective_system_cost"]:
        show[c] = show[c].apply(lambda v: f"{float(v):.3f}" if pd.notna(v) else "")

    md = []
    md.append(f"# Paper table candidates — {args.scenario}\n\n")
    md.append("- Source files: tagged result summaries (`dispatch_summary_pv_grid__*.json`) only by default.\n")
    if args.include_backups:
        md.append("- Included backup artifacts: yes\n")
    if args.include_live:
        md.append("- Included live summary file: yes\n")
    if keep_tokens:
        md.append(f"- Filter keep = {keep_tokens}\n")
    md.append("- Duplicate scenarios are deduplicated only if all KPIs match; otherwise the script raises an error.\n\n")
    md.append("| " + " | ".join(show.columns) + " |\n")
    md.append("|" + "|".join(["---"] * len(show.columns)) + "|\n")
    for _, r in show.iterrows():
        md.append("| " + " | ".join(str(r[c]) for c in show.columns) + " |\n")
    out_md.write_text("".join(md), encoding="utf-8")

    print("\nWrote:", out_csv)
    print("Wrote:", out_md)
    print("\n=== PAPER TABLE (preview) ===")
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
