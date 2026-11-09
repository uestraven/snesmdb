#!/usr/bin/env python3
"""Did a combined release preserve the cohort it was built from?

    verify_cohort_preserved.py <frozen-dist> <combined-dist> <report.json>

Read-only on both trees.

A combined distribution is assembled from two already-audited cohorts, and
the full verifier checks that the RESULT is internally consistent. It cannot
check the thing that actually goes wrong here: that the combined tree's
share of a cohort still agrees with the frozen release it came from.

A merge that silently dropped the frozen cohort's identity corrections --
by publishing its pre-v4 records without the correction file, say -- would
produce a tree that passes every internal check while shipping 12,336
reverted identities. Nothing downstream would notice, because the reverted
values are exactly the plausible-looking ones the corpus published for
years.

So every event table the frozen release contains must appear in the
combined release with IDENTICAL content. The one field expected to differ
lives in the index, not the events: `split`, which is recomputed over the
combined population by design and is therefore compared separately and
reported rather than asserted.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
from pathlib import Path


def load(dist: Path, rel: str):
    return json.loads(gzip.decompress((dist / rel).read_bytes()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("frozen", type=Path)
    ap.add_argument("combined", type=Path)
    ap.add_argument("report", type=Path)
    args = ap.parse_args()

    frozen_ix = json.loads((args.frozen / "index.json").read_text())
    comb_ix = json.loads((args.combined / "index.json").read_text())
    frozen = {e["track_id"]: e for e in frozen_ix["tracks"]}
    comb = {e["track_id"]: e for e in comb_ix["tracks"]}

    failures: list[str] = []
    stats: collections.Counter = collections.Counter()
    examples: list[dict] = []
    split_moves: collections.Counter = collections.Counter()

    missing = sorted(set(frozen) - set(comb))
    if missing:
        failures.append(
            f"{len(missing)} frozen tracks absent from the combined "
            f"release, e.g. {missing[:3]}")

    for tid in sorted(set(frozen) & set(comb)):
        stats["tracks_compared"] += 1
        a = load(args.frozen, frozen[tid]["events"])
        b = load(args.combined, comb[tid]["events"])

        if a == b:
            stats["event_tables_identical"] += 1
        else:
            stats["event_tables_differ"] += 1
            # Localise the difference rather than reporting "not equal".
            diffs: list[str] = []
            for key in sorted(set(a) | set(b)):
                if key == "events":
                    continue
                if a.get(key) != b.get(key):
                    diffs.append(f"header.{key}: "
                                 f"{a.get(key)!r} -> {b.get(key)!r}")
            ea, eb = a.get("events", []), b.get("events", [])
            if len(ea) != len(eb):
                diffs.append(f"event count {len(ea)} -> {len(eb)}")
            else:
                fields: collections.Counter = collections.Counter()
                for x, y in zip(ea, eb):
                    for key in sorted(set(x) | set(y)):
                        if x.get(key) != y.get(key):
                            fields[key] += 1
                diffs += [f"{k} differs on {v:,} events"
                          for k, v in fields.most_common(6)]
            if len(examples) < 20:
                examples.append({"track_id": tid, "differences": diffs})

        # `split` is RECOMPUTED over the combined population on purpose, so
        # a change here is intended. Reported, never asserted.
        fs, cs = frozen[tid].get("split"), comb[tid].get("split")
        if fs != cs:
            split_moves[f"{fs}->{cs}"] += 1

    if stats["event_tables_differ"]:
        failures.append(
            f"{stats['event_tables_differ']:,} event tables differ from the "
            f"frozen release")

    verdict = "PASS" if not failures else f"FAIL ({len(failures)} checks)"
    args.report.write_text(json.dumps({
        "schema": "snesmdb.cohort_preservation.v1",
        "verdict": verdict,
        "frozen": str(args.frozen),
        "combined": str(args.combined),
        "frozen_tracks": len(frozen),
        "combined_tracks": len(comb),
        "counts": dict(stats),
        "split_reassignments": dict(split_moves),
        "difference_examples": examples,
        "failures": failures,
        "note": (
            "Event tables must be identical. `split` is expected to move: it "
            "is a property of the population and is recomputed over the "
            "combined one."
        ),
    }, indent=1))

    print(f"{verdict}   frozen {len(frozen):,} tracks, combined "
          f"{len(comb):,} tracks")
    for k, v in sorted(stats.items()):
        print(f"  {k:30} {v:8,}")
    if split_moves:
        print(f"  split reassignments (expected): "
              + ", ".join(f"{k} {v:,}" for k, v in split_moves.most_common()))
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        for e in examples[:5]:
            print(f"    {e['track_id']}: {e['differences'][:4]}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
