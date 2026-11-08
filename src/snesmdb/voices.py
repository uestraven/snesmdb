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
import math
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

#: LEGATO NOTE SUCCESSIONS. A driver can hand a sounding voice a new note by
#: writing PITCH, with no key-on. To the DSP that is indistinguishable from a
#: bend or a vibrato cycle, so the separation is a judgement, and these are
#: the thresholds it rests on. All three were set from measurement:
#:
#: A jump must exceed half a semitone. Vibrato and portamento are built from
#: increments far smaller -- the "Time Vortex" sweep runs at a median of 0.031
#: semitones per write, 76% of them under 0.1 -- so this alone excludes both
#: mechanisms, and is why a long monotonic run does not need rejecting.
LEGATO_MIN_SEMITONES = 0.5

#: ...and the pitch must not come back. A vibrato cycle returns; a new note
#: stays. Measured, 78-96% of qualifying jumps never return, and those that do
#: return do so well inside this window.
LEGATO_RETURN_WINDOW_TICKS = 102_400          # 100 ms at 1.024 MHz
LEGATO_RETURN_SEMITONES = 0.25

#: ...and it must be clear of the key-on that started the note, so the
#: driver's own setup writes are not read as a second note.
LEGATO_MIN_LEAD_TICKS = 2_048                 # 2 ms

#: ...and it must be a musically possible interval. Axelay's driver rewrites
#: PITCH every tick (250 Hz, so every 4 ms) with values oscillating between
#: about 45 and 1790 -- a factor of forty, plus or minus SIXTY semitones. That
#: is ring modulation or a metallic texture, not a note succession, and the
#: return test misses it because the oscillation comes back to NEAR but not
#: within LEGATO_RETURN_SEMITONES of where it started (1760 against 1790 is
#: 0.29 st). A ceiling catches it cleanly: it halves Axelay's rate, 83% to
#: 40%, and moves no other game by more than 1.5 points. Two octaves is
#: deliberately generous -- melodic leaps past it essentially do not occur.
LEGATO_MAX_SEMITONES = 24.0

#: ...and it must be clear of the note's END, because a driver sets up the
#: NEXT note's pitch before keying it on, and that write lands inside the
#: current note. Measured, the patch-before-KON lead runs 400-4,281 clocks,
#: and without this floor Mega Man X reported 585 steps whose median
#: observation was 3,536 clocks -- 3 ms before the note ended, which is a
#: setup write and not a note. The floor is ~4x the longest observed lead,
#: and ~7x below the 107-116 ms median note duration, so it excludes setup
#: without reaching real steps:
#:
#:     floor      mmx-06   so-37   ff6-205   top-110
#:         0         585     160        20         3
#:     4,096         260     160        20         3
#:    16,384          51     160        20         3   <- adopted
#:    32,768          34     160        20         0
LEGATO_MIN_TRAILING_TICKS = 16_384            # 16 ms

#: PITCH spans two registers, so one logical change is two writes with a
#: half-updated value between them. Measured, the pair is a fixed 10-25 clocks
#: apart depending on the driver (median, p95 and max are all equal, so it is
#: always the same instruction sequence). 256 is an order of magnitude above
#: that and four orders below any musical interval.
LEGATO_COALESCE_TICKS = 256


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
    """The registers in force for one voice.

    SEEDED FROM THE SPC SNAPSHOT, not from zero. An SPC is a dump of a running
    system, so the DSP register block already holds the voice parameters the
    driver set up before the dump, and a driver has no reason to rewrite a
    register whose value is already correct. Many do not: Super Mario World's
    "Athletic" writes only KON, KOFF, VOL and PITCH for its entire length,
    never SRCN, ADSR1, ADSR2 or GAIN.

    Starting these at zero therefore reported a default for every register the
    driver happened not to touch, and it was wrong for 10.8% of the corpus's
    notes on SRCN alone. "Athletic" has a snapshot SRCN of [10,10,10,10,11,8,
    2,8] and all 1,164 of its notes were recorded as sample 0 -- each pitched
    against the wrong BRR sample, and assigned the wrong timbre class. Super
    Turrican was affected on 100% of its notes, Dragon Quest 5 on 41%, Breath
    of Fire 2 on 37%. It also made 540 tracks report ADSR disabled with a zero
    GAIN, i.e. a silent envelope, when their snapshots have ADSR enabled on
    every voice.
    """

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


