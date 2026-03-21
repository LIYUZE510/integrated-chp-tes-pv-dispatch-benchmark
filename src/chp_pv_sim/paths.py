from __future__ import annotations

from pathlib import Path

# Project root = .../smartcities_chp_pv_sim
ROOT: Path = Path(__file__).resolve().parents[2]

DATA_DIR: Path = ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
EXTERNAL_DIR: Path = DATA_DIR / "external"
INTERIM_DIR: Path = DATA_DIR / "interim"
PROCESSED_DIR: Path = DATA_DIR / "processed"

CONFIG_DIR: Path = ROOT / "configs"
NOTEBOOKS_DIR: Path = ROOT / "notebooks"
REPORTS_DIR: Path = ROOT / "reports"
FIGURES_DIR: Path = REPORTS_DIR / "figures"
OUTPUTS_DIR: Path = ROOT / "outputs"
LOGS_DIR: Path = ROOT / "logs"


def ensure_dirs() -> None:
    """Create required directories if they do not exist."""
    for p in [
        RAW_DIR,
        EXTERNAL_DIR,
        INTERIM_DIR,
        PROCESSED_DIR,
        FIGURES_DIR,
        OUTPUTS_DIR,
        LOGS_DIR,
    ]:
        p.mkdir(parents=True, exist_ok=True)