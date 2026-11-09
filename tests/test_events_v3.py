"""`snesmdb.events.v3` — the two fields that did not mean what they said.

Both defects were found by an independent researcher working only from the
published artifact, and **neither was detectable by any self-consistency
check**: every header count matched its own rows, every id resolved, every
cross-file total reconciled. 31 audit checks and 422 tests passed over data
in which 154,910 rows claimed a pitch change that was not there.

That is the lesson these tests encode. Checking that an artifact agrees with
itself is not checking that it means what it claims. Each test below asserts a
field's *semantics* against an independent source — the raw registers, or the
definition in the documentation — rather than against another published
number.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import events


def _note(note_id: int, midi: float | None = 60.0, register: int = 4096):
    return {
        "note_id": note_id, "voice": 0, "srcn": 0, "start_sec": 0.0,
        "end_sec": 1.0, "midi_note": midi, "pitch_register": register,
        "pitch_confidence": "high",
    }


def _step(parent: int, pitch: int, time_sec: float = 0.5):
    return {
        "parent_note_id": parent, "pitch": pitch, "previous_pitch": 4096,
        "semitones": 0.0, "time_sec": time_sec, "voice": 0,
    }


# ---------------------------------------------------------------------------
# A legato step carries its OWN pitch
# ---------------------------------------------------------------------------

def test_a_step_an_octave_up_reads_an_octave_up():
    """PITCH is a frequency multiplier, so double the register is +12."""
    assert events.step_midi_note(
        _step(0, 8192), _note(0, 60.0, 4096)
    ) == 72.0


def test_a_step_reports_the_pitch_it_wrote_not_its_parents():
    """THE DEFECT. All 154,910 published steps carried the parent's pitch,
    maximum difference exactly 0.0, because the code asked a step record for a
    `midi_note` key it does not have and silently fell back to the parent."""
    parent = _note(0, 60.0, 4096)
    table = events.build(
        "g-01:h", True, 2.0, [parent], {0: "s"},
        legato_steps=[_step(0, 4871)],       # ~+3 semitones
    )
    step = next(e for e in table["events"] if e["origin"] == "legato_step")
    attack = next(e for e in table["events"] if e["origin"] == "key_on")
    assert step["midi_note"] != attack["midi_note"]
    assert step["midi_note"] == round(
        60.0 + 12.0 * math.log2(4871 / 4096), 4
    )


def test_the_pitch_comes_from_the_registers_not_the_semitones_field():
    """`semitones` is relative to the PREVIOUS write, not to the note. Steps
    chain, so for the second step of a chain the two readings differ -- 79 of
    103 did in the first Actraiser track. Only the register ratio is correct.
    """
    parent = _note(0, 60.0, 4096)
    # Two chained steps, each a semitone above the last. A `semitones`-based
    # reading would place the second one wrongly.
    first = dict(_step(0, 4340, 0.2), semitones=1.0, previous_pitch=4096)
    second = dict(_step(0, 4598, 0.4), semitones=1.0, previous_pitch=4340)
    table = events.build(
        "g-01:h", True, 2.0, [parent], {0: "s"},
        legato_steps=[first, second],
    )
    steps = sorted(
        (e for e in table["events"] if e["origin"] == "legato_step"),
        key=lambda e: e["onset_sec"],
    )
    assert steps[0]["midi_note"] == round(
        60.0 + 12.0 * math.log2(4340 / 4096), 4
    )
    # The second is ~2 semitones above the NOTE, not 1 -- which is what a
    # naive `parent + semitones` would have produced.
    assert steps[1]["midi_note"] == round(
        60.0 + 12.0 * math.log2(4598 / 4096), 4
    )
    assert abs(steps[1]["midi_note"] - (60.0 + 1.0)) > 0.5


def test_an_unrecoverable_pitch_stays_unrecoverable():
    """A step on an unpitched parent must not acquire a pitch. Inheriting the
    parent's was the whole defect; inheriting `None` is correct."""
    table = events.build(
        "g-01:h", True, 2.0, [_note(0, None)], {0: "s"},
        legato_steps=[_step(0, 8192)],
    )
    step = next(e for e in table["events"] if e["origin"] == "legato_step")
    assert step["midi_note"] is None
    assert step["pitch_status"] == events.PITCH_UNRECOVERABLE


