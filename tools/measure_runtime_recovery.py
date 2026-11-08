#!/usr/bin/env python3
"""Measure what runtime directory resolution recovers, per note attack.

    measure_runtime_recovery.py <out-dir> <spc-dir> <report.json> [--limit N]

Answers one question per attack: did resolving the sample directory at KEY-ON
time, rather than at the SPC snapshot instant, change what we know about this
note? Reports absolute counts in five outcomes, and reports recovered SAMPLE
IDENTITY separately from recovered PITCH, because they are related and not
equivalent -- a sample can become available and still yield no fundamental.

Read-only with respect to any published corpus.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import brr, dirtimeline as dt, pitch, sampleid, spcfile  # noqa: E402

DUMPER = ROOT / "build" / "spc_dump"


def _identity_and_pitch(aram: bytes, start: int, loop: int, cache: dict):
    """Canonical identity and estimated f0 for a BRR block, memoised."""
    key = (start, loop)
    if key in cache:
        return cache[key]
    try:
        decoded = brr.decode(aram, start, loop)
    except Exception:
        cache[key] = (None, None)
        return cache[key]
    if not decoded.data:
        cache[key] = (None, None)
        return cache[key]
    ident = sampleid.sample_id(decoded.data, decoded.loop_offset)
    f0 = pitch.estimate_f0(0, decoded.data, decoded.loop_offset).f0_hz
    cache[key] = (ident, f0)
    return cache[key]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("spc_dir", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    spcs = {p.name: p for p in args.spc_dir.rglob("*.spc")}
    rows = [
        json.loads(line)
        for line in (args.out_dir / "manifest.jsonl").read_text().splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if r.get("ok") and r.get("record_path")]
    # `--limit` caps tracks ACTUALLY PROCESSED, not manifest rows scanned:
    # the manifest may hold the whole corpus while `spc_dir` selects one
    # game, and slicing rows first would usually select none of it.

    totals = collections.Counter()
    pitch_gain = collections.Counter()
    per_track: dict[str, dict[str, int]] = {}
    changed_ids: dict[str, list[str]] = collections.defaultdict(list)

    for row in rows:
        if args.limit and len(per_track) >= args.limit:
            break
        source = spcs.get(row["source"])
        if source is None:
            continue
        spc = spcfile.load(source)
        page = spc.dsp[0x5D]
        base = page << 8
        initial = dt.DirectoryState(
            0, page, spc.aram[base: base + dt.TABLE_BYTES]
        )
        seconds = max(5, min(int(row.get("render_seconds") or 30), 300))
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "w.jsonl"
            final = Path(tmp) / "aram.bin"
            subprocess.run(
                [str(DUMPER), str(source), str(log), str(seconds),
                 "--aram", str(final)],
                capture_output=True, timeout=1800,
            )
            records = []
            if log.is_file():
                for line in log.read_text().splitlines():
                    if '"kind":"dir"' in line:
                        records.append(json.loads(line))
            end_aram = final.read_bytes() if final.is_file() else b""
        timeline = dt.read_log(records)
        # THE TRUE t=0 STATE MUST BE IN THE TIMELINE.
        #
        # `Timeline.at` falls back to the earliest state it holds, which is
        # the first LOGGED snapshot -- taken after a chunk of audio has
        # already rendered. Without the initial ARAM directory seeded at tick
        # 0, every note before that first snapshot resolved against a table
        # that may already have been rewritten. On Super Turrican that
        # inflated `identity_corrected` to 31.2% and `unresolved` to 28.5%
        # before the error was caught.
        timeline.add(0, page, initial.data)

        # SAMPLE BYTES, over the regions key-ons actually reference.
        #
        # Directory tracking fixes WHERE a sample is; it says nothing about
        # whether the bytes THERE changed. This compares the initial ARAM
        # against the end-of-run ARAM, restricted to the BRR blocks the
        # track's key-ons resolve to, so unrelated ARAM churn is not counted.
        #
        # DOCUMENTED LIMITATION: a region modified during playback and
        # restored before the end would be invisible here. Detecting that
        # needs periodic snapshots of the referenced regions, which is a
        # further precision improvement and not attempted.
        byte_changes = 0
        regions: set[tuple[int, int]] = set()

        cache: dict[Any, Any] = {}
        record = json.loads((args.out_dir / row["record_path"]).read_text())
        counts = collections.Counter()
        for note in record["notes"]:
            srcn = int(note["srcn"])
            tick = int(note["start"])
            state = timeline.at(tick)
            eff = state.entry(srcn) if state else None
            ini = initial.entry(srcn)

            if timeline.ambiguous(tick, srcn):
                counts[dt.AMBIGUOUS] += 1
                totals[dt.AMBIGUOUS] += 1
                continue

            id_before, f0_before = (
                _identity_and_pitch(spc.aram, *ini, cache)
                if dt.plausible(ini) else (None, None)
            )
            id_after, f0_after = (
                _identity_and_pitch(spc.aram, *eff, cache)
                if dt.plausible(eff) else (None, None)
            )
            if id_after is None:
                outcome = dt.UNRESOLVED
            elif id_before is None:
                outcome = dt.NEWLY_RESOLVED
            elif id_before != id_after:
                outcome = dt.IDENTITY_CORRECTED
            else:
                outcome = dt.UNCHANGED
            counts[outcome] += 1
            totals[outcome] += 1
            if dt.plausible(eff):
                regions.add(eff)

            # Identity and pitch recover separately.
            if outcome in (dt.NEWLY_RESOLVED, dt.IDENTITY_CORRECTED):
                if f0_before is None and f0_after is not None:
                    pitch_gain["pitch_newly_available"] += 1
                elif f0_before is not None and f0_after is None:
                    pitch_gain["pitch_lost"] += 1
                elif (f0_before is not None and f0_after is not None
                      and abs(f0_before - f0_after) > 0.5):
                    pitch_gain["pitch_changed"] += 1
                else:
                    pitch_gain["pitch_unchanged"] += 1
                if outcome == dt.IDENTITY_CORRECTED:
                    changed_ids[row["track_id"]].append(
                        f"srcn {srcn}: {id_before} -> {id_after}"
                    )
        if end_aram and len(end_aram) == len(spc.aram):
            for start, loop in regions:
                try:
                    n = len(brr.decode(spc.aram, start, loop).data)
                except Exception:
                    continue
                # Nine bytes per BRR block, 16 samples per block.
                span = max(9, (n // 16) * 9)
                lo, hi = start, min(start + span, len(end_aram))
                if spc.aram[lo:hi] != end_aram[lo:hi]:
                    byte_changes += 1
        totals["sample_regions_examined"] += len(regions)
        totals["sample_regions_bytes_changed"] += byte_changes
        counts["sample_regions_bytes_changed"] = byte_changes
        per_track[row["track_id"]] = dict(counts)

    args.report.write_text(json.dumps({
        "schema": "snesmdb.runtime_recovery.v1",
        "out_dir": str(args.out_dir),
        "n_tracks": len(per_track),
        "totals": dict(totals),
        "pitch_effect_on_corrected_attacks": dict(pitch_gain),
        "identity_corrections": {k: v[:5] for k, v in changed_ids.items()},
        "per_track": per_track,
    }, indent=1))
    # Attack outcomes and region counters are different units and must not
    # share a denominator -- mixing them would misreport both.
    region_keys = {"sample_regions_examined", "sample_regions_bytes_changed"}
    attacks = {k: v for k, v in totals.items() if k not in region_keys}
    total = sum(attacks.values()) or 1
    print(f"{len(per_track)} tracks, {total:,} attacks")
    for key, value in sorted(attacks.items(), key=lambda kv: -kv[1]):
        print(f"  {key:22} {value:8,}  {100*value/total:5.1f}%")
    print(f"  sample regions examined: {totals['sample_regions_examined']:,}"
          f" | with bytes changed by end of playback: "
          f"{totals['sample_regions_bytes_changed']:,}")
    print("pitch effect on corrected attacks:", dict(pitch_gain))


if __name__ == "__main__":
    main()
