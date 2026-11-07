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
| `summary.json` | corpus-level extraction statistics, including the row-clock census |
| `provenance.json` | the commit, dirty flag and parameters that built this tree |
| `performance.json` | per-game performance conventions, over all tracks |
| `performance_music.json` | the same, restricted to `track_class == music` |

**`timbre_codebook.json` is deliberately not published.** The milestone 5
codebook failed its own validation -- class agreement across games falls to the
shuffled null once the leaking features are removed -- and `timbre_class` is
written as `-1` for every note in this corpus rather than offering a number
from it. Shipping the file would invite a consumer to use a clustering this
project has documented as not transferable. The analysis and the negative
result are in [milestones.md](milestones.md); the artifact carries neither.

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

## The row-rate decision, recorded

**snesmdb uses a 100 Hz uniform score grid as a deliberate analytical
convention.** The rate was selected by empirical evaluation of event
preservation, timing accuracy and storage cost on SNES music. **It does not
represent a universal SNES sequencer frequency** — no such frequency exists;
every driver programs its own timer.

The primary timer-derived grid and the original timestamped event records
remain available for hardware-oriented analysis and higher-resolution
reconstruction.

**100 Hz is not claimed to be optimal for all future SNES recordings.** It is
the best-supported choice among the candidates measured, on the corpus as it
stands. `tools/rate_benchmark.py` reruns the comparison, and
`make verify` re-checks the preservation claim on every rebuild, so the figure
cannot quietly rot as the corpus grows.

### What the benchmark measured

Full corpus: **1,458,211 pitched notes across all 1,243 tracks that contain
one**, of 1,316. The 405,288 unpitched notes are excluded, and that is the
exact coverage of the claim — an unpitched note carries no note number and so
never enters a piano roll in any format, at any rate.

| rate | exact divisor | events lost | repeat attacks | collisions | notes < 1 row | onset median / p95 |
|---|---|---|---|---|---|---|
| 50 Hz | yes | **94** | 67 | 27 | 0.74% | 4.94 / 9.5 ms |
| **100 Hz** | **yes** | **1** | **1** | **0** | 0.14% | 2.49 / 4.7 ms |
| 200 Hz | yes | **0** | 0 | 0 | 0.03% | 1.26 / 2.4 ms |

**100 Hz loses exactly one event in 1,458,211, and 200 Hz loses none.** So the
price of the rate is one note: doubling to 200 Hz recovers a single attack, at
twice the rows and storage. That is the whole argument, and it is now a known
quantity rather than a bound.

### Known quantisation limitation

> The 100 Hz uniform grid loses one repeated-note attack among 1,458,211
> pitched events in the evaluated corpus. The affected passage occurs in
> Axelay, track `axe-03`, where two successive same-pitch attacks are separated
> by approximately 5.1 ms. The second attack merges into the first at 100 Hz
> but remains distinguishable at 200 Hz. Original event timestamps preserve
> both.

Named precisely because a loss that more resolution *cannot* fix would mean
something different — a representation limit rather than quantisation. This one
is plain quantisation.

| | |
|---|---|
| track | `axe-03` — Axelay, "Unkai" |
| notes | voice 5, both MIDI 98.998, `srcn` 1, note ids 940 and 941 |
| gap | 5,228 ticks = **5.1055 ms** |

Two consecutive same-pitch attacks 5.1 ms apart, a retrigger around 196 Hz. At
100 Hz a row is 10 ms, so both land on one row and the second attack is
rewritten as duration. At 200 Hz the rows are 5 ms and they separate, which is
why the loss disappears there and nowhere beyond.

Both notes are present with exact timestamps in `records/` and `raw/`. Only
the 100 Hz score drops the second attack.

Two figures in this section were wrong before being measured directly, and the
corrections are kept because the pattern is instructive. A 296-track sample
reported "100.000% preserved" — rounding — so the claim is now a count. And
"200 Hz loses the same one" was inferred from a table rounding to 0.000%,
never measured; it loses none.

**Repeated attacks are counted separately from collisions** because the losses
differ in kind. A collision drops a note. A lost repeated attack silently
rewrites rhythm as duration — a tremolo or drum roll becomes one sustained
note — which nothing downstream would detect by counting notes. At 24 Hz, the
rate first considered for NES-MDB comparability, that loss is 174 events.

### For microtiming, do not use the score

Even at 100 Hz a row is 10 ms, and onsets move by 2.49 ms at the median and
4.7 ms at p95. Durations under 10 ms cannot be represented at all (0.14% of
notes). **Anyone studying expressive microtiming should use the original
timestamps, not reconstructed score rows.** Those are preserved and published:

