#!/usr/bin/env python3
"""Compare JSON schemas across experiment folders using index files or direct scan.

For each folder (full, no_few_shot_no_constraints, single_agent) this script:
 - finds JSON files (optionally via `reports/*_index.json` if present)
 - parses each JSON and builds a set of JSON-path -> observed types
 - produces per-folder schema report: for each JSON path, which files contain it and which types were observed
 - reports unique paths (present only in one file) and paths with type conflicts
 - writes output to `reports/<folder>_schema_report.json` and a small human-readable summary

Usage:
  python scripts/compare_schemas.py --root . --reports reports

"""
from __future__ import annotations
import argparse
import json
import os
import fnmatch
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def load_index_if_exists(index_path: Path) -> Optional[dict]:
    if index_path.exists():
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def find_json_files(folder: Path, index: Optional[dict] = None, ignore_patterns: Optional[List[str]] = None) -> List[Path]:
    """Find JSON files under folder or via index, optionally excluding patterns.

    ignore_patterns are fnmatch-style patterns matched against the filename (Path.name).
    """
    files: List[Path] = []
    if index is not None:
        for e in index.get("entries", []):
            p = Path(e.get("file"))
            if p.exists():
                files.append(p)
    else:
        for dirpath, _, filenames in os.walk(folder):
            for fname in filenames:
                if fname.lower().endswith(".json"):
                    files.append(Path(dirpath) / fname)

    files = sorted(set(files))

    # apply ignore patterns
    if ignore_patterns:
        filtered: List[Path] = []
        for p in files:
            name = p.name
            skip = False
            for pat in ignore_patterns:
                if fnmatch.fnmatch(name, pat):
                    skip = True
                    break
            if not skip:
                filtered.append(p)
        files = filtered

    return files


def _json_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def walk_json(obj: Any, base: str = "") -> List[Tuple[str, str]]:
    """Return list of (path, type) pairs.

    - Object keys join with dot: e.g. 'root.person.name'
    - For arrays, the path contains '[]' to indicate array elements: e.g. 'root.items[]'
    """
    pairs: List[Tuple[str, str]] = []

    t = _json_type(obj)
    # record the current path's type
    pairs.append((base or "$", t))

    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{base}.{k}" if base else k
            pairs.extend(walk_json(v, child_path))

    elif isinstance(obj, list):
        # for arrays, record types of elements and inspect up to N elements
        # to avoid heavy work we sample first few elements
        child_base = f"{base}[]" if base else "[]"
        if obj:
            # sample up to 5 elements
            for i, el in enumerate(obj[:5]):
                pairs.extend(walk_json(el, child_base))
        else:
            # empty array: just record the array type at base
            pass
    return pairs


@dataclass
class FileSchema:
    path: Path
    path_types: Dict[str, Set[str]]  # maps json path -> set of types


def analyze_files(files: List[Path]) -> List[FileSchema]:
    out: List[FileSchema] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
            obj = json.loads(text)
        except Exception as e:
            # treat as invalid json: record file with no schema
            print(f"Warning: failed to parse {p}: {e}")
            out.append(FileSchema(path=p, path_types={"$": {"invalid_json"}}))
            continue

        pairs = walk_json(obj, "$")
        d: Dict[str, Set[str]] = defaultdict(set)
        for path, typ in pairs:
            d[path].add(typ)
        out.append(FileSchema(path=p, path_types=dict(d)))
    return out


def merge_schemas(schemas: List[FileSchema]) -> Dict[str, Dict[str, Any]]:
    # For each path, collect types observed and which files contain it
    result: Dict[str, Dict[str, Any]] = {}
    all_files = {s.path for s in schemas}
    for s in schemas:
        for path, types in s.path_types.items():
            rec = result.setdefault(path, {"types": set(), "files": set()})
            rec["types"].update(types)
            rec["files"].add(str(s.path))
    # finalize: convert sets to lists and also record missing files
    for path, rec in result.items():
        rec["types"] = sorted(rec["types"])
        rec["files"] = sorted(rec["files"])
        rec_files = set(rec["files"])
        missing = sorted(str(p) for p in all_files - {Path(f) for f in rec["files"]})
        rec["missing_in_files"] = missing
    return result


def summarize_schema(merged: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    total_paths = len(merged)
    paths_with_type_conflict = [p for p, r in merged.items() if len(r.get("types", [])) > 1]
    paths_missing = [p for p, r in merged.items() if r.get("missing_in_files")]
    unique_paths = [p for p, r in merged.items() if len(r.get("files", [])) == 1]
    return {
        "total_paths": total_paths,
        "paths_with_type_conflict_count": len(paths_with_type_conflict),
        "paths_with_type_conflict": paths_with_type_conflict[:20],
        "paths_missing_count": len(paths_missing),
        "paths_missing_examples": paths_missing[:20],
        "unique_paths_count": len(unique_paths),
        "unique_paths_examples": unique_paths[:20],
    }


def write_reports(root: Path, folder_name: str, schemas: List[FileSchema], merged: Dict[str, Dict[str, Any]], outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    rep = {
        "folder": folder_name,
        "files_count": len(schemas),
        "files": [str(s.path) for s in schemas],
        "merged_schema": merged,
        "summary": summarize_schema(merged),
    }
    outpath = outdir / f"{folder_name}_schema_report.json"
    outpath.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")

    # also write a short human readable summary
    md = [f"# Schema report for {folder_name}\n"]
    md.append(f"Files analyzed: {len(schemas)}\n")
    sm = rep["summary"]
    md.append(f"- Total unique JSON paths: {sm['total_paths']}\n")
    md.append(f"- Paths with type conflicts: {sm['paths_with_type_conflict_count']} (examples: {sm['paths_with_type_conflict']})\n")
    md.append(f"- Paths missing in some files: {sm['paths_missing_count']} (examples: {sm['paths_missing_examples']})\n")
    md.append(f"- Unique paths (present in only 1 file): {sm['unique_paths_count']} (examples: {sm['unique_paths_examples']})\n")
    mdpath = outdir / f"{folder_name}_schema_summary.md"
    mdpath.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote schema report {outpath} and summary {mdpath}")


def process_folder(root: Path, folder_name: str, reports_dir: Path, ignore_patterns: Optional[List[str]] = None) -> None:
    folder = root / folder_name
    index_path = reports_dir / f"{folder_name}_index.json"
    index = load_index_if_exists(index_path)
    files = find_json_files(folder, index, ignore_patterns=ignore_patterns)
    print(f"Found {len(files)} JSON files under {folder_name} (after applying ignore patterns)")
    schemas = analyze_files(files)
    merged = merge_schemas(schemas)
    write_reports(root, folder_name, schemas, merged, reports_dir)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".", help="repo root")
    p.add_argument("--reports", default="reports", help="reports directory (contains _index.json files)")
    p.add_argument("--folders", nargs="*", default=["full", "no_few_shot_no_constraints", "single_agent"], help="folders to process")
    p.add_argument("--ignore-patterns", nargs="*", help="fnmatch patterns for filenames to ignore (e.g. '*metadata*.json' 'modeler.json')")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    reports_dir = Path(args.reports).resolve()

    # default ignore patterns to skip metadata/modeler/parser and full-response files
    ignore_patterns = args.ignore_patterns or [
        "*_full_response.json",
        "*full_response*.json",
        "*metadata*.json",
        "modeler.json",
        "parser.json",
        "*parser*.json",
        "*modeler_metadata*.json",
    ]

    for folder_name in args.folders:
        process_folder(root, folder_name, reports_dir, ignore_patterns=ignore_patterns)

    print("All done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
