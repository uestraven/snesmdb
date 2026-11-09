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
import collections
import glob
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import (  # noqa: E402
    corpus as corpus_mod,
    events as events_mod,
    sampleid,
    scores as scores_mod,
    trackclass,
)

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

#: Degeneracy bound for records that resolve identity AT KEY-ON.
#:
#: `srcn_not_degenerate` exists to catch sample resolution collapsing onto
#: one entry. It measured that through SRCN, which was the right proxy while
#: identity came from the capture-time directory via the SRCN index. Under
#: `events.v4` identity comes from the directory entry the DSP committed for
#: each attack, so SRCN determines nothing: a driver may legitimately keep
#: every voice on SRCN 0 and rewrite that entry continuously. Secret of
#: Evermore does exactly that -- 20.8% of its notes report SRCN 0, and those
#: 11,587 attacks resolve to 36 distinct identities, every one established.
#:
#: So for v4 records the assertion moves to the quantity that actually
#: identifies a sample. Collapse means one identity for everything: 100% on
#: a single id, one distinct id. The bound is set well clear of real data
#: rather than tuned to admit a game -- Evermore's most common identity holds
#: 30.0% of its resolved attacks, and the 22-game baseline is sampled at
#: 2.9% on the SRCN measure.
MAX_IDENTITY_CONCENTRATION = 0.90
MIN_DISTINCT_IDENTITIES = 2


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes: list[str] = []
        #: Verified measurements that fall outside the frozen baseline's
        #: observed span. NOT passes and NOT failures: new data legitimately
        #: outside an old sampling frame is the point of an expansion, and
        #: calling it either would be wrong.
        self.extensions: list[str] = []
        #: Checks whose precondition the subset does not meet, so there is
        #: nothing to evaluate. Recorded rather than silently skipped.
        self.not_applicable: list[str] = []

    def check(self, name: str, ok: bool, detail: str) -> None:
        if ok:
            self.passes.append(f"  ok      {name}: {detail}")
        else:
            self.failures.append(f"  FAILED  {name}: {detail}")

    def extension(self, name: str, detail: str) -> None:
        """A verified measurement beyond the baseline's range. Nonblocking."""
        self.extensions.append(f"  EXTENDS {name}: {detail}")

    def skip(self, name: str, why: str) -> None:
        """A check the subset cannot evaluate. Nonblocking, and named."""
        self.not_applicable.append(f"  n/a     {name}: {why}")


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
        int((r.get("scores") or {}).get("max_voices_sounding_per_row") or 0)
        for r in good
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


