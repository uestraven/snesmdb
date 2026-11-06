"""The two timbre-free score formats.

Milestone 4. With pitch (3) and the grid (4) in hand, two of NES-MDB's score
formats are expressible without touching timbre -- which matters, because
timbre is milestone 5 and the research risk. These two do not wait on it.

**expressive** -- one row-indexed track per DSP voice, each cell a triple of
(note, velocity, timbre class). NES-MDB's `exprsco`. The timbre axis is the
codebook class from milestone 5, and it carries that milestone's limitation
with it: only the binary tonal/percussive split was shown to transfer across
games, so `timbre_validated` on the score says which claim the consumer may
rely on. Emitting the finer class anyway is the honest choice -- it is real
information about this corpus even where it is not cross-game meaning -- but it
must not be presented as an alphabet.

**separated** -- one row-indexed track per DSP voice, each cell a MIDI note
number or 0 for silence. Voice identity is kept. The SNES analogue of
NES-MDB's `sepsco`, with 8 generic voices in place of 4 fixed channels, and
that difference is the honest caveat: on the NES, track 0 is always pulse 1;
here voice 0 is whatever the driver assigned it to this frame. Voice ROLE is
milestone 5.

**blended** -- one row-indexed list of the distinct notes sounding, voice
identity discarded. NES-MDB's `blndsco`. Immune to the voice-assignment
problem above, which makes it the more comparable of the two today.

`separated` and `blended` carry no velocity, timbre or envelope: that is what
"timbre-free" means here, and it is a deliberate reduction, not an omission to fix later. The full
note list stays in the record for anything that needs more.

What cannot be represented is COUNTED rather than dropped quietly:

- an unpitched note (percussion, noise, or a sample whose fundamental was not
  recoverable) has no note number, so it cannot appear in a pitch-only score
- a note whose recovered pitch lands outside MIDI 1-127 is an octave error
  showing through, and writing it in would put a wrong number in the corpus

Both counts ride on the score, per track, so a consumer knows what fraction of
the music the score actually describes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import envelope as envelope_mod
from .grid import Grid

#: DSP voices. Fixed by the hardware.
N_VOICES = 8

#: The per-row channels of the expressive score, in order. `sustain` was added
#: after `velocity` was found to carry only VOL, which is half of the DSP's
#: amplitude -- see `expressive`. Appended rather than inserted, so a consumer
#: indexing 0..2 is unaffected.
CHANNELS = ("note", "velocity", "timbre_class", "sustain")

#: 0 is silence in both formats, so the usable note range is 1..127.
MIN_NOTE = 1
MAX_NOTE = 127


@dataclass
class Scores:
    """Both score formats for one track, plus what they could not say."""

    n_rows: int = 0
    #: separated[voice][row] -> note number, 0 for silence.
    separated: list[list[int]] = field(default_factory=list)
    #: blended[row] -> sorted distinct note numbers sounding.
    blended: list[list[int]] = field(default_factory=list)

    n_notes: int = 0
    n_notes_represented: int = 0
    n_notes_unpitched: int = 0
    n_notes_out_of_range: int = 0
    #: A note shorter than one row that fell between two rows, snapped to the
    #: nearest. Reported because snapping moves an onset in time.
    n_notes_snapped: int = 0
    #: A note that could not be placed at all: it starts past the last row.
    n_notes_unplaced: int = 0
    #: Voice-rows where two notes collided and the later one won.
    n_cells_contested: int = 0

    n_cells_filled: int = 0
    n_rows_sounding: int = 0
    max_polyphony: int = 0

    @property
    def coverage(self) -> float:
        return self.n_notes_represented / self.n_notes if self.n_notes else 0.0

    @property
    def density(self) -> float:
        """Filled cells as a fraction of the separated grid."""
        total = self.n_rows * N_VOICES
        return self.n_cells_filled / total if total else 0.0

    def stats(self) -> dict[str, Any]:
        """Everything except the scores themselves, for the manifest."""
        return {
            "n_rows": self.n_rows,
            "n_notes": self.n_notes,
            "n_notes_represented": self.n_notes_represented,
            "n_notes_unpitched": self.n_notes_unpitched,
            "n_notes_out_of_range": self.n_notes_out_of_range,
            "n_notes_snapped": self.n_notes_snapped,
            "n_notes_unplaced": self.n_notes_unplaced,
            "n_cells_contested": self.n_cells_contested,
            "coverage": round(self.coverage, 4),
            "n_cells_filled": self.n_cells_filled,
            "separated_density": round(self.density, 5),
            "n_rows_sounding": self.n_rows_sounding,
            "rows_sounding_fraction": (
                round(self.n_rows_sounding / self.n_rows, 4) if self.n_rows else 0.0
            ),
            "max_polyphony": self.max_polyphony,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.stats(), "separated": self.separated, "blended": self.blended}


def _note_number(note: dict[str, Any]) -> int | None:
    midi = note.get("midi_note")
    if midi is None:
        return None
    value = int(round(float(midi)))
    if value < MIN_NOTE or value > MAX_NOTE:
        return 0  # in range of "pitched" but not of the format
    return value


def _clamped_ends(notes: Sequence[dict[str, Any]], last_tick: int) -> dict[int, int]:
    """End tick per note index, with each voice's notes made non-overlapping.

    A DSP voice sounds ONE note at a time, but a note still sounding when the
    render window closes has `end: null`, and reading that as "sounds to the
    end of the track" makes it overlap every later note on its own voice. In
    the blended score those overlaps accumulate, which is how an eight-voice
    machine comes to report a maximum polyphony of nine.

    So an unterminated note ends where its own voice's next note begins.
    """
    by_voice: dict[int, list[int]] = {}
    for index, note in enumerate(notes):
        by_voice.setdefault(int(note["voice"]), []).append(index)
    ends: dict[int, int] = {}
    for indices in by_voice.values():
        ordered = sorted(indices, key=lambda i: int(notes[i]["start"]))
        for position, index in enumerate(ordered):
            note = notes[index]
            end = note.get("end")
            next_start = (
                int(notes[ordered[position + 1]]["start"])
                if position + 1 < len(ordered)
                else last_tick
            )
            resolved = int(end) if end is not None else next_start
            ends[index] = max(int(note["start"]), min(resolved, next_start))
    return ends


def _velocity(note: dict[str, Any]) -> int:
    """Per-note loudness, 0..127, from the two signed side volumes.

    Magnitude only: a negative side volume inverts that side's phase, which a
    scalar velocity cannot express. The loss is recorded in the corpus
    limitations, and it is not small -- two games invert on over half their
    notes.
    """
    left = abs(int(note.get("volume_left") or 0))
    right = abs(int(note.get("volume_right") or 0))
    return max(0, min(127, int(round((left + right) / 2.0))))


def _sustain(note: dict[str, Any], velocity: int) -> int:
    """Sustained amplitude, 0..127, or -1 when the envelope cannot be read.

    `velocity` is the attack peak (VOL alone, which is correct because the
    ADSR attack always reaches full envelope). This scales it by where the
    envelope settles, so the two channels are in the same units.
    """
    env = envelope_mod.of_note(note)
    fraction = env.sustain_fraction
    if fraction is None:
        return -1
    return max(0, min(127, int(round(velocity * fraction))))


def expressive(
    notes: Sequence[dict[str, Any]],
    grid: Grid,
    timbre_of: dict[int, int] | None = None,
    render_ticks: int = 0,
) -> dict[str, Any]:
    """The third score format, per voice-row: note, velocity, timbre, sustain.

    `timbre_of` maps a sample index (SRCN) to its codebook class. Absent, the
    timbre axis is written as -1 throughout rather than as a plausible zero,
    so a missing codebook can never be mistaken for class 0.

    THE FOURTH CHANNEL IS SUSTAIN, and it exists because `velocity` is only
    half of loudness. The DSP computes `((sample * env) >> 11) * VOL >> 7`, so
    amplitude is env x VOL while `velocity` carries VOL alone. That is right
    for the ATTACK -- the ADSR attack phase drives env to full scale whatever
    the rate, so peak loudness really is VOL -- but it says nothing about where
    the note settles.

    It settles below full scale for **20.0% of the corpus, 372,538 notes**,
    down to silence at sustain level 0. Without this channel a staccato pluck
    and a held horn with equal VOL are identical in the score, which is wrong
    for one note in five.

    Channel 3 is the sustained amplitude on the same 0..127 scale as velocity,
    so the two compare directly: equal means the note holds, lower means it
    decays to that level. -1 marks an envelope whose level cannot be read from
    the key-on state -- a ramping GAIN mode, which no note in this corpus uses,
    so it should not appear. -1 rather than 0, because 0 means silent.
    """
    base = build(notes, grid, render_ticks)
    if not base.n_rows:
        return {
            "n_rows": 0, "voices": [], "timbre_classes_present": [],
            "timbre_validated": "tonal_vs_percussive_only",
            "channels": CHANNELS,
        }

    n_rows = base.n_rows
    voices: list[list[list[int]]] = [
        [[0, 0, -1, 0] for _ in range(n_rows)] for _ in range(N_VOICES)
    ]
    ends = _clamped_ends(notes, render_ticks or max(
        (int(n["end"]) for n in notes if n.get("end") is not None), default=0
    ))
    present: set[int] = set()
    for index, note in enumerate(notes):
        number = _note_number(note)
        if not number:
            continue
        voice = int(note["voice"])
        if not 0 <= voice < N_VOICES:
            continue
        velocity = _velocity(note)
        sustain = _sustain(note, velocity)
        klass = (timbre_of or {}).get(int(note["srcn"]), -1)
        present.add(klass)
        start = int(note["start"])
        first = max(0, -(-(start - grid.phase_ticks) // grid.period_ticks))
        last = -(-(ends[index] - grid.phase_ticks) // grid.period_ticks) - 1
        rows = range(int(first), min(int(last), n_rows - 1) + 1)
        if not rows:
            snapped = grid.row_of(start)
            if not 0 <= snapped < n_rows:
                continue
            rows = range(snapped, snapped + 1)
        for row in rows:
            voices[voice][row] = [number, velocity, klass, sustain]
    return {
        "n_rows": n_rows,
        "voices": voices,
        "timbre_classes_present": sorted(present),
        # The claim a consumer may rely on, carried with the data.
        "timbre_validated": "tonal_vs_percussive_only",
        # Named so a consumer never has to count positions, and so the
        # fourth channel's arrival is self-describing in old and new files.
        "channels": CHANNELS,
    }


def build(
    notes: Sequence[dict[str, Any]],
    grid: Grid,
    render_ticks: int = 0,
) -> Scores:
    """Render both score formats onto `grid`.

    A note occupies every row whose row time falls inside `[start, end)`, which
    is a sampling of sustain rather than a re-statement of the onset: a held
    note repeats its number down the column, exactly as a tracker displays it.
    A note too short to contain any row time is snapped to the nearest row so
    that a fast passage is not silently deleted, and the snap is counted.
    """
    scores = Scores(n_notes=len(notes))
    if not grid.found or not grid.period_ticks:
        return scores

    last_tick = render_ticks
    for note in notes:
        end = note.get("end")
        last_tick = max(last_tick, int(note["start"]), int(end) if end else 0)
    n_rows = min(grid.n_rows, int((last_tick - grid.phase_ticks) // grid.period_ticks) + 1)
    n_rows = max(n_rows, 0)
    scores.n_rows = n_rows
    if n_rows == 0:
        return scores

    separated = [[0] * n_rows for _ in range(N_VOICES)]
    ends = _clamped_ends(notes, last_tick)

    for index, note in enumerate(notes):
        number = _note_number(note)
        if number is None:
            scores.n_notes_unpitched += 1
            continue
        if number == 0:
            scores.n_notes_out_of_range += 1
            continue

        voice = int(note["voice"])
        if not 0 <= voice < N_VOICES:
            scores.n_notes_unplaced += 1
            continue

        start = int(note["start"])
        end_tick = ends[index]

        # Rows whose time lies in the HALF-OPEN interval [start, end). A note
        # ending exactly on a row boundary does not occupy that row: closing it
        # inclusively makes every note one row too long and makes a note that
        # hands its voice straight to the next one contend for a cell it does
        # not own.
        first = max(0, -(-(start - grid.phase_ticks) // grid.period_ticks))  # ceil
        last = -(-(end_tick - grid.phase_ticks) // grid.period_ticks) - 1  # ceil - 1
        rows = range(int(first), min(int(last), n_rows - 1) + 1)

        if not rows:
            # Shorter than a row, or landing between two. Snap to the nearest
            # row rather than losing the note.
            snapped = grid.row_of(start)
            if 0 <= snapped < n_rows:
                rows = range(snapped, snapped + 1)
                scores.n_notes_snapped += 1
            else:
                scores.n_notes_unplaced += 1
                continue

        placed = False
        for row in rows:
            if separated[voice][row] and separated[voice][row] != number:
                # Two notes claiming one voice-row. Physically a voice plays
                # one note at a time, so this is a note shorter than a row, or
                # two key-ons on the same tick. The later one wins and the
                # collision is counted, because the grid cannot show both.
                scores.n_cells_contested += 1
            separated[voice][row] = number
            placed = True
        if placed:
            scores.n_notes_represented += 1
        else:
            scores.n_notes_unplaced += 1

    # The blended score is derived FROM the separated grid rather than
    # accumulated alongside it. Built independently, a voice could contribute
    # two numbers to one row and the corpus would report a polyphony of nine on
    # eight-voice hardware. Deriving it makes that arithmetically impossible.
    blended: list[list[int]] = []
    for row in range(n_rows):
        blended.append(sorted({separated[v][row] for v in range(N_VOICES)} - {0}))

    scores.separated = separated
    scores.blended = blended
    scores.n_cells_filled = sum(1 for track in separated for cell in track if cell)
    scores.n_rows_sounding = sum(1 for row in blended if row)
    scores.max_polyphony = max((len(row) for row in blended), default=0)
    return scores
