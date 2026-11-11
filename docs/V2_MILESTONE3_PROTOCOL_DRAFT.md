# RSE v2 Milestone 3 protocol — DRAFT, NOT FROZEN

**Status: draft for review. Not registered. No training authorized.**

Decisions 1–3 are frozen and not reopened: the 4000 Hz grouped-event codec,
the C2 k=512 exact delta vocabulary, and the G3 token grammar.

The research question is unchanged: **can RSE v2 generate coherent music, or
only syntactically valid symbolic performances?** Level 2 answered that
negatively for the previous representation while passing every structural
check, so this protocol is built so the same confusion cannot recur.

## 1. Training

| | |
|---|---|
| architecture | decoder-only, d_model 256, 6 layers, 8 heads, context 1024, weight-tied |
| parameters | **5,646,336** (vocabulary 2,544 = 2,543 G3 tokens + PAD) |
| optimizer | AdamW, lr 1e-3, weight decay 0.01, PyTorch default betas, grad clip 1.0 |
| schedule | linear warmup 200 steps, then cosine **to the budget's end** |
| precision | bf16 autocast, fp32 loss |
| batch | 8 — the measured throughput knee (790,741 scored targets/s; batch 16 is *lower*) |
| seed | 0, single run |
| data | 1,384 train tracks, 9,589 windows, **8,906,692 scored targets** |

### The exposure budget is justified, not inherited

**50,000 steps is explicitly rejected.** At 1,199 steps/epoch that is 41.7
epochs, and Level 1's selected checkpoint landed at **3.8 epochs** (step 5,000
of a 50,000-step cosine, which therefore never completed — the LR was still
near peak at selection). Carrying that number over would be inheritance, not
reasoning.

| | |
|---|---|
| budget | **20 epochs = 23,980 steps** |
| rationale | 5.3× the epoch count at which Level 1 selected, so the schedule can complete and early stopping can bind before the budget does |
| cosine | completes at 23,980 steps, so the LR actually anneals |
| exposure | 20 × 8,906,692 = **178,133,840 scored targets** |
| wall clock | ~4.0 min at 12.1 s/epoch |
| evaluation | every 600 steps (~0.5 epoch), 0.52 s per pass |
| early stop | patience 8 evaluations on validation bits/scored-target |

Budget is stated in **epochs and scored targets**, with optimizer updates
recorded separately. Equal steps are not equal exposure, and because
tokenizations differ, equal token exposure is not equal musical information
either — so no Level 1 comparison is claimed on this axis.

### One run, not many

**Cheap compute does not authorize repeated runs until one sounds
convincing.** The primary experiment is one fixed model, seed, schedule and
generation protocol. Any further run is exploratory, labelled as such, and
cannot supply the primary result. A 4-minute training run makes this rule
*more* necessary, not less: the temptation to sample until something pleases
is exactly proportional to how cheap sampling is.

## 2. Model selection

Validation only — 180 tracks, 1,446 windows, 1,356,836 scored targets. The
criterion is validation bits per **scored target**, where scored targets
exclude padding and snapshot positions (a snapshot is given conditioning, not
model output).

The test split (176 tracks) stays sealed until selection is final. No
architecture, hyperparameter, sampling or threshold decision may follow test
inspection.

## 3. Baseline

A matched autoregressive baseline on the **identical** G3 serialization,
decoder and renderer, so the only difference is the model.

- **Form**: an interpolated n-gram over G3 tokens with Witten-Bell smoothing,
  order selected on validation only.
- **Not** the Level 2 `SlotNGram`: that exploited a fixed stride-4 slot cycle
  which G3 does not have, so it has no analogue here.
- **The grammar mask applies to both arms identically.** Level 2's comparator
  looked structurally perfect partly because it was handed the slot; here
  neither arm may be advantaged by the harness.

A baseline that matches or beats the Transformer on listening is a result, not
a failure of the protocol.

## 4. Generation

| | |
|---|---|
| excerpts | 24 per arm |
| length | 45–60 s |
| seeds | fixed, disjoint from any development seed, recorded before generation |
| sampling | fixed parameters chosen by the registered listening-free distributional procedure on **train/dev only** |
| rollover | required — see below |
| selection | **none**. Excerpts are taken as generated. No cherry-picking, no regeneration of an unflattering excerpt. |

