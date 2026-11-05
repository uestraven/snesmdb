"""Milestone 5: BRR sample features and the timbre codebook."""

from __future__ import annotations

import math
import random

import pytest

from snesmdb import timbre
from snesmdb.timbre import DSP_RATE, Features


def _sine(hz: float, n: int, amp: int = 10000) -> list[int]:
    return [int(amp * math.sin(2 * math.pi * hz * i / DSP_RATE)) for i in range(n)]


def _noise(n: int, amp: int = 10000, seed: int = 1) -> list[int]:
    rng = random.Random(seed)
    return [rng.randint(-amp, amp) for _ in range(n)]


# --- features --------------------------------------------------------------


def test_a_tone_is_not_flat_and_noise_is() -> None:
    """Spectral flatness is the axis that separates pitch from percussion."""
    tone = timbre.features(0, _sine(440, 4096), 0, 440.0)
    noise = timbre.features(1, _noise(4096), None)
    assert tone.flatness < 0.1
    assert noise.flatness > 0.3
    assert noise.flatness > tone.flatness * 3


def test_centroid_tracks_pitch() -> None:
    low = timbre.features(0, _sine(200, 4096), 0, 200.0)
    high = timbre.features(1, _sine(3000, 4096), 0, 3000.0)
    assert high.centroid_hz > low.centroid_hz * 3


def test_zero_crossing_rate_is_about_twice_the_frequency() -> None:
    f = timbre.features(0, _sine(500, 8192), 0, 500.0)
    assert f.zero_crossing_rate == pytest.approx(1000, rel=0.1)


def test_a_struck_sound_has_an_immediate_attack() -> None:
    struck = [10000] + [int(10000 * 0.999**i) for i in range(1, 4000)]
    swelled = [int(10000 * i / 4000) for i in range(4000)]
    assert timbre.features(0, struck, None).attack_fraction < 0.01
    # A linear ramp reaches 90% of its peak at exactly 0.9 of its length, so
    # the boundary is the expected value rather than something to clear.
    assert timbre.features(1, swelled, None).attack_fraction == pytest.approx(0.9, abs=0.01)


def test_loop_structure_is_reported() -> None:
    data = _sine(440, 4000)
    looped = timbre.features(0, data, 2000, 440.0)
    one_shot = timbre.features(1, data, None, 440.0)
    assert looped.looped and looped.loop_length == 2000
    assert looped.loop_fraction == pytest.approx(0.5)
    assert not one_shot.looped and one_shot.loop_fraction == 0.0


def test_harmonicity_is_high_for_a_tone_and_low_for_noise() -> None:
    tone = timbre.features(0, _sine(440, 4096), 0, 440.0)
    noise = timbre.features(1, _noise(4096), None, 440.0)
    assert tone.harmonicity > noise.harmonicity


def test_an_empty_sample_does_not_raise() -> None:
    f = timbre.features(0, [], None)
    assert f.n_samples == 0 and f.vector()


def test_f0_dependent_features_are_measured_but_kept_out_of_the_vector() -> None:
    """The leak that made the first validation circular.

    `pitched` and `harmonicity` both depend on whether an f0 was recoverable,
    and the usage half's `unpitched_fraction` is very nearly the same thing --
    a note gets a MIDI number only when its sample's f0 estimate was usable.
    With them in the vector, separation measured 426 against a null of 0.18 and
    was measuring the leak.
    """
    axes = Features.axes()
    assert "pitched" not in axes
    assert "harmonicity" not in axes
    assert len(Features().vector()) == len(axes)
    # Still measured and reported, because they are useful to a consumer.
    reported = timbre.features(0, _sine(440, 4096), 0, 440.0).to_dict()
    assert "pitched" in reported and "harmonicity" in reported


# --- the codebook ----------------------------------------------------------


def _population(seed: int = 0) -> list[Features]:
    rng = random.Random(seed)
    out = []
    for _ in range(40):
        out.append(timbre.features(0, _sine(rng.uniform(150, 400), 4096), 0, 300.0))
    for _ in range(40):
        out.append(timbre.features(1, _noise(1024, seed=rng.randrange(999)), None))
    return out


def test_two_obvious_families_separate() -> None:
    book, labels = timbre.build(_population(), 2, seed=0)
    assert book.k == 2
    tones, noises = labels[:40], labels[40:]
    assert len(set(tones)) == 1
    assert len(set(noises)) == 1
    assert tones[0] != noises[0]


def test_the_codebook_is_deterministic_for_a_seed() -> None:
    a = timbre.build(_population(), 4, seed=3)
    b = timbre.build(_population(), 4, seed=3)
    assert a[0].to_dict() == b[0].to_dict()
    assert a[1] == b[1]


def test_assignment_uses_the_scaling_the_codebook_was_built_with() -> None:
    population = _population()
    book, labels = timbre.build(population, 2, seed=0)
    for feat, label in zip(population, labels):
        assert book.assign(feat.vector()) == label


def test_standardising_is_not_optional() -> None:
    """Raw axes span log-samples near 10 and flatness near 0.01, so
    unstandardised distance would be decided by sample length alone."""
    book, _labels = timbre.build(_population(), 3, seed=0)
    assert len(book.means) == len(Features.axes())
    assert all(s > 0 for s in book.scales)


def test_k_is_never_more_than_the_population() -> None:
    book, labels = timbre.build(_population()[:3], 10, seed=0)
    assert book.k == 3
    assert len(set(labels)) <= 3


def test_an_empty_population_yields_an_empty_codebook() -> None:
    book, labels = timbre.build([], 4)
    assert book.centroids == [] and labels == []


def test_silhouette_is_higher_for_the_right_k_on_separable_data() -> None:
    population = _population()
    _b2, l2 = timbre.build(population, 2, seed=0)
    _b7, l7 = timbre.build(population, 7, seed=0)
    assert timbre.silhouette(population, l2, seed=0) > timbre.silhouette(
        population, l7, seed=0
    )


def test_silhouette_is_zero_without_two_classes() -> None:
    population = _population()
    assert timbre.silhouette(population, [0] * len(population)) == 0.0
