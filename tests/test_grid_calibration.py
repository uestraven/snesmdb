"""The grid calibration set: a listening test for a thing no statistic settles.

These tests guard one property above all: THE CLICK MUST BE LISTENABLE. The
first version of this tool clicked the raw grid period, which is a tracker row
and not a beat -- 74% of the corpus runs faster than 8 rows/second, so the
metronome came out as a buzz and the 25 files were worthless for their only
purpose. Nothing in the MIDI was malformed; the files parsed perfectly. The
defect was audible and invisible to every check that existed.
"""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "grid_calibration",
    Path(__file__).resolve().parent.parent / "tools" / "grid_calibration.py",
)
gc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gc)

TICKS = gc.TICKS


def _parse(data: bytes):
    """Minimal independent MIDI reader, so a test cannot pass by symmetry."""
    assert data[:4] == b"MThd"
    header_len = struct.unpack(">I", data[4:8])[0]
    fmt, n_tracks, ppq = struct.unpack(">HHH", data[8 : 8 + header_len])
    pos = 8 + header_len
    tracks = []
    while pos < len(data):
        assert data[pos : pos + 4] == b"MTrk"
        length = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + length]
        pos += 8 + length
        events, i, now, running = [], 0, 0, None
        while i < len(body):
            delta = 0
            while True:
                byte = body[i]
                i += 1
                delta = (delta << 7) | (byte & 0x7F)
                if not byte & 0x80:
                    break
            now += delta
            status = body[i]
            if status < 0x80:
                status = running
            else:
                i += 1
                running = status
            if status == 0xFF:
                meta = body[i]
                i += 1
                size = 0
                while True:
                    byte = body[i]
                    i += 1
                    size = (size << 7) | (byte & 0x7F)
                    if not byte & 0x80:
                        break
                i += size
                if meta == 0x2F:
                    break
            elif status & 0xF0 in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                events.append((now, status & 0xF0, status & 0x0F, body[i], body[i + 1]))
                i += 2
            elif status & 0xF0 in (0xC0, 0xD0):
                i += 1
            else:
                raise AssertionError(hex(status))
        tracks.append(events)
    assert len(tracks) == n_tracks
    return fmt, ppq, tracks


def _clicks_per_second(track, ppq):
    ons = [e for e in track if e[1] == 0x90]
    span = (ons[-1][0] - ons[0][0]) / ppq / (gc.midi_mod.BPM / 60.0)
    return (len(ons) - 1) / span


# --------------------------------------------------------------------------
# beat_multiple: the fix for the buzz
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rows_per_second", [1.2, 2.5, 5, 9.2, 13.3, 43, 80, 190, 250, 1000])
def test_click_lands_in_a_plausible_tempo_range(rows_per_second):
    """Whatever the row rate, the click must come out as a tempo."""
    period = int(round(TICKS / rows_per_second))
    multiple = gc.beat_multiple(period)
    beat_seconds = period * multiple / TICKS
    assert gc.MIN_BEAT_SECONDS <= beat_seconds <= gc.MAX_BEAT_SECONDS, (
        f"{rows_per_second} rows/s -> {60 / beat_seconds:.0f} BPM, outside the "
        f"range a listener can judge as a pulse"
    )


def test_beat_multiple_is_a_whole_number_of_rows():
    """The click may not land between rows: that would test the wrong thing.

    A click off the grid would be judged as a bad grid when it is only a bad
    metronome, so the multiple must come from the fixed list.
    """
    for rows_per_second in (3, 17, 62.5, 250):
        period = int(round(TICKS / rows_per_second))
        assert gc.beat_multiple(period) in gc.BEAT_MULTIPLES


def test_a_very_slow_grid_clicks_every_row():
    """At 2.5 rows/second the row already IS a beat; do not slow it further."""
    assert gc.beat_multiple(int(TICKS / 2.5)) == 1


def test_a_fast_grid_is_divided_rather_than_clicked_raw():
    """The regression that made the first set useless."""
    period = int(TICKS / 250.0)
    multiple = gc.beat_multiple(period)
    assert multiple > 1
    assert 250.0 / multiple < 4.0


def test_beat_multiple_prefers_the_range_over_proximity_to_120bpm():
    """A multiple inside the range wins even if one outside sits nearer 120.

    Guards the `inside or pool` fallback: without it the nearest-to-0.5s rule
    alone could pick a multiple that is marginally closer but unlistenable.
    """
    # 1.0 rows/sec: multiple 1 gives 60 BPM (inside), and no smaller option
    # exists, so the range must be what decides.
    period = TICKS
    multiple = gc.beat_multiple(period)
    assert gc.MIN_BEAT_SECONDS <= period * multiple / TICKS <= gc.MAX_BEAT_SECONDS


# --------------------------------------------------------------------------
# the click track itself
# --------------------------------------------------------------------------

def _bare_midi(n_tracks=1):
    body = bytearray()
    body += gc._vlq(0) + b"\xff\x03\x04test"
    body += gc._vlq(0) + b"\xff\x2f\x00"
    track = b"MTrk" + struct.pack(">I", len(body)) + bytes(body)
    header = b"MThd" + struct.pack(">I", 6) + struct.pack(
        ">HHH", 1, n_tracks, gc.midi_mod.PPQ
    )
    return header + track * n_tracks


