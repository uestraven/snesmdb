"""The publication contract: tests that open files under `dist`.

EVERY TEST HERE READS A PUBLISHED FILE. None calls an extraction or scoring
function to reconstruct what the output should be, because that is exactly how
the defect these tests exist for survived: `scores.uniform_grid` was correct,
benchmarked and committed, `extract.py` wrote a `uniform` block into
`data/out`, and `publish.py` never learned about it -- so the distributable
corpus had no 100 Hz scores at all while every internal measurement passed.
A test that called `scores.build` would have agreed with the implementation and
told us nothing.

The same shape of failure happened twice before: `scores.expressive` was dead
code for two milestones, and the documented rebuild recipe omitted the step
that derived the row clock. In all three cases the internal result was right
and the artifact did not have it.

WHERE THE CORPUS COMES FROM. `SNESMDB_DIST` names the published tree, and
`SNESMDB_OUT` the extraction output it was built from. Both default to the
usual locations. These tests SKIP when the corpus is absent, because no SPC is
redistributable and CI has nothing to publish -- but skipping is itself how
things get missed, so `tools/verify_corpus.py` hard-fails on the same
conditions and `make corpus` runs it. The division is deliberate: these tests
describe the contract, and `verify` enforces it on every build.
"""

from __future__ import annotations

import gzip
import json
import os
import random
from pathlib import Path

import pytest

DIST = Path(os.environ.get(
    "SNESMDB_DIST", Path.home() / "snesmdb-corpus" / "dist"
))
OUT = Path(os.environ.get(
    "SNESMDB_OUT",
    Path(__file__).resolve().parent.parent / "data" / "out",
))

TICKS = 1_024_000
EXPECTED_UNIFORM_HZ = 100.0
EXPECTED_UNIFORM_PERIOD = 10_240


def _need_dist() -> list[dict]:
    index = DIST / "index.json"
    if not index.is_file():
        pytest.skip(
            f"no published corpus at {DIST} -- run `make corpus`. "
            f"verify_corpus.py enforces this on every build."
        )
    return json.loads(index.read_text())


def _published_score(entry: dict) -> dict:
    path = DIST / entry["scores"]
    assert path.is_file(), f"index names {entry['scores']} but it is absent"
    with gzip.open(path, "rt") as handle:
        return json.load(handle)


def _sample(entries: list[dict], n: int = 8) -> list[dict]:
    scored = [e for e in entries if e.get("scores")]
    random.Random(0).shuffle(scored)
    return scored[:n]


# --------------------------------------------------------------------------
# Gate 1: the 100 Hz uniform score is actually published
# --------------------------------------------------------------------------

def test_every_indexed_track_has_a_published_score_file():
    entries = _need_dist()
    missing = [e["track_id"] for e in entries if not e.get("scores")]
    assert not missing, f"{len(missing)} indexed tracks have no score file"


def test_a_published_score_carries_a_uniform_block():
    """The Gate 1 defect. `publish.py` had no `uniform` anything, so the rate
    this project benchmarked at length never reached a distributable file."""
    for entry in _sample(_need_dist()):
        score = _published_score(entry)
        assert "uniform" in score, (
            f"{entry['track_id']}: published score has no `uniform` block, so "
            f"the 100 Hz grid did not reach `dist`"
        )


def test_the_published_uniform_block_states_its_rate_and_period():
    for entry in _sample(_need_dist()):
        uniform = _published_score(entry)["uniform"]
        assert uniform["hz"] == EXPECTED_UNIFORM_HZ
        assert round(uniform["period_ticks"]) == EXPECTED_UNIFORM_PERIOD, (
            "100 Hz must be exactly 10,240 SPC700 ticks, so rows cannot drift"
        )


def test_the_published_uniform_row_count_matches_the_track_length():
    """A row count that disagrees with the track's duration means the grid was
    built against the wrong render window."""
    for entry in _sample(_need_dist()):
        uniform = _published_score(entry)["uniform"]
        expected = int(entry["render_seconds"] * EXPECTED_UNIFORM_HZ) + 1
        assert abs(uniform["n_rows"] - expected) <= 1, (
            f"{entry['track_id']}: {uniform['n_rows']} rows for "
            f"{entry['render_seconds']}s at {EXPECTED_UNIFORM_HZ} Hz"
        )


def test_the_published_uniform_block_has_all_three_formats():
    for entry in _sample(_need_dist()):
        uniform = _published_score(entry)["uniform"]
        for name in ("separated", "blended", "expressive"):
            assert name in uniform, f"{entry['track_id']}: uniform.{name} absent"
        assert len(uniform["separated"]) == 8, "one row-track per DSP voice"
        assert len(uniform["blended"]) == uniform["n_rows"]


def test_the_published_uniform_contents_match_the_extraction_output():
    """THE SAFEGUARD THAT MATTERS: numbers, not key presence.

    A `uniform` block containing the wrong arrays -- stale, truncated, or built
    on a different rate -- would satisfy every check above. This compares the
    published cells against `data/out`, which is the only independent copy.
    """
    entries = _need_dist()
    if not (OUT / "manifest.jsonl").is_file():
        pytest.skip(f"no extraction output at {OUT} to compare against")
    rows = {
        r["track_id"]: r
        for r in (json.loads(l) for l in (OUT / "manifest.jsonl").open())
        if r.get("scores_path")
    }
    compared = 0
    for entry in _sample(entries, 5):
        row = rows.get(entry["track_id"])
        if not row:
            continue
        with gzip.open(OUT / row["scores_path"], "rt") as handle:
            internal = json.load(handle)
        if "uniform" not in internal:
            pytest.skip("extraction output predates the uniform block")
        published = _published_score(entry)["uniform"]
        assert published["separated"] == internal["uniform"]["separated"], (
            f"{entry['track_id']}: published uniform.separated differs from "
            f"the extraction output it was built from"
        )
        assert published["blended"] == internal["uniform"]["blended"]
        compared += 1
    assert compared, "no track could be compared; the safeguard did not run"


def test_the_published_uniform_score_is_not_the_primary_score():
    """Two grids, and they must not be the same array under two names.

    The primary row count lives in `stats.n_rows`, not at the top level --
    this test asserted `score["n_rows"]` and raised KeyError, which looked
    like a data defect and was a test defect. Cross-checked against the
    length of `separated[0]` so it cannot silently read the wrong field again.
    """
    for entry in _sample(_need_dist()):
        score = _published_score(entry)
        primary_rows = score["stats"]["n_rows"]
        assert primary_rows == len(score["separated"][0]), (
            "stats.n_rows disagrees with the published separated score"
        )
        if abs(score["clock"]["hz"] - EXPECTED_UNIFORM_HZ) < 0.01:
            continue        # a track whose timer really runs at 100 Hz
        assert score["uniform"]["n_rows"] != primary_rows, (
            f"{entry['track_id']}: uniform and primary row counts are both "
            f"{primary_rows}, so one grid is not the one it claims"
        )


def test_the_uniform_score_is_shorter_than_a_fast_primary_grid():
    """A 500 Hz driver clock gives five times the rows of a 100 Hz grid, so
    the published uniform score should be materially smaller for those."""
    checked = 0
    for entry in _sample(_need_dist(), 12):
        score = _published_score(entry)
        if score["clock"]["hz"] < 300.0:
            continue
        ratio = score["stats"]["n_rows"] / score["uniform"]["n_rows"]
        assert ratio > 2.5, f"{entry['track_id']}: ratio only {ratio:.2f}"
        checked += 1
    if not checked:
        pytest.skip("no sampled track has a primary clock above 300 Hz")
