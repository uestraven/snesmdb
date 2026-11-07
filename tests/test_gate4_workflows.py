"""Gate 4 — the published corpus supports research, using only `dist`.

Gate 4 asks an engineering question: can the distributed artifact be read
correctly, and do the numbers it yields agree with the extraction it came
from? Every workflow under test runs against `dist` with the standard library
alone, and every reference figure is recomputed from `data/out` by a different
route, so an agreement here is two independent paths meeting rather than one
path checking itself.

IT DOES NOT ASK WHETHER A RESEARCHER CAN USE IT. That is Gate 5, it needs an
evaluator who did not build this, and nothing here may stand in for it. In
particular there is no polyphony or simultaneous-voice analysis in this file:
that question is reserved, and writing its answer here would convert the
independent evaluation into a confirmation of our own assumptions.
"""

from __future__ import annotations

import ast
import gzip
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "examples"))

import workflows  # noqa: E402

DIST = Path(os.environ.get(
    "SNESMDB_DIST", Path.home() / "snesmdb-corpus" / "dist",
))
OUT = Path(os.environ.get("SNESMDB_OUT", ROOT / "data" / "out"))

#: Kept small so the suite stays fast while still spanning several games,
#: which is what the cross-game sample checks need.
REFERENCE_GAMES = ("Actraiser", "Plok!", "Super Turrican")


def _need_dist() -> dict:
    if not (DIST / "index.json").is_file():
        pytest.skip(f"no published corpus at {DIST} -- run `make corpus`")
    return workflows.load_index(DIST)


def _need_out() -> list[dict]:
    path = OUT / "manifest.jsonl"
    if not path.is_file():
        pytest.skip(f"no extraction records at {path}")
    return [json.loads(line) for line in path.open()]


def _records(rows: list[dict], track_ids: set[str]) -> dict[str, dict]:
    """The extraction records for named tracks: the independent reference."""
    found = {}
    for row in rows:
        if row["track_id"] in track_ids and row.get("record_path"):
            found[row["track_id"]] = json.loads(
                (OUT / row["record_path"]).read_text()
            )
    return found


def _reference_attack_pitches(record: dict) -> list[float]:
    """Pitched ATTACKS from an extraction record.

    Uses `notes` only -- one note is one key-on -- so this never touches the
    legato-step handling it is used to check. The precedence is the documented
    one: noise and pitch modulation mean the PITCH register does not describe
    what sounded, whatever value it holds.
    """
    pitches = []
    for note in record.get("notes") or []:
        if note.get("noise") or note.get("pitch_modulated"):
            continue
        if note.get("midi_note") is None:
            continue
        pitches.append(float(note["midi_note"]))
    return pitches


# ---------------------------------------------------------------------------
# The rule that makes Gate 4 mean anything
# ---------------------------------------------------------------------------

