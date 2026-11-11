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

- same-voice overlap **43.23%** of consecutive same-voice pairs
- **40.7%** of notes require clamping by voice stealing
- peak **19** concurrent note instances, on hardware with **8** voices

These are not to be improved by re-running parameter selection, and the
intervention rate stays visible in any listening report. A study must not
conceal how much correction the model's output needed.

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
