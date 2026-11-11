# Two harness defects found while measuring Level 2

Recorded 2026-11-11. Both were found by checking a *negative* result before
accepting it, and both changed what the result means. Neither involved
retraining, re-selecting sampling parameters, imposing grammar constraints, or
replacing the locked checkpoint — the frozen artifacts are untouched.

The order matters: the registered structural-validity criterion appeared to
fail at 79.2% against a required ≥99%. That failure was about to be recorded as
a dataset/model finding. It was conditioned on the five invalid excerpts being
intrinsic to the generator rather than another harness defect. They were
mostly not.

## Defect 1 — the generation window desynchronised the grammar

**What the representation assumes.** The serialization is a fixed stride-4
cycle, `TIME VOICE PITCH DUR`, and the slot of a token is a function of its
absolute position: `_slot(p) = (p - 1) % 4`.

**What training showed the model.** `train.windows` cuts each track at
`range(0, len(tokens), context)` with `context = 1024`. Because
`1024 ≡ 0 (mod 4)`, a token's index *within a window* always carried the same
slot phase as its index within the track. Every window the model ever saw was
phase-aligned, so positional phase was a reliable cue and the model learned to
use it.

**What generation showed the model.** `generate_model` took `tokens[-1024:]`,
whose start index advances by one token per step. Past token 1024, three steps
in four presented a positional phase that never occurred in training.

**The evidence it mattered.**

- All five invalid excerpts first broke the cycle *past* token 1024 — at body
  indices 1042, 1046, 1249, 2440, 2478. Two within ~20 tokens of the boundary.
- Of excerpts that stayed inside the window, 0 of 9 failed. Of those that
  crossed it, 5 of 15 failed.
- Regenerating the five with the window start snapped to a stride boundary —
  **same checkpoint, same seeds, same temperature and top_p, sampling still
  unconstrained over all 240 tokens** — made **4 of 5 valid**.

| seed | original | aligned window |
|---|---|---|
| 1 | invalid, break at 1042 | **valid**, 2,098 tokens |
| 3 | invalid, break at 1249 | still invalid, break at 2280 |
| 9 | invalid, break at 2478 | **valid**, 2,114 tokens |
| 20 | invalid, break at 2440 | **valid**, 2,838 tokens |
| 23 | invalid, break at 1046 | **valid**, 1,294 tokens |

**Seed 3 remains a genuine grammar failure.** The defect accounted for most of
the measured invalidity, not all of it. The generator does lose the cycle on
its own.

**Fixed** in `generate.generate_model`: the window start is snapped to a
multiple of the stride, restoring the training-time convention. This is a
harness correction, not a grammar constraint — validity is still measured
rather than enforced.

**Level 1 is unaffected.** Its evaluator scored fixed 1024-token windows cut
exactly as training cut them. The sealed-test figure of 23.66% and every
artifact behind it stand as measured.

### A correction to an interpretation of my own

The post-break output was first described as a well-formed cycle continuing in
a shifted phase. That was wrong. Fitting each tail to its best phase gives only
31–58% agreement with thousands of further violations, so the output degrades
progressively rather than slipping once. The "phase-shifted cycle" reading was
inferred from near-equal group counts after the break, which fit disordered
emission just as well.

## Defect 2 — occupancy conflated three different quantities

`max_simultaneous_voices` was named for a voice count but computed a note
count: it swept note intervals without grouping by voice. Applied to a
voice-stolen table, where the two should coincide, it reported **13 and 14**
concurrent voices on eight-voice hardware.

**The original figures are preserved as an invalidated diagnostic, not a
dataset finding:** peak voices after stealing 13 (SlotNGram) and 14
(Transformer). They measured the function, not the output.

### The three quantities, now separate

| quantity | meaning | bound |
|---|---|---|
| (1) `concurrent_notes` | concurrent note *instances* as generated | may exceed 8 — this is the diagnostic |
| (2) `concurrent_after_stealing` | instances after the renderer's policy | must be ≤ 8 |
| (3) `occupied_voices` | distinct occupied hardware voices | ≤ 8 by construction |

Implemented with exact `Decimal` arithmetic and half-open `[onset, end)`
intervals, so a note ending exactly when another begins does not count as
overlapping. Occupancy is computed per voice, with each note truncated at the
next key-on on its voice. Eight edge cases are covered by tests: identical
boundaries, simultaneous starts on distinct voices, repeated key-ons, repeated
key-ons at an *identical* onset, zero-duration events, zero-duration key-ons
that must still end the previous note, the ≤8 invariant, and accumulated-float
onsets.

### The correction exposed a real renderer bug

Quantity 2 was expected to be ≤8 trivially. It was not, and two successive
causes had to be fixed:

1. `apply_voice_stealing` clamped in float against `limit + 1e-6`, leaving each
   voice a sub-microsecond residual. Eight voices then read as nine or more.
   Now clamped exactly in `Decimal`, with no tolerance.
2. Even then quantity 2 read 9 and 10, because decoded onsets are *accumulated
   floats*, not the release's exact 6-dp literals, so re-deriving the end as
   `onset + duration` landed an ULP past the next onset. Voice stealing now
   records an authoritative `end_sec` copied from the following onset's own
   value, making adjacency exact by construction.

The reported voice-stealing *rate* is unchanged: a sub-microsecond documented
rounding artefact is clamped but still not counted as a stealing event, so the
rates stay comparable to those already recorded.

