#!/usr/bin/env python3
"""Batch-extract a directory of SPCs into a corpus tree.

    extract.py <spc-dir> <out-dir> [--seconds 180] [--keep-wav] [--jobs 4]

Writes, per track, a JSON record of its notes and metadata, and one
manifest.jsonl for the corpus, plus splits.json. Every record carries the
source file's sha256 and a validation score, so a corpus row can always be
traced back and judged.

Nothing here hides a failure: a track that will not load, will not play, or
scores badly is recorded with its reason and counted in the summary. A corpus
whose manifest only lists successes cannot be reasoned about.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import gzip
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import splits as splits_mod  # noqa: E402
from snesmdb.spcfile import SpcError, load  # noqa: E402
from snesmdb import brr, pitch  # noqa: E402
from snesmdb.checks import audio_peak, run as run_checks  # noqa: E402
from snesmdb import grid as grid_mod, scores as scores_mod, tick as tick_mod  # noqa: E402
from snesmdb.voices import extract, read_log  # noqa: E402
from snesmdb import trackclass  # noqa: E402

BINARY = Path(__file__).resolve().parent.parent / "build" / "spc_dump"


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _track_id(path: Path, sha: str) -> str:
    return f"{path.stem}:{sha[:12]}"


def process(args: tuple[str, float, bool, str]) -> dict[str, Any]:
    """Extract one SPC. Returns a manifest row, successful or not."""
    path_str, seconds, want_audio, out_dir_str, max_seconds = args
    out_dir = Path(out_dir_str)
    path = Path(path_str)
    row: dict[str, Any] = {"source": path.name, "ok": False}

    try:
        spc = load(path)
    except (SpcError, OSError) as error:
        row["error"] = f"load: {error}"
        return row

    # Render for the track's OWN length, from the ID666 "seconds to play"
    # field, rather than a flat window. A fixed 60 s both over-rendered a
    # 9-second fragment and captured 8.8% of the 683-second "Dancing Mad
    # (Full)" -- 68 of Final Fantasy VI's 82 tracks are longer than 60 s, so a
    # flat window silently truncated most of the corpus.
    if seconds <= 0:
        tagged = spc.tag.seconds or 0
        seconds = float(min(tagged, max_seconds)) if tagged else 180.0
        row["render_source"] = "id666" if tagged else "default"
    else:
        row["render_source"] = "requested"
    row["render_seconds"] = seconds

    row.update(
        {
            "track_id": _track_id(path, spc.sha256),
            "sha256": spc.sha256,
            "size": spc.size,
            "tag": spc.tag.to_dict(),
        }
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        log = tmp_dir / "writes.jsonl"
        wav = tmp_dir / "out.wav"
        try:
            result = subprocess.run(
                [
                    str(BINARY), str(path), str(log),
                    str(seconds), "--wav", str(wav),
                ],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            row["error"] = "spc_dump: timed out"
            return row
        if result.returncode != 0:
            row["error"] = f"spc_dump: {result.stderr.strip()[:200]}"
            return row
        if not log.is_file() or log.stat().st_size == 0:
            # A silent driver, or one that configures the DSP without the CPU
            # writing to it. Either way there is nothing to extract, and that
            # is a finding rather than a crash.
            row["error"] = "no DSP writes logged"
            return row

        # The snapshot's DSP block seeds the voice state. Without it, every
        # register the driver never rewrites reads as zero -- which was wrong
        # for 10.8% of corpus notes on SRCN alone, pitching them against the
        # wrong BRR sample. See voices.VoiceState.
        result_extract = extract(read_log(log), initial_dsp=spc.dsp)
        row["summary"] = result_extract.summary()

        # Milestone 3: absolute pitch, where it can be had. The PITCH register
        # is a resample ratio, so each sample's own fundamental is recovered
        # from the BRR data in ARAM and the note number follows. Samples whose
        # two estimators disagree are left without one -- a plausible wrong
        # pitch in a corpus is worse than a missing one.
        srcns = {n.srcn for n in result_extract.notes}
        entries = brr.read_directory(spc.aram, spc.dsp[0x5D], srcns)
        fundamentals: dict[int, Any] = {}
        for srcn, entry in entries.items():
            if not entry.plausible:
                continue
            decoded = brr.decode(spc.aram, entry.start, entry.loop)
            fundamentals[srcn] = pitch.estimate_f0(
                srcn, decoded.data, decoded.loop_offset
            )
        row["samples"] = {
            str(srcn): {**entry.__dict__, **fundamentals[srcn].to_dict()}
            for srcn, entry in entries.items()
            if srcn in fundamentals
        }

        notes_out = []
        for note in result_extract.notes:
            item = note.to_dict()
            estimate = fundamentals.get(note.srcn)
            usable = (
                estimate is not None
                and estimate.f0_hz
                and estimate.confidence in ("high", "medium")
                and note.pitch > 0
                and not note.noise
                and not note.pitch_modulated
            )
            if usable:
                hz, midi = pitch.note_for(note.pitch, estimate.f0_hz)
                item["hz"] = hz
                item["midi_note"] = midi
                item["pitch_confidence"] = estimate.confidence
            else:
                item["hz"] = None
                item["midi_note"] = None
                item["pitch_confidence"] = (
                    estimate.confidence if estimate else "none"
                )
            notes_out.append(item)
        row["notes"] = notes_out

        pitched = [n for n in notes_out if n["midi_note"] is not None]
        implausible = [
            n for n in pitched if not (12.0 <= n["midi_note"] <= 108.0)
        ]
        row["pitch"] = {
            "n_pitched": len(pitched),
            "n_unpitched": len(notes_out) - len(pitched),
            # Notes outside a musical register signal a residual OCTAVE error
            # in the fundamental: two estimators can agree and still both be
            # an octave out. Measured at 5.6% over the first 60 tracks.
            "n_implausible_register": len(implausible),
            "n_samples": len(entries),
            "n_samples_with_f0": sum(
                1 for f in fundamentals.values()
                if f.confidence in ("high", "medium")
            ),
        }

        # Milestone 4: the row grid, then the two timbre-free scores.
        #
        # The driver's tick period is nowhere in the SPC, so it is recovered
        # from the spacing of the key-ons themselves. A track whose onsets do
        # not lie on one period gets `found: false` and a reason rather than a
        # fabricated tempo -- a wrong grid would silently quantise the whole
        # score onto the wrong lattice.
        render_ticks = int(seconds * grid_mod.TICKS_PER_SECOND)
        onsets = grid_mod.onsets_from_notes(notes_out)

        # The driver's timer, from the write cadence rather than from key-ons.
        # This is the correction the first attempt needed: onsets are sparse
        # and gave 5.4 rows/s for Zelda against a real 62.5 Hz tick, wrong by
        # 11.6x. All DSP writes are one to two orders of magnitude denser and
        # carry the timer directly.
        driver_tick = tick_mod.infer(w["t"] for w in read_log(log))
        row["tick"] = driver_tick.to_dict()

        track_grid = grid_mod.infer(onsets, render_ticks=render_ticks)
        if track_grid.found and driver_tick.found:
            # Where the tick is trustworthy it is the better measurement, so
            # the row becomes a whole number of ticks -- then re-fitted, and
            # the snap is kept only if the grid still describes the music at
            # least as well.
            before_fit = track_grid.fit
            before_period = track_grid.period_ticks
            snapped = grid_mod.refit(
                grid_mod.snap_to_tick(track_grid, driver_tick.period_ticks),
                onsets, render_ticks,
            )
            if snapped.fit + 1e-9 < before_fit:
                snapped.period_ticks = before_period
                snapped.snapped_to_tick = False
                track_grid = grid_mod.refit(snapped, onsets, render_ticks)
            else:
                track_grid = snapped
        row["grid"] = track_grid.to_dict()
        # Was the onset grid consistent with the tick before snapping? The
        # ratio is the diagnostic that exposed the original error.
        row["grid"]["onset_grid_over_tick"] = (
            round(row["grid"]["period_ticks"] / driver_tick.period_ticks, 3)
            if driver_tick.found and driver_tick.period_ticks else None
        )

        track_scores = scores_mod.build(notes_out, track_grid, render_ticks)
        row["scores"] = track_scores.stats()
        if track_grid.found and track_scores.n_rows:
            scores_dir = out_dir / "scores"
            scores_dir.mkdir(parents=True, exist_ok=True)
            stem_scores = row["track_id"].replace(":", "_")
            score_path = scores_dir / f"{stem_scores}.json.gz"
            with gzip.open(score_path, "wt", encoding="utf-8") as handle:
                json.dump(
                    {
                        "track_id": row["track_id"],
                        "grid": row["grid"],
                        **track_scores.to_dict(),
                    },
                    handle,
                    separators=(",", ":"),
                )
            row["scores_path"] = f"scores/{score_path.name}"
            row["scores_bytes"] = score_path.stat().st_size

        peak: int | None = None
        try:
            peak = audio_peak(wav)
        except (ValueError, OSError) as error:
            row["audio_error"] = str(error)
        row["checks"] = run_checks(
            result_extract, render_seconds=seconds, peak=peak
        ).to_dict()

        # The reference artifact, and the analogue of NES-MDB's raw VGM: the
        # DSP write log, which is a register log rather than audio. Gzipped it
        # is ~1.1 MB a track against 7.7 MB for the WAV, and anyone can replay
        # it. Audio is regenerable from the SPC, so it stays opt-in.
        raw_dir = out_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        stem = row["track_id"].replace(":", "_")
        raw_path = raw_dir / f"{stem}.jsonl.gz"
        with log.open("rb") as src, gzip.open(raw_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        row["raw_path"] = f"raw/{raw_path.name}"
        row["raw_bytes"] = raw_path.stat().st_size

        if want_audio:
            audio_dir = out_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            kept = audio_dir / f"{stem}.wav"
            shutil.copyfile(wav, kept)
            row["audio_path"] = f"audio/{kept.name}"
            row["audio_bytes"] = kept.stat().st_size

    row["ok"] = True
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spc_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument(
        "--seconds", type=float, default=0.0,
        help="render length per track; 0 (default) uses each track's ID666 "
             "length, capped by --max-seconds",
    )
    parser.add_argument(
        "--max-seconds", type=float, default=720.0,
        help="cap when taking the length from ID666",
    )
    parser.add_argument(
        "--reference-audio", action="store_true",
        help="also keep the rendered WAV per track (~7.7 MB per 60 s)",
    )
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--valid-fraction", type=float, default=0.1)
    parser.add_argument("--test-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if not BINARY.is_file():
        raise SystemExit(f"{BINARY} is missing -- run `make` first")

    sources = sorted(
        p for p in args.spc_dir.rglob("*")
        if p.suffix.lower() in {".spc"} and p.is_file()
    )

    # Archives are NOT unpacked here, and silently ignoring them is how a
    # corpus ends up quietly missing most of its input: snesmusic.org ships
    # sets as .rsn (a renamed RAR), so a directory of downloads can look full
    # and contain zero usable files. Say so loudly instead.
    archives = sorted(
        p for p in args.spc_dir.rglob("*")
        if p.suffix.lower() in {".rsn", ".rar", ".zip", ".7z"} and p.is_file()
    )
    if archives:
        print(
            f"warning: {len(archives)} archive(s) found and SKIPPED "
            f"(e.g. {archives[0].name}). Unpack them to .spc first; see "
            f"data/spc/README.md.",
            file=sys.stderr,
        )
    if not sources:
        raise SystemExit(
            f"no .spc files under {args.spc_dir}"
            + (f" (but {len(archives)} archive(s) are present -- unpack them)"
               if archives else "")
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    records_dir = args.out_dir / "records"
    records_dir.mkdir(exist_ok=True)

    work = [
        (str(p), args.seconds, args.reference_audio,
         str(args.out_dir), args.max_seconds)
        for p in sources
    ]
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            rows = list(pool.map(process, work))
    else:
        rows = [process(item) for item in work]

    # Per-track records out of the manifest, so the manifest stays readable.
    manifest: list[dict[str, Any]] = []
    for row in rows:
        notes = row.pop("notes", None)
        if row.get("ok") and notes is not None:
            record = records_dir / f"{row['track_id'].replace(':', '_')}.json"
            record.write_text(json.dumps({**row, "notes": notes}, indent=1))
            row["record_path"] = f"records/{record.name}"
        manifest.append(row)

    # A commercial SPC set is not a song list. Label every track from
    # measurements already taken -- nothing is dropped, so aggregates can be
    # reported over everything AND over music only, and the denominator
    # survives.
    for row in manifest:
        if row.get("ok"):
            row.update(trackclass.classify(row).to_dict())

    good = [r for r in manifest if r.get("ok")]

    # Composer-disjoint splits over what actually extracted.
    tracks_by_game: dict[str, list[str]] = {}
    game_composers: dict[str, list[str]] = {}
    track_composers: dict[str, list[str]] = {}
    for row in good:
        tag = row["tag"]
        game = tag["game"] or f"unknown:{row['track_id']}"
        # Individual people, not the raw label: a field crediting
        # "Masanori Adachi, Taro Kudou" must link to a game crediting either
        # of them, or the disjointness check passes on a technicality.
        composers = tag.get("composers") or []
        tracks_by_game.setdefault(game, []).append(row["track_id"])
        game_composers.setdefault(game, [])
        for name in composers:
            if name not in game_composers[game]:
                game_composers[game].append(name)
        track_composers[row["track_id"]] = composers

    assigned = splits_mod.assign(
        tracks_by_game, game_composers,
        valid_fraction=args.valid_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    leaks = splits_mod.verify_disjoint(assigned.assignment, track_composers)
    for row in manifest:
        if row.get("ok"):
            row["split"] = assigned.assignment.get(row["track_id"])

    with (args.out_dir / "manifest.jsonl").open("w") as handle:
        for row in manifest:
            handle.write(json.dumps(row) + "\n")

    empty = [
        name for name, want in assigned.requested.items()
        if want > 0 and not assigned.counts.get(name)
    ]

    failures_by_check: dict[str, int] = {}
    for row in good:
        for name in row.get("checks", {}).get("failed", []):
            failures_by_check[name] = failures_by_check.get(name, 0) + 1

    # Why a grid was refused, counted. The reason strings carry the offending
    # numbers after a semicolon, so they are grouped on the part before it.
    grid_reasons: dict[str, int] = {}
    for row in good:
        info = row.get("grid", {})
        if info.get("found"):
            continue
        reason = info.get("reason", "?").split(";")[0]
        grid_reasons[reason] = grid_reasons.get(reason, 0) + 1
    grid_reasons = dict(sorted(grid_reasons.items(), key=lambda kv: -kv[1]))
    summary = {
        "n_sources": len(sources),
        "n_extracted": len(good),
        "n_failed": len(manifest) - len(good),
        "failures": sorted(
            {r.get("error", "?") .split(":")[0] for r in manifest if not r.get("ok")}
        ),
        "n_notes": sum(r["summary"]["n_notes"] for r in good),
        "n_notes_pitched": sum(r.get("pitch", {}).get("n_pitched", 0) for r in good),
        "n_notes_implausible_register": sum(
            r.get("pitch", {}).get("n_implausible_register", 0) for r in good
        ),
        "rendered_seconds_total": round(
            sum(r.get("render_seconds", 0.0) for r in good), 1
        ),
        "render_sources": {
            k: sum(1 for r in good if r.get("render_source") == k)
            for k in ("id666", "default", "requested")
        },
        "n_tracks_all_checks_passed": sum(
            1 for r in good if r.get("checks", {}).get("ok")
        ),
        "check_failures": dict(sorted(failures_by_check.items())),
        "track_classes": trackclass.census(good),
        # Milestone 4. A grid is reported per track with its fit, so the
        # corpus says how much of itself it has a tempo for rather than
        # claiming one everywhere.
        "grid": {
            "n_found": sum(1 for r in good if r.get("grid", {}).get("found")),
            "n_not_found": sum(
                1 for r in good if not r.get("grid", {}).get("found")
            ),
            "reasons": grid_reasons,
            "median_fit": round(_median([
                r["grid"]["fit"] for r in good if r.get("grid", {}).get("found")
            ]), 4),
            "median_rows_per_second": round(_median([
                r["grid"]["rows_per_second"]
                for r in good if r.get("grid", {}).get("found")
            ]), 3),
            "median_residual_fraction": round(_median([
                r["grid"]["median_abs_residual_fraction"]
                for r in good if r.get("grid", {}).get("found")
            ]), 4),
        },
        "tick": {
            "n_found": sum(1 for r in good if r.get("tick", {}).get("found")),
            "median_hz": round(_median([
                r["tick"]["hz"] for r in good if r.get("tick", {}).get("found")
            ]), 2),
            "median_sharpness": round(_median([
                r["tick"]["sharpness"] for r in good if r.get("tick", {}).get("found")
            ]), 3),
            # A tick is a property of the DRIVER, so every track in a game
            # should report the same one. The count of distinct values per game
            # is the real check on whether this is measuring the driver or
            # fitting noise, and it goes in the summary rather than being
            # left for a reader to work out.
            "distinct_hz_per_game": {},
        },
        "scores": {
            "n_tracks": sum(1 for r in good if r.get("scores_path")),
            "n_rows_total": sum(r.get("scores", {}).get("n_rows", 0) for r in good),
            "n_notes_represented": sum(
                r.get("scores", {}).get("n_notes_represented", 0) for r in good
            ),
            "n_notes_unpitched": sum(
                r.get("scores", {}).get("n_notes_unpitched", 0) for r in good
            ),
            "n_notes_out_of_range": sum(
                r.get("scores", {}).get("n_notes_out_of_range", 0) for r in good
            ),
            "n_notes_snapped": sum(
                r.get("scores", {}).get("n_notes_snapped", 0) for r in good
            ),
            "n_notes_unplaced": sum(
                r.get("scores", {}).get("n_notes_unplaced", 0) for r in good
            ),
            "max_polyphony": max(
                (r.get("scores", {}).get("max_polyphony", 0) for r in good),
                default=0,
            ),
        },
        "splits": assigned.report(),
        "composer_leaks": leaks,
        # Names cut off at ID666's 32-byte limit: the last credit in such a
        # field is unrecoverable, so any link made through it is a guess.
        "tracks_with_truncated_composer": sorted(
            r["track_id"] for r in good if r["tag"].get("composer_truncated")
        ),
        # A corpus with an empty requested split is unusable for the purpose
        # the split exists for. Expected on a tiny corpus, where there are
        # fewer composer components than splits; a real finding on a large one.
        "empty_splits": empty,
    }
    per_game: dict[str, set[float]] = {}
    for row in good:
        info = row.get("tick", {})
        if not info.get("found"):
            continue
        name = row["tag"]["game"] or "?"
        per_game.setdefault(name, set()).add(round(info["hz"], 1))
    summary["tick"]["distinct_hz_per_game"] = {
        name: {"n_distinct": len(values), "hz": sorted(values)[:6]}
        for name, values in sorted(per_game.items())
    }

    (args.out_dir / "splits.json").write_text(
        json.dumps({"assignment": assigned.assignment, **assigned.report()}, indent=1)
    )
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    if leaks:
        raise SystemExit(
            f"composer-disjointness VIOLATED for {len(leaks)} composers; "
            "the corpus is not comparable to NES-MDB until this is fixed"
        )


if __name__ == "__main__":
    main()
