"""The documentation's factual claims, checked against the code and corpus.

Every defect this file guards against actually shipped, and all of them are
the same shape: a number or a rate written into prose, correct when typed, and
never revisited. A reviewer found three in the README at the frozen
`gate5-rc1` commit -- a stale test count, a stale verification-check count, and
an inert field described as though it were a live one -- and a fourth that was
worse than all three: the uniform score documented as **60.0988 Hz, "the
NES-MDB row rate"**, which is neither. It is the NTSC *video* frame rate, it
means nothing on SNES hardware, NES-MDB's scores are 24 Hz, and this corpus
publishes 100 Hz. A researcher following that sentence would have mistimed
every uniform row by 66%.

Correcting prose by hand is what produced the defect. These tests make the
claims fail loudly instead, so the documentation cannot drift from the
artifact without the suite saying so.
"""

from __future__ import annotations

import re
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import corpus, events, sampleid, scores  # noqa: E402

README = (ROOT / "README.md").read_text()
SCHEMA_DOC = (ROOT / "docs" / "SCHEMA.md").read_text()
DATASET = (ROOT / "docs" / "DATASET.md").read_text()
CHANGELOG = (ROOT / "docs" / "CHANGELOG.md").read_text()


def test_the_readme_test_count_is_the_real_test_count(request):
    """A count in prose drifts every time a test is added, so it is checked
    against what this session actually collected.

    Only meaningful on a full run: selecting one file or using `-k` collects a
    subset, and asserting against that would make the test fail during the
    ordinary edit-and-run-one-file loop. Skipped rather than relaxed, because
    a loose bound on a count is no check at all.
    """
    selected = any(
        ".py" in str(arg) or "::" in str(arg) for arg in request.config.args
    ) or request.config.option.keyword
    if selected:
        pytest.skip("partial selection; the count is checked on a full run")
    collected = len(request.session.items)
    claimed = re.search(r"# (\d+) tests, no skips", README)
    assert claimed, "the README no longer states a test count"
    assert int(claimed.group(1)) == collected, (
        f"README claims {claimed.group(1)} tests; this run collected "
        f"{collected}. Update the README."
    )


def test_the_documented_uniform_rate_is_the_implemented_one():
    """The defect that mattered most: both documents described a rate the
    corpus does not use, in a passage telling researchers to rely on it.

    The first version of this test checked only that "100" appeared somewhere
    in DATASET.md, which is true of almost any document and missed a whole
    stale section -- a comparison table of 60.0988 Hz figures in the file that
    ships inside `dist`. So this now checks the row-duration claim, which is
    specific to the rate and cannot be satisfied by coincidence.
    """
    rate = scores.UNIFORM_HZ
    assert rate == 100.0
    period_ms = 1000.0 / rate
    for name, text in (("README.md", README), ("DATASET.md", DATASET)):
        assert f"{rate:g} Hz" in text, f"{name} omits the uniform rate"
        assert f"{period_ms:.2f} ms" in text or f"{period_ms:g} ms" in text, (
            f"{name} does not state the {period_ms:g} ms row duration"
        )


def test_no_document_attaches_a_stale_rate_to_the_uniform_grid():
    """The exact shape of the shipped defect: a figure that is true of the NES
    stated as a property of this corpus's uniform score."""
    stale = ("60.0988", "16.639", "16.64")
    for name, text in (("README.md", README), ("DATASET.md", DATASET)):
        for line in text.splitlines():
            if not any(token in line for token in stale):
                continue
            lowered = line.lower()
            assert "uniform" not in lowered, (
                f"{name}: a stale rate is attached to the uniform grid: "
                f"{line!r}"
            )
            assert "nes" in lowered or "video" in lowered, (
                f"{name}: stale rate stated without naming it an NES video "
                f"rate: {line!r}"
            )


def test_no_document_calls_any_rate_the_nes_mdb_row_rate():
    """NES-MDB's scores are 24 Hz. 60.0988 Hz is an NTSC video frame rate and
    has no meaning on the SPC700, which runs off its own 1.024 MHz clock. The
    phrase is banned rather than corrected, because it was wrong in a way that
    reads as authoritative."""
    for name, text in (
        ("README.md", README), ("DATASET.md", DATASET),
        ("CHANGELOG.md", CHANGELOG),
    ):
        assert "NES-MDB row rate" not in text, (
            f"{name} resurrects the NES-MDB row-rate claim"
        )


