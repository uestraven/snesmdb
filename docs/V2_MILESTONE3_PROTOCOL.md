# RSE v2 Milestone 3 protocol — AMENDED

**Amended 2026-11-11, before any model training and before any generated
output existed.** Decisions 1–3 (codec, delta vocabulary, G3 grammar) are
frozen and not reopened.

## 0. The amendment, and why it is prospective

The originally proposed **absolute musical-coherence endpoint is retired.** It
was abandoned after **two failed renderer/task calibrations**, both run on
genuine music with no RSE v2 output in either set, and both completed before
any model was trained.

| calibration | genuine at top rating | required | outcome |
|---|---|---|---|
| 1 (yes/no, 29 clips) | 7/10 *yes* (3 *maybe*) | ≥90% | **fail**, and unscoreable — the scale lacked the third category the listener used |
| 2 (frozen 3-point, 30 clips) | 6/10 score 2 | ≥90% | **fail** |
| combined | **13/20 = 65%** | ≥90% | **fail** |

Genuine SNES-MDB music does not reliably reach the top rating through this
renderer and task. The absolute endpoint therefore has **no usable reference
ceiling**: a model cannot be assessed against a 90% criterion that real music
misses, and a 60%-vs-60% comparison measures nothing.

This is a **prospective protocol amendment**, not a post-hoc change to a
model's result. Nothing about RSE v2's output has been heard or generated.

### What the calibrations did establish

- **Relative judgement detects gross musical destruction.** In calibration 2,
  genuine outranked the free pitch permutation in **9 of 10** pairs (1 tie),
  with the permuted arm at 0% top rating.
- **Sensitivity to subtle musical damage is unestablished.** The
  interval-constrained permutation produced **6 strict wins and 4 ties**, with
  80% of its clips at score 1. A generative model is more likely to make the
  subtle kind of mistake, so this is a **standing limitation of the primary
  endpoint**, retained deliberately.
- **The free permutation's detectability was partly a confound**, now
  measured: it inflates the median melodic interval from 1.53 to 11.04
  semitones and puts 45.1% of steps beyond an octave, against 2.3% for
  genuine. The constrained arm matches genuine (2.01 median, 2.3%), which is
  why its weaker separation is the more informative result.

### A qualification that limits this amendment

The 9/10 paired ordering was **derived from independently assigned ordinal
scores, not from a directly administered A/B comparison.** It justifies
changing the study design; it does **not** establish that the paired
instrument has passed calibration. No third calibration is required, but this
limitation is reported with the results.

## 1. Primary endpoint: blinded paired preference

Two excerpts, rendered identically, one question:

> **Which excerpt exhibits more recognizable musical organization — discernible
> phrases, intentional pitch relationships, and continuity between musical
> ideas?**
>
> **A** / **B** / **no discernible difference**

Listeners are *not* asked which is prettier, more nostalgic, or more
enjoyable.

| component | registered value |
|---|---|
| primary comparison | RSE v2 vs matched G3 baseline, same seed |
| practical threshold | **≥60% adjusted v2 preference** |
| tie handling | **½ win each** |
| adjusted rate | `(v2 wins + 0.5 × ties) / all valid comparisons` |
| statistical criterion | **clustered 95% CI lower bound > 50%** |
| bootstrap | resampled at **both listener and excerpt-pair level**, preserving the paired design |
| listeners | **≥20 independent** |
| stimulus selection | fixed seeds, **no cherry-picking**, every registered excerpt retained |

**Both the practical threshold and the statistical criterion must pass** to
claim demonstrated preference. 60% with an interval spanning 50% is reported
as *"threshold met, superiority not established"* — not a pass. With only 20
listeners the uncertainty is reported prominently, not in a footnote.

## 2. Reference and panel-check comparisons

| arm | purpose | pass/fail? |
|---|---|---|
| v2 vs matched G3 baseline | primary hypothesis | **yes** |
| v2 vs genuine validation excerpts | how large is the perceived gap to real music | **no** — descriptive only |
| genuine vs free pitch permutation | does *this panel* detect gross degradation | **gate** |

v2 is **not** required to beat genuine music, and failure to distinguish them
is **not** evidence of equivalence — it would equally indicate an insensitive
instrument, which the calibrations show is a live possibility.

**If the panel check fails, the perceptual evaluation is inconclusive** and
no musical claim is made in either direction. Registered threshold: the panel
must prefer genuine over the free permutation at an adjusted rate ≥70%.