def test_with_click_increments_the_header_track_count():
    data = gc.with_click(_bare_midi(3), TICKS // 4, 0, 4 * TICKS, rows_per_beat=2)
    fmt, ppq, tracks = _parse(data)
    assert fmt == 1 and len(tracks) == 4


def test_click_is_on_the_percussion_channel_only():
    """Channel 10 (index 9) is the one channel the music exporter never uses,
    so the click can never be mistaken for an extracted voice."""
    data = gc.with_click(_bare_midi(), TICKS // 4, 0, 8 * TICKS, rows_per_beat=2)
    _, _, tracks = _parse(data)
    ons = [e for e in tracks[-1] if e[1] == 0x90]
    assert ons and {e[2] for e in ons} == {gc.CLICK_CHANNEL}


def test_two_clicks_never_sound_at_once():
    """A note-off that lands after the next note-on swallows the click."""
    for rows_per_beat in (1, 2, 4, 16, 128):
        data = gc.with_click(
            _bare_midi(), TICKS // 100, 0, 10 * TICKS, rows_per_beat=rows_per_beat
        )
        _, _, tracks = _parse(data)
        depth = 0
        for event in sorted(tracks[-1], key=lambda e: e[0]):
            depth += 1 if event[1] == 0x90 else -1
            assert depth <= 1, f"overlapping clicks at {rows_per_beat} rows/beat"


def test_every_click_is_released():
    data = gc.with_click(_bare_midi(), TICKS // 8, 0, 6 * TICKS, rows_per_beat=4)
    _, _, tracks = _parse(data)
    ons = [e for e in tracks[-1] if e[1] == 0x90]
    offs = [e for e in tracks[-1] if e[1] == 0x80]
    assert len(ons) == len(offs) > 0


def test_the_bar_is_accented():
    data = gc.with_click(_bare_midi(), TICKS // 4, 0, 10 * TICKS, rows_per_beat=1)
    _, _, tracks = _parse(data)
    ons = [e for e in tracks[-1] if e[1] == 0x90]
    notes = [e[3] for e in ons]
    assert notes[0] == gc.CLICK_ACCENT
    assert notes[1 : gc.ACCENT_EVERY] == [gc.CLICK_NOTE] * (gc.ACCENT_EVERY - 1)
    assert notes[gc.ACCENT_EVERY] == gc.CLICK_ACCENT


def test_clicking_starts_before_the_phase():
    """A grid whose phase is late must still click through the opening bars.

    Otherwise the listener hears silence exactly where the question is whether
    the grid caught the downbeat.
    """
    period = TICKS // 4
    data = gc.with_click(_bare_midi(), period, 3 * period, 8 * TICKS, rows_per_beat=1)
    _, ppq, tracks = _parse(data)
    assert [e for e in tracks[-1] if e[1] == 0x90][0][0] == 0


def test_click_phase_tracks_the_inferred_phase():
    """The click must sit ON the grid, offset included -- that is the test.

    A click track that ignored the phase would be a different experiment: the
    listener would be judging the period alone, and a correct period with the
    downbeat on the off-beat would come back as 'yes'.
    """
    period = TICKS // 2          # 0.5 s, so 120 BPM at one click per row
    phase = period // 4          # a quarter-row offset
    data = gc.with_click(_bare_midi(), period, phase, 6 * TICKS, rows_per_beat=1)
    _, ppq, tracks = _parse(data)
    pulses = [e[0] for e in tracks[-1] if e[1] == 0x90]
    per_beat = ppq * (gc.midi_mod.BPM / 60.0) * (period / TICKS)
    offset = phase / TICKS * (gc.midi_mod.BPM / 60.0) * ppq
    assert pulses[0] == pytest.approx(offset, abs=1), "first click is off the phase"
    for index, pulse in enumerate(pulses):
        assert abs(pulse - (offset + index * per_beat)) <= 1, (index, pulse)
    assert len(pulses) > 5


def test_a_real_grid_yields_a_listenable_click():
    """End to end, at the corpus median of 13.3 rows/second."""
    period = int(round(TICKS / 13.3))
    multiple = gc.beat_multiple(period)
    data = gc.with_click(_bare_midi(), period, 0, 30 * TICKS, rows_per_beat=multiple)
    _, ppq, tracks = _parse(data)
    rate = _clicks_per_second(tracks[-1], ppq)
    assert 0.8 <= rate <= 4.0, f"{rate:.2f} clicks/second is not a metronome"


def test_bands_straddle_the_threshold_the_tick_evidence_points_at():
    """The set exists to test a threshold, so it must sample both sides of it.

    The driver tick puts the break at 0.70, not the 0.80 the pipeline uses, so
    the bands bracket 0.70. A set entirely above the bar could only confirm it.
    """
    edges = [low for low, _ in gc.BANDS] + [gc.BANDS[-1][1]]
    assert any(low < 0.70 for low, _ in gc.BANDS)
    assert any(low >= 0.70 for low, _ in gc.BANDS)
    assert 0.70 in edges, "0.70 must be a band edge for the comparison to be clean"
    assert edges == sorted(edges)
