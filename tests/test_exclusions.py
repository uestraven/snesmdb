"""The evaluation-exclusion record, and the properties that keep it honest.

A cross-split duplicate was found: the Capcom startup fanfare is a complete
track in Mega Man X and Breath of Fire 2 (train) and in Street Fighter II
Turbo (valid), matching on absolute pitch at full coverage. The response is
a change to the evaluation protocol, not to the corpus -- the dataset is
immutable and its splits are published.

What these tests protect is the difference between "excluded from a score"
and "removed from the dataset", and the conditionality that stops one
experiment's duplicate from shrinking everyone's evaluation set.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import exclusions  # noqa: E402

CAPCOM_VALID = "sf2t-01:e5fe428a1b8c"
CAPCOM_TRAIN = ("mmx-01:4c67c8f50c56", "bof2-s01:63651d0deeed")


def test_the_shipped_record_loads_and_names_the_confirmed_duplicate():
    record = exclusions.load()
    assert {e.track_id for e in record.exclusions} == {CAPCOM_VALID}
    only = record.exclusions[0]
    assert only.cluster_id == "capcom-startup-fanfare"
    assert set(only.conditional_on) == set(CAPCOM_TRAIN)


def test_the_exclusion_applies_when_a_duplicate_was_trained_on():
    record = exclusions.load()
    for trained in CAPCOM_TRAIN:
        assert record.excluded([trained]) == {CAPCOM_VALID}, (
            f"training on {trained} makes the validation copy a recall test"
        )


def test_the_exclusion_does_not_apply_when_no_duplicate_was_trained_on():
    """The conditionality is the point. An unconditional drop would shrink
    every experiment's evaluation set, including those for which the
    duplication is irrelevant."""
    record = exclusions.load()
    assert record.excluded(["some-other-track:0"]) == set()
    assert record.excluded([]) == set()


def test_an_unconfirmed_candidate_never_excludes_anything():
    """The Lufia 2 / Secret of Mana figure repeats every 8 notes and covers
    7% and 4% of two long tracks. It is recorded for review; treating it as
    leakage would discard valid evaluation data on weak evidence."""
    record = exclusions.load()
    ids = {m["track_id"]
           for c in record.unconfirmed for m in c.get("members", [])}
    assert "ed2-102:0d7928d92091" in ids
    assert record.excluded(list(CAPCOM_TRAIN)) & ids == set()


def test_every_exclusion_can_explain_itself():
    """An exclusion a reader cannot see is indistinguishable from a
    convenient subset."""
    record = exclusions.load()
    rows = record.report(list(CAPCOM_TRAIN))
    assert rows and all(r["rationale"] for r in rows)
    assert all(r["cluster_id"] for r in rows)


def test_the_record_does_not_ask_for_anything_to_be_deleted():
    raw = json.loads(exclusions.DEFAULT_PATH.read_text())
    cluster = raw["duplicate_clusters"][0]
    assert cluster["exclusions"][0]["action"] == "exclude_from_scoring"
    text = json.dumps(raw).lower()
    assert "not a dataset change" in text
    # The members list keeps all three tracks, including the excluded one.
    assert len(cluster["members"]) == 3


def test_matching_is_by_track_id_not_by_title():
    """Two of the three members share the title 'Capcom Logo' and a third
    carries an unrelated title for the same music, so titles identify
    nothing here."""
    raw = json.loads(exclusions.DEFAULT_PATH.read_text())
    titles = [m["title"] for m in raw["duplicate_clusters"][0]["members"]]
    assert titles.count("Capcom Logo") == 2
    assert "La la la..." in titles
    assert "Do not match on game or title" in raw["note"]


def test_the_claim_does_not_assert_composer_disjointness():
    record = exclusions.load()
    claim = record.claim.lower()
    assert "recorded-credit-disjoint" in claim
    assert "not established" in claim
    assert "held-out-game" in claim


def test_the_unresolved_attribution_overlap_is_recorded_without_acting():
    raw = json.loads(exclusions.DEFAULT_PATH.read_text())
    caveat = raw["attribution_caveats"][0]
    assert caveat["affected_tracks_in_train"] == 206
    assert caveat["action"] == "none", (
        "a two-letter prefix must not move 206 tracks between splits"
    )


def test_coverage_limits_refuse_to_claim_absence_of_duplication():
    record = exclusions.load()
    joined = " ".join(record.limits).upper()
    assert "DOES NOT ESTABLISH" in joined


def test_a_wrong_schema_is_rejected(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"schema": "something.else"}))
    try:
        exclusions.load(path)
    except ValueError:
        return
    raise AssertionError("a foreign schema must not load silently")