### Corrected measurement, with controls

| population | (1) concurrent notes | (2) after stealing | (3) occupied voices |
|---|---|---|---|
| real, as published | 16 | 8 | 8 |
| real, tokenized round-trip (the control) | 16 | 8 | 8 |
| SlotNGram | 29 | 8 | 8 |
| Transformer | 68 | 8 | 8 |

**The control changes the reading.** Real published music also reaches 16
concurrent nominal notes, so exceeding 8 is not by itself evidence of a model
pathology — the earlier "29 and 68 against a limit of 8" framing implied the
real corpus never exceeds 8, and it does. What discriminates is magnitude:
16 real → 29 comparator → 68 Transformer.

## Re-measured result: the registered criterion still fails

Regenerating all 24 seeds with the corrected harness (3,026 s on CPU; the
baseline arm is untouched because it uses no sliding window):

**Structural validity 23/24 = 95.8%, against a registered ≥99%. The criterion
FAILS.** With n = 24, ≥99% admits no failures at all, so the verdict is
unchanged — but the magnitude is: one genuine grammar failure (seed 3), not
five. Four of the original five were the harness.

### A second failure mode the criterion does not catch

Seeds 6 and 19 ran to the 4,000-event cap **while remaining grammatically
valid**: 4,000 events in 8.42 s and 22.12 s, i.e. 475 and 181 attacks per
second, with 3,585 and 3,642 concurrent note instances. The model emitted long
runs of `TIME_SAME`, so its clock barely advanced and the excerpt never
reached its 25-second stop condition.

`TIME_SAME` is not a rare token — 51.9% of consecutive key-on pairs in the
corpus share an onset — so looping on it is a plausible degeneration, and it
is the model's own doing rather than a harness artefact.

This matters for how the criterion should be read: **an excerpt with 3,642
simultaneous notes passes the registered structural-validity test.** Token
grammar is a far weaker guarantee than it appears.

### Three levels of validity, and which one was registered

Seeds 6 and 19 are arguably the most informative outputs of Level 2, because
they separate things the criterion had implicitly treated as one:

1. **Syntactic validity** — tokens follow the four-field event grammar.
2. **Performance validity** — time advances, event density stays plausible,
   voice lifetimes are consistent.
3. **Musical quality** — convincing rhythm, phrasing, harmony, development.

The registered structural-validity criterion measures only (1). Seeds 6 and 19
are direct evidence that **passing (1) does not imply (2)**, independently of
anything a listener might say about (3). Any future registered criterion needs
a clock-progress and density condition alongside the grammar one.

These two excerpts are preserved and rendered rather than excluded: they are
the evidence for this distinction.

These two excerpts also hold 53% of all notes in the batch, so every
pooled rate is dominated by them. The pooled figures (80.69% overlap, 40.55
attacks/s, 3,642 peak concurrent) are reported for completeness but are not
the robust statistic; per-excerpt medians are.

### Like-for-like comparison, per-excerpt medians

| population | same-voice overlap | attacks/s | concurrent notes, median / max |
|---|---|---|---|
| real, as published | 0.00% | 19.79 | 8 / 16 |
| real, tokenized (the control) | 3.08% | 18.08 | 10 / 16 |
| SlotNGram | 45.10% | 20.59 | 22.5 / 29 |
| Transformer | 63.57% | 12.90 | 18.0 / 3,642 |

The overlap finding is robust to the runaways: the Transformer's median moves
only from 63.57% to 63.33% when they are excluded.

#### Never mix the two aggregations

The control has **two** values depending on aggregation, and the earlier
6.638% figure recorded in this repo is the pooled one. Quoting a median
numerator against the pooled denominator gives a wrong multiplier. Both
consistent readings, which agree on the conclusion:

| aggregation | control | SlotNGram | Transformer |
|---|---|---|---|
| per-excerpt median | 3.08% | 14.6× | **20.6×** |
| pooled over pairs | 6.638% | 6.75× | **12.2×** |

Either way both generators far exceed real music and the Transformer is worse,
so the interpretation band registered in advance that applies is **"both
struggle; Transformer substantially worse."** The pooled Transformer figure is
inflated by the two runaways; the median one is not.

On density the two arms separate in opposite directions: the comparator tracks
the corpus closely (20.59 against 18.08) while the Transformer undershoots by
about 29% (12.90). The comparator's match is partly by construction — the
registered selection procedure chose its temperature to minimise exactly this
distance — so it is not independent evidence of superior musical pacing.

## Which excerpts the rates cover

An excerpt failing the structural criterion decodes to zero events, so there
is nothing on it to measure: every density and overlap rate is necessarily
computed over the **valid** excerpts only. No excerpt was dropped for being
unflattering and none was regenerated. The rates must always be read beside
`n_valid / n_excerpts`, which is now reported with them, and the valid
excerpts are never presented as the whole generated population.

## An asymmetry in the validity comparison

The comparator's 24/24 structural validity is not evidence that it learned the
grammar better than the Transformer. `SlotNGram` is *handed* the slot, derived
from absolute position, and places only ~3.8e-4 of its probability mass on
illegal groups — a tail the selected `top_p = 0.95` prunes. It is not
structurally incapable of a violation, but it is close to it by design.

The Transformer must infer the slot from content and position, and the harness
was feeding it positional phases it had never trained on. **The two arms were
never comparable on this criterion.** Any future registered criterion on
grammar validity should either constrain both arms or neither.
