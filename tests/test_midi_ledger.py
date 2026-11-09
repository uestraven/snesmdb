"""The MIDI export ledger's five acceptance properties.

The ledger exists because "431,783 dropped" answered no question a
researcher has. What matters is whether an omission is recoverable -- a
usable fixed-pitch estimate that no MIDI note carries -- or whether the
published representation gives no single note to write, in which case
writing one would fabricate it.

The properties enforced here are the ones that make the ledger trustworthy
rather than merely plausible:

    1. every published attack lands in exactly one disposition
    2. per-track totals reconcile with the published event records
    3. global totals reconcile
    4. no track with exported pitched notes lacks a MIDI file
    5. out-of-range estimates stay visible and do not fall into a generic
       unpitched bucket

Property 5 is the one most easily lost. Those attacks have a pitch and are
the only recoverable omissions in the corpus; folding them into
"unpitched" would erase the only actionable finding in 2,041,091 rows.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "midi_ledger", ROOT / "tools" / "midi_export_ledger.py")
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)


def _event(event_id, voice=0, midi=60.0, status="estimated"):
    return {
        "event_id": event_id, "origin": "key_on", "voice": voice,
        "midi_note": midi, "pitch_status": status,
        "onset_sec": 0.1 * event_id, "duration_sec": 0.05,
    }


def _dist(tmp_path, tracks):
    """A minimal published tree: index plus gzipped event tables."""
    (tmp_path / "events").mkdir(parents=True, exist_ok=True)
    (tmp_path / "midi").mkdir(parents=True, exist_ok=True)
    entries = []
    for i, (events, has_midi) in enumerate(tracks):
        rel = f"events/t{i}.json.gz"
        attacks = [e for e in events if e["origin"] == "key_on"]
        (tmp_path / rel).write_bytes(gzip.compress(json.dumps({
            "schema": "snesmdb.events.v4", "track_id": f"t{i}:0",
            "events": events, "attack_count": len(attacks),
        }).encode()))
        entry = {"track_id": f"t{i}:0", "events": rel, "game": "G",
                 "track_class": "music", "attack_count": len(attacks),
                 "pitched_attack_count": sum(
                     1 for e in attacks
                     if e["pitch_status"] == "estimated")}
        if has_midi:
            # A real, minimal MIDI file so the note-on parser has something
            # to read; content is irrelevant to these properties.
            mid = f"midi/t{i}.mid"
            (tmp_path / mid).write_bytes(
                b"MThd" + (6).to_bytes(4, "big") + b"\x00\x01\x00\x01\x01\xe0"
            )
            entry["midi"] = mid
        entries.append(entry)
    (tmp_path / "index.json").write_text(json.dumps({
        "schema": "snesmdb.index.v1", "tracks": entries}))
    return tmp_path


def _run(dist, tmp_path):
    out = tmp_path / "ledger.json"
    import sys
    argv = sys.argv
    sys.argv = ["midi_export_ledger.py", str(dist), str(out)]
    try:
        ledger.main()
    except SystemExit as exc:          # non-reconciling ledger exits
        if exc.code:
            return json.loads(out.read_text()) if out.is_file() else None
    finally:
        sys.argv = argv
    return json.loads(out.read_text())


# ---------------------------------------------------------------------------
# 1 & 3. Exactly one disposition per attack; global totals reconcile
# ---------------------------------------------------------------------------

def test_every_attack_lands_in_exactly_one_disposition(tmp_path):
    dist = _dist(tmp_path / "d", [
        ([_event(0), _event(1, midi=None, status="unrecoverable"),
          _event(2, midi=200.0)], True),
    ])
    got = _run(dist, tmp_path)
    assert got["reconciles"] is True
    assert got["attacks_classified"] == got["published_attacks"] == 3
    assert got["written_to_midi"] + got["omitted_from_midi"] == 3


def test_a_ledger_that_does_not_reconcile_fails_loudly(tmp_path):
    """If classification ever misses an attack the ledger must refuse,
    not publish a total that happens to look sensible."""
    dist = _dist(tmp_path / "d", [([_event(0)], True)])
    index = json.loads((dist / "index.json").read_text())
    index["tracks"][0]["attack_count"] = 99        # contradict the events
    (dist / "index.json").write_text(json.dumps(index))
    got = _run(dist, tmp_path)
    assert got is None or got["reconciles"] is False


# ---------------------------------------------------------------------------
# 2. Per-track reconciliation
# ---------------------------------------------------------------------------

def test_per_track_totals_reconcile_with_the_event_records(tmp_path):
    dist = _dist(tmp_path / "d", [
        ([_event(0), _event(1, midi=None, status="noise")], True),
        ([_event(0, voice=1), _event(1, voice=1)], True),
    ])
    got = _run(dist, tmp_path)
    for track in got["tracks"]:
        assert track["written"] + track["omitted"] == track["attacks"], (
            f"{track['track_id']} does not reconcile"
        )


def test_the_ledger_reports_whether_each_track_has_a_midi_file(tmp_path):
    dist = _dist(tmp_path / "d", [
        ([_event(0)], True),
        ([_event(0, midi=None, status="unrecoverable")], False),
    ])
    got = _run(dist, tmp_path)
    flags = {t["track_id"]: t["has_midi_file"] for t in got["tracks"]}
    assert flags == {"t0:0": True, "t1:0": False}


# ---------------------------------------------------------------------------
# 4. No track with exported pitched notes may lack a MIDI file
# ---------------------------------------------------------------------------

def test_a_track_with_exportable_pitched_notes_and_no_midi_file_is_visible(
        tmp_path):
    """The silent exporter failure: a track whose notes WOULD export but
    that shipped no file. All 78 such tracks in the 27-game release are
    legitimately unpitched; one that was not would be a defect, and the
    ledger has to make it countable."""
    dist = _dist(tmp_path / "d", [([_event(0, midi=60.0)], False)])
    got = _run(dist, tmp_path)
    offenders = [
        t for t in got["tracks"]
        if not t["has_midi_file"]
        and t["reasons"].get("track_has_no_midi_file", 0) > 0
    ]
    assert offenders, "a file-less track's attacks must be attributed"
    assert got["omissions_by_reason"]["track_has_no_midi_file"] == 1


# ---------------------------------------------------------------------------
# 5. Out-of-range estimates stay visible
# ---------------------------------------------------------------------------

def test_an_out_of_range_estimate_is_not_folded_into_unpitched(tmp_path):
    dist = _dist(tmp_path / "d", [
        ([_event(0, midi=200.0), _event(1, midi=None,
                                        status="unrecoverable")], True),
    ])
    got = _run(dist, tmp_path)
    assert got["omissions_by_reason"]["pitch_outside_midi_range"] == 1
    assert got["omissions_by_reason"]["no_pitch_recovered"] == 1
    assert got["omitted_with_a_fixed_pitch_estimate"] == 1, (
        "an omission carrying a usable pitch is the actionable category and "
        "must not be counted as unpitched"
    )
    key = "pitch_outside_midi_range|estimated"
    assert got["omissions_by_reason_and_pitch_status"][key] == 1


def test_midi_note_zero_is_in_range(tmp_path):
    """MIDI spans 0..127. A 1..127 bound discarded note 0 for four real
    attacks, so the ledger must treat it as writable."""
    assert ledger.MIDI_LOW == 0 and ledger.MIDI_HIGH == 127
    dist = _dist(tmp_path / "d", [([_event(0, midi=-0.0595)], True)])
    got = _run(dist, tmp_path)
    assert got["written_to_midi"] == 1
    assert got["attacks_rounding_to_midi_note_zero"] == 1


def test_a_voice_outside_the_exported_range_is_its_own_reason(tmp_path):
    dist = _dist(tmp_path / "d", [([_event(0, voice=9)], True)])
    got = _run(dist, tmp_path)
    assert got["omissions_by_reason"]["voice_outside_exported_range"] == 1


def test_the_interpretation_does_not_claim_omitted_events_are_unpitched():
    """The scientific qualification: `unrecoverable` means the pipeline
    could not determine a pitch, not that the sound had none."""
    text = ledger.INTERPRETATION["no_pitch_recovered"]
    assert "not the same as" in text
    assert "may have been" in text or "may be" in text
