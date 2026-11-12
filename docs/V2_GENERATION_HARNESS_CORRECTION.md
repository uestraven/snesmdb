# RSE v2 — generation harness correction (2026-11-12)

**This is a defect fix in the harness, not an amendment to the frozen
procedure.** No threshold, weight, grid value, seed, metric, tie-break or
outcome category in `V2_GENERATION_PROCEDURE.md` changes. What changes is that
the implementation now produces a *parseable* stream at the stopping boundary
§5 already specified.

Found before any development excerpt was scored, in the first end-to-end run
of the baseline arm.

## The defect

A delta token is the **prefix** of the group it belongs to:

    BOS [delta_0 actions_0] [delta_1 actions_1] ... [delta_n actions_n] EOS

So a group boundary immediately after a delta has an **open group with no
actions**, and `EOS` closes an open group — a group with nothing in it has
nothing to close. `legal()` correctly refuses `EOS` there.

`generate()` nevertheless appended `vocab.EOS` unconditionally when the clock
reached the soft stop or hard cap:

```python
if state.at_group_boundary and seconds >= hard_cap_sec:
    emitted.append(vocab.EOS)              # illegal at this boundary
    outcome, reason = "complete", f"hard cap at {seconds:.2f}s"
```

Consequence: **every clock-terminated excerpt was undecodable.** `parse`
raised `GrammarError: empty group before token N`. Only excerpts where the
*model* sampled `EOS` — the `short` outcomes — survived.

### How far it reached

| population | retained outcomes unparseable |
|---|---|
| uniform-distribution model, seeds 0–11 | **5 / 12** |
| KN order-1 baseline, first partial grid run | every `complete` outcome observed |

Under Amendment A1 an undecodable outcome makes its candidate **ineligible**.
So the defect would have disqualified candidates for the harness's reason
rather than the model's — Level 2's error, repeated. In Level 2 it was window
phase alignment; here it was stream termination. Both were measurement
failures presented as grammar failures.

### Why twelve generator tests passed

None of them took a long excerpt through `parse()`. They checked the mask, the
rollover snapshot, the outcome categories, the illegal-mass ledger and the
sampling order — every component except the end-to-end property that the
thing it produces can be read back.

### The same defect in a second place

`budget_exhausted` broke out of the loop without terminating at all, so its
stream had **no `EOS`** and `parse` rejected it with `IncompleteStream`.

Amendment A1 states explicitly:

> `short` and `budget_exhausted` remain **decodable outcomes** governed by §5
> and §6. They are not reclassified as invalid.

That claim was false in the implementation. Every budget-exhausted outcome
would have made its candidate ineligible — again for the harness's reason.
Both branches now terminate through the same `_terminate()`.

## The fix

`generate._terminate()` closes the group grammatically, in two cases, and
invents no musical material the model did not produce:

1. **Notes are sounding.** Each active handle **releases** — the ending a
   composition actually has — which gives the terminal group its actions,
   after which `EOS` is legal. Counted in `Excerpt.terminal_releases`, so the
   intervention is visible rather than folded into the note content.
2. **Nothing is sounding, or the stop fell mid-action.** There is no action
   available, so the **incomplete terminal group is dropped**: the emitted
   stream is truncated back to before the delta that opened it and `EOS`
   follows the previous group's actions. A delta closes the *preceding*
   group, so that group keeps everything it had — nothing complete is lost.
   The clock reverts with it, and the reason string says so.

Every token still passes through the same `legal()` mask; the terminal
releases are drawn from it, not written around it.

One case is reported rather than repaired: a stop inside the **very first
group**, where there is no earlier group to fall back on and any termination
would have to invent an action. The outcome is retained and recorded as not
decodable, with that reason. It is not relabelled `invalid`, and it is not
patched.

The releases push a budget-exhausted stream a few tokens past 6,000. That is
disclosed in the termination reason rather than hidden.

## The test that was missing

`tests/test_snes_v2_generate_parses.py` states the property once:

> For any model, any seed and any sampling setting, a retained outcome that is
> not `invalid` decodes, and its decoded notes have defined statistics.

It is driven by a **uniform-distribution model** — no musical knowledge at
all, so the mask is the only thing shaping the output and a grammar defect in
the harness cannot be hidden by a model that happens to sample `EOS` early.
Further tests pin the specific shapes: the stream ends `... action(s) EOS` and
never `... DELTA EOS`; a clock-terminated excerpt decodes and carries its
duration; terminal releases appear in the record; and a budget-exhausted
excerpt decodes, across three reduced budgets and the four development seeds.

The budget tests override the budget rather than the procedure, so the frozen
6,000 is untouched. One of them exists only to prove the branch under test is
actually reached — a decodability test over outcomes that never include
`budget_exhausted` would pass while testing nothing, which is the shape of
the SNES V1 test that never ran.

Verified to fail against the pre-fix behaviour: 5 of 12 unparseable.

## A second, separate finding: hard-cap overshoot

§5 stops "at the next group boundary", and the clock only advances when a
delta is sampled, so **one sampled delta can jump past the 60 s cap**. The
first baseline run produced a `complete` excerpt at **85.23 s**; the
uniform-distribution model reached 3,030.91 s.

This is **conformant** with §5 as written. It is not corrected here, because
masking out an overshooting delta would change the registered grammar, and
changing the cap would change a registered threshold. Instead it is made
**visible**: `Excerpt.exceeded_hard_cap` is set whenever the terminating
boundary was already past 60 s, so such an excerpt can never be read as an
in-target 45–60 s result.

Whether §5 should be amended to mask deltas that would overshoot is a
procedure decision, recorded here as open rather than taken silently.

## What did not change

- The mask, `GenerationState`, `build_windows`, the snapshot machinery.
- The candidate grid, the development and evaluation seeds, the objective,
  the tie-break, the soft stop, the hard cap, the token budget.
- The four outcome categories, and Amendment A1's eligibility rule.
- The locked checkpoint, step 5,400.

## Provenance

The partial first run that exposed the defect is retained at
`~/workplace/v2_artifacts/selection_baseline/` and is **not** a selection
result: it was stopped mid-grid and its `complete` outcomes carry the defect.
The superseding run is `selection_baseline_v2/`.
