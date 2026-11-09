#!/usr/bin/env python3
"""Compare an accepted pre-v4 extraction against its native v4 re-extraction.

    compare_native_v4.py <accepted-dist> <native-dist> <report.json>

Read-only on both trees.

This is a REGRESSION comparison, not an audit of the new tree -- the subset
verifier does that. The question here is narrower and sharper: re-running a
game through the validated pipeline must change identity and pitch only, and
must change nothing about what notes exist or when they happen.

So the fields split three ways, and the split is the whole design:

    INVARIANT      event counts and ids, origin, parent, onset, duration,
                   voice, pitch_register, attack and sustain levels. A
                   difference here is a defect in the re-extraction, not a
                   result. The pipeline was not supposed to touch them.
    COMPARED       sample identity, and pitch. Both are EXPECTED to move,
                   because native v4 resolves identity before pitch is
                   estimated rather than after. Every change is classified
                   and counted; none is assumed benign.
    PROVENANCE     every non-null identity in the new tree must say it was
                   observed at key-on. A published identity that silently
                   fell back to the capture-time directory is the failure
                   this catches, and it looks identical to a good one
                   without this check.

Pitch is reported as recovered / changed / lost / unchanged. `lost` is the
category that matters: native v4 is expected to recover pitch, so losing it
anywhere needs an explanation rather than a net figure that hides it.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import events as events_mod  # noqa: E402

#: Fields the re-extraction must not move. `event_id` and `parent_event_id`
#: are here because a reader may have stored them.
INVARIANT = (
    "event_id", "parent_event_id", "origin", "onset_sec", "duration_sec",
    "voice", "pitch_register", "attack_level", "sustain_level",
)
HEX16 = re.compile(r"^[0-9a-f]{16}$")


def load(dist: Path, rel: str):
    return json.loads(gzip.decompress((dist / rel).read_bytes()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("accepted", type=Path)
    ap.add_argument("native", type=Path)
    ap.add_argument("report", type=Path)
    args = ap.parse_args()

    old_ix = json.loads((args.accepted / "index.json").read_text())
    new_ix = json.loads((args.native / "index.json").read_text())
    old = {e["track_id"]: e for e in old_ix["tracks"]}
    new = {e["track_id"]: e for e in new_ix["tracks"]}

    failures: list[str] = []
    stats: collections.Counter = collections.Counter()
    identity_changes: list[dict] = []
    invariance: list[dict] = []
    pitch_lost: list[dict] = []
    reasons: collections.Counter = collections.Counter()

    if set(old) != set(new):
        failures.append(
            f"track sets differ: {len(set(old) - set(new))} only accepted, "
            f"{len(set(new) - set(old))} only native")

    for tid in sorted(set(old) & set(new)):
        a = load(args.accepted, old[tid]["events"])
        b = load(args.native, new[tid]["events"])

        # Counts must reconcile exactly, per origin as well as in total: a
        # key-on turning into a step would keep the total and change the data.
        for field in ("event_count", "attack_count", "legato_step_count"):
            if a.get(field) != b.get(field):
                failures.append(
                    f"{tid}: {field} {a.get(field)} -> {b.get(field)}")
        if len(a["events"]) != len(b["events"]):
            failures.append(f"{tid}: event list length differs")
            continue

        ordinals: collections.Counter = collections.Counter()
        for ea, eb in zip(a["events"], b["events"]):
            for field in INVARIANT:
                if ea.get(field) != eb.get(field):
                    stats["invariant_field_changed"] += 1
                    if len(invariance) < 20:
                        invariance.append({
                            "track_id": tid, "event_id": ea.get("event_id"),
                            "field": field, "accepted": ea.get(field),
                            "native": eb.get(field)})

            # PROVENANCE, on every event of the new tree.
            sid = eb.get("sample_id")
            if sid == "":
                stats["native_sample_id_empty_string"] += 1
            elif sid is not None:
                if not HEX16.match(str(sid)):
                    stats["native_sample_id_malformed"] += 1
                if eb.get("sample_id_source") != events_mod.SOURCE_OBSERVED:
                    stats["identity_without_v4_provenance"] += 1
            else:
                reasons[eb.get("sample_id_unresolved_reason")] += 1

            if eb["origin"] != "key_on":
                continue
            stats["attacks"] += 1

            # IDENTITY, per attack.
            was = ea.get("sample_id") or None
            if was == sid:
                stats["identity_unchanged"] += 1
            else:
                kind = ("identity_established" if was is None else
                        "identity_withdrawn" if sid is None else
                        "identity_replaced")
                stats[kind] += 1
                if len(identity_changes) < 40:
                    identity_changes.append({
                        "track_id": tid, "voice": eb["voice"],
                        "ordinal": ordinals[eb["voice"]],
                        "kind": kind, "accepted": was, "native": sid,
                        "reason": eb.get("sample_id_unresolved_reason")})
            ordinals[eb["voice"]] += 1

            # PITCH, per attack.
            pa = ea.get("midi_note")
            pb = eb.get("midi_note")
            if pa is None and pb is not None:
                stats["pitch_recovered"] += 1
            elif pa is not None and pb is None:
                stats["pitch_lost"] += 1
                if len(pitch_lost) < 40:
                    pitch_lost.append({
                        "track_id": tid, "voice": eb["voice"],
                        "accepted_midi": pa,
                        "native_status": eb.get("pitch_status"),
                        "native_sample_id": sid})
            elif pa is None and pb is None:
                stats["pitch_absent_in_both"] += 1
            elif abs(float(pa) - float(pb)) > 1e-6:
                stats["pitch_changed"] += 1
            else:
                stats["pitch_unchanged"] += 1

    for name in ("invariant_field_changed", "native_sample_id_empty_string",
                 "native_sample_id_malformed",
                 "identity_without_v4_provenance"):
        if stats[name]:
            failures.append(f"{name}: {stats[name]:,}")

    verdict = "PASS" if not failures else f"FAIL ({len(failures)} checks)"
    args.report.write_text(json.dumps({
        "schema": "snesmdb.native_v4_comparison.v1",
        "verdict": verdict,
        "accepted": str(args.accepted), "native": str(args.native),
        "tracks_compared": len(set(old) & set(new)),
        "counts": dict(stats),
        "unresolved_reasons": {str(k): v for k, v in reasons.items()},
        "failures": failures,
        "invariance_examples": invariance,
        "identity_change_examples": identity_changes,
        "pitch_lost_examples": pitch_lost,
        "note": (
            "Identity and pitch are EXPECTED to move: native v4 resolves "
            "identity before pitch is estimated rather than after. Event "
            "structure and timing are not expected to move at all."
        ),
    }, indent=1))

    print(f"{verdict}   {len(set(old) & set(new)):,} tracks, "
          f"{stats['attacks']:,} attacks")
    for k, v in sorted(stats.items()):
        print(f"  {k:36} {v:10,}")
    if reasons:
        print(f"  unresolved reasons: "
              + ", ".join(f"{k} {v:,}" for k, v in reasons.most_common()))
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
