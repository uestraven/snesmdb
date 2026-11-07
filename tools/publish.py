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
import glob
import hashlib
import gzip
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import (  # noqa: E402
    brr,
    clock as clock_mod,
    corpus as corpus_mod,
    envelope as envelope_mod,
    events as events_mod,
    provenance as provenance_mod,
    sampleid,
    spcfile,
    grid as grid_mod,
    midi as midi_mod,
    scores as scores_mod,
)

TICKS = grid_mod.TICKS_PER_SECOND

#: The published-tree schema names and the index document live in the library,
#: so the verifier checks the same definition this writes rather than a copy.
INTAKE_SCHEMA = corpus_mod.INTAKE_SCHEMA


def write_json_gz(path: Path, payload: Any) -> None:
    """Write gzipped JSON whose BYTES depend only on the content.

    `gzip.open` stamps the current time into the member header, so rebuilding
    an unchanged corpus produced a different hash for every one of its 3,948
    compressed files. That was measured: between the `gate5-rc1` and
    `gate5-rc2` trees every events, scores and intake file changed hash while
    all 3,948 were byte-identical once decompressed.

    The consequence is not cosmetic. The release pin exists so two trees can
    be compared, and a consumer diffing two downloads by hash would have
    concluded the whole dataset had changed when only a documentation file
    had. Making the bytes a function of the content alone means a hash
    difference means a content difference.

    The header carries TWO pieces of incidental metadata, not one. `mtime=0`
    handles the timestamp; `filename=""` is also required, because gzip stores
    the original name and would otherwise make the bytes depend on the track
    id. The second was caught only because the test compared two files written
    from the same payload under different names.
    """
    raw = json.dumps(payload, separators=(",", ":")).encode()
    with open(path, "wb") as out:
        with gzip.GzipFile(
            filename="", fileobj=out, mode="wb", compresslevel=9, mtime=0
        ) as handle:
            handle.write(raw)


def _clock_from_dict(info: dict[str, Any]) -> clock_mod.Clock:
    """The row clock a manifest row was scored on.

    THIS USED TO READ `row["grid"]`, the inferred ONSET period, which is no
    longer what rows are indexed on -- and because the grid was only found for
    866 of 1,316 tracks, publishing from it silently dropped a third of the
    corpus that the clock covers in full. The onset grid is still carried
    through to the payload as provenance; it just does not decide anything.
    """
    return clock_mod.Clock(
        period_ticks=int(info.get("period_ticks") or 0),
        source=str(info.get("source") or clock_mod.SOURCE_FIXED),
        reason=str(info.get("reason") or ""),
        measured_hz=float(info.get("measured_hz") or 0.0),
    )


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


def _sample_ids(
    spc_index: dict[str, str], row: dict[str, Any]
) -> dict[int, str]:
    """SRCN -> content hash of the decoded BRR block, for THIS track.

    An index does not name a fixed sample even inside one game: Super
    Turrican's 8 indices resolve to 48 distinct samples across its 12 tracks,
    because each SPC is its own ARAM snapshot and drivers reload their bank.
    So identity has to be the content, and the mapping is per track.
    """
    path = spc_index.get(row.get("source", ""))
    if not path:
        return {}
    try:
        spc = spcfile.load(Path(path))
    except Exception:
        return {}
    srcns = {int(k) for k in (row.get("samples") or {})}
    out: dict[int, str] = {}
    for srcn, entry in brr.read_directory(spc.aram, spc.dsp[0x5D], srcns).items():
        if not entry.plausible:
            continue
        try:
            decoded = brr.decode(spc.aram, entry.start, entry.loop)
        except (ValueError, IndexError):
            continue
        if decoded.data:
            # Defined in sampleid.py: SHA-256 over a version prefix, the loop
            # offset, and the decoded PCM as signed 16-bit little-endian,
            # truncated to 64 bits. The loop offset is PART of the identity --
            # identical audio with different loop points sustains differently.
            out[srcn] = sampleid.sample_id(decoded.data, decoded.loop_offset)
    return out


