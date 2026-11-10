"""The documented figures must equal the measured ones.

The README spent three expansion milestones describing the 27-game release
as the current corpus while the 50-game release sat frozen on disk. Nothing
in it was internally inconsistent -- that is exactly the problem. Every
figure was true of *a* population, the document never said which, and a
reader would have taken the size, composition and evaluation protocol of a
superseded release as current.

Internal consistency cannot catch that. So the figures now come from
`tools/corpus_census.py`, which measures them from a release's own published
artifacts, and these tests assert the prose quotes the artifact. A population
expansion that forgets the documentation now fails the suite.

What this does NOT check is whether a figure is correctly *attributed*. A
cohort-scoped measurement is still legitimate in these documents; it just
has to say which population it describes. That remains a human judgement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CENSUS_PATH = ROOT / "docs" / "corpus_census_50game.json"
README = (ROOT / "README.md").read_text()
DATASET = (ROOT / "docs" / "DATASET.md").read_text()
CHANGELOG = (ROOT / "docs" / "CHANGELOG.md").read_text()
SCHEMA = (ROOT / "docs" / "SCHEMA.md").read_text()


@pytest.fixture(scope="module")
def census() -> dict:
    assert CENSUS_PATH.is_file(), (
        f"{CENSUS_PATH.name} is missing. Regenerate it with "
        f"`make census RELEASE=<release-dir>`; the documentation's figures "
        f"are asserted against it.")
    return json.loads(CENSUS_PATH.read_text())


def grouped(n: int) -> str:
    return f"{n:,}"


#: (README table label, census key). Each row of the results table states one
#: measured figure, and the first grouped number after the label is it.
TABLE_ROWS = [
    ("tracks / games", "tracks"),
    ("events", "events"),
    ("attacks with a recovered pitch", "pitched_attacks"),
    ("attacks with an established sample identity",
     "attacks_with_sample_id"),
    ("attacks published with `sample_id: null`",
     "attacks_without_sample_id"),
    ("distinct sample identities", "distinct_sample_identities"),
    ("tracks with a clock read from a timer register",
     "tracks_with_hardware_clock"),
    ("tracks with a MIDI file", "midi_files"),
    ("tracks carrying a truncated composer credit",
     "tracks_with_truncated_credit"),
]


def row_value(label: str) -> str:
    """The first grouped number on the README table row with this label."""
    for line in README.splitlines():
        if line.startswith("|") and label in line:
            cell = line.split("|")[2]
            match = re.search(r"\d[\d,]*", cell)
            if match:
                return match.group(0)
    raise AssertionError(f"no README table row labelled {label!r}")


@pytest.mark.parametrize("label,key", TABLE_ROWS)
def test_readme_results_table_matches_the_census(label, key, census):
    assert row_value(label) == grouped(census[key]), (
        f"README row {label!r} disagrees with the measured census "
        f"({census[key]:,}). Run `make census` and update the table.")


def test_readme_headline_matches_the_census(census):
    head = README.split("## Contents", 1)[0]
    assert f"{census['tracks']:,} tracks from {census['games']} games" \
        in head, "the README headline does not state the measured size"
    assert grouped(census["events"]) in head
    assert census["release"] in head, (
        "the headline does not name the release its figures come from")


def test_readme_names_the_measured_release(census):
    assert census["release"] == "snesmdb-50game-rc1"
    assert census["release"] in README


def test_readme_event_row_reconciles(census):
    """events = attacks + legato steps, in the prose as in the data."""
    row = next(line for line in README.splitlines()
               if line.startswith("| events |"))
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", row)]
    assert numbers[0] == census["events"]
    assert numbers[1] == census["attacks"]
    assert numbers[2] == census["legato_steps"]
    assert numbers[1] + numbers[2] == numbers[0], (
        "the README's own event arithmetic does not add up")


def test_readme_split_row_matches_the_census(census):
    row = next(line for line in README.splitlines()
               if line.startswith("| splits "))
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", row)]
    tracks = [census["splits"][s]["tracks"] for s in
              ("train", "valid", "test")]
    games = [census["splits"][s]["games"] for s in ("train", "valid", "test")]
    assert numbers[:3] == tracks, f"README splits {numbers[:3]} != {tracks}"
    assert numbers[3:6] == games, f"README split games {numbers[3:6]} != {games}"
    assert sum(tracks) == census["tracks"], (
        "the splits do not cover every track")


def test_readme_percentages_match_the_census(census):
    for share, label in (
            (census["pitched_share"], "pitched"),
            (census["identity_coverage"], "identity")):
        pct = f"{100 * share:.2f}%"
        assert pct in README, f"README does not state the measured {label} "\
                              f"share {pct}"


def test_readme_unpitched_share_is_the_complement(census):
    pct = f"{100 * census['unpitched_share']:.2f}%"
    assert pct in README, (
        f"README does not state the measured unpitched share {pct}; a "
        f"rounded complement of the pitched share is not the same number")


# ------------------------------------------------- cross-document agreement

def test_dataset_headline_matches_the_census(census):
    head = DATASET.split("---", 1)[0]
    for key in ("tracks", "games", "attacks"):
        assert grouped(census[key]) in head, (
            f"DATASET.md's opening omits the measured {key}")
    assert census["release"] in head


def test_dataset_populations_table_has_the_current_release(census):
    assert "### Seven statistical populations" in DATASET, (
        "the populations section is missing or renamed")
    section = DATASET.split("### Seven statistical populations", 1)[1][:3000]
    row = next((line for line in section.splitlines()
                if census["release"] in line), None)
    assert row, f"the populations table has no {census['release']} row"
    for key in ("games", "tracks", "attacks"):
        assert grouped(census[key]) in row, (
            f"the populations row omits the measured {key}")


def test_changelog_release_history_names_the_current_release(census):
    assert "## Release history" in CHANGELOG
    history = CHANGELOG.split("## Release history", 1)[1][:4000]
    assert census["release"] in history
    assert "the current corpus" in history, (
        "the release history does not identify which release is current")
    for label in ("snesmdb-40game-rc1", "snesmdb-27game-rc1",
                  "expansion-9-rc1", "expansion-8-rc1"):
        assert label in history, f"release history omits {label}"


def test_no_document_still_presents_a_superseded_release_as_current():
    """The exact failure: a superseded population stated without scope."""
    for name, text in (("README.md", README), ("DATASET.md", DATASET)):
        for stale in ("tracks from 27 games", "tracks from 22 games",
                      "tracks from 40 games"):
            assert stale not in text, f"{name} presents {stale!r} as current"


def test_schema_does_not_pin_the_game_count(census):
    """`game_slug` was documented as 'one of 22' through three expansions."""
    assert "one of 22" not in SCHEMA
    assert "for all 22" not in SCHEMA


def test_schema_documents_the_published_game_family_fields():
    """Both ship in `index.json` and neither was documented."""
    for field in ("release_variant", "game_tag_verbatim"):
        assert field in SCHEMA, f"SCHEMA.md omits the published {field} field"
    assert "Game families" in SCHEMA


def test_readme_key_on_claim_is_measured(census):
    """"Every published sample identity was observed at key-on" is checked.

    The census sums each event table's own
    `attacks_identity_observed_at_key_on` header and compares it against the
    attacks that carry an identity. The README may only make the claim while
    those are equal.
    """
    claim = "Every published sample identity was observed at key-on" in README
    measured = census["all_identities_observed_at_key_on"]
    assert measured, (
        f"only {census['attacks_identity_observed_at_key_on']:,} of "
        f"{census['attacks_with_sample_id']:,} identities were observed at "
        f"key-on; the README's unqualified claim is false")
    assert claim, "the measurement holds but the README no longer states it"


def test_census_agrees_with_the_release_index(census):
    """The census cross-checks itself against the index it read."""
    assert census["index_disagreements"] == {}, (
        f"the census disagrees with the release index: "
        f"{census['index_disagreements']}")


def test_cohort_tracks_partition_the_corpus(census):
    """1,316 + 161 + 362 + 389 = 2,228. The one thing that does add."""
    assert 1316 + 161 + 362 + 389 == census["tracks"]
    assert "1,316 + 161 + 362 + 389 = 2,228" in README + DATASET


# ------------------------------------------------------- stale instructions

def test_readme_clone_command_names_the_real_repository():
    assert "git clone <repo>" not in README, "placeholder clone command"
    assert "git clone https://github.com/uestraven/snesmdb.git" in README


def test_readme_does_not_hardcode_verifier_check_counts():
    """These drift every time an assertion is added, and they did."""
    for stale in ("37 checks", "39 checks", "41 checks"):
        assert stale not in README, (
            f"README hardcodes {stale!r}; describe what the target checks "
            f"and let it print its own count")


def test_readme_says_the_raw_format_is_not_distributed():
    """It documents a build-tree-only format beside shipped ones."""
    section = README.split("### Raw format", 1)[1].split("\n## ", 1)[0]
    assert "not distributed" in section.lower()
    assert "No release contains it" in section


def test_readme_scopes_the_interval_baseline_to_its_own_population():
    """It was run on the 27-game corpus and not recomputed since."""
    assert "27-game population" in README
