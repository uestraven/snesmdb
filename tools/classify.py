#!/usr/bin/env python3
"""Annotate an existing manifest with track_class, in place.

    classify.py <out-dir>

The label is derived entirely from fields the manifest already carries, so it
needs no emulation and no re-extraction. `extract.py` applies the same function
during a run; this exists so an existing corpus can be labelled without
rebuilding it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import trackclass  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()

    path = args.out_dir / "manifest.jsonl"
    rows = [json.loads(line) for line in path.open()]
    for row in rows:
        if row.get("ok"):
            row.update(trackclass.classify(row).to_dict())
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    # Per-track records carry the label too, so a consumer reading one record
    # does not have to join against the manifest to know what it is.
    for row in rows:
        if not row.get("ok") or not row.get("record_path"):
            continue
        record_path = args.out_dir / row["record_path"]
        record = json.loads(record_path.read_text())
        record["track_class"] = row["track_class"]
        record["track_class_reason"] = row["track_class_reason"]
        record_path.write_text(json.dumps(record, indent=1))

    good = [r for r in rows if r.get("ok")]
    census = trackclass.census(good)
    summary_path = args.out_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["track_classes"] = census
    summary_path.write_text(json.dumps(summary, indent=1))

    print(json.dumps(census, indent=1))
    print(f"annotated {len(good)} tracks in {path}")


if __name__ == "__main__":
    main()