### Rollover is intrinsic, and bounds what can be claimed

45–60 s is roughly **2,700–3,700 tokens** at 60.9 tok/s, against a 1,024-token
context giving ~15.3 s. So every excerpt requires **3–4 context rollovers**,
each carrying forward only the active-note snapshot.

**A snapshot carries current note state, not earlier musical material.** A
motif that leaves the window is gone. Therefore:

- **Primary endpoint**: audible musical coherence across the whole excerpt.
- **Secondary, exploratory**: long-range motif recurrence. A statistically
  detected recurrence is **not** evidence that the model remembered an earlier
  motif, and reliable intentional reprise after 30 s would be testing a
  capability this architecture was never given.

If long-range thematic recall proves necessary, that argues for a later
hierarchical model or explicit memory. It must not be smuggled in here.

## 5. Listening

| element | requirement |
|---|---|
| blinding | neutral randomised filenames, identity key sealed until all responses are recorded |
| positive controls | genuine SNES-MDB excerpts, rendered identically |
| negative controls | a deliberately degraded arm with a *known* defect |
| identical-source control | one pair that is the same render twice |
| **sensitivity gate** | the setup must demonstrably distinguish a known musical degradation **before** any null result is accepted |

### The sensitivity gate is non-negotiable

Level 2's listening test produced two nulls that turned out to carry no
information: a 25 Hz positive control changed sounding RMS by 4% and the
waveform difference not at all, so "indistinguishable" was the expected
outcome regardless of the codec. **A null from an unvalidated setup is not
evidence.**

So the degradation used as the negative control must be chosen and *verified
audible* first. Candidates, to be settled before registration: pitch
randomisation within a phrase, inter-onset shuffling, or removal of the
accompaniment voices. The 25 Hz grid is explicitly unsuitable — it is already
known to be inaudible through this renderer.

If the gate fails, the listening result is reported as **inconclusive** and no
musical claim is made in either direction.

## 6. Registered success criteria

To be fixed before any candidate audio is heard. Thresholds below are
proposals for review.

| criterion | proposed threshold | level |
|---|---|---|
| Coherence | ≥60% of excerpts judged "coherent music" by a majority of listeners | primary |
| Preference | ≥60% preference over the matched baseline | primary |
| Positive-control separation | real excerpts judged coherent at ≥90% | gate |
| Negative-control separation | degraded arm judged coherent at ≤20% | gate |
| Development | exploratory, no threshold | secondary |

**Inconclusive rules, registered in advance:**

- If either gate fails, the outcome is **inconclusive**, not negative.
- With a single listener the result is **diagnostic only** and cannot satisfy
  Coherence or Preference, exactly as in Level 2.
- A tie or absence of perceived difference between arms is reported as
  observed; it is **not** a measured equivalence.
- Failing Coherence while passing every structural check is a **valid,
  reportable negative result** — that was Level 2's outcome and it was
  informative.

## 7. The engineering-versus-learning ledger

Reported **separately** and never counted toward musical quality:

| guaranteed by construction | measured intervention | learned |
|---|---|---|
| grammatical framing | grammar-mask exclusions, and the probability mass they removed | phrase structure |
| strictly positive clock progress | forced group closures | harmonic organisation |
| ≤8 occupied voices | voice displacement | motif recurrence |
| complete delta escapes | truncated completions | development |
| | invalid handle attempts | |

Two rules:

1. **A decoder guarantee is never evidence of model competence.** The model
   cannot stall the clock or exceed eight voices because the representation
   forbids it, not because it learned not to.
2. **Pre-mask probability mass is the diagnostic that matters.** A model whose
   output is valid mainly because masking redirected it has not demonstrated
   independent competence. An excerpt that is valid but required extensive
   intervention is a poor result, not a good one.

## Open items before freezing

1. **The negative-control degradation** must be chosen and verified audible.
2. **Listener count.** 20 listeners satisfies the primary criteria; a single
   listener is diagnostic only. If 20 are unavailable, the primary criteria
   remain unmet and that is the registered outcome.
3. **Thresholds** in §6 are proposals.
4. **The renderer.** The Level 2 neutral renderer is first-party and safe but
   plain, and its insensitivity to fine timing is now documented. It may need
   improvement to pass the sensitivity gate — and any change must be made
   before registration, never after hearing candidates.
