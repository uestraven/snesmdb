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

---

## Both experiments frozen — 2026-11-11

Level 1 and Level 2 are closed. **No further technical experiments are
required for the current claims**, and none should be run under these
registrations: not a larger model, not a temperature search, not a Level 3,
not an additional evaluation gate. Any future work is a new experiment with
its own registration.

Frozen artifacts, both verified on this date:

| set | location | integrity |
|---|---|---|
| Level 1 | `~/workplace/level1_artifacts/` | 9 files, `SHA256SUMS` verified; checkpoint sha256 `c146d36ad661fe3643f7c2896ad3747e663aac0c6741124165b6c9ba8e6bc6a9` |
| Level 2 | `~/workplace/level2_artifacts/` | 12 files, `SHA256SUMS` verified, `PROVENANCE.md` written |

The locked model is 5,056,512 parameters: d_model 256, 6 layers, 8 heads,
context 1024, vocabulary 240.

### The position being published

1. **SNES-MDB is a viable symbolic-music research corpus** — reproducible
   extraction, validated musical measurements, and statistically significant
   predictive learning across held-out games (23.66%, 8/8 games, two-sided
   sign test p = 0.0078).
2. **The tested generative approach fails** — the registered
   generation-validity criterion was not met (23/24), performances are
   hardware-inconsistent (44–80% of notes need voice stealing against 0.0% for
   real music), and two excerpts show pathological clock stagnation while
   remaining grammatically valid. The single-listener diagnostic found the
   output incoherent; genuine symbolic performances survived identical
   rendering.
3. **The dataset's broader generative potential remains open.** This
   experiment does not establish that other representations, architectures, or
   constrained decoding would fail.

### Caveats that must travel with claim 1

- The generalization is across unseen **games**, never an unseen **composer**:
  406 tracks carry incomplete or missing credits and a possible authorship
  overlap covering 206 tracks is unresolved.
- The splits are not interchangeable samples: pitched share 77.5 / 81.8 /
  85.5% across train/valid/test, validation is a 43% expansion cohort against
  train's 6.8%, and test median max polyphony is 6 against train's 8.
- The comparator's 24/24 structural validity is **not** evidence of better
  grammar learning. It is handed the slot from absolute position and places
  only ~3.8e-4 on illegal groups, which `top_p = 0.95` prunes. The arms were
  never symmetric on that criterion.
- Same-voice overlap has two control values — 6.638% pooled, 3.08%
  per-excerpt median — and the multipliers differ roughly twofold between
  them. Fix one aggregation and state which.
