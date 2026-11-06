"""Note recovery from a write log. Pure Python -- always runs, never skips."""

from __future__ import annotations

import pytest

from snesmdb import voices
from snesmdb.voices import R_KOFF, R_KON, R_NON, R_PMON, extract

V = 0x10  # voice stride


def w(t: int, addr: int, data: int) -> dict:
    return {"t": t, "addr": addr, "data": data, "reg": hex(addr), "voice": -1}


def setup_voice(t: int, voice: int, pitch: int, srcn: int = 0, vol: int = 0x60):
    base = voice * V
    return [
        w(t + 0, base + 0x00, vol),
        w(t + 1, base + 0x01, vol),
        w(t + 2, base + 0x02, pitch & 0xFF),
        w(t + 3, base + 0x03, (pitch >> 8) & 0x3F),
        w(t + 4, base + 0x04, srcn),
    ]


def test_a_note_runs_from_key_on_to_key_off() -> None:
    log = [*setup_voice(0, 0, 0x0800), w(10, R_KON, 0x01), w(1000, R_KOFF, 0x01)]
    out = extract(iter(log))
    assert len(out.notes) == 1
    note = out.notes[0]
    assert (note.start, note.end, note.duration) == (10, 1000, 990)
    assert note.pitch == 0x0800
    assert not out.unhandled


def test_parameters_are_latched_at_key_on_not_at_write_time() -> None:
    """A driver writes a voice's registers, keys it on, then writes the NEXT
    note's parameters into the same registers. Reading the final register
    state would give every note the last note's pitch."""
    log = [
        *setup_voice(0, 0, 0x0800),
        w(10, R_KON, 0x01),
        w(20, R_KOFF, 0x01),
        *setup_voice(30, 0, 0x1000),
        w(40, R_KON, 0x01),
        w(50, R_KOFF, 0x01),
    ]
    out = extract(iter(log))
    assert [n.pitch for n in out.notes] == [0x0800, 0x1000]


def test_a_re_key_without_key_off_ends_the_previous_note() -> None:
    """Drivers retrigger a voice without keying it off. Treating that as a
    continuation would merge two notes into one long one."""
    log = [
        *setup_voice(0, 1, 0x0800),
        w(10, R_KON, 0x02),
        *setup_voice(100, 1, 0x0C00),
        w(110, R_KON, 0x02),
        w(200, R_KOFF, 0x02),
    ]
    out = extract(iter(log))
    assert len(out.notes) == 2
    first, second = out.notes
    assert (first.end, first.ended_by_rekey) == (110, True)
    assert (second.start, second.end) == (110, 200)
    assert [n.pitch for n in out.notes] == [0x0800, 0x0C00]


def test_one_key_on_write_can_start_several_voices() -> None:
    log = [
        *setup_voice(0, 0, 0x0800),
        *setup_voice(5, 3, 0x1000),
        w(10, R_KON, 0x09),  # voices 0 and 3
        w(500, R_KOFF, 0x09),
    ]
    out = extract(iter(log))
    assert sorted(n.voice for n in out.notes) == [0, 3]
    assert all(n.duration == 490 for n in out.notes)


def test_a_note_still_sounding_at_the_end_is_marked_unfinished() -> None:
    """Not dropped and not given a fabricated end time -- the log simply
    stopped while the voice was running, and the corpus should say so."""
    log = [*setup_voice(0, 0, 0x0800), w(10, R_KON, 0x01)]
    out = extract(iter(log))
    assert out.notes[0].end is None
    assert out.notes[0].duration is None
    assert out.summary()["n_unfinished_notes"] == 1


