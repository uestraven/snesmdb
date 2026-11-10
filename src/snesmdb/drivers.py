"""Game to audio-driver mapping — **curated external knowledge**.

EVERYTHING ELSE IN THIS PROJECT IS MEASURED. No extraction step identifies a
driver, nothing game-specific enters the pipeline, and "zero unhandled DSP
registers across every game in the corpus" is the claim the corpus exists to
support. This module is the one exception, and it is isolated in its own file
and labelled in its own output so that the boundary is visible rather than
implied.

COVERAGE IS PARTIAL. The map was written for the original 22-game cohort and
has not been extended since, so it labels 22 of the 50 published games. A
game with no entry publishes no driver fields; absence of a label is absence
of curated knowledge, not absence of a driver. Any analysis conditioned on
`driver` therefore runs on under half the corpus, and a per-driver aggregate
is drawn from the oldest cohort.

WHY IT EXISTS ANYWAY. `DATASET.md` conditions substantive advice on the
driver in four places -- which games are safe for interval-level work, the
per-driver envelope-strategy table, the clock-corroboration list, and the
warning to check the driver balance of a split -- and the distribution
published no mapping. An independent evaluator could not act on any of it
without supplying their own knowledge of who wrote each game's audio engine,
which is exactly what the dataset is supposed to make unnecessary. Advice
that cannot be acted on is worse than no advice, so either the mapping ships
or the advice goes; this is the mapping.

HOW TO READ IT. These attributions come from published documentation of SNES
audio engines and from the games' own credits. They are **not derived from the
SPC files**, they are **not verifiable from anything in the corpus**, and a
publisher reusing or replacing an engine between titles is normal. Treat a
driver label as a hypothesis worth testing against the data, never as a
measurement. `driver_confidence` says how firm each attribution is.

Anything computed from this field is conditional on it. The corpus itself
remains driver-agnostic.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "snesmdb.drivers.v1"

#: How firmly a title is attributed. `documented` means the engine is named in
#: published technical documentation of that game or its publisher's audio
#: system; `attributed` means it follows from the publisher and era and is
#: consistent with the family's known behaviour, but the specific title is not
#: individually documented.
CONFIDENCE_DOCUMENTED = "documented"
CONFIDENCE_ATTRIBUTED = "attributed"

#: slug -> (driver family, vendor, confidence)
#:
#: N-SPC is Nintendo's engine, written by Yuji Ohta and widely licensed, so it
#: appears under several publishers. AKAO is Square's, named for Minoru Akao.
DRIVERS: dict[str, tuple[str, str, str]] = {
    "smw":  ("N-SPC", "Nintendo", CONFIDENCE_DOCUMENTED),
    "loz3": ("N-SPC", "Nintendo", CONFIDENCE_DOCUMENTED),
    "sm":   ("N-SPC", "Nintendo", CONFIDENCE_DOCUMENTED),
    "kss":  ("N-SPC", "HAL", CONFIDENCE_DOCUMENTED),
    "mo2":  ("N-SPC", "HAL", CONFIDENCE_DOCUMENTED),
    "ff6":  ("AKAO", "Square", CONFIDENCE_DOCUMENTED),
    "ct":   ("AKAO", "Square", CONFIDENCE_DOCUMENTED),
    "sd2":  ("AKAO", "Square", CONFIDENCE_DOCUMENTED),
    "so":   ("AKAO-derived", "tri-Ace", CONFIDENCE_ATTRIBUTED),
    "top":  ("AKAO-derived", "Namco/Wolf Team", CONFIDENCE_ATTRIBUTED),
    "mmx":  ("Capcom", "Capcom", CONFIDENCE_DOCUMENTED),
    "br":   ("Konami", "Konami", CONFIDENCE_DOCUMENTED),
    "scv4": ("Konami", "Konami", CONFIDENCE_DOCUMENTED),
    "dkc":  ("Rare", "Rare", CONFIDENCE_DOCUMENTED),
    "dkq":  ("Rare", "Rare", CONFIDENCE_DOCUMENTED),
    "dq5":  ("Chunsoft", "Chunsoft", CONFIDENCE_ATTRIBUTED),
    "bof2": ("Capcom", "Capcom", CONFIDENCE_ATTRIBUTED),
    "actr": ("Quintet", "Quintet", CONFIDENCE_ATTRIBUTED),
    "axe":  ("Konami", "Konami", CONFIDENCE_ATTRIBUTED),
    "turr": ("Factor 5", "Factor 5", CONFIDENCE_DOCUMENTED),
    "plok": ("Software Creations", "Software Creations", CONFIDENCE_DOCUMENTED),
    "ed2":  ("Neverland", "Neverland", CONFIDENCE_ATTRIBUTED),
}


def for_slug(slug: str) -> dict[str, Any]:
    """The driver record for a game slug, or an explicit absence.

    An unknown slug returns nulls rather than a guess: a missing attribution
    must not be indistinguishable from a confident one.
    """
    entry = DRIVERS.get(slug)
    if entry is None:
        return {
            "driver": None, "driver_vendor": None,
            "driver_confidence": None,
        }
    family, vendor, confidence = entry
    return {
        "driver": family,
        "driver_vendor": vendor,
        "driver_confidence": confidence,
    }


def block() -> dict[str, Any]:
    """The whole mapping, for publication in `index.json`.

    Carries its own provenance statement, because a consumer reading only the
    JSON must learn that this one field is curated rather than measured.
    """
    return {
        "schema": SCHEMA,
        "source": "curated external knowledge, NOT derived from the SPC files",
        "caveat": (
            "No extraction step identifies a driver; nothing else in this "
            "corpus depends on these labels. They come from published "
            "documentation of SNES audio engines and from game credits, are "
            "not verifiable from anything in the distribution, and should be "
            "treated as a hypothesis to test rather than a measurement. "
            "Publishers reuse and replace engines between titles."
        ),
        "games": {slug: for_slug(slug) for slug in sorted(DRIVERS)},
    }
