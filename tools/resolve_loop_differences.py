#!/usr/bin/env python3
"""Resolve loop-only identity differences against the loop actually taken.

    resolve_loop_differences.py <out-dir> <dist-dir> <spc-dir> <report.json>
                               [--limit N] [--seconds-cap N]

Read-only. `sample_id`'s definition is untouched.

WITHDRAWN FIGURES. Every number this tool printed before the fixes below is
retracted, not merely superseded. It ran with an unseeded SRCN -- so 13,025
of 38,440 attacks resolved against directory entry 0 -- and a decode cache
keyed on `(start, loop)` with no track in the key, which served one track's
audio for another's. Its "10,955 loop-only of 16,205" and its variable-loop
count of 128 are both artifacts of those two defects; no population under
the corrected tools yields 128. The corrected split, confirmed twice
independently, is 16,195 content differences and 10 loop-only. See
`reconcile_identity_reports.py` and `tests/test_identity_comparison.py`.

The per-attack classifications this tool produced must be RECOMPUTED rather
than carried forward, including any downstream publication-impact estimate
built on them.

A published identity may differ from the one computed at key-on only in its
LOOP OFFSET. On Super Turrican that is 10 of 16,205 differences, and the
loop value captured at sample start is the directory's second word at that
instant -- not proof of the destination the DSP eventually used, because this
driver rewrites directory entries while a voice sustains.

So the destination is observed instead, at the BRR end block where the DSP
takes the loop. Each attack falls into one of three classes, and the third is
not collapsed into either of the others:

    confirmed_different   a loop was taken, and the identity built from the
                          committed start plus that destination differs from
                          what was published
    confirmed_same        a loop was taken and the identity matches
    not_established       no loop was taken during this note, so the runtime
                          destination is unknown. NOT a zero loop offset, and
                          not evidence either way.

A voice that also shows a changing destination within one note is counted
separately: that is a driver rewriting the entry mid-sustain, where no single
loop value describes the note.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import (  # noqa: E402
    eventmatch, identity, spcfile, voices,
)

INSTRUMENTED = ROOT / "build" / "spc_dump_evt"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("out_dir", type=Path)
    p.add_argument("dist_dir", type=Path)
    p.add_argument("spc_dir", type=Path)
    p.add_argument("report", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--seconds-cap", type=int, default=300)
    args = p.parse_args()

    spcs = {q.name: q for q in args.spc_dir.rglob("*.spc")}
    index = json.loads((args.dist_dir / "index.json").read_text())
    published = {e["track_id"]: e for e in index["tracks"]}
    rows = [
        json.loads(line)
        for line in (args.out_dir / "manifest.jsonl").read_text().splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if r.get("ok") and r.get("record_path")
            and r["source"] in spcs and r["track_id"] in published]
    if args.limit:
        rows = rows[: args.limit]

    totals = collections.Counter()
    # Keyed by (track, start, loop). An address pair means nothing
    # without the ARAM it is read from, so a cache shared across
    # tracks serves one track's decode for another's and the verdict
    # becomes track-order dependent.
    cache: dict = {}
    track_key = [""]

    def identity_of(aram, start, loop):
        """Canonical identity via the one identity producer, or None.

        None means "not established" -- an implausible entry, an undecodable
        block, or no samples. It must never be backfilled with a substitute.
        """
        key = (track_key[0], start, loop)
        if key not in cache:
            cache[key] = identity.identity_for_entry(aram, start, loop)[0]
        return cache[key]

    for row in rows:
        source = spcs[row["source"]]
        spc = spcfile.load(source)
        track_key[0] = row["track_id"]
        seconds = max(5, min(int(row.get("render_seconds") or 30),
                             args.seconds_cap))
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "e.jsonl"
            subprocess.run(
                [str(INSTRUMENTED), str(source), str(log), str(seconds),
                 "--chunk", "1"],
                capture_output=True, timeout=3600,
            )
            commits, loops, writes = [], [], []
            for line in log.read_text().splitlines() if log.is_file() else []:
                r = json.loads(line)
                kind = r.get("kind")
                if kind == "sample":
                    commits.append(r)
                elif kind == "loop":
                    loops.append(r)
                elif "addr" in r:
                    writes.append(r)

        # The DSP snapshot carries every voice register the driver
        # never rewrites -- SRCN among them. Omitting it reads
        # those as zero.
        extracted = voices.extract(iter(writes), spc.dsp)
        outcome = eventmatch.match(
            extracted.notes, commits, spc.dsp[eventmatch.REG_KON],
            [(int(w["t"]), int(w["data"])) for w in writes
             if int(w["addr"]) == eventmatch.REG_KON],
        )
        if not outcome.ok:
            totals["unmatched_tracks"] += 1
            continue

        loops_by_voice: dict[int, list] = {}
        for record in loops:
            loops_by_voice.setdefault(int(record["voice"]), []).append(record)
        for value in loops_by_voice.values():
            value.sort(key=lambda r: int(r["t"]))

        table = json.loads(gzip.decompress(
            (args.dist_dir / published[row["track_id"]]["events"]).read_bytes()
        ))
        pub: dict[int, list[str]] = {}
        for event in table["events"]:
            if event["origin"] == "key_on":
                pub.setdefault(int(event["voice"]), []).append(
                    event["sample_id"] or "")

        # Commits per voice in order, so a note's window is [this, next).
        by_voice: dict[int, list] = {}
        for note, commit in outcome.pairs:
            by_voice.setdefault(int(note.voice), []).append(commit)

        seen = collections.Counter()
        for note, commit in outcome.pairs:
            voice = int(note.voice)
            ordinal = seen[voice]
            seen[voice] += 1
            pub_list = pub.get(voice, [])
            if ordinal >= len(pub_list) or not pub_list[ordinal]:
                continue
            was = pub_list[ordinal]
            start = int(commit["start"])
            at_start = identity_of(spc.aram, start, int(commit["loop"]))
            if at_start == was:
                totals["unchanged_at_start"] += 1
                continue

            # The window this note occupies on its voice.
            series = by_voice[voice]
            lo = int(commit["t"])
            hi = (int(series[ordinal + 1]["t"])
                  if ordinal + 1 < len(series) else None)
            taken = [int(r["dest"]) for r in loops_by_voice.get(voice, [])
                     if lo <= int(r["t"]) and (hi is None or int(r["t"]) < hi)]
            if not taken:
                totals["not_established"] += 1
                continue
            if len(set(taken)) > 1:
                totals["destination_changed_mid_note"] += 1
                continue
            runtime = identity_of(spc.aram, start, taken[0])
            if runtime is None:
                totals["not_established"] += 1
            elif runtime == was:
                totals["confirmed_same"] += 1
            else:
                totals["confirmed_different"] += 1

    args.report.write_text(json.dumps({
        "schema": "snesmdb.loop_resolution.v1",
        "tracks": len(rows),
        "totals": dict(totals),
        "note": (
            "A note with no loop taken has an UNKNOWN runtime destination. "
            "That is not a zero loop offset and not evidence either way."
        ),
    }, indent=1))
    print(f"{len(rows)} tracks")
    for key, value in totals.most_common():
        print(f"  {key:30} {value:8,}")


if __name__ == "__main__":
    main()
