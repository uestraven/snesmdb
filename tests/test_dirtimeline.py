"""Resolving the sample directory at key-on time.

Every case here is one the Evermore investigation showed to be real or that
the four-outcome classification must keep apart. The defect being fixed was
not a missing identity but a SILENT one: 28,203 note attacks across 42 tracks
resolved to nothing and were published as "probably percussive or noise".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import dirtimeline as dt


def _table(entries: dict[int, tuple[int, int]], fill: int = 0xFF) -> bytes:
    """A 1,024-byte directory, unwritten slots filled as memory would be."""
    data = bytearray([fill]) * dt.TABLE_BYTES
    for srcn, (start, loop) in entries.items():
        off = srcn * 4
        data[off:off + 4] = bytes(
            [start & 0xFF, start >> 8, loop & 0xFF, loop >> 8]
        )
    return bytes(data)


def _ident(start, loop):
    """A stand-in canonical identity: audio keyed by address."""
    return None if start in (0, 0xFFFF) else f"audio@{start:04X}"


# ---------------------------------------------------------------------------
# The timeline
# ---------------------------------------------------------------------------

def test_the_table_covers_the_whole_srcn_range():
    """1,024 bytes, not 256. The corpus reaches SRCN 73 -- 18 tracks in
    Donkey Kong Country 2 and Kirby Super Star exceed 63 -- so a 256-byte
    snapshot would silently lose their entries while appearing to work on
    every game tested before them."""
    assert dt.TABLE_BYTES == 1024
    state = dt.DirectoryState(0, 2, _table({73: (0x4000, 0x4000)}))
    assert state.entry(73) == (0x4000, 0x4000)
    assert state.entry(255) == (0xFFFF, 0xFFFF)
    assert state.entry(256) is None


def test_a_short_snapshot_reports_absence_rather_than_guessing():
    state = dt.DirectoryState(0, 2, _table({0: (0x1000, 0x1000)})[:256])
    assert state.entry(0) == (0x1000, 0x1000)
    assert state.entry(64) is None, "beyond the snapshot must be None, not 0"


def test_the_effective_state_is_the_latest_at_or_before_the_key_on():
    tl = dt.Timeline()
    tl.add(0, 2, _table({}))
    tl.add(1000, 2, _table({0: (0x6791, 0x6791)}))
    tl.add(5000, 2, _table({0: (0x8570, 0x8570)}))
    assert tl.at(500).entry(0) == (0xFFFF, 0xFFFF)
    assert tl.at(1000).entry(0) == (0x6791, 0x6791)   # same tick: in effect
    assert tl.at(4999).entry(0) == (0x6791, 0x6791)
    assert tl.at(999999).entry(0) == (0x8570, 0x8570)


def test_a_key_on_before_any_change_uses_the_first_state():
    tl = dt.Timeline()
    tl.add(9000, 2, _table({0: (0x6791, 0x6791)}))
    assert tl.at(5).entry(0) == (0x6791, 0x6791)


def test_records_out_of_order_are_sorted():
    tl = dt.Timeline()
    tl.add(5000, 2, _table({0: (0x8570, 0x8570)}))
    tl.add(1000, 2, _table({0: (0x6791, 0x6791)}))
    assert tl.at(2000).entry(0) == (0x6791, 0x6791)


def test_a_moving_DIR_page_is_carried_with_the_state():
    """The page is logged per state, so a driver that repoints DIR mid-track
    is handled even though no corpus game observed so far does."""
    tl = dt.Timeline()
    tl.add(0, 0x02, _table({0: (0x1000, 0x1000)}))
    tl.add(100, 0x40, _table({0: (0x9000, 0x9000)}))
    assert tl.at(50).page == 0x02
    assert tl.at(150).page == 0x40
    assert tl.at(150).entry(0) == (0x9000, 0x9000)


def test_read_log_ignores_non_directory_records_and_bad_hex():
    tl = dt.read_log([
        {"t": 10, "addr": 76, "reg": "KON", "data": 1},
        {"t": 20, "kind": "dir", "page": 2, "bytes": _table({0: (0x30, 0x30)}).hex()},
        {"t": 30, "kind": "dir", "page": 2, "bytes": "not hex"},
    ])
    assert len(tl.states) == 1
    assert tl.at(25).entry(0) == (0x30, 0x30)


# ---------------------------------------------------------------------------
# The four outcomes
# ---------------------------------------------------------------------------

def test_directory_population_is_newly_resolved():
    """Evermore's defect: nothing at t=0, real audio at key-on."""
    out, ident = dt.classify((0xFFFF, 0xFFFF), (0x6791, 0x6791), _ident)
    assert out == dt.NEWLY_RESOLVED and ident == "audio@6791"


