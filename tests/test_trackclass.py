"""Mechanical track classification."""

from __future__ import annotations

from snesmdb import trackclass as T


def _row(seconds, notes, effective=None):
    return {
        "ok": True,
        "render_seconds": seconds,
        "summary": {
            "n_notes": notes,
            "n_kon_effective": notes if effective is None else effective,
        },
    }


def test_a_drone_is_identified_by_mechanism_not_by_length() -> None:
    """An SPC is a snapshot, so a track already sounding and never re-keyed
    has no key-on to recover. Final Fantasy VI's "Time Vortex" is 238 seconds
    long with zero notes, so duration cannot be the test."""
    assert T.classify(_row(1.0, 0, effective=0)).label == "drone"
    assert T.classify(_row(238.0, 0, effective=0)).label == "drone"


def test_a_handful_of_notes_is_an_effect_at_any_duration() -> None:
    assert T.classify(_row(1.0, 3)).label == "effect"
    assert T.classify(_row(60.0, 3)).label == "effect"


def test_a_dense_one_second_track_is_a_jingle_not_an_effect() -> None:
    """Donkey Kong Country's one-second "Extra Life Balloon" extracted 23
    notes cleanly. Duration alone would have thrown it away."""
    assert T.classify(_row(1.0, 23)).label == "jingle"


def test_a_long_sparse_track_is_an_effect_not_music() -> None:
    assert T.classify(_row(120.0, 30)).label == "effect"


def test_a_normal_song_is_music() -> None:
    assert T.classify(_row(90.0, 1372)).label == "music"


def test_the_jingle_window_is_a_duration_not_a_density() -> None:
    assert T.classify(_row(T.JINGLE_SECONDS, 200)).label == "jingle"
    assert T.classify(_row(T.JINGLE_SECONDS + 0.5, 200)).label == "music"


def test_every_label_carries_its_reason() -> None:
    """A classification a consumer cannot interrogate is a magic number."""
    for row in (_row(1.0, 0, 0), _row(1.0, 3), _row(1.0, 23), _row(90.0, 900)):
        result = T.classify(row)
        assert result.label in T.CLASSES
        if result.label != "music":
            assert result.reason


def test_the_census_covers_every_class_even_when_empty() -> None:
    counts = T.census([_row(90.0, 900)])
    assert set(counts) == set(T.CLASSES)
    assert counts["music"] == 1 and counts["effect"] == 0


def test_the_census_preserves_the_total() -> None:
    """Nothing is dropped: a curated list is not reproducible, and deleting
    tracks destroys the denominator findings are reported against. Asserted on
    BEHAVIOUR rather than by grepping the source -- the first version of this
    test searched for "del " and matched the phrase "the note model cannot
    represent it" inside a docstring.
    """
    rows = [
        _row(1.0, 0, 0), _row(1.0, 3), _row(1.0, 23),
        _row(90.0, 900), _row(120.0, 30), _row(5.0, 400),
    ]
    counts = T.census(rows)
    assert sum(counts.values()) == len(rows)
    assert all(T.classify(row).label for row in rows)
