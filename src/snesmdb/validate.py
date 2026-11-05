"""Scoring an extraction against the emulator's own audio.

Why this exists, specifically. It would be easy to score an extraction against
our own idea of what the SPC contains, which proves nothing: the sibling
project shipped a BRR codec validated only against its own decoder and hid a
67% hardware wrap rate behind three rounds of green tests. The only
trustworthy reference is the emulator's rendered output, which is downstream
of the write log but independent of our interpretation of it.

What this measures. The extractor claims notes start at particular times. If
that claim is right, the rendered audio should show amplitude onsets at those
times. So: detect onsets in the WAV, and ask what fraction of extracted
note-starts have an audio onset nearby, and what fraction of audio onsets were
accounted for. Both directions matter -- the first catches invented notes, the
second catches missed ones.

What this is NOT. It is a proxy for the full gate, which is to re-render the
extracted score with a SNES renderer and compare waveforms. That needs the
renderer and the later milestones (pitch, grid, timbre); this works today and
catches the failure that matters most now, which is timing. It says nothing
about whether recovered PITCH values are correct.
"""

from __future__ import annotations

import array
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from snesmdb.voices import CLOCK_RATE

#: An extracted onset and an audio onset within this many milliseconds of each
#: other are treated as the same event. The S-DSP applies a key-on over a few
#: samples and envelopes have attack time, so an audio onset legitimately lags
#: the register write.
DEFAULT_TOLERANCE_MS = 12.0


@dataclass
class Validation:
    n_extracted: int
    n_audio: int
    n_matched: int
    tolerance_ms: float
    #: Audio onsets with no extracted note nearby: notes we may have missed.
    unexplained_audio: int
    #: Extracted notes with no audio onset nearby: notes we may have invented.
    unsupported_notes: int

    @property
    def recall(self) -> float:
        """Fraction of audio onsets explained by an extracted note."""
        return self.n_matched / self.n_audio if self.n_audio else 0.0

    @property
    def precision(self) -> float:
        """Fraction of extracted notes supported by an audio onset."""
        return self.n_matched / self.n_extracted if self.n_extracted else 0.0

    @property
    def score(self) -> float:
        """Harmonic mean, so one good direction cannot hide a bad one."""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_extracted_onsets": self.n_extracted,
            "n_audio_onsets": self.n_audio,
            "n_matched": self.n_matched,
            "precision": self.precision,
            "recall": self.recall,
            "score": self.score,
            "unexplained_audio_onsets": self.unexplained_audio,
            "unsupported_notes": self.unsupported_notes,
            "tolerance_ms": self.tolerance_ms,
            "method": "audio-onset agreement (proxy for full re-render gate)",
        }


def read_wav_mono(path: str | Path) -> tuple[list[float], int]:
    """Read a WAV as mono floats. Stereo channels are averaged."""
    with wave.open(str(path)) as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        if width != 2:
            raise ValueError(f"{path}: expected 16-bit audio, got {width * 8}-bit")
        samples = array.array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
    if channels == 1:
        return [float(s) for s in samples], rate
    mono = [
        (samples[i] + samples[i + 1]) / 2.0 for i in range(0, len(samples) - 1, channels)
    ]
    return mono, rate


def detect_onsets(
    samples: Sequence[float],
    rate: int,
    *,
    hop_ms: float = 2.0,
    rise_ratio: float = 2.5,
    floor: float = 0.005,
) -> list[float]:
    """Onset times in seconds, from a rise in short-window energy.

    Deliberately simple: a frame is an onset when its RMS exceeds the previous
    frame's by `rise_ratio` and clears an absolute `floor`. A spectral-flux
    detector would find more, but every parameter added here is a parameter
    that can be tuned until the validation passes, which would defeat the
    point of having an independent reference.
    """
    hop = max(1, int(rate * hop_ms / 1000.0))
    peak = max((abs(s) for s in samples), default=0.0) or 1.0
    energies: list[float] = []
    for start in range(0, len(samples) - hop, hop):
        window = samples[start : start + hop]
        rms = (sum(s * s for s in window) / len(window)) ** 0.5 / peak
        energies.append(rms)

    onsets: list[float] = []
    for index in range(len(energies)):
        # Silence before the file starts. Without this the FIRST note is
        # always missed -- frame 0 already contains audio, so there is no rise
        # into it -- and since nearly every track begins at t=0, every score
        # came out exactly one onset short. A gate with a systematic bias is
        # worse than no gate: it is the thing you end up tuning thresholds
        # against.
        previous = energies[index - 1] if index else 0.0
        current = energies[index]
        if current < floor:
            continue
        if previous <= 0.0 or current / max(previous, 1e-9) >= rise_ratio:
            onsets.append(index * hop / rate)
    return onsets


def compare(
    note_starts_clocks: Sequence[int],
    audio_onsets_sec: Sequence[float],
    *,
    tolerance_ms: float = DEFAULT_TOLERANCE_MS,
) -> Validation:
    """Match extracted note starts against audio onsets, one to one.

    Greedy nearest-match without reuse, so two extracted notes cannot both
    claim the same audio onset -- otherwise a burst of spurious notes near one
    real onset would score as perfect precision.
    """
    extracted = sorted(t / CLOCK_RATE for t in note_starts_clocks)
    audio = sorted(float(t) for t in audio_onsets_sec)
    tolerance = tolerance_ms / 1000.0

    used: set[int] = set()
    matched = 0
    for start in extracted:
        best: tuple[float, int] | None = None
        for index, onset in enumerate(audio):
            if index in used:
                continue
            delta = abs(onset - start)
            if delta <= tolerance and (best is None or delta < best[0]):
                best = (delta, index)
        if best is not None:
            used.add(best[1])
            matched += 1

    return Validation(
        n_extracted=len(extracted),
        n_audio=len(audio),
        n_matched=matched,
        tolerance_ms=tolerance_ms,
        unexplained_audio=len(audio) - len(used),
        unsupported_notes=len(extracted) - matched,
    )


def validate_wav(
    note_starts_clocks: Sequence[int],
    wav_path: str | Path,
    *,
    tolerance_ms: float = DEFAULT_TOLERANCE_MS,
) -> Validation:
    samples, rate = read_wav_mono(wav_path)
    return compare(
        note_starts_clocks, detect_onsets(samples, rate), tolerance_ms=tolerance_ms
    )
