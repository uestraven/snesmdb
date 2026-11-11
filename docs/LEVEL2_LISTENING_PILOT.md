# Exploratory listening pilot, and the genuine-music control

**Status: exploratory, single listener, n = 1.** Registered as such in advance.
This pilot **cannot** satisfy the Level 2 musical-preference criterion, which
is satisfiable only by the 20-listener study. It is recorded because a
diagnostic observation is evidence about what to investigate next, not because
it decides a registered outcome.

## What was listened to

All 48 excerpts of the registered batch — 24 Transformer, 24 SlotNGram —
rendered identically: one fixed timbre, fixed 1/8 per-voice gain, no
per-excerpt normalisation, eight-voice stealing applied, unpitched events
sounding as percussion. Nothing was excluded, repaired or substituted. The two
runaway excerpts (seeds 6 and 19) and the valid prefix of the single
grammar-failure excerpt (seed 3) were included and labelled.

## Assessment, recorded without softening

The listener is the project owner, who listened to all 48 files and reports:

> every single one sounds incoherent, as if a child was banging on a keyboard

No excerpt in either arm was reported as musically coherent, and **no
difference in favour of either generator was reported**. Taken at face value
this is substantial negative evidence about the musical quality of both
generators under the tested conditions.

**Attribution matters here.** This is a human listening report. The assistant
that ran the experiment has no audio perception, heard none of the 48 files,
and contributed no perceptual judgement to this record. An earlier draft of
this conclusion risked being attributed to a listener who does not exist.

### What it does and does not establish

- It **does** indicate that neither generator produced recognisable music in
  a 48-excerpt diagnostic.
- It **does not** establish the Level 2 preference verdict, which was
  registered as requiring 20 listeners and remains unmeasured.
- It **does not** by itself attribute the failure to the generators. That is
  what the control below is for.

## The genuine-music control

Rendering real SNES-MDB tracks through the **identical** code path separates
two very different explanations:

1. real music sounds like music here and generated music does not — the
   representation and renderer preserve enough musical information, and the
   generators are failing to organise it;
2. real music also sounds incoherent — the pipeline is destroying musical
   information, and the listening failure cannot be attributed to the
   generators at all.

This control was motivated partly by two pipeline defects already found:
unpitched events were initially rendered as silence, and the generated output
needs very heavy voice stealing.

Five tracks from the **test** split (never trained on), each rendered twice:

- `real_published` — the release's own events, full symbolic fidelity. The
  upper bound of what this synthesiser can convey.
- `real_roundtrip` — the same events through encode then decode, carrying the
  tokenizer's quantisation: 96 log-spaced time buckets, 32 duration quantiles,
  semitone-rounded pitch. **This is the fair comparison for the generators**,
  which can only emit round-tripped material.

A gap between those two arms measures the representation. A gap between
`real_roundtrip` and the generators measures the generators.

### Objective result, before anyone listens

| track | events | voice stealing, published | voice stealing, round-tripped | pitched |
|---|---|---|---|---|
| actr-01 | 466 | 0.0% | 2.6% | 98.9% |
| actr-02 | 72 | 0.0% | 30.1% | 100.0% |
| actr-03 | 110 | 0.0% | 6.4% | 100.0% |
| actr-04 | 894 | 0.0% | 0.8% | 94.0% |
| actr-05 | 721 | 1.7% | 1.1% | 97.4% |

Against the generators: **SlotNGram ~44% and Transformer ~80%** of notes need
clamping, with individual Transformer excerpts from 47% to 98%.

So on a measurement that needs no listener, real music and generated output
are not close. Real music as published is essentially hardware-consistent
already — which it should be, since it was extracted from hardware playback —
and survives the tokenizer with a few percent of clamping on four of five
tracks. The generators require intervention on half to nearly all of their
notes.

`actr-02` is the informative exception: 30.1% clamping introduced by the
round trip alone, on a sparse 72-event track. The representation does degrade
some material substantially, so the round-tripped arm is the control that
matters.

### Perceptual result

The three possible outcomes were written down **before** the control was
heard, so the answer could not be shaded afterwards:

| outcome | conclusion |
|---|---|
| **both sound musical** | **the generators are the failure; the negative result is clean and attributable** |
| published musical, round-trip not | the representation is destroying the music; the generators were never given a fair medium |
| neither sounds musical | the renderer is the limiting factor and the 48-excerpt assessment cannot be attributed to the generators |

**The first outcome is what occurred.** The same listener reports that

- `real_published` and the corresponding `real_roundtrip` **sound identical**
  to each other, and
- the control renders **sound recognisably like music** — identifiable
  melody, rhythm and harmony through the same plain timbre.

Both halves matter:

1. **The tokenizer's quantisation is perceptually transparent on real music.**
   96 log-spaced time buckets, 32 duration quantiles and semitone-rounded
   pitch cost nothing audible — including on `actr-02`, whose round trip
   introduces 30.1% voice-stealing clamping. The middle outcome is ruled out.
2. **The renderer conveys music.** The bottom outcome is ruled out. A plain
   tone, fixed gain, no normalisation and eight-voice stealing are together
   sufficient for real SNES music to be recognisable as music.

> A sample-domain check is worth recording because it looks alarming and is
> not: the two arms differ substantially as waveforms — all five md5 pairs
> differ and the difference signal is about 3 dB **louder** than the signal
> itself. Displacing a note by a few milliseconds produces an enormous
> sample-wise difference while sounding the same, so sample distance is not
> perceptual distance. The listener is the correct instrument here, and
> waveform difference should not be read as audible difference.

### The control is not single-game

The first draw took the first qualifying tracks in split order and drew all
five from ActRaiser, which would have left the control vulnerable to one game
being atypical. Redrawn one track per game — ActRaiser, Alien 3, F-Zero,
Sailor Moon, Star Fox — the pattern holds: **0.0% voice stealing as published
in every game, 0.0–2.6% round-tripped.** Rendered under
`~/workplace/level2_renders_crossgame/`.

Files are outside both repositories, in `~/workplace/level2_renders/` and
`~/workplace/level2_renders_crossgame/`.

## Attribution: the generators

With the pipeline cleared, the 48-excerpt result attributes to the
generators. Real SNES music, carried through the identical representation and
the identical synthesiser, is recognisable as music; neither generator's
output is. The failure is in what the generators produce, not in how it is
measured or heard.

This is a clean, defensible negative result and the experiment can close on
it.

## What is not being done in response

- No larger Transformer.
- No temperature search until one excerpt sounds pleasant.
- No 20-listener study comparing two generators when the preliminary
  impression is that neither produces recognisable music. That would spend
  effort measuring a problem not yet diagnosed.

## What this means for the dataset

This does not invalidate SNES-MDB, and arguably the opposite: its validated
measurements are what allowed predictive success, grammar failure,
hardware-consistency failure and apparent perceptual failure to be told apart
at all.

What has been shown is narrower and worth stating exactly: **the current
four-token event representation and a small autoregressive Transformer are
insufficient, under the tested conditions, to produce convincing SNES-style
compositions.** It has *not* been shown that SNES-MDB cannot support
convincing generative music — that would require testing other
representations and models, and should wait until the control above is read.

The original contribution — extracting reproducible, hardware-grounded
symbolic music from a diverse collection of SNES games — is unaffected.