def _software_divisor(row: dict[str, Any], clock_hz: float) -> int | None:
    """How many timer ticks the driver counts per sequencer row, or None.

    A row in this dataset is one HARDWARE timer tick. Where a driver counts M
    ticks per musical row, rows are M times finer than the music -- and M is
    exactly the ratio between the register clock and the rate `tick.py`
    measures from write cadence, because the former is the timer and the
    latter is the sequencer.

    Recoverable only where the write-cadence estimate exists AND the ratio is
    a clean integer: 462 of the 519 tracks with a tick, 89%, and about a third
    of the corpus. None everywhere else, which is honest rather than assuming
    M = 1 -- assuming it would silently claim the row IS the musical row for
    two thirds of the corpus.
    """
    tick = (row.get("tick") or {})
    if not tick.get("found") or not tick.get("hz") or not clock_hz:
        return None
    ratio = clock_hz / float(tick["hz"])
    if ratio < 1.0:
        return None
    nearest = round(ratio)
    if nearest < 1 or abs(ratio - nearest) > 0.02:
        return None
    return int(nearest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--spc-dir", type=Path, default=Path("data/spc"),
        help="where to find SPC files. Needed for content-based sample_id: an "
             "SRCN index does not name a fixed sample even within one game, "
             "so identity is the hash of the decoded BRR block.",
    )
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
    for sub in ("scores", "midi", "intake", "events"):
        (args.dist_dir / sub).mkdir(parents=True, exist_ok=True)

    counts = {
        "tracks": 0, "with_clock": 0, "scores_written": 0, "midi_written": 0,
        "midi_notes_written": 0, "midi_notes_dropped": 0,
        "expressive_with_timbre": 0, "intake_written": 0,
        "with_software_divisor": 0, "uniform_written": 0,
        "events_written": 0, "events_total": 0, "events_unpitched": 0,
        "tracks_unpitched_only": 0, "sample_ids_resolved": 0,
    }
    spc_index = {
        Path(p).name: p
        for p in glob.glob(str(args.spc_dir / "*" / "*.spc"))
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
            # The MUSICAL classification, computed since milestone 1 and never
            # published, so a researcher could not exclude sound effects from a
            # melodic study without re-deriving it. It is independent of
            # `extraction_status`: 42 effects contain recoverable pitch and 11
            # music tracks contain none, so neither field implies the other.
            "track_class": row.get("track_class"),
        }

        # MIDI: available for every track with any pitched note.
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

        # The three scores are indexed on the SPC700 timer register, which
        # every track has, so this is no longer conditional on an inference.
        # Resolved BEFORE the intake tree is written, which needs them. An
        # evaluator found intake notes carrying only `srcn` -- the identifier
        # the documentation explicitly tells researchers not to join on --
        # with no path to a `sample_id` at all.
        sample_ids = _sample_ids(spc_index, row)
        track_clock = _clock_from_dict(row.get("clock", {}))
        if track_clock.period_ticks:
            counts["with_clock"] += 1
            track_grid = track_clock.to_grid(render_ticks)
            built = scores_mod.build(notes, track_grid, render_ticks)

            # THE UNIFORM GRID. This was missing: scores.uniform_grid existed,
            # was benchmarked, and extract.py wrote a `uniform` block into
            # data/out -- and publish.py never learned about it, so the
            # distributable corpus had no 100 Hz scores at all while every
            # internal measurement passed. Third time this shape of defect
            # shipped from this pipeline, after dead expressive() code and a
            # rebuild recipe that omitted a required step.
            uniform_grid = scores_mod.uniform_grid(render_ticks)
            uniform_built = scores_mod.build(notes, uniform_grid, render_ticks)
            counts["uniform_written"] += 1
            timbre_of = timbre_by_game.get(row["tag"]["game"] or "", {})
            expr = scores_mod.expressive(notes, track_grid, timbre_of, render_ticks)
            if timbre_of:
                counts["expressive_with_timbre"] += 1
            payload = {
                "track_id": row["track_id"],
                "clock": row.get("clock"),
                "software_divisor_m": _software_divisor(row, track_clock.hz),
                "timers": row.get("timers"),
                "envelope": row.get("envelope"),
                # Provenance only: the inferred ONSET period, which is a
                # separate musical measurement and indexes nothing.
                "onset_grid": row.get("grid"),
                "tick": row.get("tick"),
                "separated": built.separated,
                "blended": built.blended,
                "expressive": expr,
                # The comparable score: the same three formats on a fixed
                # 100 Hz grid, so a row means the same thing in every track.
                # Use this for anything that compares games; the primary score
                # above is this driver's own timer tick and its rate differs
                # per track.
                "uniform": {
                    "hz": scores_mod.UNIFORM_HZ,
                    "period_ticks": uniform_grid.period_ticks,
                    "n_rows": uniform_built.n_rows,
                    "separated": uniform_built.separated,
                    "blended": uniform_built.blended,
                    "expressive": scores_mod.expressive(
                        notes, uniform_grid, timbre_of, render_ticks
                    ),
                    "stats": uniform_built.stats(),
                },
                "stats": built.stats(),
            }
            write_json_gz(args.dist_dir / "scores" / f"{stem}.json.gz", payload)
            counts["scores_written"] += 1
            entry["scores"] = f"scores/{stem}.json.gz"
            entry["uniform_hz"] = scores_mod.UNIFORM_HZ
            entry["uniform_n_rows"] = uniform_built.n_rows

            # Intake tree. The shape is documented in DATASET.md and is NOT
            # verified against the renderer's `acquire(from_extracted=True)`,
            # which lives in a sibling project not present here; that is
            # recorded as a limitation rather than assumed compatible.
            intake = {
                "schema": INTAKE_SCHEMA,
                "source": {"track_id": row["track_id"], "sha256": row["sha256"]},
                "timing": {
                    "ticks_per_second": TICKS,
                    "row_period_ticks": track_clock.period_ticks,
                    "rows_per_second": round(track_clock.hz, 4),
                    "row_clock_source": track_clock.source,
                    # One row is one physical timer tick. Where a driver counts
                    # M ticks per sequencer row, rows are M times finer than the
                    # music and M is not recoverable here -- see DATASET.md.
                    "sequencer_timer": (row.get("timers") or {}).get(
                        "sequencer_timer"
                    ),
                    # Timer ticks per musical row, where it can be recovered.
                    # Multiply a row index by this to get a sequencer row.
                    # None means it is not known -- not that it is 1.
                    "software_divisor_m": _software_divisor(row, track_clock.hz),
                    # The write-cadence estimate the divisor comes from. It is
                    # the SEQUENCER rate, not the timer, and it is absent for
                    # 797 tracks and wrong for a documented 20.
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
                                # Velocity is the ATTACK (VOL alone, which is
                                # correct because the ADSR attack reaches full
                                # envelope). Sustain is where it settles, and
                                # differs for 20% of the corpus.
                                "sustain": scores_mod._sustain(
                                    n, scores_mod._velocity(n)
                                ),
                                "srcn": n["srcn"],
                                # The joinable identity. `srcn` is an ARAM
                                # index and is not stable across a game's
                                # tracks; this is the content hash.
                                "sample_id": sample_ids.get(
                                    int(n["srcn"]), ""
                                ),
                                "timbre_class": timbre_of.get(int(n["srcn"]), -1),
                            }
                            for n in notes if int(n["voice"]) == v
                        ],
                    }
                    for v in range(scores_mod.N_VOICES)
                ],
            }
            write_json_gz(args.dist_dir / "intake" / f"{stem}.json.gz", intake)
            counts["intake_written"] += 1
            if _software_divisor(row, track_clock.hz):
                counts["with_software_divisor"] += 1
            entry["intake"] = f"intake/{stem}.json.gz"

        # events.v3 -- the researcher-facing table. Flat, in seconds, pitched
        # AND unpitched, with every absence explained.
        #
        # OUTSIDE the clock conditional, deliberately. This block used to sit
        # inside it, which made the event table depend on a row clock it never
        # reads: every onset here is in seconds. Every track in the corpus
        # happens to have a clock, so the coupling cost nothing and was
        # invisible -- but the published contract says every track has an event
        # table, and that claim must not rest on a coincidence in the current
        # corpus.
        counts["sample_ids_resolved"] += len(sample_ids)
        table = events_mod.build(
            track_id=row["track_id"],
            ok=bool(row.get("ok")),
            duration_sec=float(row.get("render_seconds") or 0.0),
            notes=notes,
            sample_ids=sample_ids,
            legato_steps=record.get("legato_steps") or [],
            attack_level=scores_mod._velocity,
            sustain_level=scores_mod._sustain,
            game=row["tag"]["game"],
            track_class=row.get("track_class"),
        )
        write_json_gz(args.dist_dir / "events" / f"{stem}.json.gz", table)
        counts["events_written"] += 1
        counts["events_total"] += table["event_count"]
        counts["events_unpitched"] += table["unpitched_event_count"]
        if table["extraction_status"] == events_mod.STATUS_UNPITCHED_ONLY:
            counts["tracks_unpitched_only"] += 1
        entry["events"] = f"events/{stem}.json.gz"
        entry["event_count"] = table["event_count"]
        entry["pitched_event_count"] = table["pitched_event_count"]
        entry["pitched_attack_count"] = table["pitched_attack_count"]
        entry["unpitched_event_count"] = table["unpitched_event_count"]
        # An event is not an attack. Published alongside the event total so a
        # rhythmic study gets the right number without filtering by `origin`.
        entry["attack_count"] = table["attack_count"]
        entry["legato_step_count"] = table["legato_step_count"]
        entry["extraction_status"] = table["extraction_status"]

        index.append(entry)

    (args.dist_dir / "index.json").write_text(
        json.dumps(corpus_mod.index_document(index), indent=1)
    )
    # tracks.csv: the same per-track metadata in a format that degrades
    # gracefully. A truncated JSON document is unparseable in its entirety --
    # an evaluator received a copy of index.json short-written at a 768 KiB
    # boundary and lost all 1,316 rows to one unterminated string, recovering
    # 734 only by incremental decoding. A truncated CSV loses the tail and
    # keeps every line before it.
    (args.dist_dir / "tracks.csv").write_text(corpus_mod.tracks_csv(index))
    # Stands alone so the artifact is traceable without opening summary.json.
    (args.dist_dir / "provenance.json").write_text(json.dumps(
        provenance_mod.record(
            tool="publish.py",
            out_dir=str(args.out_dir),
            dist_dir=str(args.dist_dir),
            limit=args.limit or None,
            counts=counts,
        ),
        indent=1,
    ))
    # timbre_codebook.json and timbre_assignments.json are NOT copied. The
    # milestone 5 codebook failed its own cross-game validation and
    # `timbre_class` publishes as -1 throughout, so shipping them would offer
    # a consumer a clustering this project documents as untransferable. The
    # negative result lives in the docs; the artifact carries neither.
    for name in ("splits.json", "summary.json",
                 "performance.json", "performance_music.json"):
        source = args.out_dir / name
        if source.is_file():
            (args.dist_dir / name).write_text(source.read_text())
    # CHANGELOG.md ships with the corpus because the index's top-level shape
    # changed: a download whose migration note stayed in the repository would
    # leave a consumer to discover the break by crashing.
    for doc in ("DATASET.md", "CHANGELOG.md", "SCHEMA.md"):
        source = Path(__file__).resolve().parent.parent / "docs" / doc
        if source.is_file():
            (args.dist_dir / doc).write_text(source.read_text())

    (args.dist_dir / "manifest_counts.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))
    print(f"\nwrote {args.dist_dir}")


if __name__ == "__main__":
    main()
