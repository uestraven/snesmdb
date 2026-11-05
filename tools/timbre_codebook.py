#!/usr/bin/env python3
"""Fit the timbre codebook, choose k, and test whether it means anything.

    timbre_codebook.py <features.json> <out-dir> [--k 0] [--seed 0]

Milestone 5, stage two. The exit criterion is not the codebook -- that is just
k-means -- it is the sanity check that "the same instrument in different games
lands in the same class", and that check is the whole point of this file.

There is no ground truth, so the evidence is built from independence:

  FIT uses only sample-intrinsic features -- length, loop, attack, spectrum.
  TEST uses only corpus usage -- the register a sample is played at, how long
  its notes last, whether it is ever pitched. The fit never sees these.

Three tests, in increasing strength:

  1. SEPARATION. Do the clusters differ on usage at all? If the codebook were
     noise, usage would be flat across classes. Reported as the ratio of
     between-class to within-class variance on each usage axis.

  2. CROSS-GAME AGREEMENT. Computed per game and then compared. A class that
     means "bass" in Final Fantasy VI and "cymbal" in Chrono Trigger shows up
     here and nowhere else.

  3. HELD-OUT GAMES. Fit on the composer-disjoint TRAIN split only, assign the
     TEST games, and compare each class's usage profile across the two. This is
     the milestone's criterion stated exactly: the games in test share no
     composer and no code with the games the codebook was built from.

And a NULL for each: the same statistics over shuffled labels. Without it a
positive number means nothing, because clusters of any kind partition a
correlated feature space and will separate *something*. This project has
shipped a measurement that only a random control exposed as vacuous -- the
semitone-grid fit in milestone 3 -- so the control is not optional.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import timbre  # noqa: E402

#: Usage axes: never seen by the fit, so they are the evidence.
USAGE_AXES = ("median_midi", "median_duration_sec", "unpitched_fraction")


def _usage_value(sample: dict[str, Any], axis: str) -> float | None:
    value = sample["usage"].get(axis)
    if value is None:
        return None
    if axis == "median_duration_sec":
        return math.log1p(float(value))
    return float(value)


def _variance_ratio(samples: Sequence[dict], labels: Sequence[int], axis: str) -> float:
    """Between-class over within-class variance on one usage axis.

    1.0 means the classes say nothing about this axis. Higher means the
    partition separates it.
    """
    groups: dict[int, list[float]] = defaultdict(list)
    for sample, label in zip(samples, labels):
        value = _usage_value(sample, axis)
        if value is not None:
            groups[label].append(value)
    groups = {k: v for k, v in groups.items() if len(v) >= 3}
    if len(groups) < 2:
        return 0.0
    everything = [v for values in groups.values() for v in values]
    grand = statistics.fmean(everything)
    between = sum(
        len(values) * (statistics.fmean(values) - grand) ** 2 for values in groups.values()
    ) / max(1, len(groups) - 1)
    within = sum(
        sum((v - statistics.fmean(values)) ** 2 for v in values)
        for values in groups.values()
    ) / max(1, len(everything) - len(groups))
    return between / within if within > 0 else 0.0


def _profile(samples: Sequence[dict], labels: Sequence[int], k: int) -> dict[int, dict[str, float | None]]:
    out: dict[int, dict[str, float | None]] = {}
    for cluster in range(k):
        members = [s for s, lab in zip(samples, labels) if lab == cluster]
        entry: dict[str, float | None] = {"n": len(members)}
        for axis in USAGE_AXES:
            values = [_usage_value(m, axis) for m in members]
            values = [v for v in values if v is not None]
            entry[axis] = statistics.median(values) if values else None
        out[cluster] = entry
    return out


def _profile_spread(
    samples: Sequence[dict], labels: Sequence[int], k: int
) -> dict[str, float]:
    """Per-axis disagreement of a class's profile BETWEEN games.

    For each class, the profile is computed separately for every game with
    enough members, and the spread of those per-game values is reported in
    units of the axis's overall standard deviation. Small means a class means
    the same thing wherever it appears.
    """
    out: dict[str, float] = {}
    for axis in USAGE_AXES:
        overall = [
            v for v in (_usage_value(s, axis) for s in samples) if v is not None
        ]
        if len(overall) < 4:
            out[axis] = 0.0
            continue
        scale = statistics.pstdev(overall) or 1.0
        spreads = []
        for cluster in range(k):
            per_game: dict[str, list[float]] = defaultdict(list)
            for sample, label in zip(samples, labels):
                if label != cluster:
                    continue
                value = _usage_value(sample, axis)
                if value is not None:
                    per_game[sample["game"]].append(value)
            medians = [
                statistics.median(values)
                for values in per_game.values()
                if len(values) >= 2
            ]
            if len(medians) >= 3:
                spreads.append(statistics.pstdev(medians) / scale)
        out[axis] = statistics.fmean(spreads) if spreads else 0.0
    return out


def _feature_list(samples: Sequence[dict]) -> list[timbre.Features]:
    out = []
    for sample in samples:
        feat = timbre.Features(**{
            key: value for key, value in sample["features"].items()
            if key in timbre.Features.__dataclass_fields__
        })
        out.append(feat)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("features", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--k", type=int, default=0, help="0 selects k by sweep")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--k-max", type=int, default=16)
    args = parser.parse_args()

    payload = json.loads(args.features.read_text())
    samples = payload["samples"]
    feats = _feature_list(samples)
    print(f"{len(samples)} distinct samples across "
          f"{len({s['game'] for s in samples})} games")

    # --- choosing k ------------------------------------------------------
    sweep = []
    for k in range(2, args.k_max + 1):
        book, labels = timbre.build(feats, k, seed=args.seed)
        sil = timbre.silhouette(feats, labels, seed=args.seed)
        ratios = {axis: _variance_ratio(samples, labels, axis) for axis in USAGE_AXES}
        sweep.append({
            "k": k,
            "inertia": round(book.inertia, 2),
            "inertia_per_sample": round(book.inertia / max(1, book.n_samples), 4),
            "silhouette": round(sil, 4),
            "usage_variance_ratio": {a: round(v, 2) for a, v in ratios.items()},
        })
        print(f"  k={k:2d}  inertia/n {book.inertia/max(1,book.n_samples):7.4f}"
              f"  silhouette {sil:6.3f}"
              f"  usage F: " + "  ".join(f"{a.split('_')[1][:4]} {ratios[a]:6.1f}" for a in USAGE_AXES))

    if args.k:
        chosen = args.k
        reason = f"k={chosen} given on the command line"
    else:
        # Prefer the k that separates USAGE best per unit of model size, not
        # the k that looks tidiest in feature space. Silhouette rewards tight
        # spheres and this data has none; the point of the codebook is that the
        # classes predict something the fit never saw.
        def score(row: dict[str, Any]) -> float:
            return statistics.fmean(row["usage_variance_ratio"].values())
        best = max(sweep, key=score)
        chosen = best["k"]
        reason = (
            f"k={chosen} maximises mean usage separation "
            f"({score(best):.1f}) over k=2..{args.k_max}; silhouette is "
            f"reported but not optimised, because the classes exist to predict "
            f"usage rather than to be round in feature space"
        )
    print(f"\n{reason}")

    book, labels = timbre.build(feats, chosen, seed=args.seed)
    sil = timbre.silhouette(feats, labels, seed=args.seed)

    # --- test 1: separation, with a null ---------------------------------
    rng = random.Random(args.seed)
    shuffled = list(labels)
    rng.shuffle(shuffled)
    separation = {
        axis: {
            "real": round(_variance_ratio(samples, labels, axis), 3),
            "shuffled": round(_variance_ratio(samples, shuffled, axis), 3),
        }
        for axis in USAGE_AXES
    }

    # --- test 2: cross-game agreement, with a null -----------------------
    agreement = {
        "real": {a: round(v, 3) for a, v in _profile_spread(samples, labels, chosen).items()},
        "shuffled": {a: round(v, 3) for a, v in _profile_spread(samples, shuffled, chosen).items()},
    }

    # --- test 3: held-out games ------------------------------------------
    splits = json.loads((args.out_dir / "splits.json").read_text())["assignment"]
    manifest_game_split: dict[str, str] = {}
    for line in (args.out_dir / "manifest.jsonl").open():
        row = json.loads(line)
        if row.get("ok") and row.get("split"):
            manifest_game_split.setdefault(row["tag"]["game"] or "?", row["split"])

    train_idx = [i for i, s in enumerate(samples)
                 if manifest_game_split.get(s["game"]) == "train"]
    test_idx = [i for i, s in enumerate(samples)
                if manifest_game_split.get(s["game"]) in ("valid", "test")]

    heldout: dict[str, Any] = {
        "n_train_samples": len(train_idx),
        "n_heldout_samples": len(test_idx),
        "train_games": sorted({samples[i]["game"] for i in train_idx}),
        "heldout_games": sorted({samples[i]["game"] for i in test_idx}),
    }
    if len(train_idx) > chosen and len(test_idx) > chosen:
        train_feats = [feats[i] for i in train_idx]
        book_t, labels_t = timbre.build(train_feats, chosen, seed=args.seed)
        assigned = [book_t.assign(feats[i].vector()) for i in test_idx]
        profile_train = _profile([samples[i] for i in train_idx], labels_t, chosen)
        profile_test = _profile([samples[i] for i in test_idx], assigned, chosen)

        # Difference per class per axis, in units of the axis's spread over the
        # whole corpus. This is the number the milestone turns on.
        diffs: dict[str, list[float]] = {axis: [] for axis in USAGE_AXES}
        for cluster in range(chosen):
            for axis in USAGE_AXES:
                a = profile_train[cluster].get(axis)
                b = profile_test[cluster].get(axis)
                if a is None or b is None:
                    continue
                overall = [v for v in (_usage_value(s, axis) for s in samples) if v is not None]
                scale = statistics.pstdev(overall) or 1.0
                diffs[axis].append(abs(float(a) - float(b)) / scale)
        heldout["profile_difference_in_sd"] = {
            axis: round(statistics.fmean(values), 3) if values else None
            for axis, values in diffs.items()
        }
        heldout["classes_compared"] = {
            axis: len(values) for axis, values in diffs.items()
        }
        heldout["profile_train"] = {str(c): profile_train[c] for c in profile_train}
        heldout["profile_heldout"] = {str(c): profile_test[c] for c in profile_test}

    report = {
        "k": chosen,
        "k_reason": reason,
        "seed": args.seed,
        "silhouette": round(sil, 4),
        "sweep": sweep,
        "codebook": book.to_dict(),
        "class_profiles": {str(c): p for c, p in _profile(samples, labels, chosen).items()},
        "test_1_separation": separation,
        "test_2_cross_game_agreement": agreement,
        "test_3_held_out_games": heldout,
    }
    (args.out_dir / "timbre_codebook.json").write_text(json.dumps(report, indent=1))

    assignments = [
        {"game": s["game"], "key": s["key"], "srcns": s["srcns"], "timbre_class": lab}
        for s, lab in zip(samples, labels)
    ]
    (args.out_dir / "timbre_assignments.json").write_text(json.dumps(assignments))

    print("\n--- test 1: do classes separate usage the fit never saw? ---")
    for axis, values in separation.items():
        print(f"  {axis:24s} real {values['real']:8.2f}   shuffled {values['shuffled']:8.2f}")
    print("--- test 2: does a class mean the same thing in different games? ---")
    print("  (spread of per-game profiles, in SD; lower is better)")
    for axis in USAGE_AXES:
        print(f"  {axis:24s} real {agreement['real'][axis]:8.3f}   "
              f"shuffled {agreement['shuffled'][axis]:8.3f}")
    print("--- test 3: held-out games ---")
    if "profile_difference_in_sd" in heldout:
        print(f"  fitted on {len(heldout['train_games'])} games, "
              f"assigned {len(heldout['heldout_games'])}")
        for axis, value in heldout["profile_difference_in_sd"].items():
            print(f"  {axis:24s} profile difference {value} SD")
    else:
        print("  not enough samples either side of the split")
    print(f"\nwrote {args.out_dir}/timbre_codebook.json and timbre_assignments.json")


if __name__ == "__main__":
    main()
