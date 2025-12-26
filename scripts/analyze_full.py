#!/usr/bin/env python3
"""Create an index (JSON) of files under `full/` for later manual analysis.

For each JSON file we store: relative path, absolute path, size (bytes), whether
it is valid JSON, top-level keys (if an object), and a small preview of the file
content (first 500 characters). No additional analysis is performed.
"""
from pathlib import Path
import json
import os


def index_folder(folder: Path, outpath: Path, preview_len: int = 500) -> None:
    entries = []
    folder = folder.resolve()
    for dirpath, _, filenames in os.walk(folder):
        for fname in filenames:
            if not fname.lower().endswith(".json"):
                continue
            fpath = Path(dirpath) / fname
            rel = fpath.relative_to(folder.parent)
            size = fpath.stat().st_size
            text = fpath.read_text(encoding="utf-8", errors="replace")
            preview = text[:preview_len]
            is_valid = True
            top_keys = []
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    top_keys = list(obj.keys())
            except Exception:
                is_valid = False

            entries.append(
                {
                    "relpath": str(rel),
                    "file": str(fpath),
                    "size_bytes": size,
                    "is_valid_json": is_valid,
                    "top_level_keys": top_keys,
                    "preview": preview,
                }
            )
    outpath.parent.mkdir(parents=True, exist_ok=True)
    outdata = {"root": str(folder), "files_count": len(entries), "entries": entries}
    outpath.write_text(json.dumps(outdata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote index to {outpath}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    folder = repo_root / "full"
    outpath = repo_root / "reports" / "full_index.json"
    if not folder.exists():
        print(f"Folder {folder} does not exist")
        return 2
    index_folder(folder, outpath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
