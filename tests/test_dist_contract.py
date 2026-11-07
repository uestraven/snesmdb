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
    """The per-track entries. Gate 3 made the index a document, so this reads
    `tracks` where it is one and the whole list where it is still a list."""
    index = DIST / "index.json"
    if not index.is_file():
        pytest.skip(
            f"no published corpus at {DIST} -- run `make corpus`. "
            f"verify_corpus.py enforces this on every build."
        )
    raw = json.loads(index.read_text())
    return raw if isinstance(raw, list) else raw["tracks"]


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


# --------------------------------------------------------------------------
# Gate 2: events.v1 -- the researcher-facing event table
# --------------------------------------------------------------------------

EVENTS_SCHEMA = "snesmdb.events.v3"

#: An absence of recovered pitch must never be readable as extraction failure
#: or as musical silence. These four are distinct states and a researcher has
#: to be able to tell them apart from the published file alone.
EXTRACTION_STATES = frozenset({
    "complete_with_pitched_events",
    "complete_unpitched_only",
    "complete_no_events",
    "incomplete",
})

#: `estimated` rather than `measured`: a sample's fundamental is estimated from
#: its BRR content, and `measured` would claim a certainty the pipeline does
#: not establish.
PITCH_STATES = frozenset({
    "estimated", "noise", "pitch_modulated", "unrecoverable",
})


def _events(entry: dict) -> dict:
    assert entry.get("events"), (
        f"{entry['track_id']}: index has no `events` reference, so the "
        f"researcher-facing table was not published"
    )
    path = DIST / entry["events"]
    assert path.is_file(), f"index names {entry['events']} but it is absent"
    with gzip.open(path, "rt") as handle:
        return json.load(handle)


def test_every_track_publishes_an_event_table():
    """Including the 73 with no pitched notes. A track that produced only
    unpitched observations still has musical content."""
    entries = _need_dist()
    missing = [e["track_id"] for e in entries if not e.get("events")]
    assert not missing, f"{len(missing)} of {len(entries)} tracks have none"


def test_the_event_table_declares_its_schema_version():
    for entry in _sample(_need_dist()):
        assert _events(entry)["schema"] == EVENTS_SCHEMA


def test_events_are_a_flat_list_in_seconds():
    """Not nested under eight DSP voices. A researcher should not have to
    know the hardware has eight voices to iterate the notes."""
    for entry in _sample(_need_dist()):
        table = _events(entry)
        assert isinstance(table["events"], list)
        for event in table["events"][:50]:
            assert isinstance(event["onset_sec"], (int, float))
            assert event["onset_sec"] >= 0.0
            assert "duration_sec" in event


def test_every_event_declares_a_pitch_status():
    """The published artifact gave `midi_note: null` with no reason, so a
    researcher could not tell percussion from a failed estimate."""
    for entry in _sample(_need_dist()):
        for event in _events(entry)["events"]:
            assert event["pitch_status"] in PITCH_STATES, (
                f"{entry['track_id']}: pitch_status "
                f"{event.get('pitch_status')!r} is not one of {PITCH_STATES}"
            )


def test_a_pitch_is_present_exactly_when_it_was_estimated():
    for entry in _sample(_need_dist()):
        for event in _events(entry)["events"]:
            if event["pitch_status"] == "estimated":
                assert event["midi_note"] is not None
            else:
                assert event["midi_note"] is None, (
                    "a non-estimated event must not carry a pitch"
                )


def test_pitch_confidence_is_separate_from_pitch_status():
    """An estimated note with high confidence is still an estimate, so the
    two must not be collapsed into one field."""
    for entry in _sample(_need_dist()):
        estimated = [
            e for e in _events(entry)["events"]
            if e["pitch_status"] == "estimated"
        ]
        if estimated:
            assert "pitch_confidence" in estimated[0]
            return
    pytest.skip("no estimated events in the sample")


