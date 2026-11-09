"""The baseline experiment's protocol, pinned as properties.

The point of 7B.3 is not the score. It is that an independent researcher can
run the experiment and know what the number means. That depends on protocol
properties a reader cannot check by looking at the output:

    determinism         two runs over one release give identical numbers
    melody definition   voice-local, key-on only, applied identically to
                        every split
    selection hygiene   hyperparameters chosen on validation, never on test
    honest reporting    an exclusion that did not fire is reported as not
                        fired, rather than claimed as a leakage correction

The last one matters most here. The confirmed cross-split duplicate is
jingle-class, and the task is music-class only, so the exclusion does NOT
apply to this population. Reporting it as "corrected for leakage" would
claim a control that was never exercised.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "baseline", ROOT / "tools" / "baseline_interval_ngram.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)


def _table(voice_notes: dict[int, list[float]], steps: int = 0):
    events = []
    eid = 0
    for voice, notes in voice_notes.items():
        for i, note in enumerate(notes):
            events.append({
                "event_id": eid, "origin": "key_on", "voice": voice,
                "midi_note": note,
                "pitch_status": "estimated" if note is not None
                                else "unrecoverable",
                "onset_sec": i * 0.25, "duration_sec": 0.2})
            eid += 1
    for i in range(steps):
        events.append({
            "event_id": eid, "origin": "legato_step", "voice": 0,
            "midi_note": 70.0, "pitch_status": "estimated",
            "onset_sec": 0.1, "duration_sec": None})
        eid += 1
    return {"schema": "snesmdb.events.v4", "events": events}


# ---------------------------------------------------------------------------
# The melody definition
# ---------------------------------------------------------------------------

def test_sequences_are_voice_local_not_a_global_time_sort():
    """A global sort would interleave two voices and produce intervals that
    describe the arrangement rather than any melody. Here two voices play
    simultaneously in different registers; a time-sorted stream would yield
    huge alternating intervals."""
    table = _table({0: [60.0, 62.0, 64.0], 1: [36.0, 38.0, 40.0]})
    seqs = base.sequences_for(table)
    assert len(seqs) == 2
    assert all(s == [2, 2] for s in seqs), (
        "each voice must yield its own stepwise intervals"
    )


def test_legato_steps_do_not_contribute_intervals():
    """A step is a pitch change inside a sounding note, derived from a
    register ratio rather than re-keyed. Mixing it in would make the
    learning population impossible to state."""
    plain = base.sequences_for(_table({0: [60.0, 62.0, 64.0]}))
    with_steps = base.sequences_for(_table({0: [60.0, 62.0, 64.0]}, steps=5))
    assert plain == with_steps


def test_attacks_without_a_pitch_estimate_are_skipped():
    table = _table({0: [60.0, None, 64.0]})
    assert base.sequences_for(table) == [[4]], (
        "an unpitched attack has no interval and must not break or "
        "contribute to the sequence"
    )


def test_a_voice_with_one_note_yields_no_interval():
    assert base.sequences_for(_table({0: [60.0]})) == []


def test_intervals_beyond_two_octaves_collapse_into_one_bucket():
    """A closed vocabulary is needed for a likelihood, and a leap beyond two
    octaves is a voice reassignment or an octave error more often than a
    melodic step."""
    assert base.clip(40) == base.BIG_UP
    assert base.clip(-40) == base.BIG_DOWN
    assert base.clip(12) == 12
    assert len(base.VOCAB) == 2 * base.CLIP + 3


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------

def test_the_control_ignores_context_entirely():
    """If the control used context it would not be a frequency baseline and
    any difference between the two would be uninterpretable."""
    control = base.Frequency()
    control.fit([[2, 2, 2, -5, 7]])
    a, _ = control.predict(())
    b, _ = control.predict((2, 2, 2))
    assert a == b == 2


def test_the_ngram_uses_context():
    model = base.Ngram(order=1, alpha=0.01)
    # After 5 the next is always 1; after -5 it is always -1.
    model.fit([[5, 1] * 20 + [-5, -1] * 20])
    assert model.predict((5,))[0] == 1
    assert model.predict((-5,))[0] == -1


def test_the_ngram_backs_off_to_the_unigram_for_unseen_context():
    model = base.Ngram(order=2, alpha=0.01)
    model.fit([[3] * 40])
    best, probs = model.predict((17, 19))      # never seen
    assert best == 3
    assert abs(sum(probs.values()) - 1.0) < 1e-6


def test_probabilities_are_normalised_and_never_zero():
    """A zero would make NLL infinite on a single unseen interval."""
    model = base.Ngram(order=2, alpha=0.1)
    model.fit([[1, 2, 3, 4]])
    _, probs = model.predict((1, 2))
    assert abs(sum(probs.values()) - 1.0) < 1e-6
    assert min(probs.values()) > 0


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

def _dist(root: Path, tracks):
    (root / "events").mkdir(parents=True, exist_ok=True)
    entries = []
    for tid, game, split, cls, table in tracks:
        rel = f"events/{tid.replace(':', '_')}.json.gz"
        (root / rel).write_bytes(gzip.compress(json.dumps(table).encode()))
        entries.append({"track_id": tid, "game": game, "split": split,
                        "track_class": cls, "events": rel})
    (root / "index.json").write_text(json.dumps({
        "schema": "snesmdb.index.v1", "tracks": entries}))
    return root


def _melody(seed: int, n: int = 60):
    notes, value = [], 60.0
    for i in range(n):
        value += ((seed * 7 + i * 5) % 11) - 5
        notes.append(max(24.0, min(96.0, value)))
    return notes


def _run(dist: Path, out: Path):
    argv = sys.argv
    sys.argv = ["baseline_interval_ngram.py", str(dist), str(out)]
    try:
        base.main()
    finally:
        sys.argv = argv
    return json.loads(out.read_text())


def test_the_experiment_is_deterministic(tmp_path):
    dist = _dist(tmp_path / "d", [
        (f"t{i}:0", f"Game{i % 6}",
         "train" if i % 6 < 4 else ("valid" if i % 6 == 4 else "test"),
         "music", _table({0: _melody(i), 1: _melody(i + 3)}))
        for i in range(18)
    ])
    first = _run(dist, tmp_path / "a.json")
    second = _run(dist, tmp_path / "b.json")
    assert first["test"] == second["test"]
    assert first["selection"]["chosen"] == second["selection"]["chosen"]


def test_non_music_tracks_are_excluded_from_the_population(tmp_path):
    dist = _dist(tmp_path / "d", [
        ("m1:0", "A", "train", "music", _table({0: _melody(1)})),
        ("m2:0", "B", "valid", "music", _table({0: _melody(2)})),
        ("m3:0", "C", "test", "music", _table({0: _melody(3)})),
        ("j1:0", "D", "train", "jingle", _table({0: _melody(4)})),
    ])
    got = _run(dist, tmp_path / "r.json")
    assert got["population"]["dropped_not_music_class"] == 1
    assert got["tracks_per_split"]["train"] == 1


def test_an_exclusion_that_did_not_fire_is_reported_as_not_fired(tmp_path):
    """The confirmed duplicate is jingle-class and the task is music-only,
    so the conditional exclusion does not apply. Claiming the experiment
    was corrected for leakage would assert a control never exercised."""
    dist = _dist(tmp_path / "d", [
        ("m1:0", "A", "train", "music", _table({0: _melody(1)})),
        ("m2:0", "B", "valid", "music", _table({0: _melody(2)})),
        ("m3:0", "C", "test", "music", _table({0: _melody(3)})),
    ])
    got = _run(dist, tmp_path / "r.json")
    assert got["exclusion_policy"]["applied"] == []
    assert got["exclusion_policy"]["tracks_removed"] == {
        "valid": 0, "test": 0}
    assert "does NOT fire" in got["exclusion_policy"]["note"]


def test_the_report_states_the_selected_setting_and_the_grid(tmp_path):
    dist = _dist(tmp_path / "d", [
        (f"t{i}:0", f"Game{i % 6}",
         "train" if i % 6 < 4 else ("valid" if i % 6 == 4 else "test"),
         "music", _table({0: _melody(i)}))
        for i in range(12)
    ])
    got = _run(dist, tmp_path / "r.json")
    chosen = got["selection"]["chosen"]
    assert chosen["order"] in base.ORDERS
    assert chosen["alpha"] in base.ALPHAS
    assert got["selection"]["grid"]["orders"] == list(base.ORDERS)
    assert len(got["selection"]["validation_results"]) == \
        len(base.ORDERS) * len(base.ALPHAS)
    assert "selected_at_grid_boundary" in chosen


def test_the_report_refuses_the_composer_generalisation_claim(tmp_path):
    dist = _dist(tmp_path / "d", [
        ("m1:0", "A", "train", "music", _table({0: _melody(1)})),
        ("m2:0", "B", "valid", "music", _table({0: _melody(2)})),
        ("m3:0", "C", "test", "music", _table({0: _melody(3)})),
    ])
    got = _run(dist, tmp_path / "r.json")
    joined = " ".join(got["limitations"])
    assert "Held-out-GAME" in joined
    assert "NOT established" in joined
    assert "normalised away" in joined
