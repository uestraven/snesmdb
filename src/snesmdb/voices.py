"""Turn a raw DSP write log into voice events.

The C++ logger stays dumb on purpose: it emits timestamped register writes and
nothing else. This is where those become notes, because the semantics will
change many times and are far cheaper to iterate and test here.

What a "note" is on this hardware. The driver writes a voice's parameters
(pitch, sample, volume, envelope) and then sets a bit in KON. The DSP starts
that voice. The note ends at the matching KOFF bit, or -- drivers do this --
at the next KON for the same voice without an intervening KOFF. So a note's
parameters are the LATEST values written to that voice's registers at the
moment its KON bit is set, which means the log has to be replayed in order
rather than grouped by register.

Deliberately NOT done here: pitch is left as the raw 14-bit PITCH register
value, not converted to a note number. That conversion needs each BRR sample's
own fundamental frequency, which lives in the game's private instrument table
and has to be recovered from the sample data. Guessing a base frequency would
put a plausible, wrong number in the corpus. PITCH ratios are already exact
and are enough for interval-level work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

#: SPC700 clocks per second.
CLOCK_RATE = 1_024_000

#: Per-voice register offsets within a voice's 0x10-byte block.
V_VOLL, V_VOLR, V_PITCHL, V_PITCHH = 0x00, 0x01, 0x02, 0x03
V_SRCN, V_ADSR1, V_ADSR2, V_GAIN = 0x04, 0x05, 0x06, 0x07

R_KON, R_KOFF, R_FLG, R_DIR = 0x4C, 0x5C, 0x6C, 0x5D
R_NON, R_PMON, R_EON = 0x3D, 0x2D, 0x4D

VOICE_COUNT = 8

#: Global registers with no per-note meaning, enumerated EXPLICITLY.
#:
#: An earlier version ignored anything whose low nibble was 0x0C or 0x0D,
#: which is wrong in a way that matters: 0x1D is unused on real hardware, and
#: the broad test swallowed it, so an SPC writing registers we do not model
#: would have reported full coverage. Listing them individually means
#: `unhandled` actually earns its name.
KNOWN_GLOBAL: frozenset[int] = frozenset(
    {
        0x0C,  # MVOLL
        0x1C,  # MVOLR
        0x2C,  # EVOLL
        0x3C,  # EVOLR
        0x6C,  # FLG
        0x7C,  # ENDX (readback)
        0x0D,  # EFB
        0x4D,  # EON
        0x5D,  # DIR
        0x6D,  # ESA
        0x7D,  # EDL
    }
)

#: Per-voice readback registers (ENVX, OUTX) and the echo FIR coefficients.
KNOWN_IGNORED_LOW: frozenset[int] = frozenset({0x08, 0x09, 0x0F})


def _signed8(value: int) -> int:
    return value - 256 if value >= 128 else value


@dataclass
class VoiceState:
    """The registers a driver has written for one voice, so far."""

    voll: int = 0
    volr: int = 0
    pitchl: int = 0
    pitchh: int = 0
    srcn: int = 0
    adsr1: int = 0
    adsr2: int = 0
    gain: int = 0

    @property
    def pitch(self) -> int:
        """The 14-bit PITCH register: a resample RATIO, not a frequency."""
        return ((self.pitchh & 0x3F) << 8) | (self.pitchl & 0xFF)


@dataclass
class Note:
    """One sounding voice, from key-on to key-off."""

    voice: int
    start: int
    end: int | None
    pitch: int
    srcn: int
    volume_left: int
    volume_right: int
    adsr1: int
    adsr2: int
    gain: int
    #: True when the note was ended by the next key-on rather than a key-off.
    ended_by_rekey: bool = False
    #: True when NON had this voice's bit set, so the DSP played noise and the
    #: sample and pitch mean nothing.
    noise: bool = False
    #: True when PMON had this voice's bit set, so its pitch was modulated by
    #: the previous voice and the PITCH register alone does not describe it.
    pitch_modulated: bool = False

    @property
    def duration(self) -> int | None:
        return None if self.end is None else self.end - self.start

    def seconds(self) -> tuple[float, float | None]:
        end = None if self.end is None else self.end / CLOCK_RATE
        return self.start / CLOCK_RATE, end

    def to_dict(self) -> dict[str, Any]:
        start_s, end_s = self.seconds()
        return {
            "voice": self.voice,
            "start": self.start,
            "end": self.end,
            "start_sec": start_s,
            "end_sec": end_s,
            "pitch_register": self.pitch,
            "srcn": self.srcn,
            "volume_left": self.volume_left,
            "volume_right": self.volume_right,
            "adsr1": self.adsr1,
            "adsr2": self.adsr2,
            "gain": self.gain,
            "ended_by_rekey": self.ended_by_rekey,
            "noise": self.noise,
            "pitch_modulated": self.pitch_modulated,
        }


@dataclass
class Extraction:
    notes: list[Note] = field(default_factory=list)
    #: Register writes the extractor did not interpret, by name, for honesty
    #: about coverage rather than silent omission.
    unhandled: dict[str, int] = field(default_factory=dict)
    n_writes: int = 0
    last_time: int = 0

    def summary(self) -> dict[str, Any]:
        voices = sorted({n.voice for n in self.notes})
        samples = sorted({n.srcn for n in self.notes})
        complete = [n for n in self.notes if n.duration is not None]
        return {
            "n_writes": self.n_writes,
            "n_notes": len(self.notes),
            "duration_sec": self.last_time / CLOCK_RATE,
            "voices_used": voices,
            "n_voices_used": len(voices),
            "samples_used": samples,
            "n_samples_used": len(samples),
            "n_unfinished_notes": len(self.notes) - len(complete),
            "n_noise_notes": sum(1 for n in self.notes if n.noise),
            "n_pitch_modulated_notes": sum(
                1 for n in self.notes if n.pitch_modulated
            ),
            "unhandled_writes": dict(sorted(self.unhandled.items())),
        }


def read_log(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def extract(writes: Iterator[dict[str, Any]]) -> Extraction:
    """Replay a write log and recover the notes it describes."""
    state = [VoiceState() for _ in range(VOICE_COUNT)]
    live: dict[int, Note] = {}
    out = Extraction()
    noise_mask = pmon_mask = 0

    for write in writes:
        addr = int(write["addr"])
        data = int(write["data"])
        time = int(write["t"])
        out.n_writes += 1
        out.last_time = max(out.last_time, time)

        low = addr & 0x0F
        if low <= 0x07:
            voice = addr >> 4
            if voice < VOICE_COUNT:
                slot = state[voice]
                if low == V_VOLL:
                    slot.voll = data
                elif low == V_VOLR:
                    slot.volr = data
                elif low == V_PITCHL:
                    slot.pitchl = data
                elif low == V_PITCHH:
                    slot.pitchh = data
                elif low == V_SRCN:
                    slot.srcn = data
                elif low == V_ADSR1:
                    slot.adsr1 = data
                elif low == V_ADSR2:
                    slot.adsr2 = data
                elif low == V_GAIN:
                    slot.gain = data
            continue

        if addr == R_NON:
            noise_mask = data
        elif addr == R_PMON:
            pmon_mask = data
        elif addr == R_KON:
            for voice in range(VOICE_COUNT):
                if not (data >> voice) & 1:
                    continue
                # A re-key with no KOFF ends the previous note. Drivers do
                # this, and treating it as a continuation would merge two
                # notes into one.
                previous = live.pop(voice, None)
                if previous is not None:
                    previous.end = time
                    previous.ended_by_rekey = True
                slot = state[voice]
                note = Note(
                    voice=voice,
                    start=time,
                    end=None,
                    pitch=slot.pitch,
                    srcn=slot.srcn,
                    volume_left=_signed8(slot.voll),
                    volume_right=_signed8(slot.volr),
                    adsr1=slot.adsr1,
                    adsr2=slot.adsr2,
                    gain=slot.gain,
                    noise=bool((noise_mask >> voice) & 1),
                    pitch_modulated=bool((pmon_mask >> voice) & 1),
                )
                live[voice] = note
                out.notes.append(note)
        elif addr == R_KOFF:
            for voice in range(VOICE_COUNT):
                if (data >> voice) & 1:
                    note = live.pop(voice, None)
                    if note is not None:
                        note.end = time
        elif addr in KNOWN_GLOBAL or low in KNOWN_IGNORED_LOW:
            pass  # no per-note semantics
        else:
            name = str(write.get("reg", hex(addr)))
            out.unhandled[name] = out.unhandled.get(name, 0) + 1

    out.notes.sort(key=lambda n: (n.start, n.voice))
    return out