def test_amplitude_is_published_as_attack_and_sustain_levels():
    """Not as `velocity`, which implies a measured loudness the register
    values do not provide."""
    for entry in _sample(_need_dist()):
        for event in _events(entry)["events"][:20]:
            assert "attack_level" in event and "sustain_level" in event
            assert "velocity" not in event, (
                "`velocity` implies perceived loudness; use attack_level"
            )


def test_sample_identity_is_content_based_not_a_hardware_index():
    """`srcn` is an ARAM directory index that is not stable across a game's
    tracks -- Super Turrican's 8 indices resolve to 48 distinct samples -- so
    it is not usable as instrument identity."""
    for entry in _sample(_need_dist()):
        for event in _events(entry)["events"][:20]:
            assert "sample_id" in event
            assert isinstance(event["sample_id"], str) and event["sample_id"]
            assert "srcn" not in event, "srcn belongs to the hardware layer"


def test_extraction_status_is_declared_and_valid():
    for entry in _sample(_need_dist()):
        table = _events(entry)
        assert table["extraction_status"] in EXTRACTION_STATES


def test_extraction_status_is_independent_of_track_class():
    """A sound effect can contain recoverable pitch and a music track can
    contain only unpitched observations, so a musical label must never double
    as a data-quality indicator."""
    for entry in _sample(_need_dist()):
        table = _events(entry)
        assert "track_class" not in table["extraction_status"]


def test_the_counts_reconcile_with_the_event_list():
    for entry in _sample(_need_dist()):
        table = _events(entry)
        events = table["events"]
        pitched = sum(1 for e in events if e["pitch_status"] == "estimated")
        assert table["event_count"] == len(events)
        assert table["pitched_event_count"] == pitched
        assert table["unpitched_event_count"] == len(events) - pitched


def test_a_track_with_no_pitched_events_is_not_an_extraction_failure():
    """THE ACCEPTANCE TEST FOR THIS GATE.

    73 tracks recovered no pitch at all. Their musical events must still be
    published, their missing pitches explained, and the track distinguishable
    from a failed extraction -- which the previous artifact could not do.
    """
    found = None
    for entry in _need_dist():
        if not entry.get("events"):
            continue
        table = _events(entry)
        if table["pitched_event_count"] == 0 and table["event_count"] > 0:
            found = (entry, table)
            break
    if found is None:
        pytest.skip("no track in this corpus has events but no pitch")
    entry, table = found
    assert table["extraction_status"] == "complete_unpitched_only", (
        f"{entry['track_id']}: {table['extraction_status']!r} -- a successful "
        f"extraction of unpitched events must not read as a failure"
    )
    assert table["events"], "the musical events must still be present"
    for event in table["events"]:
        assert event["pitch_status"] in PITCH_STATES - {"estimated"}
        assert event["midi_note"] is None


def test_events_reconcile_against_the_source_records():
    """Every published event must correspond to a note in `data/out`, and
    none may be invented or dropped."""
    entries = _need_dist()
    if not (OUT / "manifest.jsonl").is_file():
        pytest.skip(f"no extraction output at {OUT}")
    rows = {
        r["track_id"]: r
        for r in (json.loads(l) for l in (OUT / "manifest.jsonl").open())
        if r.get("record_path")
    }
    compared = 0
    for entry in _sample(entries, 6):
        row = rows.get(entry["track_id"])
        if not row:
            continue
        record = json.loads((OUT / row["record_path"]).read_text())
        table = _events(entry)
        source_onsets = sorted(
            round(n["start_sec"], 6) for n in record["notes"]
        )
        published = sorted(
            round(e["onset_sec"], 6) for e in table["events"]
            if e.get("origin", "key_on") == "key_on"
        )
        assert published == source_onsets, (
            f"{entry['track_id']}: {len(published)} key-on events published "
            f"against {len(source_onsets)} notes in the source record"
        )
        compared += 1
    assert compared, "no track could be reconciled"


