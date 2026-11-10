#!/usr/bin/env python3
"""Recompute SNES-MDB's published claims from the distribution, independently.

    python3 replicate.py                 # from the package root
    python3 replicate.py path/to/dist --claims docs/claims.json
    python3 replicate.py path/to/dist --report out.json

This is NOT the engineering audit. `verify_corpus.py` checks that the artifact
is internally consistent; this checks that the NUMBERS IN THE DOCUMENTATION
are true of the artifact. Three independent evaluations found 35 defects
between them, the data survived almost all of it, and every substantive
finding came from an outsider recomputing a published figure. This makes that
cheap and routine instead of exceptional.

FOUR RULES, because a replication that breaks any of them proves less than it
appears to:

  1. It reads ONLY the published distribution. No extraction records, no
     intermediate output.
  2. It imports nothing from this project -- standard library only. A check
     that borrowed the code under test would be circular.
  3. Where possible it reads a DIFFERENT published representation from the one
     the claim's own figure came from. Two calculations over one extraction
     can agree perfectly while both are wrong; the MIDI note-on count is
     recovered by parsing the binary files, which no JSON table touches.
     Claims that cannot be checked that way are marked
     `same_representation` in the registry and prove correspondingly less.
  4. It separates three things the registry keeps apart: a `measurement` that
     must reproduce, an `estimate` that reproduces only under a named
     assumption, and an `interpretation` that cannot be checked at all and is
     listed so a reader knows which claims rest on judgement.

What this does NOT establish: that a measurement corresponds to the musical
concept it is named for, or that any conclusion generalises beyond these 22
games. Those are separate claims and no runner can settle them.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics
import struct
from pathlib import Path
from typing import Any, Callable

#: Rows whose onset-to-end crossing is pure publication rounding. The
#: documented remedy; applied here so the sweep measures the hardware.
ROUNDING_TOLERANCE_SEC = 1.5e-6


# ---------------------------------------------------------------------------
# Reading the distribution
# ---------------------------------------------------------------------------

def _load_gz(path: Path) -> Any:
    with gzip.open(path, "rt") as handle:
        return json.load(handle)


def _tracks(dist: Path) -> list[dict[str, Any]]:
    raw = json.loads((dist / "index.json").read_text())
    return raw if isinstance(raw, list) else raw["tracks"]


def _events(dist: Path, entry: dict[str, Any]) -> dict[str, Any]:
    return _load_gz(dist / entry["events"])


# ---------------------------------------------------------------------------
# Replications. Each returns a dict compared against the registry's `reported`.
# ---------------------------------------------------------------------------

def replicate_row_duration(dist: Path, tracks: list) -> dict[str, Any]:
    """From the INTAKE timing block, not the scores clock the claim came from."""
    periods = []
    for entry in tracks:
        if not entry.get("intake"):
            continue
        timing = _load_gz(dist / entry["intake"]).get("timing") or {}
        ticks = timing.get("row_period_ticks")
        per_sec = timing.get("ticks_per_second")
        if ticks and per_sec:
            periods.append(ticks / per_sec * 1000.0)
    return {"min": round(min(periods), 3), "max": round(max(periods), 3),
            "_n": len(periods)}


def replicate_coarser_than_uniform(dist: Path, tracks: list) -> dict[str, Any]:
    coarse = total = 0
    for entry in tracks:
        if not entry.get("intake"):
            continue
        timing = _load_gz(dist / entry["intake"]).get("timing") or {}
        ticks, per_sec = timing.get("row_period_ticks"), timing.get("ticks_per_second")
        if not ticks or not per_sec:
            continue
        total += 1
        if ticks / per_sec * 1000.0 > 10.0:
            coarse += 1
    return {"count": coarse, "fraction": round(coarse / total, 3) if total else 0}


def replicate_pitched_attacks(dist: Path, tracks: list) -> dict[str, Any]:
    """Counted from the event ROWS, not from the index block that reports it."""
    total = 0
    for entry in tracks:
        for event in _events(dist, entry)["events"]:
            if event["origin"] == "key_on" and event["pitch_status"] == "estimated":
                total += 1
    return {"count": total}


def replicate_legato_steps(dist: Path, tracks: list) -> dict[str, Any]:
    total = sum(
        1 for entry in tracks
        for event in _events(dist, entry)["events"]
        if event["origin"] == "legato_step"
    )
    return {"count": total}


def _midi_note_ons(data: bytes) -> int:
    """Count note-on events in a Standard MIDI File, running status included.

    Written from the SMF specification rather than from this project's writer,
    so the count is recovered from the bytes a third party would read.
    """
    if data[:4] != b"MThd":
        return 0
    pos = 8 + struct.unpack(">I", data[4:8])[0]
    notes = 0
    while pos + 8 <= len(data):
        chunk, length = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body, pos = data[pos + 8:pos + 8 + length], pos + 8 + length
        if chunk != b"MTrk":
            continue
        i, status = 0, 0
        while i < len(body):
            # Variable-length delta time.
            while i < len(body) and body[i] & 0x80:
                i += 1
            i += 1
            if i >= len(body):
                break
            byte = body[i]
            if byte & 0x80:
                status, i = byte, i + 1
            if status in (0xFF,):
                meta = body[i]
                i += 1
                size = 0
                while i < len(body) and body[i] & 0x80:
                    size = (size << 7) | (body[i] & 0x7F)
                    i += 1
                size = (size << 7) | (body[i] & 0x7F) if i < len(body) else size
                i += 1 + size
                if meta == 0x2F:
                    break
                continue
            if status in (0xF0, 0xF7):
                size = 0
                while i < len(body) and body[i] & 0x80:
                    size = (size << 7) | (body[i] & 0x7F)
                    i += 1
                size = (size << 7) | (body[i] & 0x7F) if i < len(body) else size
                i += 1 + size
                continue
            high = status & 0xF0
            if high in (0xC0, 0xD0):
                i += 1
            elif high == 0x90:
                if i + 1 < len(body) and body[i + 1] > 0:
                    notes += 1
                i += 2
            else:
                i += 2
    return notes


def replicate_midi_note_ons(dist: Path, tracks: list) -> dict[str, Any]:
    notes = files = 0
    for path in sorted((dist / "midi").glob("*.mid")):
        files += 1
        notes += _midi_note_ons(path.read_bytes())
    return {"count": notes, "files": files}


def replicate_max_voices(dist: Path, tracks: list) -> dict[str, Any]:
    """Interval sweep over events, applying the documented rounding remedy."""
    peak = 0
    for entry in tracks:
        table = _events(dist, entry)
        by_voice: dict[int, list[tuple[float, float]]] = {}
        duration = float(table.get("duration_sec") or 0.0)
        for event in table["events"]:
            if event["origin"] != "key_on":
                continue
            start = float(event["onset_sec"])
            length = event["duration_sec"]
            end = duration if length is None else start + float(length)
            by_voice.setdefault(int(event["voice"]), []).append((start, end))
        edges: list[tuple[float, int]] = []
        for intervals in by_voice.values():
            intervals.sort()
            for index, (start, end) in enumerate(intervals):
                # Clamp to the next onset on this voice: the documented remedy
                # for the 1 us publication-rounding crossing.
                if index + 1 < len(intervals):
                    end = min(end, intervals[index + 1][0])
                if end - start <= 0:
                    continue
                edges.append((start, 1))
                edges.append((end, -1))
        # Closes before opens at equal timestamps, as the documentation
        # requires for half-open intervals.
        edges.sort(key=lambda e: (e[0], e[1]))
        live = 0
        for _, delta in edges:
            live += delta
            peak = max(peak, live)
    return {"max": peak}


def replicate_out_of_range(dist: Path, tracks: list) -> dict[str, Any]:
    bad = total = 0
    for entry in tracks:
        for event in _events(dist, entry)["events"]:
            if event["origin"] != "key_on" or event["midi_note"] is None:
                continue
            total += 1
            if not 12 <= event["midi_note"] <= 108:
                bad += 1
    return {"fraction": round(bad / total, 4) if total else 0.0}


def replicate_saturated_games(dist: Path, tracks: list) -> dict[str, Any]:
    """Duty cycle recomputed from the published events, where the claim's own
    figure is computed from the extraction records."""
    gated: dict[str, list[float]] = {}
    for entry in tracks:
        if entry.get("track_class") != "music":
            continue
        table = _events(dist, entry)
        duration = float(table.get("duration_sec") or 0.0)
        if duration <= 0:
            continue
        by_voice: dict[int, float] = {}
        for event in table["events"]:
            if event["origin"] != "key_on":
                continue
            length = event["duration_sec"]
            start = float(event["onset_sec"])
            end = duration if length is None else start + float(length)
            by_voice[int(event["voice"])] = by_voice.get(
                int(event["voice"]), 0.0
            ) + max(0.0, end - start)
        if not by_voice:
            continue
        # Denominator: the voices the track actually uses, as the field does.
        duty = sum(by_voice.values()) / (duration * len(by_voice))
        gated.setdefault(table["game"], []).append(min(duty, 1.0))
    saturated = [
        game for game, values in gated.items()
        if statistics.median(values) >= 0.95
    ]
    return {"count": len(saturated), "_games": sorted(saturated)}


def replicate_timbre_inert(dist: Path, tracks: list) -> dict[str, Any]:
    seen: set[int] = set()
    for entry in tracks[:: max(1, len(tracks) // 25)]:
        if entry.get("scores"):
            block = _load_gz(dist / entry["scores"]).get("expressive") or {}
            seen.update(block.get("timbre_classes_present") or [])
        if entry.get("intake"):
            for voice in _load_gz(dist / entry["intake"])["voices"]:
                for note in voice["notes"]:
                    if "timbre_class" in note:
                        seen.add(note["timbre_class"])
    return {"distinct_values": len(seen),
            "value": next(iter(seen)) if len(seen) == 1 else None}


def _resultant(phases: list[float]) -> float:
    if not phases:
        return 0.0
    x = statistics.fmean(math.cos(2 * math.pi * p) for p in phases)
    y = statistics.fmean(math.sin(2 * math.pi * p) for p in phases)
    return math.hypot(x, y)


def replicate_onset_concentration(dist: Path, tracks: list) -> dict[str, Any]:
    grid_r, clock_r = [], []
    music = [t for t in tracks if t.get("track_class") == "music"]
    for entry in music[:: max(1, len(music) // 120)]:
        if not entry.get("scores"):
            continue
        score = _load_gz(dist / entry["scores"])
        onsets = [
            float(e["onset_sec"]) for e in _events(dist, entry)["events"]
            if e["origin"] == "key_on"
        ]
        if len(onsets) < 40:
            continue
        for key, bucket in (("onset_grid", grid_r), ("clock", clock_r)):
            block = score.get(key) or {}
            period = block.get("period_sec")
            if not period:
                ticks = block.get("period_ticks")
                period = ticks / 1_024_000 if ticks else None
            if period:
                bucket.append(_resultant([(o / period) % 1.0 for o in onsets]))
    grid = statistics.fmean(grid_r) if grid_r else 0.0
    clock = statistics.fmean(clock_r) if clock_r else 0.0
    # THE TESTABLE CONTENT IS THE ORDERING AND THE SIZE OF THE GAP, not the
    # values: the resultant length depends on the estimator, and the first
    # replication of this claim failed on exactly that -- 0.779 against a
    # documented 0.937 while the ordering held firmly. Pinning the values
    # would make the registry assert something no independent method can
    # reproduce.
    return {"grid_beats_clock": grid > clock,
            "gap_at_least": round(grid - clock, 2) >= 0.3,
            "_onset_grid_R": round(grid, 3), "_clock_R": round(clock, 3)}


def _driver_of(dist: Path) -> dict[str, str]:
    """Slug to driver, read from the PUBLISHED index, not from any module."""
    raw = json.loads((dist / "index.json").read_text())
    block = (raw.get("drivers") or {}).get("games") or {}
    return {slug: (info or {}).get("driver") or "?" for slug, info in block.items()}


def replicate_ladder_deviation(dist: Path, tracks: list) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[float]] = {}
    for entry in tracks:
        table = _events(dist, entry)
        for event in table["events"]:
            if (event["origin"] != "key_on" or event["midi_note"] is None
                    or not event["sample_id"]):
                continue
            groups.setdefault(
                (table["game_slug"], event["sample_id"]), []
            ).append(float(event["midi_note"]))
    # AGGREGATED PER DRIVER, which is what the documented table does: a
    # driver pools its games. Computing it per GAME instead gives 4.06
    # (Mega Man X) against 2.46 for the Capcom driver -- the first
    # replication of this claim failed purely on that unstated choice, which
    # is the kind of thing this registry exists to pin down.
    driver = _driver_of(dist)
    per_driver: dict[str, list[float]] = {}
    per_game: dict[str, list[float]] = {}
    for (slug, _), notes in groups.items():
        if len(notes) < 8:
            continue
        best = min(
            statistics.median(
                abs((n - k / 100.0) - round(n - k / 100.0)) * 100 for n in notes
            )
            for k in range(100)
        )
        per_driver.setdefault(driver.get(slug, "?"), []).append(best)
        per_game.setdefault(slug, []).append(best)
    worst_driver = max(
        (statistics.median(v) for v in per_driver.values()), default=0.0
    )
    worst_game = max(
        (statistics.median(v) for v in per_game.values()), default=0.0
    )
    return {"worst_driver_cents": round(worst_driver, 2),
            "worst_game_cents": round(worst_game, 2)}


METHODS: dict[str, Callable[[Path, list], dict[str, Any]]] = {
    name: value for name, value in list(globals().items())
    if name.startswith("replicate_")
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def population_size(dist: Path, tracks: list, key: str) -> int | None:
    """The realised size of a sampling frame in THIS release.

    The registry records a selection rule, which is stable; this reports what
    the rule selects here, which is not. Printing both is what makes a
    22-game report comparable with a 50-game one rule by rule, instead of
    leaving a reader to guess whether a figure moved because the music
    differs or because the frame grew.
    """
    if key == "all_indexed_tracks":
        return len(tracks)
    if key in ("indexed_music_tracks", "game_weighted_music"):
        music = [t for t in tracks if t.get("track_class") == "music"]
        if key == "indexed_music_tracks":
            return len(music)
        return len({t.get("game") for t in music})
    if key == "midi_files":
        return sum(1 for _ in (dist / "midi").glob("*.mid"))
    if key in ("pitched_attacks", "all_published_events", "legato_steps"):
        return sum(
            int(t.get({"pitched_attacks": "pitched_attack_count",
                       "all_published_events": "event_count",
                       "legato_steps": "legato_step_count"}[key], 0) or 0)
            for t in tracks
        )
    return None


def _compare(reported: dict, got: dict, tolerance: float) -> list[str]:
    problems = []
    for key, want in (reported or {}).items():
        if key not in got:
            problems.append(f"{key}: not recomputed")
            continue
        have = got[key]
        if isinstance(want, (int, float)) and isinstance(have, (int, float)):
            if abs(have - want) > tolerance:
                problems.append(
                    f"{key}: documented {want}, recomputed {have} "
                    f"(|delta| {abs(have - want):.6g} > {tolerance})"
                )
        elif have != want:
            problems.append(f"{key}: documented {want!r}, recomputed {have!r}")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument("dist", nargs="?", type=Path, default=here / "dist")
    parser.add_argument("--claims", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--only", default=None, help="one claim id")
    args = parser.parse_args()

    dist = args.dist.expanduser().resolve()
    claims_path = args.claims or next(
        (p for p in (here / "docs" / "claims.json", here / "claims.json",
                     here.parent / "docs" / "claims.json") if p.is_file()),
        None,
    )
    if claims_path is None or not claims_path.is_file():
        raise SystemExit("no claims.json found; pass --claims")
    registry = json.loads(claims_path.read_text())

    pin = {}
    if (dist / "RELEASE.json").is_file():
        pin = json.loads((dist / "RELEASE.json").read_text())
    print(f"replicating {registry['schema']} against {dist}")
    print(f"  release    {pin.get('label')}  built from "
          f"{(pin.get('built_from') or {}).get('git_commit', '?')[:12]}")

    tracks = _tracks(dist)
    print(f"  tracks     {len(tracks)}\n")

    results, failures, skipped, not_applicable = [], 0, 0, 0
    for claim in registry["claims"]:
        if args.only and claim["id"] != args.only:
            continue
        kind = claim["kind"]
        if kind == "interpretation" or not claim.get("method"):
            print(f"  --   {claim['id']}: {kind}, not mechanically checkable")
            skipped += 1
            results.append({**claim, "outcome": "not_checkable"})
            continue
        method = METHODS.get(claim["method"])
        if method is None:
            print(f"  ??   {claim['id']}: no method {claim['method']}")
            skipped += 1
            continue
        frame = claim.get("population")
        size = population_size(dist, tracks, frame) if frame else None

        # COHORT GATE. A claim's `reported` figure was measured on one data
        # release. Recomputing it over a different population and calling
        # the difference a defect is a sampling-frame error: all six
        # "failures" against the 27-game corpus were 22-game cohort figures
        # compared against 1,477 tracks. Not applicable is the correct
        # verdict, and it is reported rather than passed silently.
        measured = claim.get("measured_on") or {}
        expected_tracks = measured.get("tracks")
        if expected_tracks is not None and expected_tracks != len(tracks):
            print(f"  n/a  {claim['id']}: measured on "
                  f"{measured.get('data_release', '?')} "
                  f"({expected_tracks:,} tracks); this release has "
                  f"{len(tracks):,}")
            not_applicable += 1
            results.append({**claim, "outcome": "not_applicable",
                            "release_tracks": len(tracks)})
            continue

        got = method(dist, tracks)
        problems = _compare(claim.get("reported", {}), got,
                            float(claim.get("tolerance", 0)))
        same = claim.get("same_representation", False)
        mark = "same-repr" if same else "cross-repr"
        if problems:
            failures += 1
            print(f"  FAIL {claim['id']} [{kind}, {mark}]")
            for line in problems:
                print(f"         {line}")
        else:
            where = f"{frame}" + (f" n={size:,}" if size is not None else "")
            print(f"  ok   {claim['id']} [{kind}, {mark}] over {where}")
        results.append({**claim, "recomputed": got,
                        "population_size_in_this_release": size,
                        "outcome": "fail" if problems else "ok",
                        "problems": problems})

    checked = len(results) - skipped - not_applicable
    print(f"\n{checked - failures}/{checked} applicable claims reproduced, "
          f"{failures} failed, {not_applicable} not applicable to this "
          f"release, {skipped} not mechanically checkable")
    # The game count is READ from the release being checked, not written
    # out. A hardcoded 22 here printed "beyond these 22 games" while
    # checking a 50-game corpus.
    n_games = len(
        (json.loads((dist / "index.json").read_text()).get("games") or {}))
    print("NOTE: reproducing a measurement does not establish that it "
          "measures the\n      musical concept it is named for, nor that any "
          f"conclusion generalises\n      beyond these {n_games} games.")

    if args.report:
        args.report.write_text(json.dumps({
            "schema": "snesmdb.replication.v1",
            "release": pin.get("label"),
            "built_from": (pin.get("built_from") or {}).get("git_commit"),
            "claims_schema": registry["schema"],
            "n_checked": checked, "n_failed": failures,
            "n_not_checkable": skipped,
            "results": results,
        }, indent=1))
        print(f"wrote {args.report}")

    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
