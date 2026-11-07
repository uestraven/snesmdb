#!/usr/bin/env python3
"""Refuse to let copyrighted source or derived corpus data into the repository.

    check_no_derived_data.py [--staged] [--history]

`.gitignore` is not enforcement. It is a default that a sufficiently odd path
slips past, and one did: a directory named `data/out.prebugfix/`, created while
moving a corpus aside during a fix, matched none of the ignore rules, and a
`git add -A` put 3,955 derived files totalling 2.4 GB into public history --
the DSP write logs, the note records and the scores for all 1,316 commercial
tracks. The note records are the musical content the licence actually concerns.

Two things made it possible and both are addressed here rather than only in
`.gitignore`:

  * the ignore list enumerated directories to exclude, so a new sibling name
    was unprotected by construction;
  * `*.jsonl` does not match `*.jsonl.gz`, so the compressed form of the one
     file type most clearly derived was never covered.

So this checks the TRACKED TREE and, optionally, the staged change and the
whole history -- the actual states that matter, rather than the intent
expressed by the ignore file.

Exit code is the number of violations, so it works as a pre-commit hook, a
make target and a CI gate.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

#: Anything under `data/` is derived from or is the copyrighted source
#: material, except these. Kept as an exact allow-list for the same reason the
#: ignore file now denies by default: a prefix rule is a guess about names.
ALLOWED = frozenset({
    "data/spc/.gitkeep",
    "data/spc/README.md",
    "data/out/.gitkeep",
})

#: Extensions that are source material or a derived corpus wherever they sit.
#: `.jsonl.gz` is listed explicitly because the suffix that matters is two
#: parts long and a single-extension check misses it.
FORBIDDEN_SUFFIXES = (
    ".spc", ".rsn",
    ".wav", ".flac", ".mp3", ".ogg",
    ".aram",
    ".mid", ".midi",
    ".jsonl", ".jsonl.gz", ".json.gz",
)


def _git(*args: str) -> list[str]:
    repo = Path(__file__).resolve().parent.parent
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=300,
    )
    if done.returncode != 0:
        return []
    return [line for line in done.stdout.splitlines() if line.strip()]


def violations(paths: list[str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in paths:
        if path in ALLOWED:
            continue
        if path.startswith("data/"):
            found.append((path, "under data/, which holds source and derived corpus"))
            continue
        lowered = path.lower()
        for suffix in FORBIDDEN_SUFFIXES:
            if lowered.endswith(suffix):
                found.append((path, f"{suffix} is source or derived corpus data"))
                break
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--staged", action="store_true",
        help="check what is about to be committed (use as a pre-commit hook)",
    )
    parser.add_argument(
        "--history", action="store_true",
        help="check every path ever added on any ref. Slow, and the only check "
             "that catches data already committed -- a clean working tree says "
             "nothing about what the repository still carries.",
    )
    args = parser.parse_args()

    failures = 0

    tracked = violations(_git("ls-files"))
    print(f"tracked tree: {len(tracked)} violation(s)")
    for path, why in tracked[:20]:
        print(f"  FAIL  {path}  -- {why}")
    failures += len(tracked)

    if args.staged:
        staged = violations(_git("diff", "--cached", "--name-only"))
        print(f"staged change: {len(staged)} violation(s)")
        for path, why in staged[:20]:
            print(f"  FAIL  {path}  -- {why}")
        failures += len(staged)

    if args.history:
        ever = violations(_git(
            "log", "--all", "--pretty=format:", "--name-only", "--diff-filter=A"
        ))
        unique = sorted({p for p, _ in ever})
        print(f"history (all refs): {len(unique)} distinct violating path(s)")
        for path in unique[:10]:
            print(f"  FAIL  {path}")
        if len(unique) > 10:
            print(f"  ... and {len(unique) - 10} more")
        failures += len(unique)

    if not failures:
        print("\nclean: no source or derived corpus data in the checked scope")
    raise SystemExit(min(failures, 125))


if __name__ == "__main__":
    main()
