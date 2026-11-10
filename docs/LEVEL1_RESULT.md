# Level 1 result — sealed test evaluation

Run once, on 2026-11-10, after the model, checkpoint, configuration,
tokenizer, baseline configuration and evaluation code were frozen. Protocol:
[PROTOCOL_FREEZE.md](PROTOCOL_FREEZE.md). Pre-registration:
[EXPERIMENT_PREREGISTRATION.md](EXPERIMENT_PREREGISTRATION.md).

## Verdict: LEVEL 1 PASSES

| measurement | value |
|---|---|
| comparator, re-measured on test | **3.5442** bits/token |
| locked model | **2.7057** bits/token |
| registered threshold (0.95 x baseline) | 3.3670 |
| **relative improvement** | **23.66%** |
| bootstrap 95% CI, over tracks | **[22.63%, 24.68%]** |
| bootstrap 95% CI, over games | **[21.93%, 25.92%]** |
| games improved | **8 / 8** |
| test population | 176 music tracks, 8 games, 1,313 windows |

The registered criteria for Level 1 are **Learning** and **Reproducibility**.
Both are met: the improvement clears 5% with a bootstrap lower bound of
22.63%, and the split, configuration, seeds, evaluation code and checkpoint
hash are all fixed and recorded.

## Per-game, all eight reported

| game | relative improvement |
|---|---|
| Alien 3 | +28.06% |
| Adventure Island | +27.51% |
| F-Zero | +27.00% |
| Actraiser | +24.03% |
| Tetris 2 | +23.86% |
| Star Fox | +23.81% |
| Shadowrun | +21.77% |
| Tactics Ogre | +20.15% |

8 of 8 is the only per-game count that reaches conventional two-sided
significance at this corpus size: exact sign test p = 0.0078, against 0.0703
for 7 of 8. The paired bootstrap remains the primary evidence; this is the
registered descriptive secondary.

## Per-slot breakdown

| slot | model | comparator | gain |
|---|---|---|---|
| TIME | 1.926 | 2.953 | +34.8% |
| VOICE | 1.565 | 2.162 | +27.6% |
| PITCH | 4.587 | 5.616 | +18.3% |
| DUR | 2.746 | 3.445 | +20.3% |

The improvement is broad: every token class benefits, including pitch, which
is the class a repetition model handles worst — the comparator beats the
unigram floor by only 5% on pitch against 38% on duration. Pitch nevertheless
remains the model's highest residual uncertainty at 4.587 bits.

This answers the question the diagnostic was registered to ask. The concern was
that a model might merely exploit the highly predictable voice and duration
fields; it does not. It improves on all four, by the largest margin on timing
and by a substantial margin on the hardest field.

## Uncertainty: two units, and what neither supports

The registered statistic resamples **tracks**. That answers "how uncertain is
this improvement over these 176 tracks" and it is the criterion the protocol
binds to.

It does **not** answer "how uncertain is it over unseen games". Tracks within a
game share a composer, a driver, an instrument bank and an idiom, so 176 tracks
are nowhere near 176 independent observations of game-level performance. A
**game-clustered bootstrap**, resampling whole games, is therefore reported
alongside:

| unit | n | 95% CI | width |
|---|---|---|---|
| tracks (registered) | 176 | [22.63%, 24.68%] | 2.05 pts |
| games (clustered) | 8 | **[21.93%, 25.92%]** | 3.99 pts |

Clustering roughly doubles the width and the lower bound still sits 4.4x above
the 5% threshold, because between-game variance is low — every one of the eight
improved by 20-28%.

**Neither interval supports a claim about the wider SNES library.** With only 8
clusters a clustered bootstrap is itself anti-conservative, so even the wider
figure understates game-level uncertainty. The binding limit is not the
statistic; it is that eight games are eight games, drawn from a split separated
by game family and recorded composer-credit connections rather than by proven
authorship independence, in a corpus where 406 of 2,228 tracks carry an
incomplete or missing credit.

## Reconciling the two baseline figures

Three numbers appear for the same frozen comparator. They differ by scoring
convention, not by configuration, and the model is scored identically in each
case:

| figure | split | scoring convention |
|---|---|---|
| **3.3839** | validation | whole-track sequences; history spans the track |
| **3.3898** | validation | windowed; history confined to each 1024-token window |
| **3.5442** | **test** | windowed; history confined to each window |

