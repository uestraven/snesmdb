#!/usr/bin/env python3
"""Fail loudly on the defects this pipeline has actually shipped.

    verify_corpus.py <out-dir> [dist-dir]

Every check here corresponds to something that really went wrong and was
caught by hand, late, or by accident. The point is that none of them can ship
again silently -- which is the shared property of all of them. Not one
announced itself; each was found by reading output that looked fine.

    the rebuild recipe omitted the clock-deriving pass, so publish found
    no clock and wrote no scores, without erroring -> clock_on_every_track
    publish keyed on row["grid"] and would have
    shipped 866 of 1,316 tracks                    -> scores_cover_corpus
    summary.json headlined the onset grid's 866
    as the timing statistic                        -> summary_not_stale
    voice state was not seeded from the SPC, so
    10.8% of notes carried the wrong sample        -> srcn_not_degenerate
    blended polyphony reached 9 on 8-voice
    hardware                                       -> polyphony_within_hardware
    legato steps referenced parent notes that
    did not exist                                  -> legato_parents_resolve
    note_id was never published, so the parent
    link was unresolvable on disk                  -> legato_parents_resolve
    nothing recorded what produced a tree          -> provenance_recorded

Exit code is the number of failed checks, so `make` stops on any of them.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import sys
from pathlib import Path
from typing import Any, Callable

#: The S-DSP has eight voices. Anything above this is arithmetically impossible
#: and means the note model is double-counting.
N_VOICES = 8

#: Above this share of notes reporting sample 0, the voice state is probably
#: not being seeded from the SPC's DSP block. The real figure is 2.8%; it was
#: 10.8% before the fix.
MAX_SRCN_ZERO_FRACTION = 0.06


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes: list[str] = []

    def check(self, name: str, ok: bool, detail: str) -> None:
        if ok:
            self.passes.append(f"  ok      {name}: {detail}")
        else:
            self.failures.append(f"  FAILED  {name}: {detail}")


def _rows(out_dir: Path) -> list[dict[str, Any]]:
    path = out_dir / "manifest.jsonl"
    if not path.is_file():
        raise SystemExit(f"no manifest at {path}")
    return [json.loads(line) for line in path.open()]


def check_out_dir(out_dir: Path, report: Report) -> None:
    rows = _rows(out_dir)
    good = [r for r in rows if r.get("ok")]

    # The defect the broken rebuild recipe produced.
    clocked = [r for r in good if (r.get("clock") or {}).get("period_ticks")]
    report.check(
        "clock_on_every_track",
        len(clocked) == len(good) and bool(good),
        f"{len(clocked)}/{len(good)} tracks carry a row clock"
        + ("" if len(clocked) == len(good) else
           " -- extraction did not decide a clock for every track"),
    )

    scored = [r for r in good if (r.get("scores") or {}).get("n_rows")]
    report.check(
        "scores_cover_corpus",
        len(scored) == len(good),
        f"{len(scored)}/{len(good)} tracks have row scores",
    )

    poly = [
        int((r.get("scores") or {}).get("max_polyphony") or 0) for r in good
    ]
    worst = max(poly) if poly else 0
    report.check(
        "polyphony_within_hardware",
        worst <= N_VOICES,
        f"max polyphony {worst} against {N_VOICES} voices",
    )

    unhandled: dict[str, int] = {}
    for row in good:
        for name, count in ((row.get("summary") or {})
                            .get("unhandled_writes") or {}).items():
            unhandled[name] = unhandled.get(name, 0) + count
    report.check(
        "no_unhandled_dsp_registers",
        not unhandled,
        "none" if not unhandled else f"{unhandled}",
    )

    summary_path = out_dir / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text())
        report.check(
            "summary_not_stale",
            "grid" not in summary and "clock" in summary,
            "has a clock block and no bare `grid` key"
            if "grid" not in summary and "clock" in summary
            else "still headlines the onset grid as the timing statistic",
        )
        report.check(
            "provenance_recorded",
            bool(summary.get("provenance") or summary.get("provenance_reclock")),
            "present" if summary.get("provenance")
            or summary.get("provenance_reclock") else "absent",
        )


def check_records(out_dir: Path, report: Report, limit: int) -> None:
    """Per-track record checks, on a sample so `make` stays quick."""
    rows = [r for r in _rows(out_dir) if r.get("ok") and r.get("record_path")]
    sample = rows[:: max(1, len(rows) // limit)] if rows else []
    notes = zeros = orphans = steps = 0
    for row in sample:
        record = json.loads((out_dir / row["record_path"]).read_text())
        ids = {n.get("note_id") for n in record.get("notes") or []}
        for note in record.get("notes") or []:
            notes += 1
            if int(note.get("srcn") or 0) == 0:
                zeros += 1
        for step in record.get("legato_steps") or []:
            steps += 1
            if step.get("parent_note_id") not in ids:
                orphans += 1
    if not notes:
        return
    fraction = zeros / notes
    report.check(
        "srcn_not_degenerate",
        fraction <= MAX_SRCN_ZERO_FRACTION,
        f"{fraction:.1%} of sampled notes report sample 0"
        f" (limit {MAX_SRCN_ZERO_FRACTION:.0%})",
    )
    report.check(
        "legato_parents_resolve",
        orphans == 0,
        f"{steps} steps sampled, {orphans} with an unresolvable parent",
    )


def check_dist(dist_dir: Path, report: Report) -> None:
    index_path = dist_dir / "index.json"
    if not index_path.is_file():
        report.check("dist_index", False, f"no index.json in {dist_dir}")
        return
    index = json.loads(index_path.read_text())
    report.check(
        "dist_scores_cover_index",
        all(e.get("scores") for e in index) and bool(index),
        f"{sum(1 for e in index if e.get('scores'))}/{len(index)} entries "
        f"have a score file",
    )
    report.check(
        "dist_provenance",
        (dist_dir / "provenance.json").is_file(),
        "provenance.json present"
        if (dist_dir / "provenance.json").is_file() else "absent",
    )

    # The licence constraint: SPCs are research-only and nothing derived from
    # them may ship as audio.
    leaked = [
        p for p in glob.glob(str(dist_dir / "**" / "*"), recursive=True)
        if p.endswith((".spc", ".wav", ".flac", ".mp3", ".ogg", ".rsn"))
    ]
    report.check(
        "no_audio_or_spc_in_dist",
        not leaked,
        "none" if not leaked else f"{len(leaked)} leaked: {leaked[:3]}",
    )

    # A published score must be clocked and must carry all four expressive
    # channels, checked on a sample rather than all 1,316.
    sampled = index[:: max(1, len(index) // 25)]
    bad_clock = bad_channels = 0
    for entry in sampled:
        if not entry.get("scores"):
            continue
        path = dist_dir / entry["scores"]
        if not path.is_file():
            bad_clock += 1
            continue
        with gzip.open(path, "rt") as handle:
            payload = json.load(handle)
        if not (payload.get("clock") or {}).get("period_ticks"):
            bad_clock += 1
        channels = (payload.get("expressive") or {}).get("channels")
        if channels != ["note", "velocity", "timbre_class", "sustain"]:
            bad_channels += 1
    report.check(
        "dist_scores_clocked",
        bad_clock == 0,
        f"{len(sampled)} sampled, {bad_clock} without a usable clock",
    )
    report.check(
        "dist_expressive_channels",
        bad_channels == 0,
        f"{len(sampled)} sampled, {bad_channels} with unexpected channels",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("dist_dir", type=Path, nargs="?")
    parser.add_argument("--sample", type=int, default=60)
    args = parser.parse_args()

    report = Report()
    check_out_dir(args.out_dir, report)
    check_records(args.out_dir, report, args.sample)
    if args.dist_dir and args.dist_dir.exists():
        check_dist(args.dist_dir, report)
    elif args.dist_dir:
        report.check("dist_present", False, f"{args.dist_dir} does not exist")

    for line in report.passes:
        print(line)
    for line in report.failures:
        print(line, file=sys.stderr)
    print(
        f"\n{len(report.passes)} passed, {len(report.failures)} failed",
        file=sys.stderr if report.failures else sys.stdout,
    )
    raise SystemExit(len(report.failures))


if __name__ == "__main__":
    main()
