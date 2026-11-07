#!/usr/bin/env python3
"""What a uniform row rate costs, measured on the real corpus.

    rate_benchmark.py <out-dir> [--rates 50,100,200] [--tracks 300]

The uniform score needs one rate for the whole corpus, and the choice is a
trade: a coarser grid is cheaper to store and shorter to model, and it destroys
musical events. This measures the destruction rather than arguing about it.

FIVE COSTS, and they are not interchangeable:

1. `notes_preserved`   -- the headline. A note survives if its onset lands on a
                          row no other note of that voice already occupies.
2. `repeat_attacks_lost` -- THE ONE THAT MATTERS MOST MUSICALLY. Two notes of
                          the same pitch on the same voice, landing on the same
                          row, become one note. A tremolo, a drum roll or a
                          repeated ostinato figure collapses into a single
                          sustained note, and no amount of velocity or duration
                          information brings the rhythm back.
3. `collisions`        -- different pitches on one voice sharing a row. The
                          later note is simply lost.
4. onset / offset error -- how far a kept note moves. Recoverable-ish: the
                          note is still there, just early or late.
5. rows and bytes      -- sequence length and gzipped size, which is what the
                          cheapness of a coarse grid actually buys.

Collisions are counted PER TRACK. An earlier pass at these figures pooled notes
from 260 tracks into one list and counted (voice, row) collisions across all of
them, which reported 86% onset loss at 24 Hz -- rows only mean anything inside
a single track.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import scores as scores_mod  # noqa: E402

TICKS = 1_024_000


def measure(tracks: list[tuple[float, list[dict[str, Any]]]], hz: float) -> dict[str, Any]:
    period = TICKS / hz
    total = kept = repeats = collisions = short = 0
    onset_err: list[float] = []
    offset_err: list[float] = []
    rows_total = 0

    for seconds, notes in tracks:
        rows_total += int(seconds * hz) + 1
        occupied: dict[tuple[int, int], int] = {}
        for note in notes:
            total += 1
            voice = int(note["voice"])
            row = round(note["start"] / period)
            onset_err.append(abs(note["start"] - row * period) / TICKS * 1000)
            end = note.get("end")
            if end:
                end_row = round(end / period)
                offset_err.append(abs(end - end_row * period) / TICKS * 1000)
                if end - note["start"] < period:
                    short += 1
            key = (voice, row)
            if key in occupied:
                # Same pitch on the same voice and row: a repeated attack the
                # grid cannot express. Different pitch: an outright loss.
                if occupied[key] == note["midi_note"]:
                    repeats += 1
                else:
                    collisions += 1
            else:
                occupied[key] = note["midi_note"]
                kept += 1
    return {
        "hz": hz,
        "row_ms": 1000.0 / hz,
        "exact_divisor": float(TICKS / hz).is_integer(),
        "notes": total,
        "preserved_pct": 100.0 * kept / total if total else 0.0,
        "repeat_attacks_lost": repeats,
        "repeat_attacks_lost_pct": 100.0 * repeats / total if total else 0.0,
        "collisions": collisions,
        "collisions_pct": 100.0 * collisions / total if total else 0.0,
        "shorter_than_a_row_pct": 100.0 * short / total if total else 0.0,
        "onset_err_ms_median": statistics.median(onset_err) if onset_err else 0.0,
        "onset_err_ms_p95": (
            sorted(onset_err)[int(0.95 * (len(onset_err) - 1))] if onset_err else 0.0
        ),
        "offset_err_ms_median": statistics.median(offset_err) if offset_err else 0.0,
        "rows_total": rows_total,
    }


def sized(out_dir: Path, rows: list[dict[str, Any]], hz: float, n: int) -> int:
    """Gzipped bytes of the uniform score for `n` tracks, at this rate."""
    total = 0
    for row in rows[:n]:
        notes = json.loads((out_dir / row["record_path"]).read_text())["notes"]
        render = int(float(row.get("render_seconds") or 0.0) * TICKS)
        grid = scores_mod.uniform_grid(render, hz=hz)
        built = scores_mod.build(notes, grid, render)
        payload = {
            "separated": built.separated,
            "blended": built.blended,
            "expressive": scores_mod.expressive(notes, grid, None, render),
        }
        total += len(gzip.compress(
            json.dumps(payload, separators=(",", ":")).encode(), 6
        ))
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--rates", default="50,100,200")
    parser.add_argument("--tracks", type=int, default=300)
    parser.add_argument("--size-tracks", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rows = [
        r for r in (json.loads(line) for line in (args.out_dir / "manifest.jsonl").open())
        if r.get("ok") and r.get("record_path") and r.get("track_class") == "music"
    ]
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.tracks]

    tracks: list[tuple[float, list[dict[str, Any]]]] = []
    for row in rows:
        notes = [
            n for n in json.loads((args.out_dir / row["record_path"]).read_text())["notes"]
            if n.get("midi_note") is not None
        ]
        if notes:
            tracks.append((float(row["render_seconds"]), notes))

    rates = [float(x) for x in args.rates.split(",")]
    results = [measure(tracks, hz) for hz in rates]
    notes = results[0]["notes"]
    print(
        f"{notes:,} pitched notes across {len(tracks)} music tracks; "
        f"sizes over {args.size_tracks} tracks\n"
    )
    print(f"{'rate':>6s}{'row ms':>8s}{'exact':>7s}{'preserved':>11s}"
          f"{'repeat att':>12s}{'collide':>9s}{'<1 row':>8s}"
          f"{'onset ms':>10s}{'p95':>7s}{'offset ms':>11s}{'rows':>10s}{'MB/40':>8s}")
    for result in results:
        mb = sized(args.out_dir, rows, result["hz"], args.size_tracks) / 1e6
        print(
            f"{result['hz']:6.0f}{result['row_ms']:8.1f}"
            f"{('yes' if result['exact_divisor'] else 'no'):>7s}"
            f"{result['preserved_pct']:10.3f}%"
            f"{result['repeat_attacks_lost_pct']:11.3f}%"
            f"{result['collisions_pct']:8.3f}%"
            f"{result['shorter_than_a_row_pct']:7.2f}%"
            f"{result['onset_err_ms_median']:10.2f}{result['onset_err_ms_p95']:7.1f}"
            f"{result['offset_err_ms_median']:11.2f}"
            f"{result['rows_total']:10,d}{mb:8.1f}"
        )
    print(
        "\nrepeat att = two notes of the SAME pitch on one voice landing on one\n"
        "row, so a tremolo or repeated figure becomes one sustained note. That\n"
        "loss is unrecoverable and is the cost to weigh first.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
