"""`snesmdb.events.v2` — the researcher-facing event table.

Everything else this project publishes is shaped by the hardware: scores
indexed by DSP voice and row, notes carrying `srcn` and register values, a row
clock that differs per track. That is correct and it is the wrong default. A
researcher studying harmony, rhythm or orchestration should be able to iterate
a track's notes without knowing the S-DSP has eight voices, that `srcn` is an
ARAM directory index, or that a row is one SPC700 timer tick.

So this is a flat list of events in seconds, and its job is to state plainly
what was observed, what was estimated, and what could not be recovered.

WHAT THE PREVIOUS ARTIFACT GOT WRONG, which this exists to fix:

  * `midi_note: null` with no reason. 405,288 events -- 22% of the corpus --
    arrived as an unexplained absence, so percussion, hardware noise, a
    pitch-modulated voice and a failed estimate were indistinguishable.
  * `srcn` as the only instrument identity. It is an ARAM index, it needs chip
    knowledge to interpret, and it is not stable across a game's tracks:
    Super Turrican's 8 indices resolve to 48 distinct samples across 12
    tracks. It invites a wrong join.
  * `timbre_class: -1` on every note, a field carrying nothing, 1.86 million
    times.
  * Events nested under eight DSP voices, so a flat iteration required
    knowing the hardware's voice count.

TWO DISTINCTIONS THE SCHEMA REFUSES TO BLUR.

`pitch_status` says `estimated`, never `measured`. A sample's fundamental is
estimated from its decoded BRR content by autocorrelation and loop analysis;
calling that a measurement would claim a certainty the pipeline does not
establish. `pitch_confidence` stays a separate field, because an estimate with
high confidence is still an estimate.

`extraction_status` is independent of `track_class`. An absence of recovered
pitch must never be readable as extraction failure or as musical silence, and
a musical label must never double as a data-quality indicator -- a sound
effect can contain recoverable pitch, and a music track can contain only
unpitched observations.
"""

from __future__ import annotations

from typing import Any, Iterable

SCHEMA = "snesmdb.events.v2"

#: v2 adds `game`, `game_slug` and `track_class` to the header. The change is
#: PURELY ADDITIVE -- nothing was renamed, moved or removed, so a v1 reader
#: works unchanged -- and the version is still bumped, because the version
#: exists so a consumer can tell which fields to expect. Two trees both
#: claiming `v1` while carrying different fields is precisely the silent
#: incompatibility that versioning is supposed to prevent.
#:
#: The reason for the addition is a defect report. `game` and `track_class`
#: lived in `index.json` and NOWHERE else, while the documentation instructs,
#: emphatically, that a melodic study should filter on `track_class`. An
#: evaluator who received a truncated copy of `index.json` lost both fields for
#: 44% of tracks and found `track_class` unrecoverable from any other
#: published file -- leaving only `extraction_status`, which is the proxy the
#: documentation explicitly forbids. A single file being the sole home of a
#: field researchers are told to filter on is a single point of failure, so the
#: filter fields now travel with the data they describe.
PREVIOUS_SCHEMA = "snesmdb.events.v1"

#: Why an event has, or has not, a pitch.
PITCH_ESTIMATED = "estimated"
PITCH_NOISE = "noise"
PITCH_MODULATED = "pitch_modulated"
PITCH_UNRECOVERABLE = "unrecoverable"
PITCH_STATES = (
    PITCH_ESTIMATED, PITCH_NOISE, PITCH_MODULATED, PITCH_UNRECOVERABLE,
)

#: Whether extraction succeeded, and separately whether it found anything.
STATUS_PITCHED = "complete_with_pitched_events"
STATUS_UNPITCHED_ONLY = "complete_unpitched_only"
STATUS_NO_EVENTS = "complete_no_events"
STATUS_INCOMPLETE = "incomplete"
EXTRACTION_STATES = (
    STATUS_PITCHED, STATUS_UNPITCHED_ONLY, STATUS_NO_EVENTS, STATUS_INCOMPLETE,
)

