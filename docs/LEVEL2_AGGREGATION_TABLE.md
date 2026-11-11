# Matched hardware-consistency aggregation (§6.4 replacement)

Every cell computed by one definition set, applied identically to the controls
and both generated arms. Source artifact:
`level2_artifacts/aggregation_table.json`, produced by
`scripts/snes_lm_aggregation_table.py`.

**This supersedes the previously quoted 6.638% pooled and 0.066% published
control figures.** Neither could be tied to a reproducible population: 6.638%
was a hardcoded constant, and the only traceable comparable run used 40 train
tracks under the superseded decoder. Both are replaced by recomputed values
with stated populations and denominators.

## Definitions

- **Eligible same-voice pair** — consecutive events on one voice ordered by
  onset, where the earlier has a non-null duration. The overlap denominator.
- **Overlapping pair** — an eligible pair whose earlier nominal end exceeds
  the next onset by more than the documented 1 µs rounding tolerance.
- **Overlap / stealing rate, per excerpt** — computed within one excerpt;
  the reported figure is the **median** over excerpts. *Primary statistic.*
- **Overlap / stealing rate, pooled** — totals across the population,
  event-weighted, so large excerpts dominate.
- **Peak raw note instances** — concurrent note intervals ignoring voice.
  May exceed 8; that is the diagnostic.
- **Peak occupancy after stealing** — concurrent intervals after each note is
  clamped at the next key-on on its voice, exact `Decimal`, half-open
  intervals. Bounded by 8.
- **Peak occupied hardware voices** — distinct voices sounding at once.
  Bounded by 8 by construction. **A different quantity from the two above**,
  reported separately so they cannot be conflated.

> **Never divide a pooled numerator by a per-excerpt-median denominator.**
> Compare median to median and pooled to pooled.

## The table

| population | n | events | eligible pairs | overlap med | overlap pooled | steal med | steal pooled | raw peak | after steal | voices |
|---|---|---|---|---|---|---|---|---|---|---|
| real, published, **key-on only** (matched) | 60 | 132,139 | 131,713 | 0.00% | 0.26% | 0.00% | 0.00% | 16 | 8 | 8 |
| real, published, all events incl. legato — **UNMATCHED** | 60 | 147,552 | 131,717 | 0.00% | 4.17% | 0.00% | 3.57% | 16 | 8 | 8 |
| real, tokenized round-trip — **the registered control** | 60 | 132,139 | 131,713 | 3.08% | 8.46% | 3.07% | 8.43% | 16 | 8 | 8 |
| render control, published (cross-game, 25 s, key-on) | 5 | 2,706 | 2,670 | 0.00% | 0.00% | 0.00% | 0.00% | 8 | 8 | 8 |
| render control, round-trip (cross-game, 25 s) | 5 | 2,738 | 2,702 | 1.52% | 1.18% | 1.50% | 1.17% | 10 | 8 | 8 |
| render control, published (Actraiser-only, 25 s, key-on) | 5 | 2,211 | 2,176 | 0.00% | 0.00% | 0.00% | 0.00% | 7 | 7 | 7 |
| render control, round-trip (Actraiser-only, 25 s) | 5 | 2,216 | 2,181 | 2.63% | 2.66% | 2.59% | 2.62% | 13 | 7 | 7 |
| SlotNGram, order 10, T=1.2, top_p=0.95 | 24 | 12,070 | 11,864 | 45.10% | 44.78% | 44.47% | 44.02% | 29 | 8 | 8 |
| **Transformer, T=1.0, top_p=0.95 — FULL registered** | 23 | 14,945 | 14,777 | **63.57%** | **80.69%** | 61.74% | 79.78% | **3,642** | 8 | 8 |
| Transformer — *sensitivity*, seeds 6 and 19 excluded | 21 | 6,945 | 6,793 | 63.33% | 62.27% | 61.73% | 60.91% | 48 | 8 | 8 |

The sensitivity row is a sensitivity analysis only and does **not** replace the
registered population above it.

## Multipliers against the registered control

Computed on each axis separately and never crossed.

| arm | median / median (ctl 3.08%) | pooled / pooled (ctl 8.46%) |
|---|---|---|
| SlotNGram | 14.65× | 5.29× |
| Transformer, full registered | **20.65×** | **9.54×** |
| Transformer, sensitivity | 20.58× | 7.36× |

> **A coincidence worth not being reassured by.** Dividing a median numerator
> (63.33%) by the old pooled control (6.638%) gives 9.54×, numerically almost
> identical to the correct pooled/pooled figure. The same number by an invalid
> route. Anyone sanity-checking the mixed method against this table will
> appear to confirm it.

## Three corrections this table forced

### 1. The published control was never comparable to the generators

Published event tables contain `legato_step` events — pitch changes within an
already sounding voice. A legato step shares its voice with its parent attack
and therefore registers as same-voice overlap **by construction**.
`rep.attacks()` drops them, so **no generator can emit one**.

Over the 60-track control: 132,139 `key_on` + 15,413 `legato_step` = 147,552.
Including legato puts pooled published overlap at **4.166%**; restricting to
`key_on` gives **0.256%** — a 16× difference in the control itself. 82% of the
inflated figure came from 3 of 60 tracks, one of them a 13,983-event track at
46.96%.

Restricting to `key_on` also makes the denominators agree exactly: **131,713
eligible pairs for both the published and round-tripped control**, so the
tokenizer's own contribution is measured on an identical basis rather than
inferred across populations:

| | median | pooled |
|---|---|---|
| published, key-on | 0.00% | 0.256% |
| round-tripped | 3.08% | 8.46% |

That is the irreducible cost of the representation, and it is why the
round-trip row — not the published row — is the control the generators are
judged against.

### 2. The `actr-05` 1.7% figure is an unmatched-definition artifact

Both control sets show **0.00% published-event stealing** under the matched
`key_on` definition, including the Actraiser-only set. The 1.7% previously
attributed to `actr-05` came from rendering its published events *with* legato
steps included.

Both statements are true and must not be mixed: the render pipeline did clamp
1.7% of `actr-05`'s rendered notes, and `actr-05`'s published **attacks**
require 0.0% clamping. Only the second is comparable to a generated arm. The
1.7% should not be cited as a published-event stealing rate.

The two control sets remain distinct populations — the cross-game set is one
track per game across ActRaiser, Alien 3, F-Zero, Sailor Moon and Star Fox —
but the reason to distinguish them is no longer a difference in their
published stealing rates, which are now identically 0.00%.

### 3. Whole-track and 25-second-window controls are different units

The 60-track control is whole tracks; the two rendering controls are
25-second windows, the same unit as a generated excerpt and therefore the
directly matched comparison. A whole-track overlap rate and a
25-second-window overlap rate are not the same statistic even under identical
definitions, so the unit is stated in every row. This is a third axis beyond
median-versus-pooled.

## What the table shows

Under every matched reading, both generators far exceed real music and the
Transformer is worse. The occupancy invariant holds everywhere: peak
occupancy after stealing and peak occupied voices never exceed 8, while peak
raw note instances reach 3,642 in the Transformer arm — the quantity that
makes temporal stagnation visible.

Game names are reproduced exactly as the frozen artifacts spell them:
`Actraiser`, and `Adventure Island` (whose slug `sai` abbreviates *Super
Adventure Island*). `actr-05` is unchanged.
