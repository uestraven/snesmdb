#!/usr/bin/env python3
"""Check that this SNES-MDB distribution is complete and unmodified.

    python3 verify.py            # from the package root
    python3 verify.py path/to/dist

Run this FIRST, before trusting any number in the data or the documentation.

`dist/RELEASE.json` records a SHA-256 and a byte count for every published
file. This re-reads the tree and compares. It needs only the Python standard
library and it reads nothing but the distribution.

WHY IT SHIPS. A copy of this distribution once arrived with `index.json`
truncated mid-string by a short write at a 768 KiB boundary -- the corpus data
was perfect, but the manifest was unparseable, and the recipient could not
tell a damaged transfer from a damaged release. That ambiguity cost real work:
an index is the documented entry point, so its loss looks like a defect in the
dataset. One command removes the question.

Exit code is 0 when the tree is intact and non-zero otherwise, so it can gate
a script.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

CHUNK = 1 << 20

#: Written by the packaging step, not part of the pinned tree: a pin cannot
#: contain its own hash, and the archive of past pins is metadata about
#: releases rather than published data.
NOT_PINNED = ("RELEASE.json", "releases")


def digest(path: Path) -> str:
    out = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            out.update(block)
    return out.hexdigest()


def main() -> None:
    here = Path(__file__).resolve().parent
    target = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else here / "dist"
    target = target.resolve()

    pin_path = target / "RELEASE.json"
    if not pin_path.is_file():
        raise SystemExit(
            f"no RELEASE.json in {target}.\n"
            f"Pass the path to the distribution, e.g. "
            f"`python3 verify.py path/to/dist`."
        )
    try:
        pin = json.loads(pin_path.read_text())
    except ValueError as problem:
        raise SystemExit(
            f"RELEASE.json in {target} is itself unreadable ({problem}).\n"
            f"The copy is damaged; request or re-copy the distribution."
        )

    recorded = pin.get("files", {})
    print(f"SNES-MDB {pin.get('label')}  frozen {pin.get('frozen_utc')}")
    print(f"  built from  {(pin.get('built_from') or {}).get('git_commit')}")
    print(f"  pinned      {len(recorded)} files")

    missing, truncated, changed = [], [], []
    for key, want in sorted(recorded.items()):
        path = target / key
        if not path.is_file():
            missing.append(key)
            continue
        size = path.stat().st_size
        # Size is reported separately from content because the two mean
        # different things: a wrong size is a damaged transfer, a right size
        # with a wrong hash is altered content.
        if size != want.get("bytes"):
            truncated.append((key, want.get("bytes"), size))
            continue
        if digest(path) != want.get("sha256"):
            changed.append(key)

    present = set()
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        key = path.relative_to(target).as_posix()
        if key in NOT_PINNED or key.split("/")[0] in NOT_PINNED:
            continue
        present.add(key)
    unlisted = sorted(present - set(recorded))

    for key, want, got in truncated[:20]:
        share = (got / want * 100) if want else 0
        print(f"  TRUNCATED  {key}: {got:,} of {want:,} bytes ({share:.1f}%)")
    for key in changed[:20]:
        print(f"  ALTERED    {key}: right size, wrong contents")
    for key in missing[:20]:
        print(f"  MISSING    {key}")
    for key in unlisted[:20]:
        print(f"  UNLISTED   {key}: present but not in the pin")

    broken = len(truncated) + len(changed) + len(missing)
    if not broken and not unlisted:
        print("\nINTACT: every pinned file is present, complete and unchanged.")
        raise SystemExit(0)
    if truncated and not changed and not missing:
        print(
            f"\nDAMAGED COPY: {len(truncated)} file(s) are the wrong length. "
            f"A short length is the signature of an interrupted copy, not of "
            f"a defect in the release. Re-copy the distribution and run this "
            f"again before reporting anything."
        )
    else:
        print(f"\nNOT INTACT: {broken} problem(s), {len(unlisted)} unlisted.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
