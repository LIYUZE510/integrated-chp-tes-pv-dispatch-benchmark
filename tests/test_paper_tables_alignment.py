from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(REPORTS / name)


def test_table3_retained_baseline_matches_manuscript_values() -> None:
    df = _read("canonical_table34.csv")

    uc = df.loc[df["tag"] == "uc_paper_retained_fw"].iloc[0]
    mpc = df.loc[df["tag"] == "mpc_paper_retained_fw"].iloc[0]

    assert uc["boiler_share_pct"] == pytest.approx(49.003355, abs=1e-6)
    assert uc["dump_share_pct"] == pytest.approx(1.849632, abs=1e-6)
    assert uc["net_export_mwh"] == pytest.approx(-429.877049, abs=1e-6)

    assert mpc["boiler_share_pct"] == pytest.approx(37.531533, abs=1e-6)
    assert mpc["dump_share_pct"] == pytest.approx(2.756591, abs=1e-6)
    assert mpc["net_export_mwh"] == pytest.approx(370.390044, abs=1e-6)


def test_table6_low_budget_rows_reuse_retained_baseline() -> None:
    df = _read("canonical_table6.csv")
    low = df[df["budget_level"] == "low"].copy()

    assert set(low["tag"]) == {"uc_paper_retained_fw", "mpc_paper_retained_fw"}


def test_table9_crossweek_validation_matches_manuscript_values() -> None:
    df = _read("canonical_table9.csv")

    nov_uc = df[(df["scenario"] == "week_2021_nov15") & (df["tag"] == "uc_crossweek_fw")].iloc[0]
    nov_mpc = df[(df["scenario"] == "week_2021_nov15") & (df["tag"] == "mpc_crossweek_fw")].iloc[0]
    jan_uc = df[(df["scenario"] == "week_2022_jan17") & (df["tag"] == "uc_crossweek_fw")].iloc[0]
    jan_mpc = df[(df["scenario"] == "week_2022_jan17") & (df["tag"] == "mpc_crossweek_fw")].iloc[0]

    assert nov_uc["net_export_mwh"] == pytest.approx(17.890466, abs=1e-6)
    assert nov_mpc["net_export_mwh"] == pytest.approx(333.190600, abs=1e-6)
    assert jan_uc["net_export_mwh"] == pytest.approx(235.456197, abs=1e-6)
    assert jan_mpc["net_export_mwh"] == pytest.approx(1804.778097, abs=1e-6)
