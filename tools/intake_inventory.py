#!/usr/bin/env python3
"""Inventory newly supplied SPC sets before any corpus build.

    intake_inventory.py <spc-dir> <report.json> --games NAME [NAME ...]
                        [--existing-index PATH]

Read-only. Reads SPC headers and ID666 tags; decodes no audio and writes no
derived data.

Run BEFORE extraction, because extraction answers a different question. A
build tells you what came out; an intake tells you what went in, and the
difference is where silent loss lives: a duplicate rip counted as two
tracks, a slug colliding with an accepted game, a file the loader rejects
and nobody counts.

Every source file is accounted for -- accepted, excluded, or unresolved,
with a reason. A count that does not reconcile against the directory
listing is reported as a defect rather than printed as a total.

ATTRIBUTION IS RECORDED, NEVER COMPLETED. An ID666 credit truncated at 32
bytes yields a trailing fragment, and `composer_truncated` marks it. The
fragment is preserved verbatim and never expanded to a familiar name:
`Ke` covers 206 Earthbound tracks in the accepted corpus and is not an
author identity. Externally supplied or game-level credits are not mixed in.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import spcfile  # noqa: E402

#: Titles that signal a non-music cue. Only a HINT for the intake report;
#: the authoritative classification is `trackclass` during extraction.
HINTS = (
    ("effect", r"\b(sfx|sound\s*effect|jingle\s*sfx|voice|beep)\b"),
    ("jingle", r"\b(fanfare|logo|title|game\s*over|victory|jingle|"
               r"level\s*(up|clear)|continue|intro)\b"),
    ("drone", r"\b(ambien|drone|wind|rain|cave|silence)\b"),
)


def slugify(name: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return out


def hint_class(title: str) -> str:
    low = (title or "").lower()
    for label, pattern in HINTS:
        if re.search(pattern, low):
            return label
    return "music"


#: Source material excluded by scope decision rather than by defect, keyed
#: by a substring of the ID666 game tag. Each entry records WHY, because an
#: excluded file that reconciles into a count with no reason is
#: indistinguishable from one that was lost.
#:
#: The Mario Paint set contains 22 SPCs tagged `Mario Paint (Prototype)`:
#: an unreleased build, not a regional release. Grouping it as a game family
#: would assert it is the same work as the retail game, which it is not, and
#: publishing it as a separate game would exceed the declared scope. It is
#: excluded, and the 37 retail tracks are retained under the canonical
#: identity.
TAG_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    ("Mario Paint (Prototype)", "unreleased_prototype_out_of_scope"),
)


def tag_exclusion(game_tag: str) -> str | None:
    for needle, reason in TAG_EXCLUSIONS:
        if needle and needle in (game_tag or ""):
            return reason
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spc_dir", type=Path)
    ap.add_argument("report", type=Path)
    ap.add_argument("--games", nargs="+", required=True)
    ap.add_argument("--existing-index", type=Path, action="append", default=[])
    args = ap.parse_args()

    existing_slugs: dict[str, str] = {}
    existing_hashes: dict[str, str] = {}
    for path in args.existing_index:
        index = json.loads(path.read_text())
        for entry in index.get("tracks", []):
            if entry.get("game_slug"):
                existing_slugs[entry["game_slug"]] = entry["game"]
            if entry.get("sha256_source_spc"):
                existing_hashes[entry["sha256_source_spc"]] = \
                    entry["track_id"]

    games: list[dict] = []
    totals: collections.Counter = collections.Counter()
    seen_hashes: dict[str, str] = {}
    all_slugs: dict[str, str] = {}

    for name in args.games:
        base = args.spc_dir / name
        if not base.is_dir():
            games.append({"directory": name, "error": "directory not found"})
            totals["games_missing"] += 1
            continue

        files = sorted(p for p in base.rglob("*") if p.is_file())
        spcs = [p for p in files if p.suffix.lower() == ".spc"]
        others = [p for p in files if p.suffix.lower() != ".spc"]

        accepted, excluded, unresolved = [], [], []
        titles: collections.Counter = collections.Counter()
        credits: collections.Counter = collections.Counter()
        truncated_credits: set[str] = set()
        fragments: set[str] = set()
        classes: collections.Counter = collections.Counter()
        tag_fields: collections.Counter = collections.Counter()
        game_labels: collections.Counter = collections.Counter()
        seconds: list[float] = []

        for path in spcs:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            try:
                spc = spcfile.load(path)
            except Exception as exc:
                excluded.append({
                    "file": path.name, "sha256": digest[:16],
                    "reason": f"loader rejected: "
                              f"{type(exc).__name__}: {exc}"[:160]})
                continue

            reason = tag_exclusion(spc.tag.game)
            if reason:
                excluded.append({
                    "file": path.name, "sha256": digest[:16],
                    "game_tag": spc.tag.game,
                    "title": spc.tag.title,
                    "reason": reason,
                    "excluded_by": "scope_decision",
                })
                continue
            if digest in seen_hashes:
                excluded.append({
                    "file": path.name, "sha256": digest[:16],
                    "reason": f"byte-identical duplicate of "
                              f"{seen_hashes[digest]}"})
                continue
            if digest in existing_hashes:
                excluded.append({
                    "file": path.name, "sha256": digest[:16],
                    "reason": f"already in the accepted corpus as "
                              f"{existing_hashes[digest]}"})
                continue
            seen_hashes[digest] = f"{name}/{path.name}"

            tag = spc.tag
            for field in ("title", "game", "composer", "dumper"):
                if getattr(tag, field, "") or (
                        field == "composer" and tag.composer):
                    tag_fields[field] += 1
            if tag.game:
                game_labels[tag.game] += 1
            titles[tag.title or "<untitled>"] += 1
            names = [c for c in (tag.composers or []) if c]
            for credit in names:
                credits[credit] += 1
                if tag.composer_truncated:
                    truncated_credits.add(credit)
            if tag.composer_truncated and names:
                fragments.add(names[-1])
            classes[hint_class(tag.title)] += 1
            if getattr(tag, "seconds", 0):
                seconds.append(float(tag.seconds))

            accepted.append({
                "file": path.name, "sha256": digest[:16],
                "title": tag.title, "game_tag": tag.game,
                "composer_verbatim": tag.composer,
                "composers_parsed": names,
                "composer_truncated": bool(tag.composer_truncated),
                "title_hint_class": hint_class(tag.title),
            })

        slug = slugify(name)
        collision = existing_slugs.get(slug) or all_slugs.get(slug)
        all_slugs[slug] = name

        dupe_titles = {t: n for t, n in titles.items() if n > 1}
        games.append({
            "directory": name,
            "slug": slug,
            "slug_collision": collision,
            "source_files_total": len(files),
            "source_spc_files": len(spcs),
            "non_spc_files": [p.name for p in others][:10],
            "accepted": len(accepted),
            "excluded": len(excluded),
            "unresolved": len(unresolved),
            "reconciles": len(accepted) + len(excluded) + len(unresolved)
                          == len(spcs),
            "game_tag_labels": dict(game_labels),
            "tag_field_coverage": {
                k: f"{v}/{len(accepted)}" for k, v in tag_fields.items()},
            "distinct_recorded_credits": sorted(credits),
            "credits_truncated": sorted(truncated_credits),
            "truncation_fragments": sorted(fragments),
            "duplicate_or_ambiguous_titles": dupe_titles,
            "title_hint_classes": dict(classes),
            "tag_seconds": {
                "n": len(seconds),
                "min": round(min(seconds), 1) if seconds else None,
                "max": round(max(seconds), 1) if seconds else None,
            },
            "accepted_files": accepted,
            "excluded_files": excluded,
        })
        totals["games"] += 1
        totals["source_spc"] += len(spcs)
        totals["accepted"] += len(accepted)
        totals["excluded"] += len(excluded)
        for item in excluded:
            totals[f"excluded:{item['reason']}"] += 1

    problems = []
    for game in games:
        if game.get("error"):
            problems.append(f"{game['directory']}: {game['error']}")
            continue
        if not game["reconciles"]:
            problems.append(
                f"{game['directory']}: {game['source_spc_files']} SPC files "
                f"but {game['accepted']}+{game['excluded']}+"
                f"{game['unresolved']} accounted for")
        if game["slug_collision"]:
            problems.append(
                f"{game['directory']}: slug {game['slug']!r} collides with "
                f"{game['slug_collision']!r}")
        if game["accepted"] == 0:
            problems.append(f"{game['directory']}: no accepted sources")

    args.report.write_text(json.dumps({
        "schema": "snesmdb.intake_inventory.v1",
        "spc_dir": str(args.spc_dir),
        "games_requested": args.games,
        "totals": dict(totals),
        "problems": problems,
        "attribution_note": (
            "Credits are the verbatim ID666 artist field, comma-split. A "
            "truncated field's trailing element is a FRAGMENT, flagged in "
            "`truncation_fragments`, and is not an author identity. No "
            "fragment is expanded and no external credit is merged in."
        ),
        "classification_note": (
            "`title_hint_class` is a keyword guess from the title, for "
            "intake only. The authoritative class is assigned during "
            "extraction by `trackclass`."
        ),
        "games": games,
    }, indent=1))

    print(f"{totals['games']} games, {totals['source_spc']:,} source SPC "
          f"files, {totals['accepted']:,} accepted, "
          f"{totals['excluded']:,} excluded\n")
    print(f"{'game':34}{'spc':>5}{'acc':>5}{'exc':>5}{'credits':>9}"
          f"{'trunc':>7}  titles/classes")
    for game in games:
        if game.get("error"):
            print(f"{game['directory'][:32]:34}  {game['error']}")
            continue
        cls = game["title_hint_classes"]
        print(f"{game['directory'][:32]:34}{game['source_spc_files']:>5}"
              f"{game['accepted']:>5}{game['excluded']:>5}"
              f"{len(game['distinct_recorded_credits']):>9}"
              f"{len(game['credits_truncated']):>7}  "
              f"{dict(sorted(cls.items()))}")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("\nall source files accounted for; no slug collisions")


if __name__ == "__main__":
    main()
