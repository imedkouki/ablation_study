#!/usr/bin/env python3
"""Compare per-process metadata: modeler vs parser vs combined totals.

Reads `reports/metadata_details.csv` (created by analyze_metadata.py) and
creates per-folder CSV/MD that show, for each process, modeler and parser
prompt/completion/total tokens, their sum, and differences.

Outputs:
 - reports/metadata_process_comparison.csv
 - reports/metadata_process_comparison.md

Usage:
  python scripts/metadata_process_comparison.py --reports reports --out reports
"""
from __future__ import annotations
import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


def read_details(csv_path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def process_rows(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Dict[str, Optional[int]]]]:
    # structure: results[folder][process_id] -> {'modeler': {...}, 'parser': {...}, 'full': {...}}
    results = defaultdict(lambda: defaultdict(dict))

    for r in rows:
        file = r.get('file', '')
        folder = r.get('folder') or ''
        basename = r.get('basename') or ''
        # derive process id: prefer parent directory name for full/, no_few_shot; for single_agent use basename prefix
        path = Path(file)
        parent = path.parent.name
        # heuristics
        if folder == 'ttpm-mistral-medium':
            proc = parent  # e.g. processes_01
        elif folder == 'no_few_shot_no_constraints':
            proc = path.parent.name  # '01'
        elif folder == 'single_agent':
            # basename like 01_full_response.json
            proc = basename.split('_', 1)[0]
        else:
            proc = parent

        kind = 'other'
        if 'modeler' in basename:
            kind = 'modeler'
        elif 'parser' in basename:
            kind = 'parser'
        elif 'full_response' in basename or 'fullresponse' in basename or basename.endswith('full.json'):
            kind = 'full'

        def to_int(v: str) -> Optional[int]:
            try:
                return int(v) if v != '' and v is not None else None
            except Exception:
                return None

        data = {
            'prompt_tokens': to_int(r.get('prompt_tokens', '')),
            'completion_tokens': to_int(r.get('completion_tokens', '')),
            'total_tokens': to_int(r.get('total_tokens', '')),
            'generation_count': to_int(r.get('generation_count', '')),
            'file': file,
        }
        results[folder][proc][kind] = data
    return results


def write_outputs(results, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / 'metadata_process_comparison.csv'
    md_path = out_dir / 'metadata_process_comparison.md'

    headers = ['folder','process','modeler_file','modeler_prompt','modeler_completion','modeler_total','parser_file','parser_prompt','parser_completion','parser_total','combined_prompt','combined_completion','combined_total','full_file','full_total']
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(headers)
        for folder, procs in sorted(results.items()):
            for proc, kinds in sorted(procs.items()):
                m = kinds.get('modeler', {})
                p = kinds.get('parser', {})
                ffull = kinds.get('full', {})
                combined_prompt = (m.get('prompt_tokens') or 0) + (p.get('prompt_tokens') or 0)
                combined_completion = (m.get('completion_tokens') or 0) + (p.get('completion_tokens') or 0)
                combined_total = (m.get('total_tokens') or 0) + (p.get('total_tokens') or 0)
                w.writerow([
                    folder,
                    proc,
                    m.get('file',''), m.get('prompt_tokens') or '', m.get('completion_tokens') or '', m.get('total_tokens') or '',
                    p.get('file',''), p.get('prompt_tokens') or '', p.get('completion_tokens') or '', p.get('total_tokens') or '',
                    combined_prompt, combined_completion, combined_total,
                    ffull.get('file',''), ffull.get('total_tokens') or '',
                ])

    # Markdown summary
    lines = ['# Per-process metadata comparison\n', '| Folder | Process | Modeler total | Parser total | Combined total | Full total (if present) |', '|---|---:|---:|---:|---:|---:|']
    for folder, procs in sorted(results.items()):
        for proc, kinds in sorted(procs.items()):
            m = kinds.get('modeler', {})
            p = kinds.get('parser', {})
            ffull = kinds.get('full', {})
            combined_total = (m.get('total_tokens') or 0) + (p.get('total_tokens') or 0)
            lines.append(f"| {folder} | {proc} | {m.get('total_tokens') or ''} | {p.get('total_tokens') or ''} | {combined_total} | {ffull.get('total_tokens') or ''} |")

    md_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f"Wrote {csv_path} and {md_path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--reports', default='reports', help='reports dir containing metadata_details.csv')
    p.add_argument('--out', default='reports', help='output dir')
    args = p.parse_args()

    reports_dir = Path(args.reports)
    csv_path = reports_dir / 'metadata_details.csv'
    if not csv_path.exists():
        print(f"Error: {csv_path} not found. Run scripts/analyze_metadata.py first.")
        return 1

    rows = read_details(csv_path)
    results = process_rows(rows)
    write_outputs(results, Path(args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())