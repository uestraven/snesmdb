#!/usr/bin/env python3
"""Pin a published corpus so an evaluation names one exact artifact.

    freeze_release.py <dist-dir> [--label rc1]
    freeze_release.py <dist-dir> --verify

Writes `RELEASE.json` into the tree: the commit that built it, the corpus
counts it claims, and a SHA-256 for every published file. `--verify` re-reads
the tree and reports every file that changed, appeared or went missing.

WHY THIS EXISTS. An independent evaluation is only evidence if everyone can
say which bytes were evaluated. Without a freeze, a corpus is whatever the
last `make corpus` produced, so a disagreement between the evaluator's number
and ours cannot be separated into "they read it differently" and "they read
something else". That distinction is the whole value of the exercise.

It also catches the quieter failure: a tree that was rebuilt mid-evaluation.
`provenance.json` records the commit but says nothing about whether the files
still match it, because the publish could have been interrupted or a file
touched afterwards.

This writes INSIDE the published tree, which is outside the repository by
construction -- the corpus is derived from research-only SPCs and must never
be committed. The directory is refused if it is inside a git work tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import corpus as corpus_mod, provenance as provenance_mod  # noqa: E402

SCHEMA = "snesmdb.release.v1"

#: The name of the pin itself, excluded from the hashes it contains.
RELEASE_FILE = "RELEASE.json"

#: Read in chunks: the tree is a few gigabytes and a release should not need
#: to hold a file in memory to hash it.
CHUNK = 1 << 20


def _inside_git(path: Path) -> bool:
    done = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True,
    )
    return done.returncode == 0 and done.stdout.strip() == "true"


def digest(path: Path) -> str:
    out = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            out.update(block)
    return out.hexdigest()


def inventory(dist: Path) -> dict[str, dict[str, Any]]:
    """Every published file, by tree-relative path."""
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(dist.rglob("*")):
        if not path.is_file() or path.name == RELEASE_FILE:
            continue
        key = path.relative_to(dist).as_posix()
        found[key] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return found


def build(dist: Path, label: str) -> dict[str, Any]:
    index_path = dist / "index.json"
    if not index_path.is_file():
        raise SystemExit(f"no index.json in {dist}; nothing to freeze")
    raw = json.loads(index_path.read_text())
    files = inventory(dist)
    return {
        "schema": SCHEMA,
        "label": label,
        "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # The index's own claims, copied so a mismatch between what the
        # corpus says about itself and what it contains is visible here.
        "index_schema": raw.get("schema") if isinstance(raw, dict) else None,
        "formats": raw.get("formats", {}) if isinstance(raw, dict) else {},
        "corpus": raw.get("corpus", {}) if isinstance(raw, dict) else {},
        "n_tracks_in_index": len(corpus_mod.tracks_of(raw)),
        "n_files": len(files),
        "total_bytes": sum(f["bytes"] for f in files.values()),
        # The code that produced the tree, not just the tree.
        "built_by": provenance_mod.record(tool="freeze_release.py"),
        "files": files,
    }


def verify(dist: Path) -> int:
    """Differences between the pin and the tree. Exit code is the count."""
    path = dist / RELEASE_FILE
    if not path.is_file():
        raise SystemExit(f"no {RELEASE_FILE} in {dist}; nothing to verify")
    pinned = json.loads(path.read_text())
    recorded: dict[str, dict[str, Any]] = pinned.get("files", {})
    current = inventory(dist)

    changed = sorted(
        key for key in recorded.keys() & current.keys()
        if recorded[key]["sha256"] != current[key]["sha256"]
    )
    missing = sorted(recorded.keys() - current.keys())
    added = sorted(current.keys() - recorded.keys())

    print(f"release {pinned.get('label')} frozen {pinned.get('frozen_utc')}")
    print(f"  commit      {pinned.get('built_by', {}).get('git_commit')}")
    print(f"  files       {len(recorded)} pinned, {len(current)} present")
    for label, group in (
        ("CHANGED", changed), ("MISSING", missing), ("ADDED", added),
    ):
        for key in group[:20]:
            print(f"  {label:8} {key}")
        if len(group) > 20:
            print(f"  {label:8} ... and {len(group) - 20} more")

    total = len(changed) + len(missing) + len(added)
    if not total:
        print("\nintact: every pinned file is present and unchanged")
    else:
        print(f"\n{total} difference(s): this is NOT the frozen artifact")
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--label", default="rc1")
    parser.add_argument(
        "--verify", action="store_true",
        help="re-hash the tree and report differences from the pin",
    )
    parser.add_argument(
        "--allow-dirty", action="store_true",
        help="freeze even though the working tree has uncommitted changes. "
             "Refused by default: a pin naming a commit that does not "
             "contain the code which built the tree cannot be reproduced, "
             "which is the one thing a release candidate has to offer.",
    )
    args = parser.parse_args()

    dist = args.dist_dir.expanduser().resolve()
    if not dist.is_dir():
        raise SystemExit(f"{dist} is not a directory")
    if _inside_git(dist):
        raise SystemExit(
            f"{dist} is inside a git work tree. The corpus is derived from "
            f"research-only SPCs and must not be committed."
        )

    if args.verify:
        raise SystemExit(min(verify(dist), 125))

    pin = build(dist, args.label)
    built = pin["built_by"]
    if built.get("dirty") and not args.allow_dirty:
        raise SystemExit(
            f"refusing to freeze: the working tree has uncommitted changes, "
            f"so commit {built.get('git_commit')} does not describe the code "
            f"that built this corpus.\n"
            f"  dirty: {', '.join(built.get('dirty_paths') or [])[:300]}\n"
            f"Commit first, or pass --allow-dirty for a throwaway pin."
        )
    (dist / RELEASE_FILE).write_text(json.dumps(pin, indent=1))
    print(f"froze {pin['n_files']} files, {pin['total_bytes'] / 1e9:.2f} GB")
    print(f"  label       {pin['label']}")
    print(f"  commit      {pin['built_by'].get('git_commit')}")
    print(f"  dirty       {pin['built_by'].get('dirty')}")
    print(f"  index       {pin['index_schema']}")
    print(f"  tracks      {pin['n_tracks_in_index']}")
    print(f"  wrote       {dist / RELEASE_FILE}")


if __name__ == "__main__":
    main()
