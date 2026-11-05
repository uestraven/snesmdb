"""Structural checks on an extraction.

These replaced an audio-onset "validation gate" that scored each track by
matching extracted note starts against amplitude onsets in the rendered WAV.
That gate scored 1.0000 on the synthetic fixture and 0.151 on real Final
Fantasy VI, and the real number was the honest one: in sustained polyphonic
audio the detector fires on envelope and tremolo fluctuation rather than note
attacks, finding 80 onsets where a track has 19 note-ons. The fixture --
isolated notes with silence between them -- was simply too easy, and the
difference was a property of the measurement, not of the corpus.

What is here instead needs no inference and no tunable threshold. Each check
asks a question with one defensible answer, reports the number behind it, and
either passes or fails. Nothing produces a score, because a score invites
tuning until it looks acceptable.

Deliberately NOT checked: whether recovered PITCH values are correct. Nothing
available at this milestone can answer that -- it needs each BRR sample's own
fundamental frequency (milestone 3). Claiming otherwise would be the same
mistake as the onset gate. The real comparison arrives when there is a score
to re-render and diff against the reference, at which point the reference is
the per-track write log this pipeline already keeps.
"""

from __future__ import annotations

import array
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from snesmdb.voices import CLOCK_RATE, Extraction


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "value": self.value,
            "detail": self.detail,
        }


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> list[str]:
        return [c.name for c in self.checks if not c.passed]

    @property
    def ok(self) -> bool:
        return not self.failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failed": self.failed,
            "checks": [c.to_dict() for c in self.checks],
        }


def audio_peak(path: str | Path) -> int:
    """Peak absolute sample of a 16-bit WAV. Cheap, and no onset detection."""
    with wave.open(str(path)) as handle:
        if handle.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit audio")
        samples = array.array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
    return max((abs(s) for s in samples), default=0)


def run(
    extraction: Extraction,
    *,
    render_seconds: float,
    peak: int | None = None,
) -> Report:
    """Check an extraction for the failures that are knowable now."""
    report = Report()
    notes = extraction.notes
    summary = extraction.summary()

    # Distinguish "the extractor found nothing" from "nothing was keyed on".
    # An SPC is a SNAPSHOT of a running system, so a sustained or ambient
    # track can have all eight voices already sounding and never be re-keyed.
    # Three of Final Fantasy VI's 82 tracks are exactly this: KON is written
    # 12,307 times in 60 seconds, with a zero mask every time. The notes model
    # cannot represent such a track, and that is a property of the track, not
    # a bug -- but it must be visible rather than silently yielding an empty
    # record.
    keyed = summary["n_kon_effective"]
    report.checks.append(
        Check(
            "notes_present",
            bool(notes),
            "no notes were extracted. n_kon_effective tells you which case "
            "this is: zero means nothing was ever keyed on in this window "
            "(a drone already sounding at the snapshot), non-zero means "
            "key-ons were seen and the extractor failed to pair them",
            {"n_notes": len(notes),
             "n_kon_writes": summary["n_kon_writes"],
             "n_kon_effective": keyed},
        )
    )

    report.checks.append(
        Check(
            "no_unhandled_registers",
            not extraction.unhandled,
            "a DSP register this extractor does not model was written, so "
            "something about the track is not represented",
            summary["unhandled_writes"],
        )
    )

    # Some notes legitimately ring past the end of a fixed-length render. ALL
    # of them doing so means no key-off was ever seen, which is a different
    # thing: either the driver releases notes some other way or the log is
    # being misread.
    unfinished = summary["n_unfinished_notes"]
    report.checks.append(
        Check(
            "some_notes_completed",
            bool(notes) and unfinished < len(notes),
            "every note still sounding at the end means no key-off was ever "
            "observed, so no duration in this track is real",
            f"{unfinished}/{len(notes)}",
        )
    )

    bad_duration = [
        n for n in notes if n.duration is not None and n.duration <= 0
    ]
    report.checks.append(
        Check(
            "durations_positive",
            not bad_duration,
            "a note ending at or before it started means key-on and key-off "
            "were paired wrongly",
            len(bad_duration),
        )
    )

    limit = render_seconds * CLOCK_RATE
    outside = [n for n in notes if n.start > limit]
    report.checks.append(
        Check(
            "notes_within_render",
            not outside,
            "a note starting after the render ended means the timestamp base "
            "is wrong -- the symptom an earlier chunk-relative clock produced",
            len(outside),
        )
    )

    # A driver that halts early leaves the rest of the render silent, and the
    # extraction will look fine while covering a fraction of the track.
    covered = extraction.last_time / CLOCK_RATE if extraction.last_time else 0.0
    report.checks.append(
        Check(
            "writes_span_render",
            covered >= 0.5 * render_seconds,
            "DSP writes stopped well before the end of the render, so the "
            "driver halted or looped into silence and most of the window is "
            "not music",
            round(covered, 3),
        )
    )

    if peak is not None:
        # The one cross-check against the emulator that needs no inference:
        # notes extracted from a silent render cannot be right.
        report.checks.append(
            Check(
                "audio_not_silent",
                peak > 64,
                "the emulator produced (near-)silence while notes were "
                "extracted, so the two disagree about whether anything played",
                peak,
            )
        )

    return report