The 3.3839 to 3.3898 step is the **0.17% window-boundary handicap**: confining
history to a window truncates the comparator's order-10 context in roughly the
first 40 tokens of each window. The windowed convention is used for the
judgment because it is what the model sees, and scoring the comparator on whole
tracks would have given it 1,137 extra targets on the test split.

So the registered comparison is **2.7057 against 3.5442, both windowed, both on
test**. The 3.3839 figure belongs to baseline selection and should not be
compared to a test number.

## Two properties of the measurement, stated rather than buried

**Test is harder than validation for both models** — 2.7057 against 2.5824 for
the model, 3.5442 against 3.3898 for the comparator. This is the documented
split non-interchangeability (pitched share 77.5 / 81.8 / 85.5% across
train/valid/test), and it is why the registered criterion is measured against
the baseline re-measured on test rather than against the 3.2147 validation
reference. Had the validation threshold been used, the bar would have been
wrong in the model's favour.

**The relative margin is stable across splits**: 23.66% on test against 23.82%
on validation. Absolute difficulty shifts between splits; the margin does not.

**Identical targets.** Both models were scored on the same 1,313 windows with
history confined to each window, and the evaluator asserts equal target counts
before computing anything. Scoring the comparator on whole tracks instead
would have given it 1,137 extra targets on this split and the two would not
have been performing the same task. The comparator is still *fitted* on whole
train tracks, which favours it.

**The evaluator was verified before the test set was opened**, by running the
entire pipeline on validation: it reproduced the training loop's 2.5824 and all
four of its per-slot values exactly, from an independently implemented scoring
path.

## What this establishes, and what it does not

Established: a 5.06 M-parameter decoder-only Transformer trained on
hardware-extracted SNES performance data predicts held-out musical events
substantially better than a strong, representation-aware statistical
comparator, on eight games it never saw, with the improvement broad across
timing, voice, pitch and duration.

**Not established: anything about musical quality.** Level 2 requires the
separate multi-listener study, and the 60% preference criterion applies only
there. A single-listener pilot can diagnose rendering faults and obvious
weaknesses; it cannot demonstrate Level 2.

The caution is concrete rather than formal. On the NES side of this project, a
clean retrain that improved validation loss by 11.4% produced output the
listener called "barely music". A 23.66% likelihood improvement is the same
*class* of evidence. It is a stronger result, measured far more carefully,
against a much better comparator — and it still does not tell us how the
generated music sounds.

Eight held-out games also remain eight games. Conclusions about the wider SNES
library need the qualification that the test population is small, that splits
are separated by game family and recorded composer-credit connections rather
than by proven authorship independence, and that 406 of 2,228 tracks carry an
incomplete or missing credit.

## Provenance limitations, stated plainly

**The pre-registration was not publicly timestamped before the result.** The
commits were authored locally in sequence — pre-registration, protocol freeze,
baselines, training, sealed evaluation — and the git history records that
order. But the repository was not pushed until after Level 1 completed, so
nothing here establishes public, third-party-verifiable pre-registration.

The defensible claim is: **the criteria were fixed in local commits before the
corresponding measurements, and the commit sequence is the evidence.** That is
weaker than a public preregistration timestamp and must not be reported as one.
For Level 2, push the registration before running it.

**The original training logs were not retrieved.** `history.jsonl` and
`summary.json` remain on RunPod network volume `kcc2582kg8`; the pod was
terminated before they were downloaded. The trajectory preserved in
`level1_artifacts/training_trajectory.tsv` is a transcription from the run's
stdout, labelled as such. The primary artifact is unaffected: `best.pt` carries
its own configuration, step and validation loss, and its sha256 matches what
the pod reported at save time.

**Immutable copy.** All Level 1 artifacts are sealed at
`level1_artifacts/` with a `SHA256SUMS` manifest. No later experiment may
modify them.

## Reproducing

```sh
python scripts/snes_lm_gpu.py throughput
python scripts/snes_lm_gpu.py sweep                  # 6 configs, validation only
python scripts/snes_lm_gpu.py full --lr 1e-3 --d-model 256 --n-layers 6
python scripts/snes_lm_sealed_eval.py --checkpoint best.pt
```

Checkpoint sha256:
`c146d36ad661fe3643f7c2896ad3747e663aac0c6741124165b6c9ba8e6bc6a9`
Selected at step 5,000 of a 50,000-step budget, seed 0, lr 1e-3, 256x6,
5,056,512 parameters. Full report: [sealed_test_result.json](sealed_test_result.json).