def seed_states(dsp: bytes | None = None) -> list[VoiceState]:
    """The eight voice states as the SPC snapshot left them.

    `dsp` is the 128-byte DSP register block (offset 0x10100 in an SPC file).
    Voice *v* occupies the 0x10 bytes at `v * 0x10`, with the same low-nibble
    layout as a live write, so the seeding reuses the same offsets.

    Passing None gives the old all-zero behaviour, which is correct only for a
    synthetic log that has no snapshot behind it.
    """
    states = [VoiceState() for _ in range(VOICE_COUNT)]
    if not dsp:
        return states
    for voice, slot in enumerate(states):
        base = voice * 0x10
        if base + 0x08 > len(dsp):
            break
        slot.voll = dsp[base + V_VOLL]
        slot.volr = dsp[base + V_VOLR]
        slot.pitchl = dsp[base + V_PITCHL]
        slot.pitchh = dsp[base + V_PITCHH]
        slot.srcn = dsp[base + V_SRCN]
        slot.adsr1 = dsp[base + V_ADSR1]
        slot.adsr2 = dsp[base + V_ADSR2]
        slot.gain = dsp[base + V_GAIN]
    return states


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

    #: Index of this note within its track, so a legato step can name its
    #: parent. Assigned in key-on order and stable for a given write log.
    note_id: int = -1

    @property
    def duration(self) -> int | None:
        return None if self.end is None else self.end - self.start

    def seconds(self) -> tuple[float, float | None]:
        end = None if self.end is None else self.end / CLOCK_RATE
        return self.start / CLOCK_RATE, end

    def to_dict(self) -> dict[str, Any]:
        start_s, end_s = self.seconds()
        return {
            # Published so `LegatoStep.parent_note_id` resolves. Without it
            # the link between a step and its parent -- and therefore the
            # step's sample and envelope -- is unrecoverable from the record.
            "note_id": self.note_id,
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
    #: Inferred note successions, as an INDEPENDENT table. `notes` stays bound
    #: strictly to KON edges; these hang off it by `parent_note_id`. A melodic
    #: density question wants both, a voice-allocation or envelope question
    #: wants `notes` alone -- see `_detect_legato_steps`.
    legato_steps: list[LegatoStep] = field(default_factory=list)
    #: Register writes the extractor did not interpret, by name, for honesty
    #: about coverage rather than silent omission.
    unhandled: dict[str, int] = field(default_factory=dict)
    n_writes: int = 0
    last_time: int = 0
    #: KON writes seen, and those that actually set a voice bit. Drivers
    #: re-upload the whole register block every tick -- the AKAO driver writes
    #: KON ~205 times a second -- so a raw write count says nothing about
    #: whether a note started. Final Fantasy VI's ambient tracks write KON
    #: 12,307 times in 60 s with mask 0 every single time.
    n_kon_writes: int = 0
    n_kon_effective: int = 0

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
            "n_kon_writes": self.n_kon_writes,
            "n_kon_effective": self.n_kon_effective,
            "n_noise_notes": sum(1 for n in self.notes if n.noise),
            "n_pitch_modulated_notes": sum(
                1 for n in self.notes if n.pitch_modulated
            ),
            # Inferred, and counted separately so no aggregate silently mixes
            # them with key-on notes. Driver-dependent: 0% for Chrono Trigger
            # and Secret of Mana, 21% for Star Ocean.
            "n_legato_steps": len(self.legato_steps),
            "unhandled_writes": dict(sorted(self.unhandled.items())),
        }


def read_log(path: Path) -> Iterator[dict[str, Any]]:
    """DSP register writes from a dump, and only those.

    The dump carries a second record type: `kind == "dir"`, the sample
    directory whenever it changes, which `snesmdb.dirtimeline` reads to
    resolve a sample at key-on time. Those records have no `addr`, so every
    consumer of the write stream has to skip them -- and when they were first
    emitted this function did not, which made the extractor raise KeyError on
    the first directory snapshot of every track.
    """
    with Path(path).open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if "addr" in record:
                yield record


def _semitones(from_pitch: int, to_pitch: int) -> float:
    """Interval between two PITCH values.

    PITCH is a resample ratio, so the interval is just the log of the ratio --
    no reference frequency is needed and the sample's own f0 cancels out.
    """
    return 12.0 * math.log2(to_pitch / from_pitch)


