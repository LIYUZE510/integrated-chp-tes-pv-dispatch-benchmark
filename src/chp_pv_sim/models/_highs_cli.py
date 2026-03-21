from __future__ import annotations


def add_highs_cli_args(parser, *, default_time_limit_s: float, default_mip_rel_gap: float) -> None:
    """
    Add robust CLI aliases for HiGHS controls.
    Supports both hyphen and underscore styles.
    """
    parser.add_argument(
        "--time-limit-s", "--time_limit_s",
        dest="time_limit_s",
        type=float,
        default=float(default_time_limit_s),
        help=f"HiGHS time limit in seconds (default: {default_time_limit_s}).",
    )
    parser.add_argument(
        "--mip-rel-gap", "--mip_rel_gap",
        dest="mip_rel_gap",
        type=float,
        default=float(default_mip_rel_gap),
        help=f"Relative MIP gap target (default: {default_mip_rel_gap}).",
    )


def apply_highs_options(solver, *, time_limit_s: float, mip_rel_gap: float):
    """
    Robustly apply HiGHS options for both legacy and appsi-style solvers.
    """
    applied = False

    # legacy/standard style
    opts = getattr(solver, "options", None)
    if opts is not None:
        opts["time_limit"] = float(time_limit_s)
        opts["mip_rel_gap"] = float(mip_rel_gap)
        applied = True

    # appsi_highs style
    hopts = getattr(solver, "highs_options", None)
    if hopts is not None:
        hopts["time_limit"] = float(time_limit_s)
        hopts["mip_rel_gap"] = float(mip_rel_gap)
        applied = True

    # config-style fallback
    cfg = getattr(solver, "config", None)
    if cfg is not None:
        if hasattr(cfg, "time_limit"):
            cfg.time_limit = float(time_limit_s)
            applied = True
        if hasattr(cfg, "mip_rel_gap"):
            cfg.mip_rel_gap = float(mip_rel_gap)
            applied = True

    if not applied:
        print("[WARN] Could not confirm HiGHS option attachment; please verify solver type/options manually.")

    return solver