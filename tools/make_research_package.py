#!/usr/bin/env python3
"""Assemble the research package handed to an independent evaluator.

    make_research_package.py <dist-dir> <package-dir> [--label gate5-rc2]

The package is the frozen distribution plus its public documentation, and
NOTHING ELSE. What is left out is as much the point as what goes in: an
evaluator who can read the extraction source, the test suite or the example
analyses is no longer evaluating the published artifact, and development notes
carry the expected answers.

So the omissions are enforced rather than remembered. Only the paths named in
`DOCS` and the pinned tree are copied, and `audit` then walks the result and
fails on anything matching `FORBIDDEN` -- source, tests, examples,
intermediate extraction output, revision history, development notes, and the
copyrighted source material itself.

The pin is verified BEFORE anything is copied. Packaging a tree that does not
match its own release pin would hand over an artifact nobody can identify,
which defeats the purpose of freezing one.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import freeze_release as freeze  # noqa: E402

#: Public documentation, as `(source relative to the repo, name in package)`.
#: An exact list, because "copy the docs directory" would ship the build log.
#: The documents keep their REPOSITORY paths, so that the relative links
#: inside them resolve in the package exactly as they do in the repository.
#: They were at the package root, which broke `README.md`'s own links to
#: `docs/DATASET.md` -- the same class of defect as a document pointing at a
#: tree that is not shipped, introduced while fixing that one.
DOCS = (
    ("README.md", "README.md"),
    ("docs/DATASET.md", "docs/DATASET.md"),
    ("docs/CHANGELOG.md", "docs/CHANGELOG.md"),
    ("docs/SCHEMA.md", "docs/SCHEMA.md"),
    ("docs/claims.json", "docs/claims.json"),
)

#: Development documents that must never enter the package. Named explicitly
#: so that adding one to `docs/` does not quietly make it eligible.
EXCLUDED_DOCS = (
    "milestones.md", "design.md", "performance-conventions.md",
)

#: Anything matching these in the finished package is a packaging failure.
#: Checked by walking the result, not by trusting the copy step.
FORBIDDEN_NAMES = (".git", "src", "tests", "examples", "data", "build",
                   "vendor", ".venv", "tools")
#: The ONE executable the package carries. A recipient needs a way to check
#: that what arrived is what was sent, and a blanket ban on `.py` denied them
#: that: an evaluator received a copy whose `index.json` had been truncated
#: mid-string by a short write at a 768 KiB boundary, could not tell a
#: transfer failure from a packaging failure, and wrote their own verifier
#: before concluding -- reasonably but wrongly -- that the release was
#: corrupt. An integrity checker is not the extraction source under
#: evaluation, and excluding it was over-broad.
VERIFY_SCRIPT = "verify.py"

#: The replication kit, which ships for the same reason `verify.py` does: a
#: recipient must be able to challenge the documentation's numbers without
#: reconstructing the extraction pipeline. Three evaluations found 35 defects
#: and every substantive one came from an outsider recomputing a published
#: figure; withholding the means to do that cheaply would be perverse.
REPLICATE_SCRIPT = "replicate.py"
CLAIMS_FILE = "docs/claims.json"

FORBIDDEN_SUFFIXES = (
    # Source and test code: the evaluator must read the artifact, not the
    # program that produced it. `verify.py` is the sole exception.
    ".py", ".cpp", ".h", ".hpp", ".c",
    # The copyrighted source material and anything audio. These never leave
    # the machine they were ripped on; the licence is narrower than research
    # use and the published corpus is derived data only.
    ".spc", ".rsn", ".wav", ".flac", ".mp3", ".ogg", ".aram",
    # Intermediate extraction output.
    ".jsonl", ".jsonl.gz",
)


def audit(package: Path) -> list[tuple[str, str]]:
    """Every excluded thing present in the finished package."""
    found: list[tuple[str, str]] = []
    for path in sorted(package.rglob("*")):
        key = path.relative_to(package).as_posix()
        parts = set(path.relative_to(package).parts)
        if parts & set(FORBIDDEN_NAMES):
            found.append((key, "a development directory"))
            continue
        if path.name in EXCLUDED_DOCS:
            found.append((key, "a development note"))
            continue
        if not path.is_file():
            continue
        if key in (VERIFY_SCRIPT, REPLICATE_SCRIPT):
            continue
        lowered = path.name.lower()
        for suffix in FORBIDDEN_SUFFIXES:
            if lowered.endswith(suffix):
                found.append((key, f"{suffix} must not be distributed"))
                break
    return found


def instructions(label: str, index: dict[str, Any], n_files: int) -> str:
    """The one short document that says what these materials are.

    Deliberately contains no research questions, no worked examples and no
    expected results. Its job is identification and provenance.
    """
    block = index.get("corpus", {})
    formats = index.get("formats", {})
    return f"""# SNES-MDB — official research release candidate `{label}`

