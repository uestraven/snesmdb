#!/usr/bin/env python3
"""Audit a corrected release against the preserved baseline and the evidence.

    audit_corrected_release.py <baseline-dist> <corrected-dist> <rows.jsonl>
                               <report.json>

Read-only on both trees.

The correction was supposed to change exactly one thing: which sample each
attack is said to use. So the audit's central property is a NEGATIVE one --
every other field of every event is unchanged. A release that also moved an
onset, a pitch, a duration or an event id would be a different dataset
wearing a correction's label, and no amount of agreement on identity counts
would make that acceptable.

Checks, in the order they matter:

    1. structure      same tracks, same event counts, same event ids
    2. invariance     every field except the three identity fields is equal,
                      event by event
    3. identity form  `sample_id` is null or 16 hex digits, never ""; the
                      reason is non-null exactly when the id is null; the
                      source is from the known set
    4. evidence       the per-attack changes match the DSP validation rows,
                      re-derived through the one plausibility rule
    5. coherence      a legato step carries its parent's identity, because a
                      step does not re-key
    6. preservation   the baseline tree is untouched

Counts are compared to the validation rather than to a remembered figure.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import events as events_mod, identity  # noqa: E402

IDENTITY_FIELDS = {
    "sample_id", "sample_id_source", "sample_id_unresolved_reason",
}
HEADER_ADDED = {
    "attacks_with_sample_id", "attacks_without_sample_id",
    "attacks_identity_observed_at_key_on",
}
HEX16 = re.compile(r"^[0-9a-f]{16}$")
SOURCES = {events_mod.SOURCE_OBSERVED, events_mod.SOURCE_CAPTURE,
           events_mod.SOURCE_UNRESOLVED}
REASONS = {events_mod.REASON_IMPLAUSIBLE, events_mod.REASON_NOT_ESTABLISHED,
           events_mod.REASON_NO_DIRECTORY_ENTRY}


def load(dist: Path, rel: str):
    return json.loads(gzip.decompress((dist / rel).read_bytes()))


def tree_digest(dist: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(dist.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(dist)).encode())
            h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline", type=Path)
    ap.add_argument("corrected", type=Path)
    ap.add_argument("rows", type=Path)
    ap.add_argument("report", type=Path)
    ap.add_argument("--baseline-digest", default=None,
                    help="expected sha256 of the baseline tree, to prove it "
                         "was not modified by this process")
    args = ap.parse_args()

    failures: list[str] = []
    notes: list[str] = []

    base_ix = json.loads((args.baseline / "index.json").read_text())
    corr_ix = json.loads((args.corrected / "index.json").read_text())
    base = {e["track_id"]: e for e in base_ix["tracks"]}
    corr = {e["track_id"]: e for e in corr_ix["tracks"]}

    # 1. STRUCTURE
    if set(base) != set(corr):
        only_b, only_c = set(base) - set(corr), set(corr) - set(base)
        failures.append(
            f"track sets differ: {len(only_b)} only in baseline, "
            f"{len(only_c)} only in corrected")

    # 4. EVIDENCE: what the DSP observations say should change.
    expected: dict[tuple[str, int, int], dict] = {}
    for line in args.rows.open():
        row = json.loads(line)
        start, loop = row.get("commit_start"), row.get("commit_loop")
        if start is None:
            continue
        key = (row["track_id"], int(row["voice"]), int(row["ordinal"]))
        if not identity.plausible_entry((start, loop)):
            expected[key] = {"sample_id": None,
                             "source": events_mod.SOURCE_UNRESOLVED}
        elif row.get("now"):
            expected[key] = {"sample_id": row["now"],
                             "source": events_mod.SOURCE_OBSERVED}
        else:
            expected[key] = {"sample_id": None,
                             "source": events_mod.SOURCE_UNRESOLVED}

    stats = collections.Counter()
    mismatch_examples: list[dict] = []
    invariance_examples: list[dict] = []

    for tid in sorted(set(base) & set(corr)):
        b = load(args.baseline, base[tid]["events"])
        c = load(args.corrected, corr[tid]["events"])

        if c["schema"] != events_mod.SCHEMA:
            failures.append(f"{tid}: schema is {c['schema']!r}, "
                            f"expected {events_mod.SCHEMA!r}")
        if len(b["events"]) != len(c["events"]):
            failures.append(
                f"{tid}: event count {len(b['events'])} -> "
                f"{len(c['events'])}; the correction must not add or remove "
                f"events")
            continue

        # 2. INVARIANCE, event by event, in published order.
        ordinals: collections.Counter = collections.Counter()
        for be, ce in zip(b["events"], c["events"]):
            for field in set(be) | set(ce):
                if field in IDENTITY_FIELDS:
                    continue
                if be.get(field) != ce.get(field):
                    stats["events_with_non_identity_change"] += 1
                    if len(invariance_examples) < 20:
                        invariance_examples.append({
                            "track_id": tid, "event_id": be.get("event_id"),
                            "field": field,
                            "baseline": be.get(field),
                            "corrected": ce.get(field),
                        })

            # 3. IDENTITY FORM
            sid = ce.get("sample_id")
            src = ce.get("sample_id_source")
            why = ce.get("sample_id_unresolved_reason")
            if sid == "":
                stats["sample_id_is_empty_string"] += 1
            if sid is not None and not HEX16.match(str(sid)):
                stats["sample_id_malformed"] += 1
            if src not in SOURCES:
                stats["sample_id_source_unknown"] += 1
            if (sid is None) != (why is not None):
                stats["reason_disagrees_with_null_id"] += 1
            if why is not None and why not in REASONS:
                stats["reason_unknown"] += 1

            if ce["origin"] != "key_on":
                continue
            voice = int(ce["voice"])
            ordinal = ordinals[voice]
            ordinals[voice] += 1

            # 4. EVIDENCE, per attack.
            want = expected.get((tid, voice, ordinal))
            if want is None:
                stats["attacks_without_dsp_observation"] += 1
                if sid != (be.get("sample_id") or None):
                    stats["changed_without_evidence"] += 1
                    if len(mismatch_examples) < 20:
                        mismatch_examples.append({
                            "track_id": tid, "voice": voice,
                            "ordinal": ordinal, "reason": "no observation",
                            "baseline": be.get("sample_id"),
                            "corrected": sid})
                continue
            if sid != want["sample_id"] or src != want["source"]:
                stats["attacks_disagreeing_with_evidence"] += 1
                if len(mismatch_examples) < 20:
                    mismatch_examples.append({
                        "track_id": tid, "voice": voice, "ordinal": ordinal,
                        "expected": want, "published_id": sid,
                        "published_source": src})
            else:
                stats["attacks_agreeing_with_evidence"] += 1

            was = be.get("sample_id") or None
            if was == sid:
                stats["identity_unchanged"] += 1
            elif was is None:
                stats["identity_established_where_none"] += 1
            elif sid is None:
                stats["identity_withdrawn_to_null"] += 1
            else:
                stats["identity_replaced"] += 1

        # 5. COHERENCE: a step sounds its parent's sample.
        by_id = {e["event_id"]: e for e in c["events"]}
        for ce in c["events"]:
            if ce["origin"] == "key_on":
                continue
            parent = by_id.get(ce.get("parent_event_id"))
            if parent is None:
                continue
            if ce.get("sample_id") != parent.get("sample_id"):
                stats["steps_disagreeing_with_parent"] += 1

        # header counts must describe the events in the same file
        attacks = [e for e in c["events"] if e["origin"] == "key_on"]
        if c.get("attacks_with_sample_id") != sum(
                1 for e in attacks if e["sample_id"]):
            stats["header_attacks_with_sample_id_wrong"] += 1
        if c.get("attacks_without_sample_id") != sum(
                1 for e in attacks if not e["sample_id"]):
            stats["header_attacks_without_sample_id_wrong"] += 1

    for name in ("events_with_non_identity_change", "sample_id_is_empty_string",
                 "sample_id_malformed", "sample_id_source_unknown",
                 "reason_disagrees_with_null_id", "reason_unknown",
                 "attacks_disagreeing_with_evidence",
                 "changed_without_evidence", "steps_disagreeing_with_parent",
                 "header_attacks_with_sample_id_wrong",
                 "header_attacks_without_sample_id_wrong"):
        if stats[name]:
            failures.append(f"{name}: {stats[name]:,}")

    # 6. PRESERVATION
    digest = tree_digest(args.baseline)
    if args.baseline_digest and digest != args.baseline_digest:
        failures.append(
            f"baseline tree digest changed: expected "
            f"{args.baseline_digest}, got {digest}")

    verdict = "PASS" if not failures else f"FAIL ({len(failures)} checks)"
    args.report.write_text(json.dumps({
        "schema": "snesmdb.corrected_release_audit.v1",
        "verdict": verdict,
        "baseline": str(args.baseline),
        "baseline_tree_sha256": digest,
        "corrected": str(args.corrected),
        "tracks_compared": len(set(base) & set(corr)),
        "counts": dict(stats),
        "failures": failures,
        "invariance_examples": invariance_examples,
        "evidence_mismatch_examples": mismatch_examples,
        "notes": notes,
    }, indent=1))

    print(f"{verdict}   {len(set(base) & set(corr)):,} tracks compared")
    print(f"baseline tree sha256: {digest[:16]}...")
    for k, v in sorted(stats.items()):
        print(f"  {k:44} {v:12,}")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
