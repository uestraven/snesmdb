# RSE v2 — sampling selection result (2026-11-12)

Outputs of `V2_GENERATION_PROCEDURE.md` §§1–7 with Amendment A1 and Addendum
D1, run once per arm. **No audio was heard and no test data was touched.**

## Selected settings

| arm | temperature | top-p | objective |
|---|---|---|---|
| model (Transformer, step 5,400) | **1.0** | **1.0** | **0.632450** |
| baseline (Kneser-Ney order 1) | **0.8** | **0.95** | **0.696947** |

The two arms landed on different settings. §8 registered that as expected: the
*procedure* is symmetric, not the settings it produces.

## Accounting

Every population reconciles, both arms.

| check | model | baseline |
|---|---|---|
| attempted outcomes | 40 / 40 | 40 / 40 |
| candidates | 10 / 10 | 10 / 10 |
| retained records on disk | 40 / 40 | 40 / 40 |
| eligible candidates (A1) | 10 / 10 | 10 / 10 |
| `invalid` outcomes | **0** | **0** |
| checkpoint step | 5,400 asserted | n/a |
| parameters | 5,646,336 asserted | n/a |

Outcome tallies, all four categories reported:

| | complete | short | budget_exhausted | invalid |
|---|---|---|---|---|
| model | 25 | 14 | 1 | 0 |
| baseline | 3 | 37 | 0 | 0 |

### Independent verification

The pod's own report is not the evidence. All 40 model token streams were
transferred back, **re-parsed on the authoring host**, their statistics
recomputed, and the selection re-derived from scratch:

- 40 / 40 streams decode here.
- Recomputed selection: t=1.0, p=1.0, objective 0.632450 — matching the pod
  to within 1e-12.

Hardware provenance, recorded because sampling draws from the model's float
output: `NVIDIA RTX PRO 4500 Blackwell Server Edition`, torch 2.8.0+cu128,
CUDA 12.8, cuDNN 91002. Reproducible on that hardware and build; **not
guaranteed bitwise on another GPU architecture.** 156.2 s wall clock.

## The duration gap changed the winner

Registered under D1 as reported-not-scored. It is now load-bearing, so it is
stated plainly.

| candidate | objective | in 45–60 s target | median | under 5 s |
|---|---|---|---|---|
| **t=1.0 p=1.0 — selected** | **0.6325** | **1 / 4** | **22.68 s** | **1 / 4** |
| t=0.9 p=1.0 | 0.7208 | **4 / 4** | 45.01 s | 0 / 4 |
| t=0.8 p=1.0 | 0.7766 | 3 / 4 | 45.01 s | 0 / 4 |
| t=0.8 p=0.95 | 1.0505 | 4 / 4 | 45.11 s | 0 / 4 |

§4's objective preferred a setting that mostly does **not** reach the target
over one that reaches it 4 times in 4, by a margin of **0.088** — on an
objective whose density term alone spans 0.09–0.45 across this grid. The
selected candidate's four development outcomes were 31.25 s, 14.12 s,
**3.43 s** and 45.06 s.

§9 forbids changing temperature or top-p after the fact, and D1 registered
reporting rather than amending. The selection therefore **stands as the
output of the registered procedure**, and the limitation is disclosed rather
than engineered away: under these settings a 24-excerpt evaluation batch
should be expected to reach the 45–60 s target in roughly one case in four.

**A "45–60 second composition" is not what this setting delivers.** Any claim
to that effect would be unsupported by this run.

## "Complete" means stopped, not concluded

All 25 `complete` model durations cluster at 45.0x s — the soft stop. **Not
one excerpt ended because the model sampled `EOS` at a musically plausible
point.** The 14 `short` outcomes are the ones the model chose to end, at 2.5
to 41 s.

The model has not learned to close a piece. 25 of 40 excerpts needed a
terminal release to close their final group grammatically; those releases are
an intervention by the harness and are counted as such.

## Separate the guarantee from the competence

**0 invalid in 40, and 0 in 80 across both arms, is the grammar-constrained
decoder working. It is not evidence that either model learned structure.**
Level 2 failed structural validity 23 of 24 times with no such decoder; that
contrast measures the representation and the mask, not musical competence.

The diagnostic that does bear on competence is the illegal-mass ledger — the
probability each model placed on illegal tokens *before* masking:

| arm | mean illegal mass | range |
|---|---|---|
| model | ≈ 0.12 | 0.039 – 0.192 |
| baseline | ≈ 0.17 | 0.087 – 0.257 |

The mask is doing substantial work in both arms. The Transformer is better
than the n-gram at staying inside the grammar unaided, and neither is close
to doing it unaided.

## Texture is thin across the whole grid

Mean simultaneity by candidate runs **1.23 to 1.55** against a corpus
reference of **2.30**. No candidate comes close, so this is a property of the
model rather than of a sampling setting. It echoes the lead-voice thinning
found in the NES work.

Density, by contrast, is reachable: the selected candidate's 17.46 attacks/s
sits against a reference of 17.88.

## Two harness fixes determined this result

Both were made earlier the same day, before any development excerpt was
scored, and are recorded in `V2_GENERATION_HARNESS_CORRECTION.md`.

The selected candidate's seed 1000 is the **only** `budget_exhausted` outcome
in the whole arm. Under the pre-fix code that stream carried no `EOS`, would
have failed `parse`, and would have made the selected candidate **ineligible
under A1** — handing the selection to t=0.9 / p=1.0 instead. Its seed 1003
needed a terminal release for the same reason.

So both fixes were necessary for the winning candidate to be eligible at all.
A harness defect would not have produced a visible error here; it would have
produced a different registered result.

## Artifacts

| | |
|---|---|
| model arm | `~/workplace/v2_artifacts/selection_model/` (42 files) |
| baseline arm | `~/workplace/v2_artifacts/selection_baseline_final/` |
| superseded baseline runs | `selection_baseline/`, `selection_baseline_v2/`, `selection_baseline_v3/` — harness validation, **not** selection results |
| bundle | `tmp/g3select.tar.gz`, sha256 `ed9c8709…`, 31 files |
| report sha256 | `f4d63aca83f614584590384c4567b25f834286a18621bd44b5f27204c93f71af` |

## Open, not resolved here

1. **The paired listening study cannot be administered as designed.** The
   baseline arm's selected setting yields a median of 27.99 s with one
   development excerpt at 0.60 s; the model arm's yields 22.68 s with one at
   3.43 s. Pairing excerpts of such unequal length is not a blind comparison
   of musical quality. §8 and `V2_MILESTONE3_PROTOCOL.md` need an answer
   before the 24-pair set is generated.
2. **Whether §4 should be re-registered with a duration term.** Doing so
   would use development-seed information only — seeds 1000–1003 are disjoint
   from the evaluation seeds 0–23, which have never been run, which is what a
   development set is for. It would nonetheless be a post-hoc amendment
   informed by both arms' outcomes and must be disclosed as such if taken.
