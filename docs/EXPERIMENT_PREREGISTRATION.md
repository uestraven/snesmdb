# Pre-registration — can a model learn musical structure from snesmdb?

**Registered 2026-11-10, before any model was trained.** The point of this
document is that the thresholds below were fixed in advance. If a result is
later reported against a different threshold, that is moving the goalposts and
this file is the evidence.

Release under test: **snesmdb-50game-rc1** (2,228 tracks, 50 games, 3,205,461
attacks).

---

## The question

Can a model trained on hardware-extracted SNES performances learn meaningful
musical structure and generate new, coherent compositions — rather than merely
statistically plausible note sequences?

A successful *machine-learning* experiment and a successful *music generator*
are related but not identical achievements, and are registered separately.

## Three levels

**Level 1 — Technical.** The model trains reproducibly, learns from the
symbolic representation, and predicts held-out events better than strong
statistical baselines. Establishes that the dataset supports real ML training.

**Level 2 — Musical.** The model generates original, rhythmically organised,
polyphonic passages that blind listeners consistently prefer to an elementary
statistical generator. Establishes something beyond prediction accuracy.

**Level 3 — Research contribution.** That specific properties of snesmdb's
representation (polyphonic timing, sample-aware features) give measurable
benefit over simpler representations.

> **Level 3 is OUT OF SCOPE for this experiment, by the dataset's own
> evidence.** Sample identities barely overlap between splits, so `sample_id`
> is unusable as a cross-split categorical feature, and milestone 5's exit
> criterion — a transferable instrument vocabulary — was not met. A
> sample-aware arm would be measuring an identity the test split has never
> seen. Polyphonic-timing ablations remain testable and are deferred to a
> follow-up, not folded in here.

## Acceptance criteria

| test | criterion | level |
|---|---|---|
| **Learning** | ≥5% relative reduction in held-out NLL vs the strongest matched baseline | 1 (primary) |
| **Reproducibility** | fixed split, config, eval scripts, recorded seeds; rerun reproduces reported numbers | 1 (primary) |
| **Generalization** | paired bootstrap over test tracks excludes zero improvement; per-game deltas reported for all 8 games with no game materially worse | 1 |
| **Generation validity** | ≥99% structurally valid generated event sequences | 1 |
| **Musical preference** | ≥60% preference for model excerpts over matched baseline excerpts, **multi-listener study only** | 2 (primary) |
| **Originality** | no identified near-exact copying of substantial training passages, judged by review of flagged matches against a **corpus control** | 2 (primary) |

Level 1 passes on **Learning + Reproducibility**. Level 2 passes on **Musical
preference + Originality**, and the preference criterion is satisfiable **only
by the multi-listener study** — see the listening section.

A Level 1 pass is a meaningful result on its own: it would establish that
hardware-extracted SNES symbolic data supports reproducible learning on unseen
games. There is no need to manufacture a Level 2 success for the work to be
worthwhile, and this document exists partly to make that explicit in advance.

### Two corrections to the proposed criteria

**The test set holds 8 games, not 6.** Actraiser, Adventure Island, Alien 3,
F-Zero, Shadowrun, Star Fox, Tactics Ogre, Tetris 2. Exact sign test over 8:

| games improved | one-sided | two-sided |
|---|---|---|
| 8/8 | 0.0039 | 0.0078 |
| 7/8 | 0.0352 | **0.0703** |
| 6/8 | 0.1445 | 0.2891 |

So **not even 7 of 8 clears a conventional two-sided 5% test** — only 8 of 8
does. A per-game count cannot carry the generalization claim at this corpus
size in either direction. Generalization is therefore registered as a **paired
bootstrap over test tracks** (primary), with per-game deltas reported purely
descriptively. A "4 of 6" style threshold is explicitly NOT registered as
sufficient, and neither is 7 of 8.

**Originality needs a corpus control, not a threshold.** This project has
already learned that a repetition metric without a control is meaningless: on
the NES side, exact-bar restatement looked damning until the corpus was
measured and found barely to repeat itself either. So every similarity metric
is computed on the model's output **and on held-out real tracks**, and the
model is judged against that control rather than against an absolute number.

## Population and splits

The published 50-game split is used verbatim. **The test split is not touched
until model and hyperparameter selection are final.**

