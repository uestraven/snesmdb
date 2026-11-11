# RSE v2 generation and sampling-selection procedure — FROZEN

**Frozen before training.** The procedure is fixed here; its *outputs* — the
selected temperature and top-p — are determined later by running it on the
locked checkpoint. That is a deterministic prospective procedure, not a
deferred decision.

Specified in enough detail that a separate agent could reproduce the selection
without consulting the authors.

## 1. Candidate grid

| axis | values |
|---|---|
| temperature | 0.8, 0.9, 1.0, 1.1, 1.2 |
| top-p | 1.0, 0.95 |
| combinations | **10**, evaluated exhaustively |

Order of application, fixed: temperature, then top-k (unused, k=0), then
nucleus. No other sampling parameter is swept.

## 2. Seeds

| purpose | seeds |
|---|---|
| development (selection) | **1000, 1001, 1002, 1003** |
| primary evaluation | **0 … 23** (24 excerpts per arm) |

The two lists are disjoint, so selection cannot be contaminated by the batch
it will produce. Both are fixed here.

## 3. Distributional metrics

Computed identically on generated output and on the reference.

| metric | definition |
|---|---|
| attacks per second | note starts ÷ excerpt span, **per excerpt**, then median |
| mean simultaneous voices | mean notes per distinct onset, per excerpt, then median |
| melodic interval histogram | per voice, consecutive pitched starts, clipped to ±12 semitones, pooled |

**Reference population**: 60 training tracks, shuffle seed 0,
**round-tripped through G3** — encoded and decoded — so the generators are not
charged for the representation's own quantisation. Validation and test are not
used.

**Per-excerpt then median, never pooled.** Level 2 pooled event lists and
reported 296 attacks/s against a true corpus range of 13–26, because every
decoded item restarts its clock near zero.

## 4. Selection objective

    distance = |a_gen - a_ref| / a_ref
             + |v_gen - v_ref| / v_ref
             + 0.5 * sum_k |h_gen(k) - h_ref(k)|

where `a` is median attacks/second, `v` is median simultaneity, and `h` is the
normalised interval histogram. The third term is total variation, already on
0–1, so it needs no standardisation. All three weights are 1. Lower is closer
to the corpus.

**Tie-break, deterministic**: lowest distance, then lowest temperature, then
highest top-p. Distances compared at 6 decimal places.

**No audio is heard and no test data is touched during selection.**

## 5. Duration and stopping

| property | value |
|---|---|
| target | **45–60 seconds** |
| soft stop | at the first group boundary where the clock reaches **45.0 s** |
| hard cap | **60.0 s** — generation stops at the next group boundary |
| token budget | **6,000** tokens (≈98 s at the measured 60.9 tok/s) |
| boundary convention | half-open `[0, T)`, as in the codec |
| EOS | honoured immediately if sampled; the excerpt is retained and marked short |

Stopping is only ever evaluated **at a group boundary**. Level 2 cut mid-event
and produced sequences that failed the validity criterion for the harness's
reason rather than the model's.

## 6. Failure accounting

Every registered seed produces **one retained outcome**. Nothing is silently
replaced or regenerated.

| outcome | recorded as |
|---|---|
| reached 45–60 s | `complete` |
| EOS before 45 s | `short`, with its duration |
| token budget exhausted | `budget_exhausted` |
| grammar failure | `invalid`, with the failing position |
| forced group closure | counted in the intervention ledger |

A seed producing an unusable excerpt is reported, not re-rolled. Excerpt
counts in any rate therefore always appear beside their denominator.

## 7. Context rollover

Generation uses the **frozen** `StreamState` and `build_windows` snapshot
machinery — the same code path verified for training/inference equivalence at
contexts 64/128/256/1024. **No separate inference path exists.**

A 45–60 s excerpt needs 3–4 rollovers at ~15.3 s effective context. Each
rollover carries the active-note snapshot — handle, current pitch, status, age
— and **not** earlier musical material.

The grammar mask is supplied by `legal_at` from the same causal state in both
arms, including across the snapshot prefix. Pre-mask probability mass on
illegal tokens is recorded per arm.

## 8. The baseline gets the identical procedure

The Kneser-Ney order 1 comparator is run through steps 1–7 unchanged: same
grid, same development seeds, same objective, same tie-break, same duration
and stopping rules, same rollover, same mask, same renderer. Its parameters
are selected without listening, exactly as the Transformer's are.

The two arms may land on different numerical settings. That is expected and
registered: the *procedure* is symmetric even where the models need different
temperatures to reach comparable distributional behaviour.

## 9. What may not happen after selection

- No temperature or top-p change.
- No alternative seeds.
- No handpicked examples.
- No regeneration of an unflattering excerpt.

The final settings are recorded as **outputs of this procedure**, not as
hyperparameters chosen with hindsight.