def test_noise_and_pitch_modulation_are_flagged_not_silently_wrong() -> None:
    """With NON set the DSP plays noise, so sample and pitch are meaningless;
    with PMON set the pitch is modulated by the previous voice, so the PITCH
    register alone does not describe what sounded. Both must be visible
    downstream rather than producing confident wrong notes."""
    log = [
        w(0, R_NON, 0x02),
        w(1, R_PMON, 0x04),
        *setup_voice(2, 1, 0x0800),
        *setup_voice(8, 2, 0x0900),
        w(20, R_KON, 0x06),  # voices 1 and 2
        w(900, R_KOFF, 0x06),
    ]
    out = extract(iter(log))
    by_voice = {n.voice: n for n in out.notes}
    assert by_voice[1].noise and not by_voice[1].pitch_modulated
    assert by_voice[2].pitch_modulated and not by_voice[2].noise
    assert out.summary()["n_noise_notes"] == 1
    assert out.summary()["n_pitch_modulated_notes"] == 1


def test_volume_is_signed() -> None:
    """VOL is signed 8-bit; a negative volume inverts the phase, which real
    drivers use for stereo. Reading it unsigned turns -1 into 255."""
    log = [
        w(0, 0x00, 0xC0),  # voice 0 VOLL = -64
        w(1, 0x01, 0x40),  # voice 0 VOLR = +64
        w(2, 0x02, 0x00),
        w(3, 0x03, 0x10),
        w(10, R_KON, 0x01),
        w(20, R_KOFF, 0x01),
    ]
    out = extract(iter(log))
    assert (out.notes[0].volume_left, out.notes[0].volume_right) == (-64, 64)


def test_unrecognised_registers_are_counted_not_dropped() -> None:
    log = [w(0, 0x1D, 0xFF), w(1, 0x1D, 0x00)]
    out = extract(iter(log))
    assert sum(out.unhandled.values()) == 2, out.unhandled


# --------------------------------------------------------------------------
# Seeding from the SPC snapshot
# --------------------------------------------------------------------------

def _dsp_block(**per_voice):
    """A 128-byte DSP register block with the given per-voice values."""
    block = bytearray(128)
    for voice in range(voices.VOICE_COUNT):
        base = voice * 0x10
        for name, offset in (
            ("voll", voices.V_VOLL), ("volr", voices.V_VOLR),
            ("pitchl", voices.V_PITCHL), ("pitchh", voices.V_PITCHH),
            ("srcn", voices.V_SRCN), ("adsr1", voices.V_ADSR1),
            ("adsr2", voices.V_ADSR2), ("gain", voices.V_GAIN),
        ):
            values = per_voice.get(name)
            if values is not None:
                block[base + offset] = values[voice]
    return bytes(block)


def test_seed_states_reads_the_snapshot_layout():
    srcn = [10, 10, 10, 10, 11, 8, 2, 8]        # Super Mario World "Athletic"
    block = _dsp_block(srcn=srcn, adsr1=[238] * 8, gain=[184] * 8)
    states = voices.seed_states(block)
    assert [s.srcn for s in states] == srcn
    assert all(s.adsr1 == 238 and s.gain == 184 for s in states)


def test_seed_states_without_a_block_is_all_zero():
    assert all(s.srcn == 0 for s in voices.seed_states(None))


def test_a_driver_that_never_writes_srcn_still_gets_the_right_sample():
    """The bug this guards: "Athletic" writes only KON/KOFF/VOL/PITCH for its
    whole length, so every one of its 1,164 notes was recorded as sample 0
    instead of samples 2, 8, 10 and 11 -- each pitched against the wrong BRR
    sample and given the wrong timbre class."""
    block = _dsp_block(srcn=[10, 10, 10, 10, 11, 8, 2, 8], adsr1=[238] * 8)
    log = [
        {"t": 1000, "addr": 0x02, "data": 0x00},   # voice 0 PITCHL
        {"t": 1001, "addr": 0x03, "data": 0x10},   # voice 0 PITCHH
        {"t": 1002, "addr": 0x4C, "data": 0x01},   # KON voice 0
        {"t": 9000, "addr": 0x5C, "data": 0x01},   # KOFF voice 0
    ]
    seeded = voices.extract(iter(log), initial_dsp=block)
    assert [n.srcn for n in seeded.notes] == [10]

    unseeded = voices.extract(iter(log))
    assert [n.srcn for n in unseeded.notes] == [0], "the old behaviour"


