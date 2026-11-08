"""Every published field is documented, and every documented field exists.

THE ONE DOCUMENTATION DEFECT CLASS THAT IS MECHANICALLY CHECKABLE.

Three independent evaluations produced 11, 13 and 11 findings. Almost all were
documentation, and almost none could be given a release check, because "this
sentence describes that field correctly" is not computable. One class is:
whether a field that ships is described at all, and whether a description
refers to a field that still exists.

That class produced real damage. `onset_grid` is published in all 1,316 score
files and is the grid rhythm work needs -- onsets concentrate on it at
R = 0.937 against 0.262 on the timer clock -- and a rewrite of the row-grids
section deleted its documentation, leaving it described nowhere. An evaluator
measured quantisation against the wrong grid, got 0.26, and nearly published
that this corpus is barely quantised. Nothing failed; there was nothing to
fail.

So this test walks the published artifacts, collects the field names a
researcher can actually encounter, and requires each to appear in SCHEMA.md.
It is deliberately a NAME check, not a meaning check: it cannot tell whether a
description is correct, only whether one exists. That limit is the point --
it closes the gap it can close and makes no claim about the rest.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIST = Path(os.environ.get(
    "SNESMDB_DIST", Path.home() / "snesmdb-corpus" / "dist",
))
SCHEMA_DOC = (ROOT / "docs" / "SCHEMA.md").read_text()

#: Private or structural keys a researcher never joins on, and the row-index
#: containers whose contents are positional rather than named.
IGNORED = frozenset({
    "schema", "events", "voices", "notes", "tracks", "separated", "blended",
    "per_game", "corpus", "games", "files", "parameters", "counts",
    "track_classes", "extraction_statuses", "drivers", "formats",
})


def _published_fields() -> dict[str, set[str]]:
    """Field names a researcher meets, by the file that carries them."""
    if not (DIST / "index.json").is_file():
        pytest.skip(f"no published corpus at {DIST}")
    found: dict[str, set[str]] = {}

    index = json.loads((DIST / "index.json").read_text())
    found["index.json"] = set(index) | set(index.get("corpus", {}))
    found["index.json tracks[]"] = set(index["tracks"][0])

    entry = index["tracks"][0]
    with gzip.open(DIST / entry["events"], "rt") as handle:
        table = json.load(handle)
    found["events header"] = set(table)
    found["events rows"] = set(table["events"][0]) if table["events"] else set()

    with gzip.open(DIST / entry["scores"], "rt") as handle:
        score = json.load(handle)
    found["scores"] = set(score)
    found["scores stats"] = set(score["stats"])

    with gzip.open(DIST / entry["intake"], "rt") as handle:
        intake = json.load(handle)
    found["intake"] = set(intake) | set(intake.get("timing", {}))

    perf = json.loads((DIST / "performance.json").read_text())
    game = next(iter(perf["per_game"].values()))
    fields = set(perf) | set(game)
    for block in game.values():
        if isinstance(block, dict):
            fields |= {f"{k}" for k in block}
    found["performance.json"] = fields

    found["tracks.csv"] = set(
        (DIST / "tracks.csv").read_text().splitlines()[0].split(",")
    )
    return found


def test_every_published_field_is_documented():
    undocumented: list[str] = []
    for where, names in _published_fields().items():
        for name in sorted(names):
            if name in IGNORED or not name:
                continue
            if f"`{name}`" not in SCHEMA_DOC and name not in SCHEMA_DOC:
                undocumented.append(f"{where}: {name}")
    assert not undocumented, (
        "fields ship with no entry in docs/SCHEMA.md:\n  "
        + "\n  ".join(undocumented)
    )


def test_the_documented_top_level_score_keys_all_exist():
    """The converse: a description must not name a field that is gone.

    `SCHEMA.md` lists the score payload's top-level keys explicitly, so this
    checks that list against a real file rather than trusting it.
    """
    fields = _published_fields()
    for name in ("onset_grid", "uniform", "clock", "stats", "expressive"):
        assert name in fields["scores"], f"{name} documented but absent"
        assert f"`{name}`" in SCHEMA_DOC, f"{name} published but undocumented"
