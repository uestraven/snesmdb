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
| **Musical preference** | ≥60% preference for model excerpts over matched baseline excerpts in blind listening | 2 (primary) |
| **Originality** | no identified near-exact copying of substantial training passages, judged by review of flagged matches against a **corpus control** | 2 (primary) |

Level 1 passes on **Learning + Reproducibility**. Level 2 passes on **Musical
preference + Originality**.

### Two corrections to the proposed criteria

**The test set holds 8 games, not 6.** Actraiser, Adventure Island, Alien 3,
F-Zero, Shadowrun, Star Fox, Tactics Ogre, Tetris 2. A sign test over 8 games
needs **7 of 8** to reach p<0.05 one-sided (7/8 = 0.035, 6/8 = 0.145). Rather
than set a criterion that cannot carry the claim, generalization is registered
as a **paired bootstrap over test tracks** (primary) with the per-game count
reported as a descriptive secondary. A "4 of 6" style threshold is explicitly
NOT registered as sufficient.

**Originality needs a corpus control, not a threshold.** This project has
already learned that a repetition metric without a control is meaningless: on
the NES side, exact-bar restatement looked damning until the corpus was
measured and found barely to repeat itself either. So every similarity metric
is computed on the model's output **and on held-out real tracks**, and the
model is judged against that control rather than against an absolute number.

## Population and splits

The published 50-game split is used verbatim. **The test split is not touched
until model and hyperparameter selection are final.**

Restricted to `track_class == "music"`, following the precedent of the existing
interval baseline, which dropped 353 non-music tracks by definition:

| split | all tracks | music only | games |
|---|---|---|---|
| train | 1,785 | **1,384** | 33 |
| valid | 225 | **180** | 9 |
| test | 218 | **176** | 8 |

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

## Listening test

Short excerpts (~16 bars), model and baseline rendered through the **same
neutral synthesiser**, blind, randomised pairs. Judged on musical coherence,
rhythmic organisation, melodic development and overall listenability.

**Listeners are NOT asked which sounds more like authentic SNES hardware.**
The symbolic dataset does not supply every parameter needed for faithful SNES
synthesis; this tests composition, not emulation fidelity.

The design target is 20 listeners × 12 randomised pairs, analysed with a model
accounting for repeated judgements by listener and by excerpt.

> **Open logistical risk:** every listening result in the parent project to
> date has come from a single listener. If 20 listeners cannot be recruited,
> the 60% criterion cannot carry the phrase "blind listeners consistently
> prefer", and the Level 2 claim must be restated as a single-listener
> preference with far wider uncertainty. **This must be settled before the
> listening test runs, not after.**

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