- `records/*.json` — every note with `start` and `end` in **raw SPC700
  clocks**, one tick being 0.00098 ms, unquantised
- `raw/*.jsonl.gz` — the full timestamped DSP register write log, which is
  what everything else is derived from
- `intake/*.json.gz` — absolute times in seconds, in the published tree

The event log is the authoritative representation. Both score grids are
derived, lossy views of it, and the uniform grid is additionally a convention
rather than a measurement.

## Two row grids: the driver's, and a uniform one for comparability

Each score file carries **two** sets of the three formats.

| | primary | `uniform` |
|---|---|---|
| row rate | this SPC's timer tick | **60.0988 Hz, every track** |
| row duration | 2.00–12.50 ms, 78 distinct rates | **16.639 ms, always** |
| rows per music track (median) | 12,690 | **4,658** |
| what it is | a hardware measurement | a convention, stated as one |
| use it for | anything about this driver | comparing games, or NES-MDB |

The primary grid is the honest hardware answer and it **cannot be compared
across games**: the rate differs per track, so "notes per row" means something
different in every one. NES-MDB has no such problem — every row there is
16.64 ms because every NTSC engine inherits one video frame rate — and that
uniformity is what makes a corpus of row arrays comparable at all.

So the `uniform` block re-indexes the same notes at the NES-MDB rate.
**Matching 60.0988 Hz is not physically meaningful on the SNES** — it is an
NTSC video artifact and the SPC700 has no relationship to it — and the grid
says so in its own `reason` field. The point is a shared time unit, not
physics: a model can train across both corpora without rescaling.

It also costs less than the primary grid rather than more. Measured over 120
music tracks:

- **4.03× fewer rows** (677,194 against 2,731,994), because a 500 Hz driver
  clock produces eight times the rows of a 60 Hz grid
- **3 notes unplaced of 155,633** (0.002%)
- max polyphony 8, within the hardware

The quantisation error is 4.15 ms median against the primary grid's exact
placement. That error *is* the 16.64 ms grid, and it is the same one NES-MDB
carries, so a consumer comparing the two corpora is comparing like with like.
If you want finer, 100 Hz divides the SPC700 clock exactly and costs 2.49 ms —
the rate is `scores.UNIFORM_HZ` and a rebuild can change it.

## Rows are indexed on the SPC700's own timer register

Every one of the **1,316 tracks** is clocked from a hardware register read out
of the SPC file. Nothing is inferred and nothing is averaged:

| `clock.source` | tracks | |
|---|---|---|
| `timer_register` | **1,316 (100%)** | read from `$F1`/`$FA`-`$FC` |
| `game_tick` | 0 | inferred from write cadence (fallback) |
| `track_tick` | 0 | inferred, single track (fallback) |
| `fixed` | **0** | a fabricated 100 Hz convention |

An SPC dump carries the whole 64 KB of ARAM, and the SPC700's timer registers
live in its I/O page: `$F1` holds the enable bits, `$FA`/`$FB`/`$FC` the T0, T1
and T2 targets. T0/T1 count at 8 kHz and T2 at 64 kHz, each divided by an
8-bit target where 0 means 256. The lowest enabled timer is taken as the
sequencer: **T0 for 1,295 tracks, T2 for 20, T1 for 1**.

**One row is one physical timer tick.** That is a deliberate choice over the
musical alternative. Where a driver counts M timer ticks per sequencer row,
rows are M times finer than the music and a note spans several of them; but M
is only recoverable from write cadence, which fails on 220 tracks, so dividing
by it would make a row mean different things in different tracks. The uniform
definition won.

**A row is a uniform definition, not a uniform duration.** `$FA` differs per
game, so a row is 2.00 ms in Super Mario World and 12.50 ms in Donkey Kong
Country — 80 distinct clock rates across the corpus, 32.8 Hz to 500.0 Hz,
median 205.1 Hz. Any cross-game comparison of a per-row quantity has to divide
by `clock.hz`.

**Why this replaced an inferred clock, twice over.** The first design fitted a
period to note onsets, which produced 346 distinct row rates across 664
tracks, 75% of them unique within a single game. The second measured the
driver's tick from DSP write cadence, which worked for most drivers and failed
for 220 tracks — 178 of them music — that fell back to a fabricated 100 Hz.
Three hypotheses for that failure were tested against write logs and all three
were refused: N-SPC does not expose a periodic tick in its DSP writes at all,
in either the music or the global registers, at any rate between 30 and 800 Hz.
The information was never in the write log; it was in the file.

