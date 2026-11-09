"""Guards for two defects that silently corrupted published research figures.

Neither crashed, neither failed a verifier, and both produced plausible
numbers that were reported as measurements. They are the reason the
Super Turrican cross-tab disagreed with the exposure study by exactly 4,211
attacks, and the reason "10,955 loop-only differences" was wrong by three
orders of magnitude.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import voices  # noqa: E402


# ---------------------------------------------------------------------------
# 1. SRCN comes from the DSP snapshot, not from zero
# ---------------------------------------------------------------------------

def test_seeding_recovers_an_srcn_the_driver_never_rewrites():
    """A voice register the driver never writes reads as whatever the SPC
    snapshot left in it. SRCN is routinely such a register: the driver sets
    it once before the snapshot and the log never mentions it again.

    Omitting the snapshot made every unwritten SRCN read as 0, so 13,025 of
    38,440 Super Turrican attacks resolved against directory entry 0 instead
    of the entry actually selected -- and the resulting identities were
    reported as evidence that the published data was wrong.
    """
    dsp = bytearray(128)
    dsp[0x24] = 7            # voice 2, SRCN
    states = voices.seed_states(bytes(dsp))
    assert states[2].srcn == 7
    assert states[0].srcn == 0, "untouched voices stay at zero"


def test_without_the_snapshot_every_srcn_is_indistinguishable_from_zero():
    """The failure mode is silent: zero is a VALID SRCN, so nothing
    downstream can tell a seeded 0 from a defaulted one."""
    assert all(s.srcn == 0 for s in voices.seed_states(None))


def test_extract_carries_the_seeded_srcn_onto_an_attack():
    """End to end: a key-on with no preceding SRCN write must still report
    the snapshot's SRCN."""
    dsp = bytearray(128)
    dsp[0x04] = 11           # voice 0, SRCN
    writes = [
        {"t": 100, "addr": 0x4C, "reg": "KON", "data": 0x01},
        {"t": 500, "addr": 0x5C, "reg": "KOFF", "data": 0x01},
    ]
    notes = voices.extract(iter(writes), bytes(dsp)).notes
    assert [n.srcn for n in notes] == [11]
    assert [n.srcn for n in voices.extract(iter(writes)).notes] == [0]


# ---------------------------------------------------------------------------
# 2. Content comparison must be lossless
# ---------------------------------------------------------------------------

def _low_byte_prefix(data, limit=4096):
    """The discarded comparison: low byte only, first `limit` samples."""
    return bytes(bytearray((v & 0xFF) for v in data[:limit]))


def _lossless(data):
    return hash(tuple(data))


def test_a_low_byte_comparison_calls_different_waveforms_identical():
    """`v & 0xFF` throws away the high byte of every 16-bit sample, so two
    waveforms a full octave of amplitude apart compare equal. This is what
    reported 8,869 genuine content differences as loop-only differences."""
    quiet = [0x0100, 0x0200, 0x0300]
    loud = [0x7F00, 0x7E00, 0x7D00]
    assert _low_byte_prefix(quiet) == _low_byte_prefix(loud)
    assert _lossless(quiet) != _lossless(loud)


def test_a_truncated_comparison_ignores_everything_past_the_prefix():
    """Samples longer than the prefix differ only after it -- common for
    sustained instruments that share an attack transient."""
    a = [1] * 4096 + [10]
    b = [1] * 4096 + [-10]
    assert _low_byte_prefix(a) == _low_byte_prefix(b)
    assert _lossless(a) != _lossless(b)


def test_the_lossless_comparison_still_calls_equal_waveforms_equal():
    assert _lossless([1, -2, 3]) == _lossless([1, -2, 3])


def test_signed_pcm_cannot_be_coerced_to_bytes():
    """Why the hash is over a tuple and not over `bytes(data)`: PCM is
    SIGNED, and `bytes()` raises on any negative sample. An earlier version
    swallowed that in a bare `except`, which made all 38,440 attacks read as
    content_unresolved."""
    try:
        bytes([-1])
    except ValueError:
        pass
    else:                                        # pragma: no cover
        raise AssertionError("expected bytes() to reject a negative sample")
    assert isinstance(_lossless([-1, -2]), int)


# ---------------------------------------------------------------------------
# 3. A decode cache key must name the memory it decoded
# ---------------------------------------------------------------------------

def test_an_address_pair_does_not_identify_a_sample_across_tracks():
    """The cache defect, as a property: the same (start, loop) addresses hold
    different audio in different tracks, so a cache keyed on addresses alone
    serves one track's decode for another's. The verdict then depends on the
    order tracks happen to be processed in -- it moved 3,762 of 38,440
    attacks between two otherwise identical runs."""
    def decode(aram, start):
        return aram[start]

    aram_a, aram_b = b"\x11\x22", b"\x33\x44"

    shared: dict = {}
    def cached_wrong(aram, start):
        key = start
        if key not in shared:
            shared[key] = decode(aram, start)
        return shared[key]

    scoped: dict = {}
    def cached_right(track, aram, start):
        key = (track, start)
        if key not in scoped:
            scoped[key] = decode(aram, start)
        return scoped[key]

    assert cached_wrong(aram_a, 0) == 0x11
    assert cached_wrong(aram_b, 0) == 0x11, "poisoned: track B got track A"

    assert cached_right("a", aram_a, 0) == 0x11
    assert cached_right("b", aram_b, 0) == 0x33


def test_the_analysis_tools_pass_the_dsp_snapshot_and_scope_their_cache():
    """A source check, because the defect is invisible at runtime: both
    mistakes produce confident wrong numbers rather than errors."""
    tools = [
        "measure_baseline_exposure.py",
        "crosstab_identity_evidence.py",
        "resolve_loop_differences.py",
        "reconcile_identity_reports.py",
        "verify_instrumentation.py",
    ]
    for name in tools:
        text = (ROOT / "tools" / name).read_text()
        assert "voices.extract(iter(writes), spc.dsp)" in text, (
            f"{name} must pass the DSP snapshot to extract()"
        )
        assert "voices.extract(iter(writes))" not in text, (
            f"{name} still has an unseeded extract() call"
        )
        assert "key = (start, loop)" not in text, (
            f"{name} caches decodes on addresses alone, which leaks "
            f"one track's audio into another's verdict"
        )
