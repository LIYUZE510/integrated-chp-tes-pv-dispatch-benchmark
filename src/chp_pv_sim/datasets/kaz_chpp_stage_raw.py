from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chp_pv_sim.paths import RAW_DIR, ensure_dirs


DOI = "10.17632/3tprt2ct2n.3"
DATASET_URL = "https://data.mendeley.com/datasets/3tprt2ct2n/3"
LICENSE = "CC BY 4.0"

DATASET_ROOT = RAW_DIR / "kaz_chpp_v3"
ZIP_DIR = DATASET_ROOT / "zip"
EXTRACT_DIR = DATASET_ROOT / "extracted"
MANIFEST_PATH = DATASET_ROOT / "manifest.json"
README_PATH = DATASET_ROOT / "README_KAZ_CHPP.txt"


@dataclass(frozen=True)
class FileInfo:
    relpath: str
    size_bytes: int
    sha256: str
    mtime_utc: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Secure extraction: prevent Zip Slip path traversal."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            name = member.filename
            if name.endswith("/"):
                continue
            target = (dest_dir / name).resolve()
            if not str(target).startswith(str(dest_dir.resolve())):
                raise RuntimeError(f"Unsafe path in zip: {name}")
        zf.extractall(dest_dir)


def list_files_with_hashes(root: Path) -> list[FileInfo]:
    infos: list[FileInfo] = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            mtime_utc = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
            infos.append(
                FileInfo(
                    relpath=str(p.relative_to(root)).replace("\\", "/"),
                    size_bytes=int(st.st_size),
                    sha256=sha256_file(p),
                    mtime_utc=mtime_utc,
                )
            )
    return infos


def print_tree(root: Path, max_depth: int = 4) -> None:
    root = root.resolve()
    print(f"\n[Tree] {root}")
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        depth = len(dp.relative_to(root).parts)
        if depth > max_depth:
            dirnames[:] = []
            continue
        indent = "  " * depth
        print(f"{indent}{dp.name}/")
        for fn in sorted(filenames)[:50]:
            print(f"{indent}  - {fn}")
        if len(filenames) > 50:
            print(f"{indent}  ... ({len(filenames)-50} more files)")


def write_readme() -> None:
    text = f"""Kazakhstan Coal-Fired CHPP Dataset (Raw Download)

DOI: {DOI}
URL: {DATASET_URL}
License: {LICENSE}

This folder contains:
- zip/: the original "Download All" archive as obtained from Mendeley Data
- extracted/: extracted files (unaltered)
- manifest.json: SHA256 + size inventory for reproducibility and integrity checks

Downloaded/processed by: chp_pv_sim.datasets.kaz_chpp_stage_raw
"""
    README_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    ensure_dirs()
    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

    zips = sorted([p for p in ZIP_DIR.glob("*.zip") if p.is_file()])
    if len(zips) == 0:
        raise FileNotFoundError(
            f"No zip found in {ZIP_DIR}. Please download 'Download All' zip from {DATASET_URL} and place it here."
        )
    if len(zips) > 1:
        raise RuntimeError(
            f"Multiple zip files found in {ZIP_DIR}. Please keep ONLY ONE zip for this dataset.\n"
            + "\n".join(str(p.name) for p in zips)
        )

    zip_path = zips[0]
    print("Found zip:", zip_path.name)

    zip_size = zip_path.stat().st_size
    t0 = time.time()
    zip_sha = sha256_file(zip_path)
    t1 = time.time()
    print(f"Zip size: {zip_size:,} bytes")
    print(f"Zip sha256: {zip_sha}")
    print(f"Zip hash time: {t1 - t0:.2f}s")

    existing_files = list(EXTRACT_DIR.rglob("*"))
    if any(p.is_file() for p in existing_files):
        print(f"\n[NOTE] {EXTRACT_DIR} is not empty. Skipping extraction to avoid overwriting.")
        print("If you want a fresh extraction, delete the extracted/ folder contents and rerun.")
    else:
        print("\nExtracting zip -> extracted/ ...")
        safe_extract_zip(zip_path, EXTRACT_DIR)
        print("Extraction done.")

    print("\nHashing extracted files ...")
    files_info = list_files_with_hashes(EXTRACT_DIR)
    total_bytes = sum(fi.size_bytes for fi in files_info)
    print(f"Extracted file count: {len(files_info)}")
    print(f"Extracted total size: {total_bytes:,} bytes")

    write_readme()

    manifest: dict[str, Any] = {
        "dataset": {
            "name": "Data for Modeling Large-scale Coal-Fired CHP Plant in Kazakhstan: Two Cases",
            "doi": DOI,
            "url": DATASET_URL,
            "license": LICENSE,
        },
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "zip": {
            "filename": zip_path.name,
            "size_bytes": int(zip_size),
            "sha256": zip_sha,
        },
        "extracted": {
            "root": str(EXTRACT_DIR).replace("\\", "/"),
            "file_count": int(len(files_info)),
            "total_size_bytes": int(total_bytes),
            "files": [fi.__dict__ for fi in files_info],
        },
    }

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote:", str(README_PATH))
    print("Wrote:", str(MANIFEST_PATH))

    print_tree(EXTRACT_DIR, max_depth=3)


if __name__ == "__main__":
    main()