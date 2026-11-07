"""The verifier that ships inside the research package.

This is the one executable a recipient gets, and its whole job is to answer a
question that cost real work to answer by hand: is this copy damaged, or is
the release? An evaluator received a tree whose `index.json` had been
truncated mid-string by a short write at a 768 KiB boundary, could not tell
those apart, and reported the release as corrupt after a careful
investigation. The data was perfect.

So the distinction between a WRONG LENGTH and a WRONG HASH is the thing under
test here: the first means the transfer failed, the second means something
altered the contents, and conflating them sends the reader after the wrong
cause.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import freeze_release as freeze  # noqa: E402

SCRIPT = ROOT / "tools" / "package_verify.py"


def _pinned_tree(root: Path) -> Path:
    dist = root / "dist"
    (dist / "events").mkdir(parents=True)
    (dist / "index.json").write_text(json.dumps(
        {"schema": "snesmdb.index.v1", "tracks": [{"track_id": "x:1"}] * 200}
    ))
    (dist / "events" / "a.json.gz").write_bytes(b"payload bytes")
    (dist / "provenance.json").write_text(json.dumps({"git_commit": "abc123"}))
    pin = freeze.build(dist, "test-rc")
    (dist / freeze.RELEASE_FILE).write_text(json.dumps(pin, indent=1))
    return dist


def _run(dist: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(dist)],
        capture_output=True, text=True, timeout=120,
    )


def test_the_verifier_needs_nothing_from_this_project():
    """It runs on a recipient's machine, where `src/snesmdb` does not exist."""
    import ast
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"hashlib", "json", "sys", "pathlib", "__future__"}


def test_an_intact_tree_exits_zero(tmp_path):
    done = _run(_pinned_tree(tmp_path))
    assert done.returncode == 0, done.stdout
    assert "INTACT" in done.stdout


def test_a_short_write_is_reported_as_a_damaged_copy(tmp_path):
    """The reported incident, reproduced: truncation must name the transfer
    as the cause, not the release."""
    dist = _pinned_tree(tmp_path)
    raw = (dist / "index.json").read_bytes()
    (dist / "index.json").write_bytes(raw[: int(len(raw) * 0.56)])
    done = _run(dist)
    assert done.returncode != 0
    assert "TRUNCATED" in done.stdout
    assert "index.json" in done.stdout
    assert "56.0%" in done.stdout
    assert "DAMAGED COPY" in done.stdout
    assert "Re-copy" in done.stdout
    # It must NOT suggest the release itself is at fault.
    assert "NOT INTACT" not in done.stdout


def test_altered_contents_at_the_right_length_are_distinguished(tmp_path):
    """Same length, different bytes. That is not a transfer failure, and
    saying "re-copy" would send the reader after the wrong cause."""
    dist = _pinned_tree(tmp_path)
    raw = (dist / "index.json").read_bytes()
    (dist / "index.json").write_bytes(b"X" + raw[1:])
    done = _run(dist)
    assert done.returncode != 0
    assert "ALTERED" in done.stdout
    assert "right size, wrong contents" in done.stdout
    assert "DAMAGED COPY" not in done.stdout


def test_a_missing_file_is_reported(tmp_path):
    dist = _pinned_tree(tmp_path)
    (dist / "events" / "a.json.gz").unlink()
    done = _run(dist)
    assert done.returncode != 0
    assert "MISSING" in done.stdout


def test_an_unreadable_pin_says_so_instead_of_crashing(tmp_path):
    """If RELEASE.json is itself truncated there is nothing to check against,
    and a traceback would leave the recipient guessing."""
    dist = _pinned_tree(tmp_path)
    (dist / freeze.RELEASE_FILE).write_text('{"files": {"a"')
    done = _run(dist)
    assert done.returncode != 0
    assert "unreadable" in done.stdout + done.stderr
    assert "re-copy" in (done.stdout + done.stderr).lower()


def test_a_missing_pin_explains_the_usage(tmp_path):
    bare = tmp_path / "nothing"
    bare.mkdir()
    done = _run(bare)
    assert done.returncode != 0
    assert "no RELEASE.json" in done.stdout + done.stderr


def test_the_pin_and_its_archive_are_not_flagged_as_unlisted(tmp_path):
    """They are excluded from the pin by construction -- a pin cannot contain
    its own hash. An evaluator's own verifier reported both as "unlisted on
    disk", which reads as a discrepancy and is not one."""
    dist = _pinned_tree(tmp_path)
    (dist / "releases").mkdir()
    (dist / "releases" / "test-rc.json").write_text("{}")
    done = _run(dist)
    assert done.returncode == 0, done.stdout
    assert "UNLISTED" not in done.stdout
