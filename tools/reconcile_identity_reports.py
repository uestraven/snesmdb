#!/usr/bin/env python3
"""One row per attack, carrying BOTH reports' inputs and verdicts.

    reconcile_identity_reports.py <out-dir> <dist-dir> <spc-dir> <report.json>
                                  [--rows rows.jsonl] [--limit N]

Read-only. Nothing here changes a published identity.

Two earlier reports disagreed by exactly 4,211 attacks on the same 28 Super
Turrican tracks, and the disagreement is not reconcilable by inspection
because the two tools asked different questions:

    measure_baseline_exposure   published sample_id  vs  sample_id built from
                                the COMMITTED start and the loop word sitting
                                beside it at commit time
    crosstab_identity_evidence  decoded PCM at the committed start  vs
                                decoded PCM at the INITIAL directory entry

Those differ whenever the published identity is not itself the identity of
the initial directory entry -- so that assumption is the thing to measure,
not to assume. Every attack therefore reports:

    was              the published sample_id (or "" when none)
    id_initdir       identity of the initial directory entry for this SRCN
    id_commit        identity of the committed start + the loop word at commit
    pcm_commit       content hash at the committed start
    pcm_initdir      content hash at the initial directory start
    loop             what the voice actually did before the next key-on

and the cross-classification of the two verdicts is tabulated, so a cell
that cannot exist under one identity definition shows up as a number rather
than as an argument.
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

EVT = ROOT / "build" / "spc_dump_evt"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("out_dir", type=Path)
    p.add_argument("dist_dir", type=Path)
    p.add_argument("spc_dir", type=Path)
    p.add_argument("report", type=Path)
    p.add_argument("--rows", type=Path)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    spcs = {q.name: q for q in args.spc_dir.rglob("*.spc")}
    index = json.loads((args.dist_dir / "index.json").read_text())
    pubmap = {e["track_id"]: e for e in index["tracks"]}
    rows = [json.loads(l) for l in
            (args.out_dir / "manifest.jsonl").read_text().splitlines()
            if l.strip()]
    rows = [r for r in rows if r.get("ok") and r.get("record_path")
            and r["source"] in spcs and r["track_id"] in pubmap]
    if args.limit:
        rows = rows[: args.limit]

    # Keyed by (track, start, loop) and NOT by (start, loop): an address
    # pair means nothing without the ARAM it is read from. A cache hoisted
    # above the track loop serves one track's decode for another's and the
    # verdict then depends on track order -- it moved 3,762 attacks between
    # two otherwise identical runs.
    cache: dict = {}
    track_key = [""]

    def decode(aram, start, loop):
        """`(identity, content hash)` via the one identity producer.

        Keyed by track as well as address: an address pair names a
        location in ONE track's ARAM. The plausibility gate, decode
        and hash all live in `identity.identity_for_entry` and must
        not be reimplemented here.
        """
        key = (track_key[0], start, loop)
        if key not in cache:
            cache[key] = identity.identity_for_entry(
                aram, start, loop)
        return cache[key]

    for row in rows:
        src = spcs[row["source"]]
        spc = spcfile.load(src)
        page = spc.dsp[0x5D]
        track_key[0] = row["track_id"]
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "e.jsonl"
            subprocess.run(
                [str(EVT), str(src), str(log),
                 str(max(5, int(row.get("render_seconds") or 30)))],
                capture_output=True, timeout=3600,
            )
            recs = [json.loads(l) for l in log.read_text().splitlines()] \
                if log.is_file() else []
        commits = [r for r in recs if r.get("kind") == "sample"]
        loops = [r for r in recs if r.get("kind") == "loop"]
        writes = [r for r in recs if "addr" in r]
        # The DSP snapshot MUST be passed. Without it every voice register
        # the driver never rewrites reads as zero -- and SRCN is exactly
        # such a register, so 13,025 attacks resolved against directory
        # entry 0 instead of the entry actually selected.
        ex = voices.extract(iter(writes), spc.dsp)
        m = eventmatch.match(
            ex.notes, commits, spc.dsp[0x4C],
            startup=eventmatch.startup_by_log_order(recs, spc.dsp[0x4C]))
        if not m.ok:
            unmatched += 1
            continue

        by_voice_loops: dict[int, list] = {}
        for r in loops:
            by_voice_loops.setdefault(int(r["voice"]), []).append(r)
        for v in by_voice_loops.values():
            v.sort(key=lambda r: int(r["t"]))

        table = json.loads(gzip.decompress(
            (args.dist_dir / pubmap[row["track_id"]]["events"]).read_bytes()))
        pub: dict[int, list[str]] = {}
        for e in table["events"]:
            if e["origin"] == "key_on":
                pub.setdefault(int(e["voice"]), []).append(e["sample_id"] or "")

        series: dict[int, list] = {}
        for note, commit in m.pairs:
            series.setdefault(int(note.voice), []).append(commit)

        seen = collections.Counter()
        for note, commit in m.pairs:
            voice = int(note.voice)
            ordinal = seen[voice]
            seen[voice] += 1
            plist = pub.get(voice, [])
            if ordinal >= len(plist):
                continue
            was = plist[ordinal]
            srcn = int(getattr(note, "srcn", -1))
            start = int(commit["start"])
            cloop = int(commit["loop"])

            id_commit, pcm_commit = decode(spc.aram, start, cloop)
            _, pcm_commit0 = decode(spc.aram, start, start)
            id_initdir = pcm_initdir = None
            o_start = o_loop = None
            base = (page << 8) + srcn * 4
            if 0 <= srcn and base + 4 <= len(spc.aram):
                o_start = spc.aram[base] | (spc.aram[base + 1] << 8)
                o_loop = spc.aram[base + 2] | (spc.aram[base + 3] << 8)
                id_initdir, _ = decode(spc.aram, o_start, o_loop)
                _, pcm_initdir = decode(spc.aram, o_start, o_start)

            # Where did the published identity actually come from?
            if not was:
                origin = "published_null"
            elif id_initdir == was:
                origin = "published_is_initial_entry"
            elif id_commit == was:
                origin = "published_is_committed_entry"
            else:
                origin = "published_matches_neither"
            pubsrc[origin] += 1

            # Verdict A -- the exposure report's predicate.
            if not was:
                a = "recovered"
            elif id_commit is None:
                a = "still_unresolved"
            elif id_commit == was:
                a = "identity_unchanged"
            else:
                a = "identity_changed"

            # Verdict B -- the cross-tab's predicate.
            if pcm_commit0 is None:
                b = "content_unresolved"
            elif not was:
                b = "content_recovered"
            elif pcm_initdir is None:
                b = "content_recovered"
            elif pcm_initdir == pcm_commit0:
                b = "content_same"
            else:
                b = "content_differs"

            s = series[voice]
            lo = int(commit["t"])
            hi = int(s[ordinal + 1]["t"]) if ordinal + 1 < len(s) else None
            taken = [int(r["dest"]) for r in by_voice_loops.get(voice, [])
                     if lo <= int(r["t"]) and (hi is None or int(r["t"]) < hi)]
            if not taken:
                loop = "loop_not_observed"
            elif len(set(taken)) > 1:
                loop = "loop_variable"
            else:
                ident, _ = decode(spc.aram, start, taken[0])
                loop = ("loop_observed_matches_published" if ident == was
                        else "loop_observed_differs")

            cross[(a, b)] += 1
            loopcls[(loop, a)] += 1

            # The assertion the user asked for, as data: one canonical
            # identity cannot be two different canonical contents.
            if a == "identity_unchanged" and b == "content_differs":
                violations.append({
                    "track_id": row["track_id"], "voice": voice,
                    "ordinal": ordinal, "srcn": srcn,
                    "was": was, "id_commit": id_commit,
                    "id_initdir": id_initdir,
                    "commit_start": start, "commit_loop": cloop,
                    "initdir_start": o_start, "initdir_loop": o_loop,
                })

            if sink:
                sink.write(json.dumps({
                    "track_id": row["track_id"], "voice": voice,
                    "ordinal": ordinal, "t": lo, "srcn": srcn,
                    "midi_note": getattr(note, "midi_note", None),
                    "was": was or None,
                    "id_initdir": id_initdir, "id_commit": id_commit,
                    "commit_start": start, "commit_loop": cloop,
                    "initdir_start": o_start, "initdir_loop": o_loop,
                    "content": b, "identity": a, "loop": loop,
                    "published_origin": origin,
                }) + "\n")
    if sink:
        sink.close()

    avs = sorted({a for a, _ in cross})
    bvs = sorted({b for _, b in cross})
    args.report.write_text(json.dumps({
        "schema": "snesmdb.identity_reconciliation.v1",
        "tracks": len(rows),
        "unmatched_tracks": unmatched,
        "published_identity_origin": dict(pubsrc),
        "identity_by_content": {f"{a}|{b}": n for (a, b), n in cross.items()},
        "loop_by_identity": {f"{a}|{b}": n for (a, b), n in loopcls.items()},
        "identical_identity_different_content": len(violations),
        "violation_examples": violations[:20],
    }, indent=1))

    width = max(len(a) for a in avs) + 2
    print(f"{len(rows)} tracks, {unmatched} unmatched\n")
    print("published identity origin:")
    for k, v in pubsrc.most_common():
        print(f"  {k:34} {v:9,}")
    print("\nexposure verdict (rows) x cross-tab verdict (columns):\n")
    print(" " * width + "".join(f"{b[:20]:>22}" for b in bvs) + f"{'total':>12}")
    for a in avs:
        print(f"{a:<{width}}" + "".join(f"{cross[(a, b)]:>22,}" for b in bvs)
              + f"{sum(cross[(a, b)] for b in bvs):>12,}")
    print(" " * width + "".join(
        f"{sum(cross[(a, b)] for a in avs):>22,}" for b in bvs)
        + f"{sum(cross.values()):>12,}")
    print(f"\nidentical identity classified as different content: "
          f"{len(violations):,}")
    print("\nloop class x exposure verdict:")
    for (l, a), n in sorted(loopcls.items()):
        print(f"  {l:36} {a:20} {n:8,}")


if __name__ == "__main__":
    main()