**The register corroborates the estimator where both exist.** `8000/$FA`
reproduces every clock write cadence found — Chrono Trigger 190.48 Hz, Super
Metroid 500, Final Fantasy VI 205.13, Secret of Mana 222.22, Donkey Kong
Country 80, Earthbound 500, Kirby 500, Dragon Quest 5 200, Castlevania IV 250
— and four games differ by an exact power of two (Batman Returns 2x, Breath of
Fire 2 and Mega Man X ½, Plok! ¼), which is the software divisor M. Ten exact
agreements and four clean ratios.

Being per-track, the read also handles the drivers that reprogram their
divider mid-game: Tales of Phantasia dumps 31 distinct timer values across its
tracks, Star Ocean 26, Lufia 2 21, Super Turrican 13, Plok! 10. Each track gets
its own rate rather than a per-game average or a fallback.

**Caveat on the source.** `$F1` is write-only on real hardware, so the byte an
SPC carries there is a convention of the dump format rather than something the
CPU could read back. It is trusted because it validates against those ten
independent measurements, which is empirical corroboration and not a guarantee.

**Quantisation cost is negligible.** 529 of 1,458,115 placed notes (0.036%)
are shorter than one row and were snapped to the nearest; 5 notes went
unplaced and 2 cells are contested. The `grid` block is still reported as the
**onset** period — a real and separate musical measurement — but it no longer
indexes anything.

## A row is a hardware tick; the musical row needs `software_divisor_m`

One row is one SPC700 timer tick. Where a driver counts M ticks per sequencer
row, rows are M times finer than the music and a note spans several of them.

`timing.software_divisor_m` in the intake tree, and `software_divisor_m` in
each score, carries M where it can be recovered: it is the ratio of the
register clock to the rate `tick.py` measures from DSP write cadence, since the
first is the timer and the second is the sequencer. That ratio is a clean
integer for **403 of 1,316 tracks (31%)** -- 462 of the 519 that have a
write-cadence estimate at all, 89% of them, median ratio exactly 1.00.

**It is `null`, never 1, where unknown.** Defaulting to 1 would silently assert
that the row IS the musical row for the other 913 tracks. A consumer wanting
musical rows must either restrict to tracks where M is known or accept rows at
timer resolution.

`driver_tick_hz` is published beside it as the quantity M derives from. It is
the SEQUENCER rate rather than the timer, is absent for 797 tracks, and is
wrong for 20 that report exactly 2,048 ticks -- intra-burst write spacing
mistaken for a timer. Those 20 are refused a divisor because their ratio is not
a clean integer, which is the guard working rather than an accident.

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
make corpus          # the whole thing: ~80 min on 8 jobs
```

That is the only entry point that guarantees the ordering, and the ordering is
load-bearing. The steps, if you need them individually:

```sh
make                 # build/spc_dump
make extract         # ~50 min  SPCs -> manifest, records, scores, clock
make performance     #          the §7 analysis, all tracks and music-only
make publish         # ~18 min  -> DIST_DIR
make verify          #          13 checks; exits non-zero on any failure
```

Override with `SPC_DIR=`, `OUT_DIR=`, `DIST_DIR=`, `JOBS=`.

**This used to need a second whole-corpus pass, and it was easy to forget.**
A `reclock` step derived the row clock after extraction, and the recipe
documented here omitted it -- which produced a corpus with **zero** scored
tracks, silently, because publish found no clock and wrote nothing without
erroring. Anyone reproducing the corpus from these instructions would have
gotten an empty tree and no explanation.

The step is now **gone rather than documented more loudly.** It existed
because the row clock came from a per-game consensus over write-cadence
ticks, and no track's clock could be settled until every track of its game
had been seen -- a genuine reason for a second pass. The clock is now read
from each SPC's own timer register, so it is a pure function of one track and
is decided inside the extraction loop. One pass, nothing to forget.

Two things follow from that, and they are the reason it was worth doing rather
than just fixing the prose. `make corpus` is the ordering instead of a list of
commands, so a recipe that executes cannot drift from the recipe that is
written down. And `make verify` gates it: every one of its checks corresponds
to a defect that really shipped from this pipeline, and **not one of them
announced itself** -- each was found by reading output that looked fine.

`tools/timbre_features.py` and `tools/timbre_codebook.py` are deliberately
absent from this sequence. They still run, and the analysis is in
[milestones.md](milestones.md), but their output is not published -- see the
note on `timbre_codebook.json` above.

`publish.py` refuses to write inside a git work tree, because the output is
derived from research-only material.

## What this is not

**Not a training corpus for a generative model.** On the NES side a clean
retrain improved validation loss by 11.4% and produced output a listener called
"barely music". Next-token loss does not measure music, and more data does not
change that argument.

It is a dataset and the tools to rebuild it, for analysis, comparison, and as a
public artifact. `performance-conventions.md` is what it was built to produce.
