"""`snesmdb.index.v1` — the index document's own contract.

These are the library-level invariants. The published-artifact versions live in
`test_dist_contract.py` and open the real `dist` tree; these run without a
corpus so a broken index shape fails before a twenty-minute publish does.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import corpus, events, sampleid, scores


def _entry(**extra):
    base = {
        "track_id": "g:01",
        "game": "Game",
        "track_class": "music",
        "extraction_status": events.STATUS_PITCHED,
        "event_count": 10,
        "pitched_event_count": 7,
        "unpitched_event_count": 3,
        "attack_count": 8,
    }
    base.update(extra)
    return base


def test_format_versions_are_read_from_the_modules_that_own_them():
    """Not restated. A version written twice is a version that can disagree
    with the files it describes."""
    declared = corpus.formats()
    assert declared["events"] == events.SCHEMA
    assert declared["sample_id"] == sampleid.SCHEMA
    assert declared["uniform_hz"] == scores.UNIFORM_HZ


def test_a_schema_bump_in_a_format_module_reaches_the_index(monkeypatch):
    """The point of reading from the module: if `events` ever becomes v2, the
    index must say so without anyone remembering to edit it here."""
    monkeypatch.setattr(events, "SCHEMA", "snesmdb.events.v2")
    assert corpus.formats()["events"] == "snesmdb.events.v2"


def test_each_format_is_versioned_separately():
    """One corpus version would force either a false bump for consumers that
    were unaffected, or a silent one for a change that mattered."""
    declared = corpus.formats()
    assert "events" in declared and "intake" in declared
    assert declared["events"] != declared["intake"]


def test_the_corpus_block_reconciles_with_the_track_rows():
    doc = corpus.index_document([
        _entry(event_count=10, pitched_event_count=7, attack_count=8),
        _entry(track_id="g:02", event_count=4, pitched_event_count=0,
               attack_count=4, extraction_status=events.STATUS_UNPITCHED_ONLY),
    ])
    block = doc["corpus"]
    assert block["n_tracks"] == 2
    assert block["n_events"] == 14
    assert block["n_pitched_events"] == 7
    assert block["n_attacks"] == 12


def test_the_census_never_loses_a_track():
    """A track with no classification must be counted as `unknown`, not
    dropped. A census whose total disagrees with `n_tracks` would understate
    the corpus while looking perfectly consistent."""
    doc = corpus.index_document([
        _entry(),
        _entry(track_id="g:02", track_class=None),
        _entry(track_id="g:03", extraction_status=None),
    ])
    block = doc["corpus"]
    assert sum(block["track_classes"].values()) == block["n_tracks"]
    assert sum(block["extraction_statuses"].values()) == block["n_tracks"]
    assert block["track_classes"]["unknown"] == 1
    assert block["extraction_statuses"]["unknown"] == 1


def test_the_track_rows_pass_through_unchanged():
    """Gate 3 wraps the list; it must not rewrite the entries. A consumer
    reading `tracks` must find exactly what the bare list used to hold."""
    rows = [_entry(), _entry(track_id="g:02")]
    doc = corpus.index_document(rows)
    assert doc["tracks"] == rows


def test_both_index_shapes_are_readable():
    """A corpus published before the index became a document is still a real
    artifact, and reading one is exactly when the verifier gets used."""
    rows = [_entry()]
    assert corpus.tracks_of(rows) == rows
    assert corpus.tracks_of(corpus.index_document(rows)) == rows


def test_an_empty_corpus_is_a_document_not_a_crash():
    doc = corpus.index_document([])
    assert doc["schema"] == corpus.INDEX_SCHEMA
    assert doc["corpus"]["n_tracks"] == 0
    assert doc["tracks"] == []


# ---------------------------------------------------------------------------
# Redundancy for the fields researchers are told to filter on
# ---------------------------------------------------------------------------

def test_the_slug_map_covers_every_track_and_is_not_guessable():
    """Published because it cannot be derived. `mo2` is Earthbound (Mother 2)
    and `sd2` is Secret of Mana (Seiken Densetsu 2); an evaluator who needed
    this had to reconstruct it from per-game track counts."""
    rows = [
        _entry(track_id="mo2-01:ab", game="Earthbound"),
        _entry(track_id="mo2-02:cd", game="Earthbound"),
        _entry(track_id="sd2-01:ef", game="Secret of Mana"),
    ]
    assert corpus.games(rows) == {
        "mo2": "Earthbound", "sd2": "Secret of Mana",
    }


def test_tracks_csv_has_one_line_per_track_plus_a_header():
    rows = [_entry(track_id="a-01:x"), _entry(track_id="b-02:y")]
    lines = corpus.tracks_csv(rows).splitlines()
    assert lines[0].split(",") == list(corpus.TRACKS_CSV_COLUMNS)
    assert len(lines) == 3


def test_tracks_csv_survives_truncation_row_by_row():
    """The property that makes it worth shipping alongside the JSON index. A
    copy of `index.json` truncated at a 768 KiB boundary lost all 1,316 rows
    to one unterminated string; a truncated CSV keeps every complete line."""
    import csv as csv_mod
    import io
    rows = [_entry(track_id=f"g-{n:02d}:h{n}") for n in range(40)]
    text = corpus.tracks_csv(rows)
    cut = text[: int(len(text) * 0.56)]
    parsed = list(csv_mod.DictReader(io.StringIO(cut)))
    # Most rows survive, every surviving row is complete, and the last
    # (possibly partial) line is simply absent or short -- never fatal.
    assert 10 < len(parsed) < 40
    assert all(row["track_id"] for row in parsed)


def test_composer_lists_do_not_collide_with_the_csv_delimiter():
    rows = [_entry(track_id="a-01:x", composers=["Koji Kondo", "Soyo Oka"])]
    line = corpus.tracks_csv(rows).splitlines()[1]
    assert "Koji Kondo; Soyo Oka" in line


def test_the_tracks_csv_format_is_versioned():
    assert corpus.formats()["tracks_csv"] == corpus.TRACKS_CSV_SCHEMA
