#!/usr/bin/env python3
"""Compare grid-inference objectives against already-extracted records.

    grid_sweep.py <out-dir> [--games "Final Fantasy 6,Donkey Kong Country"]

Development tool, not part of the pipeline. The point is that grid inference
reads only note onsets, which are already in `records/*.json`, so an objective
can be changed and re-measured over the whole corpus in seconds without
re-emulating a single SPC. Re-running `extract.py` to try a tolerance is the
slow way to learn nothing.

What it measures, per objective:

  found%      tracks that get a grid at all
  rows/s      median, and the SPREAD across games is the diagnostic -- a
              method that reports 5 rows/s for one driver and 80 for another
              is reporting the music's phrasing in one case and the driver's
              tick in the other
  snapped%    notes shorter than one row, whose onset the grid MOVED. This is
              the number that matters for score quality and the one the first
              objective was blind to.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import grid as G  # noqa: E402

TICKS = G.TICKS_PER_SECOND


def _percentile(values, q):
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))
    return ordered[index]


def _best(distinct, span, *, tol_rel, tol_abs, margin, max_period):
    """Score every candidate under one objective and pick a winner."""
    candidates = [p for p in G._candidates(distinct, span) if p <= max_period]
    if not candidates:
        return None
    scored = []
    for period in candidates:
        phase = G._phase_for(distinct, period)
        residuals = G._residuals(distinct, period, phase)
        limit = min(tol_rel * period, tol_abs) if tol_abs else tol_rel * period
        fit = sum(1 for r in residuals if abs(r) <= limit) / len(residuals)
        scored.append((period, fit, phase, residuals))
    best_fit = max(item[1] for item in scored)
    eligible = [item for item in scored if item[1] >= best_fit - margin]
    return max(eligible, key=lambda item: item[0])


def evaluate(records, objective):
    """Apply one objective to every record; return per-game aggregates."""
    name, kwargs = objective
    out = {}
    for game, tracks in records.items():
        found = []
        snapped_rates = []
        for onsets, durations, span in tracks:
            distinct = sorted(set(onsets))
            if len(distinct) < G.MIN_DISTINCT_ONSETS:
                continue
            result = None
            for window in G.CLUSTER_WINDOWS_TICKS:
                clustered = G.cluster(distinct, window)
                if len(clustered) < G.MIN_DISTINCT_ONSETS:
                    break
                cap = kwargs["max_period"]
                if callable(cap):
                    cap = cap(clustered, durations)
                attempt = _best(
                    clustered, span,
                    tol_rel=kwargs["tol_rel"], tol_abs=kwargs["tol_abs"],
                    margin=kwargs["margin"], max_period=cap,
                )
                if attempt is None:
                    continue
                if result is None or attempt[1] > result[1]:
                    result = attempt
                if attempt[1] >= G.MIN_FIT:
                    result = attempt
                    break
            if result is None or result[1] < G.MIN_FIT:
                continue
            period = result[0]
            found.append((TICKS / period, result[1]))
            # A note shorter than one row has to be snapped onto one, which
            # moves its onset. This is the cost a coarse grid hides.
            short = sum(1 for d in durations if d is not None and d < period)
            snapped_rates.append(short / len(durations) if durations else 0.0)
        out[game] = {
            "n": len(tracks),
            "found": len(found),
            "rows_per_second": statistics.median([f[0] for f in found]) if found else 0.0,
            "fit": statistics.median([f[1] for f in found]) if found else 0.0,
            "snapped": statistics.median(snapped_rates) if snapped_rates else 0.0,
        }
    return name, out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--games", default="")
    args = parser.parse_args()

    wanted = {g.strip() for g in args.games.split(",") if g.strip()}
    records: dict[str, list] = {}
    for row_line in (args.out_dir / "manifest.jsonl").open():
        row = json.loads(row_line)
        if not row.get("ok") or not row.get("record_path"):
            continue
        game = row["tag"]["game"] or "?"
        if wanted and game not in wanted:
            continue
        record = json.loads((args.out_dir / row["record_path"]).read_text())
        onsets = [int(n["start"]) for n in record["notes"]]
        durations = [
            (int(n["end"]) - int(n["start"])) if n.get("end") is not None else None
            for n in record["notes"]
        ]
        span = int(row["render_seconds"] * TICKS)
        records.setdefault(game, []).append((onsets, durations, span))

    tenth_ioi = lambda clustered, durations: max(  # noqa: E731
        G.MIN_PERIOD_TICKS,
        _percentile([b - a for a, b in zip(clustered, clustered[1:]) if b > a], 0.10)
        or G.MAX_PERIOD_TICKS,
    )

    objectives = [
        ("A shipped: rel 10%, margin .02, no cap",
         {"tol_rel": 0.10, "tol_abs": 0, "margin": 0.02, "max_period": G.MAX_PERIOD_TICKS}),
        ("B tight margin .002",
         {"tol_rel": 0.10, "tol_abs": 0, "margin": 0.002, "max_period": G.MAX_PERIOD_TICKS}),
        ("C abs cap 4 ms",
         {"tol_rel": 0.10, "tol_abs": 4096, "margin": 0.02, "max_period": G.MAX_PERIOD_TICKS}),
        ("D period <= 10th pct IOI",
         {"tol_rel": 0.10, "tol_abs": 0, "margin": 0.02, "max_period": tenth_ioi}),
        ("E abs cap 4 ms + IOI cap",
         {"tol_rel": 0.10, "tol_abs": 4096, "margin": 0.02, "max_period": tenth_ioi}),
    ]

    for name, kwargs in objectives:
        _, result = evaluate(records, (name, kwargs))
        total_n = sum(v["n"] for v in result.values())
        total_found = sum(v["found"] for v in result.values())
        rps = [v["rows_per_second"] for v in result.values() if v["found"]]
        snapped = [v["snapped"] for v in result.values() if v["found"]]
        print(f"\n{name}")
        print(f"  found {total_found}/{total_n} ({100*total_found/max(total_n,1):.0f}%)"
              f"  rows/s spread {min(rps):.1f}-{max(rps):.1f}"
              f"  median snapped {100*statistics.median(snapped):.1f}%")
        for game in sorted(result):
            v = result[game]
            print(f"    {game[:26]:26s} {v['found']:3d}/{v['n']:3d}"
                  f"  {v['rows_per_second']:7.1f} rows/s  fit {v['fit']:.2f}"
                  f"  snapped {100*v['snapped']:5.1f}%")


if __name__ == "__main__":
    main()
