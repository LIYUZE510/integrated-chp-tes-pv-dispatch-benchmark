from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from chp_pv_sim.paths import ROOT, ensure_dirs


def _p(x: float) -> str:
    return f"{100.0 * x:.2f}%"


def main() -> None:
    ensure_dirs()

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="week_2023_dec01")
    ap.add_argument("--tag", required=True, help="e.g. mpc_eload20MW or mpc_eload30MW")
    ap.add_argument("--soc_hi", type=float, default=0.99, help="SOC high threshold ratio")
    ap.add_argument("--soc_lo", type=float, default=0.01, help="SOC low threshold ratio")
    ap.add_argument("--eps", type=float, default=1e-6)
    args = ap.parse_args()

    res_dir = ROOT / "data" / "scenarios" / args.scenario / "results"
    f = res_dir / f"dispatch_chp_storage_pv_grid__{args.tag}.parquet"
    if not f.exists():
        raise FileNotFoundError(f"Missing dispatch parquet: {f}")

    df = pd.read_parquet(f)
    df["datetime_local"] = pd.to_datetime(df["datetime_local"])

    # infer SOC bounds from trajectory (works even if solver doesn't hit exact cap)
    s_series = pd.concat([df["S_mwh"], df.get("S_next_mwh", df["S_mwh"])], axis=0)
    s_min = float(s_series.min())
    s_max = float(s_series.max())
    s_rng = max(1e-9, s_max - s_min)

    soc_hi = s_min + args.soc_hi * s_rng
    soc_lo = s_min + args.soc_lo * s_rng

    near_hi = df["S_mwh"] >= (soc_hi - 1e-9)
    near_lo = df["S_mwh"] <= (soc_lo + 1e-9)

    dump_pos = df["dump_mw"] > args.eps
    imp_pos = df["grid_import_mw"] > args.eps
    exp_pos = df["grid_export_mw"] > args.eps
    curt_pos = df["chp_curt_mw"] > args.eps

    heat = float(df["heat_demand_mw"].sum())
    dump = float(df["dump_mw"].sum())
    boiler = float(df["boiler_mw"].sum())
    under = float(df["under_mw"].sum())

    e_chp = float(df["E_chp_mw"].sum())
    e_curt = float(df["chp_curt_mw"].sum())
    gimp = float(df["grid_import_mw"].sum())
    gexp = float(df["grid_export_mw"].sum())

    print("\n==============================")
    print(f"Inspect tag = {args.tag}")
    print(f"File        = {f.name}")
    print(f"Hours       = {len(df)}")
    print(f"S_min/S_max = {s_min:.3f} / {s_max:.3f} (range {s_rng:.3f})")
    print(f"SOC hi/lo   = >= {soc_hi:.3f} (hi), <= {soc_lo:.3f} (lo)")
    print("------------------------------")

    print("Totals:")
    print(f"  heat_demand_mwh = {heat:.3f}")
    print(f"  boiler_mwh      = {boiler:.3f} ({_p(boiler/heat) if heat>1e-9 else 'n/a'})")
    print(f"  dump_mwh        = {dump:.3f} ({_p(dump/heat) if heat>1e-9 else 'n/a'})")
    print(f"  under_mwh       = {under:.6f}")

    print("Electric:")
    print(f"  E_chp_mwh       = {e_chp:.3f}")
    print(f"  E_curt_mwh      = {e_curt:.3f} ({_p(e_curt/e_chp) if e_chp>1e-9 else 'n/a'})")
    print(f"  grid_import_mwh = {gimp:.3f}")
    print(f"  grid_export_mwh = {gexp:.3f}")
    print(f"  net_export_mwh  = {gexp-gimp:.3f}")

    def _share(mask, base_mask, label):
        base = int(base_mask.sum())
        if base == 0:
            return "0/0"
        return f"{int((mask & base_mask).sum())}/{base} ({_p(((mask & base_mask).sum())/base)})"

    print("\nEvent shares:")
    print(f"  dump hours            : {int(dump_pos.sum())}/{len(df)}")
    print(f"    dump AND SOC near-hi : {_share(near_hi, dump_pos, 'dump@hi')}")
    print(f"    dump AND SOC near-lo : {_share(near_lo, dump_pos, 'dump@lo')}")
    print(f"  import hours          : {int(imp_pos.sum())}/{len(df)}")
    print(f"    import AND SOC near-lo: {_share(near_lo, imp_pos, 'imp@lo')}")
    print(f"  export hours          : {int(exp_pos.sum())}/{len(df)}")
    print(f"  curtail hours         : {int(curt_pos.sum())}/{len(df)}")

    # Top dump hours
    show_cols = [
        "datetime_local",
        "heat_demand_mw",
        "H_chp_mw",
        "boiler_mw",
        "dump_mw",
        "ch_mw",
        "dis_mw",
        "S_mwh",
        "S_next_mwh",
        "E_chp_mw",
        "chp_curt_mw",
        "grid_import_mw",
        "grid_export_mw",
        "pv_avail_mw",
    ]
    print("\nTop 10 dump hours:")
    top_dump = df.sort_values("dump_mw", ascending=False).head(10)[show_cols]
    print(top_dump.to_string(index=False))

    print("\nTop 10 import hours:")
    top_imp = df.sort_values("grid_import_mw", ascending=False).head(10)[show_cols]
    print(top_imp.to_string(index=False))


if __name__ == "__main__":
    main()