Restricted to `track_class == "music"`. **One filter, fully accounted for:**

| split | all tracks | music only | games |
|---|---|---|---|
| train | 1,785 | **1,384** | 33 |
| valid | 225 | **180** | 9 |
| test | 218 | **176** | 8 |
| **total** | **2,228** | **1,740** | 50 |

The 488 excluded tracks are `jingle` 364, `drone` 35 and `effect` 89, summing
exactly to 2,228 − 1,740. **There is no second eligibility filter.**

An earlier draft of this section cited "353 non-music tracks" as the
precedent. That figure belongs to a DIFFERENT population — the 27-game
release, 1,477 tracks — and quoting it here implied an exclusion count that
does not apply to this experiment. The policy precedent stands (exclude
non-music by class, by definition rather than silently); the number does not.

Splits are separated by game family and recorded composer-credit connections.
**They are not proof of authorship independence**: 406 tracks carry an
incomplete or missing credit, and a possible authorship overlap covering 206
tracks is unresolved. Every memorization and generalization claim is therefore
about an **unseen game**, never an unseen composer.

The splits are also not interchangeable samples, and this is reported rather
than normalised away: pitched share runs 77.5 / 81.8 / 85.5% across
train/valid/test, validation is 43% expansion cohort against train's 6.8%, and
test median max polyphony is 6 against 8.

## Baselines

All evaluated on the identical event representation and test population.

1. **Unigram / frequency** — the floor.
2. **Tuned n-gram** — order and smoothing selected on validation only. The
   27-game precedent: order-2/3 interval n-gram reached 43.09% test accuracy
   and 3.280 bits against the frequency baseline's 32.23% and 4.015 bits.
3. **Repetition controls** — including interval reversal, which scored 36.72%
   in exploratory 27-game testing, i.e. well above the frequency floor without
   learning anything.

The 27-game figures are **not transferable** to the 50-game task and are cited
only to show why beating random is not the bar.

## Model

One small symbolic Transformer over pitch, duration, onset timing and
polyphonic voice relationships. Sample-aware features are deliberately held
back for a follow-up, because content-based sample identities do not map to
portable instrument categories across games.

A new SNES representation is built for this. RSE's frozen
`rse-repr/1.0.0-d4k4-tempo1.01` is NES-specific — four channels, duty-cycle
timbre, vocabulary 555 — and must not be modified.

## Compute discipline

Measured on the development machine (8 cores, CPU-only torch): **6,600 tok/s**,
1.25 s/step for a 5.2M-parameter model at context 1024. So 50k steps is 17.4 h
on CPU against roughly 56 minutes on the RTX PRO 4500 used previously, at about
$0.70.

**Registered rule: any run over 200 steps happens on GPU.** CPU is for smoke
runs only — proving the data loader, checkpointing and evaluation path work end
to end before anything is billed.

The reason is a measured waste, not a preference: the previous pod billed $4.33
in a day at 0% GPU utilisation, because it was provisioned before there was
anything to run. Provision late, run the sweep, terminate immediately.

Model size starts at ~5M parameters rather than larger. The NES foundation was
5.67M and its limit was never capacity — it was the objective. Starting small
also keeps a CPU fallback genuinely viable.

## Time base — measured, then chosen

The release offers three candidate time bases. The choice was made by measuring
coverage across all 1,740 music tracks, not by preference.

| candidate | coverage | verdict |
|---|---|---|
| per-track native row grid (`onset_grid`) | train 68.9% / valid 73.3% / **test 60.2%** found; only **51%** plausible | **rejected** |
| fixed 100 Hz uniform grid | 100%, snapping cost 0.0% | secondary |
| unquantised `onset_sec` | 100% | **primary** |

The native grid is rejected for three measured reasons, despite milestone 4
having genuinely delivered it — the SPC700 timer register was read for **100%**
of tracks:

1. **Coverage is only 60-73%.** The dominant failure reason is the dataset's
   own: "onsets do not lie on a single period even after clustering".
2. **Coverage is split-dependent** — 60.2% on test against 68.9% on train. That
   would make train and test differently representable, which is exactly the
   kind of asymmetry that invalidates a cross-split comparison, and it would
   stack on the non-interchangeability already documented.
