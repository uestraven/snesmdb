#!/usr/bin/env python3
"""Decode every BRR sample the corpus uses and measure it.

    timbre_features.py <out-dir> <cache.json> [--jobs 8]

Milestone 5, stage one. Writes one row per DISTINCT sample with two
independent halves:

  features  intrinsic to the decoded waveform -- what the sample IS
  usage     how the corpus plays it -- register, note length, whether it is
            ever pitched at all

They are kept apart on purpose. The codebook is fitted on `features` only, and
`usage` is the held-out evidence for whether the classes mean anything. A
feature appearing in both halves would make the validation circular, which is
the easiest way to produce a convincing and worthless result.

No emulation here: the ARAM is read straight out of each SPC, so this is file
I/O and BRR decoding, and it caches to JSON because choosing k needs many
passes over the features and none of them need the samples again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import brr, pitch, timbre  # noqa: E402
from snesmdb.spcfile import SpcError, load  # noqa: E402


def _one_track(args: tuple[str, str, str]) -> list[dict[str, Any]]:
    """Features for every sample one track uses."""
    spc_path, record_path, game = args
    try:
        spc = load(Path(spc_path))
    except (SpcError, OSError):
        return []
    record = json.loads(Path(record_path).read_text())

    srcns = {int(n["srcn"]) for n in record["notes"]}
    if not srcns:
        return []
    entries = brr.read_directory(spc.aram, spc.dsp[0x5D], srcns)

    # Usage, per srcn, from this track's notes. Pitch and duration are
    # properties of the PERFORMANCE, never of the sample, so they stay out of
    # the feature vector.
    notes_by_srcn: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for note in record["notes"]:
        notes_by_srcn[int(note["srcn"])].append(note)

    out = []
    for srcn, entry in entries.items():
        if not entry.plausible:
            continue
        try:
            decoded = brr.decode(spc.aram, entry.start, entry.loop)
        except (ValueError, IndexError):
            continue
        if not decoded.data:
            continue
        estimate = pitch.estimate_f0(srcn, decoded.data, decoded.loop_offset)
        f0 = (
            estimate.f0_hz
            if estimate and estimate.f0_hz and estimate.confidence in ("high", "medium")
            else None
        )
        feat = timbre.features(srcn, decoded.data, decoded.loop_offset, f0)

        notes = notes_by_srcn.get(srcn, [])
        midis = [n["midi_note"] for n in notes if n.get("midi_note") is not None]
        durations = [
            (int(n["end"]) - int(n["start"])) / 1_024_000.0
            for n in notes
            if n.get("end") is not None
        ]
        out.append(
            {
                # Identity: the decoded bytes, so the same instrument shared
                # between two tracks of a game counts once.
                "key": hashlib.sha256(
                    b",".join(str(v).encode() for v in decoded.data)
                ).hexdigest()[:16],
                "game": game,
                "srcn": srcn,
                "features": feat.to_dict(),
                "vector": feat.vector(),
                "usage": {
                    "n_notes": len(notes),
                    "n_pitched": len(midis),
                    "unpitched_fraction": (
                        1.0 - len(midis) / len(notes) if notes else 1.0
                    ),
                    "median_midi": statistics.median(midis) if midis else None,
                    "median_duration_sec": (
                        statistics.median(durations) if durations else None
                    ),
                },
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--spc-root", type=Path, default=Path("data/spc"))
    args = parser.parse_args()

    by_name = {p.name: p for p in args.spc_root.rglob("*.spc")}
    work = []
    for line in (args.out_dir / "manifest.jsonl").open():
        row = json.loads(line)
        if not row.get("ok") or not row.get("record_path"):
            continue
        spc = by_name.get(row["source"])
        if spc is None:
            continue
        work.append(
            (str(spc), str(args.out_dir / row["record_path"]), row["tag"]["game"] or "?")
        )
    print(f"{len(work)} tracks to read", file=sys.stderr)

    rows: list[dict[str, Any]] = []
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for result in pool.map(_one_track, work, chunksize=8):
                rows.extend(result)
    else:
        for item in work:
            rows.extend(_one_track(item))

    # Collapse to distinct samples. A game's instrument bank is shared by all
    # its tracks, so the same waveform arrives dozens of times; usage is summed
    # across every appearance, features are identical by construction.
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["game"], row["key"])
        if key not in merged:
            merged[key] = {
                "game": row["game"],
                "key": row["key"],
                "srcns": [row["srcn"]],
                "features": row["features"],
                "vector": row["vector"],
                "usage": dict(row["usage"]),
                "n_tracks": 1,
                "_midis": [],
                "_durations": [],
            }
            entry = merged[key]
        else:
            entry = merged[key]
            entry["n_tracks"] += 1
            if row["srcn"] not in entry["srcns"]:
                entry["srcns"].append(row["srcn"])
            entry["usage"]["n_notes"] += row["usage"]["n_notes"]
            entry["usage"]["n_pitched"] += row["usage"]["n_pitched"]
        if row["usage"]["median_midi"] is not None:
            entry["_midis"].append(row["usage"]["median_midi"])
        if row["usage"]["median_duration_sec"] is not None:
            entry["_durations"].append(row["usage"]["median_duration_sec"])

    final = []
    for entry in merged.values():
        usage = entry["usage"]
        usage["median_midi"] = (
            statistics.median(entry.pop("_midis")) if entry["_midis"] else None
        )
        usage["median_duration_sec"] = (
            statistics.median(entry.pop("_durations")) if entry["_durations"] else None
        )
        entry.pop("_midis", None)
        entry.pop("_durations", None)
        usage["unpitched_fraction"] = (
            1.0 - usage["n_pitched"] / usage["n_notes"] if usage["n_notes"] else 1.0
        )
        final.append(entry)

    args.cache.write_text(json.dumps({"axes": timbre.Features.axes(), "samples": final}))
    games = len({s["game"] for s in final})
    print(
        f"wrote {len(final)} distinct samples across {games} games to {args.cache}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
