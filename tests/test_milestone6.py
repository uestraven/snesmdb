"""Milestone 6: MIDI export, the expressive score, and what publishing drops."""

from __future__ import annotations

import struct

import pytest

from snesmdb import midi, scores
from snesmdb.grid import Grid

ROW = 8192


def _note(voice, start, end, midi_note, vl=40, vr=40, srcn=0):
    return {
        "voice": voice, "start": start, "end": end, "midi_note": midi_note,
        "volume_left": vl, "volume_right": vr, "srcn": srcn, "noise": False,
        "start_sec": start / 1_024_000, "end_sec": (end / 1_024_000) if end else None,
    }


# --- an independent parse, rather than trusting the writer ----------------


def _parse(data: bytes):
    """Minimal MIDI reader: returns (format, ppq, [events per track])."""
    assert data[:4] == b"MThd"
    length = struct.unpack(">I", data[4:8])[0]
    fmt, n_tracks, ppq = struct.unpack(">HHH", data[8 : 8 + length])
    pos = 8 + length
    tracks = []
    while pos < len(data):
        assert data[pos : pos + 4] == b"MTrk", data[pos : pos + 4]
        size = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + size]
        pos += 8 + size
        events = []
        i = 0
        clock = 0
        while i < len(body):
            delta = 0
            while True:
                byte = body[i]
                i += 1
                delta = (delta << 7) | (byte & 0x7F)
                if not byte & 0x80:
                    break
            clock += delta
            status = body[i]
            i += 1
            if status == 0xFF:
                meta = body[i]
                i += 1
                meta_len = 0
                while True:
                    byte = body[i]
                    i += 1
                    meta_len = (meta_len << 7) | (byte & 0x7F)
                    if not byte & 0x80:
                        break
                events.append((clock, "meta", meta, body[i : i + meta_len]))
                i += meta_len
            else:
                assert status & 0x80, f"running status at {i}: {status:#x}"
                a, b = body[i], body[i + 1]
                i += 2
                events.append((clock, status & 0xF0, status & 0x0F, (a, b)))
        tracks.append(events)
    assert len(tracks) == n_tracks
    return fmt, ppq, tracks


def test_the_file_is_a_well_formed_type_1_midi() -> None:
    notes = [_note(0, 0, 4 * ROW, 60), _note(1, ROW, 3 * ROW, 67)]
    fmt, ppq, tracks = _parse(midi.from_notes(notes, render_ticks=8 * ROW, name="x"))
    assert fmt == 1
    assert ppq == midi.PPQ
    assert len(tracks) == 9  # conductor plus eight voices
    for events in tracks:
        assert events[-1][1] == "meta" and events[-1][2] == 0x2F  # end of track


def test_every_note_on_is_matched_by_a_note_off() -> None:
    """A stuck note is the classic failure of a hand-rolled MIDI writer."""
    notes = [
        _note(0, 0, ROW, 60), _note(0, ROW, 2 * ROW, 60),  # re-key, same pitch
        _note(0, 2 * ROW, 3 * ROW, 64), _note(3, 0, 5 * ROW, 48),
    ]
    _fmt, _ppq, tracks = _parse(midi.from_notes(notes, render_ticks=6 * ROW))
    for events in tracks:
        sounding: dict[tuple[int, int], int] = {}
        for _clock, kind, channel, payload in events:
            if kind == 0x90:
                sounding[(channel, payload[0])] = sounding.get((channel, payload[0]), 0) + 1
            elif kind == 0x80:
                sounding[(channel, payload[0])] = sounding.get((channel, payload[0]), 0) - 1
        assert all(v == 0 for v in sounding.values()), sounding


def test_a_rekeyed_pitch_is_released_before_it_is_struck_again() -> None:
    notes = [_note(0, 0, ROW, 60), _note(0, ROW, 2 * ROW, 60)]
    _fmt, _ppq, tracks = _parse(midi.from_notes(notes, render_ticks=3 * ROW))
    voice0 = [e for e in tracks[1] if e[1] in (0x80, 0x90)]
    kinds = [e[1] for e in voice0]
    assert kinds == [0x90, 0x80, 0x90, 0x80], kinds