## 3. Listening administration

| | |
|---|---|
| primary pairs | 24, one per generation seed, v2 vs baseline |
| reference pairs | 12, v2 vs genuine |
| panel-check pairs | 6, genuine vs free permutation |
| total pairs | 42 |
| per listener | **14 pairs** — 8 primary, 4 reference, 2 panel-check |
| coverage | each primary pair judged by ≈6–7 listeners under a fixed rotation |
| A/B side | randomised per listener per pair, recorded in the sealed key |
| order | randomised per listener |
| blinding | neutral filenames; key sealed until all responses are recorded |

**Predefined handling of unclear or missing responses**, fixed now so no
exclusion is retrospective:

- A missing or unparseable response is dropped from that pair's denominator;
  the pair remains in the study.
- A listener missing **more than half** their 14 assignments is excluded
  entirely, and the exclusion is reported with the count.
- "No discernible difference" is a **valid response**, counted as a tie. It is
  never treated as missing data.

## 4. The renderer is unchanged

Retained for this experiment, for three reasons:

1. It demonstrably exposes substantial melodic disruption (9/10 paired).
2. Changing it introduces a variable that would itself need calibration.
3. **Per-voice timbres are not a trivial improvement here.** Original hardware
   voice indices are not stable musical-role identifiers — three lead-voice
   criteria agreed on one voice in only 9.9% of tracks — and the v2 codec
   reallocates voices extensively (median 39–49%, maximum 100%). Assigning a
   distinct instrument per slot could manufacture audible structure, or
   artifacts, that did not come from the model.

A better synthesiser may be worthwhile for a later study. It is not an
indefinite prerequisite for this one.

## 5. Training — unchanged

| | |
|---|---|
| architecture | decoder-only, d_model 256, 6 layers, 8 heads, context 1024, weight-tied |
| parameters | 5,646,336 (vocabulary 2,544) |
| optimizer | AdamW, lr 1e-3, weight decay 0.01, grad clip 1.0, bf16 autocast / fp32 loss |
| schedule | warmup 200 steps, cosine completing at the budget |
| batch | 8 — the measured throughput knee |
| seed | **0, one primary run** |
| budget | **20 epochs = 23,980 optimizer updates** |
| exposure | **178,133,840 scored targets** |
| evaluation | every 600 steps; early stop patience 8 evaluations |
| selection | **validation only**, bits per scored target; test split sealed |

Cheap compute does not authorise an undeclared model search. Any further run
is exploratory, labelled as such, and cannot supply the primary result.

## 6. The claim table

| claim | status |
|---|---|
| v2 produces more musically organized output than the G3 baseline | **testable primary hypothesis** |
| v2 output approaches genuine music in perceived organization | secondary, **descriptive only** |
| v2 produces independently coherent compositions | **not established by this instrument** |
| v2 demonstrates long-range thematic development | exploratory, not a success criterion |
| v2 satisfies syntax, clock progress and eight-voice occupancy | **engineering guarantees, excluded from musical scoring** |

**A preference victory over a poor baseline can still leave both models
producing bad music.** The report must say so explicitly if that is what the
results show.

The 45–60 second artifact is unchanged, but it requires 3–4 context rollovers
at ~15.3 s of effective context, and a snapshot carries active-note state
rather than earlier musical material. The endpoint therefore evaluates
**perceived organization within** the artifact, never evidence that the model
planned a composition.

## 7. The engineering ledger

Reported separately; **never** counted toward musical success.

| guaranteed by construction | measured intervention |
|---|---|
| grammatical framing | grammar-mask exclusions, and the probability mass removed |
| strictly positive clock progress | forced group closures |
| ≤8 occupied voices | voice displacement |
| complete delta escapes | truncated completions |
| | invalid handle attempts |

Pre-mask probability mass is the diagnostic that matters: a model whose output
is valid mainly because masking redirected it has not demonstrated
independent competence. **Every registered excerpt is retained**, including
incomplete and heavily corrected ones. No selecting what renders cleanly.

## 8. Remaining before the training run

1. Generation seeds and sampling parameters fixed and recorded (sampling
   chosen by the registered listening-free distributional procedure on
   train/dev only).
2. The matched G3 baseline implemented — an interpolated n-gram over G3
   tokens, Witten-Bell smoothed, order selected on validation only, with the
   grammar mask applied **identically** to both arms.
3. The clustered-bootstrap analysis implemented and tested on synthetic
   responses before any real ones exist.
