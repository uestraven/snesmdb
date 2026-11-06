"""Note recovery from a write log. Pure Python -- always runs, never skips."""

from __future__ import annotations

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