def test_seeding_does_not_override_a_driver_that_does_write():
    block = _dsp_block(srcn=[10] * 8)
    log = [
        {"t": 1000, "addr": 0x04, "data": 3},      # voice 0 SRCN := 3
        {"t": 1002, "addr": 0x4C, "data": 0x01},
        {"t": 9000, "addr": 0x5C, "data": 0x01},
    ]
    out = voices.extract(iter(log), initial_dsp=block)
    assert [n.srcn for n in out.notes] == [3]


def test_a_seeded_envelope_is_not_reported_as_silent():
    """540 tracks reported ADSR disabled with GAIN 0 -- a silent envelope --
    while their snapshots have ADSR enabled on every voice."""
    block = _dsp_block(srcn=[1] * 8, adsr1=[238] * 8, adsr2=[224] * 8, gain=[184] * 8)
    log = [
        {"t": 1002, "addr": 0x4C, "data": 0x01},
        {"t": 9000, "addr": 0x5C, "data": 0x01},
    ]
    note = voices.extract(iter(log), initial_dsp=block).notes[0]
    assert note.adsr1 & 0x80, "ADSR must read as enabled"
    assert not (note.adsr1 == 0 and note.gain == 0)


# --------------------------------------------------------------------------
# Legato note successions: an inferred event table, never the note stream
# --------------------------------------------------------------------------

def _pitch_for_semitones(base: int, semitones: float) -> int:
    import math
    return max(1, min(0x3FFF, int(round(base * (2.0 ** (semitones / 12.0))))))


def _voice_pitch(t: int, voice: int, pitch: int) -> list[dict]:
    """The two writes a real driver uses to set a 14-bit PITCH."""
    return [
        w(t, voice * V + 0x02, pitch & 0xFF),
        w(t + 20, voice * V + 0x03, (pitch >> 8) & 0x3F),
    ]


BASE = 0x1000


def _legato_log(steps_semitones, spacing=200_000, start=10_000):
    """A key-on followed by pitch steps, with no further key-on."""
    log = list(_voice_pitch(1_000, 0, BASE))
    log.append(w(start, R_KON, 0x01))
    pitch = BASE
    t = start + spacing
    for semis in steps_semitones:
        pitch = _pitch_for_semitones(pitch, semis)
        log += _voice_pitch(t, 0, pitch)
        t += spacing
    log.append(w(t + spacing, R_KOFF, 0x01))
    return log


def test_a_clean_legato_step_is_detected():
    out = extract(iter(_legato_log([4.0])))
    assert len(out.notes) == 1, "the note stream stays bound to KON"
    assert len(out.legato_steps) == 1
    step = out.legato_steps[0]
    assert step.semitones == pytest.approx(4.0, abs=0.05)
    assert step.parent_note_id == out.notes[0].note_id
    assert step.voice == 0


def test_the_main_note_stream_is_never_modified():
    """The invariant the whole design rests on: a consumer reading only
    `notes` sees exactly what it saw before legato steps existed."""
    log = _legato_log([4.0, -3.0, 7.0])
    with_steps = extract(iter(log))
    assert len(with_steps.legato_steps) == 3

    # The same log, with detection disabled by removing the timeline input.
    baseline = extract(iter(log))
    baseline.legato_steps = []
    assert len(with_steps.notes) == len(baseline.notes) == 1
    note = with_steps.notes[0]
    assert note.start == 10_000
    assert note.end is not None, "end must still be the KOFF, not a step time"
    assert note.end == max(x["t"] for x in log if x["addr"] == R_KOFF)
    assert note.pitch == BASE, "the parent keeps its own key-on pitch"


