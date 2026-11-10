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

import csv
import io
from typing import Any

from . import drivers, events, sampleid, scores

#: Columns of `tracks.csv`, in order. The per-track metadata in a form that
#: degrades gracefully: a truncated CSV loses its tail and keeps every
#: complete line, where a truncated JSON document is unparseable in full.
TRACKS_CSV_COLUMNS = (
    "track_id", "game_slug", "game", "title", "composers", "track_class",
    "extraction_status", "split", "render_seconds", "n_notes",
    "event_count", "pitched_event_count", "pitched_attack_count",
    "attack_count", "legato_step_count",
    # CURATED EXTERNAL KNOWLEDGE, not measured. See `snesmdb.drivers`.
    "driver", "driver_vendor", "driver_confidence",
)

#: The index's own schema.
INDEX_SCHEMA = "snesmdb.index.v1"

#: The intake tree's schema, named once. The index declares it and the payload
#: carries it; a literal in both places is an invitation for them to disagree.
INTAKE_SCHEMA = "snesmdb.intake.v1"

#: `tracks.csv`'s schema. Versioned like the others so a consumer can tell
#: which columns to expect.
TRACKS_CSV_SCHEMA = "snesmdb.tracks.v1"


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
        "tracks_csv": TRACKS_CSV_SCHEMA,
        "drivers": drivers.SCHEMA,
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
            # Pitched ATTACKS, separate from pitched events. A reviewer read
            # `n_pitched_events` as a count of distinct musical pitches and
            # was right to call it inflated while every legato step duplicated
            # its parent's pitch. The steps now carry their own pitch and both
            # figures are published, so the question is answerable from the
            # header.
            "n_pitched_attacks": sum(
                e.get("pitched_attack_count", 0) for e in tracks
            ),
            "n_games": len({e.get("game") for e in tracks}),
            "track_classes": classes,
            "extraction_statuses": statuses,
        },
        # Slug to game name. Load-bearing for per-game work and previously
        # inferrable only by counting tracks per game.
        "games": games(tracks),
        # What was collected, so a pooled figure can be weighted rather than
        # read as a universal convention.
        "composition": composition(tracks),
        # The one curated field in the distribution, carrying its own
        # provenance so a consumer reading only JSON learns that it is not
        # measured. Published because DATASET.md conditions advice on the
        # driver in four places and shipped no mapping, which made that
        # advice unactionable without outside knowledge.
        "drivers": drivers.block(),
        "tracks": tracks,
    }


def games(tracks: list[dict[str, Any]]) -> dict[str, str]:
    """Slug to game name, published rather than left to be inferred.

    The slugs are not derivable from the names: `mo2` is Earthbound (Mother
    2), `sd2` is Secret of Mana (Seiken Densetsu 2), `ed2` is Lufia 2, `dkq`
    is Donkey Kong Country 2. An evaluator who needed this had to match
    per-game track counts and then break a tie between two 66-track games
    using their clock rates -- correct, ingenious, and reverse engineering of
    something the project already knows.
    """
    found: dict[str, str] = {}
    for entry in tracks:
        # The PUBLISHED slug, which is the game family's where regional
        # releases are grouped. Re-deriving it from the track id emitted a
        # phantom entry -- `pdp` AND `ta` both mapping to Tetris Attack --
        # so the map declared 14 slugs for 13 in use.
        slug = str(entry.get("game_slug") or events.game_slug(
            str(entry.get("track_id", ""))))
        name = entry.get("game")
        if slug and name:
            found.setdefault(slug, name)
    return dict(sorted(found.items()))


def tracks_csv(tracks: list[dict[str, Any]]) -> str:
    """`tracks.csv` -- the per-track metadata, one line per track."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(TRACKS_CSV_COLUMNS)
    for entry in sorted(tracks, key=lambda e: str(e.get("track_id"))):
        row = dict(entry)
        row["game_slug"] = events.game_slug(str(entry.get("track_id", "")))
        # Semicolons, because a composer list inside a CSV cell must not
        # collide with the delimiter.
        row["composers"] = "; ".join(entry.get("composers") or [])
        row.update(drivers.for_slug(row["game_slug"]))
        writer.writerow([row.get(column, "") for column in TRACKS_CSV_COLUMNS])
    return out.getvalue()


def composition(tracks: list[dict[str, Any]]) -> dict[str, Any]:
    """What was collected, so a pooled figure can be weighted or qualified.

    A corpus-wide mean is a mean over a sample weighted by how many tracks
    each game happens to contribute, and this corpus is not balanced:
    Earthbound is 13.8% of music tracks and games range from 17 to 139, an 8x
    spread. Published so a reader can see that before quoting a global
    average, and so the choice of statistical unit is theirs rather than
    implicit in ours.

    Composer credits are MANY-TO-MANY and some are truncated at 32 characters
    by the source tags, so `tracks_per_composer` sums to more than the track
    count. That is recorded rather than smoothed over: Earthbound's three
    credited composers each appear on all 139 of its tracks.
    """
    music = [t for t in tracks if t.get("track_class") == "music"]
    per_game: dict[str, int] = {}
    per_composer: dict[str, int] = {}
    for entry in music:
        per_game[entry.get("game") or "?"] = (
            per_game.get(entry.get("game") or "?", 0) + 1
        )
        for name in entry.get("composers") or []:
            per_composer[name] = per_composer.get(name, 0) + 1
    counts = sorted(per_game.values(), reverse=True)
    total = len(music) or 1
    credits = sum(per_composer.values()) or 1
    top_composers = sorted(per_composer.values(), reverse=True)[:3]
    return {
        # The game count is INTERPOLATED, not written out. A hardcoded 22
        # survived three expansions here and shipped in every combined
        # release, telling a reader the corpus was 22 games from a field
        # beside the one reporting 50.
        "note": (
            f"Descriptive of the collected sample, NOT of SNES music. "
            f"{len(per_game)} games of roughly 700 commercial titles, "
            f"JRPG- and first-party-weighted. Weight or qualify any "
            f"corpus-wide figure accordingly."
        ),
        "n_music_tracks": len(music),
        "n_games": len(per_game),
        "n_credited_composers": len(per_composer),
        "largest_game_share": round(counts[0] / total, 4) if counts else 0,
        "top3_game_share": round(sum(counts[:3]) / total, 4),
        "top3_composer_credit_share": round(sum(top_composers) / credits, 4),
        "tracks_per_game_min": min(counts) if counts else 0,
        "tracks_per_game_max": max(counts) if counts else 0,
        "tracks_per_game": dict(sorted(per_game.items())),
        "composer_credits_are_many_to_many": True,
        "tracks_per_composer": dict(sorted(per_composer.items())),
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
