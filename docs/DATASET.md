# SNES-MDB — what this corpus is, where it came from, and where it is wrong

Symbolic SNES music extracted from SPC files by emulating the SPC700 and
logging every DSP register write. The counterpart to NES-MDB, built because no
SNES equivalent has been published.

**1,316 tracks · 22 games · 1,863,499 notes · 109,263 rendered seconds.**

---

## Provenance, and what is not here

Extracted from SPC sets published by **snesmusic.org**. Their terms are
narrower than NES-MDB's research licence: the files are copyrighted by their
owners and offered "for educational and personal non-profit use only", "as fair
use samples for preservation purposes only".

Consequently:

- **No SPC files are distributed here**, and none are in the source repository.
- Everything in this tree is **derived data** plus the tools to regenerate it
  from SPCs you obtain yourself.
- Treat it as `use_class: research_only`. It is not cleared for a product.

Every record carries the **SHA-256 of the SPC it came from**, so any row can be
traced to its source and the extraction reproduced. The extractor is
deterministic: same SPC, same output.

Per-track metadata — title, game, composers, date — comes from the **ID666 tag
inside each SPC**, not from scraping. The archive credits a composer per *set*;
the tag gives one per *track*.

## How it was made

```
SPC ─► emulate SPC700, log every DSP write ─► per-voice note events
         (blargg's snes_spc, unpatched; hook via its own macro)
     ─► decode each BRR sample from ARAM, estimate f0 ─► note numbers
     ─► infer the row grid from key-on spacing      ─► rows
     ─► cluster sample features                     ─► timbre classes
     ─► emit
```

No step identifies the driver. Nothing game-specific enters the pipeline, and
**zero unhandled DSP registers** occur across all 22 games — which is the claim
the corpus exists to support, tested against Square's AKAO, Nintendo's N-SPC,
Konami, Capcom, Rare, Chunsoft, HAL, tri-Ace, Namco, Factor 5, Software
Creations and Quintet.

Render length per track comes from the ID666 "seconds to play" field, not a
fixed window. A flat 60 s captured 8.8% of Final Fantasy VI's 683-second
"Dancing Mad (Full)" and truncated 68 of its 82 tracks.

## What is in the tree

| path | contents |
|---|---|
| `index.json` | one row per track: ids, game, composers, split, source hash, what was emitted |
| `scores/*.json.gz` | the three score formats, plus the grid and driver tick |
| `midi/*.mid` | 8-track type-1 MIDI, one track per DSP voice |
| `intake/*.json.gz` | per-voice note trees with absolute times |
| `splits.json` | composer-disjoint train/valid/test assignment |
| `summary.json` | corpus-level extraction statistics |
| `timbre_codebook.json` | the codebook, and the validation that mostly failed |
| `performance.json` | per-game performance conventions |

### The three score formats

| format | shape | NES-MDB analogue |
|---|---|---|
| `separated` | 8 tracks × rows, cell = MIDI note or 0 | `sepsco` |
| `blended` | rows × sorted distinct notes, voices merged | `blndsco` |
| `expressive` | 8 tracks × rows, cell = (note, velocity, timbre class) | `exprsco` |

**`separated` keeps voice identity but that identity means less than the NES
equivalent.** On the NES, track 0 is always pulse 1. Here, voice 0 is whatever
the driver assigned it to, and the assignment can change mid-song. `blended` is
immune to this and is the more comparable format.

## Splits

Composer-disjoint, with the **whole game** as the unit of assignment.

| split | tracks | share | requested |
|---|---|---|---|
| train | 1,049 | 79.71% | 80% |
| valid | 135 | 10.26% | 10% |
| test | 132 | 10.03% | 10% |

16 components, no composer spanning a split. A game is indivisible because its
tracks share an instrument bank, a driver and an idiom — splitting one leaks
more than splitting a composer would.

**The splits are composer-disjoint; they are NOT driver-balanced.** At a
previous corpus size every AKAO and N-SPC track landed in `train`. Check the
driver distribution before concluding anything from `valid` or `test`.

Composers are matched as **individual people**, not raw tag strings: a field
crediting "Masanori Adachi, Taro Kudou" links to any game crediting either, or
disjointness would pass on a technicality.

---

# Limitations

Read this section before using the data. Everything here was measured.

## Pitch is usable in bulk, unreliable per note

**78.7% of notes carry a note number.** The rest are percussion, noise,
or samples whose fundamental was not recoverable — labelled unpitched rather
than given a confident wrong number.

**1.78% of pitched notes land outside MIDI 12–108**, down from 9.1%.
Both estimators are ambiguous by factors of two — autocorrelation can latch
onto twice the period, and the loop refinement's integer period count preserves
whatever octave it was handed — so the octave is resolved against the spectrum
instead: a fundamental an octave too low carries almost no energy at its own
first harmonic. Measured over 179,763 notes, out-of-range fell from 9.11% to
1.96%, against **16.42% for a control that shifted by a random octave**, and
the chosen shifts concentrated at −1 (328 of 356), which is the estimator's
known failure mode rather than a spread of fitted values. An independent check
that touches neither the spectrum nor the in-range test agrees: the span of
simultaneously sounding pitches tightened from 34.1 to 29.8 semitones while the
random control widened it to 41.5.

Two caveats. 237 samples that were already fully in range were also moved, and
the in-range metric cannot adjudicate those; the harmonic-energy margin on
moves is median 2.43× with 77% clearing 1.5×, so roughly a quarter are
marginal. Every estimate carries `octave_shift` and `octave_margin` so a
consumer can see what was moved and on what evidence, and every note carries
`pitch_confidence`.

