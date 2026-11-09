#!/usr/bin/env python3
"""Per attack: which parts of its sample identity are actually established.

    crosstab_identity_evidence.py <out-dir> <dist-dir> <spc-dir> <report.json>
                                  [--limit N]

Read-only. `sample_id` and its hash are untouched.

WITHDRAWN FIGURES. This tool's published cross-tabulation is retracted in
full, along with everything derived from it -- notably the Super Turrican
publication-impact estimate of ~15,885 correctable and 17,776 uncertain
identities, and the content split of 20,416 / 13,024 / 5,000. Those cells
are artifacts of two defects, both since fixed here:

    unseeded SRCN       `voices.extract` was called without the DSP
                        snapshot, so every SRCN the driver never rewrites
                        read as 0 and 13,025 of 38,440 attacks resolved
                        against directory entry 0.
    shared decode cache keyed on `(start, loop)` with no track, so one
                        track's audio answered for another's and 3,762
                        attacks moved between otherwise identical runs.

The corrected measurement lives in `reconcile_identity_reports.py`, which
reproduces the exposure study exactly (16,205 changed / 9,211 unchanged /
13,024 recovered) with zero identity-unchanged attacks classified as
different content. Per-attack classifications must be RECOMPUTED, not
carried forward; see `tests/test_identity_comparison.py`.

A canonical identity has two inputs and they do not have equal standing:

    start pointer   DIRECTLY OBSERVED. The DSP commits it at key-on and the
                    instrumented build records it.
    BRR content     INFERRED from the initial ARAM at that address. A
                    confirmed start does not establish that every byte
                    consumed matched the snapshot; that limitation stands.
    loop offset     OBSERVED only if the note actually looped. A note that
                    never reached a BRR end block has NO runtime destination
                    -- and no instrument can supply one, because the event
                    did not happen. That is a limit of the musical event,
                    not of the extractor.

So the output is a cross-tabulation of content evidence against loop
evidence, because the two populations overlap and neither contains the other.
Counting N content differences and M confirmed loop differences as N-M
affected attacks would be wrong in both directions. (The specific counts
once quoted here came from the defective run and are withdrawn above.)
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

    cross = collections.Counter()
    unmatched = 0
    # Keyed by (track, start, loop). An address pair means nothing
    # without the ARAM it is read from, so a cache shared across
    # tracks serves one track's decode for another's and the verdict
    # becomes track-order dependent.
    dec: dict = {}
    track_key = [""]

    def decode(aram, start, loop):
        """`(identity, content hash)` via the one identity producer.

        Keyed by track as well as address: an address pair names a
        location in ONE track's ARAM. The plausibility gate, decode
        and hash all live in `identity.identity_for_entry` and must
        not be reimplemented here.
        """
        key = (track_key[0], start, loop)
        if key not in dec:
            dec[key] = identity.identity_for_entry(
                aram, start, loop)
        return dec[key]

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
        startup = eventmatch.startup_by_log_order(recs, spc.dsp[0x4C])
        # The DSP snapshot carries every voice register the driver
        # never rewrites -- SRCN among them. Omitting it reads
        # those as zero.
        ex = voices.extract(iter(writes), spc.dsp)
        m = eventmatch.match(ex.notes, commits, spc.dsp[0x4C], startup=startup)
        if not m.ok:
            unmatched += 1
            continue

        loops_by_voice: dict[int, list] = {}
        for r in loops:
            loops_by_voice.setdefault(int(r["voice"]), []).append(r)
        for v in loops_by_voice.values():
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
            was = plist[ordinal] if ordinal < len(plist) else None
            if was is None:
                continue
            start = int(commit["start"])
            srcn = int(getattr(note, "srcn", -1))

            # CONTENT: decoded audio at the committed start, against the
            # audio at the address the published identity came from.
            _, new_pcm = decode(spc.aram, start, start)
            old_pcm = None
            base = (page << 8) + srcn * 4
            if 0 <= srcn and base + 4 <= len(spc.aram):
                o_start = spc.aram[base] | (spc.aram[base + 1] << 8)
                _, old_pcm = decode(spc.aram, o_start, o_start)
            if new_pcm is None:
                content = "content_unresolved"
            elif not was:
                content = "content_recovered"
            elif old_pcm is None:
                content = "content_recovered"
            elif old_pcm == new_pcm:
                content = "content_same"
            else:
                content = "content_differs"

            # LOOP: destination actually taken during this note.
            s = series[voice]
            lo = int(commit["t"])
            hi = int(s[ordinal + 1]["t"]) if ordinal + 1 < len(s) else None
            taken = [int(r["dest"]) for r in loops_by_voice.get(voice, [])
                     if lo <= int(r["t"]) and (hi is None or int(r["t"]) < hi)]
            if not taken:
                loop = "loop_not_observed"
            elif len(set(taken)) > 1:
                loop = "loop_variable"
            else:
                ident, _ = decode(spc.aram, start, taken[0])
                loop = ("loop_observed_matches_published" if ident == was
                        else "loop_observed_differs")
            cross[(content, loop)] += 1

    contents = sorted({c for c, _ in cross})
    loopcls = sorted({l for _, l in cross})
    args.report.write_text(json.dumps({
        "schema": "snesmdb.identity_evidence.v1",
        "tracks": len(rows),
        "unmatched_tracks": unmatched,
        "evidence_standing": {
            "start_pointer": "directly observed at key-on",
            "brr_content": "inferred from initial ARAM; byte stability "
                           "during playback NOT established",
            "loop_offset": "observed only when the note actually looped",
        },
        "crosstab": {f"{c}|{l}": n for (c, l), n in cross.items()},
    }, indent=1))

    width = max(len(c) for c in contents) + 2
    print(f"{len(rows)} tracks, {unmatched} unmatched\n")
    print(" " * width + "".join(f"{l[:26]:>28}" for l in loopcls))
    for c in contents:
        print(f"{c:<{width}}" +
              "".join(f"{cross[(c, l)]:>28,}" for l in loopcls))
    print(f"\ntotal attacks cross-tabulated: {sum(cross.values()):,}")


if __name__ == "__main__":
    main()
