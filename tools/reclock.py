#!/usr/bin/env python3
"""Re-index the row scores on the per-game SPC700 timer clock.

    reclock.py <out-dir> [--dry-run] [--keep-grid]

Why this is a post-pass and not part of `extract.py`: the clock is a per-GAME
constant, derived from agreement across a game's tracks, and extraction is
per-track. Nothing here re-emulates anything. It reads the note records already
on disk, rebuilds `scores/*.json.gz` on the clock, and rewrites the manifest
rows with a `clock` block. On the 22-game corpus that is seconds rather than
the hour a re-extraction costs.

What changes, and what does not: the `grid` block is LEFT IN PLACE. It is still
a real measurement -- of the onset period, which is a musical question -- and
dropping it would destroy the evidence that motivated this change. What changes
is which of the two the scores are indexed on.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import (  # noqa: E402
    clock as clock_mod,
    envelope as envelope_mod,
    scores as scores_mod,
)

TICKS = clock_mod.TICKS_PER_SECOND


def rebuild(
    row: dict[str, Any], out_dir: Path, clock: clock_mod.Clock, write: bool
) -> dict[str, Any]:
    """Rebuild one track's scores on `clock`, returning the updated row."""
    row = dict(row)
    row["clock"] = clock.to_dict()

    record_path = row.get("record_path")
    if not record_path or not (out_dir / record_path).exists():
        row["scores"] = {}
        row.pop("scores_path", None)
        row.pop("scores_bytes", None)
        return row

    notes = json.loads((out_dir / record_path).read_text())["notes"]
    # The envelope is the factor missing from `velocity`, which uses VOL
    # alone while the DSP computes env x VOL. The census says how much that
    # costs per track without changing any existing field.
    row["envelope"] = envelope_mod.census(notes)
    row["expressive_channels"] = list(scores_mod.CHANNELS)
    render_ticks = int(float(row.get("render_seconds") or 0.0) * TICKS)
    grid = clock.to_grid(render_ticks)
    built = scores_mod.build(notes, grid, render_ticks)
    row["scores"] = built.stats()
    # The third score format. It existed in `scores.py` from milestone 6 but
    # was never emitted, so neither it nor its sustain channel reached any
    # published file. `timbre_of` is left None deliberately: the milestone 5
    # codebook failed its own cross-game validation, so every class is written
    # as -1 rather than as a number a consumer might trust.
    expressive = scores_mod.expressive(notes, grid, None, render_ticks)

    if not (grid.found and built.n_rows):
        row.pop("scores_path", None)
        row.pop("scores_bytes", None)
        return row

    stem = row["track_id"].replace(":", "_")
    path = out_dir / "scores" / f"{stem}.json.gz"
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(
                {
                    "track_id": row["track_id"],
                    # The clock the rows are on, so a score is self-describing
                    # and a consumer never has to consult the manifest to
                    # learn what one row means.
                    "clock": row["clock"],
                    # Kept for provenance: the onset grid this score used to be
                    # indexed on, and the fit that made it look reasonable.
                    "onset_grid": row.get("grid"),
                    **built.to_dict(),
                    "expressive": expressive,
                },
                handle,
                separators=(",", ":"),
            )
        row["scores_path"] = f"scores/{path.name}"
        row["scores_bytes"] = path.stat().st_size
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report the clocks and the census, write nothing",
    )
    args = parser.parse_args()

    manifest = args.out_dir / "manifest.jsonl"
    rows = [json.loads(line) for line in manifest.open()]
    clocks = clock_mod.game_clocks(rows)

    print("=== per-game clocks ===", file=sys.stderr)
    for game, clock in sorted(clocks.items()):
        if clock.period_ticks:
            print(
                f"  {game[:30]:32s}{clock.hz:8.2f} Hz  "
                f"{(clock.divider.label if clock.divider else ''):11s}"
                f"period {clock.period_ticks:6d} ticks  "
                f"(n={clock.n_confident}, {clock.agreement:.0%})",
                file=sys.stderr,
            )
    print(file=sys.stderr)
    for game, clock in sorted(clocks.items()):
        if not clock.period_ticks:
            print(f"  {game[:30]:32s}no clock: {clock.reason}", file=sys.stderr)

    updated: list[dict[str, Any]] = []
    changed = 0
    for row in rows:
        if not row.get("ok"):
            updated.append(row)
            continue
        clock = clock_mod.clock_for(row, clocks)
        before = (row.get("grid") or {}).get("period_ticks")
        new_row = rebuild(row, args.out_dir, clock, write=not args.dry_run)
        if before != clock.period_ticks:
            changed += 1
        updated.append(new_row)

    census = clock_mod.census(updated)
    total = sum(census.values())
    print("\n=== clock source census ===", file=sys.stderr)
    for source, count in census.items():
        print(
            f"  {source:12s}{count:5d} ({100 * count / total:4.1f}%)",
            file=sys.stderr,
        )
    hardware = census["game_tick"] + census["track_tick"]
    print(
        f"  hardware-grounded: {hardware}/{total} "
        f"({100 * hardware / total:.1f}%)",
        file=sys.stderr,
    )

    # Counted from the rebuilt score stats rather than from `scores_path`,
    # which a --dry-run leaves holding the previous run's value.
    scored = sum(1 for r in updated if (r.get("scores") or {}).get("n_rows"))
    print(f"\ntracks with row scores: {scored}/{total}", file=sys.stderr)
    print(f"tracks whose row period changed: {changed}", file=sys.stderr)

    if args.dry_run:
        print("\n--dry-run: nothing written", file=sys.stderr)
        return

    tmp = manifest.with_suffix(".jsonl.new")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in updated:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    tmp.replace(manifest)
    print(f"\nrewrote {manifest}", file=sys.stderr)


if __name__ == "__main__":
    main()