These materials are the **official SNES-MDB research release candidate**. They
are a complete, self-contained copy of the published dataset and its public
documentation, and they are what the project intends researchers to work from.

## What is supplied

| path | contents |
|---|---|
| `verify.py` | **run this first** — checks the copy against its hashes |
| `replicate.py` | recomputes the documentation's numbers from the data, independently |
| `dist/` | the complete frozen distribution — {n_files} files |
| `README.md` | what the project is and how the formats relate |
| `docs/DATASET.md` | the dataset reference: every format, and where the data is wrong |
| `docs/CHANGELOG.md` | published format versions and the breaking changes so far |
| `docs/SCHEMA.md` | **field reference**: every field, its type, unit, range and null meaning |

`DATASET.md` and `CHANGELOG.md` also appear inside `dist/`, as they do in any
download. The copies under `docs/` are identical, and are placed there so the
relative links inside the documents resolve.

## Check the claims, not just the files

```sh
python3 replicate.py
```

`verify.py` proves you have the bytes we sent. **`replicate.py` proves the
numbers in the documentation are true of them.** It reads only `dist/`,
imports nothing from the project, and where it can it reads a *different*
published representation from the one a figure came from — the MIDI note-on
total is recovered by parsing the binary files, which no JSON table touches.

`docs/claims.json` is the registry it works from, and it separates three
things: a **measurement** that must reproduce, an **estimate** that
reproduces only under a stated assumption, and an **interpretation** that
cannot be checked mechanically and is listed so you know which claims rest on
judgement. On this release 9 measurements and 2 estimates reproduce, and 2
interpretations are declared uncheckable.

Reproducing a measurement does not establish that it measures the musical
concept it is named for, nor that a conclusion generalises beyond these 22
games. **Finding something we got wrong is an expected outcome, not a
failure** — three previous evaluations found 35 defects between them, and the
mechanism that found almost all of them was someone recomputing a published
number.

## The dataset

{block.get('n_tracks', '?')} tracks from {block.get('n_games', '?')} games.
{block.get('n_events', 0):,} published events, of which
{block.get('n_pitched_events', 0):,} carry a recovered pitch and
{block.get('n_attacks', 0):,} are note attacks.

`dist/index.json` is the manifest and declares its own schema
(`{index.get('schema')}`) and the schema of every format it contains. Start
there. For most questions the per-track event tables in `dist/events/` are the
intended entry point; `DATASET.md` explains the alternatives and when the
hardware-indexed formats are the better choice.

**No field lives in only one file.** `dist/tracks.csv` carries the same
per-track metadata one line at a time, and each event table repeats its own
`game`, `game_slug` and `track_class` in its header. So the two fields the
documentation tells you to filter on survive the loss of any single file, and
a partial copy degrades row by row instead of all at once.
`index.json` also carries a `games` block mapping each track-id slug to its
game name — `mo2` is Earthbound, `sd2` is Secret of Mana — which is not
guessable and should never have had to be inferred.

## Verify this copy first

```sh
python3 verify.py
```

**Do this before trusting any number in the data or the documentation.** It
needs only the standard library, takes a few seconds, and re-hashes every file
against `dist/RELEASE.json`, which records a SHA-256 and a byte count for all
{n_files} of them.

This is not a formality. A copy of this distribution once arrived with
`index.json` truncated mid-string by a short write at a 768 KiB boundary. The
corpus data was perfect and the manifest was unparseable — and because the
manifest is the documented entry point, the damage read as a defect in the
release rather than in the transfer. **A wrong byte count means the copy
failed: re-copy and re-run before reporting anything.** A correct count with a
wrong hash means something altered the contents.

Every number quoted in the documentation refers to this exact tree.

## What is deliberately not supplied

The extraction source code, the test suite, example analysis scripts,
intermediate extraction output, the revision history, and the project's
internal development notes. The documentation occasionally refers to these;
those references are out of scope here and nothing in the package depends on
them.

This is intentional. The point of the exercise is whether the **published
artifact and its documentation** are sufficient on their own.