def test_a_missing_or_zero_register_yields_no_pitch_rather_than_a_guess():
    assert events.step_midi_note(_step(0, 0), _note(0)) is None
    assert events.step_midi_note(
        {"parent_note_id": 0}, _note(0)
    ) is None
    assert events.step_midi_note(_step(0, 4096), _note(0, 60.0, 0)) is None


# ---------------------------------------------------------------------------
# `event_id` is a row key
# ---------------------------------------------------------------------------

def test_event_ids_are_unique_across_both_origins():
    """They were duplicated in 517 of 1,316 tracks, because a step published
    its parent's id as its own. A `set_index("event_id")` discarded up to 85%
    of one track's rows with no error."""
    table = events.build(
        "g-01:h", True, 2.0, [_note(0), _note(1)], {0: "s"},
        legato_steps=[_step(0, 4340), _step(0, 4598), _step(1, 4340)],
    )
    ids = [e["event_id"] for e in table["events"]]
    assert len(ids) == len(set(ids)) == 5


def test_parent_event_id_is_null_on_an_attack_and_set_on_a_step():
    """`parent_event_id == event_id` held for all 2,018,409 rows, so the id
    fields could not distinguish a step from an attack. Both the README and
    the changelog already described the behaviour asserted here."""
    table = events.build(
        "g-01:h", True, 2.0, [_note(0)], {0: "s"},
        legato_steps=[_step(0, 4340)],
    )
    attack = next(e for e in table["events"] if e["origin"] == "key_on")
    step = next(e for e in table["events"] if e["origin"] == "legato_step")
    assert attack["parent_event_id"] is None
    assert step["parent_event_id"] == attack["event_id"]
    assert step["event_id"] != attack["event_id"]


def test_steps_group_back_onto_their_parent():
    """The documented use: reassembling a phrase the driver expressed as one
    sounding voice with several pitches."""
    table = events.build(
        "g-01:h", True, 2.0, [_note(0), _note(1)], {0: "s"},
        legato_steps=[_step(0, 4340), _step(0, 4598), _step(1, 4871)],
    )
    by_parent: dict[int, int] = {}
    for event in table["events"]:
        if event["parent_event_id"] is not None:
            by_parent[event["parent_event_id"]] = (
                by_parent.get(event["parent_event_id"], 0) + 1
            )
    assert by_parent == {0: 2, 1: 1}


# ---------------------------------------------------------------------------
# The headline counts
# ---------------------------------------------------------------------------

def test_pitched_attacks_are_counted_separately_from_pitched_events():
    """"The corpus contains 1.56 M pitched events" was read as a count of
    musical pitches and was 7% duplicates. Both figures are now published so
    the question is answerable from the header."""
    table = events.build(
        "g-01:h", True, 2.0, [_note(0), _note(1, None)], {0: "s"},
        legato_steps=[_step(0, 4340)],
    )
    assert table["attack_count"] == 2
    assert table["pitched_attack_count"] == 1
    assert table["pitched_event_count"] == 2      # the attack and its step
    assert table["legato_step_count"] == 1


def test_the_schema_version_is_bumped_for_a_breaking_change():
    """v4 corrects sample identity per attack and publishes null instead of
    "" for an unknown one. Both are breaking, so the version moves and every
    superseded version stays listed -- a reader must be able to tell which
    contract a file in hand was written against."""
    assert events.SCHEMA == "snesmdb.events.v4"
    for superseded in ("snesmdb.events.v3", "snesmdb.events.v2",
                       "snesmdb.events.v1"):
        assert superseded in events.PREVIOUS_SCHEMAS
