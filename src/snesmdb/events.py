"""`snesmdb.events.v1` — the researcher-facing event table.

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

SCHEMA = "snesmdb.events.v1"

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
    }


def build(
    track_id: str,
    ok: bool,
    duration_sec: float,
    notes: Iterable[dict[str, Any]],
    sample_ids: dict[int, str],
    legato_steps: Iterable[dict[str, Any]] = (),
    attack_level: Any = None,
    sustain_level: Any = None,
) -> dict[str, Any]:
    """One track's event table.

    `sample_ids` maps SRCN to a content hash for THIS track, because an index
    does not name a fixed sample even within one game. `attack_level` and
    `sustain_level` are callables taking a note, so the amplitude derivation
    stays with the scoring code that owns it.
    """
    events: list[dict[str, Any]] = []
    for note in notes:
        enriched = dict(note)
        if attack_level is not None:
            enriched["_attack_level"] = attack_level(note)
        if sustain_level is not None:
            enriched["_sustain_level"] = sustain_level(note, enriched["_attack_level"])
        events.append(
            _event(enriched, sample_ids.get(int(note.get("srcn", -1)), ""))
        )

    by_id = {n.get("note_id"): n for n in notes} if not isinstance(notes, list) else {
        n.get("note_id"): n for n in notes
    }
    for step in legato_steps:
        parent = by_id.get(step.get("parent_note_id"))
        if parent is None:
            continue
        enriched = dict(parent)
        enriched["start_sec"] = step.get("time_sec", 0.0)
        enriched["end_sec"] = None
        if attack_level is not None:
            enriched["_attack_level"] = attack_level(step)
        if sustain_level is not None:
            enriched["_sustain_level"] = sustain_level(
                parent, enriched.get("_attack_level", 0)
            )
        events.append(
            _event(
                enriched,
                sample_ids.get(int(parent.get("srcn", -1)), ""),
                ORIGIN_LEGATO_STEP,
            )
        )

    events.sort(key=lambda e: (e["onset_sec"], e["voice"]))
    pitched = sum(1 for e in events if e["pitch_status"] == PITCH_ESTIMATED)
    return {
        "schema": SCHEMA,
        "track_id": track_id,
        "duration_sec": round(float(duration_sec), 4),
        "extraction_status": extraction_status(ok, len(events), pitched),
        "event_count": len(events),
        "pitched_event_count": pitched,
        "unpitched_event_count": len(events) - pitched,
        "events": events,
    }
