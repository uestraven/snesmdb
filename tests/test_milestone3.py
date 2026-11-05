"""Milestone 3: BRR decoding, the sample directory, and pitch estimation."""

from __future__ import annotations

import math

import pytest

from snesmdb import brr, pitch


def _block(shift: int, filter_index: int, nybbles: list[int], *, end=False, loop=False):
    header = (shift << 4) | (filter_index << 2) | (0x01 if end else 0) | (0x02 if loop else 0)
    payload = bytes(
        ((nybbles[i] & 0xF) << 4) | (nybbles[i + 1] & 0xF) for i in range(0, 16, 2)
    )
    return bytes([header]) + payload


# --- BRR arithmetic -------------------------------------------------------


def test_every_decoded_sample_is_even() -> None:
    """A consequence of the hardware's `s = (int16_t)(s * 2)`.

    The S-DSP cannot emit an odd BRR sample. A decoder that saturates at full
    scale instead -- which the sibling project shipped -- sits on a different
    grid and, worse, never wraps where the hardware does.
    """
    p1 = p2 = 0
    for shift in (0, 5, 9, 12):
        for filt in range(4):
            for nybble in range(-8, 8):
                p1, p2 = brr.decode_sample(filt, p1, p2, nybble, shift), p1
                assert p1 % 2 == 0, (filt, shift, nybble, p1)


def test_an_out_of_range_shift_collapses_to_a_rail() -> None:
    """Shifts of 13-15 are invalid; hardware does not treat them as large."""
    for shift in (0xD, 0xE, 0xF):
        assert brr.decode_sample(0, 0, 0, 7, shift) == 0
        assert brr.decode_sample(0, 0, 0, -8, shift) == -0x1000


def test_decoding_stops_at_the_end_flag() -> None:
    aram = bytearray(0x10000)
    data = _block(8, 0, [1] * 16) + _block(8, 0, [2] * 16, end=True) + _block(8, 0, [3] * 16)
    aram[0x1000 : 0x1000 + len(data)] = data
    out = brr.decode(bytes(aram), 0x1000)
    assert out.blocks == 2
    assert len(out.data) == 32
    assert not out.truncated


def test_a_long_sample_is_not_truncated() -> None:
    """A 512-block cap silently cut real samples: Final Fantasy VI has one of
    1,046 blocks, and the truncated decode produced a bogus fundamental that
    landed exactly on the estimator's clamp."""
    aram = bytearray(0x10000)
    blocks = 700
    for i in range(blocks):
        aram[0x100 + i * 9 : 0x100 + (i + 1) * 9] = _block(
            8, 0, [1] * 16, end=(i == blocks - 1)
        )
    out = brr.decode(bytes(aram), 0x100)
    assert out.blocks == blocks, out.blocks
    assert not out.truncated


def test_a_loop_address_that_is_not_block_aligned_is_refused() -> None:
    """The loop length feeds pitch estimation, so a wrong offset is worse than
    none: it would silently imply the wrong period."""
    aram = bytearray(0x10000)
    data = _block(8, 0, [1] * 16) + _block(8, 0, [2] * 16, end=True, loop=True)
    aram[0x1000 : 0x1000 + len(data)] = data
    assert brr.decode(bytes(aram), 0x1000, 0x1000 + 9).loop_offset == 16
    assert brr.decode(bytes(aram), 0x1000, 0x1000 + 4).loop_offset is None
    assert brr.decode(bytes(aram), 0x1000, 0x9000).loop_offset is None


# --- sample directory -----------------------------------------------------


def test_the_directory_is_read_only_for_referenced_samples() -> None:
    """The table is a fixed 256 entries and games fill only what they use, so
    the rest is whatever was in memory."""
    aram = bytearray(0x10000)
    base = 0x1B00
    aram[base + 32 * 4 : base + 32 * 4 + 4] = (0x4D07).to_bytes(2, "little") + (
        0x5028
    ).to_bytes(2, "little")
    entries = brr.read_directory(bytes(aram), 0x1B, {32, 33})
    assert entries[32].start == 0x4D07 and entries[32].loop == 0x5028
    assert entries[32].plausible
    assert not entries[33].plausible  # all-zero leftover


def test_an_entry_whose_loop_precedes_its_start_is_implausible() -> None:
    aram = bytearray(0x10000)
    aram[0x1B00:0x1B04] = (0x5000).to_bytes(2, "little") + (0x4000).to_bytes(2, "little")
    assert not brr.read_directory(bytes(aram), 0x1B, {0})[0].plausible


# --- pitch ----------------------------------------------------------------


def test_pitch_unity_plays_the_sample_at_its_own_frequency() -> None:
    hz, note = pitch.note_for(pitch.PITCH_UNITY, 440.0)
    assert hz == pytest.approx(440.0)
    assert note == pytest.approx(69.0)


def test_pitch_is_a_ratio_so_halving_it_drops_an_octave() -> None:
    hz, note = pitch.note_for(pitch.PITCH_UNITY // 2, 440.0)
    assert hz == pytest.approx(220.0)
    assert note == pytest.approx(57.0)


def test_an_estimate_outside_the_plausible_range_is_refused() -> None:
    """A loop of one sample implies 32 kHz, which is not an instrument."""
    assert pitch.loop_f0(1) is None
    assert pitch.loop_f0(2) is None  # 16 kHz, above F0_MAX_HZ
    assert pitch.loop_f0(100) == pytest.approx(320.0)


def test_a_silent_or_tiny_sample_yields_no_estimate_rather_than_a_number() -> None:
    assert pitch.autocorrelation_f0([0] * 2000) is None
    assert pitch.autocorrelation_f0([1, 2, 3]) is None


def test_a_pure_tone_is_measured_correctly() -> None:
    rate = pitch.DSP_RATE
    hz = 440.0
    samples = [int(10000 * math.sin(2 * math.pi * hz * i / rate)) for i in range(2048)]
    estimate = pitch.autocorrelation_f0(samples)
    assert estimate is not None
    assert abs(pitch.cents(estimate, hz)) < 50, estimate


def test_percussion_is_reported_unpitched_not_given_a_plausible_number() -> None:
    """A confident wrong pitch in a corpus is worse than a missing one."""
    import random

    rng = random.Random(0)
    noise = [rng.randint(-8000, 8000) for _ in range(3000)]
    result = pitch.estimate_f0(0, noise, None)
    assert result.confidence in {"none", "low"}, result.to_dict()


def test_a_one_shot_sample_cannot_be_cross_checked_so_is_only_medium() -> None:
    rate = pitch.DSP_RATE
    samples = [int(9000 * math.sin(2 * math.pi * 500 * i / rate)) for i in range(2048)]
    result = pitch.estimate_f0(0, samples, None)
    assert result.method == "autocorrelation"
    assert result.confidence == "medium"
    assert "no loop length" in result.detail


def test_the_deleted_grid_fit_is_not_reintroduced() -> None:
    """A semitone-grid fit improved apparent accuracy to 0.1-0.4 cents and was
    deleted because a RANDOM coarse f0 fit just as well (0.13-0.29). Driver
    PITCH values are already a semitone ladder among themselves, so the fit
    measured the driver's internal consistency, not the fundamental."""
    assert not hasattr(pitch, "refine_against_semitones")
    assert not hasattr(pitch, "Tuning")
