"""The corpus gate. Each check must FAIL on the defect it is named for.

A gate that cannot fail is decoration, so every check here is exercised
against a corpus deliberately broken in exactly the way that shipped.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "verify_corpus",
    Path(__file__).resolve().parent.parent / "tools" / "verify_corpus.py",
)
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)


def _row(track_id="t:1", clock_ticks=2048, rows=100, poly=8, srcn=1,
         unhandled=None, note_id=0, parent=0):
    return {
        "ok": True,
        "track_id": track_id,
        "tag": {"game": "G", "title": "t"},
        "clock": {"period_ticks": clock_ticks, "source": "timer_register"},
        "scores": {"n_rows": rows, "max_polyphony": poly},
        "summary": {"unhandled_writes": unhandled or {}},
        "record_path": "records/t_1.json",
        "_note_id": note_id,
        "_parent": parent,
        "_srcn": srcn,
    }


def _corpus(tmp_path: Path, rows, *, summary=True, records=True):
    out = tmp_path / "out"
    (out / "records").mkdir(parents=True)
    with (out / "manifest.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    if records:
        for row in rows:
            (out / row["record_path"]).write_text(json.dumps({
                "notes": [{"note_id": row["_note_id"], "srcn": row["_srcn"]}],
                "legato_steps": [{"parent_note_id": row["_parent"]}],
            }))
    if summary:
        (out / "summary.json").write_text(json.dumps({
            "clock": {"n_clocked": len(rows)},
            "provenance": {"git_commit": "abc"},
        }))
    return out


def _run(out, dist=None):
    report = vc.Report()
    vc.check_out_dir(out, report)
    vc.check_records(out, report, 60)
    if dist is not None:
        vc.check_dist(dist, report)
    return report


def _failed(report):
    return {line.split()[1].rstrip(":") for line in report.failures}


def test_a_healthy_corpus_passes(tmp_path):
    report = _run(_corpus(tmp_path, [_row()]))
    assert report.failures == [], report.failures


def test_a_missing_clock_fails(tmp_path):
    """The defect the broken rebuild recipe produced: reclock.py skipped, so
    publish found no clock and wrote nothing, silently."""
    report = _run(_corpus(tmp_path, [_row(clock_ticks=0)]))
    assert "clock_on_every_track" in _failed(report)


def test_partial_score_coverage_fails(tmp_path):
    """publish.py keyed on row["grid"] and would have shipped 866 of 1,316."""
    report = _run(_corpus(tmp_path, [_row(), _row("t:2", rows=0)]))
    assert "scores_cover_corpus" in _failed(report)


def test_polyphony_above_the_hardware_limit_fails(tmp_path):
    """Blended polyphony reached 9 on eight-voice hardware."""
    report = _run(_corpus(tmp_path, [_row(poly=9)]))
    assert "polyphony_within_hardware" in _failed(report)


def test_unhandled_registers_fail(tmp_path):
    report = _run(_corpus(tmp_path, [_row(unhandled={"MYSTERY": 7})]))
    assert "no_unhandled_dsp_registers" in _failed(report)


def test_a_stale_summary_fails(tmp_path):
    """summary.json headlined the onset grid's 866 as the timing statistic,
    contradicting index.json in the same tree."""
    out = _corpus(tmp_path, [_row()])
    (out / "summary.json").write_text(json.dumps(
        {"grid": {"n_found": 866}, "provenance": {"git_commit": "abc"}}
    ))
    assert "summary_not_stale" in _failed(_run(out))


def test_missing_provenance_fails(tmp_path):
    out = _corpus(tmp_path, [_row()])
    (out / "summary.json").write_text(json.dumps({"clock": {"n_clocked": 1}}))
    assert "provenance_recorded" in _failed(_run(out))


def test_degenerate_srcn_fails(tmp_path):
    """Voice state unseeded from the SPC put 10.8% of notes on sample 0."""
    rows = [_row(f"t:{i}", srcn=0) for i in range(10)]
    for i, row in enumerate(rows):
        row["record_path"] = f"records/t_{i}.json"
    assert "srcn_not_degenerate" in _failed(_run(_corpus(tmp_path, rows)))


def test_an_unresolvable_legato_parent_fails(tmp_path):
    """note_id was never published, so the parent link was unresolvable."""
    report = _run(_corpus(tmp_path, [_row(note_id=0, parent=999)]))
    assert "legato_parents_resolve" in _failed(report)


def test_leaked_audio_in_dist_fails(tmp_path):
    """The licence constraint: nothing derived from the SPCs ships as audio."""
    out = _corpus(tmp_path, [_row()])
    dist = tmp_path / "dist"
    (dist / "midi").mkdir(parents=True)
    (dist / "index.json").write_text(json.dumps([{"scores": "s.json.gz"}]))
    (dist / "provenance.json").write_text("{}")
    (dist / "midi" / "leak.wav").write_bytes(b"RIFF")
    assert "no_audio_or_spc_in_dist" in _failed(_run(out, dist))


def test_a_dist_without_provenance_fails(tmp_path):
    out = _corpus(tmp_path, [_row()])
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.json").write_text(json.dumps([{"scores": "s.json.gz"}]))
    assert "dist_provenance" in _failed(_run(out, dist))


def test_an_index_entry_without_scores_fails(tmp_path):
    out = _corpus(tmp_path, [_row()])
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.json").write_text(json.dumps([{"track_id": "t:1"}]))
    (dist / "provenance.json").write_text("{}")
    assert "dist_scores_cover_index" in _failed(_run(out, dist))


def test_the_exit_code_is_the_failure_count(tmp_path):
    """So `make` stops on any failure."""
    report = _run(_corpus(tmp_path, [_row(clock_ticks=0, poly=9)]))
    assert len(report.failures) >= 2


def test_a_missing_manifest_is_an_error_not_a_pass(tmp_path):
    out = tmp_path / "empty"
    out.mkdir()
    with pytest.raises(SystemExit):
        vc.check_out_dir(out, vc.Report())
