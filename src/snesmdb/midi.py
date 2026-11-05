"""Eight-track MIDI, one track per DSP voice.

Milestone 6. This is not novel and the design doc says so: VGMTrans already
does per-driver SPC-to-MIDI well. It exists so every track in the corpus has a
MIDI rendering produced the same way, by the same driver-agnostic pipeline, as
every other -- uniformity rather than capability.

What it deliberately does NOT do is guess. There is no instrument assignment,
because milestone 5 established that sample identity does not transfer across
games, so any General MIDI program number here would be invention. Every track
is left on program 0 and the voice index is the only identity claimed. Channel
10 is avoided entirely rather than used for the percussive class, for the same
reason: the mapping from a BRR sample to a GM drum note is not recoverable.

Pure stdlib. A MIDI file is a header chunk and one chunk per track, and the
only fiddly part is the variable-length delta encoding.
"""

from __future__ import annotations

import struct
from typing import Any, Iterable, Sequence

TICKS_PER_SECOND = 1_024_000

#: Pulses per quarter note in the emitted file. 480 is the usual DAW default
#: and divides cleanly by 2, 3, 4, 5, 6 and 8, so triplets and quintuplets
#: both land on integers.
PPQ = 480

#: Tempo written into the file. The S-DSP has no tempo, so one is chosen and
#: all timing is expressed against it: at 120 BPM a quarter note is 0.5 s and
#: a PPQ tick is 1/960 s, which is finer than the 20 ms the ear resolves.
BPM = 120.0

#: DSP voices. Channel 9 (zero-based) is General MIDI percussion and is
#: skipped, so voice 7 lands on channel 8 and nothing is implicitly a drum.
CHANNEL_FOR_VOICE = (0, 1, 2, 3, 4, 5, 6, 8)


def _vlq(value: int) -> bytes:
    """MIDI variable-length quantity."""
    if value < 0:
        value = 0
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def _chunk(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack(">I", len(body)) + body


def _ppq_of(tick: int) -> int:
    """SPC700 clock ticks to MIDI pulses."""
    seconds = tick / TICKS_PER_SECOND
    return int(round(seconds * (BPM / 60.0) * PPQ))


def _velocity(note: dict[str, Any]) -> int:
    """Volume to MIDI velocity.

    The S-DSP's per-side volumes are signed 8-bit and a negative one inverts
    that side's phase, which MIDI cannot express -- so magnitude is used and
    the inversion is lost. That loss is listed in the corpus limitations
    rather than hidden here, and it matters: two games invert the phase on
    over half their notes.
    """
    left = abs(int(note.get("volume_left") or 0))
    right = abs(int(note.get("volume_right") or 0))
    loudness = (left + right) / 2.0
    # The hardware range is 0..127 per side; map to 1..127 so a sounding note
    # is never silent, which MIDI would read as a note-off.
    return max(1, min(127, int(round(loudness))))


def _pan_controller(note: dict[str, Any]) -> int | None:
    """CC10 pan from the ratio of the two volumes, or None if centred."""
    left = abs(int(note.get("volume_left") or 0))
    right = abs(int(note.get("volume_right") or 0))
    total = left + right
    if total == 0:
        return None
    value = int(round(64 + 63 * ((right - left) / total)))
    value = max(0, min(127, value))
    return None if value == 64 else value


def from_notes(
    notes: Sequence[dict[str, Any]],
    *,
    render_ticks: int = 0,
    name: str = "",
    n_voices: int = 8,
) -> bytes:
    """A type-1 MIDI file: one conductor track, then one track per voice.

    Only notes carrying a recovered MIDI number appear. An unpitched note has
    no note number to write and inventing one would put a wrong pitch in a
    published artifact; the count of what was dropped is returned by
    `summary()` so a consumer knows.
    """
    tracks: list[bytes] = []

    # Track 0: tempo and name only, as type 1 expects.
    conductor = bytearray()
    conductor += _vlq(0) + b"\xff\x51\x03" + struct.pack(">I", int(60_000_000 / BPM))[1:]
    if name:
        label = name.encode("utf-8", "replace")[:127]
        conductor += _vlq(0) + b"\xff\x03" + _vlq(len(label)) + label
    conductor += _vlq(0) + b"\xff\x2f\x00"
    tracks.append(_chunk(b"MTrk", bytes(conductor)))

    by_voice: dict[int, list[dict[str, Any]]] = {v: [] for v in range(n_voices)}
    for note in notes:
        voice = int(note["voice"])
        if 0 <= voice < n_voices and note.get("midi_note") is not None:
            by_voice[voice].append(note)

    for voice in range(n_voices):
        channel = CHANNEL_FOR_VOICE[voice % len(CHANNEL_FOR_VOICE)]
        items = sorted(by_voice[voice], key=lambda n: int(n["start"]))
        events: list[tuple[int, int, bytes]] = []
        # (pulse, order, bytes). `order` keeps note-off before note-on at the
        # same pulse, so a re-keyed voice does not end up with two overlapping
        # notes of the same pitch -- which some players render as a stuck note.
        last_pan: int | None = None
        for note in items:
            number = int(round(float(note["midi_note"])))
            if not 1 <= number <= 127:
                continue
            start = _ppq_of(int(note["start"]))
            end_tick = note.get("end")
            end = _ppq_of(int(end_tick)) if end_tick is not None else _ppq_of(render_ticks)
            if end <= start:
                end = start + 1
            pan = _pan_controller(note)
            if pan is not None and pan != last_pan:
                events.append((start, 0, bytes([0xB0 | channel, 10, pan])))
                last_pan = pan
            events.append((start, 1, bytes([0x90 | channel, number, _velocity(note)])))
            events.append((end, 0, bytes([0x80 | channel, number, 0])))

        events.sort(key=lambda item: (item[0], item[1]))
        body = bytearray()
        label = f"voice {voice}".encode()
        body += _vlq(0) + b"\xff\x03" + _vlq(len(label)) + label
        previous = 0
        for pulse, _order, payload in events:
            body += _vlq(max(0, pulse - previous)) + payload
            previous = pulse
        body += _vlq(0) + b"\xff\x2f\x00"
        tracks.append(_chunk(b"MTrk", bytes(body)))

    header = _chunk(b"MThd", struct.pack(">HHH", 1, len(tracks), PPQ))
    return header + b"".join(tracks)


def summary(notes: Iterable[dict[str, Any]], n_voices: int = 8) -> dict[str, Any]:
    """What the MIDI contains and what it had to leave out."""
    total = 0
    written = 0
    unpitched = 0
    out_of_range = 0
    bad_voice = 0
    inverted = 0
    for note in notes:
        total += 1
        if not 0 <= int(note["voice"]) < n_voices:
            bad_voice += 1
            continue
        if note.get("midi_note") is None:
            unpitched += 1
            continue
        if not 1 <= int(round(float(note["midi_note"]))) <= 127:
            out_of_range += 1
            continue
        written += 1
        if (int(note.get("volume_left") or 0) < 0) != (int(note.get("volume_right") or 0) < 0):
            inverted += 1
    return {
        "n_notes": total,
        "n_written": written,
        "n_unpitched_dropped": unpitched,
        "n_out_of_range_dropped": out_of_range,
        "n_bad_voice_dropped": bad_voice,
        # Phase inversion cannot be expressed in MIDI, so these notes are
        # written with their magnitude and the effect is lost.
        "n_phase_inverted_flattened": inverted,
        "ppq": PPQ,
        "bpm": BPM,
    }
