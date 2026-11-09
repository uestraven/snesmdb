#!/usr/bin/env python3
"""Generate the blinded observation form from the plan and render report.

    make_listening_form.py <plan.json> <render_report.json> <form.md>

The form is non-audio metadata and is meant to be retained with the results.
It is generated rather than written by hand so that the questions asked
cannot drift from the excerpts actually rendered.

Two design choices are deliberate.

First, the question is never "does this sound like SNES music" or "is this
faithful". A render built from the published records CANNOT match the
original: panning, per-channel volume, ADSR rates, the echo unit, pitch
modulation and noise are not in the published representation at all. Those
differences are present in BOTH candidates and therefore cancel. Asking
about absolute fidelity would score documented representational scope as
defect.

Second, "no difference detected" is a first-class answer, not a failure to
complete the task. Four of the twelve excerpts are null controls whose two
candidates are byte-identical, and the correct observation there is that
there is nothing to hear.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PREAMBLE = """# Blinded listening observations

Seed `{seed}`. {n} excerpts, {window:g} s each.

## What you are comparing

Each excerpt has three files:

    {ex}-reference.wav   the original SPC, rendered by the emulator
    {ex}-X.wav           one candidate
    {ex}-Y.wav           the other candidate

X and Y are built from the SAME published records -- identical note times,
durations, pitches, gains and envelopes. They differ in ONE respect: which
audio sample each note uses. Which of X or Y is the baseline is recorded
only in `answer_key.json`.

**Do not open the answer key until every observation below is written
down.**

## The question

For each excerpt: **which of X or Y is closer to the reference, and in what
audible respect?**

Not "which sounds better", and not "which sounds more like a SNES". If you
cannot hear a difference, say so -- that is a real and expected result for
some excerpts.

## Differences that are EXPECTED in both candidates, and are not findings

Both renders are reconstructions from a symbolic representation that does
not contain these, so both will differ from the reference in the same way.
Do not record them:

- no stereo image; everything is centred (no pan or per-channel volume)
- no echo or reverb (the FIR unit is not represented)
- blunt envelopes (ADSR *rates* are not represented, only levels)
- no pitch modulation, no noise channel
- note onsets quantised to a 100 Hz grid
- plain nearest-neighbour resampling instead of the hardware's
  Gaussian interpolation

## Two different kinds of difference

Please keep these apart; they mean different things:

- **timbre changed** -- the same note, played with a different sound
- **a note is present in one candidate and absent in the other** -- this
  happens where one version establishes no identity for that note and
  nothing was substituted for it. A missing note is not a wrong timbre.

---
"""

BLOCK = """## {ex}  ({n} of {total})

- track `{track}` - {game}
- window: {start:g} s to {end:g} s
- notes in window: {attacks}

Files: `{ex}-reference.wav`, `{ex}-X.wav`, `{ex}-Y.wav`

| field | answer |
|---|---|
| closer to reference | `X` / `Y` / `no difference detected` / `cannot tell` |
| confidence | `high` / `medium` / `low` |
| kind of difference | `timbre changed` / `note present in one only` / `both` / `none` |
| where (seconds into excerpt) | |
| what you heard | |
| anything else | |

"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("plan", type=Path)
    p.add_argument("render_report", type=Path)
    p.add_argument("form", type=Path)
    args = p.parse_args()

    plan = json.loads(args.plan.read_text())
    excerpts = plan["excerpts"]
    # Presentation order is the excerpt order, which is already stratified
    # and seeded; the STRATUM is deliberately not printed, so the listener
    # cannot tell a null control from a signal excerpt.
    out = [PREAMBLE.format(seed=plan["seed"], n=len(excerpts),
                           window=plan["window_sec"], ex="exNN")]
    for n, ex in enumerate(excerpts, 1):
        out.append(BLOCK.format(
            ex=ex["excerpt_id"], n=n, total=len(excerpts),
            track=ex["track_id"], game=ex["game"],
            start=ex["start_sec"],
            end=ex["start_sec"] + ex["window_sec"],
            attacks=ex["attacks_in_window"],
        ))
    out.append(
        "---\n\n## After recording every observation\n\n"
        "Only then open `answer_key.json`. It records which of X and Y was "
        "the baseline for each excerpt, which excerpts were null controls "
        "with byte-identical candidates, and how many notes were present in "
        "only one candidate.\n\n"
        "A difference reported on a null control is not evidence about the "
        "data. It is evidence about the listening procedure, and it is the "
        "reason the null controls are in the set.\n"
    )
    args.form.write_text("".join(out))
    print(f"wrote {args.form} -- {len(excerpts)} excerpts, strata withheld")


if __name__ == "__main__":
    main()
