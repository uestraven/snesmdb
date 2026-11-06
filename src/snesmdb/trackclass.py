"""Mechanical per-track classification: music, jingle, effect or drone.

A commercial SPC set is not a song list. It carries fanfares, logos, stingers,
puzzle cues and room ambiences alongside the music, and those pollute any
aggregate computed over the whole corpus -- the performance conventions, the
timbre codebook, the grid statistics.

The obvious response is to curate by ear or by title. This is deliberately not
that. NES-MDB is comparable because its inclusion rule is mechanical; a list
curated by listening is a subjective filter nobody else can reproduce, and it
would be the only step in this pipeline that is neither driver-agnostic nor
data-derived. It also destroys the denominator: "29% of a commercial set does
not lie on a single tempo grid" is a finding, and deleting the tracks makes it
unmeasurable.

So nothing is dropped. Every track gets a label computed from measurements the
pipeline already produces, and consumers filter. Aggregates can then be
reported twice -- over everything, and over `music` only -- which also measures
how much the non-music was shifting them.

THRESHOLDS COME FROM THE CORPUS, not from taste. Note density across 1,316
tracks sits at 12-17 notes/second for every duration bucket above two seconds,
and collapses to 6.5/s only below two seconds. So duration alone separates
nothing: a one-second track carrying 23 notes is a fanfare, and a one-second
track carrying 3 is a door chime. The note COUNT and the key-on mechanism are
what distinguish them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Fewer notes than this cannot carry a phrase, whatever the duration. The
#: corpus has 15 tracks under five notes -- "K. Rool's Letter", "Victory",
#: "The Sphinx's Puzzle 1-5" -- against a median of 29 notes even in the
#: two-to-four-second bucket.
MIN_NOTES_FOR_MUSIC = 10

#: Short-form music: fanfares, logos and stingers. "Level Up", "Stage Clear",
#: "Konami Logo". Musically real and usually well-formed -- Donkey Kong
#: Country's one-second "Extra Life Balloon" extracted 23 notes cleanly -- but
#: not a song, and averaging them in with songs skews every duration-sensitive
#: measure.
JINGLE_SECONDS = 10.0

#: Below this, a track that lasts a while is sounding without being played:
#: ambience, a held chord, a sound bed. Separate from `drone` below, which is
#: an extraction fact rather than a musical one.
MIN_NOTES_PER_SECOND = 1.0

CLASSES = ("music", "jingle", "effect", "drone")


@dataclass
class TrackClass:
    label: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"track_class": self.label, "track_class_reason": self.reason}


def classify(row: dict[str, Any]) -> TrackClass:
    """Label one manifest row.

    Order matters: `drone` is tested first because it is a statement about
    what the extraction could observe, not about the music, and it applies at
    any length -- Final Fantasy VI's "Time Vortex" is 238 seconds long with
    zero notes.
    """
    summary = row.get("summary") or {}
    notes = int(summary.get("n_notes") or 0)
    effective = int(summary.get("n_kon_effective") or 0)
    seconds = float(row.get("render_seconds") or 0.0)

    if effective == 0:
        return TrackClass(
            "drone",
            "no key-on took effect in the render window: an SPC is a snapshot "
            "of a running system, so this track was already sounding and was "
            "never re-keyed. The note model cannot represent it, and that is "
            "a property of the track rather than a failure",
        )

    if notes < MIN_NOTES_FOR_MUSIC:
        return TrackClass(
            "effect",
            f"{notes} notes is fewer than the {MIN_NOTES_FOR_MUSIC} needed to "
            f"carry a phrase, at any duration",
        )

    if seconds and notes / seconds < MIN_NOTES_PER_SECOND:
        return TrackClass(
            "effect",
            f"{notes / seconds:.2f} notes per second is below "
            f"{MIN_NOTES_PER_SECOND}: sounding without being played",
        )

    if seconds <= JINGLE_SECONDS:
        return TrackClass(
            "jingle",
            f"{seconds:.1f}s is within the {JINGLE_SECONDS:.0f}s short-form "
            f"window, with {notes} notes: a fanfare, logo or stinger rather "
            f"than a song",
        )

    return TrackClass("music", "")


def census(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Counts per label, in a fixed order so a diff is readable."""
    counts = {name: 0 for name in CLASSES}
    for row in rows:
        label = row.get("track_class") or classify(row).label
        counts[label] = counts.get(label, 0) + 1
    return counts
