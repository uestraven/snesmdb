"""Subset mode: audits a part of the corpus without weakening the whole.

AN AUDIT INFRASTRUCTURE CORRECTION, found during the F-Zero pilot. Two checks
silently assumed they were looking at all 1,316 tracks:

  * `dist_sample_ids_plausible` asserts `len(ids) > 100`, an absolute floor
    calibrated for the full corpus. F-Zero resolves 24 distinct samples
    across 17 tracks, which is plausible for a 1991 launch title with a small
    ARAM bank, and the check failed on it.
  * `dist_documented_row_duration_matches` requires the MEASURED range string
    to appear in `DATASET.md`. F-Zero runs one rate and measures
    2.000-2.000 ms, which is INSIDE the documented 2.000-30.500 ms. The check
    asserted equality where containment is the correct relation for a part.

Neither was an extraction defect, and neither justified relaxing anything for
the full corpus. So `--subset` replaces exactly those two assertions with
subset-scoped equivalents and keeps every other check.

THE POINT OF THIS FILE IS THE NEGATIVE CASES. A subset mode that stopped
detecting corrupted published data would be worse than the false failures it
replaces, so most of what follows breaks a subset deliberately and requires
subset mode to notice.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "verify_corpus",
    Path(__file__).resolve().parent.parent / "tools" / "verify_corpus.py",
)
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)

#: The documented corpus-wide span, as DATASET.md states it.
DOC = "| row duration | **2.000–30.500 ms**, median 4.875 |\n"


def _event(event_id, origin="key_on", parent=None, midi=60.0, sample="a1b2"):
    return {
        "event_id": event_id, "parent_event_id": parent, "origin": origin,
        "onset_sec": 0.1 * event_id, "duration_sec": 0.05, "voice": 0,
        "pitch_status": "estimated" if midi is not None else "unrecoverable",
        "midi_note": midi, "pitch_confidence": "high" if midi else None,
        "sample_id": sample, "attack_level": 60, "sustain_level": 60,
        "pitch_register": 4096,
    }


def _dist(tmp_path: Path, *, n_tracks=4, period_ticks=2048,
          samples=("a1", "b2", "c3"), break_counts=False,
          break_filter_fields=False, doc=DOC) -> Path:
    """A small but structurally complete published tree."""
    dist = tmp_path / "dist"
    for sub in ("events", "scores", "intake", "midi"):
        (dist / sub).mkdir(parents=True, exist_ok=True)
    tracks = []
    for i in range(n_tracks):
        stem, tid = f"g-{i:02d}_h{i}", f"g-{i:02d}:h{i}"
        events = [
            _event(j, sample=samples[j % len(samples)]) for j in range(4)
        ]
        table = {
            "schema": "snesmdb.events.v3", "track_id": tid, "game": "Game",
            "game_slug": "g", "track_class": "music", "duration_sec": 10.0,
            "extraction_status": "complete_with_pitched_events",
            "event_count": 99 if break_counts else len(events),
            "pitched_event_count": len(events),
            "unpitched_event_count": 0, "attack_count": len(events),
            "legato_step_count": 0, "pitched_attack_count": len(events),
            "events": events,
        }
        if break_filter_fields:
            table["track_class"] = "effect"
        with gzip.open(dist / "events" / f"{stem}.json.gz", "wt") as handle:
            json.dump(table, handle)
        score = {
            "track_id": tid,
            "clock": {"hz": 1_024_000 / period_ticks,
                      "period_ticks": period_ticks, "source": "timer_register"},
            "separated": [[0]], "blended": [[]],
            "expressive": {"channels": ["note", "velocity", "timbre_class",
                                        "sustain"], "voices": []},
            "onset_grid": {"found": False},
            "uniform": {"hz": 100.0, "period_ticks": 10240, "n_rows": 1000,
                        "separated": [[0]], "blended": [[]],
                        "expressive": {"channels": ["note", "velocity",
                                                    "timbre_class", "sustain"],
                                       "voices": []},
                        "stats": {"n_rows": 1000}},
            "stats": {"n_rows": 1000, "max_voices_sounding_per_row": 4},
        }
        with gzip.open(dist / "scores" / f"{stem}.json.gz", "wt") as handle:
            json.dump(score, handle)
        with gzip.open(dist / "intake" / f"{stem}.json.gz", "wt") as handle:
            json.dump({"schema": "snesmdb.intake.v1",
                       "timing": {"ticks_per_second": 1_024_000,
                                  "row_period_ticks": period_ticks,
                                  "driver_tick_hz": None,
                                  "driver_tick_found": False},
                       "voices": []}, handle)
        tracks.append({
            "track_id": tid, "game": "Game", "game_slug": "g",
            "track_class": "music", "composers": ["C"],
            "events": f"events/{stem}.json.gz",
            "scores": f"scores/{stem}.json.gz",
            "intake": f"intake/{stem}.json.gz",
            "event_count": len(events), "pitched_event_count": len(events),
            "attack_count": len(events), "pitched_attack_count": len(events),
            "legato_step_count": 0,
            "extraction_status": "complete_with_pitched_events",
        })
    (dist / "index.json").write_text(json.dumps({
        "schema": "snesmdb.index.v1",
        "formats": {"events": "snesmdb.events.v3"},
        "corpus": {"n_tracks": len(tracks)},
        "games": {"g": "Game"},
        "tracks": tracks,
    }))
    (dist / "tracks.csv").write_text(
        "track_id\n" + "\n".join(t["track_id"] for t in tracks) + "\n"
    )
    (dist / "provenance.json").write_text(json.dumps({"git_commit": "abc"}))
    (dist / "DATASET.md").write_text(doc)
    return dist


def _run(dist: Path, *, subset: bool) -> dict[str, bool]:
    report = vc.Report()
    vc.check_dist(dist, report, exhaustive=True, subset=subset)
    vc.check_events(dist, report, exhaustive=True, subset=subset)
    out: dict[str, bool] = {}
    for line in report.passes:
        out[line.split()[1].rstrip(":")] = True
    for line in report.failures:
        out[line.split()[1].rstrip(":")] = False
    return out


# ---------------------------------------------------------------------------
# Positive: subset mode accepts a small, sound subset that full mode rejects
# ---------------------------------------------------------------------------

def test_a_sound_subset_fails_full_mode_and_passes_subset_mode(tmp_path):
    """The F-Zero situation, reduced: a small correct tree trips two
    corpus-wide assertions and nothing else."""
    dist = _dist(tmp_path)
    full = _run(dist, subset=False)
    assert full["dist_sample_ids_plausible"] is False
    assert full["dist_documented_row_duration_matches"] is False

    sub = _run(dist, subset=True)
    assert sub["subset_sample_ids_not_degenerate"] is True
    assert sub["subset_row_duration_within_documented_range"] is True
    assert "dist_sample_ids_plausible" not in sub
    assert "dist_documented_row_duration_matches" not in sub

    # Subset mode must break nothing that full mode accepted. Comparing the
    # FAILURE SETS says that precisely, and does not require the fixture to be
    # a fully-formed corpus -- this minimal tree legitimately fails a few
    # checks in both modes because it declares one format and one track class.
    substituted = {"dist_sample_ids_plausible",
                   "dist_documented_row_duration_matches"}
    introduced = {"subset_sample_ids_not_degenerate",
                  "subset_row_duration_within_documented_range"}
    full_failures = {k for k, v in full.items() if not v} - substituted
    sub_failures = {k for k, v in sub.items() if not v} - introduced
    assert sub_failures == full_failures, (
        f"subset mode changed an unrelated verdict: "
        f"{sub_failures ^ full_failures}"
    )


def test_subset_mode_keeps_every_other_check(tmp_path):
    """Only the two corpus-wide assertions are substituted; the rest of the
    gate must still be present, or subset mode would be an exemption."""
    dist = _dist(tmp_path)
    sub = _run(dist, subset=True)
    for name in (
        "dist_events_present", "dist_events_counts_reconcile",
        "dist_events_status_consistent", "dist_events_pitch_explained",
        "dist_events_carry_filter_fields", "dist_scores_cover_index",
        "dist_uniform_present", "dist_uniform_wellformed",
        "dist_scores_clocked", "dist_expressive_channels",
        "dist_provenance", "no_audio_or_spc_in_dist",
        "dist_index_declares_schema", "dist_tracks_csv_covers_every_track",
        "dist_slug_to_game_map_complete",
    ):
        assert name in sub, f"{name} absent from subset mode"


# ---------------------------------------------------------------------------
# Negative: subset mode still detects corrupted published data
# ---------------------------------------------------------------------------

def test_subset_mode_detects_header_counts_that_disagree(tmp_path):
    """The reconciliation check, which is the one that catches a table whose
    header does not describe its own rows."""
    dist = _dist(tmp_path, break_counts=True)
    assert _run(dist, subset=True)["dist_events_counts_reconcile"] is False


def test_subset_mode_detects_a_truncated_event_file(tmp_path):
    """A short write, the failure mode a real transfer produced."""
    dist = _dist(tmp_path)
    victim = next((dist / "events").glob("*.json.gz"))
    raw = victim.read_bytes()
    victim.write_bytes(raw[: len(raw) // 2])
    report = vc.Report()
    try:
        vc.check_events(dist, report, exhaustive=True, subset=True)
    except Exception:
        return  # a hard failure is an acceptable detection
    assert report.failures, "a truncated event table went unnoticed"


def test_subset_mode_detects_a_missing_score(tmp_path):
    dist = _dist(tmp_path)
    next((dist / "scores").glob("*.json.gz")).unlink()
    assert _run(dist, subset=True)["dist_scores_clocked"] is False


def test_subset_mode_detects_degenerate_sample_resolution(tmp_path):
    """The defect the corpus-wide floor of 100 existed to catch: directory
    resolution collapsing so every voice reports one sample. The subset floor
    scales with track count rather than abandoning the check."""
    dist = _dist(tmp_path, n_tracks=40, samples=("same",))
    sub = _run(dist, subset=True)
    assert sub["subset_sample_ids_not_degenerate"] is False


def test_subset_mode_detects_a_row_duration_outside_the_documented_range(
    tmp_path
):
    """Containment is still an assertion: a subset whose hardware row falls
    outside the documented span is a real defect and must fail."""
    dist = _dist(tmp_path, period_ticks=64_000)       # 62.5 ms, far outside
    sub = _run(dist, subset=True)
    assert sub["subset_row_duration_within_documented_range"] is False


def test_subset_mode_detects_filter_fields_disagreeing_with_the_index(
    tmp_path
):
    dist = _dist(tmp_path, break_filter_fields=True)
    assert _run(dist, subset=True)["dist_events_carry_filter_fields"] is False


def test_subset_mode_fails_when_the_documented_range_is_absent(tmp_path):
    """If DATASET.md carries no range at all there is nothing to contain the
    subset, which must not read as a pass."""
    dist = _dist(tmp_path, doc="no range here\n")
    assert _run(dist, subset=True)[
        "subset_row_duration_within_documented_range"] is False


# ---------------------------------------------------------------------------
# Full-corpus verification is not weakened
# ---------------------------------------------------------------------------

def test_full_mode_still_applies_the_corpus_wide_assertions(tmp_path):
    dist = _dist(tmp_path, n_tracks=40, samples=("same",))
    full = _run(dist, subset=False)
    assert full["dist_sample_ids_plausible"] is False
    assert "subset_sample_ids_not_degenerate" not in full
    assert "subset_row_duration_within_documented_range" not in full


def test_subset_is_off_by_default():
    """The build gate and the release audit must keep running full-corpus
    verification without anyone remembering a flag."""
    import inspect
    for fn in (vc.check_dist, vc.check_events):
        assert inspect.signature(fn).parameters["subset"].default is False
