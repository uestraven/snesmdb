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
     ─► measure the driver's timer from write cadence ─► the row clock
     ─► (also: fit a period to onsets, reported but not used for rows)
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
| `scores/*.json.gz` | the three score formats, plus the row clock and the onset grid |
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

## Rows are indexed on the driver's own clock, not on an inferred grid

Every one of the **1,316 tracks** has row scores, because every track has a row
clock. What varies is the strength of the evidence behind it, and the `clock`
block says which of three rules produced it:

| `clock.source` | tracks | what it means |
|---|---|---|
| `game_tick` | 926 (70.4%) | an SPC700 timer rate corroborated across the game |
| `track_tick` | 140 (10.6%) | this track's own rate, verified against the hardware |
| `fixed` | 250 (19.0%) | a 100 Hz convention, not a measurement |

**81.0% of tracks are indexed on a measured hardware clock** (798 of 1,006
music tracks). Treat `fixed` rows as having an arbitrary time unit.

**Why not the onset grid.** The first design fitted a period to note onsets,
reasoning by analogy with the NES, where every game inherits one row clock. The
analogy is false twice over. On the NES the shared rate is the **PPU** frame
rate of 60.0988 Hz, which music engines pick up because they run off the vblank
NMI — not the APU frame counter, which is a separate ~240 Hz divider driving
envelopes. And the SNES has no equivalent signal at all: the SPC700 and DSP sit
on their own crystal, isolated from the CPU and PPU, and each driver programs
its own timer. There is no universal SNES row rate to borrow.

Fitting onsets instead produced **346 distinct row rates across 664 tracks,
75% of them unique within a single game** — Final Fantasy VI alone got twenty,
including 2.2 and 2.3 as separate values. One row meant 4 ms in one track and
847 ms in another, so the row arrays were not comparable across the corpus,
which is the one property that makes row arrays worth having.

**The clock is not the tempo.** Timer 0 and Timer 1 count at a base 8 kHz and
Timer 2 at 64 kHz, each scaled by an 8-bit divider, so the clock is the quantum
the sequence is measured in. Tempo is how many ticks a note consumes and varies
freely: Final Fantasy VI holds 205.13 Hz across all 55 music tracks while its
median inter-onset spacing runs from 13.8 driver ticks to 183.0, a 13× spread,
clustering near 24/36/48/72 — tracker row durations.

**The hardware constrains the measurement, which is how it is checked.** A real
timer read must land on base/N. Across the corpus range a random frequency does
so 20.4% of the time; **89% of the 519 measured ticks do**, and all fourteen
per-game clocks resolve to a plain Timer 0/1 divider — Final Fantasy VI
8000/39, Chrono Trigger 8000/42, Secret of Mana 8000/36, Mega Man X 8000/128,
Super Metroid 8000/16. Clocks are snapped to the nearest achievable divider,
and a track's own tick is trusted only if it passes.

**Eight games have no per-game clock, and for five the driver is the reason.**
Star Ocean, Tales of Phantasia, Lufia 2, Super Turrican and Plok! put 63–100%
of their ticks on real dividers but spread them over 4–23 distinct rates: these
drivers set tempo by reprogramming the divider rather than counting a fixed
tick, so no constant exists and each track is indexed on its own verified rate.
The other three (Actraiser, Axelay, Zelda, Super Mario World) simply have too
few confident ticks. **A game does not have one tempo, and this is where that
shows up** — it is a property of the drivers, not a failure of the clock.

**0.03% of placed notes are shorter than one row** (410 of 1,465,861) and were
snapped onto the nearest, moving their onset. On the inferred grid this was
**11.3%**, up to 32.4% for Kirby Super Star: the fitted period was coarser than
the music it described and was displacing one note in nine. The driver clock is
a fine subdivision, so almost nothing is lost. Contested cells — two notes of
one voice falling in one row — number 16 across 1,863,499 notes.

One known artifact survives in the underlying `tick` field: 20 tracks across
six unrelated games report exactly 2,048 ticks, which is intra-burst write
spacing rather than a timer.

The `grid` block is still present on every row. It remains a real measurement
of the **onset** period, which is a musical question rather than a hardware one,
and the scores record it as `onset_grid` for provenance. It is no longer what
the rows are indexed on.

## Velocity ignores the envelope, and the envelope is not recoverable from key-on state

`velocity` is derived from the two signed side volumes only:
`(|VOL_L| + |VOL_R|) / 2`. The DSP's actual output is
`amp = ((sample * env) >> 11) * VOL >> 7`, so loudness is **env × VOL** and
the envelope is missing from every velocity in this corpus. Three measured
facts bound how much that costs, and they point in different directions:

**For 88.7% of notes the envelope is ADSR, and for 85.2% of those the sustain
level is 7** — the envelope holds at full scale, so VOL alone is the loudness
and nothing is lost. SL is read as `ADSR2 >> 5`, with the decay ending when
`(env >> 8) == SL`, so the plateau is `SL × 256` and SL=7 means no decay at
all.

**13% of notes have SL < 7**, where VOL-only velocity overstates sustained
loudness — worst at SL=0 (3.4% of ADSR notes), which decays to silence. A
staccato pluck and a held horn with equal VOL currently get equal velocity.
This part is fixable from data already in the note records.

**For the remaining 11.3% the envelope cannot be read from the key-on state at
all.** These notes have ADSR disabled and GAIN in direct mode, and the drivers
that do this run their own software envelope by writing GAIN continuously —
Mega Man X writes GAIN 390 times against 26 SRCN writes in ten seconds. The
value at key-on is therefore an arbitrary point on a ramp, and it is **zero for
most of them** (5.74% of all notes). Scaling velocity by it would silence
expressive notes rather than correct them. Recovering it needs the envelope's
peak across the note's span, which means retaining the DSP write log — these
are not stored, so it needs a re-extraction.

Not an inherited-state artifact: the SPC snapshots have ADSR enabled on nearly
every voice (ADSR1 bit 7 set), so the zeros are written by the driver.

**Driver envelope strategies differ enough that one rule will not serve.**
Measured over ten seconds of one track per game, counting writes:

| driver behaviour | games | signature |
|---|---|---|
| full voice patch per note | DKC, Kirby, Super Metroid, Star Ocean, Tales of Phantasia, Super Mario World | SRCN/ADSR1/ADSR2/GAIN written in lockstep |
| ADSR per note, no GAIN | Chrono Trigger, Secret of Mana | GAIN never written |
| software envelope | Mega Man X | GAIN/ADSR1 written far more often than SRCN |
| set once, VOL does everything | Earthbound (this track: one write of each) | VOL written 274×, patch 1× |

Phase inversion is also lost: velocity takes the magnitude, and a negative side
volume inverts that side's phase, which two games do on over half their notes.

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

Only notes with a recovered pitch appear — 1,465,863 of 1,863,499 notes are
written and 382,544 dropped, across 1,252 of the 1,316 tracks (a track with no
pitched note at all gets no file). No General MIDI
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