3. **Half the found grids are not musical.** In a 300-track sample: 154
   plausible at 4-40 rows/s, 39 above 40, 21 below 4. `rows_per_second` spans
   1.18 to 500.00 corpus-wide.

**Primary representation: delta-time tokens from unquantised `onset_sec`**,
bucketed by quantiles **fitted on the training split only**. This assumes no
grid, covers every event, and keeps the sealed split sealed.

The 100 Hz uniform grid is retained as a **secondary** representation, and the
comparison between the two is exactly the deferred Level 3 representation
ablation rather than something to fold in here.

Driver labels are used for **no** modelling purpose — not as features, not for
stratification — because the release documents them as "curated external
knowledge, NOT derived from the SPC files… a hypothesis to test rather than a
measurement". Per-driver breakdowns remain legitimate as descriptive output.

## Listening test

Short excerpts (~16 bars), model and baseline rendered through the **same
neutral synthesiser**, blind, randomised pairs. Judged on musical coherence,
rhythmic organisation, melodic development and overall listenability.

**Listeners are NOT asked which sounds more like authentic SNES hardware.**
The symbolic dataset does not supply every parameter needed for faithful SNES
synthesis; this tests composition, not emulation fidelity.

**Settled 2026-11-10.** Two studies, with different standing. 20 independent
listeners cannot be recruited by the project, and completion of the ML
experiment is explicitly NOT made dependent on recruiting volunteers.

| study | purpose | permitted conclusion |
|---|---|---|
| single listener, blinded | **exploratory pilot** | "one listener preferred one model over another" — nothing more |
| ~20 independent listeners | **confirmatory Level 2** | evidence of listener preference, subject to uncertainty analysis |
| no listening study | Level 1 only | no claim about perceived musical quality |

**The 60% criterion applies to the multi-listener study only.** It is not a
passing threshold for a single listener, and a single-listener result at or
above 60% does not demonstrate Level 2.

**A poor pilot means Level 2 is NOT DEMONSTRATED, not conclusively failed.**
That distinction matters precisely because a failure is the registered
prediction: a weak pilot is consistent with the prediction but is not evidence
for it at n=1.

The pilot's legitimate uses are diagnostic — finding rendering problems,
confusing comparisons, or obvious musical weaknesses. It must not be used to
tune the model, and it touches no test-set decision.

For the eventual multi-listener study: 12 randomised comparisons per
participant, retained as proposed. Uncertainty is analysed across **both
listeners and excerpts** — 240 judgements from 20 people are not 240
independent observations.

## Known measurement traps

Registered here because walking into one would invalidate a result.

- **Polyphony.** The published 6-dp onsets are not float64-representable, and
  a naive sweep reports **9 to 13 simultaneous voices on 8-voice hardware**.
  Parse with `decimal.Decimal`, process closes before opens at equal
  timestamps, and apply one documented remedy (clamp to next onset, ignore
  overlaps ≤1 µs, or union per-voice intervals).
- **Absolute pitch.** `midi_note` is a per-sample estimate, fractional and not
  clamped — measured −36.74 to +131.09. Interval-based metrics do not inherit
  this; absolute-pitch metrics do.
- **Legato.** `origin == "legato_step"` is a pitch change inside a sounding
  note, not an attack. Include or exclude by definition and say which.
- **Right censoring.** 4,674 key-ons were still sounding when the render
  window ended, median onset at 99.64% of the window. Budget against that
  figure, not against the 159,584 null durations.

## Prediction, recorded in advance

The model beats the n-gram on next-event prediction and **fails** the
listening test. Confidence ~75%.

Basis: two independently trained NES models lost decisively to a rules-based
composer, and an 11.4% validation-loss improvement there produced output the
listener called "barely music". Nothing in this design changes the training
objective; what it changes is that the evaluation can now tell the two
outcomes apart.

Recording this so that a Level 1 pass is not quietly presented as a Level 2
result, and so that the predicted outcome — Level 1 passes, Level 2 fails — is
reported as the informative result it would be, rather than as a failure.

## What a pass would and would not establish

A pass at Levels 1 and 2 would support: hardware-extracted SNES symbolic music
can train a model that learns and generates musical structure beyond simple
statistical baselines.

It would **not** establish that the model produces human-quality compositions,
that it reproduces authentic SNES performances, or that snesmdb is superior to
any other dataset. Those are different claims needing different comparisons.
