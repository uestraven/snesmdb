"""Recovering absolute pitch.

The PITCH register is a resample RATIO, not a frequency. A voice plays its
sample at `PITCH/4096` times the DSP's own 32 kHz rate, so

    sounding_hz = f0_of_sample * PITCH / 4096

and the missing term is `f0_of_sample`, which lives in the game's private
instrument table and is recorded nowhere in the SPC. So it is recovered from
the sample data itself.

Two independent estimators, deliberately:

1. **Loop length.** A pitched instrument loops over a whole number of periods,
   so `32000 / (loop_length / periods)` is the fundamental. Exact when the
   loop is one period, and cheap.
2. **Autocorrelation** over the looped region.

They are computed separately and compared. Agreement is the confidence
signal; disagreement means the sample is percussive, inharmonic, or looped
over several periods, and the result is reported as low confidence rather than
silently averaged. A plausible wrong pitch in a corpus is worse than a missing
one, which is the same reason `voices.py` leaves noise and pitch-modulated
voices unpitched.

Dependency-free pure Python: a few dozen samples per game, decoded once.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

#: The S-DSP's output rate. A sample plays at this rate when PITCH is 0x1000.
DSP_RATE = 32000.0

#: PITCH value that means "play at the sample's natural rate".
PITCH_UNITY = 0x1000

#: Plausible fundamental range for a pitched instrument sample. Outside this,
#: an estimate is far more likely to be an octave error or noise than a real
#: reading, so it is rejected rather than trusted.
F0_MIN_HZ = 40.0
F0_MAX_HZ = 4000.0


def hz_to_midi(hz: float) -> float:
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def midi_to_hz(note: float) -> float:
    return 440.0 * (2.0 ** ((note - 69.0) / 12.0))


def cents(a: float, b: float) -> float:
    """Interval between two frequencies, in cents."""
    return 1200.0 * math.log2(a / b)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def autocorrelation_f0(samples: list[int], rate: float = DSP_RATE) -> float | None:
    """Fundamental by normalised autocorrelation, or None if unconvincing.

    Searches lags covering F0_MIN_HZ..F0_MAX_HZ and takes the first strong
    local maximum rather than the global one, because the global peak of a
    harmonic signal often sits at a multiple of the true period and reports an
    octave too low.
    """
    n = len(samples)
    if n < 64:
        return None
    mean = _mean([float(s) for s in samples])
    signal = [float(s) - mean for s in samples]
    energy = sum(v * v for v in signal)
    if energy <= 0.0:
        return None

    min_lag = max(2, int(rate / F0_MAX_HZ))
    max_lag = min(n // 2, int(rate / F0_MIN_HZ))
    if max_lag <= min_lag:
        return None

    best_lag = 0
    best_score = 0.0
    scores: list[tuple[int, float]] = []
    for lag in range(min_lag, max_lag):
        acc = 0.0
        for i in range(n - lag):
            acc += signal[i] * signal[i + lag]
        norm = acc / energy
        scores.append((lag, norm))
        if norm > best_score:
            best_score, best_lag = norm, lag

    if best_lag == 0 or best_score < 0.3:
        return None

    # Take the first strong LOCAL MAXIMUM, not the first lag to cross a
    # threshold. On a pure 440 Hz sine the thresholded version returned
    # 477.6 Hz -- 142 cents sharp -- because it stopped on the rising flank of
    # the first peak rather than its apex. The global maximum is no better: for
    # a harmonic signal it often sits at a multiple of the true period and
    # reports an octave or a twelfth too low.
    threshold = 0.85 * best_score
    for index in range(1, len(scores) - 1):
        lag, norm = scores[index]
        if (
            norm >= threshold
            and norm >= scores[index - 1][1]
            and norm >= scores[index + 1][1]
        ):
            # Parabolic interpolation around the apex: the true period is
            # rarely a whole number of samples.
            previous, following = scores[index - 1][1], scores[index + 1][1]
            denominator = previous - 2.0 * norm + following
            offset = 0.0
            if denominator != 0.0:
                offset = max(-0.5, min(0.5, 0.5 * (previous - following) / denominator))
            return rate / (lag + offset)
    return rate / best_lag


def loop_f0(loop_length: int, rate: float = DSP_RATE) -> float | None:
    """Fundamental implied by a loop of `loop_length` samples holding ONE period."""
    if loop_length <= 1:
        return None
    hz = rate / loop_length
    return hz if F0_MIN_HZ <= hz <= F0_MAX_HZ else None


@dataclass
class SampleF0:
    """An estimated fundamental, and how much to trust it."""

    srcn: int
    f0_hz: float | None
    method: str
    confidence: str  # "high", "medium", "low", "none"
    detail: str
    autocorrelation_hz: float | None = None
    loop_hz: float | None = None
    loop_periods: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "srcn": self.srcn,
            "f0_hz": self.f0_hz,
            "method": self.method,
            "confidence": self.confidence,
            "detail": self.detail,
            "autocorrelation_hz": self.autocorrelation_hz,
            "loop_hz": self.loop_hz,
            "loop_periods": self.loop_periods,
        }


def estimate_f0(
    srcn: int, samples: list[int], loop_offset: int | None
) -> SampleF0:
    """Estimate a sample's fundamental, cross-checking two methods.

    The loop estimator assumes the loop spans ONE period, which is often
    false; so rather than trust it alone, the number of periods is derived
    from the autocorrelation result and the loop is used to refine it. When
    the two cannot be reconciled the result is low confidence.
    """
    region = samples[loop_offset:] if loop_offset is not None else samples
    if len(region) < 64:
        region = samples

    auto = autocorrelation_f0(region)
    loop_length = (len(samples) - loop_offset) if loop_offset is not None else None
    raw_loop = loop_f0(loop_length) if loop_length else None

    if auto is None and raw_loop is None:
        return SampleF0(
            srcn, None, "none", "none",
            "neither autocorrelation nor loop length gave a usable "
            "fundamental; the sample is probably percussive or noise",
            None, raw_loop, None,
        )

    if auto is None:
        return SampleF0(
            srcn, raw_loop, "loop", "low",
            "only the loop length gave an estimate, and it assumes the loop "
            "holds exactly one period, which is often false",
            None, raw_loop, 1,
        )

    if loop_length is None:
        return SampleF0(
            srcn, auto, "autocorrelation", "medium",
            "a one-shot sample, so there is no loop length to cross-check "
            "against",
            auto, None, None,
        )

    # How many periods does the loop span, per the autocorrelation estimate?
    periods = loop_length * auto / DSP_RATE
    nearest = max(1, round(periods))
    refined = DSP_RATE * nearest / loop_length
    error = abs(cents(refined, auto))

    if error <= 35.0:
        return SampleF0(
            srcn, refined, "loop+autocorrelation", "high",
            f"loop spans {nearest} period(s); the two estimates agree to "
            f"{error:.0f} cents",
            auto, raw_loop, nearest,
        )
    return SampleF0(
        srcn, auto, "autocorrelation", "low",
        f"loop length implies {periods:.2f} periods, which disagrees with "
        f"autocorrelation by {error:.0f} cents; the sample is likely "
        f"inharmonic or the loop is not periodic",
        auto, raw_loop, None,
    )


def note_for(pitch_register: int, f0_hz: float) -> tuple[float, float]:
    """Sounding frequency and (fractional) MIDI note for a PITCH value."""
    hz = f0_hz * pitch_register / PITCH_UNITY
    return hz, hz_to_midi(hz)


# A semitone-grid refinement was implemented here and DELETED. The idea was
# that since a voice plays equal-tempered notes, the correct f0 is the one
# putting `f0 * PITCH / 4096` on semitones for every note using that sample --
# a one-parameter fit over real data instead of a guess from a short loop. It
# improved the fit from 5-40 cents to 0.1-0.4 cents and looked like a result.
#
# It was not one. A control with a RANDOM coarse f0 fit equally well: 0.13 to
# 0.29 cents. The reason is structural -- a driver computes PITCH as
# `base * 2**(n/12)`, so the PITCH values for one sample are ALREADY a
# semitone ladder among themselves. Any f0 maps that ladder onto a semitone
# grid; only the grid's offset moves. The fit measured the driver's internal
# consistency, which is always present, and said nothing about f0.
#
# Measured consequence, per sample, median deviation from an exact semitone
# ladder: Rare 0.30 cents (96% of samples under 5), Square 0.48 (91%),
# Nintendo N-SPC 2.87 (65%), Konami 3.39 (69%), Capcom 10.67 (19%). So
# RELATIVE pitch within a sample is essentially exact for some drivers and
# unreliable for others, and ABSOLUTE pitch is not recoverable this way at
# all. Do not reintroduce a grid fit as evidence about f0.
