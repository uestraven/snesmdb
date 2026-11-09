"""Per-attack identity correction, and the end of `""` as "unknown".

The defect v4 corrects is that identity was resolved per SRCN from the
directory as the SPC was CAPTURED. The DSP reads the entry at key-on and
drivers rewrite entries during playback, so one SRCN addresses different
audio at different moments. A correction keyed per SRCN cannot express that;
it has to be keyed per attack.

The alignment is the fragile part. Ordinals count key-ons per voice in
PUBLISHED order, which is the order the measurement used, so the correction
must be applied after the sort. Applying it before would misalign every
attack following the first difference -- and the result would still look
like a plausible table.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import events  # noqa: E402

A, B = "a" * 16, "b" * 16


def _note(note_id, voice, start, srcn=0, pitch=0x1000):
    return {"note_id": note_id, "voice": voice, "start_sec": start,
            "end_sec": start + 0.1, "srcn": srcn, "pitch": pitch,
            "pitch_register": pitch, "midi_note": 60.0,
            "pitch_confidence": "high"}


def _build(notes, corrections=None, sample_ids=None, steps=()):
    return events.build(
        track_id="t:0", ok=True, duration_sec=10.0, notes=notes,
        sample_ids=sample_ids if sample_ids is not None else {0: A},
        legato_steps=steps,
        attack_level=lambda n: 15, sustain_level=lambda n, a: 15,
        game="G", track_class="music", corrections=corrections,
    )


def _attacks(table):
    return [e for e in table["events"] if e["origin"] == events.ORIGIN_KEY_ON]


# ---------------------------------------------------------------------------
# The schema contract
# ---------------------------------------------------------------------------

def test_an_unresolved_identity_is_null_and_never_the_empty_string():
    """v3 used `""` for 13,413 events and null for none, so a reader testing
    `is not None` saw every one of them as a resolved identity."""
    table = _build([_note(0, 0, 0.0, srcn=9)], sample_ids={})
    event = _attacks(table)[0]
    assert event["sample_id"] is None
    assert event["sample_id"] != ""


def test_a_reason_is_present_exactly_when_the_identity_is_null():
    resolved = _attacks(_build([_note(0, 0, 0.0)]))[0]
    assert resolved["sample_id"] == A
    assert resolved["sample_id_unresolved_reason"] is None

    missing = _attacks(_build([_note(0, 0, 0.0, srcn=9)], sample_ids={}))[0]
    assert missing["sample_id"] is None
    assert missing["sample_id_unresolved_reason"] is not None


def test_the_schema_declares_v4_and_keeps_every_superseded_version():
    assert events.SCHEMA == "snesmdb.events.v4"
    assert "snesmdb.events.v3" in events.PREVIOUS_SCHEMAS


# ---------------------------------------------------------------------------
# Correction, keyed per attack
# ---------------------------------------------------------------------------

def test_two_attacks_on_one_srcn_can_carry_different_identities():
    """The whole point. Under v3 these two attacks shared an identity
    because they share an SRCN; the DSP read a rewritten entry for the
    second."""
    notes = [_note(0, 0, 0.0, srcn=3), _note(1, 0, 1.0, srcn=3)]
    table = _build(notes, corrections={
        (0, 1): {"sample_id": B, "source": events.SOURCE_OBSERVED,
                 "reason": None},
    }, sample_ids={3: A})
    got = [(e["sample_id"], e["sample_id_source"]) for e in _attacks(table)]
    assert got == [(A, events.SOURCE_CAPTURE),
                   (B, events.SOURCE_OBSERVED)]


def test_ordinals_are_counted_in_published_order_not_input_order():
    """`notes` here is in DESCENDING time, and the table is sorted ascending.
    A correction for ordinal 0 must land on the EARLIEST attack. Keyed off
    input order it would hit the latest instead, and every later attack on
    that voice would be shifted too."""
    notes = [_note(0, 0, 5.0, srcn=3), _note(1, 0, 1.0, srcn=3)]
    table = _build(notes, corrections={
        (0, 0): {"sample_id": B, "source": events.SOURCE_OBSERVED,
                 "reason": None},
    }, sample_ids={3: A})
    attacks = _attacks(table)
    assert [e["onset_sec"] for e in attacks] == [1.0, 5.0]
    assert attacks[0]["sample_id"] == B, "correction hit the wrong attack"
    assert attacks[1]["sample_id"] == A


def test_ordinals_are_counted_per_voice_independently():
    notes = [_note(0, 0, 0.0, srcn=3), _note(1, 1, 0.5, srcn=3),
             _note(2, 0, 1.0, srcn=3)]
    table = _build(notes, corrections={
        (1, 0): {"sample_id": B, "source": events.SOURCE_OBSERVED,
                 "reason": None},
    }, sample_ids={3: A})
    by_voice = {(e["voice"], e["onset_sec"]): e["sample_id"]
                for e in _attacks(table)}
    assert by_voice[(1, 0.5)] == B
    assert by_voice[(0, 0.0)] == A and by_voice[(0, 1.0)] == A


def test_a_correction_can_withdraw_an_identity_to_null_with_a_reason():
    """15,165 attacks in the corpus resolve to unwritten memory, which still
    decodes into a confident-looking hash. Withdrawing those is the single
    largest effect of the correction."""
    table = _build([_note(0, 0, 0.0, srcn=3)], corrections={
        (0, 0): {"sample_id": None, "source": events.SOURCE_UNRESOLVED,
                 "reason": events.REASON_IMPLAUSIBLE},
    }, sample_ids={3: A})
    event = _attacks(table)[0]
    assert event["sample_id"] is None
    assert event["sample_id_source"] == events.SOURCE_UNRESOLVED
    assert event["sample_id_unresolved_reason"] == events.REASON_IMPLAUSIBLE


def test_a_withdrawn_identity_is_not_replaced_by_a_substitute():
    """No convenient stand-in: the reason field must not come with a hash."""
    table = _build([_note(0, 0, 0.0, srcn=3)], corrections={
        (0, 0): {"sample_id": "", "source": events.SOURCE_UNRESOLVED,
                 "reason": events.REASON_NOT_ESTABLISHED},
    }, sample_ids={3: A})
    assert _attacks(table)[0]["sample_id"] is None


def test_an_attack_with_no_correction_keeps_its_capture_time_identity():
    """1,833,879 of 1,863,499 attacks are unchanged; the correction must be
    silent on them rather than rewriting the column wholesale."""
    table = _build([_note(0, 0, 0.0, srcn=3)], corrections={
        (7, 5): {"sample_id": B, "source": events.SOURCE_OBSERVED,
                 "reason": None},
    }, sample_ids={3: A})
    event = _attacks(table)[0]
    assert event["sample_id"] == A
    assert event["sample_id_source"] == events.SOURCE_CAPTURE


# ---------------------------------------------------------------------------
# Legato steps
# ---------------------------------------------------------------------------

def test_a_legato_step_follows_its_parents_corrected_identity():
    """A step does not re-key, so it sounds the parent's sample. If the
    parent's identity is corrected and the step's is not, the table
    contradicts itself about what a sustained note is playing."""
    notes = [_note(0, 0, 0.0, srcn=3)]
    steps = [{"parent_note_id": 0, "time_sec": 0.05, "pitch": 0x1200}]
    table = _build(notes, corrections={
        (0, 0): {"sample_id": B, "source": events.SOURCE_OBSERVED,
                 "reason": None},
    }, sample_ids={3: A}, steps=steps)
    step = [e for e in table["events"]
            if e["origin"] == events.ORIGIN_LEGATO_STEP][0]
    assert step["sample_id"] == B
    assert step["sample_id_source"] == events.SOURCE_OBSERVED


def test_a_step_follows_a_parent_whose_identity_was_withdrawn():
    notes = [_note(0, 0, 0.0, srcn=3)]
    steps = [{"parent_note_id": 0, "time_sec": 0.05, "pitch": 0x1200}]
    table = _build(notes, corrections={
        (0, 0): {"sample_id": None, "source": events.SOURCE_UNRESOLVED,
                 "reason": events.REASON_IMPLAUSIBLE},
    }, sample_ids={3: A}, steps=steps)
    step = [e for e in table["events"]
            if e["origin"] == events.ORIGIN_LEGATO_STEP][0]
    assert step["sample_id"] is None
    assert step["sample_id_unresolved_reason"] == events.REASON_IMPLAUSIBLE


# ---------------------------------------------------------------------------
# Header counts describe the file they are in
# ---------------------------------------------------------------------------

def test_the_header_counts_match_the_events_after_correction():
    notes = [_note(i, 0, float(i), srcn=3) for i in range(4)]
    table = _build(notes, corrections={
        (0, 1): {"sample_id": None, "source": events.SOURCE_UNRESOLVED,
                 "reason": events.REASON_IMPLAUSIBLE},
        (0, 2): {"sample_id": B, "source": events.SOURCE_OBSERVED,
                 "reason": None},
    }, sample_ids={3: A})
    assert table["attack_count"] == 4
    assert table["attacks_with_sample_id"] == 3
    assert table["attacks_without_sample_id"] == 1
    assert table["attacks_identity_observed_at_key_on"] == 1
    assert (table["attacks_with_sample_id"]
            + table["attacks_without_sample_id"]) == table["attack_count"]


def test_correction_does_not_change_event_count_or_ids():
    """The correction must move the identity column and nothing else."""
    notes = [_note(i, i % 2, float(i), srcn=3) for i in range(6)]
    plain = _build(notes, sample_ids={3: A})
    fixed = _build(notes, corrections={
        (0, 0): {"sample_id": B, "source": events.SOURCE_OBSERVED,
                 "reason": None},
    }, sample_ids={3: A})
    assert plain["event_count"] == fixed["event_count"]
    strip = lambda t: [
        {k: v for k, v in e.items() if not k.startswith("sample_id")}
        for e in t["events"]
    ]
    assert strip(plain) == strip(fixed)
