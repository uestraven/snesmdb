#!/usr/bin/env python3
"""Three research workflows that use the published corpus and nothing else.

    workflows.py <dist-dir> discover --game "Actraiser"
    workflows.py <dist-dir> pitch    --game "Actraiser"
    workflows.py <dist-dir> samples

Gate 4. These are the researcher-facing counterpart to the test suite: every
line here runs against a downloaded `dist` tree using only the Python standard
library. THIS MODULE DELIBERATELY DOES NOT IMPORT `snesmdb`. A researcher who
downloads the corpus does not have this repository's library, so a workflow
that needed it would prove nothing about whether the published artifact is
usable -- and a test enforces the rule rather than trusting this comment.

They are also the worked answer to the question the schema exists to make
answerable: what does a researcher have to know to get a correct number out of
this dataset? Each workflow states the trap it avoids.

WHAT IS NOT HERE, on purpose. No polyphony or simultaneous-voice analysis.
That question is reserved for the independent evaluation, and writing the
analysis here first would turn that evaluation into a check of our own
assumptions rather than a test of whether the artifact can be read correctly
by someone who did not build it.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

#: The index shapes this code accepts. `snesmdb.index.v1` made the index a
#: document; before that it was a bare list of track rows.
INDEX_SCHEMA = "snesmdb.index.v1"

#: The event-table versions this script understands, newest first. A READER
#: SHOULD ACCEPT EVERY VERSION IT KNOWS, not only the one it was written
#: against. This script originally tested the schema string for equality with
#: `v1` and refused `v2` outright -- even though v2 only ADDS fields and every
#: field this code touches is unchanged. That is worth noting because the
#: changelog claimed "a reader written for v1 works unchanged", and a reader
#: doing strict equality does not. Both statements are now precise: field
#: access is unaffected; a consumer pinning the exact string must add the new
#: version to its accepted set.
SUPPORTED_EVENT_SCHEMAS = ("snesmdb.events.v2", "snesmdb.events.v1")
EVENTS_SCHEMA = SUPPORTED_EVENT_SCHEMAS[0]

#: A pitch is usable as a pitch only in this state. The other three say WHY
#: there is no note number -- hardware noise, pitch modulation from the
#: previous voice, or an estimate that failed -- and they are not
#: interchangeable with each other or with zero.
PITCH_USABLE = "estimated"

#: An event is not an attack. `key_on` is a newly triggered note; a
#: `legato_step` is a pitch change on a voice that never re-keyed.
ORIGIN_ATTACK = "key_on"


def load_index(dist: Path) -> dict[str, Any]:
    """The corpus manifest, as a document.

    MIGRATION. `index.json` used to be a bare JSON array, so the old idiom was

        tracks = json.load(handle)

    and it is now

        tracks = json.load(handle)["tracks"]

    This reads either, because a corpus published before the change is still a
    real artifact; a download's own shape is identified by its top-level
    `schema` field, which the array form cannot carry.
    """
    raw = json.loads((dist / "index.json").read_text())
    if isinstance(raw, list):
        # Pre-v1 download: synthesise the document so callers have one shape.
        return {"schema": None, "formats": {}, "corpus": {}, "tracks": raw}
    if raw.get("schema") != INDEX_SCHEMA:
        raise SystemExit(
            f"index declares schema {raw.get('schema')!r}; this script was "
            f"written against {INDEX_SCHEMA!r}. Check the release notes "
            f"before trusting any number below."
        )
    return raw


def load_events(dist: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """One track's event table, checked against the index row that named it.

    The index carries the event counts so that a census needs no pass over the
    corpus. That is only safe if the two agree, so this verifies rather than
    assumes -- a stale index would otherwise silently scale every result.
    """
    with gzip.open(dist / entry["events"], "rt") as handle:
        table = json.load(handle)
    if table.get("schema") not in SUPPORTED_EVENT_SCHEMAS:
        raise SystemExit(
            f"{entry['track_id']}: event schema {table.get('schema')!r} is "
            f"not one this script knows ({', '.join(SUPPORTED_EVENT_SCHEMAS)})"
        )
    for field in ("track_id", "event_count", "pitched_event_count",
                  "attack_count", "extraction_status"):
        if entry.get(field) != table.get(field):
            raise SystemExit(
                f"{entry['track_id']}: index says {field}={entry.get(field)!r} "
                f"but the event table says {table.get(field)!r}"
            )
    return table


# ---------------------------------------------------------------------------
# Workflow 1: corpus discovery
# ---------------------------------------------------------------------------

def discover(
    dist: Path,
    game: str | None = None,
    track_class: str | None = "music",
    require_pitched: bool = True,
) -> list[dict[str, Any]]:
    """Find the tracks a study is about, from the index alone.

    THE TRAP: filtering on the wrong field. `track_class` is MUSICAL (music,
    jingle, effect, drone) and `extraction_status` is a DATA-QUALITY statement.
    They are independent -- 42 sound effects in this corpus contain recoverable
    pitch and 11 music tracks contain none -- so a melodic study filters on
    both and neither one implies the other.
    """
    tracks = load_index(dist)["tracks"]
    found = []
    for entry in tracks:
        if game is not None and entry.get("game") != game:
            continue
        if track_class is not None and entry.get("track_class") != track_class:
            continue
        if require_pitched and not entry.get("pitched_event_count"):
            continue
        found.append(entry)
    return sorted(found, key=lambda e: e["track_id"])


# ---------------------------------------------------------------------------
# Workflow 2: pitch distribution and range
# ---------------------------------------------------------------------------

def pitch_profile(
    dist: Path, entries: list[dict[str, Any]]
) -> dict[str, Any]:
    """Pitch distribution and range over a set of tracks.

    THE TRAP, and it is the one that produces a confidently wrong number:
    treating a missing `midi_note` as a rest, a zero, or a dropped row. 458,407
    of the 2,018,409 published events carry no note number, and `pitch_status`
    says which of four reasons applies. Only `estimated` is a pitch.

    THE SECOND TRAP: counting every event as a note. A `legato_step` is a pitch
    change inside a note that is already sounding. It belongs in a distribution
    of SOUNDED PITCHES and not in a count of NOTES PLAYED, so both are reported
    and neither is called "notes".
    """
    attack_pitches: list[float] = []
    all_pitches: list[float] = []
    excluded: Counter[str] = Counter()
    n_events = 0
    for entry in entries:
        table = load_events(dist, entry)
        for event in table["events"]:
            n_events += 1
            status = event["pitch_status"]
            if status != PITCH_USABLE:
                excluded[status] += 1
                continue
            pitch = float(event["midi_note"])
            all_pitches.append(pitch)
            if event["origin"] == ORIGIN_ATTACK:
                attack_pitches.append(pitch)
    semitones = Counter(round(p) for p in attack_pitches)
    return {
        "n_tracks": len(entries),
        "n_events": n_events,
        # Pitched ATTACKS: the right denominator for "how many notes".
        "n_attacks_pitched": len(attack_pitches),
        # Every sounded pitch, attacks plus legato steps: the right
        # denominator for "what pitches occur".
        "n_pitch_events": len(all_pitches),
        "attack_pitch_min": min(attack_pitches) if attack_pitches else None,
        "attack_pitch_max": max(attack_pitches) if attack_pitches else None,
        "attack_pitch_mean": (
            round(sum(attack_pitches) / len(attack_pitches), 4)
            if attack_pitches else None
        ),
        # Why each unpitched event has no pitch. Published so that a
        # researcher can report the exclusion rather than hide it.
        "excluded_by_pitch_status": dict(excluded),
        "semitone_histogram": dict(sorted(semitones.items())),
    }


# ---------------------------------------------------------------------------
# Workflow 3: sample identity across tracks
# ---------------------------------------------------------------------------

def sample_usage(
    dist: Path, entries: list[dict[str, Any]], min_tracks: int = 2
) -> dict[str, Any]:
    """Which sample content recurs, and what that does and does not mean.

    THE TRAP: reading `sample_id` as an instrument label. It is a content hash
    of the decoded BRR audio -- it says two tracks played THE SAME SOUND, and
    says nothing about that sound's musical role. The evidence is in the
    output: the pitch span over which a recurring sample is used is reported
    per sample, and a sample used across three octaves is not playing one
    instrumental part.

    What the hash does buy is the join that `srcn` cannot support. An SRCN is
    an ARAM directory index and is not stable across a game's tracks, so
    grouping on it would merge unrelated sounds.
    """
    tracks_by_sample: dict[str, set[str]] = {}
    games_by_sample: dict[str, set[str]] = {}
    pitches_by_sample: dict[str, list[float]] = {}
    for entry in entries:
        table = load_events(dist, entry)
        for event in table["events"]:
            sample = event.get("sample_id")
            if not sample:
                # No directory entry resolved for this voice in this track;
                # reported rather than silently grouped under "".
                continue
            tracks_by_sample.setdefault(sample, set()).add(entry["track_id"])
            games_by_sample.setdefault(sample, set()).add(entry.get("game"))
            if event["pitch_status"] == PITCH_USABLE:
                pitches_by_sample.setdefault(sample, []).append(
                    float(event["midi_note"])
                )
    recurring = []
    for sample, tracks in tracks_by_sample.items():
        if len(tracks) < min_tracks:
            continue
        pitches = pitches_by_sample.get(sample, [])
        recurring.append({
            "sample_id": sample,
            "n_tracks": len(tracks),
            "n_games": len(games_by_sample[sample]),
            "pitch_min": min(pitches) if pitches else None,
            "pitch_max": max(pitches) if pitches else None,
            # The span is the point: a wide span is direct evidence that one
            # sample is not one instrument.
            "pitch_span_semitones": (
                round(max(pitches) - min(pitches), 2) if pitches else None
            ),
        })
    recurring.sort(key=lambda r: (-r["n_tracks"], r["sample_id"]))
    return {
        "n_distinct_samples": len(tracks_by_sample),
        "n_recurring": len(recurring),
        "n_cross_game": sum(1 for r in recurring if r["n_games"] > 1),
        "recurring": recurring,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path, help="a published corpus tree")
    parser.add_argument(
        "workflow", choices=("discover", "pitch", "samples"),
    )
    parser.add_argument("--game", default=None)
    parser.add_argument("--track-class", default="music")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    index = load_index(args.dist)
    print(
        f"corpus {index.get('schema')}: "
        f"{index.get('corpus', {}).get('n_tracks')} tracks, "
        f"events {index.get('formats', {}).get('events')}"
    )
    entries = discover(args.dist, args.game, args.track_class)
    if args.limit:
        entries = entries[: args.limit]

    if args.workflow == "discover":
        for entry in entries:
            print(
                f"{entry['track_id']:28} {entry['track_class']:7} "
                f"{entry['extraction_status']:30} "
                f"{entry['attack_count']:6} attacks  {entry['title']}"
            )
        print(f"\n{len(entries)} tracks")
        return

    if args.workflow == "pitch":
        print(json.dumps(pitch_profile(args.dist, entries), indent=1))
        return

    report = sample_usage(args.dist, entries)
    print(json.dumps({
        "n_distinct_samples": report["n_distinct_samples"],
        "n_recurring": report["n_recurring"],
        "n_cross_game": report["n_cross_game"],
        "widest_spans": sorted(
            (r for r in report["recurring"]
             if r["pitch_span_semitones"] is not None),
            key=lambda r: -r["pitch_span_semitones"],
        )[:10],
    }, indent=1))


if __name__ == "__main__":
    main()
