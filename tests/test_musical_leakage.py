"""The leakage search's sensitivity and its specificity, both pinned.

A search that reports zero matches is worthless without evidence it could
have found one. The first version of this search reported 852 cross-split
"matches" that were almost entirely one voice with 1,053 attacks on a
SINGLE pitch -- 1,053 zero intervals -- matching every other repetitive
voice in the corpus. Tightening the filter took the count to zero, which
looks like a result and could equally be a broken tool.

So both directions are tested:

    SENSITIVITY   a composition planted in another split, transposed, must
                  be found -- otherwise "no leakage" means nothing
    SPECIFICITY   ostinati, scales, trills and periodic figures must not be
                  reported, because declaring them leakage would make the
                  audit useless in the other direction

The transposition case also checks that the three representations differ as
intended: `exact_pitch` must MISS a transposed quote and `interval` must
catch it. If both behaved the same, one of them would be decoration.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "musical_leakage", ROOT / "tools" / "audit_musical_leakage.py")
leak = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(leak)

#: A melody with real variety: 48 notes, no short period, many intervals.
MELODY = [
    60, 62, 64, 67, 65, 62, 59, 60, 64, 69, 67, 64, 62, 65, 69, 71,
    72, 69, 65, 62, 60, 64, 67, 71, 74, 72, 69, 65, 64, 60, 57, 59,
    62, 66, 69, 73, 71, 68, 64, 61, 59, 63, 66, 70, 68, 65, 61, 58,
]


def _events(notes, voice=0, step=0.25):
    return [
        {"event_id": i, "origin": "key_on", "voice": voice,
         "midi_note": float(n), "pitch_status": "estimated",
         "onset_sec": i * step, "duration_sec": step * 0.9}
        for i, n in enumerate(notes)
    ]


def _dist(root: Path, tracks):
    """`tracks` is [(track_id, game, split, events)]."""
    (root / "events").mkdir(parents=True, exist_ok=True)
    entries = []
    for tid, game, split, events in tracks:
        rel = f"events/{tid.replace(':', '_')}.json.gz"
        (root / rel).write_bytes(gzip.compress(json.dumps({
            "schema": "snesmdb.events.v4", "track_id": tid,
            "events": events}).encode()))
        entries.append({"track_id": tid, "game": game, "split": split,
                        "title": tid, "events": rel})
    (root / "index.json").write_text(json.dumps({
        "schema": "snesmdb.index.v1", "tracks": entries}))
    return root


def _search(dist: Path, tmp_path: Path, **kw):
    out = tmp_path / "leak.json"
    argv = sys.argv
    sys.argv = ["audit_musical_leakage.py", str(dist), str(out)]
    for key, value in kw.items():
        sys.argv += [f"--{key.replace('_', '-')}", str(value)]
    try:
        leak.main()
    finally:
        sys.argv = argv
    return json.loads(out.read_text())


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------

def test_a_transposed_duplicate_across_splits_is_found(tmp_path):
    """The case the audit exists for: the same composition in two games,
    landing in two splits, in a different key."""
    dist = _dist(tmp_path / "d", [
        ("a:1", "Game A", "train", _events(MELODY)),
        ("b:1", "Game B", "test", _events([n + 5 for n in MELODY])),
    ])
    got = _search(dist, tmp_path)
    assert got["cross_split_matches"] > 0, (
        "a planted transposed duplicate must be found, or a zero result "
        "from the real corpus means nothing"
    )
    methods = {f["method"] for f in got["findings"]}
    assert "interval" in methods, "transposition-invariance did not fire"
    assert "exact_pitch" not in methods, (
        "exact_pitch must MISS a transposed quote; if it matched, the three "
        "representations are not doing different work"
    )
    best = max(got["findings"], key=lambda f: f["run_tokens"])
    assert best["evidence_strength"] == "complete_duplicate"
    assert best["a"]["coverage_of_voice"] > 0.9


def test_an_untransposed_duplicate_is_found_by_exact_pitch(tmp_path):
    dist = _dist(tmp_path / "d", [
        ("a:1", "Game A", "train", _events(MELODY)),
        ("b:1", "Game B", "valid", _events(MELODY)),
    ])
    got = _search(dist, tmp_path)
    assert "exact_pitch" in {f["method"] for f in got["findings"]}


# ---------------------------------------------------------------------------
# Specificity
# ---------------------------------------------------------------------------

def test_a_single_pitch_ostinato_is_not_reported(tmp_path):
    """The real false positive: `ed2-138` voice 7 carries 1,053 attacks on
    one pitch, so its interval sequence is 1,053 zeros, and it matched 16
    unrelated tracks across Zelda, Plok!, Chrono Trigger and Earthbound."""
    dist = _dist(tmp_path / "d", [
        ("a:1", "Game A", "train", _events([60] * 300)),
        ("b:1", "Game B", "test", _events([72] * 300)),
    ])
    got = _search(dist, tmp_path)
    assert got["cross_split_matches"] == 0


def test_a_repeating_figure_is_not_reported(tmp_path):
    """An arpeggio looping every four notes is a driver pattern, not a
    shared theme, however long it runs."""
    figure = [60, 64, 67, 72] * 100
    dist = _dist(tmp_path / "d", [
        ("a:1", "Game A", "train", _events(figure)),
        ("b:1", "Game B", "test", _events([n + 3 for n in figure])),
    ])
    got = _search(dist, tmp_path)
    assert got["cross_split_matches"] == 0


def test_a_scale_is_not_reported(tmp_path):
    """Two games playing a chromatic run share a convention, not music."""
    scale = list(range(48, 96)) * 6
    dist = _dist(tmp_path / "d", [
        ("a:1", "Game A", "train", _events(scale)),
        ("b:1", "Game B", "test", _events(scale)),
    ])
    got = _search(dist, tmp_path)
    assert got["cross_split_matches"] == 0


def test_a_match_within_one_split_is_not_leakage(tmp_path):
    """Two train tracks sharing material is not an evaluation problem."""
    dist = _dist(tmp_path / "d", [
        ("a:1", "Game A", "train", _events(MELODY)),
        ("b:1", "Game B", "train", _events(MELODY)),
    ])
    assert _search(dist, tmp_path)["cross_split_matches"] == 0


def test_two_tracks_of_one_game_are_never_compared(tmp_path):
    """A game cannot span splits, so a within-game match is irrelevant and
    would otherwise flood the report from internal repetition."""
    dist = _dist(tmp_path / "d", [
        ("a:1", "Game A", "train", _events(MELODY)),
        ("a:2", "Game A", "test", _events(MELODY)),
    ])
    assert _search(dist, tmp_path)["cross_split_matches"] == 0


# ---------------------------------------------------------------------------
# The diagnostics, directly
# ---------------------------------------------------------------------------

def test_run_diagnostics_identify_a_constant_pitch_run():
    diag = leak.run_diagnostics([0] * 64, "interval")
    assert diag["distinct_nonzero_intervals"] == 0
    assert diag["zero_interval_share"] == 1.0


def test_run_diagnostics_find_a_short_period():
    diag = leak.run_diagnostics([4, 3, 5, -12] * 16, "interval")
    assert diag["shortest_period"] == 4


def test_run_diagnostics_accept_varied_material():
    intervals = [MELODY[i] - MELODY[i - 1] for i in range(1, len(MELODY))]
    diag = leak.run_diagnostics(intervals, "interval")
    assert diag["distinct_nonzero_intervals"] >= \
        leak.MIN_DISTINCT_NONZERO_INTERVALS
    assert diag["shortest_period"] >= leak.MIN_PERIOD


def test_the_report_states_that_a_negative_result_is_not_a_proof(tmp_path):
    dist = _dist(tmp_path / "d", [
        ("a:1", "Game A", "train", _events(MELODY)),
    ])
    got = _search(dist, tmp_path)
    joined = " ".join(got["coverage_limits"]).upper()
    assert "DOES NOT ESTABLISH" in joined
