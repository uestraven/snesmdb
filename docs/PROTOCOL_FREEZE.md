# Protocol freeze — locked before GPU training

Frozen 2026-11-10, before any Transformer was trained. Nothing in this file
may be revised because the model performs poorly. **The baseline and the
Transformer must see the same task.**

## Tokenizer — `snes-lm-repr/1.0.0-log96-cap2s`

| property | frozen value |
|---|---|
| vocabulary | **240** |
| time tokens | **97** = 1 `TIME_SAME` + **96 log-spaced positive bins** |
| positive bin range | 0.5 ms – 2.0 s, geometric |
| voice tokens | 8 |
| pitch tokens | 99 = 87 semitones (MIDI 12–108) + `PITCH_NONE` + `PITCH_OOR` |
| duration tokens | 33 = 32 quantile bins + `DUR_NONE` |
| stride | 4 — TIME, VOICE, PITCH, DUR |
| fitted on | train split only, 1,384 music tracks |

> **Correction to the authorising note.** The frozen tokenizer has **96**
> positive time bins, not 25. The 25-bin figure was the **rejected** quantile
> scheme, whose positive-delta p99 error was 10,806 ms; log-96 brings that to
> **30.6 ms** (mean 428.55 → 5.10 ms). Freezing 25 bins would freeze the
> version that was discarded on measurement.

Measured quantisation error, part of the record: p50 3.04 ms, p90 11.93 ms,
p99 30.56 ms, mean 5.10 ms, max 165 ms. The 2 s cap is exceeded by 888 of
1,224,840 train positive deltas (0.072%), folded into the top bin, identically
for every model.

## Task construction

- **Population:** `track_class == "music"`. Train 1,384 / valid 180 / test 176
  across 8 games. 488 non-music tracks excluded by class (jingle 364, drone 35,
  effect 89).
- **Events:** `origin == "key_on"` only; legato steps excluded by definition.
- **Order within a tick:** by voice ascending. 51.9% of consecutive pairs share
  an onset, so this is the common case, and it is deterministic.
- **Windows:** per track, stride = context = 1,024. Final partial window padded
  and masked. **Tracks never share a window.**
- **Targets:** every non-PAD token after BOS. Padding masked.
- **Loss:** cross-entropy, reported in bits/token.
- **Onsets parsed as `Decimal`**, never float.

## Frozen comparator

`SlotNGram(order=10, discount=64.0, use_event_prefix=False)`, fitted on the
train split, **3.3839 validation bits/token**. Selected from 36 configurations
on validation.

## Level 1 judgment — measured on the sealed test set

The 5% criterion is evaluated against the **baseline re-measured on test**,
not against the validation threshold:

```
pass  iff  test_bits(transformer)  <=  0.95 x test_bits(frozen_slotngram)
```

The validation figure of 3.2147 bits/token is a reference only. Both models are
evaluated on the identical untouched test population, with the registered
paired bootstrap over test tracks, a confidence interval, and all eight games
reported descriptively.

## Diagnostic, not a criterion

Validation loss is recorded **separately for TIME, VOICE, PITCH and DUR**
tokens. This distinguishes a model learning temporal and pitch relationships
from one exploiting the highly predictable voice and duration fields. It is
diagnostic and adds no pass condition.

## Training configuration

| parameter | value |
|---|---|
| architecture | decoder-only Transformer |
| parameters | ~5 M |
| context | 1,024 |
| effective batch | 8 windows |
| maximum steps | 50,000 (38.3 epochs; 1,304 steps/epoch) |
| selection | validation only, early stopping and checkpoint choice |
| hardware | one GPU |

Recorded for every run: loss curves, token counts, hyperparameters, random
seeds, checkpoint hashes.

## Sequence

1. **Feasibility probe** — short run measuring memory, step time, gradient
   stability, checkpoint restore. *A failed probe is an engineering problem,
   not evidence against the hypothesis.*
2. **Bounded validation sweep** — a small pre-registered set of learning rates
   and depths at approximately constant parameter budget and identical
   training-token budgets. Not an unlimited search.
3. **Full run** — selected configuration, up to 50,000 steps.
4. **Sealed evaluation** — once model and checkpoint are locked, both models on
   the untouched test population.

## Pre-registered sweep grid

Fixed now so it cannot expand after seeing results:

- learning rate ∈ {1e-4, 3e-4, 1e-3}
- depth × width ∈ {6 × 256, 8 × 224} — both ≈5 M parameters
- 6 configurations, identical token budget each, 4,000 steps

## Outcome interpretations, agreed in advance

| outcome | interpretation |
|---|---|
| beats test baseline by ≥5% with the registered evidence | **Level 1 passes** |
| improves but by <5% | learning demonstrated; registered threshold not met |
| matches SlotNGram | local repetition may explain most modelable structure at this scale |
| worse than SlotNGram | informative negative result about representation, architecture or regime |

None of these determines Level 2, which requires the separate listening study.

The 10,426 vs 11,151 training-window parallel with NES-MDB stays **contextual,
not a replication**: the representations and learning tasks are not identical.

## Prediction, unchanged

Level 1 passes, Level 2 fails, ~75% confidence. The experiment is to be allowed
to contradict it.
