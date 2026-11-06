#!/usr/bin/env python3
"""Per-game legato step rates: how much of a game's melody has no key-on.

    legato_report.py <out-dir> [--track-class music] [--csv]

A legato step is a note the driver delivered by writing PITCH to an already
sounding voice, with no key-on. `voices.py` emits these as an independent
table rather than as notes, so this is the view that puts the two side by
side -- and the reason it matters is that the rate is a property of the
DRIVER, not of the music.

That makes it a comparability hazard. A game whose driver always re-keys has
every note in `notes`; a game whose driver uses legato has some fraction of
its melody in `legato_steps` instead. Any per-game statistic computed over
`notes` alone -- note density, interval distributions, melodic range -- is
therefore measuring driver convention as much as composition, and this report
is how you find out by how much before trusting such a comparison.

Columns:

    notes          key-on notes, each traceable to a hardware edge
    steps          inferred note successions
    +%             steps as a percentage of notes
    med st         median absolute interval of a step, in semitones
    tempered       share of steps landing within 0.1 st of a whole semitone,
                   against a null that jitters each interval by +/-6%
    x              that share over the null -- THE TRUST COLUMN, see below
    med obs ms     median time from a step to the end of its parent note; a
                   short observation is a weaker claim (see LegatoStep)

READ THE `x` COLUMN BEFORE THE `+%` COLUMN. A step is detected from a pitch
write, and a driver writes pitch for melody AND for modulation. Equal
temperament separates them: a real note succession lands on a whole semitone,
while portamento, vibrato and pitch-based effects are continuous and land
anywhere. So per game, the enrichment over the jitter null says whether that
game's steps are music at all.

Measured on the 22-game corpus, this splits the games in two, and it is not
the split the raw rate suggests:

    Super Turrican        99.2% tempered vs 41.5% null   2.39x   music
    Super Castlevania 4   94.7%              54.8%       1.73x   music
    Plok!                 78.5%              51.6%       1.52x   music
    Breath of Fire 2      82.8%              59.2%       1.40x   music
    Chrono Trigger        33.3%              26.8%       1.24x   music
    Final Fantasy 6       83.3%              71.0%       1.17x   music
    Mega Man X            74.0%              63.4%       1.17x   music
    ---
    Earthbound            17.5%              17.1%       1.02x   NOT music
    Kirby Super Star      15.8%              16.0%       0.99x   NOT music
    Axelay                18.9%              19.7%       0.96x   NOT music
    Donkey Kong Country   15.1%              15.9%       0.95x   NOT music
    Donkey Kong Country 2  8.3%               9.1%       0.91x   NOT music

Earthbound and Axelay are the two largest step populations in the corpus and
neither is melodic -- those drivers use PITCH for continuous modulation, so
their steps are real register events that are not notes. Treating the corpus
rate as a melodic figure would therefore be wrong, and wrong mostly because of
the games with the highest rates.

The test is a POPULATION statistic and cannot judge one step: a single
interval sits near a whole semitone 20-30% of the time by chance. So nothing
is filtered on it. It is reported, per game, as the thing to check first.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

CLOCK_RATE = 1_024_000


def collect(out_dir: Path, track_class: str | None) -> dict[str, dict[str, Any]]:
    games: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"notes": 0, "steps": 0, "semitones": [], "observed": [],
                 "tracks": 0, "tracks_with_steps": 0}
    )
    for line in (out_dir / "manifest.jsonl").open():
        row = json.loads(line)
        if not row.get("ok") or not row.get("record_path"):
            continue
        if track_class and row.get("track_class") != track_class:
            continue
        record = json.loads((out_dir / row["record_path"]).read_text())
        steps = record.get("legato_steps") or []
        entry = games[(row.get("tag") or {}).get("game") or "?"]
        entry["notes"] += len(record.get("notes") or [])
        entry["steps"] += len(steps)
        entry["tracks"] += 1
        if steps:
            entry["tracks_with_steps"] += 1
        for step in steps:
            entry["semitones"].append(abs(step["semitones"]))
            entry["observed"].append(step["observed_ticks"] / CLOCK_RATE * 1000)
    return games


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument(
        "--track-class", default=None,
        help="restrict to one track_class, e.g. music",
    )
    parser.add_argument("--csv", action="store_true")
    args = parser.parse_args()

    games = collect(args.out_dir, args.track_class)
    if not games:
        print("no tracks matched", file=sys.stderr)
        return

    rng = random.Random(0)

    def tempered(values: list[float]) -> float:
        """Share landing within 0.1 st of a whole semitone."""
        if not values:
            return 0.0
        hits = sum(1 for x in values if abs(x - round(x)) <= 0.1)
        return 100.0 * hits / len(values)

    rows = []
    for game, entry in games.items():
        rate = 100 * entry["steps"] / entry["notes"] if entry["notes"] else 0.0
        semis = entry["semitones"]
        # The null preserves the interval distribution and destroys only its
        # alignment to the tempered grid, the same shape of control used for
        # the driver-clock test in clock.py.
        null = [x * rng.uniform(0.94, 1.06) for x in semis]
        temp, temp_null = tempered(semis), tempered(null)
        rows.append((
            rate, game, entry["notes"], entry["steps"],
            statistics.median(semis) if semis else 0.0,
            temp, (temp / temp_null) if temp_null else 0.0,
            statistics.median(entry["observed"]) if entry["observed"] else 0.0,
            entry["tracks_with_steps"], entry["tracks"],
        ))
    rows.sort(reverse=True)

    if args.csv:
        print("game,notes,legato_steps,percent,median_semitones,"
              "tempered_percent,tempered_enrichment,median_observed_ms,"
              "tracks_with_steps,tracks")
        for (rate, game, notes, steps, semis, temp, enrich, obs,
             twc, tracks) in rows:
            print(f'"{game}",{notes},{steps},{rate:.2f},{semis:.3f},'
                  f'{temp:.1f},{enrich:.2f},{obs:.1f},{twc},{tracks}')
        return

    scope = args.track_class or "all"
    print(f"Legato steps by game ({scope} tracks)\n")
    print(f"{'game':28s}{'notes':>9s}{'steps':>8s}{'+%':>7s}"
          f"{'med st':>8s}{'tempered':>10s}{'x':>7s}{'obs ms':>9s}{'tracks':>11s}")
    for (rate, game, notes, steps, semis, temp, enrich, obs,
         twc, tracks) in rows:
        verdict = "" if enrich >= 1.10 else "  <- not melodic"
        print(f"{game[:27]:28s}{notes:9d}{steps:8d}{rate:6.1f}%"
              f"{semis:8.2f}{temp:9.1f}%{enrich:7.2f}{obs:9.0f}"
              f"{f'{twc}/{tracks}':>11s}{verdict}")

    total_notes = sum(r[2] for r in rows)
    total_steps = sum(r[3] for r in rows)
    melodic = sum(r[3] for r in rows if r[6] >= 1.10)
    print(f"\n{'CORPUS':28s}{total_notes:9d}{total_steps:8d}"
          f"{100 * total_steps / total_notes:6.1f}%")
    print(f"{'of which in melodic games':28s}{'':9s}{melodic:8d}"
          f"{100 * melodic / total_notes:6.1f}%")
    using = [r for r in rows if r[3]]
    print(f"\ngames with any legato: {len(using)}/{len(rows)}")
    if using:
        print(f"range across games: {min(r[0] for r in rows):.1f}% to "
              f"{max(r[0] for r in rows):.1f}%")
    print(
        "\nThe spread is the finding. A per-game statistic over `notes` alone\n"
        "measures driver convention as much as composition.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