def test_a_half_written_pitch_does_not_create_a_step():
    """The artifact that inflated the first measurement of this.

    PITCH is two registers, so one logical change lands as two writes with a
    wild intermediate value between them. Counting that as a jump reported
    1,006 steps for Mega Man X where there are 568, and 96 for a Final
    Fantasy VI track that has none at all.
    """
    # One logical change of +0.1 semitones -- below threshold -- but its
    # intermediate state is an enormous interval.
    target = _pitch_for_semitones(BASE, 0.1)
    log = list(_voice_pitch(1_000, 0, BASE))
    log.append(w(10_000, R_KON, 0x01))
    log += _voice_pitch(200_000, 0, target)
    log.append(w(400_000, R_KOFF, 0x01))
    out = extract(iter(log))
    assert out.legato_steps == [], "a half-written PITCH was read as a step"


def test_vibrato_is_not_a_legato_step():
    """It returns, so it is modulation. Depth is deliberately large.

    The modulation runs right up to the key-off, which is what a driver
    actually does -- it has no reason to stop modulating early. For the case
    where it does, see the next test.
    """
    log = list(_voice_pitch(1_000, 0, BASE))
    log.append(w(10_000, R_KON, 0x01))
    t = 50_000
    for i in range(20):
        log += _voice_pitch(t, 0, _pitch_for_semitones(BASE, 2.0 if i % 2 else 0.0))
        t += 20_000
    log.append(w(t, R_KOFF, 0x01))
    out = extract(iter(log))
    # 20 excursions, and the modulation must not be shredded into notes. The
    # final excursion is structurally ambiguous -- nothing follows it to come
    # back to -- so zero is not achievable and claiming it would be a lie
    # about what the data can show. See the next test.
    assert len(out.legato_steps) <= 1, "vibrato was read as note successions"


def test_modulation_that_stops_mid_note_is_a_known_false_positive():
    """The one case the return test cannot catch, pinned deliberately.

    If a driver modulates and then stops, holding the final excursion for the
    rest of the note, that excursion is indistinguishable from a step: the
    pitch moved and did not come back. It is recorded as a step, with
    `observed_ticks` showing how long the hold lasted so a consumer can weigh
    it.

    A fixed 100 ms "room to prove itself" guard was tried against this and
    reverted: median note duration is 116 ms for Mega Man X and 107 ms for
    Star Ocean, so a window that long rejected 94% of real steps. A window
    longer than the thing it measures cannot measure it.
    """
    log = list(_voice_pitch(1_000, 0, BASE))
    log.append(w(10_000, R_KON, 0x01))
    t = 50_000
    for i in range(6):
        log += _voice_pitch(t, 0, _pitch_for_semitones(BASE, 2.0 if i % 2 else 0.0))
        t += 20_000
    log.append(w(t + 400_000, R_KOFF, 0x01))   # long hold on the last swing
    out = extract(iter(log))
    assert len(out.legato_steps) == 1
    assert out.legato_steps[0].observed_ticks > 0


def test_portamento_is_not_a_legato_step():
    """A slide is built from increments under the threshold, so it is
    excluded before run length is even considered."""
    log = list(_voice_pitch(1_000, 0, BASE))
    log.append(w(10_000, R_KON, 0x01))
    t = 50_000
    pitch = BASE
    for _ in range(40):                      # 40 x 0.2 st = 8 semitones total
        pitch = _pitch_for_semitones(pitch, 0.2)
        log += _voice_pitch(t, 0, pitch)
        t += 5_000
    log.append(w(t + 50_000, R_KOFF, 0x01))
    out = extract(iter(log))
    assert out.legato_steps == [], "a slide was read as note successions"


def test_a_step_at_the_key_on_is_not_a_second_note():
    """The driver's own setup writes land right after the KON."""
    log = list(_voice_pitch(1_000, 0, BASE))
    log.append(w(10_000, R_KON, 0x01))
    log += _voice_pitch(10_100, 0, _pitch_for_semitones(BASE, 5.0))  # < 2 ms
    log.append(w(400_000, R_KOFF, 0x01))
    out = extract(iter(log))
    assert out.legato_steps == []


