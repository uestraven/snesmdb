"""The provenance block recorded with a corpus."""

from __future__ import annotations

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