def test_an_event_is_not_necessarily_an_attack():
    """Counting event rows as note attacks would distort rhythmic analysis,
    so the attack count is published rather than left to be derived."""
    for entry in _sample(_need_dist()):
        table = _events(entry)
        events = table["events"]
        attacks = sum(1 for e in events if e["origin"] == "key_on")
        steps = sum(1 for e in events if e["origin"] == "legato_step")
        assert table["attack_count"] == attacks
        assert table["legato_step_count"] == steps
        assert attacks + steps == table["event_count"]


def test_a_legato_step_names_the_attack_it_continues():
    """So a phrase the driver expressed as one sounding voice with several
    pitches can be reassembled by grouping, without hardware knowledge."""
    for entry in _sample(_need_dist(), 12):
        table = _events(entry)
        attacks = {
            e["event_id"] for e in table["events"] if e["origin"] == "key_on"
        }
        steps = [e for e in table["events"] if e["origin"] == "legato_step"]
        if not steps:
            continue
        for step in steps:
            assert step["parent_event_id"] in attacks, (
                f"{entry['track_id']}: legato step at {step['onset_sec']}s "
                f"names parent {step['parent_event_id']}, which is no attack"
            )
        return
    pytest.skip("no legato steps in the sample")


def test_a_key_on_event_is_its_own_parent():
    for entry in _sample(_need_dist()):
        for event in _events(entry)["events"]:
            if event["origin"] == "key_on":
                assert event["parent_event_id"] == event["event_id"]


def test_event_totals_reconcile_with_notes_plus_legato_steps():
    """Explicitly NOT asserting that events equal the historical note count:
    the event table includes legato steps, which `summary.n_notes` does not,
    so the two use different definitions and must be reconciled rather than
    equated."""
    entries = _need_dist()
    if not (OUT / "manifest.jsonl").is_file():
        pytest.skip(f"no extraction output at {OUT}")
    rows = {
        r["track_id"]: r
        for r in (json.loads(l) for l in (OUT / "manifest.jsonl").open())
    }
    compared = 0
    for entry in _sample(entries, 8):
        row = rows.get(entry["track_id"])
        if not row:
            continue
        table = _events(entry)
        summary = row.get("summary") or {}
        assert table["attack_count"] == summary.get("n_notes"), (
            f"{entry['track_id']}: {table['attack_count']} attacks against "
            f"{summary.get('n_notes')} notes in the source summary"
        )
        assert table["legato_step_count"] <= summary.get("n_legato_steps", 0)
        assert table["event_count"] == (
            table["attack_count"] + table["legato_step_count"]
        )
        compared += 1
    assert compared, "no track could be reconciled"


def test_sample_ids_are_unique_per_content_across_the_corpus():
    """A truncated hash covering two different samples would corrupt every
    join a researcher makes on it, so uniqueness is checked rather than
    assumed. Exhaustive over every published event table."""
    seen: dict[str, str] = {}
    collisions = []
    for entry in _need_dist():
        if not entry.get("events"):
            continue
        for event in _events(entry)["events"]:
            sid = event["sample_id"]
            if not sid:
                continue
            seen.setdefault(sid, entry["track_id"])
    assert len(seen) > 100, f"only {len(seen)} distinct sample ids -- suspicious"
    assert not collisions


# --------------------------------------------------------------------------
# Gate 3: metadata and compatibility
# --------------------------------------------------------------------------

INDEX_SCHEMA = "snesmdb.index.v1"

TRACK_CLASSES = frozenset({"music", "jingle", "effect", "drone"})

#: Keys an existing consumer already indexes on. Gate 3 adds fields; it must
#: not rename or remove these, because a published schema that quietly changes
#: shape is worse than one that is merely incomplete.
LEGACY_INDEX_KEYS = (
    "track_id", "game", "title", "composers", "split",
    "render_seconds", "n_notes", "sha256_source_spc",
    "scores", "midi", "intake",
)
LEGACY_SCORE_KEYS = (
    "track_id", "clock", "separated", "blended", "expressive", "stats",
)


