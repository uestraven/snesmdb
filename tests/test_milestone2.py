"""Milestone 2: metadata, validation gate, composer-disjoint splits."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from snesmdb import splits as sp
from snesmdb.spcfile import SpcError, load, parse_id666
from snesmdb.validate import compare, detect_onsets
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


# --- validation gate ------------------------------------------------------


def test_the_signal_start_counts_as_an_onset() -> None:
    """Audio beginning at t=0 has no quiet frame before it to rise from, so a
    rise-only detector misses it -- and nearly every track starts at t=0, so
    every score came out exactly one onset short. A gate with a systematic
    bias is the thing you end up tuning thresholds against."""
    rate = 32000
    samples = [0.5 if i < rate // 10 else 0.0 for i in range(rate)]
    onsets = detect_onsets(samples, rate)
    assert onsets, "a signal starting at t=0 must register an onset"
    assert onsets[0] == pytest.approx(0.0, abs=0.005)


def test_perfect_agreement_scores_one() -> None:
    starts = [int(t * CLOCK_RATE) for t in (0.0, 0.3, 0.6)]
    result = compare(starts, [0.0, 0.3, 0.6])
    assert result.precision == 1.0 and result.recall == 1.0
    assert result.score == 1.0


def test_an_invented_note_costs_precision_and_a_missed_one_costs_recall() -> None:
    starts = [int(t * CLOCK_RATE) for t in (0.0, 0.3, 0.9)]
    result = compare(starts, [0.0, 0.3, 0.6])
    assert result.unsupported_notes == 1  # 0.9 has no audio behind it
    assert result.unexplained_audio == 1  # 0.6 was not extracted
    assert result.precision < 1.0 and result.recall < 1.0


def test_two_notes_cannot_claim_the_same_audio_onset() -> None:
    """Without one-to-one matching, a burst of spurious notes near one real
    onset would score as perfect precision."""
    starts = [int(t * CLOCK_RATE) for t in (0.300, 0.302, 0.304)]
    result = compare(starts, [0.300])
    assert result.n_matched == 1
    assert result.unsupported_notes == 2


def test_the_score_cannot_be_rescued_by_one_good_direction() -> None:
    """Harmonic mean: 100% recall with 10% precision is not a pass."""
    starts = [int(t * CLOCK_RATE) for t in (0.0,)] + [
        int((5.0 + i * 0.5) * CLOCK_RATE) for i in range(9)
    ]
    result = compare(starts, [0.0])
    assert result.recall == 1.0
    assert result.score < 0.25


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