def test_60_0988_hz_appears_only_as_an_nes_video_rate():
    """It is a true fact about the NES and a false one about this corpus, so
    it may appear only where it is described as the NES's video frame rate."""
    for line in README.splitlines():
        if "60.0988" not in line:
            continue
        lowered = line.lower()
        assert "video" in lowered or "nes" in lowered, (
            f"60.0988 Hz used without naming it an NES video rate: {line!r}"
        )
        assert "uniform" not in lowered, (
            f"60.0988 Hz still attached to the uniform score: {line!r}"
        )


def test_the_schema_versions_in_the_docs_match_the_code():
    for version in (
        corpus.INDEX_SCHEMA, corpus.INTAKE_SCHEMA,
        events.SCHEMA, sampleid.SCHEMA,
    ):
        assert version in CHANGELOG, f"{version} undocumented in CHANGELOG"


def test_the_inert_timbre_field_is_described_as_inert_and_located():
    """It is still present in the score and intake trees and absent from
    events.v1. Describing it as simply "published" or simply "removed" would
    both be wrong, and a researcher joining on it needs to know which."""
    assert "timbre_class" in README
    assert "-1" in README
    # The README must say where it does and does not appear.
    assert "events/*.json.gz" in README
    assert "absent" in README.lower()
    # And no event FIELD may carry it. Checked against a built table rather
    # than the module text, which legitimately discusses the field as one of
    # the defects this schema exists to fix.
    table = events.build(
        track_id="x:1", ok=True, duration_sec=1.0,
        notes=[{
            "note_id": 0, "voice": 0, "srcn": 0, "start_sec": 0.0,
            "end_sec": 0.5, "midi_note": 60.0, "pitch_confidence": "high",
        }],
        sample_ids={0: "abc"},
    )
    keys = set(table) | set(table["events"][0])
    assert not any("timbre" in key for key in keys), sorted(keys)


def test_the_breaking_index_change_names_both_access_patterns():
    assert "json.load(handle)[\"tracks\"]" in CHANGELOG
    assert "BREAKING" in CHANGELOG.upper()


def test_the_documented_quantization_loss_matches_the_measured_one():
    """One lost attack in 1,458,211 pitched events, in Axelay axe-03. Written
    into both documents, so both are checked for the same figures."""
    for name, text in (("DATASET.md", DATASET), ("CHANGELOG.md", CHANGELOG)):
        assert "1,458,211" in text, f"{name} lost the measured denominator"
        assert "axe-03" in text, f"{name} lost the affected track"


#: Paths a reader of the SHIPPED documents can actually open. The research
#: package carries `README.md`, `docs/DATASET.md`, `docs/CHANGELOG.md`,
#: `verify.py` and `dist/`, and nothing else.
SHIPPED_PATHS = frozenset({
    "README.md", "docs/DATASET.md", "docs/CHANGELOG.md", "docs/SCHEMA.md",
    "verify.py", "SCHEMA.md", "CHANGELOG.md", "DATASET.md",
})


def _relative_links(text: str) -> list[str]:
    import re
    found = []
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        found.append(target.split("#")[0])
    return [t for t in found if t]


def test_no_shipped_document_links_to_something_that_is_not_shipped():
    """The defect class an evaluator reported three instances of at once.

    `DATASET.md` described `records/*.json` and `raw/*.jsonl.gz` as "preserved
    and published" when neither is distributed, pointed at
    `examples/workflows.py`, and cited the build log as the authoritative
    defect list while that log was deliberately withheld. A document that
    ships inside a corpus must not point at files a download does not
    contain: the reader cannot tell a missing file from a missing feature.
    """
    for name, text in (
        ("README.md", README), ("DATASET.md", DATASET),
        ("CHANGELOG.md", CHANGELOG),
    ):
        for target in _relative_links(text):
            assert target in SHIPPED_PATHS, (
                f"{name} links to {target!r}, which is not part of a "
                f"distribution. Describe it as repository-only instead of "
                f"linking to it."
            )


def test_dataset_md_states_that_records_and_raw_are_not_distributed():
    """The `records/`/`raw/` defect, checked positively.

    A first version of this test sniffed prose -- flagging any line naming a
    withheld tree near the word "published" -- and failed on the CHANGELOG's
    own correction, which quotes the wrong claim in order to retract it. A
    heuristic that cannot tell a claim from its retraction is not a test. So
    this asserts the FIX is present instead: the document must say plainly
    that these two trees are not in the distribution, and must point
    microtiming work at the format that is.
    """
    section = DATASET[DATASET.index("For microtiming"):][:3000]
    assert "Not in this distribution" in section
    assert "records/" in section and "raw/" in section
    assert "events/*.json.gz" in section
    # And the axe-03 example must not send the reader to the same two trees.
    example = DATASET[DATASET.index("Known quantisation limitation"):][:2500]
    assert "events/axe-03" in example