## Licensing

The dataset is **derived data for research use only**. It was extracted from
SPC files that are copyrighted by their original publishers, and no SPC file,
decoded audio, or other source material is included here or may be
redistributed with it.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--label", default=None,
                        help="defaults to the label in the tree's pin")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing package directory")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    dist = args.dist_dir.expanduser().resolve()
    package = args.package_dir.expanduser().resolve()

    if freeze._inside_git(package.parent if not package.exists() else package):
        raise SystemExit(
            f"{package} is inside a git work tree. The corpus is derived from "
            f"research-only SPCs and must not be committed."
        )

    # Verify the pin FIRST. Packaging a tree that does not match its own pin
    # would hand over an artifact nobody can identify.
    pin_path = dist / freeze.RELEASE_FILE
    if not pin_path.is_file():
        raise SystemExit(
            f"{dist} carries no {freeze.RELEASE_FILE}. Freeze it first: "
            f"the package must name one exact artifact."
        )
    differences = freeze.verify(dist)
    if differences:
        raise SystemExit(
            f"refusing to package: {dist} does not match its own pin "
            f"({differences} difference(s)). Re-publish and re-freeze."
        )
    pin = json.loads(pin_path.read_text())
    label = args.label or pin.get("label")

    if package.exists():
        if not args.force:
            raise SystemExit(f"{package} exists; pass --force to replace it")
        shutil.rmtree(package)
    package.mkdir(parents=True)

    # A HALF-BUILT PACKAGE MUST NOT SURVIVE A FAILURE. The audit and the
    # copy check already delete on rejection, but an unexpected exception
    # left the partial tree on disk -- which happened: a missing parent
    # directory for `docs/DATASET.md` raised FileNotFoundError after `dist/`
    # had been copied, leaving something that looked like a package and was
    # missing its documentation. Anything incomplete is removed.
    try:
        _assemble(repo, dist, package, pin, label)
    except BaseException:
        shutil.rmtree(package, ignore_errors=True)
        raise


def _assemble(
    repo: Path, dist: Path, package: Path, pin: dict[str, Any], label: str
) -> None:
    shutil.copytree(dist, package / "dist")
    for source, name in DOCS:
        path = repo / source
        if not path.is_file():
            raise SystemExit(f"missing public document: {source}")
        target = package / name
        # The documents keep their repository paths, so a destination may sit
        # in a subdirectory that does not exist yet.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text())

    shutil.copyfile(
        Path(__file__).resolve().parent / "package_verify.py",
        package / VERIFY_SCRIPT,
    )
    shutil.copyfile(
        Path(__file__).resolve().parent / "replicate.py",
        package / REPLICATE_SCRIPT,
    )

    index = json.loads((dist / "index.json").read_text())
    n_files = pin.get("n_files", 0)
    (package / "START-HERE.md").write_text(
        instructions(label, index, n_files)
    )

    # VERIFY THE COPY, not just the source. The source pin was checked before
    # copying, which says nothing about whether the copy succeeded: a short
    # write during this step would have shipped silently, and that is exactly
    # the failure an evaluator hit one copy further downstream. Re-hashing
    # here is the difference between "the tree we meant to send was good" and
    # "the tree we are sending is good".
    copied = freeze.verify(package / "dist")
    if copied:
        shutil.rmtree(package)
        raise SystemExit(
            f"the copied tree does not match the pin ({copied} difference(s)) "
            f"-- the copy failed. The package has been deleted rather than "
            f"shipped."
        )

    problems = audit(package)
    if problems:
        for key, why in problems[:20]:
            print(f"  FAIL  {key}  -- {why}")
        shutil.rmtree(package)
        raise SystemExit(
            f"{len(problems)} excluded item(s) reached the package; it has "
            f"been deleted rather than shipped."
        )

    total = sum(p.stat().st_size for p in package.rglob("*") if p.is_file())
    count = sum(1 for p in package.rglob("*") if p.is_file())
    print(f"\nresearch package: {package}")
    print(f"  label        {label}")
    print(f"  built from   {(pin.get('built_from') or {}).get('git_commit')}")
    print(f"  files        {count} ({total / 1e6:.1f} MB)")
    print(f"  documents    START-HERE.md, {VERIFY_SCRIPT}, " +
          ", ".join(name for _, name in DOCS))
    print("  exclusions   clean: no source, tests, examples, intermediate "
          "output, history or audio")


if __name__ == "__main__":
    main()
