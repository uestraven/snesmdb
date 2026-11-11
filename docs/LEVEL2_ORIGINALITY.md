# Originality: memorization versus novelty

The registered criterion is control-relative by design — "no identified
near-exact copying of substantial training passages, judged by review of
flagged matches against a **corpus control**" — because this project has
already been burned once by a similarity metric without a control. On the NES
side, exact-bar restatement looked damning until the corpus was measured and
found barely to repeat itself either.

## Method

Tokens are ids below 256, so an n-token window packs into `bytes` and either
appears verbatim in a training track or does not. No similarity heuristic and
no threshold: exact matching, measured identically on

- the Transformer's 23 structurally valid excerpts,
- the SlotNGram comparator's 24 excerpts,
- **the control: 176 held-out real tracks** from the test split, real SNES
  music the model never saw, through the identical pipeline.

Matches never span track boundaries — n-grams are collected per track. The
training population is 1,384 music tracks, 9,960,420 tokens.

The comparator was included on the expectation that an order-10 model would
copy by construction and so would set the scale for "definitely copying".
**That expectation was wrong** and the reason is instructive: `SlotNGram`
conditions on same-slot history at −4/−8/−12, so its order-10 context spans 40
raw tokens non-contiguously, and Witten-Bell interpolation lets it emit
continuations never observed. It copies contiguous runs *less* than real music
does.

## Result: neither generator memorizes

Coverage is the fraction of an excerpt's n-token windows found verbatim in
training; median across excerpts, with the per-excerpt maximum beside it.

| window | Transformer | SlotNGram | held-out real (control) |
|---|---|---|---|
| 4 tokens (1 event) | 79.10% / max 99.15% | 64.51% / 69.18% | 72.72% / max 95.26% |
| 8 tokens (2 events) | 5.00% / max 56.17% | 1.38% / 2.87% | 1.44% / max 32.91% |
| 16 tokens (4 events) | 0.00% / max 3.09% | 0.00% / 0.00% | 0.00% / max 1.97% |
| 18 tokens | 0.00% / max 1.77% | 0.00% / 0.00% | 0.00% / max 0.05% |
| 20 tokens (5 events) | 0.00% / max 0.67% | 0.00% / 0.00% | **0** |
| 22 tokens | **0** | **0** | **0** |

Longest verbatim span by population: **Transformer 20 tokens (5 events),
control 18 tokens, SlotNGram nothing at 16 or above.** Nothing anywhere
matches at 22 tokens.

> A coarser first ladder (4, 8, 16, 24, …) reported the Transformer's longest
> span as 4 events, because it stepped straight from 16 to 24 and could not
> resolve the matches at 20. The figure above supersedes it, and the control
> was re-measured at the same resolution — comparing a 5-event model match
> against a control sampled only at 4 and 6 events would be exactly the
> aggregation mismatch this document warns about elsewhere.

Reading it against the control, which is the registered basis:

- The Transformer's longest span exceeds the control's by 2 tokens — half an
  event. Both die out at the same scale.
- Single-event agreement is high for everything, including real held-out music
  at 72.72%. That is a property of the representation, not of any generator: one
  event is a (time, voice, pitch, duration) tuple and the corpus covers most
  combinations. It carries no information about copying.
- The Transformer does reuse 2-event fragments more than the control — median
  5.00% against 1.44%, with one excerpt at 56.17%. This is the only
  substantially elevated figure, and it is at a scale of two notes.

## Review of the flagged matches

The criterion requires the longest matches be reviewed, not just counted.
Both matches at 20 tokens occur in **seed 10** and trace to `ff6-313`:

```
tokens: 100 205 238 3  101 205 238 3  102 205 238 3  103 205 238 3  104 205 238 3
groups: voi pit dur tim voi pit dur tim voi pit dur tim voi pit dur tim voi pit dur tim
```

The copied material is a **mechanically repeating figure**: the same pitch
token (205 = `PITCH_NONE`), the same duration token, and the same time token
repeated five times, with only the voice index stepping 100 → 104. It is an
unpitched roll walking up the voices.

Three observations make this the weakest possible form of copying:

1. **It is entirely unpitched.** Seed 10 is 116/117 `PITCH_NONE`, so what
   recurred is percussion timing, not melodic or harmonic material.
2. **It is not event-aligned.** The two matches sit at phases 1 and 2, so they
   straddle event boundaries — token-level coincidences rather than reproduced
   musical events.
3. **It is trivially generable.** A constant-duration, constant-interval
   figure cycling through voices is the kind of pattern any corpus containing a
   drum roll will hold, and it appears in only 1–2 training tracks.

**Verdict: the Originality criterion PASSES.** The longest verbatim spans are
five events of a constant unpitched roll, against a control whose longest is
four to five events. There is no near-exact copying of a substantial musical
passage.

This does not rescue Level 2. Level 2 requires **Musical preference AND
Originality**, the structural-validity criterion has already failed at 23/24,
and musical preference remains unmeasured and is satisfiable only by the
multi-listener study.

## A distributional finding the other metrics missed

Rendering exposed something none of the overlap, density or concurrency
measurements could see, because all of them count events regardless of pitch:
several Transformer excerpts are almost entirely **unpitched**. Seed 23 is
323/323 `PITCH_NONE`, seed 20 is 706/709, seed 10 is 116/117.

Control first, and it changes the conclusion:

| population | pitched share, median | min | max | excerpts under 5% pitched |
|---|---|---|---|---|
| Transformer | 82.08% | 0.00% | 100.00% | 4 / 23 (17.4%) |
| SlotNGram | 81.28% | 75.84% | 85.93% | 0 / 24 |
| real, tokenized (control) | 80.06% | 0.00% | 100.00% | 2 / 60 (3.3%) |

An entirely unpitched track is **in distribution** — the real corpus contains
them, so generating one is not a pathology. The Transformer produces them
about 5× more often than the control, which at n = 23 is not a significant
difference. All three medians agree closely (82.1 / 81.3 / 80.1%), matching
the corpus-wide pitched share of 77.5–85.5% recorded in the preregistration.

The comparator is the outlier here. It spans only 75.84–85.93% where real
music spans 0–100%, and it never produces an all-percussion track. On this
axis the Transformer's spread matches real music and the comparator's does
not — a point the registered hardware-consistency metrics could not have
surfaced.
