from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import xlrd

from chp_pv_sim.paths import RAW_DIR, REPORTS_DIR, ensure_dirs


RAW_EXTRACT_DIR = RAW_DIR / "kaz_chpp_v3" / "extracted"
OUT_JSON = REPORTS_DIR / "kaz_chpp_inspect.json"
OUT_MD = REPORTS_DIR / "kaz_chpp_inspect.md"


KEYWORDS = [
    # English
    "chp", "coal", "boiler", "turbine", "unit", "generator",
    "heat", "thermal", "steam", "power", "electric",
    "min", "max", "ramp", "startup", "shutdown", "efficiency", "fuel", "cost",
    # Russian (common engineering terms)
    "кот", "котел", "турбин", "электр", "мощн", "тепл", "пар",
    "миним", "максим", "разгон", "пуск", "останов", "кпд", "топлив", "угол", "стоим",
]


@dataclass
class SheetSummary:
    sheet_name: str
    nrows: int
    ncols: int
    preview_top_left: list[list[str]]
    keyword_hits: list[dict[str, Any]]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _cell_to_str(v: Any, max_len: int = 60) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def main() -> None:
    ensure_dirs()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    xls_files = sorted([p for p in RAW_EXTRACT_DIR.rglob("*.xls") if p.is_file()])
    if len(xls_files) == 0:
        raise FileNotFoundError(f"No .xls found under: {RAW_EXTRACT_DIR}")
    if len(xls_files) > 1:
        raise RuntimeError("Multiple .xls found; keep only one or refine the search:\n" + "\n".join(map(str, xls_files)))

    xls_path = xls_files[0]
    print("Found xls:", xls_path.name)
    print("Path:", str(xls_path))
    print("Size bytes:", xls_path.stat().st_size)
    print("SHA256:", sha256_file(xls_path))

    book = xlrd.open_workbook(str(xls_path), formatting_info=False)
    sheet_names = book.sheet_names()
    print("\nSheet count:", len(sheet_names))
    for i, name in enumerate(sheet_names, start=1):
        sh = book.sheet_by_name(name)
        print(f"  {i:02d}. {name} (nrows={sh.nrows}, ncols={sh.ncols})")

    summaries: list[SheetSummary] = []

    for name in sheet_names:
        sh = book.sheet_by_name(name)
        nrows, ncols = sh.nrows, sh.ncols

        # Preview top-left block
        rmax = min(nrows, 20)
        cmax = min(ncols, 12)
        preview: list[list[str]] = []
        for r in range(rmax):
            row = []
            for c in range(cmax):
                row.append(_cell_to_str(sh.cell_value(r, c)))
            preview.append(row)

        # Keyword scan
        hits: list[dict[str, Any]] = []
        for r in range(nrows):
            for c in range(ncols):
                v = sh.cell_value(r, c)
                if v is None or v == "":
                    continue
                s = str(v).strip()
                if not s:
                    continue
                low = s.lower()
                for kw in KEYWORDS:
                    if kw in low:
                        hits.append({"row": r, "col": c, "value": _cell_to_str(s, 120), "matched": kw})
                        break
                if len(hits) >= 80:
                    break
            if len(hits) >= 80:
                break

        summaries.append(
            SheetSummary(
                sheet_name=name,
                nrows=int(nrows),
                ncols=int(ncols),
                preview_top_left=preview,
                keyword_hits=hits,
            )
        )

    payload = {
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "xls": {
            "filename": xls_path.name,
            "path": str(xls_path).replace("\\", "/"),
            "size_bytes": int(xls_path.stat().st_size),
            "sha256": sha256_file(xls_path),
        },
        "sheets": [asdict(s) for s in summaries],
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote:", OUT_JSON)

    # Markdown summary (more readable in VSCode)
    md = []
    md.append("# Kazakhstan CHPP Excel Inspection Report\n\n")
    md.append(f"- Created (UTC): {payload['created_utc']}\n")
    md.append(f"- File: `{payload['xls']['filename']}`\n")
    md.append(f"- SHA256: `{payload['xls']['sha256']}`\n\n")

    md.append("## Sheets\n\n")
    md.append("| sheet | nrows | ncols | keyword_hits |\n")
    md.append("|---|---:|---:|---:|\n")
    for s in summaries:
        md.append(f"| {s.sheet_name} | {s.nrows} | {s.ncols} | {len(s.keyword_hits)} |\n")

    md.append("\n## Top-left previews\n")
    for s in summaries:
        md.append(f"\n### {s.sheet_name}\n\n")
        prev_df = pd.DataFrame(s.preview_top_left)
        md.append("```text\n")
        md.append(prev_df.to_string(index=False, header=False))
        md.append("\n```\n")

        if s.keyword_hits:
            md.append("\nKeyword hits (first 30):\n\n")
            md.append("| row | col | matched | value |\n")
            md.append("|---:|---:|---|---|\n")
            for h in s.keyword_hits[:30]:
                v = str(h["value"]).replace("\n", " ").replace("|", "\\|")
                md.append(f"| {h['row']} | {h['col']} | {h['matched']} | {v} |\n")
        else:
            md.append("\n(No keyword hits in first scanned range.)\n")

    OUT_MD.write_text("".join(md), encoding="utf-8")
    print("Wrote:", OUT_MD)

    print("\nNext: based on the report, we'll extract a clean CHP parameter schema (YAML+Parquet) and run unit/feasibility checks.")


if __name__ == "__main__":
    main()