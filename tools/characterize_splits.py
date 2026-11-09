#!/usr/bin/env python3
"""What do train, validation and test actually contain?

    characterize_splits.py <dist-dir> <report.json>

Read-only, and reads ONLY the published distribution, so a researcher can
reproduce every figure from the download.

Composer-disjointness is verified for these splits, and that is not the same
as the splits supporting a composer-generalization claim. This measures the
dimensions along which the three partitions differ, so a result computed
across them can be interpreted rather than merely reported.

The objective is NOT to equalise the statistics. Unbalanced categories are
a property of 27 commercial soundtracks and reassigning tracks to flatten
them would trade a real limitation for a hidden one. What matters is knowing
WHICH differences change the reading of an experiment:

    a test split short of pitched material inflates any pitch-based metric's
    apparent difficulty; a test split whose samples never appear in training
    makes a timbre-conditioned model look worse than it is; a test split
    carrying one cohort's production path confounds method with music.

Every number here is per split and per track, because a handful of long
tracks can carry an aggregate on their own.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import statistics
from pathlib import Path

SPLITS = ("train", "valid", "test")

#: The five expansion games. Their records were produced by native
#: `events.v4` extraction; the other 22 games' identities were corrected
#: after extraction. The two paths differ in when pitch was estimated, so an
#: uneven split across cohorts confounds production method with music.
EXPANSION_GAMES = {
    "Secret of Evermore", "F-Zero", "Ken Griffey Jr. Baseball",
    "Street Fighter 2 Turbo", "Tetris 2",
}


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    def at(q: float) -> float:
        if len(ordered) == 1:
            return round(ordered[0], 4)
        pos = q * (len(ordered) - 1)
        low = math.floor(pos)
        high = min(low + 1, len(ordered) - 1)
        frac = pos - low
        return round(ordered[low] * (1 - frac) + ordered[high] * frac, 4)
    return {"p10": at(0.10), "median": at(0.50), "p90": at(0.90),
            "mean": round(statistics.fmean(ordered), 4)}


def max_polyphony(events: list[dict]) -> int:
    """Greatest number of attacks sounding at once.

    Computed by sweeping onsets and ends rather than sampling a grid, so a
    brief overlap is not missed. A note with no duration is treated as
    ending at its onset: inventing a length would invent polyphony.
    """
    marks: list[tuple[float, int]] = []
    for event in events:
        if event["origin"] != "key_on":
            continue
        start = float(event["onset_sec"])
        length = event.get("duration_sec")
        end = start + float(length) if length else start
        marks.append((start, 1))
        marks.append((end, -1))
    marks.sort(key=lambda m: (m[0], -m[1]))
    live = peak = 0
    for _, delta in marks:
        live += delta
        peak = max(peak, live)
    return peak


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist", type=Path)
    ap.add_argument("report", type=Path)
    args = ap.parse_args()

    index = json.loads((args.dist / "index.json").read_text())

    per_split: dict[str, dict] = {
        s: {
            "tracks": 0, "games": set(), "attacks": 0, "pitched": 0,
            "seconds": 0.0, "classes": collections.Counter(),
            "composers": set(), "composers_truncated": set(),
            "tracks_truncated_credit": 0, "cohorts": collections.Counter(),
            "identities": set(), "midi_tracks": 0,
            "track_density": [], "track_polyphony": [], "track_pitch": [],
            "track_duration": [], "track_pitched_share": [],
            "track_attacks": [],
        } for s in SPLITS
    }
    games_to_splits: dict[str, set[str]] = collections.defaultdict(set)
    composer_to_splits: dict[str, set[str]] = collections.defaultdict(set)

    for entry in index["tracks"]:
        split = entry.get("split")
        if split not in per_split:
            continue
        bucket = per_split[split]
        game = entry.get("game")
        table = json.loads(gzip.decompress(
            (args.dist / entry["events"]).read_bytes()))
        events = table["events"]
        attacks = [e for e in events if e["origin"] == "key_on"]
        pitched = [e for e in attacks if e["pitch_status"] == "estimated"]
        seconds = float(entry.get("render_seconds") or 0.0)

        bucket["tracks"] += 1
        bucket["games"].add(game)
        bucket["attacks"] += len(attacks)
        bucket["pitched"] += len(pitched)
        bucket["seconds"] += seconds
        bucket["classes"][entry.get("track_class")] += 1
        bucket["cohorts"]["expansion" if game in EXPANSION_GAMES
                           else "baseline"] += 1
        if entry.get("midi"):
            bucket["midi_tracks"] += 1
        names = [c for c in (entry.get("composers") or []) if c]
        for name in names:
            bucket["composers"].add(name)
            composer_to_splits[name].add(split)
            if entry.get("composer_truncated"):
                bucket["composers_truncated"].add(name)
        if entry.get("composer_truncated"):
            bucket["tracks_truncated_credit"] += 1
        games_to_splits[game].add(split)

        for event in attacks:
            if event.get("sample_id"):
                bucket["identities"].add(event["sample_id"])

        bucket["track_attacks"].append(len(attacks))
        if seconds > 0:
            bucket["track_density"].append(len(attacks) / seconds)
        bucket["track_polyphony"].append(max_polyphony(events))
        if attacks:
            bucket["track_pitched_share"].append(len(pitched) / len(attacks))
        if pitched:
            bucket["track_pitch"].append(
                statistics.fmean(float(e["midi_note"]) for e in pitched))
        lengths = [float(e["duration_sec"]) for e in attacks
                   if e.get("duration_sec")]
        if lengths:
            bucket["track_duration"].append(statistics.median(lengths))

    # Sample-identity overlap between splits: a test timbre never seen in
    # training is a harder problem than the same timbre in a new piece.
    overlap = {}
    for a in SPLITS:
        for b in SPLITS:
            if a >= b:
                continue
            ia, ib = per_split[a]["identities"], per_split[b]["identities"]
            shared = ia & ib
            overlap[f"{a}|{b}"] = {
                "shared": len(shared),
                f"share_of_{a}": round(len(shared) / len(ia), 4) if ia else 0,
                f"share_of_{b}": round(len(shared) / len(ib), 4) if ib else 0,
            }

    leaked_games = {g: sorted(s) for g, s in games_to_splits.items()
                    if len(s) > 1}
    leaked_composers = {c: sorted(s) for c, s in composer_to_splits.items()
                        if len(s) > 1}

    out = {
        "schema": "snesmdb.split_characterization.v1",
        "dist": str(args.dist),
        "game_disjoint": not leaked_games,
        "games_in_more_than_one_split": leaked_games,
        "composer_disjoint_by_recorded_credit": not leaked_composers,
        "composers_in_more_than_one_split": leaked_composers,
        "sample_identity_overlap": overlap,
        "splits": {},
    }
    for split in SPLITS:
        b = per_split[split]
        out["splits"][split] = {
            "tracks": b["tracks"],
            "games": len(b["games"]),
            "game_names": sorted(x for x in b["games"] if x),
            "attacks": b["attacks"],
            "seconds": round(b["seconds"], 1),
            "pitched_attacks": b["pitched"],
            "pitched_share": round(b["pitched"] / b["attacks"], 4)
            if b["attacks"] else None,
            "track_classes": dict(b["classes"]),
            "tracks_with_midi": b["midi_tracks"],
            "distinct_composers": len(b["composers"]),
            "composers_resting_on_a_truncated_credit":
                len(b["composers_truncated"]),
            "tracks_with_truncated_credit": b["tracks_truncated_credit"],
            "cohorts": dict(b["cohorts"]),
            "distinct_sample_identities": len(b["identities"]),
            "per_track": {
                "attacks": _percentiles([float(x)
                                         for x in b["track_attacks"]]),
                "attacks_per_second": _percentiles(b["track_density"]),
                "max_polyphony": _percentiles([float(x)
                                               for x in b["track_polyphony"]]),
                "mean_midi_note": _percentiles(b["track_pitch"]),
                "median_note_duration_sec": _percentiles(b["track_duration"]),
                "pitched_share": _percentiles(b["track_pitched_share"]),
            },
        }
    args.report.write_text(json.dumps(out, indent=1))

    print(f"game-disjoint: {out['game_disjoint']}   "
          f"composer-disjoint (by recorded credit): "
          f"{out['composer_disjoint_by_recorded_credit']}\n")
    rows = [
        ("tracks", lambda d: f"{d['tracks']:,}"),
        ("games", lambda d: str(d["games"])),
        ("attacks", lambda d: f"{d['attacks']:,}"),
        ("seconds", lambda d: f"{d['seconds']:,.0f}"),
        ("pitched share", lambda d: f"{100*d['pitched_share']:.2f}%"),
        ("distinct composers", lambda d: str(d["distinct_composers"])),
        ("  on truncated credit",
         lambda d: str(d["composers_resting_on_a_truncated_credit"])),
        ("tracks w/ truncated credit",
         lambda d: f"{d['tracks_with_truncated_credit']:,}"),
        ("distinct identities",
         lambda d: f"{d['distinct_sample_identities']:,}"),
        ("tracks with MIDI", lambda d: f"{d['tracks_with_midi']:,}"),
        ("baseline / expansion",
         lambda d: f"{d['cohorts'].get('baseline',0)} / "
                   f"{d['cohorts'].get('expansion',0)}"),
        ("median attacks/track",
         lambda d: f"{d['per_track']['attacks'].get('median',0):,.0f}"),
        ("median attacks/sec",
         lambda d: f"{d['per_track']['attacks_per_second'].get('median',0):.2f}"),
        ("median max polyphony",
         lambda d: f"{d['per_track']['max_polyphony'].get('median',0):.1f}"),
        ("median mean pitch",
         lambda d: f"{d['per_track']['mean_midi_note'].get('median',0):.1f}"),
        ("median note length",
         lambda d: f"{d['per_track']['median_note_duration_sec'].get('median',0):.3f}s"),
    ]
    print(f"{'':30}{'train':>14}{'valid':>14}{'test':>14}")
    for label, fn in rows:
        cells = "".join(f"{fn(out['splits'][s]):>14}" for s in SPLITS)
        print(f"{label:30}{cells}")
    print("\nsample-identity overlap:")
    for pair, info in overlap.items():
        a, b = pair.split("|")
        print(f"  {a:6} vs {b:6} shared {info['shared']:>5}  "
              f"{100*info[f'share_of_{b}']:.1f}% of {b}'s identities")
    print("\nclasses per split:")
    for split in SPLITS:
        print(f"  {split:6} {out['splits'][split]['track_classes']}")


if __name__ == "__main__":
    main()
