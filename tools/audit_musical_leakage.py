#!/usr/bin/env python3
"""Does the same musical material appear in more than one split?

    audit_musical_leakage.py <dist-dir> <report.json>
                             [--min-run 32] [--seed-length 16]

Read-only, published artifacts only. No audio is read or produced.

Game-disjointness does not give composition-disjointness. The same theme can
appear in two different games -- a sequel, a port, a shared sound team, a
licensed arrangement -- and a model would then be evaluated on material it
trained on while every structural check reports a clean partition.

This is a SEARCH, not a proof. Three things bound it, and they are reported
rather than buried:

    it reads SYMBOLIC data        a passage whose pitches were never
                                  recovered is invisible here
    recovery differs by cohort    the 22-game cohort's pitch came from the
                                  capture-time directory and the expansion's
                                  from the sample used at key-on, so the two
                                  halves are not equally observable
    it matches SEQUENCES          a re-orchestrated or re-harmonised quote
                                  need not share a note sequence at all

So a negative result says "no match within this method's coverage", never
"no shared composition".

Sequences are built PER VOICE rather than from the interleaved attack
stream. Eight voices mixed together produce an order that depends on
arrangement rather than melody, and two performances of the same tune would
not share it.

Three representations, increasingly permissive:

    exact pitch       the same notes, same transposition
    interval          transposition-invariant: the same tune in any key
    interval + rhythm interval plus a coarse bucket of the inter-onset
                      ratio, so a match must agree on shape AND timing

A hit is extended to its maximal run before being judged, and judged on RUN
LENGTH and on what fraction of each track it covers. A 32-note agreement is
not a scale; a 32-note agreement covering most of two tracks is the same
piece.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path

EXPANSION_GAMES = {
    "Secret of Evermore", "F-Zero", "Ken Griffey Jr. Baseball",
    "Street Fighter 2 Turbo", "Tetris 2",
}


def ratio_bucket(previous: float, current: float) -> int:
    """A coarse class for an inter-onset ratio.

    Coarse on purpose: performed timing in a sequenced driver is not exact,
    and a fine bucket would make two renderings of one phrase look
    different. Powers of two with a tolerance band, which is what a tracker
    actually produces.
    """
    if previous <= 0 or current <= 0:
        return 0
    r = current / previous
    for index, edge in enumerate((0.3, 0.6, 0.85, 1.2, 1.7, 3.0)):
        if r < edge:
            return index + 1
    return 7


def sequences(events: list[dict]) -> dict[int, list[tuple[int, float]]]:
    """Per voice: pitched attacks in onset order as (note, onset)."""
    by_voice: dict[int, list[tuple[int, float]]] = collections.defaultdict(list)
    for event in events:
        if event["origin"] != "key_on":
            continue
        if event["pitch_status"] != "estimated":
            continue
        note = event.get("midi_note")
        if note is None:
            continue
        by_voice[int(event["voice"])].append(
            (int(round(float(note))), float(event["onset_sec"])))
    for voice in by_voice:
        by_voice[voice].sort(key=lambda p: p[1])
    return by_voice


def tokens(seq: list[tuple[int, float]], kind: str) -> list:
    """One token per adjacent pair, in the chosen representation."""
    out = []
    for i in range(1, len(seq)):
        (pa, ta), (pb, tb) = seq[i - 1], seq[i]
        interval = pb - pa
        if kind == "exact_pitch":
            out.append(pb)
        elif kind == "interval":
            out.append(interval)
        else:
            prev = ta - seq[i - 2][1] if i >= 2 else 0.0
            out.append((interval, ratio_bucket(prev, tb - ta)))
    return out


def melodic_intervals(run: list, kind: str) -> list[int]:
    """The run's pitch intervals, in whichever representation it is.

    REPRESENTATION-AWARE on purpose. `exact_pitch` tokens are absolute
    pitches, not intervals, and reading them as intervals made a chromatic
    scale look like 48 distinct intervals instead of 2 -- so a scale shared
    by two games was reported as a complete duplicate.
    """
    if kind == "exact_pitch":
        return [run[i] - run[i - 1] for i in range(1, len(run))]
    if kind == "interval":
        return list(run)
    return [t[0] for t in run]


def run_diagnostics(run: list, kind: str) -> dict:
    """Is this run musical material, or a repeated figure?

    The first version of this search returned 852 cross-split "matches"
    dominated by one voice with 1,053 attacks on a SINGLE pitch -- its
    interval sequence is 1,053 zeros. A seed filter counting distinct
    TOKENS let it through, because a constant pitch with varying rhythm
    still produces several distinct (0, bucket) tokens.

    So a candidate is measured on melodic content and on periodicity:

        distinct_nonzero_intervals  a scale, a drum ostinato and a trill all
                                    have very few
        shortest_period             a figure repeating every few notes is a
                                    loop, not a theme
    """
    intervals = melodic_intervals(run, kind)
    nonzero = {i for i in intervals if i != 0}
    period = len(run)
    for candidate in range(1, min(16, len(run)) + 1):
        if all(run[i] == run[i % candidate] for i in range(len(run))):
            period = candidate
            break
    return {
        "distinct_tokens": len(set(run)),
        "distinct_nonzero_intervals": len(nonzero),
        "shortest_period": period,
        "zero_interval_share": round(
            sum(1 for i in intervals if i == 0) / len(intervals), 3)
        if intervals else 1.0,
    }


#: A candidate must clear both. Melodic variety rules out scales, trills and
#: single-pitch percussion; the period floor rules out loops.
MIN_DISTINCT_NONZERO_INTERVALS = 5
MIN_PERIOD = 8


def extend(a: list, ai: int, b: list, bi: int, length: int) -> tuple[int, int]:
    """Grow a seed match to its maximal run. Returns (start_in_a, length)."""
    start_a, start_b = ai, bi
    while start_a > 0 and start_b > 0 and a[start_a - 1] == b[start_b - 1]:
        start_a -= 1
        start_b -= 1
    end_a, end_b = ai + length, bi + length
    while end_a < len(a) and end_b < len(b) and a[end_a] == b[end_b]:
        end_a += 1
        end_b += 1
    return start_a, end_a - start_a


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist", type=Path)
    ap.add_argument("report", type=Path)
    ap.add_argument("--seed-length", type=int, default=16)
    ap.add_argument("--min-run", type=int, default=32)
    args = ap.parse_args()

    index = json.loads((args.dist / "index.json").read_text())
    meta: dict[str, dict] = {}
    series: dict[str, dict[str, dict[int, list]]] = {}

    for entry in index["tracks"]:
        table = json.loads(gzip.decompress(
            (args.dist / entry["events"]).read_bytes()))
        voices = sequences(table["events"])
        meta[entry["track_id"]] = {
            "split": entry.get("split"), "game": entry.get("game"),
            "title": entry.get("title"),
            "cohort": ("expansion" if entry.get("game") in EXPANSION_GAMES
                       else "baseline"),
            "pitched_attacks": sum(len(v) for v in voices.values()),
        }
        series[entry["track_id"]] = {
            kind: {v: tokens(seq, kind) for v, seq in voices.items()}
            for kind in ("exact_pitch", "interval", "interval_rhythm")
        }

    findings: list[dict] = []
    stats: collections.Counter = collections.Counter()

    for kind in ("exact_pitch", "interval", "interval_rhythm"):
        # Seed index: hash of a short window -> where it occurs.
        seeds: dict[tuple, list[tuple[str, int, int]]] = (
            collections.defaultdict(list))
        for tid, kinds in series.items():
            for voice, toks in kinds[kind].items():
                for i in range(0, len(toks) - args.seed_length + 1):
                    window = tuple(toks[i:i + args.seed_length])
                    # Melodic variety, not token variety. Token variety let
                    # a 1,053-note single-pitch voice through.
                    nz = set(melodic_intervals(list(window), kind)) - {0}
                    if len(nz) < 3:
                        continue
                    seeds[window].append((tid, voice, i))

        seen_pairs: set[tuple] = set()
        for window, hits in seeds.items():
            if len(hits) < 2:
                continue
            for x in range(len(hits)):
                for y in range(x + 1, len(hits)):
                    ta, va, ia = hits[x]
                    tb, vb, ib = hits[y]
                    if meta[ta]["split"] == meta[tb]["split"]:
                        continue
                    if meta[ta]["game"] == meta[tb]["game"]:
                        continue       # same game cannot cross splits
                    key = (kind, ta, va, tb, vb)
                    if key in seen_pairs:
                        continue
                    a = series[ta][kind][va]
                    b = series[tb][kind][vb]
                    start, run = extend(a, ia, b, ib, args.seed_length)
                    # `min_run` guards against a motif embedded in a long
                    # track. It is the WRONG gate for a short track matched
                    # end to end: the Capcom logo fanfare is 24 notes long
                    # and appears complete in both Mega Man X (train) and
                    # Street Fighter II Turbo (valid), so a 32-token floor
                    # hid a real duplicate. Coverage decides that case.
                    cov_a_pre = run / len(a) if a else 0.0
                    cov_b_pre = run / len(b) if b else 0.0
                    complete = min(cov_a_pre, cov_b_pre) >= 0.8
                    if run < args.min_run and not complete:
                        stats[f"{kind}:below_min_run"] += 1
                        continue
                    diag = run_diagnostics(a[start:start + run], kind)
                    if diag["distinct_nonzero_intervals"] < \
                            MIN_DISTINCT_NONZERO_INTERVALS:
                        stats[f"{kind}:rejected_too_few_intervals"] += 1
                        continue
                    if diag["shortest_period"] < MIN_PERIOD:
                        stats[f"{kind}:rejected_periodic_figure"] += 1
                        continue
                    seen_pairs.add(key)
                    cov_a = run / len(a) if a else 0.0
                    cov_b = run / len(b) if b else 0.0
                    strength = (
                        "complete_duplicate"
                        if min(cov_a, cov_b) >= 0.8 else
                        "substantial_passage"
                        if run >= 64 or min(cov_a, cov_b) >= 0.3 else
                        "short_shared_motif")
                    stats[f"{kind}:{strength}"] += 1
                    findings.append({
                        "method": kind,
                        "run_tokens": run,
                        "evidence_strength": strength,
                        "diagnostics": diag,
                        "a": {"track_id": ta, "voice": va,
                              "game": meta[ta]["game"],
                              "title": meta[ta]["title"],
                              "split": meta[ta]["split"],
                              "cohort": meta[ta]["cohort"],
                              "coverage_of_voice": round(cov_a, 4),
                              "voice_tokens": len(a)},
                        "b": {"track_id": tb, "voice": vb,
                              "game": meta[tb]["game"],
                              "title": meta[tb]["title"],
                              "split": meta[tb]["split"],
                              "cohort": meta[tb]["cohort"],
                              "coverage_of_voice": round(cov_b, 4),
                              "voice_tokens": len(b)},
                    })

    # A voice matching many unrelated tracks is producing conventional
    # material. Recorded per finding so a reader can discount it rather
    # than having it silently dropped.
    partners: dict[tuple, set] = collections.defaultdict(set)
    for f in findings:
        partners[(f["a"]["track_id"], f["a"]["voice"])].add(
            f["b"]["track_id"])
        partners[(f["b"]["track_id"], f["b"]["voice"])].add(
            f["a"]["track_id"])
    for f in findings:
        pa = len(partners[(f["a"]["track_id"], f["a"]["voice"])])
        pb = len(partners[(f["b"]["track_id"], f["b"]["voice"])])
        f["partner_tracks_max"] = max(pa, pb)
        if f["partner_tracks_max"] > 3 and \
                f["evidence_strength"] != "complete_duplicate":
            f["evidence_strength"] = "conventional_material_suspected"

    findings.sort(key=lambda f: -f["run_tokens"])
    by_strength = collections.Counter(f["evidence_strength"] for f in findings)

    out = {
        "schema": "snesmdb.musical_leakage.v1",
        "dist": str(args.dist),
        "seed_length": args.seed_length,
        "min_run": args.min_run,
        "tracks_searched": len(meta),
        "cross_split_matches": len(findings),
        "by_evidence_strength": dict(by_strength),
        "counts": dict(stats),
        "findings": findings[:200],
        "coverage_limits": [
            "Symbolic only: a passage whose pitches were never recovered "
            "cannot match. 21.29% of attacks carry no fixed-pitch estimate.",
            "Pitch recovery differs between the two cohorts, so the halves "
            "are not equally observable and a cross-cohort match is less "
            "likely to be found than a within-cohort one.",
            "Sequence matching only: a re-orchestrated, re-harmonised or "
            "re-voiced quotation need not share a note sequence.",
            "Per voice: material split across voices in one arrangement and "
            "merged in another will not match.",
            "A NEGATIVE RESULT BOUNDS THIS METHOD'S COVERAGE AND DOES NOT "
            "ESTABLISH THAT NO SHARED COMPOSITION EXISTS.",
        ],
    }
    args.report.write_text(json.dumps(out, indent=1))

    print(f"{len(meta):,} tracks searched, seed {args.seed_length}, "
          f"min run {args.min_run}")
    print(f"cross-split matches: {len(findings)}")
    print(f"by evidence strength: {dict(by_strength)}\n")
    for f in findings[:15]:
        a, b = f["a"], f["b"]
        print(f"  {f['evidence_strength']:20} {f['method']:16} "
              f"run {f['run_tokens']:4}")
        print(f"      {a['split']:5} {a['game'][:22]:24} "
              f"{str(a['title'])[:20]:22} v{a['voice']} "
              f"cov {a['coverage_of_voice']:.2f}")
        print(f"      {b['split']:5} {b['game'][:22]:24} "
              f"{str(b['title'])[:20]:22} v{b['voice']} "
              f"cov {b['coverage_of_voice']:.2f}")
    if not findings:
        print("  none found -- which bounds this method, not the question")


if __name__ == "__main__":
    main()
