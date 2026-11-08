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


# ---------------------------------------------------------------------------
# The claim registry
# ---------------------------------------------------------------------------

CLAIMS = json.loads((ROOT / "docs" / "claims.json").read_text())
KINDS = frozenset({"measurement", "estimate", "interpretation"})


def test_every_registered_claim_is_well_formed():
    """A registry that lets a claim omit its kind or its evidence would be a
    list of numbers, which is what it exists to replace."""
    seen = set()
    for claim in CLAIMS["claims"]:
        assert claim["id"] not in seen, f"duplicate id {claim['id']}"
        seen.add(claim["id"])
        assert claim["kind"] in KINDS, claim["id"]
        assert claim["description"] and claim["documented_in"], claim["id"]
        if claim["kind"] == "interpretation":
            assert claim.get("not_checkable_because"), (
                f"{claim['id']}: an unverifiable claim must say why"
            )
        else:
            assert claim.get("method"), claim["id"]
            assert claim.get("reported"), claim["id"]
            assert claim.get("reads") and claim.get("independent_of"), claim["id"]
        if claim["kind"] == "estimate":
            assert claim.get("assumes"), (
                f"{claim['id']}: an estimate must name its assumption, or it "
                f"is being published as a measurement"
            )


def test_every_registered_method_exists_in_the_runner():
    source = (ROOT / "tools" / "replicate.py").read_text()
    for claim in CLAIMS["claims"]:
        if claim.get("method"):
            assert f"def {claim['method']}(" in source, claim["method"]


def test_the_runner_imports_nothing_from_this_project():
    """It ships to recipients and must not borrow the code under test: a
    replication that imported the extraction library would be circular."""
    import ast as ast_mod
    tree = ast_mod.parse((ROOT / "tools" / "replicate.py").read_text())
    imported = set()
    for node in ast_mod.walk(tree):
        if isinstance(node, ast_mod.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast_mod.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "snesmdb" not in imported, sorted(imported)
    assert imported <= {
        "argparse", "gzip", "json", "math", "statistics", "struct",
        "pathlib", "typing", "__future__",
    }, sorted(imported)


def test_most_checkable_claims_read_a_different_representation():
    """The property that makes replication worth more than a second opinion:
    two calculations over one extraction can agree while both are wrong. Not
    every claim can manage it, so this asserts a majority and requires the
    exceptions to be declared."""
    checkable = [c for c in CLAIMS["claims"] if c.get("method")]
    cross = [c for c in checkable if not c.get("same_representation")]
    assert len(cross) > len(checkable) / 2, (
        f"only {len(cross)}/{len(checkable)} claims are cross-representation"
    )


def test_every_checkable_claim_declares_its_statistical_unit():
    """Pooling over tracks lets one game drive 1 observation in 7.

    Earthbound is 13.8% of music tracks and games range 17 to 139, so a
    per-track pooled figure is weighted by what was collected rather than by
    anything musical. A claim that does not say which unit it was computed
    over cannot be compared with one that used a different unit.
    """
    units = set(CLAIMS["units_of_analysis"]) - {"note"}
    for claim in CLAIMS["claims"]:
        if not claim.get("method"):
            continue
        unit = claim.get("unit_of_analysis")
        assert unit in units, f"{claim['id']}: unit {unit!r} not registered"


def test_no_claim_asserts_it_generalises_beyond_the_corpus():
    """22 games of roughly 700 commercial SNES titles, JRPG- and
    first-party-weighted. A corpus-wide figure describes the sample that was
    collected; calling it an SNES convention would be a claim about a
    population this corpus does not sample."""
    assert CLAIMS["generalisation"]["sample_composition"]
    for claim in CLAIMS["claims"]:
        if claim.get("method"):
            assert claim.get("generalises_beyond_corpus") is False, claim["id"]


def test_every_checkable_claim_names_a_registered_population():
    """Which sampling frame a figure describes.

    `generalises_beyond_corpus: false` says a claim is not about SNES music.
    This says which subset of the corpus it IS about, and several distinct
    populations live inside one corpus: all indexed tracks, music tracks,
    game-weighted music, pitched attacks, dense sample groups. Two figures
    over different frames are not comparable, and a 22-game report cannot be
    read against a 50-game one unless both name their frame.
    """
    frames = set(CLAIMS["populations"]) - {"note"}
    for claim in CLAIMS["claims"]:
        if not claim.get("method"):
            continue
        assert claim.get("population") in frames, (
            f"{claim['id']}: population {claim.get('population')!r} not registered"
        )


def test_every_population_states_a_selection_rule_not_a_size():
    """A rule survives a corpus expansion; a size does not. Recording sizes
    here would make the registry stale the moment the corpus grows, which is
    exactly when it needs to be readable."""
    for key, frame in CLAIMS["populations"].items():
        if key == "note":
            continue
        assert frame.get("rule") and frame.get("unit"), key
        assert not any(
            isinstance(v, (int, float)) for v in frame.values()
        ), f"{key}: a population must not record a size"