#: How an event was established. `key_on` was observed at a hardware edge;
#: `legato_step` was inferred from a pitch write on an already-sounding voice,
#: which the DSP cannot distinguish from a bend. Published together, labelled,
#: because silently excluding a whole category of event is how MIDI came to
#: drop 405,288 unpitched notes.
ORIGIN_KEY_ON = "key_on"
ORIGIN_LEGATO_STEP = "legato_step"

#: AN EVENT IS NOT NECESSARILY A NOTE ATTACK, and conflating the two distorts
#: rhythmic analysis. `key_on` is a new triggered note, observed at a hardware
#: edge. `legato_step` is a pitch change within a voice that was already
#: sounding, inferred from a PITCH write with no key-on. How to read the table
#: depends on the question:
#:
#:   how many note attacks?          count origin == key_on
#:   how many pitch events?          count everything
#:   how many voices sound at once?  count active voices, not event rows
#:   how often does pitch change?    count everything
#:   how long does a note sustain?   follow parent_event_id across steps
#:
#: `parent_event_id` makes the last two answerable without hardware knowledge:
#: a legato step names the key-on event it belongs to, so a continuous phrase
#: can be reassembled by grouping on it.


def pitch_status(note: dict[str, Any]) -> str:
    """Why this event has the pitch it has, or none.

    RESOLUTION ORDER MATTERS and is documented rather than incidental. Noise
    is checked first: when NON is set the DSP plays noise and the PITCH
    register describes nothing, so no amount of estimation applies. Pitch
    modulation is next: PITCH is real but is being modulated by the previous
    voice, so it does not describe what sounded. Only then does the question
    of whether a fundamental was recoverable arise.
    """
    if note.get("noise"):
        return PITCH_NOISE
    if note.get("pitch_modulated"):
        return PITCH_MODULATED
    if note.get("midi_note") is not None:
        return PITCH_ESTIMATED
    return PITCH_UNRECOVERABLE


def extraction_status(
    ok: bool, n_events: int, n_pitched: int
) -> str:
    """The four states, kept apart from anything musical.

    `incomplete` is reserved for extraction actually failing. A track that
    extracted perfectly and contains only unpitched percussion reports
    `complete_unpitched_only`, which is the distinction the previous artifact
    could not express -- 73 tracks recovered no pitch and were
    indistinguishable from failures.
    """
    if not ok:
        return STATUS_INCOMPLETE
    if n_events == 0:
        return STATUS_NO_EVENTS
    if n_pitched == 0:
        return STATUS_UNPITCHED_ONLY
    return STATUS_PITCHED


def _event(
    note: dict[str, Any],
    sample_id: str,
    origin: str = ORIGIN_KEY_ON,
    event_id: int = 0,
    parent_event_id: int | None = None,
) -> dict[str, Any]:
    status = pitch_status(note)
    start = float(note.get("start_sec") or 0.0)
    end = note.get("end_sec")
    return {
        "onset_sec": round(start, 6),
        # None when the note was still sounding when the render window
        # ended, rather than an invented length.
        "duration_sec": (
            round(float(end) - start, 6) if end is not None else None
        ),
        # Kept because concurrency is a musical question -- how many voices
        # sound at once -- not because the researcher needs the hardware.
        "voice": int(note.get("voice", 0)),
        "pitch_status": status,
        "midi_note": (
            round(float(note["midi_note"]), 4)
            if status == PITCH_ESTIMATED else None
        ),
        "pitch_confidence": note.get("pitch_confidence"),
        # Content identity of the decoded BRR block. Identifies the SOUND
        # SOURCE reproducibly; it is NOT an instrument label, and carries no
        # claim that a sample performs a consistent musical role.
        "sample_id": sample_id,
        # Register-derived amplitude controls at attack and sustain. NOT
        # measurements of perceived loudness, acoustic intensity, or
        # standardised MIDI velocity.
        "attack_level": int(note.get("_attack_level", 0)),
        "sustain_level": int(note.get("_sustain_level", 0)),
        "origin": origin,
        "event_id": event_id,
        # For a key-on, itself. For a legato step, the key-on it continues --
        # so grouping on this field reassembles a phrase that the driver
        # expressed as one sounding voice with several pitches.
        "parent_event_id": (
            event_id if parent_event_id is None else parent_event_id
        ),
    }


