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
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import splits as splits_mod  # noqa: E402
from snesmdb.spcfile import SpcError, load  # noqa: E402
from snesmdb.validate import validate_wav  # noqa: E402
from snesmdb.voices import extract, read_log  # noqa: E402

BINARY = Path(__file__).resolve().parent.parent / "build" / "spc_dump"


def _track_id(path: Path, sha: str) -> str:
    return f"{path.stem}:{sha[:12]}"


def process(args: tuple[str, float, bool]) -> dict[str, Any]:
    """Extract one SPC. Returns a manifest row, successful or not."""
    path_str, seconds, keep_wav = args
    path = Path(path_str)
    row: dict[str, Any] = {"source": path.name, "ok": False}

    try:
        spc = load(path)
    except (SpcError, OSError) as error:
        row["error"] = f"load: {error}"
        return row

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

        try:
            validation = validate_wav(
                [n.start for n in result_extract.notes], wav
            )
            row["validation"] = validation.to_dict()
        except (ValueError, OSError) as error:
            row["validation"] = {"error": str(error)}

        if keep_wav:
            row["wav_bytes"] = wav.stat().st_size

    row["ok"] = True
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spc_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--keep-wav", action="store_true")
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
    if not sources:
        raise SystemExit(f"no .spc files under {args.spc_dir}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    records_dir = args.out_dir / "records"
    records_dir.mkdir(exist_ok=True)

    work = [(str(p), args.seconds, args.keep_wav) for p in sources]
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
        composer = tag["composer"]
        composers = [composer] if composer else []
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

    scores = [
        r["validation"]["score"] for r in good
        if isinstance(r.get("validation"), dict) and "score" in r["validation"]
    ]
    summary = {
        "n_sources": len(sources),
        "n_extracted": len(good),
        "n_failed": len(manifest) - len(good),
        "failures": sorted(
            {r.get("error", "?") .split(":")[0] for r in manifest if not r.get("ok")}
        ),
        "n_notes": sum(r["summary"]["n_notes"] for r in good),
        "validation_score_mean": (sum(scores) / len(scores)) if scores else None,
        "validation_score_min": min(scores) if scores else None,
        "splits": assigned.report(),
        "composer_leaks": leaks,
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
