# RSE v2 Milestone 1: the 4000 Hz grouped-event codec

**Closed.** No model has been trained. Milestone 2 addresses the token
inventory and generation architecture.

## Selected resolution: 4000 Hz

**The resolution ladder is a sequence of corrections, not a clean derivation,
and should be read as one.** 250 Hz was chosen from a 60-track development
sweep; the full train audit rejected it (78 tracks collide two legato pitch
changes onto one grid step). 1000 Hz then passed on train and validation and
**failed on the held-out test split** — one track, `tet2-17`, with 5
collisions. 4000 Hz passes all twelve criteria on all three splits.

The honest reading is that the development sample was never large enough to
select a resolution. Each step was evidence-driven, but 4000 Hz was arrived at
by elimination, not by a sound a-priori procedure.

| grid | verdict | onset mean / max | duration mean / max |
|---|---|---|---|
| 250 Hz | FAIL — 78 train tracks, legato collisions | 0.975 / 2.000 ms | 1.287 / 3.996 ms |
| 1000 Hz | FAIL — passes train and valid, fails test | 0.246 / 0.500 ms | 0.323 / 0.999 ms |
| **4000 Hz** | **PASS on train, valid and test** | 0.064 / 0.125 ms | 0.083 / 0.249 ms |

The finer grid costs almost nothing. Actions per source event and median
actions per track are **identical at every grid** — the grid changes only the
time-delta vocabulary's range, not sequence length. An earlier claim in this
project that sequence economy favoured a coarser grid was wrong.

## What is established

**Symbolic musical reconstruction**, over the **entire 1,740-track music
population** — train, validation and test, 3,452,267 source events:

| measurement | result |
|---|---|
| attacks preserved | **3,174,938 / 3,174,938** |
| legato pitch changes retained | **277,329 / 277,329** |
| legato changes fully verified by identity, value and order | **277,329** |
| lost / duplicated attacks | 0 / 0 |
| indistinguishable starts | 0 |
| same-step rekey collisions | 0 |
| decoder-induced voice steals | 0 |
| unmatched ends, orphaned pitch changes | 0 / 0 |
| peak occupied voices | ≤ 8 on every track |
| onset error | max 0.125 ms = the quantisation bound, every split |
| systematic displacement | signed mean +0.0011 / −0.0015 / +0.0009 ms by split |

**The ordering guarantee is exercised, not merely available.** At 4000 Hz
there are no same-step collisions, so ordering passes vacuously. It was
therefore also run at 250 Hz, where 78 train tracks *do* collide: all 220,809
changes verified with **zero ordering mismatches**, demonstrating that the
explicit per-parent `sequence` index preserves order through collisions. The
250 Hz failure is a loss of timestamp distinctness, not of musical
information — but the criterion is not relaxed on that basis, because it
exists so the representation does not depend on a recovery mechanism being
correct.

Legato verification compared each decoded change against its source
`events.v4` record by stable `event_id`, not by count: parent identity, event
identity, pitch status, pitch value, preserved unrecoverability, ordering
within each parent, and time. Zero mismatches in all eight categories. For the
~18.5% of legato steps whose pitch is unrecoverable, a reconstructed value is
scored as its own failure category; none occurred.

**Voice steals are structurally impossible, not merely absent.** With the
encode-time rekey clamp, each provenance voice holds at most one active note
and there are at most eight voices, so the decoder can never need a ninth
slot. That replaces an empirical zero with a property of the representation.

## Disclosed normalisation: 27,841 clamped note endings

Reported **per split** rather than folded into one figure, because the rate
differs by more than three orders of magnitude between splits.

| split | clamped ends | affected tracks |
|---|---|---|
| train | 20,232 | 184 of 1,384 |
| validation | 7,604 | 62 of 180 |
| test | **5** | 4 of 176 |
| **total** | **27,841** (0.877% of attacks) | **250 of 1,740 (14.4%)** |

| | |
|---|---|
| per-track rate, train | median 1.77%, max 17.65% |
| most affected track | `sbm2-09`, 1,816 of 13,810 attacks (13.1%) |

The splits are **not** interchangeable on this measure: validation carries
7,604 clamps across 62 of 180 tracks while test carries 5 across 4 of 176. A
single corpus-wide percentage would misrepresent all three.

Each is a published note duration terminated at the next key-on on the same
provenance voice — the physical voice-replacement rule, applied at encode.

