from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from chp_pv_sim.paths import RAW_DIR, INTERIM_DIR, REPORTS_DIR, ensure_dirs


RAW_EXTRACT_DIR = RAW_DIR / "kaz_chpp_v3" / "extracted"
OUT_RAW_DIR = INTERIM_DIR / "kaz_chpp_v3" / "raw_sheets"
OUT_AUTO_DIR = INTERIM_DIR / "kaz_chpp_v3" / "auto_tables"

OUT_JSON = REPORTS_DIR / "kaz_chpp_tables_stage.json"
OUT_MD = REPORTS_DIR / "kaz_chpp_tables_stage.md"

SHEETS = [
    "DemEH (Case 1)",
    "DemEH (Case 2)",
    "MaxMin (Case 1)",
    "MaxMin (Case 2)",
    "UnitEff (Case 1)",
    "UnitEff (Case 2)",
    "Turbine(MW)",
]


@dataclass
class AutoTableInfo:
    sheet: str
    raw_shape: tuple[int, int]
    chosen_header_row: int | None
    chosen_shape: tuple[int, int] | None
    chosen_columns: list[str] | None
    unnamed_cols: int | None
    nonnull_cells_ratio: float | None
    notes: list[str]


def _sanitize(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return s[:80] if len(s) > 80 else s


def _read_xls(path: Path, sheet: str, header: int | None) -> pd.DataFrame:
    # engine=xlrd is required for .xls
    return pd.read_excel(path, sheet_name=sheet, header=header, engine="xlrd")


def _score_table(df: pd.DataFrame) -> tuple[float, dict[str, Any]]:
    """
    Score how 'table-like' a df is:
      - fewer unnamed columns is better
      - more non-null cells is better
      - more unique (non-empty) column names is better
    """
    nrows, ncols = df.shape
    if ncols == 0:
        return -1e9, {"reason": "zero columns"}

    cols = [str(c) for c in df.columns]
    unnamed = sum(1 for c in cols if c.lower().startswith("unnamed"))
    # drop completely empty rows/cols for scoring only
    df2 = df.copy()
    df2 = df2.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if df2.shape[1] == 0:
        return -1e9, {"reason": "all columns empty after dropna"}

    nonnull_ratio = float(df2.notna().sum().sum()) / float(df2.shape[0] * df2.shape[1])

    # uniqueness: treat empty strings as bad
    col_clean = [c.strip() for c in cols]
    unique_cols = len(set([c for c in col_clean if c and not c.lower().startswith("unnamed")]))
    unique_ratio = unique_cols / max(1, (ncols - unnamed))

    # weights tuned for excel tables
    score = 3.0 * nonnull_ratio + 1.5 * unique_ratio - 0.5 * (unnamed / max(1, ncols))

    return score, {
        "unnamed": unnamed,
        "nonnull_ratio": nonnull_ratio,
        "unique_ratio": unique_ratio,
        "raw_shape": (nrows, ncols),
        "after_dropna_shape": df2.shape,
    }


def _choose_best_header(xls_path: Path, sheet: str, max_header_row: int = 25) -> tuple[int | None, pd.DataFrame | None, list[str]]:
    notes: list[str] = []
    # First get raw shape with header=None
    raw = _read_xls(xls_path, sheet, header=None)
    raw_shape = raw.shape
    notes.append(f"raw_shape={raw_shape}")

    best_score = -1e18
    best_hr: int | None = None
    best_df: pd.DataFrame | None = None
    best_meta: dict[str, Any] = {}

    # Try header rows 0..max_header_row-1 (bounded by sheet length)
    upper = min(max_header_row, raw_shape[0])
    for hr in range(0, upper):
        try:
            df = _read_xls(xls_path, sheet, header=hr)
        except Exception as e:
            notes.append(f"header={hr} read failed: {repr(e)}")
            continue

        # If everything is NaN, skip
        if df.dropna(axis=0, how="all").dropna(axis=1, how="all").shape[1] == 0:
            continue

        score, meta = _score_table(df)
        if score > best_score:
            best_score = score
            best_hr = hr
            best_df = df
            best_meta = meta

    if best_hr is None or best_df is None:
        notes.append("No suitable header row detected; keeping only raw sheet export.")
        return None, None, notes

    notes.append(f"best_header_row={best_hr}, score={best_score:.4f}, meta={best_meta}")
    return best_hr, best_df, notes


def main() -> None:
    ensure_dirs()
    OUT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_AUTO_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    xls_files = sorted([p for p in RAW_EXTRACT_DIR.rglob("*.xls") if p.is_file()])
    if len(xls_files) != 1:
        raise RuntimeError(f"Expected exactly 1 .xls under {RAW_EXTRACT_DIR}, found {len(xls_files)}")
    xls_path = xls_files[0]

    infos: list[AutoTableInfo] = []

    print("Using xls:", xls_path.name)

    for sheet in SHEETS:
        safe = _sanitize(sheet)
        print("\n---", sheet, "---")

        # Export raw grid (header=None) 100% faithful
        raw = _read_xls(xls_path, sheet, header=None)
        raw_path = OUT_RAW_DIR / f"{safe}.csv"
        raw.to_csv(raw_path, index=False, header=False, encoding="utf-8-sig")
        print("Wrote raw:", raw_path)

        hr, df_best, notes = _choose_best_header(xls_path, sheet)

        if hr is None or df_best is None:
            infos.append(
                AutoTableInfo(
                    sheet=sheet,
                    raw_shape=tuple(map(int, raw.shape)),
                    chosen_header_row=None,
                    chosen_shape=None,
                    chosen_columns=None,
                    unnamed_cols=None,
                    nonnull_cells_ratio=None,
                    notes=notes,
                )
            )
            print("Auto table: NOT DETECTED")
            continue

        # Clean: drop fully empty rows/cols, strip column names
        df = df_best.copy()
        df.columns = [str(c).strip() for c in df.columns]
        df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")

        # Some excel exports have repeated header rows inside; keep them for now (no deletion here).
        auto_csv = OUT_AUTO_DIR / f"{safe}__header{hr}.csv"
        auto_parquet = OUT_AUTO_DIR / f"{safe}__header{hr}.parquet"

        df.to_csv(auto_csv, index=False, encoding="utf-8-sig")
        df.to_parquet(auto_parquet, index=False, engine="pyarrow", compression="zstd")

        unnamed = sum(1 for c in df.columns if str(c).lower().startswith("unnamed"))
        nonnull_ratio = float(df.notna().sum().sum()) / float(df.shape[0] * df.shape[1]) if df.shape[0] * df.shape[1] > 0 else 0.0

        infos.append(
            AutoTableInfo(
                sheet=sheet,
                raw_shape=tuple(map(int, raw.shape)),
                chosen_header_row=int(hr),
                chosen_shape=tuple(map(int, df.shape)),
                chosen_columns=[str(c) for c in df.columns],
                unnamed_cols=int(unnamed),
                nonnull_cells_ratio=float(nonnull_ratio),
                notes=notes,
            )
        )

        print(f"Auto table header row: {hr}")
        print("Auto shape:", df.shape, "| unnamed_cols:", unnamed, "| nonnull_ratio:", f"{nonnull_ratio:.3f}")
        print("Columns:", df.columns.tolist())

        # Print top 5 rows to terminal for quick sanity (won't be huge)
        print(df.head(5).to_string(index=False))

    payload = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "xls": {"filename": xls_path.name, "path": str(xls_path).replace("\\", "/")},
        "tables": [asdict(i) for i in infos],
        "out_raw_dir": str(OUT_RAW_DIR).replace("\\", "/"),
        "out_auto_dir": str(OUT_AUTO_DIR).replace("\\", "/"),
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote:", OUT_JSON)

    # Markdown summary
    md = []
    md.append("# Kazakhstan CHPP Tables Staging Report\n\n")
    md.append(f"- Created (UTC): {payload['created_utc']}\n")
    md.append(f"- Source XLS: `{payload['xls']['filename']}`\n\n")
    md.append("## Auto-detected tables\n\n")
    md.append("| sheet | raw_shape | header_row | auto_shape | unnamed_cols | nonnull_ratio |\n")
    md.append("|---|---:|---:|---:|---:|---:|\n")
    for t in infos:
        md.append(
            f"| {t.sheet} | {t.raw_shape} | "
            f"{t.chosen_header_row if t.chosen_header_row is not None else '-'} | "
            f"{t.chosen_shape if t.chosen_shape is not None else '-'} | "
            f"{t.unnamed_cols if t.unnamed_cols is not None else '-'} | "
            f"{t.nonnull_cells_ratio if t.nonnull_cells_ratio is not None else '-'} |\n"
        )

    md.append("\n## Output locations\n\n")
    md.append(f"- Raw grids: `{payload['out_raw_dir']}` (CSV, header=None)\n")
    md.append(f"- Auto tables: `{payload['out_auto_dir']}` (CSV + Parquet)\n")

    OUT_MD.write_text("".join(md), encoding="utf-8")
    print("Wrote:", OUT_MD)

    print("\nNext: we will convert these auto tables into a unified CHP parameter schema with strict unit checks.")


if __name__ == "__main__":
    main()