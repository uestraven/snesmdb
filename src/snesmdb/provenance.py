"""What produced a corpus, recorded alongside it.

Every track in the manifest already carries the SHA-256 of the SPC it came
from, which proves the INPUT. Nothing recorded what processed it, so an
artifact could not be traced back to the code that made it -- and this corpus
changed shape repeatedly while the inputs stayed identical. The row clock alone
went from a fitted onset grid, to a per-game write-cadence tick, to the SPC700
timer register, with the same 1,316 SPCs behind all three. Two trees with the
same input hashes can therefore disagree completely, and without this block
there is no way to tell which is which.

`dirty` is the field that matters most. A corpus built from an uncommitted
working tree cannot be reproduced from the commit it names, so it is recorded
rather than hidden, and a consumer can treat such an artifact as provisional.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: Bumped when the shape of a published artifact changes incompatibly, not
#: when a figure moves. v3 is the SPC700 timer-register row clock, four
#: expressive channels, and the legato step table.
CORPUS_SCHEMA = "snesmdb.corpus.v3"

_REPO = Path(__file__).resolve().parent.parent.parent


def _git(*args: str) -> str | None:
    """Git output, or None when git could not answer.

    An EMPTY result is returned as the empty string, not None. `git status
    --porcelain` says "clean" by printing nothing, and collapsing that into
    None conflated a clean tree with an unknown one -- which reported
    `dirty: None` on a committed build and so understated what was known. The
    whole point of the flag is that None means "could not tell".
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(_REPO), *args],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def _dirty_paths(status: str | None) -> list[str] | None:
    """Paths from `git status --porcelain`.

    Split rather than sliced: the status prefix is two code columns and a
    space, but a staged-and-modified entry puts a code in the second column,
    so a fixed `line[3:]` ate the first character of the path -- it reported
    `ools/extract.py`. Rename entries also carry `old -> new`, and the new
    name is the one that matters.
    """
    if status is None:
        return None
    paths: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            continue
        rest = line[2:].strip() if len(line) > 2 else line.strip()
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        paths.append(rest.strip('"'))
    return sorted(paths)[:40] or None


def record(**extra: Any) -> dict[str, Any]:
    """A provenance block for a corpus artifact.

    `extra` carries the parameters of the run that produced it -- the input
    directory, render policy, job count -- because those change the output as
    surely as the code does.
    """
    status = _git("status", "--porcelain")
    commit = _git("rev-parse", "HEAD")
    return {
        "schema": CORPUS_SCHEMA,
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": commit or None,
        "git_describe": _git("describe", "--always", "--dirty") or None,
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD") or None,
        # True when the build came from an uncommitted tree, so it cannot be
        # reproduced from `git_commit` alone.
        "dirty": bool(status) if status is not None else None,
        "dirty_paths": _dirty_paths(status),
        "python": sys.version.split()[0],
        # Kernel and architecture, which affect reproducibility. NOT the
        # hostname and NOT the user.
        #
        # Those two were recorded and published. They are not reproducibility
        # data -- nothing about the output depends on who ran the build or on
        # what the machine is called -- and `provenance.json` ships inside
        # every distribution, so they disclosed an operator's account name and
        # an internal hostname to anyone who received the corpus. A published
        # provenance record should describe the code, the inputs and the
        # platform, and nothing about the person.
        "platform": platform.platform(),
        "parameters": {k: v for k, v in extra.items() if v is not None},
    }
