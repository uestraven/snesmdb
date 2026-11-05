"""Full path: generate an SPC, run the real SPC700, recover the notes.

This is the test that matters, because it is the only one that exercises the
emulator and the hook. It needs `make` to have run, and it FAILS rather than
skips when the binary is missing -- a skip here would look like coverage of
the extraction path while testing nothing, which is a trap this project's
sibling repo has already fallen into once.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from snesmdb.voices import extract, read_log

ROOT = Path(__file__).resolve().parent.parent
BINARY = ROOT / "build" / "spc_dump"
GENERATOR = ROOT / "tools" / "make_test_spc.py"

#: The pitches `make_test_spc.py` writes, in order. Asserting against these
#: makes the test a round-trip: what the driver wrote must be what we recover.
EXPECTED_PITCHES = [0x0800, 0x0A00, 0x0C00, 0x1000, 0x1400, 0x1800]


def _build_generator():
    spec = importlib.util.spec_from_file_location("make_test_spc", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def extraction(tmp_path_factory):
    if not BINARY.is_file():
        pytest.fail(
            f"{BINARY} is missing -- run `make` first. This test is not "
            "skipped when the binary is absent, on purpose: a skip would "
            "report coverage of the emulator path while exercising none of it."
        )
    tmp = tmp_path_factory.mktemp("e2e")
    spc = tmp / "synthetic.spc"
    spc.write_bytes(_build_generator().build(len(EXPECTED_PITCHES)))

    log = tmp / "writes.jsonl"
    wav = tmp / "out.wav"
    result = subprocess.run(
        [str(BINARY), str(spc), str(log), "3.0", "--wav", str(wav)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert log.is_file() and log.stat().st_size > 0, "the hook logged nothing"
    return extract(read_log(log)), wav


def test_every_note_the_driver_played_is_recovered(extraction) -> None:
    out, _ = extraction
    assert len(out.notes) == len(EXPECTED_PITCHES), out.summary()
    assert [n.pitch for n in out.notes] == EXPECTED_PITCHES


def test_the_recovered_notes_use_one_voice_each_in_order(extraction) -> None:
    out, _ = extraction
    assert [n.voice for n in out.notes] == list(range(len(EXPECTED_PITCHES)))


def test_timestamps_are_monotonic_across_play_chunks(extraction) -> None:
    """The hook reports time relative to the current play() call, so the
    logger has to add a running base. Without it, timestamps ran BACKWARDS at
    every 2048-frame boundary -- a KOFF at 37 ms followed by the next write at
    25 ms -- silently corrupting every duration downstream.
    """
    out, _ = extraction
    starts = [n.start for n in out.notes]
    assert starts == sorted(starts), starts
    # The fixture is deliberately regular: 225 ms notes on a 300 ms period,
    # which also spans several chunk boundaries (a chunk is ~64 ms).
    assert out.last_time > 64 * 1024, "fixture must cross a chunk boundary"
    for note in out.notes:
        assert note.duration is not None
        assert abs(note.duration / 1024 - 225.0) < 1.0, note.to_dict()
    gaps = [b.start - a.start for a, b in zip(out.notes, out.notes[1:])]
    for gap in gaps:
        assert abs(gap / 1024 - 300.0) < 1.0, gaps


def test_the_emulator_actually_produced_audio(extraction) -> None:
    """A log full of writes with silent output would mean the driver ran but
    the DSP never sounded -- the fixture has to be a real playing SPC."""
    import array
    import wave

    _, wav = extraction
    with wave.open(str(wav)) as handle:
        frames = handle.getnframes()
        samples = array.array("h")
        samples.frombytes(handle.readframes(frames))
    peak = max(abs(s) for s in samples)
    assert peak > 1000, f"peak {peak}: the DSP produced no audible output"


def test_the_extractor_handled_every_write(extraction) -> None:
    out, _ = extraction
    assert not out.unhandled, out.unhandled
    assert out.summary()["n_unfinished_notes"] == 0
