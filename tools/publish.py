#!/usr/bin/env python3
"""Assemble the distributable corpus tree.

    publish.py <out-dir> <dist-dir> [--limit 0]

Milestone 6. Emits, per track: the three score formats, an 8-track MIDI, and
an intake JSON tree; plus, once, the splits, the manifest and the dataset
documentation.

WHAT THIS DOES NOT PUT IN THE TREE, and why. No SPC files: snesmusic.org's
terms are "educational and personal non-profit use only", narrower than
NES-MDB's research licence, and the design doc's rule is that they never enter
the repository and never ship in a product artifact. The published thing is
derived data plus the tools to rebuild it from SPCs the user supplies
themselves. The tree is written OUTSIDE the repository for the same reason and
the directory is refused if it is inside one.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import grid as grid_mod, midi as midi_mod, scores as scores_mod  # noqa: E402

TICKS = grid_mod.TICKS_PER_SECOND


def _grid_from_dict(info: dict[str, Any]) -> grid_mod.Grid:
    g = grid_mod.Grid(found=bool(info.get("found")))
    g.period_ticks = int(info.get("period_ticks") or 0)
    g.phase_ticks = int(info.get("phase_ticks") or 0)
    g.n_rows = int(info.get("n_rows") or 0)
    g.fit = float(info.get("fit") or 0.0)
    g.cluster_ticks = int(info.get("cluster_ticks") or 0)
    return g


def _timbre_map(out_dir: Path) -> dict[str, dict[int, int]]:
    """game -> {srcn: class}, from the milestone 5 assignments.

    A sample index can appear in more than one entry for a game because ARAM
    layout differs between its tracks, so the majority class wins and the
    ambiguity is counted by the caller rather than silently resolved.
    """
    path = out_dir / "timbre_assignments.json"
    if not path.is_file():
        return {}
    votes: dict[str, dict[int, dict[int, int]]] = {}
    for row in json.loads(path.read_text()):
        game = row["game"]
        for srcn in row["srcns"]:
            bucket = votes.setdefault(game, {}).setdefault(int(srcn), {})
            bucket[row["timbre_class"]] = bucket.get(row["timbre_class"], 0) + 1
    return {
        game: {srcn: max(counts.items(), key=lambda kv: kv[1])[0]
               for srcn, counts in by_srcn.items()}
        for game, by_srcn in votes.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    # Refuse to write derived copyrighted material into a git tree.
    probe = subprocess.run(
        ["git", "-C", str(args.dist_dir.parent), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True,
    )
    if probe.returncode == 0 and probe.stdout.strip() == "true":
        raise SystemExit(
            f"{args.dist_dir} is inside a git work tree. The corpus is derived "
            f"from research-only SPCs and must not be committed; publish it "
            f"outside the repository."
        )

    rows = [json.loads(line) for line in (args.out_dir / "manifest.jsonl").open()]
    good = [r for r in rows if r.get("ok") and r.get("record_path")]
    if args.limit:
        good = good[: args.limit]

    timbre_by_game = _timbre_map(args.out_dir)
    for sub in ("scores", "midi", "intake"):
        (args.dist_dir / sub).mkdir(parents=True, exist_ok=True)

    counts = {
        "tracks": 0, "with_grid": 0, "scores_written": 0, "midi_written": 0,
        "midi_notes_written": 0, "midi_notes_dropped": 0,
        "expressive_with_timbre": 0, "intake_written": 0,
    }
    index: list[dict[str, Any]] = []

    for row in good:
        record = json.loads((args.out_dir / row["record_path"]).read_text())
        notes = record["notes"]
        stem = row["track_id"].replace(":", "_")
        render_ticks = int(row["render_seconds"] * TICKS)
        counts["tracks"] += 1

        entry: dict[str, Any] = {
            "track_id": row["track_id"],
            "game": row["tag"]["game"],
            "title": row["tag"]["title"],
            "composers": row["tag"].get("composers") or [],
            "composer_truncated": bool(row["tag"].get("composer_truncated")),
            "split": row.get("split"),
            "sha256_source_spc": row["sha256"],
            "render_seconds": row["render_seconds"],
            "n_notes": len(notes),
            "checks_passed": bool(row.get("checks", {}).get("ok")),
        }

        # MIDI: available for every track with any pitched note, grid or not.
        data = midi_mod.from_notes(
            notes, render_ticks=render_ticks,
            name=f"{row['tag']['game']} - {row['tag']['title']}",
        )
        info = midi_mod.summary(notes)
        if info["n_written"]:
            (args.dist_dir / "midi" / f"{stem}.mid").write_bytes(data)
            counts["midi_written"] += 1
            counts["midi_notes_written"] += info["n_written"]
            counts["midi_notes_dropped"] += (
                info["n_unpitched_dropped"] + info["n_out_of_range_dropped"]
            )
            entry["midi"] = f"midi/{stem}.mid"
            entry["midi_summary"] = info

        # The three scores need a grid.
        track_grid = _grid_from_dict(row.get("grid", {}))
        if track_grid.found and track_grid.period_ticks:
            counts["with_grid"] += 1
            built = scores_mod.build(notes, track_grid, render_ticks)
            timbre_of = timbre_by_game.get(row["tag"]["game"] or "", {})
            expr = scores_mod.expressive(notes, track_grid, timbre_of, render_ticks)
            if timbre_of:
                counts["expressive_with_timbre"] += 1
            payload = {
                "track_id": row["track_id"],
                "grid": row["grid"],
                "tick": row.get("tick"),
                "separated": built.separated,
                "blended": built.blended,
                "expressive": expr,
                "stats": built.stats(),
            }
            with gzip.open(args.dist_dir / "scores" / f"{stem}.json.gz", "wt") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            counts["scores_written"] += 1
            entry["scores"] = f"scores/{stem}.json.gz"

            # Intake tree. The shape is documented in DATASET.md and is NOT
            # verified against the renderer's `acquire(from_extracted=True)`,
            # which lives in a sibling project not present here; that is
            # recorded as a limitation rather than assumed compatible.
            intake = {
                "schema": "snesmdb.intake.v1",
                "source": {"track_id": row["track_id"], "sha256": row["sha256"]},
                "timing": {
                    "ticks_per_second": TICKS,
                    "row_period_ticks": track_grid.period_ticks,
                    "rows_per_second": row["grid"].get("rows_per_second"),
                    "driver_tick_hz": (row.get("tick") or {}).get("hz"),
                },
                "voices": [
                    {
                        "voice": v,
                        "notes": [
                            {
                                "start_sec": n["start_sec"],
                                "end_sec": n.get("end_sec"),
                                "midi_note": n.get("midi_note"),
                                "velocity": scores_mod._velocity(n),
                                "srcn": n["srcn"],
                                "timbre_class": timbre_of.get(int(n["srcn"]), -1),
                            }
                            for n in notes if int(n["voice"]) == v
                        ],
                    }
                    for v in range(scores_mod.N_VOICES)
                ],
            }
            with gzip.open(args.dist_dir / "intake" / f"{stem}.json.gz", "wt") as handle:
                json.dump(intake, handle, separators=(",", ":"))
            counts["intake_written"] += 1
            entry["intake"] = f"intake/{stem}.json.gz"

        index.append(entry)

    (args.dist_dir / "index.json").write_text(json.dumps(index, indent=1))
    for name in ("splits.json", "summary.json", "timbre_codebook.json", "performance.json"):
        source = args.out_dir / name
        if source.is_file():
            (args.dist_dir / name).write_text(source.read_text())
    for doc in ("DATASET.md",):
        source = Path(__file__).resolve().parent.parent / "docs" / doc
        if source.is_file():
            (args.dist_dir / doc).write_text(source.read_text())

    (args.dist_dir / "manifest_counts.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))
    print(f"\nwrote {args.dist_dir}")


if __name__ == "__main__":
    main()
