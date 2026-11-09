"""A deliberately minimal, deterministic playback engine for A/B listening.

NOT a synthesizer, and not an S-DSP model. Its only job is to make a
difference in SAMPLE IDENTITY audible while holding everything else fixed,
so that a listener comparing two renders is comparing that one variable.

What it does NOT model, on purpose: stereo panning and per-channel volume,
ADSR rates, the echo/FIR unit, pitch modulation, noise, and the 32-step
Gaussian interpolation. None of those are in the published representation,
so a render cannot recover them -- but every one of them is IDENTICAL in
both candidate renders, and therefore cancels in the comparison. Absolute
fidelity to the SPC is not claimed and is not what the experiment measures.

Two properties matter more than sound quality:

    DETERMINISM   the same inputs produce byte-identical output. No RNG, no
                  dict-iteration order, no floating-point accumulation whose
                  order depends on anything but event order.
    NO SUBSTITUTION
                  an event whose identity is unresolved, or absent from the
                  bank, is NOT rendered and is reported. Filling it with a
                  convenient sample would manufacture the very agreement the
                  experiment is trying to test.

The pitch treatment is the one place this is faithful rather than
approximate: the SNES PITCH register IS a resample ratio, with $1000
meaning 1.0x, so `pitch_register / 4096` is what the hardware does. No
assumption about a sample's natural base pitch is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SAMPLE_RATE = 32000          # the S-DSP's output rate
PITCH_UNITY = 0x1000         # PITCH register value meaning 1.0x
LEVEL_FULL = 15              # attack_level / sustain_level are 0..15
ATTACK_SEC = 0.008
RELEASE_SEC = 0.004
VOICE_HEADROOM = 8           # mix divisor: eight voices without clipping


@dataclass(frozen=True)
class Sample:
    """Decoded audio for one canonical identity.

    `loop_offset` is None for a one-shot. It is part of the identity, so two
    `Sample`s differing only in loop point are different identities.
    """

    pcm: tuple[int, ...]
    loop_offset: int | None


@dataclass
class Event:
    """One note to render, assembled from the published representation."""

    onset_sec: float
    duration_sec: float
    voice: int
    pitch_register: int
    attack_level: int
    sustain_level: int
    sample_id: str | None


@dataclass
class Render:
    pcm: list[int] = field(default_factory=list)
    rendered: int = 0
    skipped_unresolved_identity: int = 0
    skipped_identity_not_in_bank: int = 0
    skipped_unusable_event: int = 0
    skipped_ids: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> int:
        return (self.skipped_unresolved_identity
                + self.skipped_identity_not_in_bank
                + self.skipped_unusable_event)


def _envelope(index: int, total: int, attack: float, sustain: float) -> float:
    """Attack to `attack`, decay to `sustain`, short release. Shared by both
    candidates, so its crudeness cannot bias the comparison."""
    if total <= 0:
        return 0.0
    a = min(int(ATTACK_SEC * SAMPLE_RATE), total)
    r = min(int(RELEASE_SEC * SAMPLE_RATE), total - a) if total > a else 0
    if index < a:
        return attack * (index + 1) / a if a else attack
    if index >= total - r and r:
        return sustain * (total - index) / r
    body = total - a - r
    if body <= 0:
        return sustain
    t = (index - a) / body
    return attack + (sustain - attack) * t


def render(
    events: list[Event],
    bank: dict[str, Sample],
    seconds: float,
) -> Render:
    """Mix `events` into a mono buffer. Deterministic for fixed inputs.

    Events are processed in the order given; the caller sorts them. Nothing
    here iterates a dict or depends on insertion order, so two runs over
    equal inputs produce equal output.
    """
    total = max(1, int(seconds * SAMPLE_RATE))
    acc = [0.0] * total
    out = Render()

    for event in events:
        if not event.sample_id:
            # No established identity. NOT rendered, NOT substituted.
            #
            # Tested for falsiness, not `is None`: the published records use
            # BOTH null and the empty string for "no identity", and treating
            # "" as a real id sent six baseline attacks looking for a sample
            # named "" -- so candidate A fell silent where B played, an
            # asymmetry that had nothing to do with sample identity.
            out.skipped_unresolved_identity += 1
            continue
        sample = bank.get(event.sample_id)
        if sample is None:
            out.skipped_identity_not_in_bank += 1
            out.skipped_ids.append(event.sample_id)
            continue
        if not sample.pcm or event.duration_sec <= 0:
            out.skipped_unusable_event += 1
            continue

        ratio = event.pitch_register / PITCH_UNITY
        if ratio <= 0:
            out.skipped_unusable_event += 1
            continue

        start = int(event.onset_sec * SAMPLE_RATE)
        if start >= total:
            continue
        length = min(int(event.duration_sec * SAMPLE_RATE), total - start)
        if length <= 0:
            continue

        attack = min(event.attack_level, LEVEL_FULL) / LEVEL_FULL
        sustain = min(event.sustain_level, LEVEL_FULL) / LEVEL_FULL
        n = len(sample.pcm)
        loop = sample.loop_offset

        for i in range(length):
            # Nearest-neighbour resampling: audibly adequate, and identical
            # for both candidates. Interpolation would change both renders
            # the same way and so cannot affect the comparison.
            pos = int(i * ratio)
            if pos >= n:
                if loop is None or loop >= n:
                    break          # one-shot: the note simply stops
                span = n - loop
                pos = loop + (pos - n) % span
            acc[start + i] += (sample.pcm[pos] / VOICE_HEADROOM) * _envelope(
                i, length, attack, sustain)
        out.rendered += 1

    out.pcm = [max(-32768, min(32767, int(v))) for v in acc]
    return out


def wav_bytes(pcm: list[int], rate: int = SAMPLE_RATE) -> bytes:
    """A 16-bit mono WAV. Written here rather than via `wave` so the bytes
    are fully determined by `pcm` -- no library metadata, no timestamps."""
    data = bytearray()
    for v in pcm:
        data += int(v).to_bytes(2, "little", signed=True)
    n = len(data)
    head = bytearray()
    head += b"RIFF" + (36 + n).to_bytes(4, "little") + b"WAVE"
    head += b"fmt " + (16).to_bytes(4, "little")
    head += (1).to_bytes(2, "little") + (1).to_bytes(2, "little")
    head += rate.to_bytes(4, "little") + (rate * 2).to_bytes(4, "little")
    head += (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
    head += b"data" + n.to_bytes(4, "little")
    return bytes(head + data)
