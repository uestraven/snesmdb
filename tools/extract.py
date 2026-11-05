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
from snesmdb.checks import audio_peak, run as run_checks  # noqa: E402
from snesmdb.voices import extract, read_log  # noqa: E402

BINARY = Path(__file__).resolve().parent.parent / "build" / "spc_dump"


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

        result_extract = extract(read_log(log))
        row["summary"] = result_extract.summary()
        row["notes"] = [note.to_dict() for note in result_extract.notes]

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
    summary = {
        "n_sources": len(sources),
        "n_extracted": len(good),
        "n_failed": len(manifest) - len(good),
        "failures": sorted(
            {r.get("error", "?") .split(":")[0] for r in manifest if not r.get("ok")}
        ),
        "n_notes": sum(r["summary"]["n_notes"] for r in good),
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
