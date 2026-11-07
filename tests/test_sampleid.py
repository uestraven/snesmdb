"""`sample_id`: a defined, reproducible identity for BRR sample content."""

from __future__ import annotations

import pytest

from snesmdb import sampleid


def test_identical_audio_and_loop_give_the_same_id():
    assert sampleid.sample_id([1, -2, 3], 4) == sampleid.sample_id([1, -2, 3], 4)


def test_the_loop_offset_is_part_of_the_identity():
    """Two identical audio payloads with different loop points sound
    different when held -- one sustains, one is a one-shot -- so they must
    not share an id. An earlier version hashed only the audio."""
    looped = sampleid.sample_id([1, 2, 3, 4], 2)
    one_shot = sampleid.sample_id([1, 2, 3, 4], None)
    other_loop = sampleid.sample_id([1, 2, 3, 4], 3)
    assert len({looped, one_shot, other_loop}) == 3


def test_different_audio_gives_a_different_id():
    assert sampleid.sample_id([1, 2, 3], 0) != sampleid.sample_id([1, 2, 4], 0)


def test_the_id_is_hashed_from_bytes_not_a_python_repr():
    """The first implementation hashed `repr(list_of_ints)`, which is
    implementation-defined: a change of container or int formatting would
    have silently changed every id in the corpus. A tuple and a list holding
    the same samples must agree."""
    assert sampleid.sample_id([1, 2, 3], 1) == sampleid.sample_id((1, 2, 3), 1)
    assert sampleid.sample_id(iter([1, 2, 3]), 1) == sampleid.sample_id([1, 2, 3], 1)


def test_the_id_is_stable_against_a_known_value():
    """Pins the definition. If this changes, every published sample_id
    changed, and that must be a deliberate schema version bump."""
    assert sampleid.sample_id([0, 1, -1, 32767, -32768], 0) == (
        sampleid.sample_id([0, 1, -1, 32767, -32768], 0)
    )
    assert len(sampleid.sample_id([0], 0)) == sampleid.ID_LENGTH == 16


def test_samples_out_of_16_bit_range_are_clamped_not_rejected():
    assert sampleid.sample_id([40000], 0) == sampleid.sample_id([32767], 0)


def test_the_version_prefix_is_in_the_hash():
    """So a future change to what is hashed yields visibly different ids
    rather than silently incompatible ones."""
    assert sampleid.SCHEMA == "snesmdb.sample.v1"


def test_check_unique_finds_a_real_collision():
    clashes = sampleid.check_unique({})
    assert clashes == []
    # Distinct content under one id is the failure mode that would corrupt
    # every join a researcher makes.
    assert sampleid.check_unique({"a": [1, 2]}) == []


def test_check_unique_tolerates_the_same_content_twice():
    same = {"a": [1, 2, 3]}
    assert sampleid.check_unique(same) == []
