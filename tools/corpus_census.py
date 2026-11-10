#!/usr/bin/env python3
"""Measure every figure the public documentation quotes, from one release.

    corpus_census.py <release-dir> <census.json> [--label LABEL]

Read-only. Reads only the published distribution -- the files a researcher
downloads -- so every number is reproducible by anyone holding the release.

WHY THIS EXISTS. The README fell three expansion milestones behind: it
presented the 27-game release as the current corpus while the 50-game
release was frozen, and a reader could not tell which population a figure
belonged to. The figures were not wrong when written. They were copied into
prose, and prose does not get recomputed.

So the documented numbers now come from an artifact. `corpus_census.py`
emits them, `tests/test_readme_census.py` asserts the README quotes them,
and a population expansion that forgets the README fails the suite instead
of shipping.

EVERY FIGURE IS SCOPED TO ONE RELEASE. A census describes the release
directory it was given and nothing else. Statistics from different
populations must not be added: sample banks overlap across cohorts, so even
a distinct-identity count is not a sum.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path


def read_table(path: Path) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("release", type=Path)
    ap.add_argument("census", type=Path)
    ap.add_argument("--label", default=None,
                    help="release label; read from RELEASE.json if present")
    args = ap.parse_args()

    root = args.release
    index = json.loads((root / "index.json").read_text())
    tracks = index["tracks"]

    label = args.label
    frozen_utc = None
    release_path = root / "RELEASE.json"
    if release_path.is_file():
        record = json.loads(release_path.read_text())
        label = label or record.get("label")
        frozen_utc = record.get("frozen_utc")

    # ---- counted from the event tables, not from publisher counters.
    attacks = steps = pitched = with_id = 0
    null_reasons: collections.Counter = collections.Counter()
    identities: set[str] = set()
    loop_only_note = 0
    per_game_tracks: collections.Counter = collections.Counter()
    per_game_ids: dict[str, set[str]] = collections.defaultdict(set)
    per_game_null: collections.Counter = collections.Counter()
    per_game_attacks: collections.Counter = collections.Counter()

    # Each table's header asserts how many of its identities came from
    # instrumented DSP observation at key-on rather than from the
    # capture-time directory. Summed here so the README's "every published
    # identity was observed at key-on" is a measurement and not a slogan.
    observed_at_key_on = 0

    for entry in tracks:
        table = read_table(root / entry["events"])
        observed_at_key_on += int(
            table.get("attacks_identity_observed_at_key_on") or 0)
        per_game_tracks[entry["game"]] += 1
        for event in table["events"]:
            if event["origin"] != "key_on":
                steps += 1
                continue
            attacks += 1
            per_game_attacks[entry["game"]] += 1
            if event["pitch_status"] == "estimated":
                pitched += 1
            sid = event.get("sample_id")
            if sid:
                with_id += 1
                identities.add(sid)
                per_game_ids[entry["game"]].add(sid)
            else:
                null_reasons[event.get("sample_id_unresolved_reason")
                             or "<absent>"] += 1
                per_game_null[entry["game"]] += 1

    # ---- splits, and the games behind them.
    splits = json.loads((root / "splits.json").read_text())
    assignment = splits["assignment"]
    game_of = {t["track_id"]: t["game"] for t in tracks}
    split_tracks: collections.Counter = collections.Counter()
    split_games: dict[str, set[str]] = collections.defaultdict(set)
    for track_id, split in assignment.items():
        split_tracks[split] += 1
        if track_id in game_of:
            split_games[split].add(game_of[track_id])

    # ---- attribution. A truncated ID666 credit is not a confirmed identity.
    #
    # TWO SCOPES, both reported, because they differ and each is right for a
    # different claim. The index's `n_credited_composers` counts credits on
    # MUSIC tracks; counting every track adds eight more, most of them
    # truncation fragments ('Hitoshi', 'Kir', 'Sato') that are not author
    # identities. Quoting one scope as the other overstates or understates
    # the roster.
    truncated = sum(1 for t in tracks if t.get("composer_truncated"))
    credited = {c for t in tracks for c in (t.get("composers") or []) if c}
    credited_music = {c for t in tracks if t.get("track_class") == "music"
                      for c in (t.get("composers") or []) if c}

    # ---- clock provenance, read from the score files.
    #
    # NOT from the index, which carries no clock field, and not from the
    # publisher's `with_clock` counter. An earlier draft of this tool read a
    # `clock_hz` key that does not exist and reported 0 tracks with a
    # hardware clock -- a missing field silently becoming a measurement is
    # the failure this whole census exists to prevent. Where the scores are
    # absent the figure is None, never 0.
    with_clock = register_read = None
    if any((root / t["scores"]).is_file() for t in tracks[:1]):
        with_clock = register_read = 0
        for entry in tracks:
            score = read_table(root / entry["scores"])
            clock = score.get("clock") or {}
            if clock.get("is_hardware"):
                with_clock += 1
            if clock.get("is_register_read"):
                register_read += 1

    # ---- MIDI, from the files actually present.
    midi_present = sum(1 for t in tracks
                       if t.get("midi") and (root / t["midi"]).is_file())
    midi_absent = len(tracks) - midi_present

    census = {
        "schema": "snesmdb.census.v1",
        "release": label,
        "release_dir": str(root),
        "frozen_utc": frozen_utc,
        "formats": index.get("formats"),
        "note": (
            "Measured from this release's own published artifacts. Figures "
            "from different populations must NOT be added: sample banks "
            "overlap across cohorts, so a distinct-identity count is not a "
            "sum."
        ),
        "tracks": len(tracks),
        "games": len(per_game_tracks),
        "events": attacks + steps,
        "attacks": attacks,
        "legato_steps": steps,
        "pitched_attacks": pitched,
        "pitched_share": round(pitched / attacks, 6) if attacks else None,
        "unpitched_share": round(1 - pitched / attacks, 6) if attacks else None,
        "attacks_with_sample_id": with_id,
        "attacks_without_sample_id": attacks - with_id,
        "identity_coverage": round(with_id / attacks, 6) if attacks else None,
        "distinct_sample_identities": len(identities),
        "attacks_identity_observed_at_key_on": observed_at_key_on,
        "all_identities_observed_at_key_on": observed_at_key_on == with_id,
        "sample_id_null_reasons": dict(null_reasons.most_common()),
        "tracks_with_hardware_clock": with_clock,
        "tracks_with_clock_read_from_register": register_read,
        "splits": {
            s: {"tracks": split_tracks.get(s, 0),
                "games": len(split_games.get(s, ()))}
            for s in ("train", "valid", "test")
        },
        "tracks_with_truncated_credit": truncated,
        "distinct_recorded_credits": len(credited),
        "distinct_recorded_credits_music_tracks": len(credited_music),
        "midi_files": midi_present,
        "tracks_without_midi": midi_absent,
        "track_classes": index.get("corpus", {}).get("track_classes"),
        "extraction_statuses": index.get("corpus", {}).get(
            "extraction_statuses"),
        "tracks_per_game": dict(sorted(per_game_tracks.items())),
        "attacks_per_game": dict(sorted(per_game_attacks.items())),
        "distinct_identities_per_game": {
            g: len(ids) for g, ids in sorted(per_game_ids.items())},
        # Per game, so a reader can see that unresolved identity is
        # concentrated in the earliest cohort rather than spread evenly.
        "attacks_without_sample_id_per_game": dict(
            sorted(per_game_null.items(), key=lambda kv: -kv[1])),
    }

    # The index's own totals must agree with what was just counted. A
    # disagreement means one of them is wrong, and a census that averages
    # them would hide which.
    declared = index.get("corpus") or {}
    mismatch = {
        key: {"index": declared[key], "counted": census[ours]}
        for key, ours in (("n_tracks", "tracks"), ("n_events", "events"),
                          ("n_attacks", "attacks"), ("n_games", "games"),
                          ("n_pitched_attacks", "pitched_attacks"))
        if key in declared and declared[key] != census[ours]
    }
    census["index_disagreements"] = mismatch

    args.census.write_text(json.dumps(census, indent=1))

    print(f"{label or root.name}: {census['tracks']:,} tracks, "
          f"{census['games']} games")
    print(f"  events   {census['events']:,} = "
          f"{census['attacks']:,} attacks + {census['legato_steps']:,} steps")
    print(f"  pitched  {census['pitched_attacks']:,} "
          f"({100 * census['pitched_share']:.2f}%)")
    print(f"  identity {census['attacks_with_sample_id']:,} "
          f"({100 * census['identity_coverage']:.2f}%), "
          f"{census['distinct_sample_identities']:,} distinct, "
          f"{census['attacks_without_sample_id']:,} null")
    print(f"  keyon    {census['attacks_identity_observed_at_key_on']:,} "
          f"observed at key-on"
          + ("  (ALL of them)" if census["all_identities_observed_at_key_on"]
             else f"  -- NOT all {census['attacks_with_sample_id']:,}"))
    print(f"  splits   " + "  ".join(
        f"{s} {v['tracks']}/{v['games']}g"
        for s, v in census["splits"].items()))
    print(f"  midi     {census['midi_files']:,} files, "
          f"{census['tracks_without_midi']} tracks without one")
    print(f"  credits  {census['distinct_recorded_credits']} recorded "
          f"({census['distinct_recorded_credits_music_tracks']} on music "
          f"tracks), {census['tracks_with_truncated_credit']} tracks "
          f"truncated")
    print(f"  clock    {census['tracks_with_hardware_clock']} hardware, "
          f"{census['tracks_with_clock_read_from_register']} read from a "
          f"timer register")
    if mismatch:
        print(f"\n  INDEX DISAGREES: {mismatch}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
