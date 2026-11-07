"""`snesmdb.index.v1` — what a published corpus says about itself.

The index used to be a bare JSON list of track entries. That is enough to find
a file and not enough to be a published artifact: it could not state which
contract it followed, so a researcher holding two downloads could only tell
them apart by diffing them, and nothing recorded how large the corpus was
without an aggregation pass over 1,316 gzipped files.

So the index is a document: `{schema, formats, corpus, tracks}`. `tracks` is
the old list, unchanged, because a published shape that quietly renames or
drops a field is worse than one that is merely incomplete.

PER-FORMAT VERSIONS, NOT ONE CORPUS VERSION. The formats move independently:
`events.v1` arrived while the score payload stayed exactly as it was. A single
corpus version would force a choice between bumping it for consumers that were
not affected, or leaving it alone and letting a real change pass unannounced.
Naming each format separately lets a consumer check the one it actually reads.

This lives in the library rather than in `publish.py` so that the writer and
the verifier share one definition. The verifier's whole job is to check the
contract, and it cannot do that honestly by importing a copy.
"""

from __future__ import annotations

from typing import Any

from . import events, sampleid, scores

#: The index's own schema.
INDEX_SCHEMA = "snesmdb.index.v1"

#: The intake tree's schema, named once. The index declares it and the payload
#: carries it; a literal in both places is an invitation for them to disagree.
INTAKE_SCHEMA = "snesmdb.intake.v1"


def formats() -> dict[str, Any]:
    """The schema of every format the tree publishes, from its owning module.

    Read from the modules rather than restated, so the index cannot claim a
    version the files do not have.
    """
    return {
        "events": events.SCHEMA,
        "intake": INTAKE_SCHEMA,
        "sample_id": sampleid.SCHEMA,
        "uniform_hz": scores.UNIFORM_HZ,
    }


def index_document(tracks: list[dict[str, Any]]) -> dict[str, Any]:
    """The index as a self-describing document.

    The `corpus` block exists so that "how big is this dataset" needs no pass
    over the corpus. Both censuses are published because `track_class` and
    `extraction_status` are independent -- a sound effect can contain
    recoverable pitch and a music track can contain none -- so a reader needs
    the joint picture rather than either margin.
    """
    classes: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for entry in tracks:
        klass = entry.get("track_class") or "unknown"
        classes[klass] = classes.get(klass, 0) + 1
        status = entry.get("extraction_status") or "unknown"
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "schema": INDEX_SCHEMA,
        "formats": formats(),
        "corpus": {
            "n_tracks": len(tracks),
            "n_events": sum(e.get("event_count", 0) for e in tracks),
            "n_pitched_events": sum(
                e.get("pitched_event_count", 0) for e in tracks
            ),
            # An event is not an attack: a legato step is a pitch change on a
            # voice that never re-keyed. Published so a rhythmic study does
            # not have to know that to get the right number.
            "n_attacks": sum(e.get("attack_count", 0) for e in tracks),
            "n_games": len({e.get("game") for e in tracks}),
            "track_classes": classes,
            "extraction_statuses": statuses,
        },
        "tracks": tracks,
    }


def tracks_of(raw: Any) -> list[dict[str, Any]]:
    """The per-track entries, from either index shape.

    The bare-list form is still read: a corpus published before the index
    became a document is a legitimate artifact, and reading one is exactly
    when a researcher reaches for the verifier.
    """
    if isinstance(raw, list):
        return raw
    return raw.get("tracks", [])
