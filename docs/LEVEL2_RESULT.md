# Level 2 result: fails, and the failure is attributable

Level 2 required **Musical preference AND Originality**, registered before
training. It fails.

| registered criterion | result |
|---|---|
| Generation validity ≥99% structurally valid | **FAIL — 23/24 (95.8%)** |
| Originality: no near-exact copying of substantial passages, against a corpus control | **PASS** |
| Musical preference ≥60%, multi-listener study only | **UNMEASURED** — and not worth measuring, see below |

## What was established

| question | answer |
|---|---|
| Can meaningful symbolic information be extracted from SNES music? | Yes |
| Can a Transformer learn statistical relationships in it? | Yes — 23.66% over a strong comparator on a sealed test set, 8/8 games |
| Does the representation survive its own tokenizer? | Yes — perceptually transparent on real music |
| Does the renderer convey music? | Yes — real tracks are recognisable through it |
| Can the model reliably generate valid performances? | **No** — registered criterion failed |
| Does its output sound like coherent music? | **No** — in a 48-excerpt single-listener diagnostic |
| Does the comparator sound better? | **No difference reported** |

## The central finding

**Learning the statistical properties of music is not the same as learning to
compose music.**

The model predicts timing, voice, pitch and duration substantially better than
a strong statistical comparator — 23.66% on held-out games, which is a real
and reproducible result. It has not learned to organise those predictions into
phrases, progressions, recognisable rhythms or development.

Three independent measurements agree with that reading, and none of them is a
listening impression:

- **Grammar.** One excerpt in 24 loses the four-token event cycle outright and
  never recovers.
- **Temporal stagnation.** Two excerpts emit long runs of `TIME_SAME`, so the
  clock never advances: 4,000 events in 8.42 s and 22.12 s, 3,585 and 3,642
  concurrent notes. Both are **grammatically valid**, which is why the
  registered criterion did not catch them.
- **Voice occupancy.** 44% (comparator) to 80% (Transformer) of generated
  notes require voice-stealing clamping, against **0.0%** for real music as
  published and 0.0–2.6% round-tripped, consistently across five games. Real
  music is already hardware-consistent — it was extracted from hardware
  playback — and the generators are nowhere near it.

## Why the failure is attributable, not confounded

A poor listening result could have meant the pipeline was destroying the
music. The control settles it: real SNES-MDB events, through the **identical**
tokenizer and the **identical** renderer, sound recognisably like music, and
the published and round-tripped arms sound identical to each other. The three
possible outcomes were recorded before the control was heard.

So the representation is transparent, the renderer conveys music, and what
remains is the generators.

## Three levels of validity

The experiment's most transferable result is a distinction its own registered
criterion failed to make:

1. **Syntactic validity** — tokens follow the event grammar.
2. **Performance validity** — time advances, density is plausible, voice
   lifetimes are consistent.
3. **Musical quality** — convincing rhythm, phrasing, harmony, development.

The registered criterion measured only (1). Seeds 6 and 19 pass (1) while
failing (2) catastrophically, independently of any perceptual judgement about
(3). **Any future registered criterion needs a clock-progress and density
condition beside the grammar one.**

## Why no 20-listener study

The registered preference criterion is satisfiable only by a 20-listener
study, and that study is not worth running now. Its purpose is to compare two
generators, and the preliminary diagnostic reports that neither produces
recognisable music and that there is no audible difference between them. It
would spend twenty people's time measuring a problem already diagnosed by
three objective measurements.

This is recorded as a decision not to measure, not as a measurement.

## What is explicitly NOT concluded

- **SNES-MDB is not invalidated.** The opposite: its validated measurements
  are what allowed predictive success, grammar failure, hardware-consistency
  failure and perceptual failure to be told apart at all. A dataset that could
  not support that distinction would have left the result uninterpretable.
- **It is not shown that SNES-MDB cannot support convincing generative
  music.** What is shown is narrower: *the four-token event representation and
  a small autoregressive Transformer are insufficient, under the tested
  conditions, to produce convincing SNES-style compositions.* Other
  representations and models are untested.
- **No architecture conclusion follows yet.** No larger model was trained, no
  temperature was searched for a pleasant excerpt, and the locked checkpoint
  was never replaced. Deciding what to build next is a separate question from
  this experiment's result.

The original contribution — extracting reproducible, hardware-grounded
symbolic music from a diverse collection of SNES games — is unaffected, and
Level 1 stands exactly as measured.
