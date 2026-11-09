#!/usr/bin/env python3
"""Can a smoothed n-gram predict melodic movement in an unseen SNES game?

    baseline_interval_ngram.py <dist-dir> <report.json>

Read-only, published artifacts only. Deterministic: no sampling, no RNG, no
parallelism, so two runs over one release give identical numbers.

THE QUESTION. Given the preceding intervals of a voice, predict the next
melodic interval. The control is a frequency-only model that ignores context
entirely. If local context carries predictive information about held-out
games, the n-gram beats it; if not, it does not. Both are findings.

WHAT A MELODY IS HERE, decided before any model was fitted and applied
identically to every split:

    voice-local     sequences are built per (track, voice). A global
                    time-sorted stream would put adjacent events in
                    different voices or inside one chord, so its
                    "intervals" would be an artefact of arrangement.
    key-on only     a pitched key-on contributes a note. Legato steps do
                    NOT: a step is a pitch change inside a sounding note,
                    its pitch is derived from a register ratio rather than
                    re-keyed, and mixing two event kinds with different
                    provenance into one sequence would make the learning
                    population impossible to state. Their count is reported
                    as excluded rather than quietly dropped.
    estimated only  an attack with no fixed-pitch estimate has no interval.
                    21.29% of corpus attacks are in that position.
    no gap splitting
                    consecutive attacks on a voice form an interval however
                    far apart they are. Splitting on a silence threshold
                    would be a tunable choice dressed as a definition; the
                    cost is that two phrases either side of a rest are
                    joined, and that is a stated limitation.

SCOPE OF ANY CONCLUSION. Held-out-GAME symbolic interval prediction. Not
composer generalisation -- 287 tracks carry an incomplete credit and one
possible authorship overlap covering 206 tracks is unresolved. Not musical
quality, and not full-song generation.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import exclusions as exclusions_mod  # noqa: E402

SPLITS = ("train", "valid", "test")

EXPANSION_GAMES = {
    "Secret of Evermore", "F-Zero", "Ken Griffey Jr. Baseball",
    "Street Fighter 2 Turbo", "Tetris 2",
}

#: Intervals outside two octaves collapse into one bucket per direction.
#: A closed vocabulary is needed for a likelihood, and an interval beyond
#: two octaves is a voice reassignment or an octave error far more often
#: than a melodic step.
CLIP = 24
BIG_UP, BIG_DOWN = CLIP + 1, -(CLIP + 1)
VOCAB = tuple(range(BIG_DOWN, BIG_UP + 1))

#: The search grid, fixed here before any evaluation. Selection happens on
#: validation and the chosen setting is recorded before test is touched.
ORDERS = (1, 2, 3)
ALPHAS = (0.01, 0.1, 1.0)


def clip(interval: int) -> int:
    if interval > CLIP:
        return BIG_UP
    if interval < -CLIP:
        return BIG_DOWN
    return interval


def sequences_for(table: dict) -> list[list[int]]:
    """Interval sequences, one per voice, for one track."""
    by_voice: dict[int, list[tuple[float, int]]] = collections.defaultdict(list)
    for event in table["events"]:
        if event["origin"] != "key_on":
            continue
        if event["pitch_status"] != "estimated":
            continue
        note = event.get("midi_note")
        if note is None:
            continue
        by_voice[int(event["voice"])].append(
            (float(event["onset_sec"]), int(round(float(note)))))
    out = []
    for voice in sorted(by_voice):
        notes = [n for _, n in sorted(by_voice[voice], key=lambda p: p[0])]
        if len(notes) < 2:
            continue
        out.append([clip(notes[i] - notes[i - 1])
                    for i in range(1, len(notes))])
    return out


class Ngram:
    """Add-alpha smoothed interval n-gram with backoff to the unigram.

    `order` is the number of preceding intervals used as context. Order 1
    conditions on one interval; the control conditions on nothing.
    """

    def __init__(self, order: int, alpha: float):
        self.order = order
        self.alpha = alpha
        self.counts: dict[tuple, collections.Counter] = (
            collections.defaultdict(collections.Counter))
        self.unigram: collections.Counter = collections.Counter()

    def fit(self, sequences: list[list[int]]) -> None:
        for seq in sequences:
            for i, value in enumerate(seq):
                self.unigram[value] += 1
                for k in range(1, self.order + 1):
                    if i - k < 0:
                        break
                    self.counts[tuple(seq[i - k:i])][value] += 1

    def _dist(self, context: tuple) -> collections.Counter:
        # Longest available context, backing off until one is seen.
        for k in range(len(context), 0, -1):
            tail = context[len(context) - k:]
            if tail in self.counts:
                return self.counts[tail]
        return self.unigram

    def predict(self, context: tuple) -> tuple[int, dict[int, float]]:
        counts = self._dist(context)
        total = sum(counts.values()) + self.alpha * len(VOCAB)
        probs = {v: (counts.get(v, 0) + self.alpha) / total for v in VOCAB}
        best = max(VOCAB, key=lambda v: (probs[v], -abs(v)))
        return best, probs


class Frequency:
    """The control: the training interval distribution, context ignored."""

    def __init__(self, alpha: float = 0.1):
        self.alpha = alpha
        self.counts: collections.Counter = collections.Counter()

    def fit(self, sequences: list[list[int]]) -> None:
        for seq in sequences:
            self.counts.update(seq)

    def predict(self, context: tuple) -> tuple[int, dict[int, float]]:
        total = sum(self.counts.values()) + self.alpha * len(VOCAB)
        probs = {v: (self.counts.get(v, 0) + self.alpha) / total
                 for v in VOCAB}
        best = max(VOCAB, key=lambda v: (probs[v], -abs(v)))
        return best, probs


def score(model, tracks: list[dict]) -> dict:
    """Micro and per-track metrics. NLL is in bits per interval."""
    hits = total = 0
    bits = 0.0
    per_track = []
    for track in tracks:
        t_hits = t_total = 0
        t_bits = 0.0
        for seq in track["sequences"]:
            for i, truth in enumerate(seq):
                order = getattr(model, "order", 0)
                context = tuple(seq[max(0, i - order):i]) if order else ()
                best, probs = model.predict(context)
                t_total += 1
                if best == truth:
                    t_hits += 1
                t_bits += -math.log2(max(probs[truth], 1e-12))
        if not t_total:
            continue
        hits += t_hits
        total += t_total
        bits += t_bits
        per_track.append({
            "track_id": track["track_id"], "game": track["game"],
            "cohort": track["cohort"], "intervals": t_total,
            "accuracy": t_hits / t_total, "nll_bits": t_bits / t_total,
        })
    if not total:
        return {}
    return {
        "intervals": total,
        "micro_accuracy": round(hits / total, 6),
        "micro_nll_bits": round(bits / total, 6),
        "macro_accuracy_per_track": round(
            sum(t["accuracy"] for t in per_track) / len(per_track), 6),
        "macro_nll_bits_per_track": round(
            sum(t["nll_bits"] for t in per_track) / len(per_track), 6),
        "tracks": len(per_track),
        "per_track": per_track,
    }


def group(per_track: list[dict], key: str) -> dict:
    out: dict[str, dict] = {}
    buckets: dict[str, list[dict]] = collections.defaultdict(list)
    for row in per_track:
        buckets[str(row[key])].append(row)
    for name, rows in sorted(buckets.items()):
        n = sum(r["intervals"] for r in rows)
        out[name] = {
            "tracks": len(rows), "intervals": n,
            "micro_accuracy": round(
                sum(r["accuracy"] * r["intervals"] for r in rows) / n, 6),
            "micro_nll_bits": round(
                sum(r["nll_bits"] * r["intervals"] for r in rows) / n, 6),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist", type=Path)
    ap.add_argument("report", type=Path)
    args = ap.parse_args()

    index = json.loads((args.dist / "index.json").read_text())
    release = None
    release_path = args.dist / "RELEASE.json"
    if release_path.is_file():
        release = json.loads(release_path.read_text()).get("label")

    # POPULATION. Music-class only, then the conditional exclusion policy
    # applied to the membership that actually results.
    population: dict[str, list[dict]] = {s: [] for s in SPLITS}
    census = collections.Counter()
    for entry in index["tracks"]:
        split = entry.get("split")
        if split not in population:
            continue
        census["tracks_total"] += 1
        if entry.get("track_class") != "music":
            census["dropped_not_music_class"] += 1
            continue
        table = json.loads(gzip.decompress(
            (args.dist / entry["events"]).read_bytes()))
        census["legato_steps_excluded_by_definition"] += sum(
            1 for e in table["events"] if e["origin"] != "key_on")
        census["attacks_without_a_pitch_estimate"] += sum(
            1 for e in table["events"]
            if e["origin"] == "key_on" and e["pitch_status"] != "estimated")
        seqs = sequences_for(table)
        if not seqs:
            census["dropped_no_usable_sequence"] += 1
            continue
        population[split].append({
            "track_id": entry["track_id"], "game": entry.get("game"),
            "cohort": ("expansion" if entry.get("game") in EXPANSION_GAMES
                       else "baseline"),
            "sequences": seqs,
        })
        census["tracks_eligible"] += 1
        census["voices"] += len(seqs)
        census["intervals"] += sum(len(s) for s in seqs)

    record = exclusions_mod.load()
    training_ids = [t["track_id"] for t in population["train"]]
    to_exclude = record.excluded(training_ids)
    applied = record.report(training_ids)
    removed = collections.Counter()
    for split in ("valid", "test"):
        before = len(population[split])
        population[split] = [t for t in population[split]
                             if t["track_id"] not in to_exclude]
        removed[split] = before - len(population[split])

    # SELECTION on validation only.
    train_seqs = [s for t in population["train"] for s in t["sequences"]]
    control = Frequency()
    control.fit(train_seqs)

    selection = []
    best_setting = None
    for order in ORDERS:
        for alpha in ALPHAS:
            model = Ngram(order, alpha)
            model.fit(train_seqs)
            got = score(model, population["valid"])
            selection.append({"order": order, "alpha": alpha,
                              "valid_accuracy": got["micro_accuracy"],
                              "valid_nll_bits": got["micro_nll_bits"]})
            key = (got["micro_nll_bits"], order, alpha)
            if best_setting is None or key < best_setting[0]:
                best_setting = (key, order, alpha)
    _, order, alpha = best_setting
    at_edge = []
    if order == max(ORDERS):
        at_edge.append(f"order={order} is the grid maximum")
    if alpha == max(ALPHAS):
        at_edge.append(f"alpha={alpha} is the grid maximum")
    chosen = {
        "order": order, "alpha": alpha,
        "criterion": "lowest validation NLL in bits",
        "selected_at_grid_boundary": at_edge,
        "boundary_note": (
            "Validation selected a setting at the edge of the pre-declared "
            "grid. These results describe the selected configuration under "
            "that grid; THE EFFECT OF A BROADER SEARCH IS UNMEASURED. A "
            "boundary selection suggests a wider search would be "
            "informative, but it does not establish that wider tuning would "
            "improve held-out performance -- it could equally overfit "
            "validation. The grid is NOT being widened now: selection would "
            "be clean, but test has already been evaluated once and "
            "re-running it after seeing the result is how a held-out set "
            "stops being held out."
            if at_edge else
            "The selected setting is interior to the grid."),
    }

    # FINAL EVALUATION, once, after selection is fixed.
    final = Ngram(order, alpha)
    final.fit(train_seqs)
    test_ngram = score(final, population["test"])
    test_control = score(control, population["test"])
    valid_ngram = score(final, population["valid"])
    valid_control = score(control, population["valid"])

    delta_acc = test_ngram["micro_accuracy"] - test_control["micro_accuracy"]
    delta_nll = test_control["micro_nll_bits"] - test_ngram["micro_nll_bits"]
    if delta_nll > 0.01 and delta_acc > 0.001:
        outcome = ("N-GRAM OUTPERFORMS THE FREQUENCY BASELINE: local melodic "
                   "context carries predictive information on held-out "
                   "games.")
    elif abs(delta_nll) <= 0.01:
        outcome = ("MODELS PERFORM SIMILARLY: the tested context model adds "
                   "little predictive value under this protocol.")
    else:
        outcome = ("N-GRAM UNDERPERFORMS: consistent with distribution "
                   "shift, context sparsity, or insufficient "
                   "generalisation.")

    out = {
        "schema": "snesmdb.interval_baseline.v1",
        "release": release,
        "dist": str(args.dist),
        "research_question": (
            "Can a smoothed interval n-gram predict the next melodic "
            "interval in an unseen SNES game better than a frequency-only "
            "baseline?"),
        "outcome": outcome,
        "melody_definition": {
            "scope": "per (track, voice)",
            "events_used": "key_on with pitch_status == 'estimated'",
            "legato_steps": "excluded by definition, not dropped silently",
            "gap_splitting": "none",
            "interval_clip": CLIP,
            "vocabulary_size": len(VOCAB),
        },
        "population": dict(census),
        "tracks_per_split": {s: len(population[s]) for s in SPLITS},
        "exclusion_policy": {
            "applied": applied,
            "tracks_removed": dict(removed),
            "note": (
                "The confirmed cross-split duplicate is jingle-class "
                "material. Music-class filtering removes its training "
                "copies, so the conditional exclusion does NOT fire for "
                "this population. Reported as not-applied rather than "
                "claimed as a leakage correction."
                if not applied else
                "The conditional exclusion fired; see `applied`."),
        },
        "selection": {
            "grid": {"orders": list(ORDERS), "alphas": list(ALPHAS)},
            "validation_results": selection,
            "chosen": chosen,
        },
        "validation": {
            "ngram": {k: v for k, v in valid_ngram.items()
                      if k != "per_track"},
            "frequency": {k: v for k, v in valid_control.items()
                          if k != "per_track"},
        },
        "test": {
            "ngram": {k: v for k, v in test_ngram.items()
                      if k != "per_track"},
            "frequency": {k: v for k, v in test_control.items()
                          if k != "per_track"},
            "delta_accuracy": round(delta_acc, 6),
            "delta_nll_bits_improvement": round(delta_nll, 6),
            "by_game": {
                "ngram": group(test_ngram["per_track"], "game"),
                "frequency": group(test_control["per_track"], "game"),
            },
            "by_cohort": {
                "ngram": group(test_ngram["per_track"], "cohort"),
                "frequency": group(test_control["per_track"], "cohort"),
            },
            "per_track_ngram": test_ngram["per_track"],
        },
        "limitations": [
            "Held-out-GAME evaluation. Composer generalisation is NOT "
            "established: 287 of 1,477 tracks carry an incomplete credit, "
            "and one possible authorship overlap covering 206 tracks is "
            "unresolved.",
            "Splits are not interchangeable samples. Pitched share is "
            "77.49% / 81.75% / 85.48% across train/valid/test, validation "
            "is 43% expansion-cohort against train's 6.8%, and test median "
            "max polyphony is 6 against 8. These are reported as measured "
            "and were NOT normalised away.",
            "Sample identities barely overlap between splits, so nothing "
            "here conditions on timbre and `sample_id` is unusable as a "
            "categorical feature across splits.",
            "Legato steps are excluded, so pitch movement inside a "
            "sounding note is outside the task.",
            "No gap splitting: two phrases either side of a rest are "
            "joined into one sequence.",
            "Says nothing about musical quality or full-song generation.",
            "The selected n-gram order and smoothing sat at the edge of the "
            "pre-declared search grid. These figures describe the selected "
            "configuration under that grid; the effect of a broader search "
            "is unmeasured.",
        ],
    }
    args.report.write_text(json.dumps(out, indent=1))

    print(f"release {release}   vocabulary {len(VOCAB)}")
    print(f"population: {census['tracks_eligible']:,} music tracks, "
          f"{census['voices']:,} voices, {census['intervals']:,} intervals")
    print(f"  dropped non-music {census['dropped_not_music_class']:,}, "
          f"no usable sequence {census['dropped_no_usable_sequence']:,}")
    print(f"  excluded by definition: "
          f"{census['legato_steps_excluded_by_definition']:,} legato steps, "
          f"{census['attacks_without_a_pitch_estimate']:,} attacks with no "
          f"pitch")
    print(f"tracks per split: "
          f"{ {s: len(population[s]) for s in SPLITS} }")
    print(f"exclusion policy applied: {applied if applied else 'NOT APPLIED'}"
          f"  removed {dict(removed)}")
    print(f"\nselected on validation: order={order} alpha={alpha}")
    if at_edge:
        print(f"  WARNING: {', '.join(at_edge)} -- optimum may lie outside "
              f"the declared grid; not widened after seeing test")
    print(f"{'':12}{'accuracy':>12}{'NLL bits':>12}")
    for name, got in (("valid ngram", valid_ngram),
                      ("valid freq", valid_control),
                      ("TEST ngram", test_ngram),
                      ("TEST freq", test_control)):
        print(f"{name:12}{got['micro_accuracy']:>12.4f}"
              f"{got['micro_nll_bits']:>12.4f}")
    print(f"\ntest delta: accuracy {delta_acc:+.4f}, "
          f"NLL improvement {delta_nll:+.4f} bits")
    print(f"\n{outcome}")
    print("\nper game (test, n-gram vs frequency):")
    for game, g in out["test"]["by_game"]["ngram"].items():
        f = out["test"]["by_game"]["frequency"][game]
        print(f"  {game[:28]:30} n={g['intervals']:>7,}  "
              f"acc {g['micro_accuracy']:.4f} vs {f['micro_accuracy']:.4f}  "
              f"nll {g['micro_nll_bits']:.4f} vs {f['micro_nll_bits']:.4f}")
    print("\nper cohort (test, n-gram):")
    for cohort, g in out["test"]["by_cohort"]["ngram"].items():
        print(f"  {cohort:12} tracks {g['tracks']:4} n={g['intervals']:>8,}  "
              f"acc {g['micro_accuracy']:.4f}  nll {g['micro_nll_bits']:.4f}")


if __name__ == "__main__":
    main()
