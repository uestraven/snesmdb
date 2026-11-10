# CPU baseline results — the Level 1 comparator

Registered under `docs/EXPERIMENT_PREREGISTRATION.md`. Selected on the
**validation split only**; the eight-game test split is untouched. No model has
been trained.

Population: `snesmdb-50game-rc1`, `track_class == "music"`, train 1,384 tracks
(2,490,105 events) and valid 180 tracks (370,655 events). Tokenizer
`snes-lm-repr/1.0.0-log96-cap2s`, vocabulary 240. All baselines predict the
same targets under the same masking, in **bits/token** — the units the
Transformer optimises.

## Result

**Strongest validated baseline: `slot_ngram_order10_d64` at 3.3839
bits/token.** 36 configurations evaluated on validation.

**Level 1 target: 3.2147 bits/token** (a 5% relative reduction).

| baseline | bits/token | gain on the one above |
|---|---|---|
| unigram, flat | 6.2025 | — |
| **unigram, stride-aware** (the floor) | **4.2025** | **2.000** |
| interval reversal, λ=0.1 | 4.1622 | 0.040 |
| copy previous event, λ=0.1 | 4.0200 | 0.182 |
| copy at lag 16, λ=0.25 | 3.9589 | 0.244 |
| **slot n-gram, order 10, discount 64** | **3.3839** | **0.819** |

## What the decomposition says

**2.000 bits is grammar, not music.** Flat 6.2025 → stride-aware 4.2025, a gap
of exactly log2(4) = log2(STRIDE): the stride-aware unigram confines its mass
to a quarter of the vocabulary. Any model gets this free from the token cycle,
which is why the floor is the stride-aware unigram. Scoring a model against the
flat unigram would hand it two bits it did not earn.

**Repetition is worth about 0.82 bits, and the simple heuristics capture a
quarter of it.** Interval reversal adds 0.040, copying the previous event
0.182, copying at a 16-token lag 0.244 — against the n-gram's 0.819.

**The strongest baseline is a repetition model, deliberately.** A slot n-gram
at order 10 conditions on the ten previous tokens *of the same slot*, reaching
back ten events; with heavy interpolation that is close to a passage lookup. It
keeps improving with order and plateaus there — order 6 gives 3.4044, order 8
3.3871, order 10 3.3839, the last step worth 0.09%. That it wins by this much
says the corpus's predictability is substantially **repetition**, which is
exactly the discrimination the experiment needs: the Transformer has to beat
repetition exploitation by 5%, not beat token frequency.

## Two findings about the representation

**A naive n-gram over the raw token stream is worse than useless.** Every
order scored *below* its own backoff, monotonically — 4.29 at order 1 rising to
6.11 at order 4 against the floor's 4.23. On a fixed-stride TIME VOICE PITCH
DUR serialisation the order-1 context for a pitch is the voice token beside it,
so the model was being asked to predict a pitch from a voice id. The 27-game
interval n-gram beat its frequency baseline because it ran over a pure interval
sequence, where consecutive elements are musically adjacent.

Conditioning **within slot** recovers the property. This also bears on the
Transformer: the informative context sits four positions back, so it must learn
a constant-offset attention pattern. The fixed stride at least makes that
offset constant rather than variable.

**Sparsity inverted the result at small scale.** On 300 training tracks the
slot n-gram beat the floor by 1.2% and *higher orders hurt*; on the full 1,384
it beats it by 19.5% and higher orders help all the way to order 10. A
baseline tuned on a subset would have been far too weak, and would have set an
artificially easy Level 1 bar.

## Two bugs found, both of which would have flattered the model

Both surfaced from questions with only one possible answer, not from reading
the code.

**A rotated slot convention.** `fit` indexed slots over a BOS-excluded body
while `score` indexed a BOS-included one, so every slot was off by one. The
stride-aware unigram predicted the wrong token group at every position and
scored **18.0 bits/token against the flat unigram's 6.2** — impossible for a
model with strictly more information.

**An interpolation that could collapse to zero.** The n-gram trusted a
frequently-seen context in proportion to its count alone, so a context that
assigned the target zero mass dragged the estimate onto 9% of the backoff. The
order-3 n-gram scored **6.274 against its own backoff's 4.209** — impossible
for an interpolated model. Replaced with Witten-Bell, where the weight is
`total / (total + discount × distinct)` and the lower order always retains
mass.

Both checks are now tests: a stride-aware unigram may not lose to a flat one,
and an interpolated n-gram may not lose to its own backoff on the data it was
fitted to.

## Reproducing

```sh
# in retro-synthesis-engine
python -m pytest tests/test_snes_lm_representation.py tests/test_snes_lm_baselines.py
```

Per-track and per-game figures are retained in
`docs/baseline_lm_validation.json` so uncertainty can be bootstrapped over
tracks and all eight test games reported descriptively at final evaluation.
