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


def test_a_pre_v1_bare_list_index_still_freezes(tmp_path):
    """A corpus published before the index became a document can still be
    pinned for evaluation; its `index_schema` is simply absent."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.json").write_text(json.dumps([{"track_id": "x:1"}]))
    pin = freeze.build(dist, "rc1")
    assert pin["index_schema"] is None
    assert pin["n_tracks_in_index"] == 1
