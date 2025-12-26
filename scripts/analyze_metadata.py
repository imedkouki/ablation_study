#!/usr/bin/env python3
"""Analyze metadata and response files to report model, temperature and token usage.

Scans the experiment folders and looks for metadata/response files such as:
 - full/*/modeler_metadata.json, parser_metadata.json
 - no_few_shot_no_constraints/*/modeler.json, parser.json
 - single_agent/full_response/*_full_response.json

Outputs:
 - reports/metadata_summary.json (aggregated per-folder)
 - reports/metadata_details.csv (one row per metadata/response file)
 - reports/<folder>_metadata.json (per-folder aggregated info)
"""
from __future__ import annotations
import argparse
import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Local helper implementations (extracted from analyze_experiments)

def extract_token_usage(obj: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Extract prompt/completion/total token counts from common metadata shapes."""
    keys = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}

    def try_assign(dct, mapping):
        for dst_key, src_key in mapping.items():
            if src_key in dct and dct[src_key] is not None:
                try:
                    keys[dst_key] = int(dct[src_key])
                except Exception:
                    # some shapes use nested dicts or non-int values
                    try:
                        keys[dst_key] = int(str(dct[src_key]))
                    except Exception:
                        pass

    if isinstance(obj.get("tokenUsage"), dict):
        try_assign(obj["tokenUsage"], {"prompt_tokens": "promptTokens", "completion_tokens": "completionTokens", "total_tokens": "totalTokens"})

    if isinstance(obj.get("tokenUsageEstimate"), dict):
        try_assign(obj["tokenUsageEstimate"], {"prompt_tokens": "promptTokens", "completion_tokens": "completionTokens", "total_tokens": "totalTokens"})

    if "modeler_metadata" in obj and isinstance(obj["modeler_metadata"], dict):
        mm = obj["modeler_metadata"]
        if isinstance(mm.get("response_metadata"), dict):
            rm = mm["response_metadata"]
            if isinstance(rm.get("token_usage"), dict):
                try_assign(rm["token_usage"], {"prompt_tokens": "prompt_tokens", "completion_tokens": "completion_tokens", "total_tokens": "total_tokens"})
            try_assign(rm, {"prompt_tokens": "promptTokens", "completion_tokens": "completionTokens", "total_tokens": "totalTokens"})

    # fallback generic checks
    for keyname in ("tokenUsage", "tokenUsageEstimate", "token_usage"):
        if keyname in obj and isinstance(obj[keyname], dict):
            try_assign(obj[keyname], {"prompt_tokens": "prompt_tokens", "completion_tokens": "completion_tokens", "total_tokens": "total_tokens"})
            try_assign(obj[keyname], {"prompt_tokens": "promptTokens", "completion_tokens": "completionTokens", "total_tokens": "totalTokens"})

    return keys


def find_generation_texts(obj: Dict[str, Any]) -> List[str]:
    """Heuristic extraction of generation text fields."""
    out: List[str] = []
    if not obj:
        return out
    resp = obj.get("response") or obj.get("responseMetadata") or obj
    if isinstance(resp, dict):
        generations = resp.get("generations")
        if isinstance(generations, list):
            for gen in generations:
                if isinstance(gen, list):
                    for g in gen:
                        if isinstance(g, dict) and "text" in g:
                            out.append(g.get("text") or "")
                elif isinstance(gen, dict) and "text" in gen:
                    out.append(gen.get("text") or "")
    if not out:
        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "text" and isinstance(v, str):
                        out.append(v)
                    else:
                        walk(v)
            elif isinstance(o, list):
                for e in o:
                    walk(e)
        walk(obj)
    return out


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: failed to load {path}: {e}")
        return None


def find_metadata_files(root: Path) -> List[Path]:
    patterns = ["*modeler_metadata.json", "*parser_metadata.json", "modeler.json", "parser.json", "*_full_response.json", "*full_response.json"]
    files: List[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            for pat in patterns:
                if Path(fname).match(pat):
                    files.append(Path(dirpath) / fname)
                    break
    return sorted(files)


def extract_model_info(obj: Dict[str, Any]) -> Dict[str, Optional[Any]]:
    model = None
    temperature = None
    # try common locations
    if isinstance(obj.get("modeler_metadata"), dict):
        mm = obj["modeler_metadata"]
        model = mm.get("model") or model
        temperature = mm.get("temperature") or temperature
        # also token usage in mm.response_metadata.token_usage
        # handled separately by extract_token_usage

    if model is None and isinstance(obj.get("model"), str):
        model = obj.get("model")
    # safely inspect nested response/generationInfo
    resp = obj.get("response")
    if model is None and isinstance(resp, dict) and isinstance(resp.get("generationInfo"), dict):
        model = resp.get("generationInfo", {}).get("model_name")

    # sometimes model name appears under response_metadata.model_name
    if model is None and isinstance(obj.get("response_metadata"), dict):
        model = obj.get("response_metadata", {}).get("model_name") or model

    return {"model": model, "temperature": temperature}


def analyze_files(files: List[Path]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for p in files:
        obj = load_json(p)
        if obj is None:
            records.append({"file": str(p), "error": "invalid_json"})
            continue
        token_info = extract_token_usage(obj)
        gens = find_generation_texts(obj)
        gen_count = len(gens)
        model_info = extract_model_info(obj)

        rec = {
            "file": str(p),
            "folder": str(p.parents[1].name) if len(p.parents) > 1 else str(p.parent.name),
            "basename": p.name,
            "model": model_info.get("model"),
            "temperature": model_info.get("temperature"),
            "prompt_tokens": token_info.get("prompt_tokens"),
            "completion_tokens": token_info.get("completion_tokens"),
            "total_tokens": token_info.get("total_tokens"),
            "generation_count": gen_count,
        }
        records.append(rec)
    return records


def aggregate_by_folder(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_folder: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_folder[r.get("folder", "<unknown>")].append(r)

    summary: Dict[str, Any] = {}
    for folder, recs in by_folder.items():
        stats = {
            "files_count": len(recs),
            "models": {},
            "prompt_tokens_total": 0,
            "completion_tokens_total": 0,
            "total_tokens_total": 0,
            "prompt_tokens_count": 0,
            "completion_tokens_count": 0,
            "total_tokens_count": 0,
            "generation_count_total": 0,
        }
        for r in recs:
            m = r.get("model") or "<unknown>"
            stats["models"].setdefault(m, 0)
            stats["models"][m] += 1
            if r.get("prompt_tokens") is not None:
                stats["prompt_tokens_total"] += r["prompt_tokens"]
                stats["prompt_tokens_count"] += 1
            if r.get("completion_tokens") is not None:
                stats["completion_tokens_total"] += r["completion_tokens"]
                stats["completion_tokens_count"] += 1
            if r.get("total_tokens") is not None:
                stats["total_tokens_total"] += r["total_tokens"]
                stats["total_tokens_count"] += 1
            if r.get("generation_count") is not None:
                stats["generation_count_total"] += r["generation_count"]

        def mkavg(total, count):
            return (total / count) if count else None

        stats["prompt_tokens_avg"] = mkavg(stats["prompt_tokens_total"], stats["prompt_tokens_count"])
        stats["completion_tokens_avg"] = mkavg(stats["completion_tokens_total"], stats["completion_tokens_count"])
        stats["total_tokens_avg"] = mkavg(stats["total_tokens_total"], stats["total_tokens_count"])

        summary[folder] = {**stats, "files": recs}
    return summary


def write_outputs(records: List[Dict[str, Any]], by_folder: Dict[str, Any], outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / "metadata_details.csv"
    json_path = outdir / "metadata_summary.json"

    keys = ["file", "folder", "basename", "model", "temperature", "prompt_tokens", "completion_tokens", "total_tokens", "generation_count"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k) for k in keys})

    json_path.write_text(json.dumps({"folders": by_folder}, indent=2, ensure_ascii=False), encoding="utf-8")

    for folder, data in by_folder.items():
        path = outdir / f"{folder}_metadata.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote metadata CSV to {csv_path} and summary JSON to {json_path}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".", help="repo root")
    p.add_argument("--out", default="reports", help="output reports dir")
    p.add_argument("--folders", nargs="*", default=None)
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    outdir = Path(args.out).resolve()

    files = find_metadata_files(root)
    if args.folders:
        wanted = set(args.folders)
        files = [f for f in files if any(part in f.parts for part in wanted)]

    print(f"Found {len(files)} metadata/response files to analyze")
    records = analyze_files(files)
    by_folder = aggregate_by_folder(records)
    write_outputs(records, by_folder, outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
