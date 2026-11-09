#!/usr/bin/env python3
"""Make a published release self-contained for research, then prove it.

    package_toolkit.py <dist-dir> [--verify-only]

Adds the research toolkit to a distribution and verifies that the published
commands run from the archive alone.

WHY THIS EXISTS. The corpus was reproducible inside the development
checkout and not outside it. The data, the schema and the dataset notes
shipped; every tool, the exclusion record and the README did not. So
"reproduce the published experiment using only the release" was impossible
for a reason no data audit could detect -- each one checks the data, not
whether the data is usable on its own.

TWO HAZARDS THIS GUARDS, both of which were real:

    hidden import     the baseline script imports `snesmdb.exclusions`,
                      which is one module out of a much larger package. A
                      release that copied the script alone would fail on
                      import, and a release that copied the whole package
                      would ship extraction code no researcher needs.
    hidden file path  `exclusions.DEFAULT_PATH` resolved three directories
                      up into `docs/`, which is the checkout's shape. In an
                      archive that path points outside the release.

So the toolkit is assembled from a declared inventory and then EXERCISED:
the verification runs the published experiment from the packaged copy with
the repository removed from `sys.path`, and compares the metrics against the
recorded results.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: What a researcher needs, and nothing else. Extraction tooling is
#: deliberately absent: it requires SPC files, which cannot be distributed.
INVENTORY = {
    "README.md": "README.md",
    "docs/DATASET.md": "DATASET.md",
    "docs/SCHEMA.md": "SCHEMA.md",
    "docs/CHANGELOG.md": "CHANGELOG.md",
    "docs/evaluation_exclusions.json": "toolkit/evaluation_exclusions.json",
    "docs/baseline_interval_ngram_results.json":
        "toolkit/baseline_interval_ngram_results.json",
    "tools/baseline_interval_ngram.py":
        "toolkit/baseline_interval_ngram.py",
    "examples/workflows.py": "toolkit/workflows.py",
    "src/snesmdb/exclusions.py": "toolkit/snesmdb/exclusions.py",
}

PACKAGE_INIT = '''"""The published research toolkit for SNES-MDB.

