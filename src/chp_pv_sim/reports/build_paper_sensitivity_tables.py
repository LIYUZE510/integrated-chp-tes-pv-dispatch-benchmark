from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from chp_pv_sim.paths import ROOT, REPORTS_DIR, ensure_dirs
from chp_pv_sim.reports.result_catalog import build_result_catalog, dedupe_catalog


def _parse_float_list(text: str) -> list[float]:
    vals = [float(x.strip()) for x in text.split(",") if x.strip()]
    if not vals:
        raise ValueError(f"No numeric values parsed from: {text}")
    return vals


def _close_mask(s: pd.Series, target: float, atol: float = 1e-9) -> pd.Series:
    return (pd.to_numeric(s, errors="coerce") - float(target)).abs() <= float(atol)


def _md_table(df: pd.DataFrame) -> str:
    lines = []
    cols = list(df.columns)
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def _format_table(df: pd.DataFrame, axis: str) -> pd.DataFrame:
    if axis == "eload":
        cols = [
            "e_load_base_mw",
            "cost_dump",
            "boiler_share_pct",
            "dump_share_pct",
            "E_curt_ratio_pct",
            "grid_import_mwh",
            "grid_export_mwh",
            "net_export_mwh",
            "starts",
            "stops",
            "file",
        ]
    else:
        cols = [
            "cost_dump",
            "e_load_base_mw",
            "boiler_share_pct",
            "dump_share_pct",
            "E_curt_ratio_pct",
            "grid_import_mwh",
            "grid_export_mwh",
            "net_export_mwh",
            "starts",
            "stops",
            "file",
        ]
    show = df[cols].copy()
    for c in ["boiler_share_pct", "dump_share_pct", "E_curt_ratio_pct"]:
        show[c] = show[c].map(lambda v: f"{float(v):.2f}%" if pd.notna(v) else "")
    for c in ["grid_import_mwh", "grid_export_mwh", "net_export_mwh"]:
        show[c] = show[c].map(lambda v: f"{float(v):.3f}" if pd.notna(v) else "")
    return show


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser(
        description="Build canonical paper sensitivity tables from the tagged result catalog."
    )
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--method", default="MPC", choices=["MPC", "Full-week UC", "Full-week"])
    ap.add_argument("--eloads", default="0,10,20,30")
    ap.add_argument("--dump-costs", default="5,20,50,100")
    ap.add_argument("--fixed-dump", type=float, default=5.0)
    ap.add_argument("--fixed-eload", type=float, default=20.0)
    ap.add_argument("--include-backups", action="store_true")
    ap.add_argument("--include-live", action="store_true")
    args = ap.parse_args()

    eloads = _parse_float_list(args.eloads)
    dump_costs = _parse_float_list(args.dump_costs)

    res_dir = ROOT / "data" / "scenarios" / args.scenario / "results"
    if not res_dir.exists():
        raise FileNotFoundError(f"Missing results dir: {res_dir}")

    catalog = build_result_catalog(res_dir, include_backups=args.include_backups, include_live=args.include_live)
    if catalog.empty:
        raise RuntimeError(f"No tagged result summaries found in {res_dir}")

    catalog = dedupe_catalog(catalog)
    catalog = catalog[catalog["method"] == args.method].copy()
    if catalog.empty:
        raise RuntimeError(f"No rows left for method={args.method}")

    # Write a canonical deduped catalog once, then slice both tables from the same source.
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    catalog_csv = REPORTS_DIR / f"{args.scenario}__result_catalog_deduped.csv"
    catalog.to_csv(catalog_csv, index=False, encoding="utf-8-sig")

    t5 = catalog[_close_mask(catalog["cost_dump"], args.fixed_dump)].copy()
    t5 = t5[t5["e_load_base_mw"].isin(eloads)].copy()
    t5 = t5.sort_values("e_load_base_mw").reset_index(drop=True)
    missing_eloads = sorted(set(eloads) - set(pd.to_numeric(t5["e_load_base_mw"], errors="coerce").dropna().tolist()))
    if missing_eloads:
        raise RuntimeError(f"Table 5 is missing e_load points at cost_dump={args.fixed_dump}: {missing_eloads}")

    t6 = catalog[_close_mask(catalog["e_load_base_mw"], args.fixed_eload)].copy()
    t6 = t6[t6["cost_dump"].isin(dump_costs)].copy()
    t6 = t6.sort_values("cost_dump").reset_index(drop=True)
    missing_dump = sorted(set(dump_costs) - set(pd.to_numeric(t6["cost_dump"], errors="coerce").dropna().tolist()))
    if missing_dump:
        raise RuntimeError(f"Table 6 is missing dump-cost points at e_load={args.fixed_eload}: {missing_dump}")

    # Explicitly verify that the shared intersection row is identical because both tables are cut
    # from the same deduped catalog.
    inter = catalog[_close_mask(catalog["e_load_base_mw"], args.fixed_eload) & _close_mask(catalog["cost_dump"], args.fixed_dump)].copy()
    if len(inter) != 1:
        raise RuntimeError(
            f"Expected exactly one canonical intersection row for (e_load={args.fixed_eload}, cost_dump={args.fixed_dump}), got {len(inter)}"
        )

    t5_show = _format_table(t5, axis="eload")
    t6_show = _format_table(t6, axis="dump")

    t5_base = REPORTS_DIR / f"{args.scenario}__table5_eload_sweep__dump{int(args.fixed_dump) if float(args.fixed_dump).is_integer() else str(args.fixed_dump).replace('.', 'p')}"
    t6_base = REPORTS_DIR / f"{args.scenario}__table6_dumpcost_sweep__eload{int(args.fixed_eload) if float(args.fixed_eload).is_integer() else str(args.fixed_eload).replace('.', 'p')}"

    t5.to_csv(t5_base.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    t6.to_csv(t6_base.with_suffix(".csv"), index=False, encoding="utf-8-sig")

    md5 = []
    md5.append(f"# Table 5 canonical source — {args.scenario}\n\n")
    md5.append(f"- Method: {args.method}\n")
    md5.append(f"- Fixed cost_dump = {args.fixed_dump}\n")
    md5.append(f"- Source catalog: `{catalog_csv.name}`\n\n")
    md5.append(_md_table(t5_show))
    t5_base.with_suffix(".md").write_text("".join(md5), encoding="utf-8")

    md6 = []
    md6.append(f"# Table 6 canonical source — {args.scenario}\n\n")
    md6.append(f"- Method: {args.method}\n")
    md6.append(f"- Fixed e_load_base = {args.fixed_eload} MW\n")
    md6.append(f"- Source catalog: `{catalog_csv.name}`\n\n")
    md6.append(_md_table(t6_show))
    t6_base.with_suffix(".md").write_text("".join(md6), encoding="utf-8")

    print("Wrote:", catalog_csv)
    print("Wrote:", t5_base.with_suffix(".csv"))
    print("Wrote:", t5_base.with_suffix(".md"))
    print("Wrote:", t6_base.with_suffix(".csv"))
    print("Wrote:", t6_base.with_suffix(".md"))
    print("\nIntersection row reused by both tables:")
    print(inter[["method", "e_load_base_mw", "cost_dump", "dump_share_pct", "net_export_mwh", "file"]].to_string(index=False))


if __name__ == "__main__":
    main()
