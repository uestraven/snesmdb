"""The uniform rate's event-preservation property, as a regression test.

The rate was chosen by benchmarking the real corpus, which tests cannot do --
no SPC is redistributable, so there is nothing to measure in CI. What IS
testable is the property the benchmark established: at 100 Hz a repeated-note
figure at the corpus's fastest spacing survives, and at a coarser rate it does
not. If someone changes `UNIFORM_HZ`, or changes `scores.build` so onsets merge
differently, this fails.

The corpus-wide claim is re-checked on real data by `verify_corpus.py`, which
runs on every `make corpus`. These two together mean the number is not a
one-time justification sitting in a commit message.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from snesmdb import scores

_spec = importlib.util.spec_from_file_location(
    "rate_benchmark",
    Path(__file__).resolve().parent.parent / "tools" / "rate_benchmark.py",
)
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)

TICKS = 1_024_000


def _repeated(hz: float, note: int = 60, voice: int = 0, n: int = 60):
    """A repeated-note figure one row apart at `hz` -- a tremolo."""
    period = TICKS / hz
    gap = int(period)
    return [
        {"voice": voice, "start": i * gap, "end": i * gap + gap,
         "midi_note": note, "volume_left": 40, "volume_right": 40,
         "srcn": 1, "noise": False, "pitch_modulated": False,
         "adsr1": 0x80, "adsr2": 0xE0, "gain": 0,
         "start_sec": 0.0, "end_sec": 0.0}
        for i in range(n)
    ]


def test_the_default_rate_preserves_a_fast_repeated_figure():
    """The property 100 Hz was chosen for.

    On the full corpus it loses 1 repeated attack of 1,458,211 pitched notes.
    At 50 Hz it loses 94, and at 24 Hz 174 -- each one a tremolo or drum roll
    silently rewritten as a single sustained note.
    """
    notes = _repeated(scores.UNIFORM_HZ)
    result = rb.measure([(2.0, notes)], scores.UNIFORM_HZ)
    assert result["repeat_attacks_lost"] == 0
    assert result["collisions"] == 0
    assert result["preserved_pct"] == pytest.approx(100.0)


def test_a_coarser_rate_destroys_it():
    """Proves the test can fail -- otherwise it asserts nothing about the rate.

    A figure spaced for 100 Hz, measured on a 24 Hz grid, must lose attacks.
    """
    notes = _repeated(scores.UNIFORM_HZ)
    result = rb.measure([(2.0, notes)], 24.0)
    assert result["repeat_attacks_lost"] > 0
    assert result["preserved_pct"] < 50.0


def test_repeat_attacks_are_counted_apart_from_collisions():
    """They are different losses. A collision drops a note; a lost repeat
    attack silently rewrites rhythm as duration, which is invisible to anyone
    counting notes."""
    period = TICKS / 100.0
    same = [
        {"voice": 0, "start": 0, "end": int(period), "midi_note": 60},
        {"voice": 0, "start": 10, "end": int(period), "midi_note": 60},
    ]
    other = [
        {"voice": 0, "start": 0, "end": int(period), "midi_note": 60},
        {"voice": 0, "start": 10, "end": int(period), "midi_note": 67},
    ]
    a = rb.measure([(1.0, same)], 100.0)
    b = rb.measure([(1.0, other)], 100.0)
    assert (a["repeat_attacks_lost"], a["collisions"]) == (1, 0)
    assert (b["repeat_attacks_lost"], b["collisions"]) == (0, 1)


def test_collisions_are_counted_per_track_not_pooled():
    """The measurement error that reported 86% onset loss at 24 Hz: notes from
    many tracks pooled into one list collide on (voice, row) because rows only
    mean anything inside a track."""
    notes = [{"voice": 0, "start": 0, "end": 10_000, "midi_note": 60}]
    pooled = rb.measure([(1.0, notes * 5)], 100.0)
    separate = rb.measure([(1.0, list(notes)) for _ in range(5)], 100.0)
    assert pooled["repeat_attacks_lost"] == 4, "pooling must collide"
    assert separate["repeat_attacks_lost"] == 0, "per track must not"


def test_the_rate_is_an_exact_divisor_so_rows_do_not_drift():
    assert float(TICKS / scores.UNIFORM_HZ).is_integer()


def test_offset_error_is_reported_not_only_onset():
    """A note's end is quantised too, and a score that keeps every onset can
    still misreport every duration."""
    notes = [{"voice": 0, "start": 0, "end": 12_345, "midi_note": 60}]
    result = rb.measure([(1.0, notes)], 100.0)
    assert result["offset_err_ms_median"] > 0.0
    assert "onset_err_ms_p95" in result
