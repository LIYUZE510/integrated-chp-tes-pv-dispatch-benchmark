from __future__ import annotations

import json
import math
import re
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from chp_pv_sim.paths import INTERIM_DIR, REPORTS_DIR, ensure_dirs


RAW_SHEETS_DIR = INTERIM_DIR / "kaz_chpp_v3" / "raw_sheets"
OUT_JSON = REPORTS_DIR / "kaz_chpp_block_detect.json"
OUT_MD = REPORTS_DIR / "kaz_chpp_block_detect.md"

TARGET_FILES = [
    "UnitEff_Case_1.csv",
    "UnitEff_Case_2.csv",
    "Turbine_MW.csv",
]


@dataclass
class BlockInfo:
    file: str
    block_id: int
    r0: int
    r1: int
    c0: int
    c1: int
    height: int
    width: int
    bbox_area: int
    nonempty_cells: int
    fill_ratio_in_bbox: float
    numeric_cells: int
    numeric_ratio: float
    sample_preview: str
    excel_range_1based: str


def excel_col_letter(n0: int) -> str:
    """0-based column index -> Excel letters (A, B, ..., AA, AB, ...)"""
    n = n0 + 1
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def excel_range(r0: int, r1: int, c0: int, c1: int) -> str:
    # Excel is 1-based rows
    a = f"{excel_col_letter(c0)}{r0+1}"
    b = f"{excel_col_letter(c1)}{r1+1}"
    return f"{a}:{b}"


_num_re = re.compile(r"^[\s]*[-+]?(?:\d+\.?\d*|\d*\.?\d+)(?:[eE][-+]?\d+)?[\s]*$")


def is_number(x: Any) -> bool:
    if x is None:
        return False
    s = str(x).strip()
    if s == "":
        return False
    # normalize decimal comma
    s = s.replace(",", ".")
    if s.lower() in {"nan", "none", "null"}:
        return False
    if _num_re.match(s) is None:
        return False
    try:
        v = float(s)
    except Exception:
        return False
    return math.isfinite(v)


def load_raw_grid(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, header=None, dtype=str, encoding="utf-8-sig")
    # Normalize blanks -> NaN
    df = df.replace(r"^\s*$", np.nan, regex=True)
    return df


def find_blocks(df: pd.DataFrame) -> list[tuple[list[tuple[int, int]], tuple[int, int, int, int]]]:
    """Find 4-neighbor connected components of non-empty cells."""
    mask = df.notna().to_numpy()
    nrows, ncols = mask.shape
    visited = np.zeros_like(mask, dtype=bool)

    blocks: list[tuple[list[tuple[int, int]], tuple[int, int, int, int]]] = []

    for r in range(nrows):
        for c in range(ncols):
            if not mask[r, c] or visited[r, c]:
                continue
            q = deque([(r, c)])
            visited[r, c] = True
            cells: list[tuple[int, int]] = []
            r0 = r1 = r
            c0 = c1 = c
            while q:
                rr, cc = q.popleft()
                cells.append((rr, cc))
                r0 = min(r0, rr)
                r1 = max(r1, rr)
                c0 = min(c0, cc)
                c1 = max(c1, cc)

                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    r2, c2 = rr + dr, cc + dc
                    if 0 <= r2 < nrows and 0 <= c2 < ncols:
                        if mask[r2, c2] and not visited[r2, c2]:
                            visited[r2, c2] = True
                            q.append((r2, c2))

            blocks.append((cells, (r0, r1, c0, c1)))

    return blocks


def preview_block(df: pd.DataFrame, r0: int, r1: int, c0: int, c1: int, max_rows: int = 12, max_cols: int = 10) -> str:
    sub = df.iloc[r0 : r1 + 1, c0 : c1 + 1].copy()
    sub = sub.fillna("")
    # Trim preview
    sub = sub.iloc[:max_rows, :max_cols]
    # Add row/col indices for context
    sub.index = [f"r{r0+i}" for i in range(sub.shape[0])]
    sub.columns = [f"c{c0+j}" for j in range(sub.shape[1])]
    return sub.to_string()