def test_the_workflows_import_nothing_from_this_project():
    """A researcher who downloads the corpus does not have `src/snesmdb`.

    A workflow that imported it would demonstrate that OUR code can read our
    own output, which is not the claim Gate 4 makes. Enforced by reading the
    import statements rather than by trusting a comment.
    """
    tree = ast.parse((ROOT / "examples" / "workflows.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level:
            pytest.fail("a relative import means this is not standalone")
    assert "snesmdb" not in imported, (
        f"the workflows import {sorted(imported)}; importing this project's "
        f"library would make the test prove nothing about the artifact"
    )
    assert imported <= {
        "argparse", "gzip", "json", "collections", "pathlib", "typing",
        "__future__",
    }, f"non-stdlib import in a dist-only workflow: {sorted(imported)}"


# ---------------------------------------------------------------------------
# Workflow 1: corpus discovery
# ---------------------------------------------------------------------------

def test_discovery_agrees_with_the_extraction_records():
    """The index is the only thing a researcher filters on, so its
    classification must match what extraction actually decided."""
    _need_dist()
    rows = _need_out()
    by_id = {r["track_id"]: r for r in rows}
    for game in REFERENCE_GAMES:
        found = workflows.discover(DIST, game=game, track_class="music")
        reference = {
            r["track_id"] for r in rows
            if r.get("ok") and r.get("record_path")
            and r["tag"]["game"] == game and r.get("track_class") == "music"
        }
        # Discovery additionally requires a pitched event, so it is a subset.
        assert {e["track_id"] for e in found} <= reference
        for entry in found:
            assert by_id[entry["track_id"]]["track_class"] == "music"
            assert entry["pitched_event_count"] > 0


def test_discovery_respects_both_filters_independently():
    """`track_class` is musical and `extraction_status` is data quality. A
    study that conflated them would silently drop or admit the wrong tracks."""
    _need_dist()
    effects_with_pitch = workflows.discover(
        DIST, track_class="effect", require_pitched=True
    )
    music_without_pitch = [
        e for e in workflows.discover(
            DIST, track_class="music", require_pitched=False
        )
        if not e["pitched_event_count"]
    ]
    # Both populations are non-empty in this corpus, which is the evidence
    # that neither field can be derived from the other.
    assert effects_with_pitch, "no pitched sound effects: filters are coupled"
    assert music_without_pitch, "no unpitched music track: filters are coupled"


def test_loading_a_track_rejects_an_index_that_disagrees_with_it():
    """A stale index would scale every published count silently. Built as a
    synthetic tree so the guard is tested, not assumed."""
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        fake = Path(raw)
        (fake / "events").mkdir()
        table = {
            "schema": workflows.EVENTS_SCHEMA, "track_id": "x:1",
            "event_count": 2, "pitched_event_count": 1, "attack_count": 2,
            "extraction_status": "complete_with_pitched_events", "events": [],
        }
        with gzip.open(fake / "events" / "x.json.gz", "wt") as handle:
            json.dump(table, handle)
        entry = dict(table, events="events/x.json.gz")
        assert workflows.load_events(fake, entry)["track_id"] == "x:1"
        with pytest.raises(SystemExit, match="event_count"):
            workflows.load_events(fake, dict(entry, event_count=99))


# ---------------------------------------------------------------------------
# Workflow 2: pitch distribution and range
# ---------------------------------------------------------------------------

def test_attack_pitch_range_matches_the_extraction_records():
    """The reference comes from `data/out` note records by a different route,
    so this is two paths agreeing rather than one checking itself."""
    _need_dist()
    rows = _need_out()
    compared = 0
    for game in REFERENCE_GAMES:
        entries = workflows.discover(DIST, game=game, track_class="music")
        # Not `continue`: a renamed game would otherwise reduce this test to
        # no assertions at all while still reporting a pass.
        assert entries, f"{game}: no music tracks found to compare"
        compared += 1
        profile = workflows.pitch_profile(DIST, entries)
        records = _records(rows, {e["track_id"] for e in entries})
        reference: list[float] = []
        for record in records.values():
            reference.extend(_reference_attack_pitches(record))
        assert reference, f"{game}: no reference pitches"
        assert profile["n_attacks_pitched"] == len(reference), game
        assert profile["attack_pitch_min"] == pytest.approx(
            min(reference), abs=1e-3
        ), game
        assert profile["attack_pitch_max"] == pytest.approx(
            max(reference), abs=1e-3
        ), game
        assert profile["attack_pitch_mean"] == pytest.approx(
            sum(reference) / len(reference), abs=1e-3
        ), game
    assert compared == len(REFERENCE_GAMES)


def test_unpitched_events_are_excluded_with_a_reason_not_zeroed():
    """The defect this schema exists to prevent: 405,288 events once arrived
    with `midi_note: null` and no reason, so a mean over them would have been
    computed against an unexplained absence."""
    _need_dist()
    entries = workflows.discover(DIST, game=REFERENCE_GAMES[0])
    if not entries:
        pytest.skip("reference game absent from this corpus")
    profile = workflows.pitch_profile(DIST, entries)
    excluded = sum(profile["excluded_by_pitch_status"].values())
    # Every event is either a usable pitch or excluded with a stated reason.
    assert profile["n_pitch_events"] + excluded == profile["n_events"]
    assert all(
        reason in {"noise", "pitch_modulated", "unrecoverable"}
        for reason in profile["excluded_by_pitch_status"]
    )
    # And a pitch distribution never silently includes a zero.
    assert profile["attack_pitch_min"] > 0


def test_legato_steps_count_as_sounded_pitch_but_not_as_notes():
    """An event is not an attack. A corpus-wide rhythmic figure that counted
    every event as a note would overstate it by 154,910."""
    _need_dist()
    entries = workflows.discover(DIST, track_class="music")[:40]
    profile = workflows.pitch_profile(DIST, entries)
    assert profile["n_pitch_events"] >= profile["n_attacks_pitched"]
    index_attacks = sum(e["attack_count"] for e in entries)
    index_events = sum(e["event_count"] for e in entries)
    assert profile["n_events"] == index_events
    assert profile["n_attacks_pitched"] <= index_attacks


# ---------------------------------------------------------------------------
# Workflow 3: sample identity
# ---------------------------------------------------------------------------

def test_sample_grouping_satisfies_the_per_game_identity():
    """Corpus-wide distinct samples, plus one count per extra game each sample
    appears in, must equal the sum of the per-game distinct counts.

    An exact identity rather than a recorded figure, so it checks the grouping
    logic itself and survives a corpus change. It is the law that was violated
    when `sample_id` hashed `repr(list)` and omitted the loop point.
    """
    _need_dist()
    entries = [
        e for e in workflows.discover(DIST, track_class=None)
        if e.get("game") in REFERENCE_GAMES
    ]
    if not entries:
        pytest.skip("reference games absent from this corpus")
    report = workflows.sample_usage(DIST, entries, min_tracks=1)
    per_game_total = 0
    for game in REFERENCE_GAMES:
        in_game = [e for e in entries if e.get("game") == game]
        if in_game:
            per_game_total += workflows.sample_usage(
                DIST, in_game, min_tracks=1
            )["n_distinct_samples"]
    extra_games = sum(
        r["n_games"] - 1 for r in report["recurring"]
    )
    assert report["n_distinct_samples"] + extra_games == per_game_total


# ---------------------------------------------------------------------------
# The index migration
# ---------------------------------------------------------------------------

def test_the_index_is_a_document_and_the_old_idiom_would_break():
    """Gate 3 changed the top-level type. The migration is documented because
    `json.load(f)` no longer yields a list, which is a BREAKING change even
    though no track-row field moved."""
    raw = json.loads((DIST / "index.json").read_text()) if (
        DIST / "index.json"
    ).is_file() else pytest.skip(f"no corpus at {DIST}")
    assert isinstance(raw, dict), "index should be a document"
    assert isinstance(raw["tracks"], list)
    assert raw["schema"] == workflows.INDEX_SCHEMA


def test_the_loader_still_reads_a_pre_v1_bare_list():
    """A corpus published before the change is a real artifact and must stay
    readable, which is why the migration is additive for readers."""
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        fake = Path(raw)
        (fake / "index.json").write_text(json.dumps([{"track_id": "x:1"}]))
        index = workflows.load_index(fake)
        assert index["tracks"] == [{"track_id": "x:1"}]
        assert index["schema"] is None


def test_an_unknown_future_index_schema_is_refused_not_guessed():
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        fake = Path(raw)
        (fake / "index.json").write_text(json.dumps(
            {"schema": "snesmdb.index.v9", "tracks": []}
        ))
        with pytest.raises(SystemExit, match="release notes"):
            workflows.load_index(fake)


def test_the_breaking_change_is_documented_with_both_access_patterns():
    """A breaking change that is only mentioned in a commit message is not
    documented for the people who consume the artifact."""
    notes = (ROOT / "docs" / "CHANGELOG.md")
    assert notes.is_file(), "no CHANGELOG.md to carry the migration"
    text = notes.read_text()
    assert 'json.load(handle)["tracks"]' in text, "no new access pattern shown"
    assert "BREAKING" in text.upper()
    assert workflows.INDEX_SCHEMA in text
