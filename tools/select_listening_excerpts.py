#!/usr/bin/env python3
"""Choose the listening experiment's excerpts, deterministically.

    select_listening_excerpts.py <rows.jsonl> <dist-dir> <plan.json>
                                 [--window 10] [--seed 20261108]
                                 [--per-stratum 4]

Read-only, and emits no audio -- only a plan. Audio is built by the render
stage into a private scratch directory.

An excerpt is a time window on one track, and a window contains many attacks
of mixed classes. So a window is assigned to a stratum only if it CONTAINS
the class of interest and contains none of the classes that would confound
it:

    content_differs   >=1 attack whose corrected identity is different
                      audio, and 0 unsuitable attacks. Expected audible.
    loop_only         >=1 attack differing only in loop point, and 0
                      unsuitable attacks. Audible only if the note actually
                      reaches its loop -- which is the point.
    null_same_track   0 changed and 0 unsuitable attacks, on a track that
                      IS affected elsewhere. A and B must be byte-identical.
    null_other_game   the same, on a game with no changes at all.

UNSUITABLE means the baseline published an identity and the correction
establishes none -- an implausible directory entry. Those events must not be
given a substitute sample, so candidate B would fall silent where A plays a
note. That is a real difference, but it is a difference in HANDLING rather
than in identity, and mixing it into an identity A/B would let a listener
score a missing note as a wrong timbre. Such windows are excluded from every
stratum and counted separately, so the exclusion is visible rather than
quiet.

The two null strata are not padding. Their A and B renders are identical by
construction, which is CHECKED rather than asserted, so a listener reporting
a difference there is telling us about the procedure and not about the data.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import identity  # noqa: E402

CHANGED = ("identity_changed:content_differs", "identity_changed:loop_only")
UNSUITABLE = ("unresolved:implausible_entry", "still_unresolved")


def gated_verdict(row: dict) -> str:
    """The row's verdict with the plausibility rule applied.

    The corpus pass predates the gate, so its raw verdicts can claim an
    identity for an unwritten entry. Re-deriving here keeps the plan honest
    without re-running 21 minutes of emulation.
    """
    start, loop = row.get("commit_start"), row.get("commit_loop")
    if start is None:
        return row["verdict"]
    if not identity.plausible_entry((start, loop)):
        return "unresolved:implausible_entry"
    return row["verdict"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("rows", type=Path, nargs="+")
    p.add_argument("dist_dir", type=Path)
    p.add_argument("plan", type=Path)
    p.add_argument("--window", type=float, default=10.0)
    p.add_argument("--seed", type=int, default=20261108)
    p.add_argument("--per-stratum", type=int, default=4)
    args = p.parse_args()

    index = json.loads((args.dist_dir / "index.json").read_text())
    pub = {e["track_id"]: e for e in index["tracks"]}

    # Per (track, voice, ordinal): the gated verdict and the corrected id.
    byattack: dict[tuple[str, int, int], dict] = {}
    for path in args.rows:
        for line in path.open():
            row = json.loads(line)
            key = (row["track_id"], int(row["voice"]), int(row["ordinal"]))
            # Tail re-runs supersede capped runs for the same attack.
            byattack[key] = row

    per_track: dict[str, list[dict]] = collections.defaultdict(list)
    for (tid, _, _), row in byattack.items():
        per_track[tid].append(row)

    games = {tid: pub[tid].get("game") for tid in per_track if tid in pub}
    changed_tracks = {
        tid for tid, rows in per_track.items()
        if any(gated_verdict(r) in CHANGED for r in rows)
    }
    changed_games = {games.get(t) for t in changed_tracks}

    # Attack onset times come from the published events, which is what the
    # listener will hear; the rows carry DSP ticks, not seconds.
    windows: list[dict] = []
    stats = collections.Counter()
    for tid, erow in pub.items():
        if tid not in per_track:
            continue
        table = json.loads(gzip.decompress(
            (args.dist_dir / erow["events"]).read_bytes()))
        ordinals: collections.Counter = collections.Counter()
        marks: list[tuple[float, str]] = []
        for event in table["events"]:
            if event["origin"] != "key_on":
                continue
            voice = int(event["voice"])
            ordinal = ordinals[voice]
            ordinals[voice] += 1
            row = byattack.get((tid, voice, ordinal))
            verdict = gated_verdict(row) if row else "not_examined"
            marks.append((float(event["onset_sec"]), verdict))
        if not marks:
            continue
        duration = float(table.get("duration_sec") or 0)
        step = args.window
        t = 0.0
        while t + step <= max(step, duration):
            inside = [v for (onset, v) in marks if t <= onset < t + step]
            if not inside:
                t += step
                continue
            c = collections.Counter(inside)
            n_changed = sum(c[k] for k in CHANGED)
            n_unsuitable = sum(c[k] for k in UNSUITABLE)
            stratum = None
            if n_unsuitable:
                stats["windows_excluded_unsuitable_present"] += 1
            elif c["identity_changed:content_differs"]:
                stratum = "content_differs"
            elif c["identity_changed:loop_only"]:
                stratum = "loop_only"
            elif n_changed == 0 and tid in changed_tracks:
                stratum = "null_same_track"
            elif n_changed == 0 and games.get(tid) not in changed_games:
                stratum = "null_other_game"
            if stratum:
                stats[f"windows_available:{stratum}"] += 1
                windows.append({
                    "track_id": tid, "game": games.get(tid),
                    "start_sec": round(t, 3),
                    "window_sec": step,
                    "stratum": stratum,
                    "attacks_in_window": len(inside),
                    "attacks_changed": n_changed,
                    "attacks_unsuitable": n_unsuitable,
                    "verdict_counts": dict(c),
                })
            t += step

    # Deterministic choice: sort, then sample with a fixed seed.
    rng = random.Random(args.seed)
    chosen: list[dict] = []
    unpopulated: list[str] = []
    for stratum in ("content_differs", "loop_only",
                    "null_same_track", "null_other_game"):
        pool = sorted(
            [w for w in windows if w["stratum"] == stratum],
            key=lambda w: (-w["attacks_changed"], w["track_id"],
                           w["start_sec"]),
        )
        # Prefer windows richest in the class of interest, but spread across
        # tracks so one track cannot dominate a stratum.
        # Spread across GAMES first, then tracks. Deduplicating on track
        # alone drew all four null_other_game excerpts from one game
        # (whichever sorted first), which would have made the bias control
        # a test of one soundtrack rather than of the corpus.
        picked: list[dict] = []
        seen_games: set[str] = set()
        seen_tracks: set[str] = set()
        # Spread by game ONLY in the null strata. There, diversity is the
        # control -- one soundtrack cannot stand in for the corpus. In the
        # signal strata the window richest in the class of interest is what
        # makes a real difference detectable, and trading that for game
        # diversity put a 1-change-in-170 window into content_differs,
        # where it would read as a null and tell us nothing.
        spread_by_game = stratum.startswith("null_")
        for pass_no in (0, 1) if spread_by_game else (1,):
            for w in pool:
                if len(picked) >= args.per_stratum:
                    break
                if w["track_id"] in seen_tracks:
                    continue
                if pass_no == 0 and w["game"] in seen_games:
                    continue
                picked.append(w)
                seen_games.add(w["game"])
                seen_tracks.add(w["track_id"])
        if len(picked) < args.per_stratum:
            rest = [w for w in pool if w not in picked]
            rng.shuffle(rest)
            picked += rest[: args.per_stratum - len(picked)]
        if not pool:
            unpopulated.append(stratum)
        chosen += picked

    for n, w in enumerate(chosen):
        w["excerpt_id"] = f"ex{n:02d}"

    args.plan.write_text(json.dumps({
        "schema": "snesmdb.listening_plan.v1",
        "seed": args.seed,
        "window_sec": args.window,
        "per_stratum": args.per_stratum,
        "strata": {
            "content_differs": "corrected identity is different audio",
            "loop_only": "differs only in loop point",
            "null_same_track": "no change; affected track. A must equal B",
            "null_other_game": "no change; unaffected game. A must equal B",
        },
        "excluded": {
            "rule": "a window containing any attack whose correction "
                    "establishes no identity is excluded from every "
                    "stratum, because candidate B would fall silent and a "
                    "missing note is not a wrong timbre",
            "windows_excluded": stats["windows_excluded_unsuitable_present"],
        },
        "availability": {k.split(":", 1)[1]: v for k, v in stats.items()
                         if k.startswith("windows_available:")},
        "unpopulated_strata": {
            name: "no window contains this class WITHOUT also containing an "
                  "attack whose correction establishes no identity, so the "
                  "stratum cannot be presented as a clean A/B and is "
                  "reported empty rather than filled with a confounded "
                  "window"
            for name in unpopulated
        },
        "tracks_affected": len(changed_tracks),
        "excerpts": chosen,
    }, indent=1))

    print(f"windows available per stratum:")
    for k, v in sorted(stats.items()):
        print(f"  {k:46} {v:7,}")
    print(f"\nchosen {len(chosen)} excerpts:")
    for w in chosen:
        print(f"  {w['excerpt_id']}  {w['stratum']:16} {w['track_id']:28} "
              f"t={w['start_sec']:7.1f}s  attacks={w['attacks_in_window']:4} "
              f"changed={w['attacks_changed']:4}")


if __name__ == "__main__":
    main()