def analyze_file(path: Path) -> list[BlockInfo]:
    df = load_raw_grid(path)
    blocks = find_blocks(df)

    infos: list[BlockInfo] = []

    for bid, (cells, (r0, r1, c0, c1)) in enumerate(blocks, start=1):
        height = r1 - r0 + 1
        width = c1 - c0 + 1
        bbox_area = height * width
        nonempty = len(cells)

        # Fill ratio of bbox
        fill_ratio = nonempty / bbox_area if bbox_area > 0 else 0.0

        # Numeric ratio (within connected cells)
        numeric = 0
        for (rr, cc) in cells:
            if is_number(df.iat[rr, cc]):
                numeric += 1
        numeric_ratio = numeric / nonempty if nonempty > 0 else 0.0

        # We ignore tiny blobs (e.g., single cell "0.9.3")
        # But we still keep them in JSON; later we'll filter for "table-like".
        prev = preview_block(df, r0, r1, c0, c1)

        infos.append(
            BlockInfo(
                file=path.name,
                block_id=bid,
                r0=int(r0),
                r1=int(r1),
                c0=int(c0),
                c1=int(c1),
                height=int(height),
                width=int(width),
                bbox_area=int(bbox_area),
                nonempty_cells=int(nonempty),
                fill_ratio_in_bbox=float(fill_ratio),
                numeric_cells=int(numeric),
                numeric_ratio=float(numeric_ratio),
                sample_preview=prev,
                excel_range_1based=excel_range(r0, r1, c0, c1),
            )
        )

    # Sort: prefer larger nonempty cell count, then bbox_area, then numeric_ratio
    infos.sort(key=lambda x: (x.nonempty_cells, x.bbox_area, x.numeric_ratio), reverse=True)
    return infos


def main() -> None:
    ensure_dirs()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    missing = [fn for fn in TARGET_FILES if not (RAW_SHEETS_DIR / fn).exists()]
    if missing:
        raise FileNotFoundError(f"Missing raw sheet CSV(s) under {RAW_SHEETS_DIR}: {missing}")

    all_infos: dict[str, list[BlockInfo]] = {}

    for fn in TARGET_FILES:
        path = RAW_SHEETS_DIR / fn
        print("\n==============================")
        print("Analyzing:", path.name)
        infos = analyze_file(path)
        all_infos[fn] = infos

        # Print top candidates to terminal (keep it readable)
        top = infos[:8]
        for b in top:
            print(
                f"\n[Block {b.block_id}] excel={b.excel_range_1based} "
                f"bbox={b.height}x{b.width} area={b.bbox_area} "
                f"nonempty={b.nonempty_cells} fill={b.fill_ratio_in_bbox:.3f} "
                f"numeric={b.numeric_cells} num_ratio={b.numeric_ratio:.3f}"
            )
            print(b.sample_preview)

    payload = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "raw_dir": str(RAW_SHEETS_DIR).replace("\\", "/"),
        "files": {fn: [asdict(b) for b in infos] for fn, infos in all_infos.items()},
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote:", OUT_JSON)

    # Markdown report
    md = []
    md.append("# Kazakhstan CHPP Block Detection Report\n\n")
    md.append(f"- Created (UTC): {payload['created_utc']}\n")
    md.append(f"- Raw sheets dir: `{payload['raw_dir']}`\n\n")

    for fn, infos in all_infos.items():
        md.append(f"## {fn}\n\n")
        md.append("| rank | block_id | excel_range | bbox(h×w) | nonempty | fill_ratio | numeric_ratio |\n")
        md.append("|---:|---:|---|---:|---:|---:|---:|\n")
        for rank, b in enumerate(infos[:12], start=1):
            md.append(
                f"| {rank} | {b.block_id} | {b.excel_range_1based} | {b.height}×{b.width} | "
                f"{b.nonempty_cells} | {b.fill_ratio_in_bbox:.3f} | {b.numeric_ratio:.3f} |\n"
            )
        md.append("\n### Top block previews\n\n")
        for b in infos[:6]:
            md.append(
                f"**Block {b.block_id}** — excel `{b.excel_range_1based}` | "
                f"bbox={b.height}×{b.width} | nonempty={b.nonempty_cells} | "
                f"fill={b.fill_ratio_in_bbox:.3f} | numeric_ratio={b.numeric_ratio:.3f}\n\n"
            )
            md.append("```text\n")
            md.append(b.sample_preview)
            md.append("\n```\n\n")

    OUT_MD.write_text("".join(md), encoding="utf-8")
    print("Wrote:", OUT_MD)

    print("\nNext: we'll pick the correct table blocks for UnitEff and Turbine and extract them into a strict CHP parameter schema.")


if __name__ == "__main__":
    main()