def test_percussion_channel_is_never_used() -> None:
    """Channel 9 is General MIDI percussion, and the mapping from a BRR
    sample to a GM drum note is not recoverable, so claiming it would be
    invention."""
    assert 9 not in midi.CHANNEL_FOR_VOICE
    notes = [_note(v, 0, ROW, 60) for v in range(8)]
    _fmt, _ppq, tracks = _parse(midi.from_notes(notes, render_ticks=2 * ROW))
    for events in tracks:
        for _clock, kind, channel, _payload in events:
            if kind in (0x80, 0x90, 0xB0):
                assert channel != 9


def test_no_instrument_is_claimed() -> None:
    """Milestone 5 showed sample identity does not transfer across games, so
    a General MIDI program number here would be fabricated."""
    notes = [_note(0, 0, ROW, 60)]
    _fmt, _ppq, tracks = _parse(midi.from_notes(notes, render_ticks=2 * ROW))
    for events in tracks:
        for _clock, kind, _channel, _payload in events:
            assert kind != 0xC0  # program change


def test_velocity_is_never_zero_for_a_sounding_note() -> None:
    """A zero-velocity note-on IS a note-off in MIDI."""
    notes = [_note(0, 0, ROW, 60, vl=0, vr=0)]
    _fmt, _ppq, tracks = _parse(midi.from_notes(notes, render_ticks=2 * ROW))
    ons = [e for events in tracks for e in events if e[1] == 0x90]
    assert ons and all(e[3][1] >= 1 for e in ons)


def test_unpitched_notes_are_dropped_and_counted() -> None:
    notes = [_note(0, 0, ROW, None), _note(1, 0, ROW, 60), _note(2, 0, ROW, 200.0)]
    info = midi.summary(notes)
    assert info["n_notes"] == 3
    assert info["n_written"] == 1
    assert info["n_unpitched_dropped"] == 1
    assert info["n_out_of_range_dropped"] == 1


def test_phase_inversion_is_counted_as_a_loss() -> None:
    """Two games invert phase on over half their notes and MIDI cannot say so."""
    notes = [_note(0, 0, ROW, 60, vl=40, vr=-40)]
    assert midi.summary(notes)["n_phase_inverted_flattened"] == 1


def test_pan_is_written_only_when_off_centre() -> None:
    centred = midi.from_notes([_note(0, 0, ROW, 60, vl=40, vr=40)], render_ticks=2 * ROW)
    panned = midi.from_notes([_note(0, 0, ROW, 60, vl=5, vr=60)], render_ticks=2 * ROW)
    controllers = lambda d: [  # noqa: E731
        e for events in _parse(d)[2] for e in events if e[1] == 0xB0
    ]
    assert controllers(centred) == []
    assert len(controllers(panned)) == 1
    assert controllers(panned)[0][3][0] == 10  # CC10, pan


def test_an_unterminated_note_still_gets_a_note_off() -> None:
    notes = [_note(0, 0, None, 60)]
    _fmt, _ppq, tracks = _parse(midi.from_notes(notes, render_ticks=4 * ROW))
    offs = [e for events in tracks for e in events if e[1] == 0x80]
    assert len(offs) == 1


# --- the expressive score -------------------------------------------------


def test_expressive_carries_note_velocity_timbre_and_sustain() -> None:
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    # ADSR enabled with sustain level 7 holds full scale, so sustain == velocity.
    notes = [_note(0, 0, 2 * ROW, 60, vl=30, vr=50, srcn=7)]
    notes[0].update({"adsr1": 0x80, "adsr2": 0xE0})
    out = scores.expressive(notes, g, {7: 3}, render_ticks=4 * ROW)
    assert out["channels"] == ("note", "velocity", "timbre_class", "sustain")
    assert out["voices"][0][0] == [60, 40, 3, 40]
    assert out["voices"][0][1] == [60, 40, 3, 40]
    assert out["voices"][0][2] == [0, 0, -1, 0]
    assert out["timbre_classes_present"] == [3]


def test_appending_sustain_did_not_move_the_first_three_channels() -> None:
    """A consumer indexing 0..2 must be unaffected by the new channel."""
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    notes = [_note(0, 0, 2 * ROW, 60, vl=30, vr=50, srcn=7)]
    notes[0].update({"adsr1": 0x80, "adsr2": 0x60})       # sustain level 3
    cell = scores.expressive(notes, g, {7: 3}, render_ticks=4 * ROW)["voices"][0][0]
    assert cell[:3] == [60, 40, 3]
    assert cell[3] != cell[1], "a decaying note must differ from its attack"


