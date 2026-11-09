"""Reconciling DSP sample-start commits with extracted attacks, by origin."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import eventmatch as em


@dataclass
class N:
    voice: int
    start: int


def C(voice, t):
    return {"voice": voice, "t": t, "dir_addr": 256, "start": 1, "loop": 1}


def test_a_zero_kon_snapshot_excludes_nothing():
    """Nothing is pending, so every commit is a playback attack."""
    r = em.match([N(0, 100)], [C(0, 110)], kon_byte=0x00)
    assert r.ok and len(r.pairs) == 1 and not r.excluded_startup


def test_a_partial_bitmap_excludes_only_its_own_voices():
    """`$01` must exclude one commit on voice 0 and leave voice 1 alone --
    the Donkey Kong Country 2 case, where "drop the first commit per voice"
    would have discarded eight events instead of one."""
    r = em.match(
        [N(0, 100), N(1, 100)],
        [C(0, 5), C(0, 110), C(1, 110)],
        kon_byte=0x01, kon_writes=[(90, 0x01)],
    )
    assert r.ok, r.problems
    assert len(r.excluded_startup) == 1
    assert r.excluded_startup[0]["t"] == 5
    assert len(r.pairs) == 2


def test_all_eight_bits_set_excludes_one_per_voice():
    """The Secret of Evermore case: `$FF`."""
    notes = [N(v, 100) for v in range(8)]
    commits = [C(v, 5) for v in range(8)] + [C(v, 110) for v in range(8)]
    r = em.match(notes, commits, kon_byte=0xFF, kon_writes=[(90, 0xFF)])
    assert r.ok, r.problems
    assert len(r.excluded_startup) == 8 and len(r.pairs) == 8


def test_an_early_write_for_this_voice_accounts_for_the_first_commit():
    """A write to $4C assigns `m.new_kon`, which the DSP latches afterwards,
    so a write before the first commit REPLACES the snapshot's pending
    request. The question is therefore causal -- does an observed key-on for
    THIS voice account for this commit -- and when one does, the commit is a
    real attack that must be matched rather than discarded as startup.

    An earlier version refused outright whenever any write preceded the first
    commit. That fired on three baseline tracks whose drivers write KON at
    t=5, inside the first DSP frame, and withheld a verdict on tracks that
    are in fact decidable. Here the write at t=5 carries voice 0's bit, so
    nothing is excluded and the surplus commit surfaces as an arity mismatch
    -- still a refusal to guess, just a better-localised one."""
    r = em.match(
        [N(0, 10)], [C(0, 20), C(0, 200)],
        kon_byte=0x01, kon_writes=[(5, 0x01)],
    )
    assert not r.ok
    assert not r.excluded_startup
    assert "1 extracted attacks against 2 commits" in r.problems[0]


def test_an_early_write_for_another_voice_does_not_account_for_it():
    """The converse, so the causal rule is not merely "any write suppresses
    exclusion": a write setting only voice 1's bit says nothing about voice
    0's pending snapshot request, which is still a startup event."""
    r = em.match(
        [N(0, 100)], [C(0, 5), C(0, 110)],
        kon_byte=0x01, kon_writes=[(5, 0x02)],
    )
    assert r.ok, r.problems
    assert len(r.excluded_startup) == 1
    assert r.excluded_startup[0]["t"] == 5
    assert len(r.pairs) == 1


def test_a_surplus_commit_fails_rather_than_shifting():
    r = em.match([N(0, 100)], [C(0, 110), C(0, 200)], kon_byte=0x00)
    assert not r.ok and "against 2 commits" in r.problems[0]


def test_a_missing_commit_fails():
    r = em.match([N(0, 100), N(0, 200)], [C(0, 110)], kon_byte=0x00)
    assert not r.ok


def test_a_pending_bit_with_no_commit_fails():
    r = em.match([], [], kon_byte=0x01)
    assert not r.ok and "no commit was observed" in r.problems[0]


def test_a_commit_preceding_its_attack_fails():
    """Beyond the one-frame tolerance for chunk-base timestamps."""
    r = em.match([N(0, 10_000)], [C(0, 100)], kon_byte=0x00)
    assert not r.ok and "precedes its attack" in r.problems[0]


def test_the_one_frame_tolerance_is_allowed():
    r = em.match([N(0, 120)], [C(0, 100)], kon_byte=0x00)
    assert r.ok, r.problems


def test_startup_voices_reads_the_bitmap():
    assert em.startup_voices(0x43) == {0, 1, 6}
    assert em.startup_voices(0xFF) == set(range(8))
    assert em.startup_voices(0x00) == set()
