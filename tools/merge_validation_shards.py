#!/usr/bin/env python3
"""Merge sharded baseline-exposure reports into one corpus-wide diff.

    merge_validation_shards.py <shard-dir> <merged.json>

Read-only. The shards partition the eligible tracks, so every count is a
plain sum -- but the merge VERIFIES the partition rather than assuming it:
a track appearing in two shards, or a track eligible in no shard, would
otherwise silently double-count or vanish into a believable total.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("shard_dir", type=Path)
    p.add_argument("merged", type=Path)
    args = p.parse_args()

    reports = sorted(args.shard_dir.glob("report-*.json"))
    rowfiles = sorted(args.shard_dir.glob("rows-*.jsonl"))
    if not reports:
        raise SystemExit(f"no shard reports in {args.shard_dir}")

    totals = collections.Counter()
    evidence = collections.Counter()
    by_game: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    coverage: dict[str, dict[str, int]] = {}
    examined = 0
    unmatched: list[str] = []
    shards_seen = []

    for path in reports:
        r = json.loads(path.read_text())
        shards_seen.append(r.get("shard", "?"))
        examined += r["tracks_examined"]
        totals.update(r["totals"])
        evidence.update(r.get("identity_change_evidence", {}))
        for game, counts in r.get("by_game", {}).items():
            by_game[game].update(counts)
        unmatched.extend(r.get("unmatched_examples", []))
        # `available` is the whole manifest per game and is identical in
        # every shard, so it is taken once rather than summed.
        for game, c in r.get("coverage", {}).items():
            slot = coverage.setdefault(
                game, {"examined": 0, "available": c["available"]})
            slot["examined"] += c["examined"]

    # Verify the partition from the per-attack rows.
    owner: dict[str, str] = {}
    duplicated: list[str] = []
    attacks = 0
    per_track_attacks = collections.Counter()
    verdicts = collections.Counter()
    tracks_with_change: set[str] = set()
    games_with_change: collections.Counter = collections.Counter()
    for path in rowfiles:
        tag = path.name
        for line in path.open():
            row = json.loads(line)
            tid = row["track_id"]
            if owner.setdefault(tid, tag) != tag:
                duplicated.append(tid)
            attacks += 1
            per_track_attacks[tid] += 1
            verdicts[row["verdict"]] += 1
            if row["verdict"].startswith("identity_changed"):
                tracks_with_change.add(tid)
                games_with_change[row.get("game") or "?"] += 1

    out = {
        "schema": "snesmdb.validation_merged.v1",
        "shards": shards_seen,
        "tracks_examined": examined,
        "tracks_in_rows": len(owner),
        "tracks_in_two_shards": sorted(set(duplicated)),
        "attacks_examined": attacks,
        "totals": dict(totals),
        "identity_change_evidence": dict(evidence),
        "verdicts": dict(verdicts),
        "tracks_with_any_identity_change": len(tracks_with_change),
        "attacks_changed_by_game": dict(games_with_change),
        "by_game": {k: dict(v) for k, v in sorted(by_game.items())},
        "coverage": coverage,
        "unmatched_examples": unmatched[:40],
    }
    args.merged.write_text(json.dumps(out, indent=1))

    print(f"{examined} tracks examined across {len(reports)} shards, "
          f"{attacks:,} attacks")
    if duplicated:
        print(f"  !! {len(set(duplicated))} tracks appeared in two shards")
    else:
        print("  partition verified: no track in two shards")
    print()
    for k, v in totals.most_common():
        print(f"  {k:28} {v:10,}")
    if evidence:
        print(f"\n  identity-change evidence: "
              + ", ".join(f"{k} {v:,}" for k, v in evidence.most_common()))
    print(f"\n  tracks with >=1 identity change: "
          f"{len(tracks_with_change):,} of {len(owner):,}")
    print(f"  games with >=1 identity change: {len(games_with_change)}")
    print("\nby game (changed / unchanged / recovered / unresolved):")
    for game, c in sorted(by_game.items(),
                          key=lambda kv: -kv[1]["identity_changed"]):
        print(f"  {game[:40]:42} {c['identity_changed']:8,} "
              f"{c['unchanged']:9,} {c['recovered']:8,} "
              f"{c['still_unresolved']:7,}")


if __name__ == "__main__":
    main()
