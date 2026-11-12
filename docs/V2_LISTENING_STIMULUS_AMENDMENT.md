# RSE v2 — Addendum D2: reporting §4, and listening stimulus construction

**Registered 2026-11-12, before the primary evaluation batch (seeds 0–23) was
generated.** Those seeds have never been run in either arm, so this is
prospective relative to every excerpt it governs. It is *not* prospective
relative to the development seeds 1000–1003, whose outcomes are what prompted
it; that is disclosed, not glossed.

---

## Part 1 — §4 stands; the gated counterfactual is published beside it

### The registered selection, unchanged

| arm | temperature | top-p | objective |
|---|---|---|---|
| model | **1.0** | **1.0** | 0.632450 |
| baseline | **0.8** | **0.95** | 0.696947 |

No registered quantity changes. §4's objective, §5's stopping rules, §9's
prohibition on changing temperature or top-p, and Amendment A1's eligibility
rule all stand exactly as frozen.

### The counterfactual, labelled as such

§4's objective scored the two arms at **0.632** and **0.697** — nearly equal —
and chose a 1-of-4-in-target candidate in both. A duration-aware rule,
applied to the **same 80 retained outcomes with no new generation**, separates
them completely:

| rule | model arm | baseline arm |
|---|---|---|
| registered §4 | t=1.0 p=1.0, obj 0.632, **1/4** in target | t=0.8 p=0.95, obj 0.697, **1/4** in target |
| all 4 seeds in the 45–60 s target | t=0.9 p=1.0, obj 0.721, **4/4** | **0 eligible → unsuccessful** |
| all 4 seeds ≥ 20 s | t=0.9 p=1.0, obj 0.721, **4/4** | **0 eligible → unsuccessful** |

The Transformer can be tuned to reach the target in 4 seeds of 4. The
Kneser-Ney baseline cannot reach even 20 s in all four seeds of **any**
candidate in the grid. That asymmetry is arguably the clearest
learned-competence signal in the experiment, and the frozen objective
conceals it by scoring the arms within 0.065 of each other.

**This is a post-hoc counterfactual computed after seeing both arms. It is
not a selection, it does not supersede §4, and no result is reported from
it other than the asymmetry above.** It is published so that a reader is not
left with the impression that the two arms performed comparably.

---

## Part 2 — Listening stimuli: a common 20.0 second window

### Why the paired design could not run as generated

| | model arm, selected setting | baseline arm, selected setting |
|---|---|---|
| median duration | 22.68 s | 27.99 s |
| shortest development excerpt | 3.43 s | 0.60 s |
| in the 45–60 s target | 1 / 4 | 1 / 4 |

Pairing a 0.60 s excerpt against a 45 s one asks a listener to judge length,
not music. The preference estimate would be uninterpretable as musical
quality, and no amount of blinding fixes it.

### The rule

1. **Every excerpt is rendered to the same 20.0 second window**, measured
   from its start, identically in both arms. Length ceases to be a cue.
2. **A pair is analysable only if both arms' excerpts for that seed reach
   20.0 s.** Nothing is padded: silence appended to a 3 s excerpt is invented
   material and would itself be audible.
3. **Excluded pairs are retained and counted** with the seed and both
   durations. The exclusion count is reported beside the preference figure,
   never folded into it.
4. The truncation is applied by the **same renderer, with identical settings,
   to both arms** — the rendering control from Level 2 applies unchanged.

### Why 20.0 seconds

Pair inclusion over the development seeds is **flat at 2 of 4 for every
window from 5 s to 20 s**, and falls to 1 of 4 above 20 s. The loss is caused
entirely by the two near-zero excerpts, which no window rescues. 20.0 s is
therefore the **longest window that costs nothing in inclusion**, and gives
the most musical material per stimulus.

### What this costs the claim

The study now measures **musical quality over a 20 second window**, not
whether the system composes a 45–60 second piece. That is a real reduction in
scope from the Composition Demonstrator's stated target and must be stated
wherever the preference result is reported. The 45–60 second question is
answered separately, and negatively, by the duration figures in
`V2_SAMPLING_SELECTION_RESULT.md`.

### Power is determined before listeners are recruited

The design assumed 24 pairs. Development suggests roughly half may be
excluded — but that estimate comes from **4 pairs**, whose 95% interval runs
from about 7% to 93%, so it is close to useless as a forecast. The actual
count comes from the evaluation batch.

`preference.MAX_MISSING_SHARE = 0.50` does **not** cover this: it excludes a
*listener* who skips more than half their assignment, and says nothing about
pairs dropped from the stimulus set before listening begins.

So, prospectively: once the evaluation batch exists and the analysable pairs
are counted, the registered clustered bootstrap is run on **simulated
judgements** at that pair count to obtain the achievable CI width and the
minimum detectable effect against the registered 0.60 practical threshold.
That figure is recorded **before any listener is recruited**. If the design
cannot resolve 0.60, the study is declared underpowered and not administered,
rather than run and reported with an interval too wide to support either
conclusion.

No arbitrary minimum pair count is registered here, because inventing one
without a power calculation would be a guess dressed as a threshold.

---

## What does not change

- §4's objective, weights and tie-break.
- §5's soft stop, hard cap, token budget and boundary convention.
- §9's prohibition on changing temperature, top-p, seeds, or regenerating.
- Amendment A1's eligibility rule; Addendum D1's report-not-score decision.
- The evaluation seeds **0–23**, still unrun in both arms.
- The locked checkpoint, step 5,400.
