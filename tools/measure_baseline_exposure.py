#!/usr/bin/env python3
"""Compare published sample identities against the ones the DSP actually used.

    measure_baseline_exposure.py <out-dir> <dist-dir> <spc-dir> <report.json>
                                 [--limit N] [--seconds-cap N]

Read-only. Nothing published is modified.

For every note attack it pairs the PUBLISHED `sample_id` -- resolved from the
SPC's initial sample directory -- against the identity computed from the start
pointer the DSP committed at that attack, captured by the instrumented build
and matched by origin (`snesmdb.eventmatch`).

EVIDENCE IS REPORTED AT THE PRECISION IT SUPPORTS. The committed START pointer
is directly observed. The LOOP pointer is the second word of the directory
entry as it stood at sample start, and the DSP may read a loop pointer again
later at a BRR end block -- so it is not established as the runtime value.
`sample_id` incorporates the loop offset, so any identity change is reported
in one of two classes:

    content_differs   the decoded audio itself differs; the change holds
                      whatever the loop pointer turns out to be
    loop_only         the decoded audio is identical and only the loop offset
                      differs, so the change rests on the unverified
                      loop-pointer assumption

A track whose events cannot be matched one-to-one is counted as UNMATCHED and
contributes no identity verdicts at all. Uncertainty is never converted into a
confident identity.
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

from snesmdb import brr, eventmatch, sampleid, spcfile, voices  # noqa: E402

INSTRUMENTED = ROOT / "build" / "spc_dump_evt"


def _decode(aram: bytes, start: int, loop: int, cache: dict):
    key = (start, loop)
    if key not in cache:
        try:
            d = brr.decode(aram, start, loop)
            cache[key] = (
                (sampleid.sample_id(d.data, d.loop_offset), bytes(
                    bytearray((v & 0xFF) for v in d.data[:4096])
                )) if d.data else (None, None)
            )
        except Exception:
            cache[key] = (None, None)
    return cache[key]


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
    rows = [r for r in rows if r.get("ok") and r.get("record_path")]

    totals = collections.Counter()
    evidence = collections.Counter()
    pitch = collections.Counter()
    by_game: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    coverage: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"examined": 0, "available": 0}
    )
    unmatched_tracks: list[str] = []

    for row in rows:
        game = (row.get("tag") or {}).get("game") or "?"
        coverage[game]["available"] += 1
    examined = 0

    for row in rows:
        if args.limit and examined >= args.limit:
            break
        source = spcs.get(row["source"])
        if source is None or row["track_id"] not in published:
            continue
        examined += 1
        game = (row.get("tag") or {}).get("game") or "?"
        coverage[game]["examined"] += 1
        spc = spcfile.load(source)
        seconds = max(5, min(int(row.get("render_seconds") or 30),
                             args.seconds_cap))
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "e.jsonl"
            subprocess.run(
                [str(INSTRUMENTED), str(source), str(log), str(seconds),
                 "--chunk", "1"],
                capture_output=True, timeout=3600,
            )
            commits, writes = [], []
            for line in log.read_text().splitlines() if log.is_file() else []:
                r = json.loads(line)
                if r.get("kind") == "sample":
                    commits.append(r)
                elif "addr" in r:
                    writes.append(r)

        extracted = voices.extract(iter(writes))
        outcome = eventmatch.match(
            extracted.notes, commits, spc.dsp[eventmatch.REG_KON],
            [(int(w["t"]), int(w["data"])) for w in writes
             if int(w["addr"]) == eventmatch.REG_KON],
        )
        if not outcome.ok:
            totals["unmatched_tracks"] += 1
            by_game[game]["unmatched_tracks"] += 1
            unmatched_tracks.append(
                f"{row['track_id']}: {outcome.problems[0][:120]}"
            )
            continue

        # Published identity per (voice, ordinal), read from the event table.
        table = json.loads(
            gzip.decompress((args.dist_dir / published[row["track_id"]]
                             ["events"]).read_bytes())
        )
        pub_by_voice: dict[int, list[str]] = {}
        for event in table["events"]:
            if event["origin"] == "key_on":
                pub_by_voice.setdefault(int(event["voice"]), []).append(
                    event["sample_id"] or ""
                )
        seen = collections.Counter()
        cache: dict = {}
        for note, commit in outcome.pairs:
            voice = int(note.voice)
            ordinal = seen[voice]
            seen[voice] += 1
            pub_list = pub_by_voice.get(voice, [])
            if ordinal >= len(pub_list):
                totals["no_published_counterpart"] += 1
                continue
            was = pub_list[ordinal]
            now, pcm_now = _decode(
                spc.aram, int(commit["start"]), int(commit["loop"]), cache
            )
            if now is None:
                totals["still_unresolved"] += 1
                by_game[game]["still_unresolved"] += 1
                continue
            if not was:
                totals["recovered"] += 1
                by_game[game]["recovered"] += 1
            elif was != now:
                totals["identity_changed"] += 1
                by_game[game]["identity_changed"] += 1
                # Does the change survive the loop-pointer assumption?
                # The PUBLISHED entry is decoded explicitly from the initial
                # directory for this note's SRCN. An earlier version searched
                # the commit cache for a matching identity, which found the
                # old audio only by luck and silently classified a miss as
                # `content_differs` -- inflating the stronger evidence class.
                srcn = int(getattr(note, "srcn", -1))
                base = (spc.dsp[0x5D] << 8) + srcn * 4
                old_pcm = None
                if 0 <= srcn and base + 4 <= len(spc.aram):
                    o_start = spc.aram[base] | (spc.aram[base + 1] << 8)
                    o_loop = spc.aram[base + 2] | (spc.aram[base + 3] << 8)
                    _, old_pcm = _decode(spc.aram, o_start, o_loop, cache)
                evidence[
                    "content_differs" if old_pcm != pcm_now else "loop_only"
                ] += 1
            else:
                totals["unchanged"] += 1
                by_game[game]["unchanged"] += 1

    args.report.write_text(json.dumps({
        "schema": "snesmdb.baseline_exposure.v1",
        "note": (
            "Read-only comparison of published sample identities against the "
            "start pointer the DSP committed at each attack. A four-track "
            "screen can establish exposure but cannot prove unscreened "
            "tracks are unaffected."
        ),
        "tracks_examined": examined,
        "totals": dict(totals),
        "identity_change_evidence": dict(evidence),
        "pitch": dict(pitch),
        "by_game": {k: dict(v) for k, v in by_game.items()},
        "coverage": dict(coverage),
        "unmatched_examples": unmatched_tracks[:20],
    }, indent=1))
    print(f"{examined} tracks examined")
    for key, value in totals.most_common():
        print(f"  {key:26} {value:8,}")
    if evidence:
        print("  identity-change evidence:", dict(evidence))


if __name__ == "__main__":
    main()
