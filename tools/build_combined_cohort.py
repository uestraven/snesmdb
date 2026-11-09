#!/usr/bin/env python3
"""Merge two validated extraction cohorts into one publishable out-dir.

    build_combined_cohort.py <out-dir>... <combined-out-dir>
                             [--valid-fraction F] [--test-fraction F]
                             [--seed N]

Does NOT re-extract anything. Records, raw logs and score files are
SYMLINKED from the source cohorts, so the combined distribution is published
from the same bytes the cohorts were audited on -- 2.4 GB of baseline
records are referenced, not copied, and a difference between the combined
release and its sources cannot come from a second extraction run.

What it does compute is the one thing that cannot be merged: THE SPLITS.

A split assignment is a property of a POPULATION. Concatenating two
manifests would carry two independently generated assignments and present
them as a corpus-level split, which is exactly the error that makes a
composer-disjointness claim vacuous -- disjointness would hold inside each
cohort and be untested across them. So the assignment is recomputed over the
union and verified against the result rather than trusted from construction.

Composer metadata is carried through unchanged, including its tiers: a
truncated ID666 credit stays marked truncated. Disjointness is only as good
as the attribution, and a truncated credit is not a confirmed identity --
the report states how much of the population rests on one.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import splits as splits_mod  # noqa: E402

LINKED_DIRS = ("records", "raw", "scores")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", type=Path, nargs="+")
    ap.add_argument("combined", type=Path)
    ap.add_argument("--valid-fraction", type=float, default=0.1)
    ap.add_argument("--test-fraction", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    combined = args.combined
    for name in LINKED_DIRS:
        (combined / name).mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    origin: dict[str, str] = {}
    for source in args.sources:
        src = source.resolve()
        for line in (src / "manifest.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            tid = row["track_id"]
            if tid in origin:
                raise SystemExit(
                    f"track_id {tid!r} appears in both {origin[tid]} and "
                    f"{src}; a combined cohort needs globally unique ids")
            origin[tid] = str(src)
            # Re-point every path at a symlink into this out-dir, so the
            # published tree is built from the source cohort's own bytes.
            for key in ("record_path", "raw_path", "score_path"):
                rel = row.get(key)
                if not rel:
                    continue
                target = src / rel
                link = combined / rel
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.exists(follow_symlinks=False):
                    os.symlink(target, link)
            rows.append(row)

    # SPLITS, recomputed over the union.
    tracks_by_game: dict[str, list[str]] = collections.defaultdict(list)
    game_composers: dict[str, set[str]] = collections.defaultdict(set)
    track_composers: dict[str, list[str]] = {}
    truncated = 0
    for row in rows:
        tag = row.get("tag") or {}
        game = tag.get("game") or "?"
        names = [c for c in (tag.get("composers") or []) if c]
        if not names and tag.get("composer"):
            names = [tag["composer"]]
        tracks_by_game[game].append(row["track_id"])
        game_composers[game].update(names)
        track_composers[row["track_id"]] = names
        if tag.get("composer_truncated"):
            truncated += 1

    assigned = splits_mod.assign(
        tracks_by_game,
        {g: sorted(c) for g, c in game_composers.items()},
        valid_fraction=args.valid_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    leaks = splits_mod.verify_disjoint(assigned.assignment, track_composers)
    if leaks:
        raise SystemExit(
            f"composer leak across splits: {dict(list(leaks.items())[:5])}")

    for row in rows:
        row["split"] = assigned.assignment.get(row["track_id"])

    rows.sort(key=lambda r: r["track_id"])
    (combined / "manifest.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))

    by_split = collections.Counter(r["split"] for r in rows)
    games_by_split: dict[str, set[str]] = collections.defaultdict(set)
    for row in rows:
        games_by_split[row["split"]].add((row.get("tag") or {}).get("game"))
    (combined / "splits.json").write_text(json.dumps({
        "schema": "snesmdb.splits.v1",
        "seed": args.seed,
        "valid_fraction": args.valid_fraction,
        "test_fraction": args.test_fraction,
        "assignment": assigned.assignment,
        "composer_disjoint_verified": True,
        "note": (
            "Recomputed over the combined population. NOT a concatenation of "
            "the source cohorts' assignments: a split is a property of the "
            "population it was drawn from, and two merged assignments would "
            "leave composer-disjointness untested across cohorts."
        ),
    }, indent=1))

    summary = {
        "schema": "snesmdb.combined_cohort.v1",
        "sources": [str(s.resolve()) for s in args.sources],
        "tracks": len(rows),
        "games": len(tracks_by_game),
        "tracks_by_split": dict(by_split),
        "games_by_split": {k: sorted(v) for k, v in games_by_split.items()},
        "distinct_composers": len({c for n in track_composers.values()
                                   for c in n}),
        "tracks_with_truncated_credit": truncated,
        "composer_leaks": {},
        "attribution_caveat": (
            "Composer-disjointness is only as strong as the attribution it "
            "is computed from. Truncated ID666 credits are carried as "
            "truncated and are NOT confirmed full identities; a game-level "
            "credit does not establish track-level authorship."
        ),
    }
    if args.report:
        args.report.write_text(json.dumps(summary, indent=1))

    print(f"combined {len(rows):,} tracks from {len(args.sources)} cohorts, "
          f"{len(tracks_by_game)} games")
    print(f"  records/raw/scores symlinked, not copied")
    print(f"  composer-disjointness verified: no leaks")
    print(f"  distinct composers {summary['distinct_composers']}, "
          f"{truncated:,} tracks on a truncated credit")
    for split in ("train", "valid", "test"):
        print(f"  {split:6} {by_split.get(split, 0):5} tracks  "
              f"{len(games_by_split.get(split, ()))} games")


if __name__ == "__main__":
    main()