A deliberately small subset of the development package: only what the
published experiments import. Extraction and publication code is not here,
because it needs SPC files that cannot be distributed.
"""
'''

REPRODUCE = '''# Reproducing the published results

Everything here runs against the data in this directory. There are **no
third-party dependencies** -- Python 3.11 or newer and its standard library
are enough. Nothing needs installing, and nothing reaches outside this
archive.

## 1. The research workflows

```sh
python3 toolkit/workflows.py . discover --game "Chrono Trigger"
python3 toolkit/workflows.py . pitch    --game "Chrono Trigger"
python3 toolkit/workflows.py . samples  --game "Chrono Trigger"
```

## 2. The published interval-prediction experiment

```sh
python3 toolkit/baseline_interval_ngram.py . my_results.json
```

This reproduces `toolkit/baseline_interval_ngram_results.json`. It is
deterministic: no sampling, no RNG, no parallelism, so the metrics are
identical on every run and on every machine.

Expect roughly a minute. It fits models on the training split, selects the
n-gram order and smoothing on validation, and evaluates the test split
once.

## 3. Reading the result correctly

The experiment reports that an interval 3-gram predicts the next melodic
interval better than a frequency-only baseline: **0.4309 vs 0.3223
accuracy, 3.2799 vs 4.0150 bits**.

What that does **not** establish is as important as what it does:

- It is **held-out-game** evaluation. Composer generalisation is **not**
  established: 287 of 1,477 tracks carry a composer credit truncated at
  32 bytes, and one possible authorship overlap affecting 206 tracks is
  unresolved.
- The splits are **not interchangeable samples**. Pitched share runs
  77.49% / 81.75% / 85.48% across train / valid / test, validation is 43%
  expansion-cohort against train's 6.8%, and test median max polyphony is
  6 against 8.
- Hyperparameter selection chose a setting at the edge of the declared
  grid, so these figures describe that configuration; **the effect of a
  broader search is unmeasured.**
- It says nothing about musical quality or full-song generation.

`DATASET.md` carries the full population definition, the duplicate-content
findings and the split limitations. Read it before quoting a figure.

## 4. What is authoritative

`events/*.json.gz` is the authoritative representation. `midi/*.mid` is a
projection of the attacks carrying a usable fixed-pitch estimate and is
lossy by design -- see the MIDI section of `DATASET.md`.
'''


def assemble(dist: Path) -> list[str]:
    written = []
    (dist / "toolkit" / "snesmdb").mkdir(parents=True, exist_ok=True)
    for source, target in INVENTORY.items():
        src = ROOT / source
        if not src.is_file():
            raise SystemExit(f"inventory names a missing file: {source}")
        dest = dist / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(target)
    init = dist / "toolkit" / "snesmdb" / "__init__.py"
    init.write_text(PACKAGE_INIT)
    written.append("toolkit/snesmdb/__init__.py")
    (dist / "REPRODUCE.md").write_text(REPRODUCE)
    written.append("REPRODUCE.md")
    return written


def sweep_bytecode(dist: Path) -> list[str]:
    """Remove `__pycache__` written by running the toolkit.

    Verification imports the packaged modules, which leaves `.pyc` files
    behind. They were pinned into a frozen manifest once: build detritus
    tagged for one interpreter version (`cpython-315`), shipped to
    researchers who may be on another, and recorded in a digest that then
    depended on which Python happened to run the packaging step.
    """
    removed = []
    for cache in sorted(dist.rglob("__pycache__")):
        if cache.is_dir():
            removed.append(str(cache.relative_to(dist)))
            shutil.rmtree(cache)
    return removed


def verify(dist: Path) -> list[str]:
    """Run the published commands from the archive, with the repo hidden.

    `-I` isolates the interpreter: no user site packages, and crucially no
    inherited `sys.path` or `PYTHONPATH` pointing back at the checkout. A
    verification that silently imported the development package would prove
    nothing about the archive.
    """
    problems = []
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    recorded = json.loads(
        (dist / "toolkit" / "baseline_interval_ngram_results.json")
        .read_text())

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "repro.json"
        # Run from a directory that is NOT the repository, referring to the
        # release by absolute path only.
        result = subprocess.run(
            [sys.executable, "-I",
             str(dist / "toolkit" / "baseline_interval_ngram.py"),
             str(dist), str(out)],
            capture_output=True, text=True, cwd=tmp, env=env, timeout=3600)
        if result.returncode != 0:
            problems.append(
                f"the published experiment failed from the archive: "
                f"{result.stderr.strip()[-400:]}")
        elif not out.is_file():
            problems.append("the experiment wrote no results")
        else:
            got = json.loads(out.read_text())
            for path in (("test", "ngram", "micro_accuracy"),
                         ("test", "ngram", "micro_nll_bits"),
                         ("test", "frequency", "micro_accuracy"),
                         ("test", "frequency", "micro_nll_bits")):
                a = recorded
                b = got
                for key in path:
                    a, b = a[key], b[key]
                if a != b:
                    problems.append(
                        f"{'.'.join(path)}: recorded {a}, reproduced {b}")
            if got["exclusion_policy"]["applied"] != \
                    recorded["exclusion_policy"]["applied"]:
                problems.append("exclusion policy outcome differs")

        for name in ("discover", "pitch", "samples"):
            result = subprocess.run(
                [sys.executable, "-I", str(dist / "toolkit" / "workflows.py"),
                 str(dist), name, "--game", "Chrono Trigger"],
                capture_output=True, text=True, cwd=tmp, env=env, timeout=600)
            if result.returncode != 0:
                problems.append(
                    f"workflow {name!r} failed from the archive: "
                    f"{result.stderr.strip()[-300:]}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist", type=Path)
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    if not args.verify_only:
        written = assemble(args.dist)
        print(f"packaged {len(written)} toolkit files into {args.dist}")
        for name in written:
            print(f"  {name}")

    print("\nverifying the published commands from the archive, with the "
          "repository hidden...")
    problems = verify(args.dist)
    # Verification imports the packaged modules; the bytecode it leaves
    # must not become part of the distribution.
    swept = sweep_bytecode(args.dist)
    if swept:
        print(f"swept bytecode written by verification: {', '.join(swept)}")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    print("\nstandalone replication verified: the published experiment "
          "reproduces its recorded metrics exactly, and all three research "
          "workflows run, using only the release contents")


if __name__ == "__main__":
    main()
