"""The provenance block recorded with a corpus."""

from __future__ import annotations

import json
from pathlib import Path

from snesmdb import provenance


def test_dirty_paths_are_not_truncated():
    """A fixed line[3:] slice ate the first character and reported
    `ools/extract.py`. The porcelain prefix is two code columns plus a
    space, but a staged-and-modified entry fills the second column."""
    status = " M tools/extract.py\nM  src/snesmdb/clock.py\n?? newfile.py"
    assert provenance._dirty_paths(status) == [
        "newfile.py", "src/snesmdb/clock.py", "tools/extract.py",
    ]


def test_a_rename_reports_the_new_name():
    status = 'R  old/path.py -> new/path.py'
    assert provenance._dirty_paths(status) == ["new/path.py"]


def test_quoted_paths_are_unquoted():
    status = '?? "a file with spaces.py"'
    assert provenance._dirty_paths(status) == ["a file with spaces.py"]


def test_a_clean_tree_has_no_dirty_paths():
    assert provenance._dirty_paths("") is None
    assert provenance._dirty_paths("\n\n") is None


def test_unavailable_git_is_none_not_clean():
    """None means "could not tell"; an empty list would claim the tree was
    clean, which is a different and stronger statement."""
    assert provenance._dirty_paths(None) is None


def test_record_carries_the_fields_an_artifact_needs():
    got = provenance.record(tool="probe", jobs=8)
    assert got["schema"] == provenance.CORPUS_SCHEMA
    for key in ("built_utc", "git_commit", "dirty", "python", "platform"):
        assert key in got
    assert got["parameters"] == {"tool": "probe", "jobs": 8}


def test_none_parameters_are_dropped_rather_than_recorded_as_null():
    got = provenance.record(tool="probe", limit=None)
    assert "limit" not in got["parameters"]
    assert got["parameters"]["tool"] == "probe"


def test_dirty_is_a_boolean_so_a_provisional_build_is_visible():
    """A corpus built from an uncommitted tree cannot be reproduced from the
    commit it names, so the flag has to be readable without parsing paths."""
    got = provenance.record()
    assert got["dirty"] in (True, False, None)


def test_a_clean_tree_reports_dirty_false_not_none():
    """`git status --porcelain` says "clean" by printing nothing, and the
    _git helper used to collapse that into None -- so a committed build
    reported `dirty: None`, claiming ignorance of something it knew. None is
    reserved for git being unavailable."""
    got = provenance.record()
    # This repo has git, so the flag must be decided either way.
    assert got["dirty"] in (True, False)
    assert got["git_commit"], "a repo with git must report a commit"


def test_git_returns_empty_string_not_none_for_empty_output():
    out = provenance._git("status", "--porcelain")
    assert out is not None, "git is available here, so this is not unknown"
    assert isinstance(out, str)


#: Keys that must never appear in a published provenance record. Not
#: reproducibility data, and `provenance.json` ships inside every
#: distribution: `host` and `user` were disclosing an operator's account name
#: and an internal hostname to everyone who received the corpus.
IDENTIFYING_KEYS = ("host", "user", "hostname", "username", "home", "cwd")


def test_published_provenance_identifies_the_build_not_the_builder():
    record = provenance.record(tool="test")
    present = [key for key in IDENTIFYING_KEYS if key in record]
    assert not present, f"provenance would publish {present}"


def test_provenance_still_records_what_reproducibility_needs():
    """The fix must not throw away the useful part: a reader has to know the
    commit, whether it was clean, and the interpreter and platform."""
    record = provenance.record(tool="test")
    for key in ("git_commit", "dirty", "python", "platform", "built_utc"):
        assert key in record, key


def test_no_identifying_value_leaks_through_the_parameters_block():
    """`parameters` is published verbatim, so a path reintroduces the
    disclosure by another route.

    AND IT DID. The first version of this test passed a RELATIVE path, so it
    never exercised the case that occurs in practice: `publish.py` records an
    absolute `dist_dir`, and the published record read
    `"dist_dir": "/home/<login>/snesmdb-corpus/dist"` while every identifying
    KEY was gone. The release gate caught what this test had missed. It now
    passes the absolute paths the real callers pass.
    """
    import os
    login = os.environ.get("USER") or "nobody"
    record = provenance.record(
        tool="test",
        dist_dir=str(Path.home() / "corpus" / "dist"),
        out_dir=f"/local/home/{login}/workplace/snesmdb/data/out",
    )
    serialised = json.dumps(record)
    assert login not in serialised, serialised
    assert "/Users/" not in serialised
    # The path must stay meaningful, not just anonymous: an earlier scrubber
    # replaced the home prefix anywhere it appeared and produced `/local~/...`.
    assert record["parameters"]["dist_dir"] == "~/corpus/dist"
    assert record["parameters"]["out_dir"].startswith("/local/home/<user>/")


def test_scrubbing_leaves_non_strings_and_plain_paths_alone():
    assert provenance.scrub(42) == 42
    assert provenance.scrub(None) is None
    assert provenance.scrub("data/out") == "data/out"
    assert provenance.scrub({"a": ["data/out", 1]}) == {"a": ["data/out", 1]}
