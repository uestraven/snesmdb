"""Which degeneracy check applies is decided by the record, not the game.

`srcn_not_degenerate` was written for a real defect: voice state was not
seeded from the SPC snapshot, so 10.8% of notes carried the wrong sample.
SRCN was the right thing to measure then, because identity came from the
capture-time directory via the SRCN index.

Under `events.v4` identity comes from the directory entry the DSP committed
for each attack. SRCN determines nothing, and a driver may legitimately hold
every voice on index 0 and rewrite that one entry continuously -- Secret of
Evermore does, putting 20.8% of its notes on SRCN 0 while those 11,587
attacks resolve to 36 distinct identities, every one established.

So the assertion moves to the quantity that identifies a sample. The tests
that matter here are the NEGATIVE ones: the replacement has to still catch
resolution collapsing, or this would be a threshold relaxation wearing a
contract correction's clothes.
"""

from __future__ import annotations

import importlib.util
import sys
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "verify_corpus",
    Path(__file__).resolve().parent.parent / "tools" / "verify_corpus.py",
)
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "src"))
from snesmdb import gamefamily  # noqa: E402


def _write(out_dir: Path, notes_per_track, matched=True):
    """A minimal out-dir: one record per entry in `notes_per_track`."""
    (out_dir / "records").mkdir(parents=True, exist_ok=True)
    lines = []
    for index, notes in enumerate(notes_per_track):
        rel = f"records/t{index}.json"
        (out_dir / rel).write_text(json.dumps(
            {"notes": notes, "legato_steps": []}))
        row = {"track_id": f"t{index}:0", "ok": True, "record_path": rel}
        if matched is not None:
            row["identity"] = {"matched": matched}
        lines.append(json.dumps(row))
    (out_dir / "manifest.jsonl").write_text("\n".join(lines) + "\n")


def _note(note_id, srcn=0, sample_id=...):
    note = {"note_id": note_id, "srcn": srcn, "voice": 0}
    if sample_id is not ...:
        note["sample_id"] = sample_id
    return note


def _run(out_dir: Path):
    report = vc.Report()
    vc.check_records(out_dir, report, limit=60)
    done = {}
    for line in report.passes + report.failures + report.not_applicable:
        for name in ("srcn_not_degenerate",
                     "identity_resolution_not_degenerate",
                     "identity_resolved_at_key_on"):
            if f" {name}:" in line:
                done[name] = ("fail" if line in report.failures else
                              "n/a" if line in report.not_applicable
                              else "ok")
    return done


# ---------------------------------------------------------------------------
# Pre-v4 records: unchanged behaviour, unchanged threshold
# ---------------------------------------------------------------------------

def test_records_without_per_attack_identity_are_still_judged_on_srcn(tmp_path):
    """The 22-game baseline's records carry no `sample_id`, and must keep
    being asserted on SRCN exactly as before."""
    notes = [_note(i, srcn=1 + i % 7) for i in range(200)]
    _write(tmp_path, [notes], matched=None)
    got = _run(tmp_path)
    assert got["srcn_not_degenerate"] == "ok"
    assert got["identity_resolution_not_degenerate"] == "n/a"


def test_the_srcn_pile_up_defect_is_still_caught_on_pre_v4_records(tmp_path):
    """The original defect: unseeded voice state puts everything on SRCN 0."""
    notes = [_note(i, srcn=0) for i in range(200)]
    _write(tmp_path, [notes], matched=None)
    assert _run(tmp_path)["srcn_not_degenerate"] == "fail"


def test_the_srcn_threshold_is_unchanged():
    """No relaxation. 6% is the limit it has always been."""
    assert vc.MAX_SRCN_ZERO_FRACTION == 0.06


# ---------------------------------------------------------------------------
# v4 records: SRCN is not applicable, identity is asserted instead
# ---------------------------------------------------------------------------

def test_srcn_is_not_applicable_once_identity_is_resolved_at_key_on(tmp_path):
    """Evermore's shape: every note on SRCN 0, many distinct identities."""
    notes = [_note(i, srcn=0, sample_id=f"id{i % 40:014d}")
             for i in range(200)]
    _write(tmp_path, [notes])
    got = _run(tmp_path)
    assert got["srcn_not_degenerate"] == "n/a", (
        "SRCN cannot indicate collapse when it does not determine the sample"
    )
    assert got["identity_resolution_not_degenerate"] == "ok"
    assert got["identity_resolved_at_key_on"] == "ok"


def test_total_collapse_onto_one_identity_fails(tmp_path):
    """THE NEGATIVE CASE. If resolution collapsed so every attack resolved to
    the same sample, the replacement must fail -- otherwise moving the
    assertion off SRCN would have removed a check rather than corrected it."""
    notes = [_note(i, srcn=1 + i % 7, sample_id="same" + "0" * 12)
             for i in range(200)]
    _write(tmp_path, [notes])
    got = _run(tmp_path)
    assert got["identity_resolution_not_degenerate"] == "fail"
    assert got["srcn_not_degenerate"] == "n/a", (
        "a healthy SRCN spread must not rescue collapsed identity"
    )