Relative pitch within a sample is near-exact for some drivers and not others —
median deviation from an equal-tempered ladder is 0.30 cents for Rare and
**10.67 cents for Capcom**. Interval-level work is safe for Rare and Square and
is not safe for Capcom.

## The row grid exists for two thirds of tracks, and is not the driver tick

**866 of 1,316 tracks (65.8%)** have a row grid, median fit 0.96. The rest are
either too sparse (58 tracks) or have onsets that do not lie on one period.

**The grid is the music's onset grid, not the hardware's clock.** The design
assumption — that the driver tick falls out as the dominant key-on spacing, as
it does on the NES where music advances on a universal 60.0988 Hz frame — is
false here. Measured: Zelda's onset grid is 5.4 rows/s against a real 62.5 Hz
tick (11.6× out); Final Fantasy VI 11.0 against 205.4 (18.7× out). Only Donkey
Kong Country agrees, because its driver keys on densely enough to exercise
every tick.

A separate `tick` field reports the driver timer, recovered from the write
cadence. It is present on **519 tracks (39.4%)** and is believable for four or
five of twenty-two drivers — judge it by whether every track in a game agrees:
Final Fantasy VI and Mega Man X give one distinct value, **Tales of Phantasia
gives 36 over 52 tracks**. One known artifact: 20 tracks across six unrelated
games report exactly 2,048 ticks, which is intra-burst write spacing and not a
timer.

**11.3% of placed notes are shorter than one row** and were snapped onto the
nearest one, moving their onset. Per game: 2.2% for Plok!, **32.4% for Kirby
Super Star**. The games where this is worst are the ones whose onset grid sits
furthest from their tick.

## The timbre axis is a binary distinction, not a vocabulary

`expressive` carries a class from a 5-class codebook over 1,162 distinct
samples. **Only the tonal/percussive split was shown to transfer across games.**

Fitted on the 16 train games and applied to 6 unseen ones, the pitched/
unpitched division transfers exactly, while register does not — one class moved
**16 semitones** between training and held-out games. Cross-game agreement over
the whole corpus sits at the shuffled-label null on every axis. So the finer
structure describes each game's own sample bank.

Each score carries `timbre_validated: "tonal_vs_percussive_only"`. Use the
class as a binary tonal/percussive flag. Do not treat class 3 as an instrument.

**Voice roles are not provided.** A role needs register and function, and
register is exactly what fails to transfer.

## MIDI drops things, and names them

Only notes with a recovered pitch appear — 81.8% of the corpus. No General MIDI
program is set, because sample identity does not transfer and a program number
would be fabricated. Channel 9 is never used, so nothing is implicitly a drum.
**Phase inversion is lost**: a negative side volume inverts that side's phase
and MIDI cannot express it, so magnitude is written. That is not a corner case
— Tales of Phantasia inverts on 55.8% of its notes and Star Ocean on 52.6%. The
per-track `midi_summary` counts every drop.

A fixed 120 BPM at 480 PPQ is written because the S-DSP has no tempo. Timing is
absolute, not quantised to the row grid.

## The intake schema is not verified against a consumer

`intake/*.json.gz` is `snesmdb.intake.v1`, documented by its own fields. The
design intends it for the sibling renderer's `acquire(from_extracted=True)`,
**which is not present in this repository and against which it has not been
tested.** Treat the schema as proposed.

## Composer credits truncate

The ID666 composer field is 32 bytes and overflows silently. **242 of 1,316
tracks (18.4%)** carry a truncated credit, concentrated in Earthbound's 206
(`Akio Ohmori, Ritsuo Kamimura, Ke` — a third contributor unrecoverable).
Disjointness still passes for those tracks, but it passes on the names that
happened to fit. `composer_truncated` flags each one.

## Structural failures

**24 of 1,316 tracks (1.8%)** fail a structural check. 17 share one cause: an
SPC is a snapshot of a running system, so a track already sounding and never
re-keyed has no key-on to recover and the note model cannot represent it. Every
such track is a drone, a jingle or an effect. Two more are sub-second jingles
whose ID666 length rounds up to a whole second, tripping a check that expects
register writes to span the window.

## Corpus composition

22 games, weighted toward JRPGs and first-party titles, with Earthbound at
206 tracks (15.7%) the largest single game. Not a random sample of the SNES
library, and not balanced by genre, year or region.

## Two of the hardware's features are effectively unused

**106 noise notes and 727 pitch-modulated notes out of 1,863,499** — 0.006% and
0.039%. Drivers write the NON and PMON registers constantly and always with
zero. If you are modelling the S-DSP, this corpus will not exercise either.

---

## Rebuilding

```sh
make                                   # builds build/spc_dump
python3 tools/extract.py data/spc data/out --jobs 8
python3 tools/timbre_features.py data/out data/out/timbre_features.json
python3 tools/timbre_codebook.py data/out/timbre_features.json data/out
python3 tools/performance.py data/out data/out/performance.json
python3 tools/publish.py data/out <dist-dir>
```

`publish.py` refuses to write inside a git work tree, because the output is
derived from research-only material.

## What this is not

**Not a training corpus for a generative model.** On the NES side a clean
retrain improved validation loss by 11.4% and produced output a listener called
"barely music". Next-token loss does not measure music, and more data does not
change that argument.

It is a dataset and the tools to rebuild it, for analysis, comparison, and as a
public artifact. `performance-conventions.md` is what it was built to produce.
