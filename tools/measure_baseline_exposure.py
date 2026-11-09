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

from snesmdb import (  # noqa: E402
    eventmatch, identity, spcfile, voices,
)

INSTRUMENTED = ROOT / "build" / "spc_dump_evt"


def _decode(aram: bytes, start: int, loop: int, cache: dict, track: str = ""):
    """Cached `(identity, content hash)` via the one identity producer.

    `track` is part of the key on purpose: an address pair identifies a
    location in ONE track's ARAM, so a cache that outlived a track would
    answer with another track's audio. It did, once, and moved 3,762 of
    38,440 attacks between two otherwise identical runs.

    The plausibility gate, the decode and the hash all live in
    `identity.identity_for_entry`. This function must not reimplement any of
    them -- that duplication is what let 15,165 hashes of unwritten memory
    be reported as established identities.
    """
    key = (track, start, loop)
    if key not in cache:
        cache[key] = identity.identity_for_entry(aram, start, loop)
    return cache[key]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("out_dir", type=Path)
    p.add_argument("dist_dir", type=Path)
    p.add_argument("spc_dir", type=Path)
    p.add_argument("report", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--seconds-cap", type=int, default=300)
    p.add_argument("--rows", type=Path,
                   help="per-attack JSONL, for the event-level diff")
    p.add_argument(
        "--only-tracks", type=Path,
        help="newline-delimited track_ids; examine only these. Used to "
             "re-validate the tails of tracks longer than a previous cap, "
             "without re-running the whole corpus.")
    p.add_argument(
        "--shard", default="0/1",
        help="I/N -- examine only tracks whose index mod N equals I. The "
             "per-track work is independent, so shards are mergeable and "
             "each shard's own report is valid for its own subset.",
    )
    args = p.parse_args()
    shard_i, shard_n = (int(x) for x in args.shard.split("/"))
    if not 0 <= shard_i < shard_n:
        p.error(f"--shard {args.shard}: need 0 <= I < N")

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
    sink = args.rows.open("w") if args.rows else None

    # Shard on the position among ELIGIBLE tracks, not on the raw manifest
    # index: filtering after sharding would hand some shards fewer tracks
    # than others for no reason, and `--limit` would then slice a different
    # population per shard.
    eligible = [r for r in rows
                if spcs.get(r["source"]) is not None
                and r["track_id"] in published]
    if args.only_tracks:
        wanted = {l.strip() for l in
                  args.only_tracks.read_text().splitlines() if l.strip()}
        eligible = [r for r in eligible if r["track_id"] in wanted]
        missing = wanted - {r["track_id"] for r in eligible}
        if missing:
            p.error(f"--only-tracks names {len(missing)} track(s) that are "
                    f"not eligible: {sorted(missing)[:5]}")
    eligible = [r for n, r in enumerate(eligible) if n % shard_n == shard_i]

    for row in eligible:
        if args.limit and examined >= args.limit:
            break
        source = spcs[row["source"]]
        examined += 1
        game = (row.get("tag") or {}).get("game") or "?"
        coverage[game]["examined"] += 1
        spc = spcfile.load(source)
        seconds = max(5, min(int(row.get("render_seconds") or 30),
                             args.seconds_cap))
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "e.jsonl"
            # Production chunk size. `--chunk 1` was a leftover from before
            # the KON-acceptance hook existed, when a commit's origin had to
            # be inferred from timestamps; it costs 18.7x and buys nothing
            # now that origin is observed. Both rules were checked against
            # each other on all 28 Super Turrican tracks and agree exactly
            # (16,205 changed / 9,211 unchanged / 13,024 recovered).
            subprocess.run(
                [str(INSTRUMENTED), str(source), str(log), str(seconds)],
                capture_output=True, timeout=3600,
            )
            records, commits, writes = [], [], []
            for line in log.read_text().splitlines() if log.is_file() else []:
                r = json.loads(line)
                records.append(r)
                if r.get("kind") == "sample":
                    commits.append(r)
                elif "addr" in r:
                    writes.append(r)

        # The DSP snapshot carries every voice register the driver
        # never rewrites -- SRCN among them. Omitting it reads
        # those as zero.
        extracted = voices.extract(iter(writes), spc.dsp)
        outcome = eventmatch.match(
            extracted.notes, commits, spc.dsp[eventmatch.REG_KON],
            startup=eventmatch.startup_by_log_order(
                records, spc.dsp[eventmatch.REG_KON]),
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
            # PLAUSIBILITY GATE, before any identity is believed.
            #
            # An address pair the DSP committed is still not a sample. The
            # memory fill (0xFFFF) and the empty entry (0, 0) both decode:
            # ARAM address 0 holds bytes, `brr.decode` reads them, and
            # `sampleid` hashes the result into a confident-looking 16 hex
            # digits. Without this gate the corpus-wide pass reported 15,165
            # such hashes as established identities -- 11,294 of them as
            # RECOVERIES over a correctly-published null, which would have
            # replaced a truthful "unknown" with a fabricated identity.
            #
            # `dirtimeline.plausible` already encodes this test and already
            # has tests; it simply was never applied here.
            start, loop = int(commit["start"]), int(commit["loop"])
            if not identity.plausible_entry((start, loop)):
                totals["unresolved_implausible_entry"] += 1
                by_game[game]["unresolved_implausible_entry"] += 1
                if sink:
                    sink.write(json.dumps({
                        "track_id": row["track_id"], "game": game,
                        "voice": voice, "ordinal": ordinal,
                        "t": int(commit["t"]),
                        "commit_start": start, "commit_loop": loop,
                        "was": was or None, "now": None,
                        "verdict": "unresolved:implausible_entry",
                    }) + "\n")
                continue
            now, pcm_now = _decode(
                spc.aram, int(commit["start"]), int(commit["loop"]), cache,
                row["track_id"],
            )
            verdict = None
            if now is None:
                totals["still_unresolved"] += 1
                by_game[game]["still_unresolved"] += 1
                if sink:
                    sink.write(json.dumps({
                        "track_id": row["track_id"], "game": game,
                        "voice": voice, "ordinal": ordinal,
                        "t": int(commit["t"]),
                        "was": was or None, "now": None,
                        "verdict": "still_unresolved",
                    }) + "\n")
                continue
            if not was:
                totals["recovered"] += 1
                by_game[game]["recovered"] += 1
                verdict = "recovered"
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
                    _, old_pcm = _decode(
                        spc.aram, o_start, o_loop, cache, row["track_id"])
                verdict = ("identity_changed:content_differs"
                           if old_pcm != pcm_now
                           else "identity_changed:loop_only")
                evidence[verdict.split(":")[1]] += 1
            else:
                totals["unchanged"] += 1
                by_game[game]["unchanged"] += 1
                verdict = "unchanged"
            if sink:
                sink.write(json.dumps({
                    "track_id": row["track_id"], "game": game,
                    "voice": voice, "ordinal": ordinal,
                    "t": int(commit["t"]), "srcn": int(getattr(
                        note, "srcn", -1)),
                    "commit_start": int(commit["start"]),
                    "commit_loop": int(commit["loop"]),
                    "was": was or None, "now": now,
                    "verdict": verdict,
                }) + "\n")

    if sink:
        sink.close()
    args.report.write_text(json.dumps({
        "schema": "snesmdb.baseline_exposure.v1",
        "shard": args.shard,
        "tracks_eligible_in_shard": len(eligible),
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
