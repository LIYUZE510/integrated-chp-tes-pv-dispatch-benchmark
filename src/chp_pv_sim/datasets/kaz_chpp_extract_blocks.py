from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from chp_pv_sim.paths import ROOT, REPORTS_DIR, ensure_dirs


CONFIG_PATH = ROOT / "configs" / "kaz_chpp_blocks.yaml"
OUT_JSON = REPORTS_DIR / "kaz_chpp_blocks_extract.json"
OUT_MD = REPORTS_DIR / "kaz_chpp_blocks_extract.md"


_range_re = re.compile(r"^\s*([A-Za-z]+)(\d+)\s*:\s*([A-Za-z]+)(\d+)\s*$")


def col_letters_to_index(letters: str) -> int:
    letters = letters.strip().upper()
    n = 0
    for ch in letters:
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"Invalid column letter: {letters}")
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1  # 0-based


def index_to_col_letters(idx0: int) -> str:
    n = idx0 + 1
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def parse_excel_range(rng: str) -> tuple[int, int, int, int]:
    m = _range_re.match(rng)
    if not m:
        raise ValueError(f"Bad excel_range format: {rng} (expected like A1:G39)")
    c0 = col_letters_to_index(m.group(1))
    r0 = int(m.group(2)) - 1
    c1 = col_letters_to_index(m.group(3))
    r1 = int(m.group(4)) - 1
    if r0 > r1 or c0 > c1:
        raise ValueError(f"Invalid excel_range ordering: {rng}")
    return r0, r1, c0, c1


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ExtractedBlock:
    raw_file: str
    block_name: str
    excel_range: str
    shape: tuple[int, int]
    out_csv: str
    out_parquet: str
    sha256_csv: str
    sha256_parquet: str
    preview_head: str


def load_raw_grid(path: Path) -> pd.DataFrame:
    # raw_sheets were exported with header=None and utf-8-sig
    df = pd.read_csv(path, header=None, dtype=str, encoding="utf-8-sig")
    # normalize blank strings -> NaN
    df = df.replace(r"^\s*$", np.nan, regex=True)
    return df


def extract_block(df_raw: pd.DataFrame, excel_rng: str) -> pd.DataFrame:
    r0, r1, c0, c1 = parse_excel_range(excel_rng)
    if r1 >= df_raw.shape[0] or c1 >= df_raw.shape[1]:
        raise IndexError(
            f"Range {excel_rng} out of bounds for raw grid shape {df_raw.shape} (0-based max r={df_raw.shape[0]-1}, c={df_raw.shape[1]-1})"
        )

    sub = df_raw.iloc[r0 : r1 + 1, c0 : c1 + 1].copy()

    # label columns by Excel letters for transparency
    col_letters = [index_to_col_letters(c) for c in range(c0, c1 + 1)]
    sub.columns = col_letters

    # add excel_row to keep absolute row anchor
    sub.insert(0, "excel_row", list(range(r0 + 1, r1 + 2)))  # back to 1-based row numbers

    return sub


def safe_name(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:100] if len(s) > 100 else s


def main() -> None:
    ensure_dirs()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw_dir = (ROOT / cfg["raw_sheets_dir"]).resolve()
    out_dir = (ROOT / cfg["out_blocks_dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    blocks_cfg = cfg["blocks"]
    extracted: list[ExtractedBlock] = []

    print("Config:", str(CONFIG_PATH))
    print("Raw sheets dir:", str(raw_dir))
    print("Out blocks dir:", str(out_dir))

    for item in blocks_cfg:
        raw_file = item["raw_file"]
        block_name = item["block_name"]
        excel_rng = item["excel_range"]

        raw_path = raw_dir / raw_file
        if not raw_path.exists():
            raise FileNotFoundError(f"Missing raw sheet file: {raw_path}")

        df_raw = load_raw_grid(raw_path)
        df_blk = extract_block(df_raw, excel_rng)

        base = safe_name(Path(raw_file).stem)
        bname = safe_name(block_name)
        rng_name = safe_name(excel_rng.replace(":", "_"))

        out_csv = out_dir / f"{base}__{bname}__{rng_name}.csv"
        out_parquet = out_dir / f"{base}__{bname}__{rng_name}.parquet"

        # Write exactly as strings (no numeric conversion)
        df_blk.to_csv(out_csv, index=False, encoding="utf-8-sig")
        df_blk.to_parquet(out_parquet, index=False, engine="pyarrow", compression="zstd")

        sha_csv = sha256_file(out_csv)
        sha_parq = sha256_file(out_parquet)

        preview = df_blk.head(8).fillna("").to_string(index=False)

        extracted.append(
            ExtractedBlock(
                raw_file=raw_file,
                block_name=block_name,
                excel_range=excel_rng,
                shape=(int(df_blk.shape[0]), int(df_blk.shape[1])),
                out_csv=str(out_csv).replace("\\", "/"),
                out_parquet=str(out_parquet).replace("\\", "/"),
                sha256_csv=sha_csv,
                sha256_parquet=sha_parq,
                preview_head=preview,
            )
        )

        print("\n--- Extracted ---")
        print("raw_file   :", raw_file)
        print("block_name :", block_name)
        print("excel_range:", excel_rng)
        print("shape      :", df_blk.shape)
        print("out_csv    :", out_csv.name)
        print("out_parquet:", out_parquet.name)
        print("sha256_csv :", sha_csv)
        print("sha256_parq:", sha_parq)
        print("Preview:\n", preview)

    payload = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "config": str(CONFIG_PATH).replace("\\", "/"),
        "raw_dir": str(raw_dir).replace("\\", "/"),
        "out_dir": str(out_dir).replace("\\", "/"),
        "blocks": [asdict(b) for b in extracted],
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote:", OUT_JSON)

    md = []
    md.append("# Kazakhstan CHPP Block Extraction Report\n\n")
    md.append(f"- Created (UTC): {payload['created_utc']}\n")
    md.append(f"- Config: `{payload['config']}`\n")
    md.append(f"- Raw dir: `{payload['raw_dir']}`\n")
    md.append(f"- Out dir: `{payload['out_dir']}`\n\n")

    md.append("| raw_file | block_name | excel_range | shape | out_csv | out_parquet |\n")
    md.append("|---|---|---|---:|---|---|\n")
    for b in extracted:
        md.append(
            f"| {b.raw_file} | {b.block_name} | {b.excel_range} | {b.shape} | "
            f"`{Path(b.out_csv).name}` | `{Path(b.out_parquet).name}` |\n"
        )

    md.append("\n## Previews (head)\n\n")
    for b in extracted:
        md.append(f"### {b.raw_file} / {b.block_name} / {b.excel_range}\n\n")
        md.append("```text\n")
        md.append(b.preview_head)
        md.append("\n```\n\n")

    OUT_MD.write_text("".join(md), encoding="utf-8")
    print("Wrote:", OUT_MD)

    print("\nNext: we will interpret each block into a strict CHP parameter schema + units + feasibility checks.")


if __name__ == "__main__":
    main()