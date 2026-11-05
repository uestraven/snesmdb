"""Features of a decoded BRR sample, and a codebook built from them.

Milestone 5, and the one with no ground truth.

`exprsco`'s timbre axis on the NES is a duty index in {0,1,2,3}: a closed,
four-value alphabet that means the same thing in all 397 games. The SNES
equivalent is "BRR sample #N in this game's ARAM" -- an open vocabulary,
arbitrary per game, with no cross-game meaning at all. There is no alphabet to
inherit, so it has to be built, and then the hard part: shown to mean
something.

HOW THIS IS VALIDATED WITHOUT LABELS. Nobody has labelled these samples, and
"strings in Final Fantasy VI and strings in Chrono Trigger are the same class"
cannot be checked against a truth table that does not exist. So the design
splits the evidence in two and never lets the halves touch:

  * the CODEBOOK is built only from features intrinsic to the decoded
    waveform -- length, loop, attack, spectrum. Nothing about how the music
    plays the sample enters it.

  * the CHECK uses only features of how the corpus USES each sample -- the
    register it is played at, how long its notes last, whether it is ever
    pitched at all. The clustering never sees these.

If spectral clusters predict usage, and predict it consistently across games
that share no code and no composer, that is evidence the classes carry meaning
rather than describing one game's sample bank. If they do not, the honest
report is that they do not, and this module makes that outcome visible rather
than burying it. That is the milestone's stated risk and the reason its exit
criterion is a check and not a deliverable.

Pure stdlib: a real DFT by hand rather than a dependency, since the project
ships none and a 512-point transform over a few thousand samples is cheap.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: The S-DSP's sample rate.
DSP_RATE = 32000.0

#: DFT size. A power of two is not required here -- there is no FFT -- but 512
#: bins over 32 kHz gives 62.5 Hz resolution, which separates a bass sample
#: from a cymbal without making the transform the slow part.
DFT_SIZE = 512


@dataclass
class Features:
    """Everything measurable from the decoded waveform alone.

    Deliberately excludes anything about how the sample is PLAYED: no register,
    no note duration, no velocity. Those are the independent check, and a
    feature that appeared in both halves would make the validation circular.
    """

    srcn: int = -1
    n_samples: int = 0
    #: Loop structure, which separates a sustaining instrument from a hit.
    looped: bool = False
    loop_length: int = 0
    loop_fraction: float = 0.0
    #: Amplitude envelope.
    peak: float = 0.0
    rms: float = 0.0
    #: Samples to first reach 90% of peak, as a fraction of length. A struck
    #: or plucked sound rises immediately; a bowed or blown one does not.
    attack_fraction: float = 0.0
    #: Zero crossings per second: a cheap brightness proxy, and robust on the
    #: very short samples where a transform has little to work with.
    zero_crossing_rate: float = 0.0
    #: Spectral shape, in Hz and in normalised units.
    centroid_hz: float = 0.0
    spread_hz: float = 0.0
    rolloff_hz: float = 0.0
    #: Geometric over arithmetic mean of the spectrum: 1 is noise, 0 is a pure
    #: tone. The single most useful axis for telling percussion from pitch.
    flatness: float = 0.0
    #: Energy at integer multiples of the estimated f0 over total energy.
    harmonicity: float = 0.0
    #: Whether an f0 was recoverable at all, from milestone 3.
    pitched: bool = False
    f0_hz: float = 0.0

    def vector(self) -> list[float]:
        """The clustering input, in a fixed order.

        `pitched` and `harmonicity` are measured and reported but deliberately
        EXCLUDED. Both depend on whether an f0 was recoverable, and the usage
        half's `unpitched_fraction` is very nearly the same quantity -- a note
        receives a MIDI number only when its sample's f0 estimate was usable.
        Including them put the answer on both sides of the validation and
        produced a separation ratio of 426 against a null of 0.18, which
        measured the leak rather than the codebook.

        Scaled so no axis dominates by its units: durations in log samples,
        frequencies in log Hz, the rest already in 0..1. Log because the ear
        and the hardware both work multiplicatively -- 100 Hz to 200 Hz is the
        same step as 1 kHz to 2 kHz, and a linear axis would let one cymbal
        outweigh every bass note in the corpus.
        """
        return [
            math.log1p(self.n_samples),
            1.0 if self.looped else 0.0,
            self.loop_fraction,
            self.attack_fraction,
            math.log1p(self.zero_crossing_rate),
            math.log1p(self.centroid_hz),
            math.log1p(self.spread_hz),
            math.log1p(self.rolloff_hz),
            self.flatness,
        ]

    @staticmethod
    def axes() -> list[str]:
        return [
            "log_n_samples", "looped", "loop_fraction", "attack_fraction",
            "log_zcr", "log_centroid", "log_spread", "log_rolloff",
            "flatness",
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "srcn": self.srcn,
            "n_samples": self.n_samples,
            "looped": self.looped,
            "loop_length": self.loop_length,
            "loop_fraction": round(self.loop_fraction, 4),
            "peak": round(self.peak, 2),
            "rms": round(self.rms, 2),
            "attack_fraction": round(self.attack_fraction, 4),
            "zero_crossing_rate": round(self.zero_crossing_rate, 1),
            "centroid_hz": round(self.centroid_hz, 1),
            "spread_hz": round(self.spread_hz, 1),
            "rolloff_hz": round(self.rolloff_hz, 1),
            "flatness": round(self.flatness, 4),
            "harmonicity": round(self.harmonicity, 4),
            "pitched": self.pitched,
            "f0_hz": round(self.f0_hz, 2),
        }


def _spectrum(samples: Sequence[int], size: int = DFT_SIZE) -> list[float]:
    """Magnitude spectrum of a Hann-windowed frame, by direct DFT.

    Taken from the middle of the sample, past the attack, so the measurement
    describes the body of the sound rather than its onset click. Short samples
    are zero-padded, which costs resolution and is honest about it.
    """
    if not samples:
        return [0.0] * (size // 2)
    centre = len(samples) // 2
    start = max(0, centre - size // 2)
    frame = [float(v) for v in samples[start : start + size]]
    if len(frame) < size:
        frame += [0.0] * (size - len(frame))
    # Hann window: without it the frame edges act as a step and smear energy
    # across every bin, which would flatten the spectrum of a pure tone.
    windowed = [
        v * 0.5 * (1.0 - math.cos(2.0 * math.pi * i / (size - 1)))
        for i, v in enumerate(frame)
    ]
    half = size // 2
    out = []
    for k in range(half):
        real = 0.0
        imag = 0.0
        angular = -2.0 * math.pi * k / size
        for n, v in enumerate(windowed):
            if v:
                real += v * math.cos(angular * n)
                imag += v * math.sin(angular * n)
        out.append(math.sqrt(real * real + imag * imag))
    return out


def _spectral_shape(magnitudes: Sequence[float]) -> tuple[float, float, float, float]:
    """(centroid, spread, rolloff, flatness) in Hz and normalised units."""
    total = sum(magnitudes)
    if total <= 0:
        return 0.0, 0.0, 0.0, 0.0
    bin_hz = DSP_RATE / DFT_SIZE
    centroid_bin = sum(i * m for i, m in enumerate(magnitudes)) / total
    spread_bin = math.sqrt(
        sum(((i - centroid_bin) ** 2) * m for i, m in enumerate(magnitudes)) / total
    )
    # 85% rolloff: the bin below which most of the energy sits.
    running = 0.0
    rolloff_bin = len(magnitudes) - 1
    for i, m in enumerate(magnitudes):
        running += m
        if running >= 0.85 * total:
            rolloff_bin = i
            break
    # Spectral flatness, on a floor so a silent bin cannot zero the product.
    floor = 1e-10
    log_mean = sum(math.log(max(m, floor)) for m in magnitudes) / len(magnitudes)
    arithmetic = total / len(magnitudes)
    flatness = math.exp(log_mean) / arithmetic if arithmetic > 0 else 0.0
    return (
        centroid_bin * bin_hz,
        spread_bin * bin_hz,
        rolloff_bin * bin_hz,
        min(1.0, flatness),
    )


def _harmonicity(magnitudes: Sequence[float], f0_hz: float) -> float:
    """Energy within one bin of an f0 harmonic, over total energy."""
    total = sum(magnitudes)
    if total <= 0 or f0_hz <= 0:
        return 0.0
    bin_hz = DSP_RATE / DFT_SIZE
    kept = 0.0
    harmonic = 1
    while True:
        centre = f0_hz * harmonic / bin_hz
        if centre >= len(magnitudes):
            break
        low = max(0, int(math.floor(centre)) - 1)
        high = min(len(magnitudes) - 1, int(math.ceil(centre)) + 1)
        kept += sum(magnitudes[low : high + 1])
        harmonic += 1
    return min(1.0, kept / total)


def features(
    srcn: int,
    data: Sequence[int],
    loop_offset: int | None,
    f0_hz: float | None = None,
) -> Features:
    """Measure one decoded BRR sample."""
    result = Features(srcn=srcn, n_samples=len(data))
    if not data:
        return result

    result.looped = loop_offset is not None
    if loop_offset is not None:
        result.loop_length = max(0, len(data) - loop_offset)
        result.loop_fraction = result.loop_length / len(data)

    absolute = [abs(float(v)) for v in data]
    result.peak = max(absolute)
    result.rms = math.sqrt(sum(v * v for v in absolute) / len(absolute))

    if result.peak > 0:
        threshold = 0.9 * result.peak
        reached = next(
            (i for i, v in enumerate(absolute) if v >= threshold), len(absolute) - 1
        )
        result.attack_fraction = reached / len(absolute)

    crossings = sum(
        1 for a, b in zip(data, data[1:]) if (a >= 0) != (b >= 0)
    )
    result.zero_crossing_rate = crossings * DSP_RATE / len(data)

    magnitudes = _spectrum(data)
    centroid, spread, rolloff, flatness = _spectral_shape(magnitudes)
    result.centroid_hz = centroid
    result.spread_hz = spread
    result.rolloff_hz = rolloff
    result.flatness = flatness

    if f0_hz:
        result.pitched = True
        result.f0_hz = f0_hz
        result.harmonicity = _harmonicity(magnitudes, f0_hz)
    return result


# --------------------------------------------------------------- the codebook


@dataclass
class Codebook:
    """A fixed set of timbre classes, and how it was arrived at."""

    k: int
    centroids: list[list[float]] = field(default_factory=list)
    axes: list[str] = field(default_factory=list)
    #: Feature means and ranges used to standardise, kept so a later sample can
    #: be assigned with the same scaling the codebook was built with.
    means: list[float] = field(default_factory=list)
    scales: list[float] = field(default_factory=list)
    inertia: float = 0.0
    n_samples: int = 0
    iterations: int = 0

    def assign(self, vector: Sequence[float]) -> int:
        standardised = _standardise_one(vector, self.means, self.scales)
        best = 0
        best_distance = float("inf")
        for index, centre in enumerate(self.centroids):
            distance = sum((a - b) ** 2 for a, b in zip(standardised, centre))
            if distance < best_distance:
                best_distance = distance
                best = index
        return best

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "axes": self.axes,
            "centroids": [[round(v, 4) for v in c] for c in self.centroids],
            "means": [round(v, 6) for v in self.means],
            "scales": [round(v, 6) for v in self.scales],
            "inertia": round(self.inertia, 4),
            "n_samples": self.n_samples,
            "iterations": self.iterations,
        }


def _standardise_one(
    vector: Sequence[float], means: Sequence[float], scales: Sequence[float]
) -> list[float]:
    return [
        (v - m) / s if s else 0.0 for v, m, s in zip(vector, means, scales)
    ]


def _standardise(vectors: Sequence[Sequence[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    """Zero mean, unit standard deviation per axis.

    Required, not cosmetic: the raw axes span log-samples around 10 and
    flatness around 0.01, so unstandardised Euclidean distance would be
    decided almost entirely by sample length.
    """
    width = len(vectors[0])
    means = [sum(v[i] for v in vectors) / len(vectors) for i in range(width)]
    scales = []
    for i in range(width):
        variance = sum((v[i] - means[i]) ** 2 for v in vectors) / len(vectors)
        deviation = math.sqrt(variance)
        scales.append(deviation if deviation > 1e-9 else 1.0)
    return (
        [_standardise_one(v, means, scales) for v in vectors],
        means,
        scales,
    )


def _kmeans(
    points: Sequence[Sequence[float]], k: int, *, seed: int = 0, iterations: int = 100
) -> tuple[list[list[float]], list[int], float, int]:
    """k-means with k-means++ seeding. Deterministic for a given seed."""
    rng = random.Random(seed)
    n = len(points)
    first = rng.randrange(n)
    centres = [list(points[first])]
    # k-means++: each further centre is drawn in proportion to its squared
    # distance from the nearest existing one. Plain random seeding on this data
    # repeatedly produced empty clusters.
    while len(centres) < k:
        weights = []
        for p in points:
            weights.append(
                min(sum((a - b) ** 2 for a, b in zip(p, c)) for c in centres)
            )
        total = sum(weights)
        if total <= 0:
            centres.append(list(points[rng.randrange(n)]))
            continue
        target = rng.random() * total
        running = 0.0
        for p, w in zip(points, weights):
            running += w
            if running >= target:
                centres.append(list(p))
                break

    labels = [0] * n
    used = 0
    for used in range(1, iterations + 1):
        moved = False
        for i, p in enumerate(points):
            best = 0
            best_distance = float("inf")
            for index, c in enumerate(centres):
                distance = sum((a - b) ** 2 for a, b in zip(p, c))
                if distance < best_distance:
                    best_distance = distance
                    best = index
            if labels[i] != best:
                labels[i] = best
                moved = True
        width = len(points[0])
        for index in range(k):
            members = [points[i] for i, lab in enumerate(labels) if lab == index]
            if not members:
                # An empty cluster is re-seeded on the worst-fit point rather
                # than dropped, so k stays the k that was asked for.
                worst = max(
                    range(n),
                    key=lambda i: sum(
                        (a - b) ** 2 for a, b in zip(points[i], centres[labels[i]])
                    ),
                )
                centres[index] = list(points[worst])
                continue
            centres[index] = [
                sum(m[j] for m in members) / len(members) for j in range(width)
            ]
        if not moved:
            break

    inertia = 0.0
    for i, p in enumerate(points):
        inertia += sum((a - b) ** 2 for a, b in zip(p, centres[labels[i]]))
    return centres, labels, inertia, used


def build(
    feature_list: Sequence[Features], k: int, *, seed: int = 0
) -> tuple[Codebook, list[int]]:
    """Fit a codebook of `k` classes and return it with per-sample labels."""
    vectors = [f.vector() for f in feature_list]
    if not vectors:
        return Codebook(k=k, axes=Features.axes()), []
    standardised, means, scales = _standardise(vectors)
    k = max(1, min(k, len(standardised)))
    centres, labels, inertia, iterations = _kmeans(standardised, k, seed=seed)
    book = Codebook(
        k=k,
        centroids=centres,
        axes=Features.axes(),
        means=means,
        scales=scales,
        inertia=inertia,
        n_samples=len(standardised),
        iterations=iterations,
    )
    return book, labels


def silhouette(
    feature_list: Sequence[Features], labels: Sequence[int], *, sample_limit: int = 600, seed: int = 0
) -> float:
    """Mean silhouette over a sample: +1 well separated, 0 on a boundary.

    Sampled because the statistic is O(n^2) and the corpus has thousands of
    samples; the mean converges long before that matters.
    """
    vectors = [f.vector() for f in feature_list]
    if len(vectors) < 3 or len(set(labels)) < 2:
        return 0.0
    standardised, _means, _scales = _standardise(vectors)
    rng = random.Random(seed)
    indices = list(range(len(standardised)))
    if len(indices) > sample_limit:
        indices = rng.sample(indices, sample_limit)
    total = 0.0
    counted = 0
    for i in indices:
        own = labels[i]
        same = []
        other: dict[int, list[float]] = {}
        for j, point in enumerate(standardised):
            if j == i:
                continue
            distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(standardised[i], point))
            )
            if labels[j] == own:
                same.append(distance)
            else:
                other.setdefault(labels[j], []).append(distance)
        if not same or not other:
            continue
        a = sum(same) / len(same)
        b = min(sum(v) / len(v) for v in other.values())
        spread = max(a, b)
        if spread > 0:
            total += (b - a) / spread
            counted += 1
    return total / counted if counted else 0.0