def test_entry_replacement_with_different_audio_is_identity_corrected():
    """The case a missing-only model hides: the baseline may hold WRONG
    non-null sample ids, not merely absent ones."""
    out, ident = dt.classify((0x1000, 0x1000), (0x6791, 0x6791), _ident)
    assert out == dt.IDENTITY_CORRECTED and ident == "audio@6791"


def test_a_changed_address_with_identical_audio_is_unchanged():
    """Compared on canonical identity, not address. Two addresses can hold
    the same decoded audio and loop point, and calling that a correction
    would overstate the fix."""
    same = lambda start, loop: "one-sound"
    out, ident = dt.classify((0x1000, 0x1000), (0x6791, 0x6791), same)
    assert out == dt.UNCHANGED and ident == "one-sound"


def test_an_unchanged_entry_is_unchanged():
    out, _ = dt.classify((0x6791, 0x6791), (0x6791, 0x6791), _ident)
    assert out == dt.UNCHANGED


def test_still_unwritten_at_key_on_is_unresolved():
    """Evermore's `soe-05` keeps 4 of 8 slots unwritten after 30 s, so
    recovery is partial and must not be reported as complete."""
    out, ident = dt.classify((0xFFFF, 0xFFFF), (0xFFFF, 0xFFFF), _ident)
    assert out == dt.UNRESOLVED and ident is None


def test_an_entry_that_becomes_invalid_is_unresolved_not_corrected():
    out, ident = dt.classify((0x6791, 0x6791), (0, 0), _ident)
    assert out == dt.UNRESOLVED and ident is None


def test_an_undecodable_block_is_unresolved_even_with_a_valid_entry():
    """A plausible address whose BRR will not decode is a different failure
    from an unwritten entry, and both end as unresolved rather than as a
    confident identity."""
    out, _ = dt.classify((0x1000, 0x1000), (0x2000, 0x2000), lambda s, l: None)
    assert out == dt.UNRESOLVED


def test_plausibility_rejects_the_memory_fill_and_degenerate_entries():
    assert dt.plausible((0x6791, 0x6791))
    assert not dt.plausible((0xFFFF, 0xFFFF))   # unwritten memory
    assert not dt.plausible((0, 0))             # no sample
    assert not dt.plausible((0x2000, 0x1000))   # loop before start
    assert not dt.plausible(None)


# ---------------------------------------------------------------------------
# Same-tick / same-chunk ordering: measured, not assumed
# ---------------------------------------------------------------------------

def test_a_stable_entry_is_never_ambiguous_even_across_a_change():
    """The ordering question only matters for the SRCN that changed.

    A snapshot boundary carrying a change to SRCN 3 says nothing about a
    key-on on SRCN 0 whose entry is identical either side, so resolution
    there is exact regardless of execution order.
    """
    tl = dt.Timeline()
    tl.add(0, 2, _table({0: (0x6791, 0x6791)}))
    tl.add(65536, 2, _table({0: (0x6791, 0x6791), 3: (0x7B29, 0x7B29)}))
    assert not tl.ambiguous(30000, srcn=0)
    assert tl.ambiguous(30000, srcn=3)


def test_a_key_on_inside_a_changing_window_is_reported_ambiguous():
    """An earlier version assumed the change preceded the key-on, justified by
    the snapshot being taken after the chunk rendered. That does not follow: a
    chunk-boundary snapshot cannot order a key-on against a CPU write inside
    the same chunk. The case is now reported instead."""
    tl = dt.Timeline()
    tl.add(0, 2, _table({}))
    tl.add(65536, 2, _table({0: (0x6791, 0x6791)}))
    assert tl.ambiguous(40000, srcn=0)


def test_a_key_on_after_the_last_change_is_unambiguous():
    tl = dt.Timeline()
    tl.add(0, 2, _table({}))
    tl.add(65536, 2, _table({0: (0x6791, 0x6791)}))
    assert not tl.ambiguous(999999, srcn=0)


def test_ambiguity_is_not_raised_before_any_observed_change():
    tl = dt.Timeline()
    tl.add(0, 2, _table({0: (0x6791, 0x6791)}))
    assert not tl.ambiguous(10, srcn=0)


def test_ambiguous_is_a_distinct_reported_outcome():
    assert dt.AMBIGUOUS in dt.OUTCOMES
    assert dt.AMBIGUOUS != dt.UNRESOLVED