def test_near_total_concentration_fails_even_with_several_identities(tmp_path):
    """95% on one identity, with others present, is still collapse."""
    notes = [_note(i, srcn=1, sample_id="dominant" + "0" * 8)
             for i in range(190)]
    notes += [_note(190 + i, srcn=1, sample_id=f"other{i:011d}")
              for i in range(10)]
    _write(tmp_path, [notes])
    assert _run(tmp_path)["identity_resolution_not_degenerate"] == "fail"


def test_real_driver_concentration_passes(tmp_path):
    """Evermore's measured 30.0% on its most common identity must pass. The
    bound is set clear of real data, not tuned to it."""
    notes = [_note(i, srcn=0, sample_id="common" + "0" * 10)
             for i in range(60)]
    notes += [_note(60 + i, srcn=0, sample_id=f"s{i % 67:015d}")
              for i in range(140)]
    _write(tmp_path, [notes])
    assert _run(tmp_path)["identity_resolution_not_degenerate"] == "ok"


def test_a_track_whose_commits_could_not_be_matched_fails(tmp_path):
    """A failed match falls back to capture-time identities SILENTLY, which
    is the quiet failure this check exists to make loud."""
    notes = [_note(i, srcn=0, sample_id=f"id{i % 40:014d}")
             for i in range(200)]
    _write(tmp_path, [notes], matched=False)
    assert _run(tmp_path)["identity_resolved_at_key_on"] == "fail"


def test_an_unresolved_identity_is_not_counted_as_a_distinct_sample(tmp_path):
    """`sample_id: null` means no identity was established. Counting nulls
    toward diversity would let a wholly unresolved track pass."""
    notes = [_note(i, srcn=0, sample_id=None) for i in range(200)]
    _write(tmp_path, [notes])
    assert _run(tmp_path)["identity_resolution_not_degenerate"] == "fail"


# ---------------------------------------------------------------------------
# A MIXED cohort: both populations judged, neither skipped
# ---------------------------------------------------------------------------

def test_a_mixed_cohort_asserts_both_populations(tmp_path):
    """The 27-game release mixes 1,316 pre-v4 records with 161 native ones.

    A single global "are there native identities" flag skipped the SRCN
    check for ALL of them, so the baseline half was judged by neither check:
    SRCN was skipped because some records had identities, and the identity
    check only ever saw the records that did. Each population is measured on
    its own notes.
    """
    pre = [_note(i, srcn=1 + i % 7) for i in range(200)]
    native = [_note(1000 + i, srcn=0, sample_id=f"id{i % 40:014d}")
              for i in range(200)]
    _write(tmp_path, [pre, native], matched=True)
    got = _run(tmp_path)
    assert got["srcn_not_degenerate"] == "ok"
    assert got["identity_resolution_not_degenerate"] == "ok"


def test_a_mixed_cohort_still_catches_srcn_pile_up_in_the_pre_v4_half(tmp_path):
    """The negative case that the global flag hid: a degenerate pre-v4
    record must fail even when native records are present and healthy."""
    pre = [_note(i, srcn=0) for i in range(200)]
    native = [_note(1000 + i, srcn=3, sample_id=f"id{i % 40:014d}")
              for i in range(200)]
    _write(tmp_path, [pre, native], matched=True)
    got = _run(tmp_path)
    assert got["srcn_not_degenerate"] == "fail", (
        "healthy native records must not rescue a degenerate pre-v4 half"
    )
    assert got["identity_resolution_not_degenerate"] == "ok"


def test_a_mixed_cohort_still_catches_identity_collapse_in_the_native_half(
        tmp_path):
    pre = [_note(i, srcn=1 + i % 7) for i in range(200)]
    native = [_note(1000 + i, srcn=2, sample_id="same" + "0" * 12)
              for i in range(200)]
    _write(tmp_path, [pre, native], matched=True)
    got = _run(tmp_path)
    assert got["srcn_not_degenerate"] == "ok"
    assert got["identity_resolution_not_degenerate"] == "fail"


# ---------------------------------------------------------------------------
# Game families are one unit for split assignment
# ---------------------------------------------------------------------------

def test_a_game_family_resolves_to_one_slug_and_records_its_variant():
    """Regional releases of one game must publish under one slug, and must
    still say which release each track came from -- grouping that erased
    provenance would trade one defect for another."""
    from snesmdb import gamefamily

    slug, name, variant = gamefamily.resolve("pdp", "Panel de Pon")
    assert slug == "ta"
    assert name == "Tetris Attack"
    assert variant == "Panel de Pon (JP)"
    assert gamefamily.is_grouped("pdp")


def test_an_ungrouped_slug_keeps_its_own_identity():
    """Every other game in the corpus must be untouched by the family map."""
    from snesmdb import gamefamily

    slug, name, variant = gamefamily.resolve("ct", "Chrono Trigger")
    assert (slug, name, variant) == ("ct", "Chrono Trigger", None)
    assert not gamefamily.is_grouped("ct")


def test_the_family_map_stays_small():
    """The map asserts that two slugs are the SAME WORK. It is not a place
    to normalise spelling or merge games that merely resemble each other, so
    growth should require justifying each entry."""
    from snesmdb import gamefamily

    assert len(gamefamily.MEMBERS) <= 2, (
        f"family map has grown to {sorted(gamefamily.MEMBERS)}; each entry "
        f"claims two slugs are regional releases of one game"
    )
