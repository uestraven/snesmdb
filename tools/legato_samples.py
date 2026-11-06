#!/usr/bin/env python3
"""Does legato concentrate on particular kinds of BRR sample? Within one game.

    legato_samples.py <out-dir> <spc-dir> --game "Plok!" [--permutations 20000]

SAMPLES ARE IDENTIFIED BY CONTENT, NOT BY SRCN. Each SPC is its own ARAM
snapshot and drivers reload their bank per track, so an SRCN index does not
name a fixed instrument: Super Turrican's 8 indices resolve to 48 distinct
samples across 12 tracks, with `srcn 0` alone being 9 different samples, and
Final Fantasy VI's 11 indices resolve to 60. Only Plok! turned out to share one
bank corpus-wide (31 indices, 31 samples). Aggregating by index would therefore
average unrelated instruments together. Identity here is the SHA-256 of the
decoded BRR block, which is what `timbre_features.py` already uses.

WITHIN ONE GAME, deliberately. The milestone 5 timbre codebook failed its own
cross-game validation once the leaking features were removed -- class agreement
across games fell to the null -- so any cross-game claim about sample character
is building on a result already known not to generalise. A driver and its
instrument library are a matched pair, and that is the only scope the evidence
supports.

WHAT IS TESTED. A legato step always inherits its parent note's sample: zero
mid-voice SRCN changes occur anywhere in this corpus, measured across 12 tracks
and seven drivers. So "which sample does a step use" is already answered, and
the open question is whether steps CONCENTRATE on samples with some property.
Per sample, the rate is `steps / notes`; the statistic is the difference in
note-weighted rate between the two groups a property defines.

THE NULL. Permuting notes would be wrong -- it would destroy the sample-size
distribution, which is heavily skewed (one sample can hold a fifth of a game's
steps). So the property LABEL is permuted across samples while each sample's
`(notes, steps)` pair is held fixed. That tests exactly the association in
question and nothing else.

THE CONFOUND, which matters more than the test. One-shot versus looping is
tied to instrument type, and instrument type is tied to whether a part is
melodic at all: percussion is one-shot and would never be played legato, pads
are looped and would. A positive result could therefore mean no more than
"legato happens on melodic instruments", which is close to a tautology. So the
test runs twice -- over all samples, and over PITCHED samples only, which
removes the percussion arm. Only the second is interpretable.

n IS SMALL. The best-equipped game in this corpus has 21 distinct parent
samples. This can detect a strong monotone effect and nothing subtler, and four
properties on 21 points invites a false positive, so the p-values are reported
with a Bonferroni-adjusted threshold alongside.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import brr, spcfile  # noqa: E402

DSP_RATE = 32000.0


def _spectral_centroid(samples: list[int]) -> float | None:
    """Centre of mass of the magnitude spectrum, in Hz.

    A plain DFT over the first power-of-two window; the sample sets here are
    small enough that an FFT dependency would not pay for itself.
    """
    data = samples[:512]
    if len(data) < 64:
        return None
    size = 1 << (len(data).bit_length() - 1)
    data = data[:size]
    mean = sum(data) / size
    windowed = [
        (value - mean) * (0.5 - 0.5 * math.cos(2 * math.pi * i / (size - 1)))
        for i, value in enumerate(data)
    ]
    weighted = total = 0.0
    for bin_index in range(1, size // 2):
        angle = -2 * math.pi * bin_index / size
        real = sum(v * math.cos(angle * n) for n, v in enumerate(windowed))
        imag = sum(v * math.sin(angle * n) for n, v in enumerate(windowed))
        magnitude = math.hypot(real, imag)
        weighted += magnitude * (bin_index * DSP_RATE / size)
        total += magnitude
    return (weighted / total) if total else None


def gather(
    out_dir: Path, spc_dir: Path, game: str
) -> dict[str, dict[str, Any]]:
    """Per distinct SAMPLE (by decoded content), its notes, steps and shape.

    ARAM is read per track, because that is the only scope in which an SRCN
    index means anything.
    """
    index = {Path(p).name: p for p in glob.glob(str(spc_dir / "*" / "*.spc"))}
    out: dict[str, dict[str, Any]] = {}

    for line in (out_dir / "manifest.jsonl").open():
        row = json.loads(line)
        if not row.get("ok") or (row.get("tag") or {}).get("game") != game:
            continue
        if not row.get("record_path"):
            continue
        spc_path = index.get(row.get("source", ""))
        if not spc_path:
            continue
        try:
            spc = spcfile.load(Path(spc_path))
        except Exception:
            continue

        record = json.loads((out_dir / row["record_path"]).read_text())
        note_list = record.get("notes") or []
        if not note_list:
            continue

        notes_by_srcn: Counter = Counter()
        steps_by_srcn: Counter = Counter()
        by_id = {}
        for position, note in enumerate(note_list):
            notes_by_srcn[int(note["srcn"])] += 1
            by_id[note.get("note_id", position)] = note
        for step in record.get("legato_steps") or []:
            parent = by_id.get(step["parent_note_id"])
            if parent is not None:
                steps_by_srcn[int(parent["srcn"])] += 1

        entries = brr.read_directory(
            spc.aram, spc.dsp[0x5D], set(notes_by_srcn)
        )
        f0_by_srcn = row.get("samples") or {}
        for srcn, entry in entries.items():
            if not entry.plausible:
                continue
            try:
                decoded = brr.decode(spc.aram, entry.start, entry.loop)
            except (ValueError, IndexError):
                continue
            if not decoded.data:
                continue
            key = hashlib.sha256(repr(decoded.data).encode()).hexdigest()[:16]
            slot = out.setdefault(key, {
                "notes": 0, "steps": 0, "srcns": set(), "tracks": 0,
                "looping": decoded.loop_offset is not None,
                "loop_length": decoded.loop_length,
                "n_samples": len(decoded.data),
                "duration_ms": 1000.0 * len(decoded.data) / DSP_RATE,
                "centroid_hz": _spectral_centroid(decoded.data),
                "pitched": False,
            })
            slot["notes"] += notes_by_srcn[srcn]
            slot["steps"] += steps_by_srcn[srcn]
            slot["srcns"].add(srcn)
            slot["tracks"] += 1
            if (f0_by_srcn.get(str(srcn)) or {}).get("f0_hz"):
                slot["pitched"] = True
    return out


def permutation_test(
    units: list[tuple[int, int, bool]], permutations: int, seed: int = 0
) -> dict[str, Any]:
    """Difference in note-weighted legato rate between the two label groups.

    `units` is `(n_notes, n_steps, label)` per sample. The LABEL is permuted;
    the `(notes, steps)` pairs stay attached to each other, so sample size and
    skew are preserved exactly.
    """
    def difference(labels: list[bool]) -> float | None:
        a_n = a_s = b_n = b_s = 0
        for (n_notes, n_steps, _), label in zip(units, labels):
            if label:
                a_n += n_notes
                a_s += n_steps
            else:
                b_n += n_notes
                b_s += n_steps
        if not a_n or not b_n:
            return None
        return (a_s / a_n) - (b_s / b_n)

    labels = [unit[2] for unit in units]
    observed = difference(labels)
    if observed is None:
        return {"n": len(units), "observed": None}

    rng = random.Random(seed)
    pool = list(labels)
    null: list[float] = []
    for _ in range(permutations):
        rng.shuffle(pool)
        value = difference(pool)
        if value is not None:
            null.append(value)
    extreme = sum(1 for value in null if abs(value) >= abs(observed))
    return {
        "n": len(units),
        "n_true": sum(labels),
        "observed": observed,
        "null_mean": statistics.mean(null) if null else 0.0,
        "null_sd": statistics.pstdev(null) if len(null) > 1 else 0.0,
        "p": (extreme + 1) / (len(null) + 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("spc_dir", type=Path)
    parser.add_argument("--game", required=True)
    parser.add_argument("--permutations", type=int, default=20000)
    parser.add_argument("--min-notes", type=int, default=30)
    args = parser.parse_args()

    samples = gather(args.out_dir, args.spc_dir, args.game)
    if not samples:
        print(f"no samples resolved for {args.game!r}", file=sys.stderr)
        return

    total_steps = sum(s["steps"] for s in samples.values())
    indices = len({i for s in samples.values() for i in s["srcns"]})
    print(f"{args.game}: {len(samples)} distinct samples by content "
          f"({indices} SRCN indices), {total_steps} legato steps\n")

    usable = [k for k, v in samples.items() if v["notes"] >= args.min_notes]
    pitched = [k for k in usable if samples[k]["pitched"]]
    looping = sum(1 for k in usable if samples[k]["looping"])
    print(f"samples with >={args.min_notes} notes: {len(usable)}"
          f"  (pitched {len(pitched)}, looping {looping}, "
          f"one-shot {len(usable) - looping})\n")

    print(f"{'sample':>10s}{'srcn':>8s}{'notes':>8s}{'steps':>7s}{'rate':>8s}"
          f"{'loop':>7s}{'ms':>8s}{'centroid':>10s}{'pitched':>9s}")
    for key in sorted(usable, key=lambda k: -samples[k]["steps"])[:16]:
        v = samples[key]
        centroid = v["centroid_hz"]
        print(f"{key[:8]:>10s}{','.join(str(i) for i in sorted(v['srcns']))[:7]:>8s}"
              f"{v['notes']:8d}{v['steps']:7d}"
              f"{100 * v['steps'] / v['notes']:7.1f}%"
              f"{('loop' if v['looping'] else 'shot'):>7s}"
              f"{v['duration_ms']:8.1f}"
              f"{(f'{centroid:.0f}' if centroid else '-'):>10s}"
              f"{('yes' if v['pitched'] else 'no'):>9s}")

    print("\npermutation tests (label shuffled, sample sizes held fixed)")
    threshold = 0.05 / 3
    for scope, pool in (("all samples", usable), ("pitched only", pitched)):
        if len(pool) < 6:
            print(f"\n  {scope}: n={len(pool)}, too few to test")
            continue
        print(f"\n  {scope} (n={len(pool)})")
        durations = {k: samples[k]["duration_ms"] for k in pool}
        bright = [k for k in pool if samples[k]["centroid_hz"]]
        median_duration = statistics.median(durations.values())
        median_centroid = (
            statistics.median(samples[k]["centroid_hz"] for k in bright)
            if bright else 0.0
        )
        cases = [
            ("looping vs one-shot", pool, lambda k: samples[k]["looping"]),
            ("longer than median", pool, lambda k: durations[k] > median_duration),
        ]
        if len(bright) >= 6:
            cases.append((
                "brighter than median", bright,
                lambda k: samples[k]["centroid_hz"] > median_centroid,
            ))
        for name, subset, label in cases:
            units = [
                (samples[k]["notes"], samples[k]["steps"], bool(label(k)))
                for k in subset
            ]
            result = permutation_test(units, args.permutations)
            if result.get("observed") is None:
                print(f"    {name:24s} all samples on one side, no test")
                continue
            mark = "  *" if result["p"] < threshold else ""
            print(f"    {name:24s} n={result['n']:3d} "
                  f"({result['n_true']} true)  "
                  f"diff {100 * result['observed']:+7.2f}pp  "
                  f"null {100 * result['null_mean']:+5.2f} "
                  f"+/- {100 * result['null_sd']:4.2f}pp  "
                  f"p={result['p']:.4f}{mark}")
    print(f"\n  * significant at Bonferroni-adjusted {threshold:.4f} "
          f"(0.05 over 3 tests)")
    print("\n  Read 'pitched only'. The all-samples row carries the percussion\n"
          "  confound: one-shot tracks instrument type, which tracks whether a\n"
          "  part is melodic at all.", file=sys.stderr)


if __name__ == "__main__":
    main()