def _index_meta() -> dict:
    path = DIST / "index.json"
    if not path.is_file():
        pytest.skip(f"no published corpus at {DIST}")
    data = json.loads(path.read_text())
    if isinstance(data, list):
        pytest.fail(
            "index.json is a bare list, so it cannot declare a schema "
            "version or corpus-level counts"
        )
    return data


def test_the_index_declares_a_schema_version():
    """A researcher must be able to tell which contract a download follows
    without diffing it against another download."""
    meta = _index_meta()
    assert meta["schema"] == INDEX_SCHEMA


def test_the_index_names_the_schema_of_every_published_format():
    """So a consumer can check compatibility per format rather than guessing
    from the corpus version."""
    formats = _index_meta()["formats"]
    assert formats["events"] == EVENTS_SCHEMA
    assert formats["intake"] == "snesmdb.intake.v1"
    assert formats["sample_id"] == "snesmdb.sample.v1"
    assert float(formats["uniform_hz"]) == 100.0


def test_every_track_carries_its_musical_classification():
    """`track_class` was computed from the start and never published, so a
    researcher could not filter sound effects out of a melodic study."""
    for entry in _index_meta()["tracks"]:
        assert entry["track_class"] in TRACK_CLASSES


def test_track_class_and_extraction_status_are_independent_fields():
    """A sound effect can contain recoverable pitch and a music track can
    contain only unpitched observations, so neither may be derived from the
    other."""
    tracks = _index_meta()["tracks"]
    pairs = {(t["track_class"], t["extraction_status"]) for t in tracks}
    classes = {c for c, _ in pairs}
    assert len(classes) > 1
    # At least one class must appear with more than one status, or the two
    # fields are carrying the same information.
    by_class: dict[str, set] = {}
    for klass, status in pairs:
        by_class.setdefault(klass, set()).add(status)
    assert any(len(v) > 1 for v in by_class.values()), (
        "every track_class maps to exactly one extraction_status, so one of "
        "the fields is redundant -- they are meant to be independent"
    )


def test_the_index_carries_event_counts_without_opening_event_files():
    for entry in _index_meta()["tracks"]:
        for key in ("event_count", "pitched_event_count",
                    "unpitched_event_count", "attack_count"):
            assert key in entry, f"{entry['track_id']}: {key} absent"
        assert entry["event_count"] >= entry["attack_count"]


def test_corpus_level_counts_are_published():
    """So "how big is this dataset" needs no aggregation pass."""
    meta = _index_meta()
    corpus = meta["corpus"]
    tracks = meta["tracks"]
    assert corpus["n_tracks"] == len(tracks)
    assert corpus["n_events"] == sum(t["event_count"] for t in tracks)
    assert corpus["n_pitched_events"] == sum(
        t["pitched_event_count"] for t in tracks
    )
    assert set(corpus["track_classes"]) <= TRACK_CLASSES
    assert set(corpus["extraction_statuses"]) <= EXTRACTION_STATES


def test_legacy_index_fields_survive():
    """Gate 3 adds metadata. It must not rename or drop what consumers
    already use."""
    for entry in _index_meta()["tracks"]:
        for key in LEGACY_INDEX_KEYS:
            if key in ("midi",):
                continue      # absent for tracks with no pitched note
            assert key in entry, f"{entry['track_id']}: lost legacy key {key}"


def test_legacy_score_payload_keys_survive():
    meta = _index_meta()
    for entry in _sample(meta["tracks"]):
        score = _published_score(entry)
        for key in LEGACY_SCORE_KEYS:
            assert key in score, f"score lost legacy key {key}"
        assert "timbre_class" not in score, (
            "the inert timbre field must not return to the score payload"
        )
