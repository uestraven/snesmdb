#!/usr/bin/env python3
"""How strong is the composer separation, really?

    audit_attribution.py <dist-dir> <report.json>

Read-only, published artifacts only.

The split assignment reports composer-disjointness, and that check compares
RECORDED CREDIT STRINGS. 287 of 1,477 tracks carry a credit truncated at
ID666's 32-byte field, so the strings being compared are not identities, and
two splits can hold the same person under two different truncations while
the check reports disjoint.

This audit refuses to resolve that by recognising names. Expanding
`Yoshihiro Sakaguchi, Yoko Shimom` to a familiar full name would be the
auditor supplying evidence the dataset does not contain, and a truncated
credit may list several contributors whose individual track-level authorship
is not recorded at all.

So overlap is tested two ways, both mechanical:

    PREFIX CONTAINMENT  a truncated credit is a prefix of a credit in
                        another split. Objective evidence that the two may
                        name the same person or group.
    SHARED CONTRIBUTOR  two credits, split on commas, share a named
                        contributor. A game-level credit listing three
                        people does not establish which of them wrote a
                        given track, so a shared name is a possible overlap
                        rather than a confirmed one.

The output is a claim, graded. "Recorded-credit-disjoint" is what the data
supports unless the mechanical tests come back empty.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

SPLITS = ("train", "valid", "test")


def contributors(credit: str) -> list[str]:
    """Named contributors within one credit string.

    The pipeline already splits a comma-separated ID666 credit into separate
    entries, so this normally returns one name. Kept for credits that were
    not split.
    """
    parts = [p.strip() for p in credit.split(",")]
    return [p for p in parts if p]


def fragments_of(entry: dict) -> set[str]:
    """Credits in this entry that are CUT OFF, not names.

    `composers` is the ID666 credit split on commas. When the tag itself was
    truncated at 32 bytes the final element is the severed remainder of a
    name -- `Ke` for Earthbound, `Kazu` for Batman Returns -- and the
    pipeline stores it as though it were a composer.

    This matters because splits are assigned BY COMPOSER. A fragment is not
    an identity: it cannot be matched against a full name without guessing,
    and two different people can share a four-letter prefix. 206 of 1,477
    tracks are attributed to `Ke`.
    """
    names = [c for c in (entry.get("composers") or []) if c]
    if not names or not entry.get("composer_truncated"):
        return set()
    return {names[-1]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist", type=Path)
    ap.add_argument("report", type=Path)
    args = ap.parse_args()

    index = json.loads((args.dist / "index.json").read_text())

    tiers: collections.Counter = collections.Counter()
    credit_splits: dict[str, set[str]] = collections.defaultdict(set)
    credit_truncated: dict[str, bool] = {}
    credit_tracks: dict[str, int] = collections.Counter()
    credit_games: dict[str, set[str]] = collections.defaultdict(set)
    multi_contributor_tracks = 0
    fragment_credits: dict[str, set[str]] = collections.defaultdict(set)
    fragment_tracks: dict[str, int] = collections.Counter()

    for entry in index["tracks"]:
        split = entry.get("split")
        names = [c for c in (entry.get("composers") or []) if c]
        truncated = bool(entry.get("composer_truncated"))
        if not names:
            tiers["absent"] += 1
            continue
        for credit in names:
            credit_splits[credit].add(split)
            credit_truncated[credit] = truncated
            credit_tracks[credit] += 1
            credit_games[credit].add(entry.get("game"))
        if truncated:
            tiers["incomplete_recorded_credit"] += 1
        else:
            tiers["complete_recorded_credit"] += 1
        if len(names) > 1:
            multi_contributor_tracks += 1
            tiers["credit_lists_several_contributors"] += 1
        for frag in fragments_of(entry):
            fragment_credits[frag].add(split)
            fragment_tracks[frag] += 1

    credits = sorted(credit_splits)

    # 1. A credit appearing in more than one split outright.
    direct = {c: sorted(credit_splits[c]) for c in credits
              if len(credit_splits[c]) > 1}

    # 2. PREFIX CONTAINMENT: a truncated credit is a prefix of another.
    prefix_overlaps = []
    for short in credits:
        if not credit_truncated.get(short):
            continue
        for other in credits:
            if other == short or not other.startswith(short):
                continue
            a, b = credit_splits[short], credit_splits[other]
            if a & b and len(a | b) == 1:
                continue
            if a - b or b - a:
                prefix_overlaps.append({
                    "truncated_credit": short,
                    "longer_credit": other,
                    "truncated_in_splits": sorted(a),
                    "longer_in_splits": sorted(b),
                    "cross_split": bool((a | b) - (a & b)) and len(a | b) > 1,
                })

    # 3. SHARED CONTRIBUTOR across splits.
    contributor_splits: dict[str, set[str]] = collections.defaultdict(set)
    contributor_credits: dict[str, set[str]] = collections.defaultdict(set)
    for credit in credits:
        for name in contributors(credit):
            contributor_splits[name] |= credit_splits[credit]
            contributor_credits[name].add(credit)
    shared_contributors = {
        name: {"splits": sorted(s),
               "credits": sorted(contributor_credits[name])}
        for name, s in contributor_splits.items() if len(s) > 1
    }

    cross_prefix = [p for p in prefix_overlaps if p["cross_split"]]

    # A fragment that prefixes a full credit in another split is the
    # clearest unresolved overlap the data can show: it may be the same
    # person, and nothing published decides it.
    fragment_prefix_overlaps = []
    for frag, frag_splits in fragment_credits.items():
        for credit in credits:
            if credit == frag or not credit.startswith(frag):
                continue
            other = credit_splits[credit]
            if other - frag_splits:
                fragment_prefix_overlaps.append({
                    "fragment": frag,
                    "fragment_tracks": fragment_tracks[frag],
                    "fragment_splits": sorted(frag_splits),
                    "candidate_full_credit": credit,
                    "candidate_splits": sorted(other),
                })
    confirmed = direct
    possible = {
        "prefix_containment_across_splits": cross_prefix,
        "shared_contributor_across_splits": shared_contributors,
        "truncation_fragment_prefixes_a_credit_in_another_split":
            fragment_prefix_overlaps,
    }

    if confirmed:
        claim = (
            "NOT composer-disjoint: a recorded credit appears in more than "
            "one split.")
    elif cross_prefix or shared_contributors or fragment_prefix_overlaps:
        claim = (
            "RECORDED-CREDIT-DISJOINT, WITH UNRESOLVED AUTHORSHIP OVERLAPS. "
            "No credit string spans two splits, but mechanical tests find "
            "credits that may name the same person or group across splits. "
            "The data does not resolve them, so held-out-COMPOSER "
            "generalisation is not established. The defensible claim is "
            "held-out-GAME evaluation.")
    else:
        claim = (
            "RECORDED-CREDIT-DISJOINT, with no mechanical evidence of "
            "cross-split authorship overlap. Still weaker than verified "
            "authorship: 287 credits are truncated and track-level "
            "authorship is not recorded for multi-contributor credits.")

    out = {
        "schema": "snesmdb.attribution_audit.v1",
        "dist": str(args.dist),
        "claim": claim,
        "tiers": dict(tiers),
        "tracks_with_multi_contributor_credit": multi_contributor_tracks,
        "distinct_credits": len(credits),
        "distinct_credits_truncated": sum(
            1 for c in credits if credit_truncated.get(c)),
        "truncation_fragments_used_as_composer_names": {
            f: {"tracks": fragment_tracks[f], "splits": sorted(s)}
            for f, s in sorted(fragment_credits.items())},
        "tracks_attributed_to_a_fragment": sum(fragment_tracks.values()),
        "confirmed_cross_split_credits": confirmed,
        "possible_cross_split_overlaps": possible,
        "credits": [
            {"credit": c, "truncated": credit_truncated.get(c),
             "tracks": credit_tracks[c], "splits": sorted(credit_splits[c]),
             "games": sorted(g for g in credit_games[c] if g),
             "contributors_named": contributors(c)}
            for c in credits
        ],
        "method_limits": (
            "Credits are compared as strings. No truncated credit is "
            "expanded to a familiar name: that would be the auditor adding "
            "evidence the dataset lacks. A negative result bounds what these "
            "tests cover, not what is true."
        ),
    }
    args.report.write_text(json.dumps(out, indent=1))

    print(f"distinct recorded credits: {len(credits)}  "
          f"({out['distinct_credits_truncated']} truncated)")
    print(f"tiers: {dict(tiers)}")
    print(f"tracks whose credit names several contributors: "
          f"{multi_contributor_tracks:,}\n")
    print(f"confirmed cross-split credits: {len(confirmed)}")
    print(f"possible overlaps by prefix containment: {len(cross_prefix)}")
    print(f"possible overlaps by shared contributor: "
          f"{len(shared_contributors)}")
    print(f"truncation fragments used as composer names: "
          f"{len(fragment_credits)} covering "
          f"{sum(fragment_tracks.values()):,} tracks")
    for f, sp in sorted(fragment_credits.items()):
        print(f"   {f!r:12} {fragment_tracks[f]:4} tracks  {sorted(sp)}")
    print(f"fragment-prefixes-a-credit overlaps: "
          f"{len(fragment_prefix_overlaps)}")
    for o in fragment_prefix_overlaps[:10]:
        print(f"   {o['fragment']!r} ({o['fragment_tracks']} tracks, "
              f"{o['fragment_splits']}) prefixes "
              f"{o['candidate_full_credit']!r} {o['candidate_splits']}")
    for name, info in list(shared_contributors.items())[:10]:
        print(f"   {name!r} in {info['splits']} via {info['credits']}")
    for p in cross_prefix[:10]:
        print(f"   {p['truncated_credit']!r} {p['truncated_in_splits']} "
              f"is a prefix of {p['longer_credit']!r} "
              f"{p['longer_in_splits']}")
    print(f"\nCLAIM: {claim}")


if __name__ == "__main__":
    main()