**This is kept distinct from quantisation error and from decoder-induced
stealing.** A note clamped from 1.0 s to 0.5 s is a correct 500 ms change that
is not quantisation; folding it into the error statistics would void the
bounds. It is reported as its own count, per track.

**It is not evidence that the original SNES performed more than eight
simultaneous voices.** The published tables contain sub-microsecond same-voice
overlaps, because onset and duration are rounded independently, which makes
nine notes nominally concurrent on eight-voice hardware.

The concentration in Super Bomberman 2 shows why a corpus-wide 0.812% cannot
characterise the change on its own: the median affected track sees 1.77% and
the worst sees 17.65%.

## What is NOT established

- **Hardware-performance reconstruction.** Voice reassignment is **median
  48.8% (train), 39.4% (validation), 46.3% (test), maximum 100.0%** — at least
  one track retains no note on its original voice. The codec preserves the
  music, not the voice allocation.
- **Perceptual equivalence.** See the listening section below.
- **Any claim of losslessness or hardware equivalence.** Fitting eight voices
  is not the same as reproducing S-DSP voice behaviour.

The reassignment rate becomes critical if future rendering uses
source-specific samples, envelopes or panning. With a single fixed timbre it is
inaudible; with per-voice timbres at 100% reassignment it would be ruinous.
That is a separate test with a different renderer.

## Two defects the full audit found

Both were invisible to the 60-track sweep and to a passing test suite.

1. **An action-ordering bug.** A note whose duration quantised to zero had its
   end processed before its start, so the end found nothing active and counted
   as unmatched. The existing test passed because it asserted the note's
   duration was zero — true, but reached by the wrong path, the note being
   closed by the final flush as `open`. A monophonic track (`kss-13`, peak
   concurrency 1) reporting 4 unmatched ends is what exposed it. A start now
   always precedes its own end.

2. **Source same-voice overlap mishandled.** Two tracks showed source
   concurrency of **9** on eight-voice hardware, from the sub-microsecond
   rounding artefact above. Fixed by the encode-time clamp.

**The second invalidated an earlier conclusion of this project twice.** It was
claimed that the 250 Hz failures were purely quantisation and a finer grid
would fix them. In fact coarse grids were *hiding* a source defect by
collapsing short notes to zero length and freeing slots early — which is why
1000 Hz passed while 4000 Hz failed. Before the clamp, any passing grid was
passing by luck, and that includes the 1000 Hz pass.

## The listening experiment was uninformative

> A neutral-synthesis listening comparison was conducted between published
> symbolic performances and their codec reconstructions. The resulting
> recordings were not reliably distinguishable. However, a deliberately
> coarsened 25 Hz positive control also produced minimal audible change,
> indicating insufficient sensitivity of the rendering setup to the temporal
> distortions under investigation. Consequently, these listening observations
> were not treated as evidence of perceptual equivalence. Codec fidelity was
> assessed using explicit symbolic reconstruction and hardware-occupancy
> measurements.

Qualification: the similar waveform-difference results and 4% RMS change
support the conclusion that **the tested renderer and stimuli** were
insensitive. They do not establish that every possible listener or playback
system would be.

## Provenance

| | |
|---|---|
| release | `snesmdb-50game-rc1`, git `24171c9692fa19a1a86b64720b8ac94a0f25a41b` |
| codec | `rse.snes_v2.codec`, grouped-event representation at 4000 Hz |
| codec resolution | 4000 Hz, 0.25 ms grid |
| population | all 1,740 music tracks (1,384 train / 180 valid / 176 test), 3,452,267 source events |
| tests | 18 codec edge-case tests passing |
| artifacts | `~/workplace/v2_artifacts/` — resolution sweep, audits and legato verification at 4000 Hz for all three splits, plus the superseded 250/1000 Hz runs retained |

## What Milestone 2 may and may not claim

The two Level 2 failure modes are now eliminated by design rather than left
for a model to discover: clock stagnation is unrepresentable because every
group advances time by a strictly positive amount, and impossible voice
occupancy is unrepresentable because the decoder allocates eight slots and the
encoder clamps same-voice overlap.

**That is an engineering guarantee and must never be reported as learned
musical competence.** A model trained on this representation cannot stall the
clock or exceed eight voices because the representation forbids it, not
because it learned to orchestrate. Whether it produces genuinely musical
compositions is the open research question, and it is exactly the question
Level 2 answered negatively for the previous representation.
