#!/usr/bin/env python3
"""Create a per-folder summary table from reports/metadata_summary.json

Outputs:
 - CSV: reports/metadata_summary_table.csv
 - Markdown: reports/metadata_summary_table.md

Usage:
  python scripts/metadata_summary_table.py --reports reports --out reports
  python scripts/metadata_summary_table.py --metric prompt_tokens
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Optional


def fmt(v: Optional[float]) -> str:
    if v is None:
        return ""
    if isinstance(v, int):
        return str(v)
    try:
        return f"{v:.1f}"
    except Exception:
        return str(v)


def summarize(reports_path: Path, metric: str = "total_tokens") -> Dict[str, Any]:
    data = json.loads(reports_path.read_text(encoding="utf-8"))
    folders = data.get("folders", {})

    rows = []
    for name, info in folders.items():
        files = info.get("files", [])
        # find files that have the metric
        metric_vals = [(f.get("file"), f.get(metric)) for f in files if f.get(metric) is not None]
        max_file, max_val = (None, None)
        min_file, min_val = (None, None)
        if metric_vals:
            metric_vals_sorted = sorted(metric_vals, key=lambda x: x[1])
            min_file, min_val = metric_vals_sorted[0]
            max_file, max_val = metric_vals_sorted[-1]

        rows.append(
            {
                "folder": name,
                "files_count": info.get("files_count"),
                "models": ";".join([f"{k}:{v}" for k, v in info.get("models", {}).items()]),
                "prompt_tokens_avg": info.get("prompt_tokens_avg"),
                "completion_tokens_avg": info.get("completion_tokens_avg"),
                "total_tokens_avg": info.get("total_tokens_avg"),
                "generation_count_total": info.get("generation_count_total"),
                "max_metric_file": max_file,
                "max_metric_value": max_val,
                "min_metric_file": min_file,
                "min_metric_value": min_val,
            }
        )
    return {"metric": metric, "rows": rows}


def write_csv(rows, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    keys = [
        "folder",
        "files_count",
        "models",
        "prompt_tokens_avg",
        "completion_tokens_avg",
        "total_tokens_avg",
        "generation_count_total",
        "max_metric_file",
        "max_metric_value",
        "min_metric_file",
        "min_metric_value",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            out = {k: (fmt(r.get(k)) if isinstance(r.get(k), (int, float)) else (r.get(k) or "")) for k in keys}
            w.writerow(out)


def write_md(rows, out_path: Path, metric: str) -> None:
    lines = []
    lines.append(f"# Metadata summary table (metric: {metric})\n")
    header = ["Folder", "Files", "Models", "Prompt avg", "Completion avg", "Total avg", "Gen count", f"Max {metric}", f"Min {metric}"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for r in rows:
        max_val = fmt(r.get("max_metric_value")) if r.get("max_metric_value") is not None else ""
        min_val = fmt(r.get("min_metric_value")) if r.get("min_metric_value") is not None else ""
        max_cell = f"{max_val} ({Path(r.get('max_metric_file') or '').name})" if r.get("max_metric_file") else ""
        min_cell = f"{min_val} ({Path(r.get('min_metric_file') or '').name})" if r.get("min_metric_file") else ""
        line = (
            "| " + " | ".join([
                str(r.get("folder")),
                str(r.get("files_count")),
                str(r.get("models")),
                fmt(r.get("prompt_tokens_avg")),
                fmt(r.get("completion_tokens_avg")),
                fmt(r.get("total_tokens_avg")),
                str(r.get("generation_count_total")),
                max_cell,
                min_cell,
            ]) + " |"
        )
        lines.append(line)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reports", default="reports", help="reports directory containing metadata_summary.json")
    p.add_argument("--out", default="reports", help="output directory for CSV and MD")
    p.add_argument("--metric", default="total_tokens", help="metric to use for min/max (total_tokens/prompt_tokens/completion_tokens)")
    args = p.parse_args()

    reports_dir = Path(args.reports)
    summary_path = reports_dir / "metadata_summary.json"
    if not summary_path.exists():
        print(f"Error: {summary_path} not found. Run scripts/analyze_metadata.py first.")
        return 2

    data = summarize(summary_path, metric=args.metric)
    rows = data["rows"]

    csv_out = Path(args.out) / "metadata_summary_table.csv"
    md_out = Path(args.out) / "metadata_summary_table.md"

    write_csv(rows, csv_out)
    write_md(rows, md_out, data["metric"])

    print(f"Wrote {csv_out} and {md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
