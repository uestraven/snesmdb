#!/usr/bin/env python3
"""Does a corpus statistic describe the corpus, or one prolific soundtrack?

    leave_one_game_out.py <dist-dir> [<dist-dir> ...] <report.json>
                          --new GAME [GAME ...]

Read-only, published artifacts only.

An aggregate over a corpus of unequal soundtracks is a weighted average
whose weights nobody chose. Super Bomberman 2 contributes 41,421 legato
steps from 22 tracks -- more than the entire 13-game cohort produced from
362 -- so "the corpus has more legato steps" could describe the corpus or
could describe that one game. The two readings call for different
conclusions and the pooled figure cannot tell them apart.

So every statistic is reported three ways:

    POOLED          every event weighted equally, so a long prolific game
                    counts more. What a model trained on the corpus sees.
    GAME-BALANCED   each game's own statistic averaged unweighted, so a
                    7-track soundtrack counts as much as an 83-track one.
                    What "SNES music does X" would have to mean.
    LEAVE-ONE-OUT   the pooled figure recomputed with one game removed. The
                    delta is that game's influence on the aggregate, which
                    is the only direct evidence of domination.

A statistic whose LOO delta for one game exceeds that game's share of the
corpus is being carried by it.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import statistics
from pathlib import Path


#: Statistics that are COUNTS rather than rates. A leave-one-out delta on
#: a count is that game's own contribution, not evidence of influence over
#: the corpus, because the corpus total is a sum of per-game values.
COUNT_METRICS = frozenset({"distinct_samples"})


def track_stats(table: dict, seconds: float) -> dict:
    """Per-track statistics, computed once and reused for every aggregate."""
    attacks = steps = pitched = 0
    ids: set[str] = set()
    durations: list[float] = []
    by_voice: dict[int, list[tuple[float, int]]] = collections.defaultdict(list)
    for event in table["events"]:
        if event["origin"] != "key_on":
            steps += 1
            continue
        attacks += 1
        if event.get("sample_id"):
            ids.add(event["sample_id"])
        if event.get("duration_sec"):
            durations.append(float(event["duration_sec"]))
        if event["pitch_status"] == "estimated":
            pitched += 1
            by_voice[int(event["voice"])].append(
                (float(event["onset_sec"]),
                 int(round(float(event["midi_note"])))))
    intervals: collections.Counter = collections.Counter()
    for notes in by_voice.values():
        notes.sort()
        for i in range(1, len(notes)):
            delta = notes[i][1] - notes[i - 1][1]
            if -24 <= delta <= 24:
                intervals[delta] += 1
    return {
        "attacks": attacks, "steps": steps, "pitched": pitched,
        "ids": ids, "intervals": intervals,
        "seconds": seconds,
        "median_duration": statistics.median(durations) if durations else None,
    }


def entropy(counter: collections.Counter) -> float | None:
    total = sum(counter.values())
    if not total:
        return None
    return -sum((n / total) * math.log2(n / total) for n in counter.values())


def pooled(tracks: list[dict]) -> dict:
    """Every event weighted equally."""
    attacks = sum(t["attacks"] for t in tracks)
    steps = sum(t["steps"] for t in tracks)
    pitched = sum(t["pitched"] for t in tracks)
    seconds = sum(t["seconds"] for t in tracks)
    ids: set[str] = set()
    intervals: collections.Counter = collections.Counter()
    for t in tracks:
        ids |= t["ids"]
        intervals.update(t["intervals"])
    durations = [t["median_duration"] for t in tracks
                 if t["median_duration"] is not None]
    if not attacks:
        return {}
    return {
        "tracks": len(tracks),
        "attacks": attacks,
        "legato_steps": steps,
        "steps_per_1000_attacks": round(1000 * steps / attacks, 2),
        "pitched_share": round(pitched / attacks, 6),
        "distinct_samples": len(ids),
        "interval_entropy_bits": round(entropy(intervals), 4)
        if intervals else None,
        "attacks_per_second": round(attacks / seconds, 4) if seconds else None,
        "median_note_duration": round(statistics.median(durations), 5)
        if durations else None,
    }


def game_balanced(by_game: dict[str, list[dict]]) -> dict:
    """Each game's own statistic, averaged unweighted."""
    per_game = {}
    for game, tracks in by_game.items():
        got = pooled(tracks)
        if got:
            per_game[game] = got
    if not per_game:
        return {}
    def mean_of(key):
        vals = [g[key] for g in per_game.values() if g.get(key) is not None]
        return round(statistics.fmean(vals), 6) if vals else None
    return {
        "games": len(per_game),
        "mean_steps_per_1000_attacks": mean_of("steps_per_1000_attacks"),
        "mean_pitched_share": mean_of("pitched_share"),
        "mean_interval_entropy_bits": mean_of("interval_entropy_bits"),
        "mean_attacks_per_second": mean_of("attacks_per_second"),
        "mean_median_note_duration": mean_of("median_note_duration"),
        "mean_distinct_samples_per_game": mean_of("distinct_samples"),
        "median_tracks_per_game": statistics.median(
            g["tracks"] for g in per_game.values()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dists", type=Path, nargs="+")
    ap.add_argument("report", type=Path)
    ap.add_argument("--new", nargs="+", required=True,
                    help="published game names of the new cohort")
    args = ap.parse_args()

    *dist_dirs, report_path = args.dists + [args.report]
    dist_dirs = args.dists
    by_game: dict[str, list[dict]] = collections.defaultdict(list)
    seen: set[str] = set()
    for dist in dist_dirs:
        index = json.loads((dist / "index.json").read_text())
        for entry in index["tracks"]:
            if entry["track_id"] in seen:
                continue
            seen.add(entry["track_id"])
            table = json.loads(gzip.decompress(
                (dist / entry["events"]).read_bytes()))
            by_game[entry["game"]].append(track_stats(
                table, float(entry.get("render_seconds") or 0)))

    new = [g for g in args.new if g in by_game]
    missing = [g for g in args.new if g not in by_game]
    old = {g: t for g, t in by_game.items() if g not in set(new)}

    all_tracks = [t for ts in by_game.values() for t in ts]
    full_pooled = pooled(all_tracks)
    full_balanced = game_balanced(by_game)

    # LEAVE ONE GAME OUT, for each new game.
    loo = {}
    for game in sorted(new, key=lambda g: -sum(
            t["attacks"] for t in by_game[g])):
        kept = {g: t for g, t in by_game.items() if g != game}
        kept_tracks = [t for ts in kept.values() for t in ts]
        without = pooled(kept_tracks)
        share_attacks = sum(t["attacks"] for t in by_game[game]) / \
            full_pooled["attacks"]
        share_tracks = len(by_game[game]) / full_pooled["tracks"]
        deltas = {}
        for key in ("steps_per_1000_attacks", "pitched_share",
                    "interval_entropy_bits", "attacks_per_second",
                    "median_note_duration", "distinct_samples"):
            a, b = full_pooled.get(key), without.get(key)
            if a is None or b is None:
                continue
            deltas[key] = {
                "with": a, "without": b, "delta": round(a - b, 6),
                "relative_delta": round((a - b) / b, 6) if b else None,
            }
        loo[game] = {
            "tracks": len(by_game[game]),
            "share_of_corpus_attacks": round(share_attacks, 6),
            "share_of_corpus_tracks": round(share_tracks, 6),
            "pooled_without_this_game": without,
            "deltas": deltas,
            # A game dominates a RATE when removing it moves that rate by
            # more than its share of the corpus would explain.
            #
            # Counts are excluded, and `distinct_samples` is why. Sample
            # banks do not cross games -- each SPC carries its own ARAM --
            # so the corpus total is the SUM of per-game banks and every
            # game necessarily "moves" it by its own contribution. The test
            # flagged 9 of 10 games, which measured the metric's additivity
            # rather than any game's influence.
            "dominates": sorted(
                k for k, v in deltas.items()
                if k not in COUNT_METRICS
                and v["relative_delta"] is not None
                and abs(v["relative_delta"]) > share_attacks
            ),
            "additive_counts": {
                k: v["delta"] for k, v in deltas.items()
                if k in COUNT_METRICS},
        }

    out = {
        "schema": "snesmdb.leave_one_game_out.v1",
        "dists": [str(d) for d in dist_dirs],
        "new_cohort": new,
        "new_cohort_not_found": missing,
        "pooled_full_corpus": full_pooled,
        "game_balanced_full_corpus": full_balanced,
        "pooled_old_cohort_only": pooled(
            [t for ts in old.values() for t in ts]),
        "game_balanced_old_cohort_only": game_balanced(old),
        "pooled_new_cohort_only": pooled(
            [t for g in new for t in by_game[g]]),
        "game_balanced_new_cohort_only": game_balanced(
            {g: by_game[g] for g in new}),
        "leave_one_game_out": loo,
        "per_game": {g: pooled(t) for g, t in sorted(by_game.items())},
        "reading_note": (
            "A pooled aggregate weights every event equally, so a long "
            "prolific soundtrack counts more than a short one. The "
            "game-balanced figure averages each game's own statistic "
            "unweighted. Where the two disagree, the pooled number is "
            "describing soundtrack size as much as musical practice. "
            "`dominates` lists statistics a single game moves by more than "
            "its share of the corpus would explain."
        ),
    }
    args.report.write_text(json.dumps(out, indent=1, default=str))

    print(f"{full_pooled['tracks']:,} tracks, {len(by_game)} games "
          f"({len(new)} new)")
    if missing:
        print(f"  NOT FOUND in the artifacts: {missing}")
    print(f"\n{'statistic':30}{'pooled':>14}{'game-balanced':>16}")
    for pkey, bkey in (
            ("steps_per_1000_attacks", "mean_steps_per_1000_attacks"),
            ("pitched_share", "mean_pitched_share"),
            ("interval_entropy_bits", "mean_interval_entropy_bits"),
            ("attacks_per_second", "mean_attacks_per_second"),
            ("median_note_duration", "mean_median_note_duration")):
        print(f"  {pkey:28}{str(full_pooled.get(pkey)):>14}"
              f"{str(full_balanced.get(bkey)):>16}")
    print(f"\nLEAVE-ONE-GAME-OUT (new cohort), pooled corpus deltas:")
    print(f"{'game':30}{'trk':>5}{'%atk':>7}{'steps/1k':>11}"
          f"{'pitched':>10}{'entropy':>10}{'samples':>9}  dominates")
    for game, info in loo.items():
        d = info["deltas"]
        def fmt(key, places=2):
            v = d.get(key)
            return f"{v['delta']:+.{places}f}" if v else "n/a"
        print(f"  {game[:28]:28}{info['tracks']:>5}"
              f"{100*info['share_of_corpus_attacks']:>6.1f}%"
              f"{fmt('steps_per_1000_attacks'):>11}"
              f"{fmt('pitched_share',4):>10}"
              f"{fmt('interval_entropy_bits',4):>10}"
              f"{fmt('distinct_samples',0):>9}"
              f"  {','.join(info['dominates']) or '-'}")
    print("\n  distinct_samples is additive across games (sample banks do "
          "not cross\n  games), so its column is each game's own "
          "contribution, not influence.")


if __name__ == "__main__":
    main()
