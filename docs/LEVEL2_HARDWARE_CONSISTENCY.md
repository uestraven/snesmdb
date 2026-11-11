# Hardware consistency of generated performances

A Level 2 diagnostic, separate from the registered structural-validity
criterion. **Token grammar and hardware-consistent note lifetimes are
different measurements**, and the registered criterion is not reinterpreted to
cover this.

## Interpretation registered BEFORE measuring the comparator

Fixed 2026-11-11, with the Transformer's figure known (43.23%) and the
comparator's unknown. These are descriptive comparisons, not pass/fail
thresholds.

| SlotNGram result | interpretation |
|---|---|
| near 6.6% | Transformer-specific failure to maintain voice occupancy |
| between 6.6% and 43.2% | both struggle; Transformer substantially worse |
| near 43.2% | failure common to both generators under this representation |
| above 43.2% | Transformer still defective against real music, but more hardware-consistent than the comparator |

## What is measured, and against which control

| measurement | both arms |
|---|---|
| raw same-voice overlap rate | before any rendering policy |
| notes requiring voice stealing | percentage |
| peak concurrent note instances | before voice stealing |
| peak physical voice occupancy | after identical rendering policy |

**The control is real tracks through the SAME tokenizer, not real tracks as
published.** That distinction is the whole measurement:

| population | same-voice overlap | worst |
|---|---|---|
| real corpus, as published | **0.066%** | 0.0 ms |
| real corpus, round-tripped (the control) | **6.638%** | 0.7 s |
| Transformer generations | **43.23%** | 2.12 s |
| SlotNGram generations | pending | pending |

Published real music almost never overlaps a voice with itself: snesmdb's
extractor ends a note when its voice is re-keyed without a key-off. The 6.638%
is what the tokenizer alone manufactures on real music, and it is irreducible
— duration is bucketed independently of the gap to the next onset, so any
representative exceeding a note's true length overshoots a tight gap. No
decode value can fix it.

## The Transformer's figures, preserved as observed

> **These figures came from an exploratory probe, not the registered batch.**
> Six 10-second excerpts at an arbitrary `temperature = 1.0` that the
> registered selection procedure had not chosen. They are preserved because
> the interpretation table above was fixed against them, but they are **not**
> the registered measurement and must not be cited as it.
>
> The peak-concurrency figure below is further superseded: the function that
> produced it conflated three distinct quantities. See
> [LEVEL2_HARNESS_CORRECTIONS.md](LEVEL2_HARNESS_CORRECTIONS.md).

- same-voice overlap **43.23%** of consecutive same-voice pairs
- **40.7%** of notes require clamping by voice stealing
- peak **19** concurrent note instances, on hardware with **8** voices

These are not to be improved by re-running parameter selection, and the
intervention rate stays visible in any listening report. A study must not
conceal how much correction the model's output needed.

## Registered batch: 24 × 25 s per arm, seeds 0–23

Sampling parameters chosen by the registered listening-free distributional
procedure: Transformer `T = 1.0, top_p = 0.95`; SlotNGram
`T = 1.2, top_p = 0.95`.

Reported as **per-excerpt medians**. Pooled rates are not robust here: two
Transformer excerpts degenerated into 4,000-event runaways and hold 53% of all
notes in that arm, which drags every pooled figure. See
[LEVEL2_HARNESS_CORRECTIONS.md](LEVEL2_HARNESS_CORRECTIONS.md) for the pooled
figures and for the two harness defects corrected before this measurement.

| measurement | control (real, tokenized) | SlotNGram | Transformer |
|---|---|---|---|
| structural validity | — | 24/24 | **23/24 (95.8%)** |
| same-voice overlap, median | 3.08% | 45.10% | 63.57% |
| attacks/sec, median | 18.08 | 20.59 | 12.90 |
| (1) concurrent notes, median / max | 10 / 16 | 22.5 / 29 | 18.0 / **3,642** |
| (2) peak after stealing | 8 | 8 | 8 |
| (3) peak occupied voices | 8 | 8 | 8 |

Both generators produce far more same-voice overlap than the tokenizer alone
manufactures on real music, so the band in the interpretation table that
applies is **"both struggle; Transformer substantially worse"** — roughly 20×
the control against the comparator's 15×.

Two cautions on reading this table:

- The comparator's close density match (20.59 against 18.08) is partly by
  construction: the registered selection procedure chose its temperature to
  minimise exactly that distance.
- The comparator's 24/24 validity is not better-learned grammar. It is handed
  the slot from absolute position and places only ~3.8e-4 of its mass on
  illegal groups, which the selected `top_p = 0.95` prunes.

## Why this does not weaken Level 1

Level 1 measured next-token likelihood on token ids. The model does predict
those better than the comparator, by 23.66% on a sealed test set. It can do
that while assembling the tokens into physically impossible performances,
because the objective never penalised the combination: `DUR` is predicted
independently of the *next* `TIME` on the same voice, so nothing in training
connected a note's length to when its voice is next needed.

That is the distinction this diagnostic exposes, and it is a finding rather
than a contradiction: **next-event prediction and valid sequential musical
performance are different capabilities, even when the training data comes from
actual hardware playback.**

## Rendering policy

A new key-on terminates the previous note on that voice, applied **identically
to both arms**. Generated event tables are never altered — `same_voice_overlap`
measures what was generated, `apply_voice_stealing` is a renderer concern, and
the two are deliberately separate functions so the fix cannot hide the
diagnostic.

What this does musically is an open question and not yet observed: frequent
voice stealing could plausibly produce truncated melodies, accompaniment that
stops before resolving, unnatural gaps, or phrases that interrupt themselves.
Those are consequences to listen for, not results.
