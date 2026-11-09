#!/usr/bin/env python3
"""Did unifying the plausibility rule change what the publisher emits?

    verify_publisher_rule_change.py <out-dir> <spc-dir> <report.json>

Read-only. Touches no published artifact.

The publisher's gate used to be `start != 0 and loop >= start`. It now also
rejects `$FFFF`, the fill byte of an unpopulated directory. The two rules
therefore disagree on EXACTLY ONE input:

    start == $FFFF and loop >= $FFFF  ->  i.e. the entry ($FFFF, $FFFF)

and on nothing else, because every other rejection is shared. So the
question "does the stricter rule change the output" reduces to a search: is
there any track, among the SRCNs it actually references, whose directory
entry is ($FFFF, $FFFF)?

For every such entry found, this then RUNS the old code path -- decode, and
mint if it decoded to anything -- and records what the old publisher would
have emitted. It does not assume the decode would have raised. That
assumption is plausible (address $FFFF leaves nine bytes of header and
samples hanging off the end of a 64 KiB address space) but an assumption is
not a measurement, and the entire reason this check exists is that an
earlier inference of exactly that shape was wrong.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import brr, identity, spcfile  # noqa: E402

FILL = 0xFFFF


def old_rule(start: int, loop: int) -> bool:
    """The publisher's gate before unification, reproduced verbatim."""
    return start != 0 and loop >= start


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("out_dir", type=Path)
    p.add_argument("spc_dir", type=Path)
    p.add_argument("report", type=Path)
    args = p.parse_args()

    spcs = {q.name: q for q in args.spc_dir.rglob("*.spc")}
    rows = [json.loads(l) for l in
            (args.out_dir / "manifest.jsonl").read_text().splitlines()
            if l.strip()]
    rows = [r for r in rows if r.get("ok") and r["source"] in spcs]

    counts = collections.Counter()
    divergent: list[dict] = []
    entries_examined = 0

    for row in rows:
        spc = spcfile.load(spcs[row["source"]])
        srcns = {int(k) for k in (row.get("samples") or {})}
        if not srcns:
            counts["tracks_with_no_referenced_srcn"] += 1
            continue
        counts["tracks_examined"] += 1
        table = brr.read_directory(spc.aram, spc.dsp[0x5D], srcns)
        for srcn, entry in table.items():
            entries_examined += 1
            was = old_rule(entry.start, entry.loop)
            now = identity.plausible_entry((entry.start, entry.loop))
            if was == now:
                continue
            counts["entries_where_the_rules_disagree"] += 1
            # Run the OLD path and see what it would actually have emitted.
            old_emitted = None
            old_error = None
            try:
                decoded = brr.decode(spc.aram, entry.start, entry.loop)
                if decoded.data:
                    from snesmdb import sampleid
                    old_emitted = sampleid.sample_id(
                        decoded.data, decoded.loop_offset)
                else:
                    old_error = "decoded to no samples"
            except Exception as exc:
                old_error = f"{type(exc).__name__}: {exc}"
            counts["old_path_would_have_emitted_an_identity"
                   if old_emitted else
                   "old_path_emitted_nothing_anyway"] += 1
            divergent.append({
                "track_id": row["track_id"],
                "game": (row.get("tag") or {}).get("game"),
                "srcn": srcn,
                "start": entry.start, "loop": entry.loop,
                "old_rule_accepted": was, "new_rule_accepts": now,
                "old_path_identity": old_emitted,
                "old_path_outcome": old_error,
            })

    changed = counts["old_path_would_have_emitted_an_identity"]
    verdict = (
        "IDENTICAL: the stricter rule rejects no entry the old publisher "
        "would have emitted an identity for, so published output is "
        "unchanged."
        if changed == 0 else
        f"CHANGED: {changed} published identities would differ."
    )
    args.report.write_text(json.dumps({
        "schema": "snesmdb.publisher_rule_change.v1",
        "verdict": verdict,
        "rules": {
            "old": "start != 0 and loop >= start",
            "new": "start not in (0, 0xFFFF) and loop >= start",
            "sole_divergent_input": "(0xFFFF, 0xFFFF)",
        },
        "directory_entries_examined": entries_examined,
        "counts": dict(counts),
        "divergent_entries": divergent[:200],
        "method": (
            "For every entry where the rules disagree, the OLD publisher path "
            "was executed -- decode, then mint if it produced samples -- and "
            "its actual result recorded. Nothing was inferred from the "
            "expectation that the decode would raise."
        ),
    }, indent=1))

    print(f"{counts['tracks_examined']:,} tracks, "
          f"{entries_examined:,} referenced directory entries")
    for k, v in counts.most_common():
        print(f"  {k:46} {v:8,}")
    print(f"\n{verdict}")
    for d in divergent[:10]:
        print(f"  {d['track_id']} srcn={d['srcn']} "
              f"({d['start']:#06x},{d['loop']:#06x}) -> "
              f"{d['old_path_identity'] or d['old_path_outcome']}")


if __name__ == "__main__":
    main()