def _legato_steps(
    timeline: list[tuple[int, int, int, int]], start: int, end: int
) -> list[tuple[int, float, int, int, int, int, int, int]]:
    """Qualifying pitch steps strictly inside one note.

    Returns `(time, semitones, run_length, voll, volr, from_pitch, to_pitch,
    observed_ticks)` per step. `timeline` is this voice's `(time, pitch, voll, volr)` history,
    ascending.
    """
    opens = start + LEGATO_MIN_LEAD_TICKS
    window = [row for row in timeline if opens < row[0] < end and row[1] > 0]
    if not window:
        return []

    # The baseline is the pitch IN FORCE when the note began, which is
    # normally written before the key-on and so sits outside the window.
    # Without it a note that is stepped exactly once has nothing to be
    # compared against and the step is missed.
    baseline = next(
        (row for row in reversed(timeline) if row[0] <= opens and row[1] > 0),
        None,
    )
    if baseline is not None:
        window = [(start, baseline[1], baseline[2], baseline[3])] + window
    if len(window) < 2:
        return []

    # PITCH is two registers, so one logical pitch change arrives as two
    # writes and the state between them is a half-updated value -- typically a
    # wild interval that would read as a step. The pair is always adjacent
    # instructions, measured at a fixed 10-25 clocks apart per driver, so
    # entries inside LEGATO_COALESCE_TICKS collapse to the last of the run.
    inside: list[tuple[int, int, int, int]] = []
    for row in window:
        if inside and row[0] - inside[-1][0] <= LEGATO_COALESCE_TICKS:
            inside[-1] = row
        else:
            inside.append(row)
    if len(inside) < 2:
        return []

    # Every jump over the threshold, with the pitch it came from.
    jumps: list[tuple[int, float, int, int, int, int, int, int]] = []
    for index in range(1, len(inside)):
        previous, current = inside[index - 1], inside[index]
        interval = _semitones(previous[1], current[1])
        if not LEGATO_MIN_SEMITONES < abs(interval) <= LEGATO_MAX_SEMITONES:
            continue
        # A write in the note's last moments is the next note's setup, not a
        # step in this one. See LEGATO_MIN_TRAILING_TICKS.
        if end - current[0] < LEGATO_MIN_TRAILING_TICKS:
            continue
        # A vibrato cycle comes back; a new note stays. The window is the
        # REST OF THE NOTE, capped at LEGATO_RETURN_WINDOW_TICKS.
        #
        # It was briefly a fixed 100 ms, which was wrong because that is the
        # same order as a note: median note duration is 116 ms for Mega Man X
        # and 107 ms for Star Ocean, so requiring 100 ms of room after a step
        # rejected 94% of real steps by construction. A window longer than the
        # thing it measures cannot measure it.
        horizon = min(current[0] + LEGATO_RETURN_WINDOW_TICKS, end)
        returned = any(
            abs(_semitones(previous[1], later[1])) < LEGATO_RETURN_SEMITONES
            for later in inside[index + 1:]
            if later[0] <= horizon
        )
        if returned:
            continue
        # How long the step could actually be observed for. Recorded rather
        # than thresholded: a step with little room is a weaker claim, and the
        # consumer filters on it. That is the point of a separate table.
        observed = end - current[0]
        jumps.append(
            (current[0], interval, 0, current[2], current[3],
             previous[1], current[1], observed)
        )

    # Run length: how many same-sign qualifying jumps this one sits in. A run
    # of 2-3 is a scale or arpeggio, so this is recorded as evidence and is
    # deliberately NOT used to reject -- a portamento is built from increments
    # under LEGATO_MIN_SEMITONES and so never reaches this point at all.
    out: list[tuple[int, float, int, int, int, int, int, int]] = []
    position = 0
    while position < len(jumps):
        sign = jumps[position][1] > 0
        run_end = position
        while run_end + 1 < len(jumps) and (jumps[run_end + 1][1] > 0) == sign:
            run_end += 1
        length = run_end - position + 1
        for item in jumps[position:run_end + 1]:
            out.append(
                (item[0], item[1], length, item[3], item[4], item[5],
                 item[6], item[7])
            )
        position = run_end + 1
    return out