def game_slug(track_id: str) -> str:
    """The game's short identifier, taken from the track id.

    Published rather than left to be inferred. The slugs are not guessable
    from the game names -- `mo2` is Earthbound (Mother 2), `sd2` is Secret of
    Mana (Seiken Densetsu 2), `ed2` is Lufia 2, `dkq` is Donkey Kong Country 2
    -- and an evaluator who needed the mapping had to reconstruct it by
    matching per-game track counts, then break a tie between two 66-track
    games from their clock rates. That is reverse engineering of something
    this project simply knows.
    """
    return track_id.split(":")[0].split("-")[0]


def build(
    track_id: str,
    ok: bool,
    duration_sec: float,
    notes: list[dict[str, Any]],
    sample_ids: dict[int, str],
    legato_steps: Iterable[dict[str, Any]] = (),
    attack_level: Any = None,
    sustain_level: Any = None,
    game: str | None = None,
    track_class: str | None = None,
) -> dict[str, Any]:
    """One track's event table.

    `sample_ids` maps SRCN to a content hash for THIS track, because an index
    does not name a fixed sample even within one game. `attack_level` and
    `sustain_level` are callables, so the amplitude derivation stays with the
    scoring code that owns it.

    `game` and `track_class` are carried here as well as in the index, so that
    the two fields a researcher is told to filter on survive the loss of any
    single file. See the note on `SCHEMA`.
    """
    def levels(note: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(note)
        attack = attack_level(note) if attack_level is not None else 0
        enriched["_attack_level"] = attack
        enriched["_sustain_level"] = (
            sustain_level(note, attack) if sustain_level is not None else attack
        )
        return enriched

    events: list[dict[str, Any]] = []
    # event_id is the note_id where there is one, so the id is stable against
    # the source record rather than an artefact of iteration order.
    by_note_id: dict[Any, int] = {}
    for index, note in enumerate(notes):
        event_id = int(note.get("note_id", index))
        by_note_id[note.get("note_id", index)] = event_id
        events.append(_event(
            levels(note),
            sample_ids.get(int(note.get("srcn", -1)), ""),
            ORIGIN_KEY_ON,
            event_id,
        ))

    parents = {n.get("note_id"): n for n in notes}
    for step in legato_steps:
        parent = parents.get(step.get("parent_note_id"))
        if parent is None:
            continue
        enriched = levels(step if attack_level is not None else parent)
        enriched["noise"] = parent.get("noise")
        enriched["pitch_modulated"] = parent.get("pitch_modulated")
        enriched["pitch_confidence"] = parent.get("pitch_confidence")
        # A legato step's pitch is the step's own; the sample and envelope are
        # the parent's, since a step does not re-key.
        enriched["midi_note"] = step.get("midi_note", parent.get("midi_note"))
        enriched["start_sec"] = step.get("time_sec", 0.0)
        enriched["end_sec"] = None
        events.append(_event(
            enriched,
            sample_ids.get(int(parent.get("srcn", -1)), ""),
            ORIGIN_LEGATO_STEP,
            int(step.get("parent_note_id", -1)),
            by_note_id.get(step.get("parent_note_id")),
        ))

    events.sort(key=lambda e: (e["onset_sec"], e["voice"]))
    pitched = sum(1 for e in events if e["pitch_status"] == PITCH_ESTIMATED)
    attacks = sum(1 for e in events if e["origin"] == ORIGIN_KEY_ON)
    return {
        "schema": SCHEMA,
        "track_id": track_id,
        # Denormalised deliberately. These describe the track, not the events,
        # and duplicating them is the price of not having a single file whose
        # loss takes the filter fields with it.
        "game": game,
        "game_slug": game_slug(track_id),
        "track_class": track_class,
        "duration_sec": round(float(duration_sec), 4),
        "extraction_status": extraction_status(ok, len(events), pitched),
        "event_count": len(events),
        "pitched_event_count": pitched,
        "unpitched_event_count": len(events) - pitched,
        # An event is not necessarily an attack. Published separately so a
        # rhythmic analysis does not have to filter to get the right number.
        "attack_count": attacks,
        "legato_step_count": len(events) - attacks,
        "events": events,
    }
