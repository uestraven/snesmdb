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

---

## AMENDMENT A1 — development-candidate eligibility (2026-11-12)

**Registered before any development generation was evaluated.** No excerpt
existed when this was written, so it is prospective relative to the outcomes
it governs.

**Reason for the amendment.** The registered objective was **undefined** for a
decoded performance containing zero notes. §3's metrics — attacks per second,
mean simultaneity, interval histogram — all require at least one note.
Omitting those failures from a candidate's median would bias selection.

### The bias this avoids

| candidate | decodable seeds | median over survivors |
|---|---|---|
| A | 1 of 4 | excellent, on its single success |
| B | 4 of 4 | good, on all four |

Scoring over survivors could select A, rewarding a configuration **because**
its failures were excluded. That defeats the fixed four-seed design.

### The rule

1. Each temperature/top-p candidate produces **exactly four** outcomes, from
   its registered development seeds.
2. A candidate is **eligible only if all four** outcomes decode into
   performances for which the frozen distributional metrics are defined.
3. For eligible candidates the objective is computed exactly as registered in
   §4: per-excerpt statistics, then the median aggregation and tie-break.
4. A candidate with one or more undecodable or zero-note outcomes is
   **ineligible** — not assigned a penalty, and **not scored over its
   surviving seeds**.
5. All outcomes are retained. Ineligible candidates are reported with their
   failure reasons.
6. **If no candidate is eligible, sampling selection is declared
   unsuccessful.** No fallback is chosen, the grid is not changed, and seeds
   are not replaced.

### What this does NOT change

`short` and `budget_exhausted` remain **decodable outcomes** governed by §5
and §6. They are not reclassified as invalid: this amendment concerns
zero-note decoded performances only. No other metric, weight, candidate, seed,
threshold or tie-break is altered.

### Denominators

Reported separately and never conflated:

| population | expected |
|---|---|
| attempted outcomes | **40** = 10 candidates × 4 seeds |
| eligible candidates | 0–10, reported with the count |

---

## ADDENDUM D1 — duration is reported, not scored (2026-11-12)

**Not an amendment. No registered quantity changes.** This records a decision
taken after the first clean baseline run, and the reason it was taken.

### The gap

§4's objective scores density, mean simultaneity and the interval histogram.
**None of the three measures duration.** So a candidate whose excerpts barely
play can score well on all three.

It did. The baseline arm's winning candidate (t=0.8, top-p=0.95) scored
**0.6969** — 17.63 attacks/s against a reference of 17.88, simultaneity 1.89
against 2.30 — while its duration distribution was:

| | whole arm (40 outcomes) | winning candidate (4) |
|---|---|---|
| in the 45–60 s target | **1 / 40** | **1 / 4** |
| under 5 seconds | **12 / 40** | 1 / 4 |
| shortest | **0.05 s** | 0.60 s |
| median | 11.29 s | 27.99 s |
| longest | 104.63 s | 45.08 s |

**No candidate in the grid reached more than 1 of 4 in target.**

A 0.05 s excerpt with corpus-like local density is, to this objective,
indistinguishable from a 50 s one.

### The decision

**§4 stays frozen, and §5 stays frozen.** Changing either would be
retrospective relative to the baseline arm, which has now been run and seen.
The remedy is visibility, not a changed formula:

1. Every candidate row carries a `duration` block — min, median, max, count
   in the 45–60 s target, count under 5 s, count past the hard cap — marked
   `"scored": false`.
2. The selected candidate carries the same block, so the one summary a reader
   quotes cannot omit it.
3. When no development excerpt of the winning candidate reached the target,
   the run says so explicitly in its output.

Nothing in this addendum feeds `objective()` or `tie_break_key()`. A test
asserts that two candidates differing only in duration receive the
**identical** objective, which is the property this addendum deliberately
preserves rather than fixes.

### What follows from it

The duration figures are a **result about the comparator**, not a defect in
it: Kneser-Ney order 1 cannot hold a 45–60 s form, and samples `EOS` early in
37 of 40 outcomes. That is reportable evidence, and it also means the
**blinded paired listening study cannot be administered as designed** if one
arm's excerpts are sub-second and the other's are ~47 s — the pairing would
not be blind. That is recorded here as an open question for §8 and for
`V2_MILESTONE3_PROTOCOL.md`, not resolved.

### Hard-cap overshoot

§5 stops "at the next group boundary" and the clock advances only when a
delta is sampled, so **one sampled delta can jump past the 60 s cap**. The
baseline produced excerpts at **85.23 s** and **104.63 s**; a
uniform-distribution probe reached 3,030.91 s.

This is conformant with §5 as written, and §5 is not amended — masking an
overshooting delta would change the registered grammar mask that both arms
share. Instead `Excerpt.exceeded_hard_cap` is set whenever the terminating
boundary was already past 60 s, so such an excerpt can never be read as an
in-target 45–60 s result. 2 of 40 baseline outcomes carry the flag.