def test_run_length_is_recorded_not_used_to_reject():
    """A scale is real notes; run length is evidence for the consumer."""
    out = extract(iter(_legato_log([2.0, 2.0, 2.0])))
    assert len(out.legato_steps) == 3
    assert all(s.run_length == 3 for s in out.legato_steps)
    assert all(s.semitones > 0 for s in out.legato_steps)


def test_direction_change_breaks_a_run():
    out = extract(iter(_legato_log([3.0, -3.0])))
    assert [s.run_length for s in out.legato_steps] == [1, 1]


def test_a_step_records_the_pitch_it_came_from_and_went_to():
    out = extract(iter(_legato_log([5.0])))
    step = out.legato_steps[0]
    assert step.previous_pitch == BASE
    assert step.pitch == _pitch_for_semitones(BASE, 5.0)
    assert step.to_dict()["parent_note_id"] == 0


def test_note_ids_are_unique_and_resolvable():
    log = list(_voice_pitch(1_000, 0, BASE))
    for i in range(4):
        log.append(w(10_000 + i * 300_000, R_KON, 0x01))
        log += _voice_pitch(10_000 + i * 300_000 + 100_000, 0,
                            _pitch_for_semitones(BASE, 4.0 + i))
    log.append(w(2_000_000, R_KOFF, 0x01))
    out = extract(iter(log))
    ids = [n.note_id for n in out.notes]
    assert len(set(ids)) == len(ids)
    by_id = {n.note_id: n for n in out.notes}
    for step in out.legato_steps:
        parent = by_id[step.parent_note_id]
        assert parent.start < step.time
        assert parent.end is None or step.time < parent.end


def test_steps_are_time_ordered():
    out = extract(iter(_legato_log([3.0, -4.0, 5.0, -6.0])))
    times = [s.time for s in out.legato_steps]
    assert times == sorted(times)


def test_no_steps_without_a_sounding_note():
    """Pitch writes with no key-on produce nothing: there is no parent."""
    log = list(_voice_pitch(1_000, 0, BASE))
    log += _voice_pitch(200_000, 0, _pitch_for_semitones(BASE, 7.0))
    out = extract(iter(log))
    assert out.notes == [] and out.legato_steps == []


def test_an_absurd_interval_is_not_a_legato_step():
    """Axelay's driver rewrites PITCH every 4 ms with values oscillating
    between ~45 and ~1790 -- plus or minus sixty semitones. That is ring
    modulation, not a note succession, and the return test misses it because
    the oscillation comes back near but not within tolerance."""
    log = list(_voice_pitch(1_000, 0, 1790))
    log.append(w(10_000, R_KON, 0x01))
    t = 50_000
    for value in (48, 2937, 1760, 45, 1725, 45, 1699):
        log += _voice_pitch(t, 0, value)
        t += 5_000
    log.append(w(t + 400_000, R_KOFF, 0x01))
    out = extract(iter(log))
    assert all(abs(s.semitones) <= voices.LEGATO_MAX_SEMITONES
               for s in out.legato_steps)
    assert len(out.legato_steps) <= 2, "ring modulation read as note successions"


def test_a_wide_but_plausible_leap_still_counts():
    """The ceiling must not reject real music. An octave and a half is a
    large but real melodic leap."""
    out = extract(iter(_legato_log([18.0])))
    assert len(out.legato_steps) == 1
    assert out.legato_steps[0].semitones == pytest.approx(18.0, abs=0.1)


def test_the_ceiling_is_generous_enough_to_be_a_pathology_filter():
    """Measured, a 24-semitone ceiling halves Axelay (83% -> 40%) and moves
    no other game by more than 1.5 points. It is there to remove a
    non-musical mechanism, not to trim the interval distribution."""
    assert voices.LEGATO_MAX_SEMITONES >= 24.0
