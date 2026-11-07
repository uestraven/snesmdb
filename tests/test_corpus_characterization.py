"""Corpus characterization — measured properties of THIS corpus.

NOT CONTRACT TESTS, and the distinction is the reason this file is separate.
Everything here records something that happens to be true of the 1,316 tracks
currently published. A failure means **the corpus changed**, not that a schema
is invalid. The correct response is to look at the new figure, decide whether
it is plausible, and update the recorded value -- never to change a published
contract to make a number come back.

The contracts themselves are definitional and do not appear here. In
particular:

    `sample_id` is a content hash of decoded audio. It is NOT an instrument
    label, BY DEFINITION, whatever any corpus's pitch-span statistics happen
    to show.

That holds for a corpus of one track and for a corpus where every sample is
used at exactly one pitch. An earlier version of the pitch-span check below
lived among the Gate 4 contract tests and was worded as though the definition
depended on the measurement; it does not, and a definition that could be
falsified by a statistic would be a weak definition rather than a strong test.
What the measurement is good for is evidence that the distinction MATTERS in
practice here, which is a claim about this corpus and belongs in this file.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "examples"))

import workflows  # noqa: E402

DIST = Path(os.environ.get(
    "SNESMDB_DIST", Path.home() / "snesmdb-corpus" / "dist",
))

#: Recorded 2026-11-07 against the gate5-rc1 tree. Each is a measurement, so
#: each carries the date it was taken.
RECORDED_TRACKS = 1316
RECORDED_GAMES = 22
RECORDED_EVENTS = 2_018_409
RECORDED_PITCHED = 1_560_002
RECORDED_ATTACKS = 1_863_499

#: The widest pitch span over which a single recurring sample is used in
#: Actraiser: 65.36 semitones across 14 tracks, measured 2026-11-07. The bound
#: is loose because the point is the order of magnitude -- several octaves, not
#: a semitone or two -- and not the exact figure.
RECORDED_WIDEST_ACTRAISER_SPAN = 65.36
WIDEST_SPAN_FLOOR = 24.0


def _need_dist() -> dict:
    if not (DIST / "index.json").is_file():
        pytest.skip(f"no published corpus at {DIST} -- run `make corpus`")
    return workflows.load_index(DIST)


def test_recorded_corpus_size():
    """If this fails, the corpus changed. Update the figures and say so in
    `docs/CHANGELOG.md`, because every published count moves with them."""
    block = _need_dist()["corpus"]
    assert block["n_tracks"] == RECORDED_TRACKS
    assert block["n_games"] == RECORDED_GAMES
    assert block["n_events"] == RECORDED_EVENTS
    assert block["n_pitched_events"] == RECORDED_PITCHED
    assert block["n_attacks"] == RECORDED_ATTACKS


def test_recorded_class_and_status_census():
    block = _need_dist()["corpus"]
    assert block["track_classes"] == {
        "music": 1006, "jingle": 233, "effect": 60, "drone": 17,
    }
    assert block["extraction_statuses"] == {
        "complete_with_pitched_events": 1243,
        "complete_unpitched_only": 56,
        "complete_no_events": 17,
    }


def test_recorded_pitch_span_of_a_recurring_sample():
    """CHARACTERIZATION. One Actraiser sample is used across 14 tracks over
    about 65 semitones.

    This is evidence that reading `sample_id` as an instrument label would
    mislead a researcher on real data -- useful for the documentation, and the
    reason the field is described the way it is. It is NOT what makes the
    contract true: a content hash is not an instrument label by definition.

    A failure here means the corpus or the sample grouping changed. Check
    which, then update `RECORDED_WIDEST_ACTRAISER_SPAN`.
    """
    _need_dist()
    entries = workflows.discover(DIST, game="Actraiser", track_class=None)
    if not entries:
        pytest.skip("Actraiser absent from this corpus")
    report = workflows.sample_usage(DIST, entries, min_tracks=2)
    spans = [
        r["pitch_span_semitones"] for r in report["recurring"]
        if r["pitch_span_semitones"] is not None
    ]
    assert spans, "no recurring sample carried pitched events"
    assert max(spans) == pytest.approx(
        RECORDED_WIDEST_ACTRAISER_SPAN, abs=0.5
    ), (
        f"widest recurring-sample span is now {max(spans):.2f} semitones, "
        f"recorded {RECORDED_WIDEST_ACTRAISER_SPAN}. The corpus or the sample "
        f"grouping changed; this is not a schema defect."
    )
    # Stated separately: the documentation's claim is about an order of
    # magnitude, so it survives a corpus change that the exact figure would
    # not.
    assert max(spans) > WIDEST_SPAN_FLOOR


def test_recorded_distinct_sample_count():
    """1,142 distinct ids corpus-wide, corroborated independently by milestone
    5's `timbre_features`, which counted 1,162 (game, content) pairs by a
    different code path; 64 ids appear in more than one game."""
    index = _need_dist()
    path = DIST / "provenance.json"
    if not path.is_file():
        pytest.skip("no provenance.json")
    counts = json.loads(path.read_text()).get("parameters", {}).get("counts", {})
    # Resolved ids are per (track, srcn), so this is well above the distinct
    # count and is recorded to catch a collapse in directory resolution.
    assert counts.get("sample_ids_resolved") == 8103
    assert len(index["tracks"]) == RECORDED_TRACKS
