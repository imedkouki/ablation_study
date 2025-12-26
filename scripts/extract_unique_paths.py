#!/usr/bin/env python3
"""Extract unique JSON paths (present in only one file) from schema reports.

Reads `reports/<folder>_schema_report.json` files created by
`scripts/compare_schemas.py` and writes per-folder outputs to
`reports/<folder>_unique_paths.json` and `reports/<folder>_unique_paths.csv`.

Optional flag --snippets will attempt to extract a short text snippet from the
containing file by searching for the final key name in the JSON file.

Usage:
  python scripts/extract_unique_paths.py --reports reports --out reports --snippets
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_schema_report(report_path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: failed to read {report_path}: {e}")
        return None


def get_key_name_from_path(path: str) -> str:
    # e.g. '$.rootElements[].flowElements[].description' -> 'description'
    parts = path.strip().split(".")
    if not parts:
        return path
    last = parts[-1]
    # remove [] markers
    last = last.replace("[]", "")
    return last


def extract_snippet(file_path: Path, key: str, ctx: int = 80) -> Optional[str]:
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    # look for quoted key occurrence or bare key
    targets = [f'"{key}"', key]
    for t in targets:
        idx = text.find(t)
        if idx != -1:
            start = max(0, idx - ctx)
            end = min(len(text), idx + len(t) + ctx)
            return text[start:end].replace("\n", " ")
    return None


def process_report(report_path: Path, out_dir: Path, snippets: bool = False) -> None:
    data = load_schema_report(report_path)
    if not data:
        return
    folder = data.get("folder") or report_path.stem.replace("_schema_report", "")
    merged = data.get("merged_schema", {})

    unique_entries: List[Dict[str, Any]] = []
    for path, info in merged.items():
        files = info.get("files", [])
        types = info.get("types", [])
        if len(files) == 1:
            file_containing = files[0]
            key = get_key_name_from_path(path)
            snippet = None
            if snippets:
                snippet = extract_snippet(Path(file_containing), key)
            unique_entries.append(
                {
                    "path": path,
                    "types": types,
                    "file": file_containing,
                    "snippet": snippet,
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    json_out = out_dir / f"{folder}_unique_paths.json"
    csv_out = out_dir / f"{folder}_unique_paths.csv"

    json_out.write_text(json.dumps({"folder": folder, "unique_paths": unique_entries}, indent=2, ensure_ascii=False), encoding="utf-8")

    # write CSV
    with csv_out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "types", "file", "snippet"])
        for e in unique_entries:
            writer.writerow([e["path"], ";".join(e["types"]), e["file"], (e["snippet"] or "")])

    print(f"Wrote {json_out} ({len(unique_entries)} entries) and {csv_out}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reports", default="reports", help="directory containing <folder>_schema_report.json files")
    p.add_argument("--out", default=None, help="output directory (defaults to reports)")
    p.add_argument("--folders", nargs="*", default=None, help="specific folders to process (e.g. full single_agent)")
    p.add_argument("--snippets", action="store_true", help="include a short snippet from the containing file when possible")
    args = p.parse_args(argv)

    reports_dir = Path(args.reports).resolve()
    out_dir = Path(args.out).resolve() if args.out else reports_dir

    # find schema report files
    report_files = list(reports_dir.glob("*_schema_report.json"))
    if args.folders:
        wanted = set(args.folders)
        report_files = [p for p in report_files if any(p.name.startswith(f"{f}_") for f in wanted)]

    if not report_files:
        print("No schema report files found in reports dir")
        return 1

    for rp in report_files:
        process_report(rp, out_dir, snippets=args.snippets)

    print("All done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