def test_sustain_level_scales_the_sustain_channel() -> None:
    """The 20% of notes this exists for: VOL alone overstates them.

    Sustain level 3 settles at 3*256 of 2047, so a note struck at velocity 40
    holds at about 15 -- and before this channel existed the score said 40.
    """
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    seen = {}
    for level in (0, 3, 7):
        notes = [_note(0, 0, 2 * ROW, 60, vl=40, vr=40, srcn=7)]
        notes[0].update({"adsr1": 0x80, "adsr2": level << 5})
        cell = scores.expressive(notes, g, None, render_ticks=4 * ROW)["voices"][0][0]
        seen[level] = cell[3]
        assert cell[1] == 40, "the attack is VOL and must not change"
    assert seen[0] == 0, "sustain level 0 decays to silence"
    assert seen[7] == 40, "sustain level 7 holds full scale"
    assert 0 < seen[3] < 40
    assert seen[0] < seen[3] < seen[7]


def test_a_staccato_pluck_and_a_held_horn_are_now_distinguishable() -> None:
    """The exact failure this channel removes: equal VOL, different envelope."""
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    cells = []
    for adsr2 in (0x00, 0xE0):                      # SL 0 vs SL 7
        notes = [_note(0, 0, 2 * ROW, 60, vl=40, vr=40, srcn=7)]
        notes[0].update({"adsr1": 0x80, "adsr2": adsr2})
        cells.append(
            scores.expressive(notes, g, None, render_ticks=4 * ROW)["voices"][0][0]
        )
    assert cells[0][1] == cells[1][1], "identical VOL, so identical velocity"
    assert cells[0] != cells[1], "but the rows must not be identical"


def test_direct_gain_sets_sustain_from_the_gain_register() -> None:
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    notes = [_note(0, 0, 2 * ROW, 60, vl=40, vr=40, srcn=7)]
    notes[0].update({"adsr1": 0x00, "adsr2": 0x00, "gain": 64})   # env 1024/2047
    cell = scores.expressive(notes, g, None, render_ticks=4 * ROW)["voices"][0][0]
    assert 0 < cell[3] < 40


def test_an_unreadable_envelope_is_minus_one_not_silent() -> None:
    """A ramping GAIN mode cannot be read from a key-on. Zero would claim the
    note is silent, which would mute exactly the most expressive drivers."""
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    notes = [_note(0, 0, 2 * ROW, 60, vl=40, vr=40, srcn=7)]
    notes[0].update({"adsr1": 0x00, "adsr2": 0x00, "gain": (4 << 5) | 0x18})
    cell = scores.expressive(notes, g, None, render_ticks=4 * ROW)["voices"][0][0]
    assert cell[3] == -1


def test_a_missing_codebook_is_minus_one_not_class_zero() -> None:
    """Writing 0 would make "no information" indistinguishable from class 0."""
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=2)
    out = scores.expressive([_note(0, 0, ROW, 60, srcn=7)], g, None, render_ticks=2 * ROW)
    assert out["voices"][0][0][2] == -1


def test_expressive_states_which_timbre_claim_is_validated() -> None:
    """Milestone 5 validated only the binary split, so the score says so."""
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=2)
    out = scores.expressive([_note(0, 0, ROW, 60)], g, {0: 1}, render_ticks=2 * ROW)
    assert out["timbre_validated"] == "tonal_vs_percussive_only"


def test_no_grid_means_no_expressive_score() -> None:
    out = scores.expressive([_note(0, 0, ROW, 60)], Grid(found=False), {}, ROW)
    assert out["n_rows"] == 0 and out["voices"] == []


def test_expressive_agrees_with_separated_on_where_notes_are() -> None:
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=6)
    notes = [_note(0, 0, 3 * ROW, 60), _note(2, ROW, 2 * ROW, 72)]
    built = scores.build(notes, g, render_ticks=6 * ROW)
    expr = scores.expressive(notes, g, {}, render_ticks=6 * ROW)
    for voice in range(scores.N_VOICES):
        for row in range(built.n_rows):
            assert (built.separated[voice][row] != 0) == (
                expr["voices"][voice][row][0] != 0
            )