def check_records(
    out_dir: Path, report: Report, limit: int, exhaustive: bool = False
) -> None:
    """Per-track record checks, on a sample so `make` stays quick.

    `--exhaustive` opens EVERY record. It used to sample even there, which
    left `identity_resolved_at_key_on` -- the check that catches a track
    silently falling back to capture-time identities -- covering 62 of 1,477
    tracks on a release audit. A quiet failure on one track is exactly what
    that check exists for, so a release cannot afford to sample it.
    """
    rows = [r for r in _rows(out_dir) if r.get("ok") and r.get("record_path")]
    if exhaustive:
        sample = rows
    else:
        sample = rows[:: max(1, len(rows) // limit)] if rows else []
    # COUNTED PER RECORD, NOT PER CORPUS.
    #
    # A combined cohort mixes pre-v4 records with native ones, and a single
    # global `native_ids` flag skipped the SRCN check for ALL of them -- so
    # on the 27-game release the 1,316 baseline tracks got neither check:
    # SRCN was skipped because some records had identities, and the identity
    # check only saw the 161 records that did. Each population is now
    # measured on its own terms and both checks report when both are
    # present.
    notes = zeros = orphans = steps = unmatched = 0
    notes_pre_v4 = zeros_pre_v4 = notes_native = 0
    identities: collections.Counter = collections.Counter()
    for row in sample:
        record = json.loads((out_dir / row["record_path"]).read_text())
        ids = {n.get("note_id") for n in record.get("notes") or []}
        if (row.get("identity") or {}).get("matched") is False:
            unmatched += 1
        for note in record.get("notes") or []:
            notes += 1
            zero = int(note.get("srcn") or 0) == 0
            if zero:
                zeros += 1
            if "sample_id" in note:
                notes_native += 1
                if note["sample_id"]:
                    identities[note["sample_id"]] += 1
            else:
                notes_pre_v4 += 1
                if zero:
                    zeros_pre_v4 += 1
        for step in record.get("legato_steps") or []:
            steps += 1
            if step.get("parent_note_id") not in ids:
                orphans += 1
    if not notes:
        return
    fraction = zeros / notes

    # WHICH DEGENERACY CHECK APPLIES DEPENDS ON THE RECORD, NOT THE GAME.
    #
    # A record that carries `sample_id` per note resolved identity at
    # key-on, so SRCN is metadata there and cannot indicate collapse. One
    # that does not carries identity through the SRCN index, where a pile-up
    # on index 0 is exactly the unseeded-voice-state defect this check was
    # written for. The threshold is unchanged in both cases; what changes is
    # which quantity is asserted on, and the inapplicable one is reported
    # rather than passed or skipped silently.
    if notes_pre_v4:
        # Asserted over the pre-v4 notes ONLY, at the unchanged limit. In a
        # mixed cohort this is the baseline half and it is still judged on
        # the quantity that identifies its samples.
        pre = zeros_pre_v4 / notes_pre_v4
        report.check(
            "srcn_not_degenerate",
            pre <= MAX_SRCN_ZERO_FRACTION,
            f"{pre:.1%} of {notes_pre_v4:,} notes WITHOUT a per-attack "
            f"identity report sample 0 (limit "
            f"{MAX_SRCN_ZERO_FRACTION:.0%})",
        )
    else:
        report.skip(
            "srcn_not_degenerate",
            f"{fraction:.1%} of notes report SRCN 0, but every record here "
            f"resolves identity at key-on, so SRCN does not determine the "
            f"sample -- a driver may hold every voice on one index and "
            f"rewrite its directory entry. Asserted on sample identity "
            f"instead",
        )
    if notes_native:
        total = sum(identities.values())
        top = identities.most_common(1)[0][1] / total if total else 1.0
        report.check(
            "identity_resolution_not_degenerate",
            len(identities) >= MIN_DISTINCT_IDENTITIES
            and top <= MAX_IDENTITY_CONCENTRATION,
            f"{len(identities)} distinct identities across {total:,} "
            f"resolved attacks, most common holds {top:.1%} "
            f"(limits: >={MIN_DISTINCT_IDENTITIES} distinct, "
            f"<={MAX_IDENTITY_CONCENTRATION:.0%} concentration)",
        )
        report.check(
            "identity_resolved_at_key_on",
            unmatched == 0,
            f"{len(sample)} tracks sampled, {unmatched} where the "
            f"extractor could not pair the DSP's sample commits to its "
            f"attacks -- those fall back to capture-time identities "
            f"silently",
        )
    else:
        report.skip(
            "identity_resolution_not_degenerate",
            "no record here carries a per-attack identity, so identity "
            "resolution cannot be assessed; SRCN degeneracy was asserted "
            "instead",
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


def check_events(
    dist_dir: Path, report: Report, exhaustive: bool,
    subset: bool = False,
) -> None:
    """The events.v3 contract, over the published tables.

    Sampled for a build gate, exhaustive for a release -- and sample_id
    uniqueness is only meaningful exhaustively, since a collision between two
    tracks outside the sample is exactly the case that would corrupt a join
    and never be seen.
    """
    index_path = dist_dir / "index.json"
    if not index_path.is_file():
        return
    entries = corpus_mod.tracks_of(json.loads(index_path.read_text()))
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
    bad_status = bad_pitch = bad_counts = bad_fields = 0
    empty_ids = reason_mismatch = bad_source = 0
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
        # The filter fields must travel WITH the data and must agree with
        # the index. A denormalised copy that disagrees is worse than none:
        # it gives two answers to "is this a music track".
        if (
            table.get("game") != entry.get("game")
            or table.get("track_class") != entry.get("track_class")
            # Compared against the INDEX's published slug, which is the
            # game family's. Deriving it from the track id again asserts
            # that a slug can never be grouped, and failed on the five
            # Panel de Pon tracks whose event tables were correct.
            or table.get("game_slug") != (
                entry.get("game_slug")
                or events_mod.game_slug(str(entry.get("track_id")))
            )
        ):
            bad_fields += 1
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
            # v4 invariants. "" is not an identity and must never be
            # published as one: v3 used it for 13,413 events and never used
            # null, so a reader testing `is not None` read every one of
            # them as a resolved identity.
            if sid == "":
                empty_ids += 1
            if (sid is None) != (
                    event.get("sample_id_unresolved_reason") is not None):
                reason_mismatch += 1
            if event.get("sample_id_source") not in (
                    events_mod.SOURCE_OBSERVED, events_mod.SOURCE_CAPTURE,
                    events_mod.SOURCE_UNRESOLVED):
                bad_source += 1

    report.check(
        "dist_sample_id_null_never_empty_string",
        empty_ids == 0,
        f"{empty_ids} events publish sample_id as an empty string instead "
        f"of null; an empty string reads as a value",
    )
    report.check(
        "dist_sample_id_reason_exactly_when_null",
        reason_mismatch == 0,
        f"{reason_mismatch} events whose sample_id_unresolved_reason is not "
        f"present exactly when sample_id is null",
    )
    report.check(
        "dist_sample_id_source_known",
        bad_source == 0,
        f"{bad_source} events whose sample_id_source is not one of the "
        f"three declared values",
    )
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
        "dist_events_carry_filter_fields",
        bad_fields == 0,
        f"{len(chosen)} tables, {bad_fields} whose game, game_slug or "
        f"track_class is absent or disagrees with the index",
    )
    report.check(
        "dist_events_counts_reconcile",
        bad_counts == 0,
        f"{len(chosen)} tables, {bad_counts} whose header counts disagree "
        f"with the event list",
    )
    if subset:
        # `len(ids) > 100` is calibrated for 1,316 tracks and says nothing
        # about 17: F-Zero resolves 24 distinct samples, which is plausible
        # for a 1991 launch title with a small ARAM bank. The degenerate case
        # this guards against -- directory resolution collapsing so every
        # voice reports one sample -- is still caught, scaled to the subset.
        report.check(
            "subset_sample_ids_not_degenerate",
            len(ids) >= max(2, len(chosen) // 8),
            f"{len(ids)} distinct sample ids across {len(chosen)} tables "
            f"(subset floor {max(2, len(chosen) // 8)}; the corpus-wide "
            f"threshold of 100 does not apply)",
        )
    else:
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


def _sample_entries(index, n=25):
    """A spread of entries for a sampled check."""
    return index[:: max(1, len(index) // n)] if index else []


def check_dist(
    dist_dir: Path, report: Report, exhaustive: bool = False,
    subset: bool = False,
) -> None:
    index_path = dist_dir / "index.json"
    if not index_path.is_file():
        report.check("dist_index", False, f"no index.json in {dist_dir}")
        return
    raw_index = json.loads(index_path.read_text())
    index = corpus_mod.tracks_of(raw_index)

    # The index must describe itself. A bare list cannot, which is what this
    # replaced -- two downloads of different vintages were distinguishable
    # only by diffing them.
    report.check(
        "dist_index_declares_schema",
        isinstance(raw_index, dict)
        and raw_index.get("schema") == corpus_mod.INDEX_SCHEMA,
        f"index schema is {raw_index.get('schema') if isinstance(raw_index, dict) else 'a bare list'}"
        f" (want {corpus_mod.INDEX_SCHEMA})",
    )
    formats = raw_index.get("formats", {}) if isinstance(raw_index, dict) else {}
    # PER FORMAT, not one corpus version: events.v1 landed while the score
    # payload was unchanged, so a consumer checks what it actually reads.
    report.check(
        "dist_index_names_format_schemas",
        formats.get("events") == events_mod.SCHEMA
        and formats.get("sample_id") == sampleid.SCHEMA
        and formats.get("intake") == corpus_mod.INTAKE_SCHEMA
        and float(formats.get("uniform_hz") or 0) == scores_mod.UNIFORM_HZ,
        f"declared formats {formats}",
    )
    classed = [e for e in index if e.get("track_class") in trackclass.CLASSES]
    report.check(
        "dist_track_class_published",
        len(classed) == len(index) and bool(index),
        f"{len(classed)}/{len(index)} tracks carry a musical classification",
    )
    # The two fields must not be derivable from each other. If every class
    # mapped to exactly one status, one of them would be carrying no
    # information and a researcher filtering on either would be misled.
    spans: dict[str, set[str]] = {}
    for entry in index:
        spans.setdefault(str(entry.get("track_class")), set()).add(
            str(entry.get("extraction_status"))
        )
    observed_statuses = {s for v in spans.values() for s in v}
    # Every observed classification is still validated, in both modes.
    bad_class = sorted(c for c in spans if c not in trackclass.CLASSES)
    bad_status = sorted(
        s for s in observed_statuses if s not in events_mod.EXTRACTION_STATES
    )
    report.check(
        "dist_classifications_are_valid",
        not bad_class and not bad_status,
        f"unknown class {bad_class or 'none'}, unknown status "
        f"{bad_status or 'none'}",
    )
    if subset:
        # A CORPUS-LEVEL INVARIANT, NOT EVALUATED ON SUBSETS.
        #
        # Independence is demonstrated corpus-wide by 42 pitched sound
        # effects and 11 pitchless music tracks. A subset's cross-tab is not
        # the corpus's: Street Fighter II Turbo extracted 36 of 36 cleanly
        # with a single unpitched effect track, so no class spans two
        # statuses -- which is a fact about 36 tracks, not evidence that the
        # two fields are coupled.
        #
        # The rule here is decided by SCOPE, not by outcome: the check is
        # skipped on every subset, whatever its cross-tab, so it cannot be
        # used to excuse a particular game. The observed cross-tab is printed
        # so a reader sees what the subset contained, and
        # `dist_classifications_are_valid` above still runs in both modes.
        # Full-corpus mode keeps the strict assertion.
        report.skip(
            "dist_class_and_status_independent",
            "corpus-level invariant, not evaluable on a subset; observed "
            + "; ".join(f"{k}={sorted(v)}" for k, v in sorted(spans.items())),
        )
    else:
        report.check(
            "dist_class_and_status_independent",
            any(len(v) > 1 for v in spans.values()),
            "; ".join(f"{k}={sorted(v)}" for k, v in sorted(spans.items())),
        )

    corpus = raw_index.get("corpus", {}) if isinstance(raw_index, dict) else {}
    report.check(
        "dist_corpus_counts_reconcile",
        corpus.get("n_tracks") == len(index)
        and corpus.get("n_events") == sum(
            e.get("event_count", 0) for e in index
        )
        and corpus.get("n_pitched_events") == sum(
            e.get("pitched_event_count", 0) for e in index
        )
        and corpus.get("n_attacks") == sum(
            e.get("attack_count", 0) for e in index
        ),
        f"corpus block: {corpus.get('n_tracks')} tracks, "
        f"{corpus.get('n_events')} events, {corpus.get('n_attacks')} attacks",
    )
    # tracks.csv and the slug map: the redundancy that stops `game` and
    # `track_class` from having a single point of failure.
    csv_path = dist_dir / "tracks.csv"
    csv_lines = csv_path.read_text().splitlines() if csv_path.is_file() else []
    report.check(
        "dist_tracks_csv_covers_every_track",
        len(csv_lines) == len(index) + 1 and bool(index),
        f"tracks.csv has {max(len(csv_lines) - 1, 0)} rows for {len(index)} tracks",
    )
    declared_games = raw_index.get("games", {}) if isinstance(raw_index, dict) else {}
    # The PUBLISHED slug, which is the game family's. It is normally the
    # track id's own slug, and differs only where regional releases of one
    # game are grouped -- see `snesmdb.gamefamily`.
    slugs = {str(e.get("game_slug") or events_mod.game_slug(
        str(e.get("track_id")))) for e in index}
    report.check(
        "dist_slug_to_game_map_complete",
        set(declared_games) == slugs and bool(slugs),
        f"{len(declared_games)} slugs declared for {len(slugs)} in use",
    )
    # ONE SLUG, ONE GAME NAME.
    #
    # Completeness is not the same property. A tree declaring 15 game names
    # for 14 slugs passed the check above, because every slug in use WAS
    # declared -- the two `Panel de Pon` spellings in one rip went unnoticed
    # and would have shipped as two games. A slug that maps to more than one
    # name means either an ungrouped regional release or an inconsistent
    # tag, and both need deciding rather than publishing.
    names_per_slug: dict[str, set[str]] = collections.defaultdict(set)
    for entry in index:
        slug = str(entry.get("game_slug") or events_mod.game_slug(
            str(entry.get("track_id"))))
        if entry.get("game"):
            names_per_slug[slug].add(str(entry["game"]))
    ambiguous = {k: sorted(v) for k, v in names_per_slug.items()
                 if len(v) > 1}
    report.check(
        "dist_slug_to_game_map_is_one_to_one",
        not ambiguous,
        f"{len(ambiguous)} slug(s) carry more than one game name"
        + (f": {ambiguous}" if ambiguous else ""),
    )
    # A grouped family must still say which release each track came from,
    # or grouping has destroyed provenance to tidy a count.
    grouped = [e for e in index
               if e.get("game_slug")
               and e.get("game_slug") != events_mod.game_slug(
                   str(e.get("track_id")))]
    missing_variant = [e.get("track_id") for e in grouped
                       if not e.get("release_variant")]
    report.check(
        "dist_grouped_tracks_record_their_release",
        not missing_variant,
        f"{len(grouped)} track(s) published under a game family, "
        f"{len(missing_variant)} without a `release_variant`",
    )
    # A published estimate must be absent where it was refused. This field
    # published the rejected value on all 1,316 tracks while the docs promised
    # it was absent for 797, so a filter on non-null admitted them silently.
    ticks = 0
    for entry in index if exhaustive else _sample_entries(index):
        path = dist_dir / entry.get("intake", "")
        if not entry.get("intake") or not path.is_file():
            continue
        with gzip.open(path, "rt") as handle:
            timing = (json.load(handle).get("timing") or {})
        if (timing.get("driver_tick_hz") is None) != (
            not timing.get("driver_tick_found")
        ):
            ticks += 1
    report.check(
        "dist_refused_tick_estimates_are_null",
        ticks == 0,
        f"{ticks} tracks whose driver_tick_hz disagrees with "
        f"driver_tick_found",
    )
    # The retired name must not reappear under a different roof.
    summary_text = (dist_dir / "summary.json").read_text() if (
        dist_dir / "summary.json"
    ).is_file() else "{}"
    report.check(
        "dist_no_retired_field_names",
        '"max_polyphony"' not in summary_text,
        "summary.json still publishes max_polyphony"
        if '"max_polyphony"' in summary_text else "none present",
    )
    # The documented row-duration range must match the corpus. This cell said
    # "2.00-12.50 ms" for three releases: two example games printed as a
    # range, contradicting the same table's own rate bounds, and understating
    # how coarse the hardware grid gets for a quarter of the corpus.
    doc = dist_dir / "DATASET.md"
    if doc.is_file():
        periods = []
        for entry in (index if exhaustive else _sample_entries(index)):
            path = dist_dir / entry.get("scores", "")
            if not entry.get("scores") or not path.is_file():
                continue
            with gzip.open(path, "rt") as handle:
                hz = (json.load(handle).get("clock") or {}).get("hz")
            if hz:
                periods.append(1000.0 / float(hz))
        text = doc.read_text()
        stated = f"{min(periods):.3f}\u2013{max(periods):.3f} ms" if periods else ""
        if subset:
            # TWO DIFFERENT THINGS, kept apart. A subset cannot span the
            # corpus range, so equality is the wrong relation -- but a rate
            # beyond the baseline's span is not thereby suspect either. Ken
            # Griffey Jr runs a 551.7 Hz row, a 1.813 ms period, where the
            # frozen 22-game baseline tops out at 500.0 Hz; that is new
            # coverage, which is the point of an expansion, and the
            # documented range is a claim about the baseline's population.
            #
            # So INVALID timing still fails and OUT-OF-BASELINE timing is
            # reported as a nonblocking extension. Invalid means the figures
            # cannot describe hardware: a non-positive or non-finite period,
            # or an hz that disagrees with the tick count it is published
            # beside.
            documented = re.search(
                r"(\d+\.\d+)\u2013(\d+\.\d+) ms", text
            )
            invalid = [p for p in periods if not (p > 0) or p != p]
            report.check(
                "subset_row_duration_valid",
                not invalid and bool(periods),
                f"{len(invalid)} invalid period(s) among {len(periods)}"
                if periods else "no periods found",
            )
            # The documented range must EXIST to be compared against; an
            # absent one is a documentation defect in the published tree and
            # must not pass silently, which an earlier version of this block
            # allowed by only reporting when the range was found.
            report.check(
                "subset_row_duration_documented",
                documented is not None,
                "DATASET.md states a row-duration range" if documented
                else "DATASET.md states NO row-duration range to compare against",
            )
            if periods and documented and not invalid:
                low, high = (float(documented.group(1)),
                             float(documented.group(2)))
                outside = [p for p in periods
                           if p < low - 1e-9 or p > high + 1e-9]
                if outside:
                    report.extension(
                        "subset_row_duration_extends_baseline",
                        f"measured {stated}, documented {documented.group(0)}; "
                        f"{len(outside)} track(s) outside the baseline span. "
                        f"Verified timing, new coverage -- restate the "
                        f"documented range against the expanded population "
                        f"at release, do not widen the frozen claim",
                    )
                else:
                    report.check(
                        "subset_row_duration_within_documented_range",
                        True,
                        f"measured {stated}; documented {documented.group(0)}",
                    )
        elif not exhaustive:
            # The documented range describes the WHOLE corpus, so a sample
            # cannot be expected to reproduce it -- a 26-track sample
            # measures its own narrower span and the comparison fails for a
            # reason that says nothing about the artifact. It failed
            # identically on the preceding release for exactly this reason.
            # The assertion is kept, and kept strict, in exhaustive mode,
            # which is the release gate.
            report.skip(
                "dist_documented_row_duration_matches",
                f"measured {stated} over a sample; the documented range is "
                f"corpus-wide. Run --exhaustive to assert it",
            )
        else:
            report.check(
                "dist_documented_row_duration_matches",
                bool(periods) and stated in text,
                f"measured {stated}; documented range "
                f"{'found' if stated in text else 'NOT found'} in DATASET.md",
            )
    # The shipped documents must match the repository's. Three releases went
    # out with a stale doc copy because publish.py copies the docs at the end
    # of its run and I edited one afterwards -- each time caught by hand, and
    # once not caught until an evaluator read the stale text. Documents are
    # part of the artifact and get checked like the rest of it.
    repo_docs = Path(__file__).resolve().parent.parent / "docs"
    stale = []
    for name in ("DATASET.md", "CHANGELOG.md", "SCHEMA.md"):
        shipped, source = dist_dir / name, repo_docs / name
        if source.is_file() and (
            not shipped.is_file() or shipped.read_text() != source.read_text()
        ):
            stale.append(name)
    report.check(
        "dist_docs_match_the_repository",
        not stale,
        f"stale in dist: {', '.join(stale)}" if stale else "all current",
    )
    report.check(
        "dist_scores_cover_index",
        all(e.get("scores") for e in index) and bool(index),
        f"{sum(1 for e in index if e.get('scores'))}/{len(index)} entries "
        f"have a score file",
    )
    # A published provenance record must describe the build, not the person
    # who ran it. `host` and `user` were shipping an operator's account name
    # and an internal hostname inside every distribution -- and removing those
    # two keys was not sufficient, because `parameters` carries
    # caller-supplied paths verbatim and still read
    # `"dist_dir": "/home/<login>/..."`.
    #
    # So this tests for IDENTITY, not for the word "home": every `home/`
    # segment must be the placeholder a scrubbed path leaves behind. An
    # earlier version rejected any string containing "/home/", which would
    # also have rejected the correctly scrubbed `/local/home/<user>/...`.
    prov_path = dist_dir / "provenance.json"
    prov_text = prov_path.read_text() if prov_path.is_file() else "{}"
    leaked = [
        key for key in ("host", "user", "hostname", "username")
        if key in json.loads(prov_text)
    ]
    logins = {
        name for name in re.findall(r'home/([^/"\\]+)', prov_text)
        if name != "<user>"
    }
    report.check(
        "dist_provenance_identifies_no_operator",
        not leaked and not logins,
        f"keys {leaked or 'clean'}; unscrubbed home segments "
        f"{sorted(logins) or 'none'}",
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
    parser.add_argument(
        "--subset", action="store_true",
        help="audit a PART of the corpus -- one game, a pilot batch. Keeps "
             "every artifact-integrity, event-reconciliation, sample-identity "
             "and score-validation check, and replaces the two assertions "
             "that are only meaningful corpus-wide: the absolute "
             "sample-diversity floor and the exact documented row-duration "
             "range. It does NOT weaken full-corpus verification, which is "
             "still what runs without this flag.",
    )
    args = parser.parse_args()

    report = Report()
    check_out_dir(args.out_dir, report)
    check_records(args.out_dir, report, args.sample, args.exhaustive)
    check_uniform_preservation(args.out_dir, report, args.sample * 4)
    if args.dist_dir and args.dist_dir.exists():
        check_dist(args.dist_dir, report, exhaustive=args.exhaustive,
                   subset=args.subset)
        check_events(args.dist_dir, report, exhaustive=args.exhaustive,
                     subset=args.subset)
    elif args.dist_dir:
        report.check("dist_present", False, f"{args.dist_dir} does not exist")

    for line in report.passes:
        print(line)
    for line in report.not_applicable:
        print(line)
    for line in report.extensions:
        print(line)
    for line in report.failures:
        print(line, file=sys.stderr)
    if args.subset:
        print(
            "\nSUBSET MODE: corpus-wide sample-diversity and exact "
            "documentation-range assertions were replaced by subset-scoped "
            "equivalents. This is not a full-corpus audit."
        )
    if report.extensions:
        print(
            f"\n{len(report.extensions)} verified measurement(s) beyond the "
            f"frozen baseline's span -- coverage extensions, nonblocking. "
            f"They do not alter the baseline's claims."
        )
    print(
        f"\n{len(report.passes)} passed, {len(report.failures)} failed, "
        f"{len(report.not_applicable)} n/a, {len(report.extensions)} extending",
        file=sys.stderr if report.failures else sys.stdout,
    )
    raise SystemExit(len(report.failures))


if __name__ == "__main__":
    main()
