"""Milestone 2: metadata, validation gate, composer-disjoint splits."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from snesmdb import splits as sp
from snesmdb.spcfile import SpcError, load, parse_id666
from snesmdb.checks import run as run_checks
from snesmdb.voices import CLOCK_RATE

ROOT = Path(__file__).resolve().parent.parent


def _generator():
    spec = importlib.util.spec_from_file_location(
        "make_test_spc", ROOT / "tools" / "make_test_spc.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- ID666 ----------------------------------------------------------------


def test_the_tag_round_trips_through_the_container(tmp_path) -> None:
    data = _generator().build(
        3, title="A Title", game="A Game", composer="A Composer"
    )
    path = tmp_path / "t.spc"
    path.write_bytes(data)
    spc = load(path)
    assert (spc.tag.title, spc.tag.game, spc.tag.composer) == (
        "A Title", "A Game", "A Composer"
    )
    assert spc.tag.layout == "text"
    assert len(spc.aram) == 0x10000
    assert spc.sha256


def test_fixed_width_numeric_fields_are_not_truncated(tmp_path) -> None:
    """ID666 pads `seconds` and `fade` with DIGITS, not a NUL terminator.

    Reserving a byte for a terminator read "030" seconds as 3 and a "05000" ms
    fade as 500 -- plausible numbers, silently wrong by a factor of ten.
    """
    path = tmp_path / "t.spc"
    path.write_bytes(_generator().build(2))
    tag = load(path).tag
    assert tag.seconds == 30, tag.to_dict()
    assert tag.fade_ms == 5000, tag.to_dict()


def test_the_tag_presence_flag_follows_the_spc_spec_not_our_guess() -> None:
    """0x23 == 26 (0x1A) means the header CONTAINS ID666 info; 27 (0x1B)
    means it does not.

    This was implemented inverted, with the fixture generator inverted to
    match, so the suite was green while all 82 real Final Fantasy VI tracks
    reported no tag at all -- despite carrying "Nobuo Uematsu" at 0xB1. The
    assertions here are on raw bytes so the fixture cannot agree with the bug
    again.
    """
    base = bytearray(b"SNES-SPC700 Sound File Data v0.30".ljust(0x100, b"\x00"))
    base[0x2E : 0x2E + 5] = b"Title"
    base[0xB1 : 0xB1 + 8] = b"Composer"

    present = bytearray(base)
    present[0x23] = 0x1A
    tag = parse_id666(bytes(present))
    assert tag.layout == "text", tag.layout_reason
    assert tag.title == "Title" and tag.composer == "Composer"

    absent = bytearray(base)
    absent[0x23] = 0x1B
    tag = parse_id666(bytes(absent))
    assert tag.layout == "unknown"
    assert tag.title == "" and tag.composer == ""


def test_a_non_spc_file_is_rejected(tmp_path) -> None:
    path = tmp_path / "bad.spc"
    path.write_bytes(b"not an spc" * 100)
    with pytest.raises(SpcError, match="signature"):
        load(path)


def test_a_truncated_spc_is_rejected_rather_than_read_past_the_end(tmp_path) -> None:
    path = tmp_path / "short.spc"
    path.write_bytes(b"SNES-SPC700 Sound File Data v0.30" + b"\x00" * 100)
    with pytest.raises(SpcError, match="too short"):
        load(path)


# --- structural checks ---------------------------------------------------
#
# These replaced an audio-onset gate that scored 1.0000 on the synthetic
# fixture and 0.151 on real Final Fantasy VI. The real number was the honest
# one: in sustained polyphonic audio the detector fired on envelope ripple
# rather than note attacks, finding 80 onsets where the track had 19 note-ons.
# Nothing here produces a score, because a score invites tuning it until it
# looks acceptable.


R_KON, R_KOFF = 0x4C, 0x5C


def w(t: int, addr: int, data: int) -> dict:
    return {"t": t, "addr": addr, "data": data, "reg": hex(addr), "voice": -1}


def setup_voice(t: int, voice: int, pitch: int) -> list[dict]:
    base = voice * 0x10
    return [
        w(t + 0, base + 0x00, 0x60),
        w(t + 1, base + 0x01, 0x60),
        w(t + 2, base + 0x02, pitch & 0xFF),
        w(t + 3, base + 0x03, (pitch >> 8) & 0x3F),
    ]


def _extraction(log: list[dict]):
    from snesmdb.voices import extract
    return extract(iter(log))


def test_a_track_with_no_notes_fails() -> None:
    report = run_checks(_extraction([]), render_seconds=10.0)
    assert "notes_present" in report.failed
    assert not report.ok


def test_an_unmodelled_register_fails_rather_than_passing_quietly() -> None:
    log = [w(0, 0x1D, 0xFF), *setup_voice(1, 0, 0x0800),
           w(10, R_KON, 0x01), w(CLOCK_RATE * 9, R_KOFF, 0x01)]
    report = run_checks(_extraction(log), render_seconds=10.0)
    assert "no_unhandled_registers" in report.failed


def test_a_note_starting_after_the_render_ended_fails() -> None:
    """The symptom the chunk-relative clock produced: timestamps that do not
    belong to the window they were logged in."""
    log = [*setup_voice(0, 0, 0x0800), w(int(CLOCK_RATE * 99), R_KON, 0x01)]
    report = run_checks(_extraction(log), render_seconds=10.0)
    assert "notes_within_render" in report.failed


def test_every_note_unfinished_fails() -> None:
    """Some notes legitimately ring past a fixed-length render. All of them
    means no key-off was ever seen, so no duration in the track is real."""
    log = [*setup_voice(0, 0, 0x0800), w(10, R_KON, 0x01),
           w(int(CLOCK_RATE * 5), 0x1C, 0x7F)]
    report = run_checks(_extraction(log), render_seconds=10.0)
    assert "some_notes_completed" in report.failed


def test_writes_stopping_early_fails() -> None:
    """A driver that halts leaves the rest of the window silent, and the
    extraction looks fine while covering a fraction of the track."""
    log = [*setup_voice(0, 0, 0x0800), w(10, R_KON, 0x01),
           w(int(CLOCK_RATE * 1), R_KOFF, 0x01)]
    report = run_checks(_extraction(log), render_seconds=60.0)
    assert "writes_span_render" in report.failed


def test_silent_audio_with_extracted_notes_fails() -> None:
    """The one cross-check against the emulator that needs no inference."""
    log = [*setup_voice(0, 0, 0x0800), w(10, R_KON, 0x01),
           w(int(CLOCK_RATE * 9), R_KOFF, 0x01)]
    extraction = _extraction(log)
    assert run_checks(extraction, render_seconds=10.0, peak=20000).ok
    loud_ok = run_checks(extraction, render_seconds=10.0, peak=0)
    assert "audio_not_silent" in loud_ok.failed


def test_a_clean_extraction_passes_every_check() -> None:
    log = [*setup_voice(0, 0, 0x0800), w(10, R_KON, 0x01),
           w(int(CLOCK_RATE * 9), R_KOFF, 0x01)]
    report = run_checks(_extraction(log), render_seconds=10.0, peak=12000)
    assert report.ok, report.to_dict()
    assert not report.failed


# --- composer-disjoint splits ---------------------------------------------


def test_a_shared_composer_forces_two_games_into_one_split() -> None:
    """The case that breaks naive per-game assignment. If two games share a
    composer and land in different splits, that composer spans both, and the
    corpus is no longer comparable to NES-MDB."""
    tracks = {"GameA": ["a1", "a2"], "GameB": ["b1"], "GameC": ["c1"]}
    composers = {"GameA": ["X"], "GameB": ["X"], "GameC": ["Y"]}
    out = sp.assign(tracks, composers, valid_fraction=0.34, test_fraction=0.0)
    assert out.assignment["a1"] == out.assignment["b1"], (
        "games sharing composer X must share a split"
    )
    assert not sp.verify_disjoint(
        out.assignment, {"a1": ["X"], "a2": ["X"], "b1": ["X"], "c1": ["Y"]}
    )


def test_disjointness_is_verified_against_the_assignment_not_assumed() -> None:
    """verify_disjoint must actually catch a violation, or it is decoration."""
    bad = {"t1": "train", "t2": "valid"}
    leaks = sp.verify_disjoint(bad, {"t1": ["Shared"], "t2": ["Shared"]})
    assert leaks == {"shared": ["train", "valid"]}


def test_composer_names_are_matched_case_and_space_insensitively() -> None:
    tracks = {"G1": ["t1"], "G2": ["t2"]}
    composers = {"G1": ["Nobuo Uematsu"], "G2": ["  nobuo uematsu "]}
    out = sp.assign(tracks, composers, valid_fraction=0.5, test_fraction=0.0)
    assert out.assignment["t1"] == out.assignment["t2"]


def test_components_are_reported_so_a_skewed_ratio_can_be_explained() -> None:
    """A prolific composer merges every game they touched into one component,
    which must land whole in one split, so achieved ratios will not match the
    request. The report has to state that rather than hide it."""
    tracks = {f"G{i}": [f"t{i}"] for i in range(10)}
    composers = {f"G{i}": ["Prolific"] for i in range(9)}
    composers["G9"] = ["Someone Else"]
    out = sp.assign(tracks, composers, valid_fraction=0.1, test_fraction=0.1)
    report = out.report()
    assert report["n_components"] == 2
    assert report["largest_component_games"][0] == 9
    assert any(abs(v) > 0.05 for v in report["fraction_error"].values()), (
        "a 9-of-10 component cannot honour a 10% split; say so"
    )
    assert not sp.verify_disjoint(
        out.assignment, {f"t{i}": composers[f"G{i}"] for i in range(10)}
    )
