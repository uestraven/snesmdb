"""Assembling the research package.

Both tests here exist because the thing they check failed in practice while
producing `gate5-rc4`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import freeze_release as freeze  # noqa: E402
import make_research_package as pack  # noqa: E402


def _pinned(root: Path) -> Path:
    dist = root / "dist"
    (dist / "events").mkdir(parents=True)
    (dist / "index.json").write_text(json.dumps({
        "schema": "snesmdb.index.v1", "formats": {}, "corpus": {},
        "tracks": [{"track_id": "x:1"}],
    }))
    (dist / "events" / "x.json.gz").write_bytes(b"payload")
    (dist / "provenance.json").write_text(json.dumps({"git_commit": "abc"}))
    pin = freeze.build(dist, "test-rc")
    (dist / freeze.RELEASE_FILE).write_text(json.dumps(pin, indent=1))
    return dist


def test_documents_keep_their_repository_paths(tmp_path, monkeypatch):
    """So the relative links inside them resolve in the package exactly as
    they do in the repository.

    They were written to the package root, which broke `README.md`'s own links
    to `docs/DATASET.md` -- a document pointing at a path the package did not
    have, which is the same defect the layout change was fixing.
    """
    dist = _pinned(tmp_path)
    package = tmp_path / "pkg"
    monkeypatch.setattr(sys, "argv", [
        "make_research_package.py", str(dist), str(package),
    ])
    pack.main()
    for _, name in pack.DOCS:
        assert (package / name).is_file(), name
    assert (package / "docs").is_dir(), (
        "a nested destination must be created, not assumed"
    )
    assert (package / pack.VERIFY_SCRIPT).is_file()
    assert (package / "START-HERE.md").is_file()


def test_nothing_incomplete_is_left_on_disk_after_a_failure(
    tmp_path, monkeypatch
):
    """A half-built package looks like a package.

    This is not hypothetical: a missing parent directory for `docs/DATASET.md`
    raised after `dist/` had already been copied, leaving a tree with the
    corpus and no documentation. The audit and the copy check delete on
    rejection; an unexpected exception did not.
    """
    dist = _pinned(tmp_path)
    package = tmp_path / "pkg"
    monkeypatch.setattr(sys, "argv", [
        "make_research_package.py", str(dist), str(package),
    ])
    boom = RuntimeError("something failed partway through")

    def explode(*_args, **_kwargs):
        raise boom

    # Fail AFTER the corpus copy, which is the ordering that produced the
    # misleading leftover.
    real_copyfile = shutil.copyfile
    monkeypatch.setattr(pack.shutil, "copyfile", explode)
    with pytest.raises(RuntimeError):
        pack.main()
    monkeypatch.setattr(pack.shutil, "copyfile", real_copyfile)
    assert not package.exists(), "a partial package survived a failure"