@dataclass
class LegatoStep:
    """An inferred note succession: a pitch step on an already-sounding voice.

    Deliberately a separate record type from `Note`. A note is observed at a
    hardware edge; a step is inferred from a register write the DSP cannot
    distinguish from a bend, and the two should not be mistaken for each other
    by anything downstream.
    """

    time: int
    voice: int
    #: `Note.note_id` of the key-on note this step occurred inside.
    parent_note_id: int
    previous_pitch: int
    pitch: int
    semitones: float
    run_length: int
    volume_left: int
    volume_right: int
    #: How long the step could be observed before the parent note ended. A
    #: short observation is a weaker claim; it is recorded so a consumer can
    #: filter rather than being thresholded away here.
    observed_ticks: int = 0

    def seconds(self) -> float:
        return self.time / CLOCK_RATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "time_sec": self.time / CLOCK_RATE,
            "voice": self.voice,
            "parent_note_id": self.parent_note_id,
            "previous_pitch": self.previous_pitch,
            "pitch": self.pitch,
            "semitones": self.semitones,
            "run_length": self.run_length,
            "volume_left": self.volume_left,
            "volume_right": self.volume_right,
            "observed_ticks": self.observed_ticks,
            "observed_ms": round(self.observed_ticks / CLOCK_RATE * 1000, 2),
        }


def _detect_legato_steps(
    notes: list[Note],
    timelines: dict[int, list[tuple[int, int, int, int]]],
    last_time: int,
) -> list[LegatoStep]:
    """Legato steps inside each key-on note, as an independent event table.

    NOTHING IN `notes` IS MODIFIED. The main note stream stays bound strictly
    to KON edges, so every entry in it remains traceable to a hardware edge
    with its attack velocity, SRCN and envelope intact. A step is an inferred
    event hanging off its parent by `parent_note_id`, which is what keeps the
    chain of custody for the timbre class: a step does not re-key, so it
    inherits its parent's sample and envelope by construction.

    The split matters for bias rather than for tidiness. Counting steps as
    notes would inflate Mega Man X by 114% and Chrono Trigger by 0%, so a
    melodic-density question wants `notes + steps` while a voice-allocation or
    envelope question wants `notes` alone. Merging them would make the second
    question unanswerable.
    """
    if not timelines:
        return []
    steps: list[LegatoStep] = []
    for note in notes:
        timeline = timelines.get(note.voice)
        if not timeline:
            continue
        # An unterminated note is bounded by the log, not by a key-off.
        end = note.end if note.end is not None else last_time + 1
        for (time, interval, run_length, voll, volr, before, after,
             observed) in _legato_steps(timeline, note.start, end):
            steps.append(
                LegatoStep(
                    time=time,
                    voice=note.voice,
                    parent_note_id=note.note_id,
                    previous_pitch=before,
                    pitch=after,
                    semitones=round(interval, 4),
                    run_length=run_length,
                    volume_left=_signed8(voll),
                    volume_right=_signed8(volr),
                    observed_ticks=observed,
                )
            )
    steps.sort(key=lambda s: (s.time, s.voice))
    return steps


def extract(
    writes: Iterator[dict[str, Any]], initial_dsp: bytes | None = None
) -> Extraction:
    """Replay a write log and recover the notes it describes.

    `initial_dsp` is the SPC's 128-byte DSP register block. Pass it: without
    it, any voice register the driver never rewrites is reported as zero
    rather than as the value actually in force. See `VoiceState`.
    """
    state = seed_states(initial_dsp)
    live: dict[int, Note] = {}
    out = Extraction()
    noise_mask = pmon_mask = 0
    # Per-voice (time, pitch, voll, volr) history, for legato detection after
    # the replay. Appended only when one of those four registers moves, so it
    # is far shorter than the write log.
    timelines: dict[int, list[tuple[int, int, int, int]]] = {}

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
                if low in (V_VOLL, V_VOLR, V_PITCHL, V_PITCHH):
                    timelines.setdefault(voice, []).append(
                        (time, slot.pitch, slot.voll, slot.volr)
                    )
            continue

        if addr == R_NON:
            noise_mask = data
        elif addr == R_PMON:
            pmon_mask = data
        elif addr == R_KON:
            out.n_kon_writes += 1
            if data:
                out.n_kon_effective += 1
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
                note.note_id = len(out.notes)
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
    # Inferred, and kept out of `out.notes` entirely. Runs after the sort so
    # parent ids are final; it reads `notes` and never writes to them.
    out.legato_steps = _detect_legato_steps(out.notes, timelines, out.last_time)
    return out
