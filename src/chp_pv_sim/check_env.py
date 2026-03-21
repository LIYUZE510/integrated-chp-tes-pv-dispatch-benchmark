from __future__ import annotations

import platform
import sys

import numpy as np
import pandas as pd
import pyomo
import pvlib

try:
    import highspy  # type: ignore
except Exception as e:  # pragma: no cover
    highspy = None
    _highs_import_error = e
else:
    _highs_import_error = None

from chp_pv_sim.paths import ROOT, ensure_dirs


def _ver(mod) -> str:
    return getattr(mod, "__version__", "unknown")


def main() -> None:
    ensure_dirs()

    print("Platform :", platform.platform())
    print("Python   :", sys.version.split()[0])
    print("numpy    :", np.__version__)
    print("pandas   :", pd.__version__)
    print("pyomo    :", pyomo.__version__)
    print("pvlib    :", _ver(pvlib))

    if highspy is None:
        print("highspy  : IMPORT FAILED ->", repr(_highs_import_error))
    else:
        print("highspy  :", _ver(highspy))

    print("Project root:", str(ROOT))


if __name__ == "__main__":
    main()