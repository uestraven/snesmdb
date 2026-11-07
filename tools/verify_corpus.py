#!/usr/bin/env python3
"""Fail loudly on the defects this pipeline has actually shipped.

    verify_corpus.py <out-dir> [dist-dir]

Every check here corresponds to something that really went wrong and was
caught by hand, late, or by accident. The point is that none of them can ship
again silently -- which is the shared property of all of them. Not one
announced itself; each was found by reading output that looked fine.

    the rebuild recipe omitted the clock-deriving pass, so publish found
    no clock and wrote no scores, without erroring -> clock_on_every_track
    the 100 Hz grid was benchmarked at length and
    publish.py never learned about it             -> dist_uniform_present
    405,288 events arrived as `midi_note: null`
    with no reason given                          -> dist_events_pitch_explained
    73 unpitched tracks were indistinguishable
    from failed extractions                       -> dist_events_status_consistent
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
    a coarse uniform rate would silently rewrite
    tremolos as sustained notes                    -> uniform_grid_preserves_events

Exit code is the number of failed checks, so `make` stops on any of them.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import events as events_mod, scores as scores_mod  # noqa: E402

#: The S-DSP has eight voices. Anything above this is arithmetically impossible
#: and means the note model is double-counting.
N_VOICES = 8

#: The uniform score's event-preservation claim, re-checked on real data every
#: rebuild so it cannot rot into a figure that was true once. Measured at 100
#: Hz over the whole corpus: 1 lost repeated attack in 1,458,211 pitched notes.
#: The bound is deliberately loose enough to survive a corpus change and tight
#: enough that a rate change or a merge-behaviour regression trips it.
MAX_UNIFORM_EVENTS_LOST = 50

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
            bool(summary.get("provenance")),
            "present" if summary.get("provenance") else "absent",
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


def check_uniform_preservation(out_dir: Path, report: Report, limit: int) -> None:
    """Does the uniform grid still lose almost no note events?

    The rate was chosen on this measurement, so it is checked rather than
    trusted. A coarser rate, or a change to how `scores.build` merges onsets,
    would show up here as lost repeated attacks -- a tremolo rewritten as one
    sustained note, which nothing downstream would notice.
    """
    rows = [r for r in _rows(out_dir) if r.get("ok") and r.get("record_path")]
    if not rows:
        return
    step = max(1, len(rows) // limit)
    period = 1_024_000 / scores_mod.UNIFORM_HZ
    notes = lost = 0
    for row in rows[::step]:
        record = json.loads((out_dir / row["record_path"]).read_text())
        seen: dict[tuple[int, int], int] = {}
        for note in record.get("notes") or []:
            if note.get("midi_note") is None:
                continue
            notes += 1
            key = (int(note["voice"]), round(note["start"] / period))
            if key in seen:
                lost += 1
            else:
                seen[key] = note["midi_note"]
    if not notes:
        return
    report.check(
        "uniform_grid_preserves_events",
        lost <= MAX_UNIFORM_EVENTS_LOST,
        f"{lost} of {notes:,} sampled pitched notes lost at "
        f"{scores_mod.UNIFORM_HZ:g} Hz (limit {MAX_UNIFORM_EVENTS_LOST})",
    )


def check_events(dist_dir: Path, report: Report, exhaustive: bool) -> None:
    """The events.v1 contract, over the published tables.

    Sampled for a build gate, exhaustive for a release -- and sample_id
    uniqueness is only meaningful exhaustively, since a collision between two
    tracks outside the sample is exactly the case that would corrupt a join
    and never be seen.
    """
    index_path = dist_dir / "index.json"
    if not index_path.is_file():
        return
    raw = json.loads(index_path.read_text())
    entries = raw if isinstance(raw, list) else raw.get("tracks", [])
    with_events = [e for e in entries if e.get("events")]
    report.check(
        "dist_events_present",
        len(with_events) == len(entries) and bool(entries),
        f"{len(with_events)}/{len(entries)} tracks have an event table",
    )
    if not with_events:
        return

    chosen = with_events if exhaustive else with_events[
        :: max(1, len(with_events) // 25)
    ]
    bad_status = bad_pitch = bad_counts = 0
    ids: dict[str, str] = {}
    statuses: dict[str, int] = {}
    for entry in chosen:
        path = dist_dir / entry["events"]
        if not path.is_file():
            bad_counts += 1
            continue
        with gzip.open(path, "rt") as handle:
            table = json.load(handle)
        if table.get("schema") != events_mod.SCHEMA:
            bad_status += 1
        status = table.get("extraction_status")
        statuses[status] = statuses.get(status, 0) + 1
        if status not in events_mod.EXTRACTION_STATES:
            bad_status += 1
        evs = table.get("events") or []
        pitched = sum(
            1 for e in evs if e.get("pitch_status") == events_mod.PITCH_ESTIMATED
        )
        attacks = sum(
            1 for e in evs if e.get("origin") == events_mod.ORIGIN_KEY_ON
        )
        if (
            table.get("event_count") != len(evs)
            or table.get("pitched_event_count") != pitched
            or table.get("unpitched_event_count") != len(evs) - pitched
            or table.get("attack_count") != attacks
        ):
            bad_counts += 1
        # A status that contradicts the counts is the misclassification this
        # schema exists to prevent.
        if events_mod.extraction_status(True, len(evs), pitched) != status:
            bad_status += 1
        for event in evs:
            if event.get("pitch_status") not in events_mod.PITCH_STATES:
                bad_pitch += 1
            elif (
                (event["pitch_status"] == events_mod.PITCH_ESTIMATED)
                != (event.get("midi_note") is not None)
            ):
                bad_pitch += 1
            sid = event.get("sample_id")
            if sid:
                ids.setdefault(sid, entry["track_id"])

    report.check(
        "dist_events_status_consistent",
        bad_status == 0,
        f"{len(chosen)} tables, {bad_status} whose schema or "
        f"extraction_status is invalid or contradicts its own counts",
    )
    report.check(
        "dist_events_pitch_explained",
        bad_pitch == 0,
        f"{len(chosen)} tables, {bad_pitch} events whose pitch_status is "
        f"invalid or disagrees with whether a pitch is present",
    )
    report.check(
        "dist_events_counts_reconcile",
        bad_counts == 0,
        f"{len(chosen)} tables, {bad_counts} whose header counts disagree "
        f"with the event list",
    )
    report.check(
        "dist_sample_ids_plausible",
        len(ids) > 100,
        f"{len(ids)} distinct sample ids across {len(chosen)} tables"
        + ("" if exhaustive else " (sampled; run --exhaustive for uniqueness)"),
    )
    if exhaustive:
        report.check(
            "dist_event_status_census",
            sum(statuses.values()) == len(chosen),
            ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())),
        )


def check_dist(dist_dir: Path, report: Report, exhaustive: bool = False) -> None:
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

    # THE UNIFORM SCORE MUST BE PRESENT IN THE PUBLISHED TREE, with contents
    # matching the extraction output. `uniform_grid_preserves_events` above
    # recomputes 100 Hz positions from the note records, so it passes whether
    # or not a uniform score was ever written -- which it was not, for the
    # whole period the rate was being benchmarked. A gate that cannot detect
    # the absence of the thing it is about is decoration.
    # SAMPLED BY DEFAULT, EXHAUSTIVE FOR A RELEASE. 26 of 1,316 gives about a
    # 2% chance of catching one corrupted file, which is fine for a fast gate
    # on every build and not fine for a release audit -- an isolated bad
    # artifact outside the sample escapes entirely. `--exhaustive` opens all
    # of them.
    sampled = index if exhaustive else index[:: max(1, len(index) // 25)]
    bad_clock = bad_channels = no_uniform = bad_uniform = 0
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
        uniform = payload.get("uniform")
        if not uniform or not uniform.get("n_rows"):
            no_uniform += 1
            continue
        # Shape and rate, so a present-but-wrong block cannot pass.
        expected_rows = int(
            float(entry.get("render_seconds") or 0.0) * scores_mod.UNIFORM_HZ
        ) + 1
        if (
            abs(float(uniform.get("hz") or 0) - scores_mod.UNIFORM_HZ) > 0.01
            or round(float(uniform.get("period_ticks") or 0)) != 10_240
            or abs(int(uniform["n_rows"]) - expected_rows) > 1
            or len(uniform.get("separated") or []) != 8
            or len(uniform.get("blended") or []) != int(uniform["n_rows"])
        ):
            bad_uniform += 1
    report.check(
        "dist_scores_clocked",
        bad_clock == 0,
        f"{len(sampled)} sampled, {bad_clock} without a usable clock",
    )
    report.check(
        "dist_uniform_present",
        no_uniform == 0,
        f"{len(sampled)} sampled, {no_uniform} with no uniform score"
        + ("" if no_uniform == 0 else " -- the 100 Hz grid did not reach dist"),
    )
    report.check(
        "dist_uniform_wellformed",
        bad_uniform == 0,
        f"{len(sampled)} sampled, {bad_uniform} whose uniform block has the "
        f"wrong rate, period, row count or shape",
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
    parser.add_argument(
        "--exhaustive", action="store_true",
        help="open EVERY published score rather than a sample. Slower, and "
             "the only mode that catches a single corrupted artifact. Use it "
             "for a release audit; the sampled default is the build gate.",
    )
    args = parser.parse_args()

    report = Report()
    check_out_dir(args.out_dir, report)
    check_records(args.out_dir, report, args.sample)
    check_uniform_preservation(args.out_dir, report, args.sample * 4)
    if args.dist_dir and args.dist_dir.exists():
        check_dist(args.dist_dir, report, exhaustive=args.exhaustive)
        check_events(args.dist_dir, report, exhaustive=args.exhaustive)
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
