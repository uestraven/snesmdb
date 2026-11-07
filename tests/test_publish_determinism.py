"""Published bytes must depend only on published content.

The release pin exists so two trees can be compared. `gzip.open` stamps the
current time into each member header, which broke that: between the
`gate5-rc1` and `gate5-rc2` trees every one of the 3,948 compressed files
changed hash while all 3,948 were byte-identical once decompressed. Only a
documentation file had actually changed. A consumer diffing two downloads by
hash would have concluded the whole dataset had moved.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import publish  # noqa: E402

PAYLOAD = {"schema": "snesmdb.events.v1", "events": [{"onset_sec": 0.5}]}


def test_identical_content_produces_identical_bytes(tmp_path):
    """Written twice, at different times, into different files."""
    first, second = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    publish.write_json_gz(first, PAYLOAD)
    publish.write_json_gz(second, PAYLOAD)
    assert first.read_bytes() == second.read_bytes()


def test_different_content_produces_different_bytes(tmp_path):
    """The other half of the claim: a hash difference must still mean a
    content difference. Determinism is worthless if it also flattens real
    changes."""
    first, second = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    publish.write_json_gz(first, PAYLOAD)
    publish.write_json_gz(second, dict(PAYLOAD, events=[{"onset_sec": 0.6}]))
    assert first.read_bytes() != second.read_bytes()


def test_the_payload_round_trips(tmp_path):
    """Determinism must not come at the cost of writing something a consumer
    cannot read with plain `gzip.open`."""
    path = tmp_path / "a.json.gz"
    publish.write_json_gz(path, PAYLOAD)
    with gzip.open(path, "rt") as handle:
        assert json.load(handle) == PAYLOAD


def test_no_timestamp_is_embedded(tmp_path):
    """Checked at the byte level rather than inferred: bytes 4..8 of a gzip
    member are the MTIME field."""
    path = tmp_path / "a.json.gz"
    publish.write_json_gz(path, PAYLOAD)
    assert int.from_bytes(path.read_bytes()[4:8], "little") == 0


def test_every_published_gzip_goes_through_the_helper():
    """A fourth write site added later with `gzip.open` would silently
    reintroduce the defect for one format only, which is harder to notice than
    reintroducing it everywhere."""
    source = (ROOT / "tools" / "publish.py").read_text()
    offenders = [
        line.strip() for line in source.splitlines()
        if "gzip.open" in line and '"wt"' in line or
        ("gzip.open" in line and '"wb"' in line)
    ]
    assert not offenders, offenders
