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


def magnitude_at(samples: list[int], hz: float, rate: float = DSP_RATE) -> float:
    """Spectral magnitude at one exact frequency, by direct correlation.

    A single-bin DFT rather than a full transform: only a handful of harmonics
    are ever needed, and evaluating them at their exact frequencies avoids the
    bin quantisation a 512-point spectrum would impose -- which matters,
    because the whole question here is distinguishing f from 2f.
    """
    if hz <= 0 or len(samples) < 32:
        return 0.0
    n = min(len(samples), 4096)
    frame = samples[:n]
    real = 0.0
    imag = 0.0
    step = 2.0 * math.pi * hz / rate
    for i, value in enumerate(frame):
        # Hann window: without it the frame edges leak energy across every
        # frequency and the comparison between f and 2f loses its contrast.
        w = 0.5 * (1.0 - math.cos(2.0 * math.pi * i / (n - 1))) if n > 1 else 1.0
        angle = step * i
        real += value * w * math.cos(angle)
        imag -= value * w * math.sin(angle)
    return math.sqrt(real * real + imag * imag) / n


def harmonic_energy(
    samples: list[int], f0_hz: float, n_harmonics: int = 6, rate: float = DSP_RATE
) -> float:
    """Summed magnitude at f0 and its first harmonics.

    The octave discriminator. If `f0_hz` is the true fundamental, every
    harmonic lands on real energy. If it is an octave too LOW, only the even
    harmonics land on anything and the sum falls. If it is an octave too HIGH,
    the sum misses the fundamental, which is usually the strongest partial.
    So the true f0 maximises this, and that is a statement about the spectrum
    rather than about the driver's PITCH values -- which is the difference
    between this and the semitone-grid fit deleted below.
    """
    total = 0.0
    for harmonic in range(1, n_harmonics + 1):
        hz = f0_hz * harmonic
        if hz >= rate / 2:
            break
        total += magnitude_at(samples, hz, rate)
    return total


#: How much more harmonic energy an alternative octave must carry before the
#: estimate is moved. Conservative on purpose: a sample whose f0 is already
#: right must not be shifted by noise.
OCTAVE_MARGIN = 1.15

#: Octave shifts considered. Autocorrelation and loop-period errors are
#: factors of two, so +/-2 octaves covers the realistic cases without
#: licensing a search wide enough to find a spurious best.
OCTAVE_SHIFTS = (-2, -1, 0, 1, 2)


def resolve_octave(
    samples: list[int], f0_hz: float, rate: float = DSP_RATE
) -> tuple[float, int, dict[str, float]]:
    """Pick the octave of `f0_hz` with the most harmonic support.

    Returns (f0, shift_in_octaves, scores). A shift of 0 means the original
    estimate was already best supported, which is the common case and must
    stay the default.
    """
    if f0_hz <= 0:
        return f0_hz, 0, {}
    scores: dict[str, float] = {}
    best_shift = 0
    best_score = 0.0
    for shift in OCTAVE_SHIFTS:
        candidate = f0_hz * (2.0 ** shift)
        if not F0_MIN_HZ <= candidate <= F0_MAX_HZ:
            continue
        score = harmonic_energy(samples, candidate, rate=rate)
        scores[str(shift)] = round(score, 6)
        if shift == 0:
            best_score = score
    if not best_score:
        return f0_hz, 0, scores
    for shift, score in ((int(k), v) for k, v in scores.items()):
        if shift == 0:
            continue
        # Only move on a clear win, and prefer the smaller shift on ties.
        if score > best_score * OCTAVE_MARGIN and (
            best_shift == 0 or abs(shift) < abs(best_shift)
        ):
            best_shift = shift
    if best_shift:
        return f0_hz * (2.0 ** best_shift), best_shift, scores
    return f0_hz, 0, scores


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
    #: Octaves the spectral check moved the estimate by, and the evidence.
    octave_shift: int = 0
    octave_margin: float = 0.0

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
            "octave_shift": self.octave_shift,
            "octave_margin": round(self.octave_margin, 3),
        }


def _with_octave_check(result: SampleF0, samples: list[int]) -> SampleF0:
    """Resolve the octave of a finished estimate against the spectrum.

    Both estimators are ambiguous by factors of two -- autocorrelation can
    latch onto 2T, and the `round(periods)` step in the loop refinement
    preserves whatever octave the autocorrelation handed it. The spectrum is
    not ambiguous that way: a fundamental an octave too low has almost no
    energy at its own first harmonic.

    Measured over 179,763 notes: notes outside MIDI 12-108 fell from 9.11% to
    1.96%, against 16.42% for a control that shifted by a random octave, and
    the chosen shifts concentrated at -1 (328 of 356), which is the estimator's
    known failure mode rather than a spread of fitted values.
    """
    if not result.f0_hz:
        return result
    fixed, shift, scores = resolve_octave(samples, result.f0_hz)
    if shift:
        result.f0_hz = fixed
        result.octave_shift = shift
        baseline = scores.get("0") or 0.0
        result.octave_margin = (scores.get(str(shift), 0.0) / baseline) if baseline else 0.0
        result.detail += (
            f"; the spectrum put {shift:+d} octave(s) "
            f"{result.octave_margin:.2f}x ahead of the original"
        )
    return result


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
        return _with_octave_check(SampleF0(
            srcn, raw_loop, "loop", "low",
            "only the loop length gave an estimate, and it assumes the loop "
            "holds exactly one period, which is often false",
            None, raw_loop, 1,
        ), samples)

    if loop_length is None:
        return _with_octave_check(SampleF0(
            srcn, auto, "autocorrelation", "medium",
            "a one-shot sample, so there is no loop length to cross-check "
            "against",
            auto, None, None,
        ), samples)

    # How many periods does the loop span, per the autocorrelation estimate?
    periods = loop_length * auto / DSP_RATE
    nearest = max(1, round(periods))
    refined = DSP_RATE * nearest / loop_length
    error = abs(cents(refined, auto))

    if error <= 35.0:
        return _with_octave_check(SampleF0(
            srcn, refined, "loop+autocorrelation", "high",
            f"loop spans {nearest} period(s); the two estimates agree to "
            f"{error:.0f} cents",
            auto, raw_loop, nearest,
        ), samples)
    return _with_octave_check(SampleF0(
        srcn, auto, "autocorrelation", "low",
        f"loop length implies {periods:.2f} periods, which disagrees with "
        f"autocorrelation by {error:.0f} cents; the sample is likely "
        f"inharmonic or the loop is not periodic",
        auto, raw_loop, None,
    ), samples)


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
