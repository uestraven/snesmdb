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

## Voice state is seeded from the SPC snapshot

An SPC is a dump of a running system, so its DSP register block already holds
the voice parameters the driver set up before the dump — and a driver has no
reason to rewrite a register whose value is already right. Super Mario World's
"Athletic" writes only KON, KOFF, VOL and PITCH for its entire length, never
SRCN, ADSR1, ADSR2 or GAIN.

Extraction originally started every voice register at zero and tracked only
observed *writes*, so anything untouched read as 0. Measured effect of seeding
from the snapshot instead:

| | before | after |
|---|---|---|
| notes reporting `srcn = 0` | 200,515 (10.8%) | 52,093 (2.8%) |
| distinct samples referenced | 7,887 | 8,168 |
| high-confidence f0 estimates | 5,303 | 5,447 |
| implausible PITCH registers | 26,059 | 25,224 |
| sample estimates needing an octave shift | 44.58% | 42.83% |
| tracks reporting a silent envelope | 540 | 0 |

**SRCN changed for 148,422 notes (8.0%) across 619 tracks.** Since f0 is
estimated from the BRR sample at SRCN, each of those was previously pitched
against the wrong sample and assigned the wrong timbre class — "Athletic" has a
snapshot SRCN of `[10,10,10,10,11,8,2,8]` and all 1,164 of its notes were
recorded as sample 0. Worst affected: Super Turrican (100% of its notes),
Dragon Quest 5 (41%), Breath of Fire 2 (37%), Earthbound (30%), Mega Man X
(24%).

Pitched-note coverage fell slightly, 78.7% to 78.3%, because some of the
newly-correct samples fail the f0 plausibility test that the wrong ones passed.
Fewer and right beats more and wrong.

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

## Velocity is the attack; sustain is a separate channel

The DSP computes

    out = (sample * env) >> 11        # env is the 11-bit internal envelope
    amp = (out * VOL) >> 7            # VOL signed 8-bit, per side

so amplitude is **env x VOL**, and `velocity` carries VOL alone. That is
correct for the ATTACK: in ADSR mode the attack phase drives env to full scale
whatever the rate, so peak loudness really is VOL. What VOL cannot express is
where the note SETTLES, which is why the expressive score has a fourth
channel.

`expressive.channels` is `(note, velocity, timbre_class, sustain)`. Channel 3
is the sustained amplitude on the same 0..127 scale as velocity, so the two
compare directly: equal means the note holds, lower means it decays to that
level. **-1 means the envelope cannot be read from the key-on state** -- a
ramping GAIN mode -- and is not zero, because zero means silent. No note in
this corpus uses a ramping mode, so -1 should not appear.

Corpus-wide over 1,863,499 notes: **93.73% ADSR, 6.27% GAIN direct, no ramping
modes**, so the envelope is 100% decidable. **80.0% of notes hold at full
scale** and need no correction; the other **20.0% (372,538 notes)** settle
below, down to silence at sustain level 0. Measured over expressive CELLS,
which are duration-weighted rather than note-weighted, 90.3% hold, 6.2% decay
and 3.5% are silent.

Sustain level is `ADSR2 >> 5`, and the hardware leaves decay when
`(env >> 8) == SL`, so **the plateau is `SL x 256`** -- the bottom of a
256-wide band, not `(SL+1) x 256`, which is that band's top edge. SL=7 is
special: env is already `0x7FF` when the attack ends and `0x7FF >> 8` is 7, so
decay never runs.

Note that the expressive score was present in `scores.py` from milestone 6 but
**was never emitted to disk until this change**, so neither it nor the sustain
channel reached any published file before now. `timbre_class` is written as -1
throughout: the milestone 5 codebook failed its own cross-game validation, so
no class number from it is offered.

**Driver envelope strategies differ, which is why one rule would not serve.**
Measured over ten seconds of one track per game, counting register writes:

| driver behaviour | games | signature |
|---|---|---|
| full voice patch per note | DKC, Kirby, Super Metroid, Star Ocean, Tales of Phantasia, Super Mario World | SRCN/ADSR1/ADSR2/GAIN written in lockstep |
| ADSR per note, no GAIN | Chrono Trigger, Secret of Mana | GAIN never written |
| software envelope | Mega Man X | GAIN written 390x against 26 SRCN writes |
| set once, VOL does everything | Earthbound (one track: one write of each) | VOL written 274x, patch 1x |

That last row is why voice state must be seeded from the SPC's DSP block --
see the note on SRCN above. Before it was, 540 tracks reported ADSR disabled
with GAIN 0, i.e. a silent envelope, purely because their drivers never
rewrote those registers. That artifact was 5.74% of notes; it is now 0.05%.

**The voice patch is always written before the key-on, never after**, so
reading the registers at the key-on instant captures the authoritative block.
Measured: Mega Man X 174/174 key-ons have the patch already in place (median
400 clocks earlier), Star Ocean 139/139 (4,281), Super Mario World 121/200
(2,202), and no driver writes a patch register in the 64-128 clocks following
a KON.

Phase inversion is still lost: velocity takes the magnitude, and a negative
side volume inverts that side's phase, which two games do on over half their
notes.

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
