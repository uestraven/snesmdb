"""The release pin: `snesmdb.release.v1`.

An independent evaluation is only evidence if everyone can say which bytes
were evaluated. These tests run on synthetic trees, so they check the pin's
behaviour rather than any particular corpus.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import freeze_release as freeze  # noqa: E402


def _tree(root: Path) -> Path:
    dist = root / "dist"
    (dist / "events").mkdir(parents=True)
    (dist / "index.json").write_text(json.dumps({
        "schema": "snesmdb.index.v1",
        "formats": {"events": "snesmdb.events.v1"},
        "corpus": {"n_tracks": 1},
        "tracks": [{"track_id": "x:1"}],
    }))
    (dist / "events" / "x.json.gz").write_bytes(b"not really gzip")
    return dist


def test_the_pin_separates_build_provenance_from_freeze_provenance(tmp_path):
    """Freezing happens after building, often several commits later. A single
    field read as "the commit that produced this corpus" named the checkout at
    freeze time instead -- correct by coincidence for the first release, and
    wrong by three commits for the second."""
    dist = _tree(tmp_path)
    (dist / "provenance.json").write_text(json.dumps({
        "git_commit": "aaaaaaa", "git_branch": "main",
        "built_utc": "2026-11-07T07:02:00Z", "dirty": False,
    }))
    pin = freeze.build(dist, "rc1")
    assert pin["built_from"]["git_commit"] == "aaaaaaa"
    assert "git_commit" in pin["frozen_by"]
    # The freeze's own commit comes from the live checkout, so it is whatever
    # this repository is on -- the point is only that it is a SEPARATE field.
    assert pin["frozen_by"]["git_commit"] != "aaaaaaa"


def test_a_tree_without_provenance_still_freezes(tmp_path):
    """An older or hand-assembled tree has no provenance.json. That makes the
    build commit unknown, which must be reported as empty rather than
    silently filled in from the current checkout."""
    dist = _tree(tmp_path)
    assert freeze.build(dist, "rc1")["built_from"] == {}


def test_the_pin_covers_every_published_file(tmp_path):
    dist = _tree(tmp_path)
    pin = freeze.build(dist, "rc1")
    assert pin["schema"] == freeze.SCHEMA
    assert set(pin["files"]) == {"index.json", "events/x.json.gz"}
    assert pin["n_files"] == 2
    assert pin["n_tracks_in_index"] == 1
    assert pin["index_schema"] == "snesmdb.index.v1"


def test_the_pin_does_not_hash_itself(tmp_path):
    """A file whose contents include its own hash cannot be verified."""
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text("{}")
    assert freeze.RELEASE_FILE not in freeze.build(dist, "rc1")["files"]


def test_an_intact_tree_verifies_clean(tmp_path, capsys):
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text(
        json.dumps(freeze.build(dist, "rc1"))
    )
    assert freeze.verify(dist) == 0
    assert "intact" in capsys.readouterr().out


def test_a_changed_byte_is_caught(tmp_path, capsys):
    """The failure this exists to catch: a tree rebuilt or touched partway
    through an evaluation, which `provenance.json` cannot detect because it
    records the commit and not the bytes."""
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text(
        json.dumps(freeze.build(dist, "rc1"))
    )
    (dist / "events" / "x.json.gz").write_bytes(b"not really gzip!")
    assert freeze.verify(dist) == 1
    out = capsys.readouterr().out
    assert "CHANGED" in out and "NOT the frozen artifact" in out


def test_a_missing_file_is_caught(tmp_path, capsys):
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text(
        json.dumps(freeze.build(dist, "rc1"))
    )
    (dist / "events" / "x.json.gz").unlink()
    assert freeze.verify(dist) == 1
    assert "MISSING" in capsys.readouterr().out


def test_an_extra_file_is_caught(tmp_path, capsys):
    """An artifact with a file nobody pinned is not the frozen artifact
    either, even though nothing pinned has changed."""
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text(
        json.dumps(freeze.build(dist, "rc1"))
    )
    (dist / "events" / "y.json.gz").write_bytes(b"later addition")
    assert freeze.verify(dist) == 1
    assert "ADDED" in capsys.readouterr().out


def test_freezing_a_tree_with_no_index_is_refused(tmp_path):
    empty = tmp_path / "dist"
    empty.mkdir()
    with pytest.raises(SystemExit, match="nothing to freeze"):
        freeze.build(empty, "rc1")


def test_verifying_an_unpinned_tree_is_refused(tmp_path):
    dist = _tree(tmp_path)
    with pytest.raises(SystemExit, match="nothing to verify"):
        freeze.verify(dist)


def test_the_pin_archive_is_not_part_of_the_pinned_tree(tmp_path):
    """Otherwise writing a pin would change the tree it is pinning, and no
    pin could ever verify."""
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_DIR).mkdir()
    (dist / freeze.RELEASE_DIR / "rc0.json").write_text("{}")
    pin = freeze.build(dist, "rc1")
    assert not any(
        key.startswith(f"{freeze.RELEASE_DIR}/") for key in pin["files"]
    )
    (dist / freeze.RELEASE_FILE).write_text(json.dumps(pin))
    assert freeze.verify(dist) == 0


def _freeze_cli(dist: Path, *args: str, monkeypatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["freeze_release.py", str(dist), *args],
    )
    freeze.main()


def test_superseding_a_candidate_is_refused_and_archives_the_old_pin(
    tmp_path, monkeypatch
):
    """The refusal message promises the outgoing pin is kept. An earlier
    version archived only the INCOMING pin while printing that promise, so
    --replace would have destroyed exactly the record it claimed to preserve.
    """
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text(
        json.dumps(dict(freeze.build(dist, "rc1"), label="rc1"))
    )
    with pytest.raises(SystemExit) as caught:
        _freeze_cli(dist, "--label", "rc2", "--allow-dirty",
                    monkeypatch=monkeypatch)
    assert "already pinned as 'rc1'" in str(caught.value)
    kept = dist / freeze.RELEASE_DIR / "rc1.json"
    assert kept.is_file(), "the message promised an archive that is absent"
    assert json.loads(kept.read_text())["label"] == "rc1"
    # And the live pin is untouched by the refusal.
    assert json.loads(
        (dist / freeze.RELEASE_FILE).read_text()
    )["label"] == "rc1"


def test_replace_supersedes_and_both_pins_survive(tmp_path, monkeypatch):
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text(
        json.dumps(dict(freeze.build(dist, "rc1"), label="rc1"))
    )
    _freeze_cli(dist, "--label", "rc2", "--replace", "--allow-dirty",
                monkeypatch=monkeypatch)
    assert json.loads(
        (dist / freeze.RELEASE_FILE).read_text()
    )["label"] == "rc2"
    for label in ("rc1", "rc2"):
        path = dist / freeze.RELEASE_DIR / f"{label}.json"
        assert path.is_file(), f"{label} pin lost"
        assert json.loads(path.read_text())["label"] == label


def test_refreezing_the_same_label_needs_no_replace(tmp_path, monkeypatch):
    """Re-pinning the same candidate after a rebuild is routine and must not
    require a flag that exists to protect a different candidate."""
    dist = _tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text(
        json.dumps(dict(freeze.build(dist, "rc1"), label="rc1"))
    )
    _freeze_cli(dist, "--label", "rc1", "--allow-dirty",
                monkeypatch=monkeypatch)
    assert json.loads(
        (dist / freeze.RELEASE_FILE).read_text()
    )["label"] == "rc1"


def test_a_pre_v1_bare_list_index_still_freezes(tmp_path):
    """A corpus published before the index became a document can still be
    pinned for evaluation; its `index_schema` is simply absent."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.json").write_text(json.dumps([{"track_id": "x:1"}]))
    pin = freeze.build(dist, "rc1")
    assert pin["index_schema"] is None
    assert pin["n_tracks_in_index"] == 1
