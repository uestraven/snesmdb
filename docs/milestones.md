# Milestones

Six milestones, ordered so that each one is independently useful and the
riskiest work comes late, after the cheap work has had a chance to invalidate
it. Each has an exit criterion: a thing that is true, not a thing that was
attempted.

The ordering principle is that **pitch, grid and timbre are three separate
recoveries**, and the score formats need different subsets of them. That is
why the scores arrive progressively rather than all at once.

| # | milestone | exit criterion | risk |
|---|---|---|---|
| 1 | Voice event log | ✅ done | low |
| 2 | Real SPCs and corpus plumbing | ✅ done — **1,316 tracks, 22 games, splits within 0.3 points** | medium |
| 3 | Absolute pitch | ⚠️ partial — **81.8% pitched, 10.4% octave-suspect** | medium |
| 4 | Grid inference | ⚠️ partial — rows + both scores on 866 tracks; the driver tick is **not** in the key-ons | low → medium |
| 5 | Timbre vocabulary | ❌ **exit criterion not met** — a transferable 2-class split, not an instrument vocabulary | **high — and it was the risk named** |
| 6 | Publish | MIDI, all three scores, intake JSON, splits | low |

---

## 1. Voice event log ✅

Run the SPC700, log every DSP register write with absolute timestamps, recover
notes from that log. Ships the **raw format** and the **voice event log**.

**Done.** Round-trips exactly on a synthetic fixture: 6 notes, pitches
recovered precisely as written, zero unhandled registers, 13 tests with no
skips.

## 2. Real SPCs and corpus plumbing

The first time the write-log approach meets a driver somebody else wrote. A
curated starting set rather than the full archive, expanded once the extractor
survives it.

- batch runner over a directory of SPCs
- **the validation gate**: re-render each extracted score and compare against
  `snes_spc`'s own audio for that SPC, per track. The reference must be the
  emulator, never our own assumptions — this project's sibling shipped a BRR
  codec validated only against its own decoder and hid a 67% hardware wrap
  rate behind three rounds of green tests.
- manifest with provenance, content hashes, and a per-track extraction score
- **composer-disjoint splits**, which NES-MDB has and a corpus without is not
  comparable to it

**Exit (met):** a curated set extracted end to end, every track carrying
structural checks and a replayable reference log, splits built and
independently verified disjoint.

The "audio validation score" originally written here was removed rather than
achieved; see the gate note below and `src/snesmdb/checks.py`.

**Open dependency, resolved:** per-track composer metadata comes from the
ID666 tag inside each SPC, not from scraping -- the archive gives composer per
SET, the tag gives it per TRACK, and it needs no network. All 634 files carry
one, though 207 of them are truncated -- see the expansion note below.

Two data-quality problems it brought with it. One field often credits several
people ("Masanori Adachi, Taro Kudou"), so the graph links games through
individual PEOPLE rather than the raw label, or two games crediting an
overlapping pair would never link and disjointness would pass on a
technicality. And the field is 32 bytes, so it truncates: `mmx-b01.spc` reads
"Setsuo, Tomozou, Sato, Yuko, Kir" with no terminator and the last credit is
unrecoverable. Such tracks are flagged (`composer_truncated`) and listed in
the summary, because a link made through a cut-off name is a guess.

**Why this is medium risk:** every driver is different. Expect this milestone
to find that some assumption in milestone 1 only held for my own fixture.

### What first contact actually found ✅

**232 tracks, 5 games, all 5 major driver families, 379,821 notes, 227 of 232
passing every check, and zero unhandled registers in any game.** All three
splits non-empty with no composer leaks, so the exit criterion is met.

| game | driver | trk | notes | notes/s | KON *writes*/s | effective | voices |
|---|---|---|---|---|---|---|---|
| Final Fantasy VI | AKAO (Square) | 82 | 149,512 | 13.4 | 204.5 | 2.7% | 7.3 |
| Zelda: A Link to the Past | N-SPC (Nintendo) | 50 | 36,507 | 13.2 | **364.9** | **1.6%** | 5.4 |
| Super Castlevania IV | Konami | 36 | 55,823 | 14.1 | 249.6 | 2.9% | 6.1 |
| Mega Man X | Capcom | 35 | 57,612 | 26.3 | 62.5 | 16.7% | 7.9 |
| Donkey Kong Country | Rare | 29 | 80,367 | 21.0 | 21.0 | **100.0%** | 7.4 |

**A 17× spread in write rate and a 62× spread in how many of those writes mean
anything.** Rare writes KON only when it intends a note. Nintendo's N-SPC
writes it 365 times a second and means it 1.6% of the time. Any measure of
register *activity* would have ranked these five almost exactly backwards:
Zelda looks seventeen times busier than DKC and is in fact slightly sparser.
Counting set bits rather than writes is the single decision that made all five
work unchanged.

**Note density is the thing that does NOT vary.** Despite the driver chatter
spanning 17×, actual notes/sec sits between 13.2 and 26.3 across every family.
Driver verbosity is an implementation habit; note density is music.

Five failures, all the same cause, now spanning two games: an SPC is a
**snapshot of a running system**, so a sustained track can have all eight
voices already sounding and never be re-keyed. FF6's Grand Finale (part 1),
Strong Wind and Rumbling, plus Zelda's Unused Sound and Teleport — all 2-15
second drones or effects with `n_kon_effective` of exactly 0. The notes model
cannot represent them, and that is a property of the track.

Three failures, all in FF6, all the same thing: an SPC is a **snapshot of a
running system**, so a sustained track can have all eight voices already
sounding and never be re-keyed. Grand Finale (part 1), Strong Wind and
Rumbling are drones of 9-23 seconds with KON written 12,307 times and a zero
mask every time. The notes model cannot represent them; `n_kon_effective`
makes the record say which case it is.

Short tracks are NOT a problem -- DKC's 1-second "Extra Life Balloon"
extracted 23 notes cleanly. Length was never the issue; being a drone was.

**Render length must come from the track.** A flat 60-second window truncated
68 of FF6's 82 tracks and captured 8.8% of the 683-second "Dancing Mad
(Full)". Reading ID666's "seconds to play" took the corpus from 60,242 notes
to 149,512 for the same 82 files, and nothing in the output had flagged the
shortfall.

**Splits, resolved by corpus size rather than by weakening the rule.** With
two games there were two components and `test` was empty. Five games give five
components and train/valid/test of 168/35/29 (72.4% / 15.1% / 12.5%) against a
requested 80/10/10 -- coarse, because whole games are indivisible, and
honestly reported as `fraction_error`. No composer spans a split.

### Corpus expansion before milestone 4

Four games added: **Chrono Trigger, Earthbound, Super Mario World, Super
Metroid.** 232 tracks → **634**, 23,895 rendered seconds → 51,209.

**Every one extracted, and still zero unhandled registers in any game.** That
is the milestone 2 claim surviving a 2.7× corpus and four more drivers, which
is the thing this expansion was for.

| game | driver | trk | pass | notes | notes/s | KON *writes*/s | effective | voices | pitched | octave-suspect |
|---|---|---|---|---|---|---|---|---|---|---|
| Final Fantasy VI | AKAO (Square) | 82 | 79 | 149,512 | 13.4 | 204.5 | 2.7% | 7.3 | 80.4% | 5.8% |
| Zelda: A Link to the Past | N-SPC (Nintendo) | 50 | 48 | 36,507 | 13.2 | 364.9 | 1.6% | 5.4 | 87.8% | 14.5% |
| Super Castlevania IV | Konami | 36 | 36 | 55,823 | 14.1 | 249.6 | 2.9% | 6.1 | 94.6% | 15.3% |
| Mega Man X | Capcom | 35 | 35 | 57,612 | 26.3 | 62.5 | 16.7% | 7.9 | 71.1% | 9.8% |
| Donkey Kong Country | Rare | 29 | 29 | 80,367 | 21.0 | 21.0 | **100.0%** | 7.4 | 86.2% | 5.3% |
| **Chrono Trigger** | AKAO (Square) | 92 | 86 | 117,153 | 13.5 | 190.0 | 2.9% | 6.4 | 72.0% | 12.2% |
| **Earthbound** | N-SPC derivative (Ape/HAL) | 206 | 204 | 155,212 | 13.8 | 307.3 | 2.1% | 6.7 | 85.4% | 13.5% |
| **Super Mario World** | N-SPC (Nintendo) | 66 | 62 | 70,142 | 21.7 | 90.7 | 10.5% | 5.6 | 80.4% | 14.5% |
| **Super Metroid** | Nintendo R&D1 | 38 | 36 | 28,439 | **7.0** | **471.1** | **0.8%** | 5.3 | 90.6% | **0.7%** |
| | | **634** | **615** | **750,767** | 14.7 | 231.2 | 3.2% | 6.5 | 81.8% | 10.4% |

Driver attribution is by published knowledge of each game, not detected by the
extractor; the numbers either side of it are measured.

**The note-density claim is now wrong and worth correcting rather than
quietly dropping.** Milestone 2 concluded that "note density is the thing that
does NOT vary... between 13.2 and 26.3 across every family", on five games.
Super Metroid comes in at **7.0 notes/s — half the old floor** — so the range
is 7.0 to 26.3 and the generalisation does not hold. The music is the
explanation: Super Metroid is sparse and atmospheric by design. Which is the
point. Note density tracks *idiom*, not driver verbosity, and five games were
not enough to see an idiom that far from the others.

**Super Metroid is also the new chatter record, and the cleanest pitch.** 471.1
KON writes/s at 0.8% effective beats Zelda's 364.9 at 1.6%, so the spread in
how much register activity means anything is now 125× rather than 62×. And its
octave-suspect rate is **0.7%**, against 15.3% for Castlevania — twenty times
better than the worst, on the chattiest driver in the corpus. Write rate
predicts neither note density nor pitch quality.

**Splits got better, which is the one thing corpus size reliably buys.** 7
components, train/valid/test 496/67/71 = **78.2 / 10.6 / 11.2%** against a
requested 80/10/10. Fraction error fell from −7.6/+5.1/+2.5 points to
**−1.8/+0.6/+1.2**. Still composer-disjoint with no leaks.

**Two composers merged four games into two components**, exactly as the warning
below predicts: Nobuo Uematsu links Final Fantasy VI and Chrono Trigger (174
tracks), Koji Kondo links Zelda and Super Mario World (116). So nine games give
seven components, not nine, and the two largest are 206 (Earthbound alone) and
174. Adding another Square or Nintendo title buys corpus but not split
granularity.

**What the splits do NOT guarantee, and a reader would assume they do.** They
are composer-disjoint; they are not driver-balanced. The assignment put every
AKAO and every N-SPC-family track in **train**, leaving valid = {DKC, Super
Metroid} and test = {Mega Man X, Castlevania IV}. So two of the five driver
families appear in training only. Nothing is wrong with the splitter — a
property it never promised — but any milestone 4+ result measured on valid or
test is measured on Rare, Nintendo R&D1, Capcom and Konami, and never on the
two families that supply 70% of the notes. Worth knowing before grid inference
is tuned.

**Earthbound makes the composer tag a real problem rather than a noted one.**
All **206** of its tracks carry a truncated credit — `Akio Ohmori, Ritsuo
Kamimura, Ke` fills the 32-byte field with no terminator — so a third
contributor is unrecoverable on 32.5% of the corpus. Truncated tracks went from
1 to 207. Disjointness still passes, but for Earthbound it passes on the names
that happened to fit, which is precisely the technicality the milestone 2 note
warns about. If the hidden credit is shared with another game in the corpus,
nothing here would detect it.

**Failures: 19 of 634 (3.0%), up from 5 of 232 (2.2%), and 17 are the same
known cause** — an SPC is a snapshot, so a track already sounding and never
re-keyed has `n_kon_effective` of 0 and the notes model cannot represent it.
Chrono Trigger contributes 6 (Time Vortex, Strong Wind, Blackbird (Outside),
Ozzie Scream, plus Rain and Flowing Water and Fall of Zeal with 1-2 notes),
Earthbound 2 (Ambush!, Giygas' Static), Super Mario World 3, Super Metroid 2.
Every one is a drone, a jingle or an effect.

**One genuinely new failure mode.** `writes_span_render` fired for the first
time, on Super Mario World's *Nintendo Logo* and *Peach's Item*: writes span
0.402 s of a 1 s render and 0.968 s of a 2 s render. Both are sub-second
jingles whose ID666 length rounds up to a whole second, so the check's
expectation that register writes cover the window is simply wrong for them. The
extraction is correct and the check is mis-scoped for tracks shorter than its
resolution — a threshold question, not a bug, and the first time the corpus has
contained anything short enough to ask it.

**Pitch got slightly worse, as an unresolved octave problem should.** 81.8%
pitched (was 83%) and 10.4% of pitched notes outside MIDI 12-108 (was 8.7%),
over 2,466 of 3,105 per-track sample slots yielding a fundamental (79.4%).
Chrono Trigger at 72.0% pitched now ties Mega Man X for the worst coverage.
Milestone 3 stays partial, and the extra data moved it the wrong way rather
than averaging the problem out.

### Why a game is the unit of assignment, not a composer

Composer-disjointness alone would permit splitting one game across splits:
DKC's Dave Wise (21 tracks), Eveline Fischer (7) and Robin Beanland (1) could
go to three different splits without any composer spanning two. That would
make the ratios much easier to hit.

It is not done, because a game's tracks share an instrument bank, a driver and
an idiom, so splitting a game across splits leaks far more than a composer
does. Whole game components are the stricter choice and the ratios pay for it.
The consequence to accept: you need at least as many composer-disjoint game
components as you want splits, so three splits need three such groups. Adding
a game is cheap; weakening the guarantee is not.

## 3. Absolute pitch

The PITCH register is a resample ratio, not a frequency, and the base
frequency lives in the game's private instrument table. So recover it from the
sample instead: decode each BRR sample out of the ARAM dump and estimate its
fundamental directly.

    note = f0_sample · PITCH / 4096

- percussion and noise fail f0 estimation and must be labelled unpitched
  rather than given a confident wrong number
- emit a per-sample confidence, so downstream work can filter

**Exit: partially met.** On the nine-game corpus, 614,474 of 750,767 notes
(81.8%) carry a note number, and 2,466 of 3,105 per-track sample slots (79.4%)
yield a usable fundamental, the rest being percussion and noise as expected.
But **10.4% of pitched notes land outside MIDI 12-108**, which is the signature
of a residual octave error: two estimators can agree and both still be an
octave out. Treat `midi_note` as usable in bulk and unreliable per note;
`pitch_confidence` is on every note.

Per game the octave-suspect rate runs from **0.7% (Super Metroid) to 15.3%
(Super Castlevania IV)** — a 22× spread that the five-game corpus understated
as 5.3-15.3%. On the five original games it was 83% pitched and 8.7% suspect;
adding four games moved both the wrong way, so the problem is not averaging
out with scale.

### What this milestone actually established

**Autocorrelation on a BRR loop is weak, and my first implementation was
broken.** It read a pure 440 Hz sine as 477.6 Hz -- 142 cents sharp -- because
it took the first lag crossing a threshold, which lands on the rising flank of
the first peak rather than its apex. Picking the first local maximum with
parabolic interpolation brought synthetic tones to within 2.4 cents across
110-1760 Hz, and real samples from one usable estimate in five to 75%.

**A semitone-grid fit looked like the answer and was deleted.** Since a voice
plays equal-tempered notes, the f0 that puts `f0 * PITCH / 4096` on semitones
for every note using that sample should be the right one -- a one-parameter fit
over real data rather than a guess from a short loop. It improved apparent
accuracy from 5-40 cents to 0.1-0.4 cents.

A control with a RANDOM coarse f0 fit equally well: 0.13 to 0.29 cents. The
reason is structural -- a driver computes PITCH as `base * 2**(n/12)`, so one
sample's PITCH values are ALREADY a semitone ladder among themselves. Any f0
maps that ladder onto a grid; only the offset moves. The fit measured the
driver's internal consistency, which is always there, and said nothing about
the fundamental. `pitch.py` carries the full note so it is not reinvented.

**Relative pitch is exact for some drivers and not others.** Median deviation
from an exact semitone ladder, per sample: Rare 0.30 cents (96% of samples
under 5 cents), Square 0.48 (91%), Nintendo N-SPC 2.87 (65%), Konami 3.39
(69%), **Capcom 10.67 (19%)**. So the design doc's fallback -- "PITCH ratios
are already exact, so dropping absolute pitch loses absolute key and nothing
else" -- holds for Rare and Square and does NOT hold for Capcom. That was
worth learning before relying on it.

Pitch write rate does not explain it: Zelda rewrites PITCH 48.8 times per note
and has a cleaner ladder than Mega Man X at 6.5. Heavy pitch modulation is
universal; whether the key-on value sits on the grid is not.

**Also found:** a 512-block decode cap silently truncated real samples. Final
Fantasy VI has one of 1,046 blocks, and the truncated decode produced a
fundamental that landed exactly on the estimator's 4 kHz clamp while being
reported as high confidence.

**The shortcut, if this stalls:** skip it. PITCH *ratios* are already exact, so
interval-level and transposition-invariant work needs nothing from this
milestone. Dropping it loses absolute key and nothing else.

## 4. Grid inference

Histogram key-on inter-onset intervals; the driver's tick period falls out as
the dominant spacing. Driver-agnostic, and the NES equivalent already exists
in the renderer (`detect_pulse`) to copy from.

With pitch (3) and grid (4) in hand, the **separated** and **blended** scores
are expressible — they need no timbre.

**Exit:** a tempo and row grid per track with a goodness-of-fit measure, and
the two timbre-free score formats emitted.

### Exit: met for the scores, and the premise above is wrong

**866 of 1,316 tracks (65.8%) carry a row grid** with a fit measure, median fit
0.96 and a median timing residual of 2.5% of a row, and **both score formats
are emitted** for every one of them. That is the exit criterion.

**But the sentence this milestone was planned around does not hold on this
hardware.** "The driver's tick period falls out as the dominant spacing of
key-ons" is true on the NES because music there advances on a universal
60.0988 Hz frame, so onsets and frames coincide. Measured here:

| | onset grid | real tick | out by |
|---|---|---|---|
| Zelda: A Link to the Past | 5.4 rows/s | 62.5 Hz | **11.6×** |
| Final Fantasy VI | 11.0 rows/s | 205.4 Hz | **18.7×** |
| Donkey Kong Country | 80.0 rows/s | 80.1 Hz | 1.00× |

Only DKC agrees, and for a reason the corpus already recorded: Rare's driver
writes KON only when it means a note, at 100% effective, so its music
exercises every tick. Every other driver keys on far more sparsely than it
ticks, and what the onset histogram then recovers is the music's own
phrasing — a perfectly real grid, but not the hardware's.

So two quantities are now reported, separately, each with its own confidence,
because conflating them is what produced the error above.

### The tick is in the write cadence, not the key-ons

A driver runs its music engine on a timer and writes a **burst of registers**
every time that timer fires, whether or not a note starts. That cadence is one
to two orders of magnitude denser than the key-ons, and it carries the timer
directly. The clean modes over 1,316 tracks:

| ticks | tracks | Hz | driver |
|---|---|---|---|
| 4,992 | 58 | 205.1 | AKAO — Final Fantasy VI |
| 5,376 | 48 | 190.5 | AKAO — Chrono Trigger |
| **16,384 = 2¹⁴** | 60 | **62.5** | Capcom — Mega Man X, Breath of Fire II |
| 12,800 | 38 | 80.0 | Rare — DKC, DKC2, Plok! |
| 4,609 | 15 | 222.2 | AKAO — Secret of Mana |

2¹⁴ ticks for 62.5 Hz is the kind of number a driver author actually writes.

**The honest validator is not the confidence score, it is whether every track
in a game reports the same tick** — a timer is a property of the driver, not
of the song. By that test:

| trustworthy | tracks | Hz | distinct values |
|---|---|---|---|
| Final Fantasy VI | 59/82 | 205.1 | **1** |
| Mega Man X | 34/35 | 62.5 | **1** |
| Breath of Fire II | 44/56 | 62.5 | 2 |
| Chrono Trigger | 58/92 | 190.5 | 3 |
| Donkey Kong Country | 10/29 | 80.0 | 4 |

| not trustworthy | tracks | Hz | distinct values |
|---|---|---|---|
| Tales of Phantasia | 52/77 | 39.6 | **36 — every track differs** |
| Star Ocean | 54/66 | 46.5 | **32** |
| Lufia II | 38/63 | 88.9 | 15 |
| DKC2 | 64/109 | 80.0 | 15 (while DKC itself gives 4) |

**519 of 1,316 tracks (39.4%) report a tick, and it is believable for four or
five of twenty-two drivers.** That is the state, and it is why this milestone
is partial rather than done.

**One artifact, named so it can be fixed.** Twenty tracks across six unrelated
games report exactly 2,048 ticks (500 Hz) — and 19 of those 20 came from the
narrowest burst window, 64 ticks. 2,048 is not a timer; it is the spacing of
writes *within* one burst, picked up as if it were the cadence. Six different
drivers do not share a 500 Hz rate. That is the first thing to look at.

### Three bugs, two of which only real data could show

**A chord is not simultaneous in the write log.** Drivers key-on a chord's
voices one after another — DKC staggers them 471 to 1,200 ticks apart — so an
eight-voice chord contributes seven tiny intervals and one musical one and the
histogram is swamped 7:1 by the driver's write order. DKC's *Theme* gave 3,201
notes, 3,201 distinct onset times and a commonest interval of 631 ticks: 1,600
rows a second, which is not a tempo. Clustering onsets first took DKC from
16/29 grids to 28/29. The clustering window is chosen per track from an
ascending ladder so no track is collapsed more than its data requires.

**Maximum polyphony of nine, on eight-voice hardware.** Two causes. A note
still sounding when the render window closes has `end: null`, and reading that
as "sounds to the end of the track" made it overlap every later note on its own
voice. And the blended score was accumulated alongside the separated grid
rather than derived from it, so one voice could contribute two numbers to one
row. Blended is now derived from separated, which makes more than eight
arithmetically impossible, and collisions are counted rather than hidden.

**A split burst passes as the tick, perfectly.** A burst window narrower than
the spacing *within* a burst makes every write its own burst, so the only
surviving gap is from the last write of one burst to the first of the next —
the period minus the burst span. It is exactly regular, so the burst-gap
statistic scored it 1.0 and read a 4,993-tick timer as 4,393. Replaced with the
circular concentration of write phases over all write times, which no choice of
window can flatter: a period wrong by one per cent makes the phase precess and
the statistic collapse.

### Two limits that are properties of the problem, not of the code

**A sub-multiple can be indistinguishable from the tick.** When a driver
spreads its writes evenly across its tick — three writes 1,500 ticks apart
inside a 6,000-tick timer — both periods put every write at the same phase, and
no statistic over write times alone separates them. The module reports the
sub-multiple, and a consumer reading four times the true rate for such a driver
is reading the data correctly.

**The confidence threshold is bounded by the driver's write style.** Writes
spread uniformly across a fraction *f* of the period give a concentration of
sinc(π*f*), so a driver whose burst occupies 60% of its tick cannot exceed 0.50
however real its timer is. The threshold is 0.25 for that reason rather than by
preference, which admits bursts up to about 75% of a tick. Confidence here
measures *regularity*, not correctness: DKC's 80.0 Hz is right and scores 0.88,
while Mega Man X's equally right 62.5 Hz scores 0.36.

### The two scores

**separated** — one row-indexed track per DSP voice, cells holding a MIDI note
or 0. The analogue of NES-MDB's `sepsco`, with the honest caveat that on the
NES track 0 is always pulse 1, whereas here voice 0 is whatever the driver
assigned it to. Voice *role* is milestone 5.

**blended** — one row-indexed list of the distinct notes sounding, voice
identity discarded. NES-MDB's `blndsco`, and immune to the voice-assignment
problem above, which makes it the more comparable of the two today.

Over 866 tracks: **1,926,961 rows, 849,956 notes placed**, maximum polyphony 8.
What the formats cannot say is counted rather than dropped: **211,375 unpitched
notes** (percussion, noise, or no recoverable fundamental), **1,589 pitches
outside MIDI 1–127** (octave errors showing through), **32 unplaceable**, and
**109,055 snapped** — notes shorter than one row, whose onset the grid moved.

**That last number is the score-quality figure and it is driver-dependent**:
2.2% for Plok!, 3.9% for DKC, against **32.4% for Kirby Super Star**, 21.8% for
Final Fantasy VI and 21.6% for Secret of Mana. A grid that moves one onset in
three is describing the music coarsely, and the games where it happens are
exactly the ones whose onset grid is far from their tick. Snapping and the
onset/tick gap are the same problem seen twice.

Where both were found and snapping did not worsen the fit, **114 row grids were
rounded to a whole number of driver ticks**; 50 of those came out at exactly
one tick per row.

### What the corpus looks like now

**1,316 tracks, 22 games, 1,863,499 notes, 109,263 rendered seconds, and still
zero unhandled DSP registers in any game** — the driver-agnostic claim holding
across twelve more families than it was first tested on, including Chunsoft,
HAL, tri-Ace, Namco and Factor 5. 1,292 of 1,316 pass every structural check.

**The splits are now effectively exact.** 16 components, train/valid/test
1,049/135/132 = **79.71 / 10.26 / 10.03%** against a requested 80/10/10 —
fraction error **−0.29 / +0.26 / +0.03 points**, from −7.6/+5.1/+2.5 at five
games. Composer-disjoint, no leaks. This is what corpus size buys, and it is
the one thing it reliably buys.

Truncated composer credits are at **242 of 1,316 (18.4%)**, down as a share
from 28.5% at twelve games but still concentrated in Earthbound's 206.

## 5. Timbre vocabulary — the research problem

`exprsco`'s timbre axis is a duty index in `{0,1,2,3}`: a closed, four-value
alphabet meaning the same thing in all 397 NES games. The SNES equivalent is
"BRR sample #N in this game's ARAM" — an open vocabulary, arbitrary per game,
with no cross-game meaning. **There is no alphabet to inherit, so it has to be
built.**

- decode every BRR sample in the corpus
- extract spectral and temporal features (centroid, harmonicity, attack time,
  loop presence, length)
- cluster into a fixed codebook of N classes, and emit the cluster id as the
  timbre axis

This also subsumes voice-role assignment: once samples are classified, a
voice's role follows from the class it is playing, which replaces the 2A03's
fixed channel semantics.

**Exit:** a codebook, a stated N with the reasoning for it, per-sample
assignments, and a sanity check that the same instrument in different games
lands in the same class. That last check is the real test and the thing most
likely to fail.

**Why this is high risk:** it is a clustering problem with no ground truth, and
"strings in Final Fantasy VI and strings in Chrono Trigger are the same class"
is a claim that has to be demonstrated, not assumed.

### Exit: not met, and the check is why

The deliverables exist. A codebook of **k=5** over **1,162 distinct samples
from 22 games**, chosen by sweep with its reasoning recorded, per-sample
assignments emitted, silhouette 0.24. What does not hold is the sanity check,
and that check was always the milestone.

**How it was tested without labels.** Nobody has labelled these samples, so the
evidence comes from independence instead. The codebook is fitted only on
features intrinsic to the decoded waveform — length, loop structure, attack,
spectral centroid, spread, rolloff, flatness. The check uses only how the
corpus *plays* each sample — the register, the note length, whether it is ever
pitched at all. The fit never sees the second set. Each test is run again
against shuffled labels, because a partition of a correlated feature space will
always separate *something*.

| test | axis | real | shuffled null | verdict |
|---|---|---|---|---|
| 1. separates usage? | unpitched fraction | **63.3** | 0.06 | strong |
| | median register | **10.7** | 0.90 | modest |
| | note duration | 0.75 | 0.85 | **no signal** |
| 2. same meaning across games? *(lower better)* | median register | 0.526 | 0.554 | **at the null** |
| | note duration | 0.255 | 0.328 | marginal |
| | unpitched fraction | 0.509 | 0.552 | **at the null** |
| 3. held-out games | unpitched fraction | **0.0 SD** | — | transfers |
| | note duration | 0.202 SD | — | transfers |
| | median register | **0.437 SD** | — | does not |

**Test 2 is the exit criterion and it comes out at the shuffled null.** A class
does not mean the same thing from game to game by more than a few per cent over
chance on any axis. The finer structure of the codebook describes each game's
own sample bank, which is what the design doc feared in as many words.

**Test 3 shows precisely what does and does not carry.** Fitted on the 16
composer-disjoint train games and applied to 6 unseen ones:

| class | train (16 games) | held out (6 games) |
|---|---|---|
| 0 | MIDI 91.1, unpitched 0.0 | MIDI 85.1, unpitched 0.0 |
| 1 | — , unpitched **1.0** | — , unpitched **1.0** |
| 2 | MIDI 77.5, unpitched 0.0 | MIDI **61.2**, unpitched 0.0 |
| 4 | MIDI 72.9, unpitched 0.0 | MIDI 67.5, unpitched 0.0 |

The pitched/unpitched division transfers exactly. Register does not: class 2
moves **sixteen semitones** between the games the codebook was built from and
games it had never seen. So spectral features recover *tonal versus
percussive*, across games, reliably — and that is a **two-value alphabet**, not
the open instrument vocabulary the milestone set out to build.

**What is defensible to publish**, therefore: a binary `tonal | percussive`
timbre axis, validated on held-out games against a null. **What is not**: a
5-class instrument codebook presented as cross-game meaningful.

### A circular result, caught by its own null

The first run reported separation of **426 against a null of 0.18** and a
perfect 0.0 SD transfer, which looked like a decisive pass. It was leakage:
`pitched` and `harmonicity` were in the clustering vector, and both depend on
whether an f0 was recoverable — the same quantity the usage half measures as
`unpitched_fraction`, since a note receives a MIDI number only when its
sample's f0 estimate was usable. The answer was on both sides of the
validation. Removing those two axes took separation from 426 to 63 and the
cross-game agreement from "clearly better than null" to "at the null".

This is the second time on this project that a result survived three rounds of
looking right and was killed by a control — the first was milestone 3's
semitone-grid fit, which a random coarse f0 fitted equally well. The pattern is
the same both times: a quantity derived from the data appearing on both sides
of its own test.

### Note duration has no signal at all, and that is a real finding

0.75 against a null of 0.85: the waveform does not predict how long notes made
with it last, in the corpus or out of it. Note length is a composition choice,
not a property of the sample — which is worth knowing before any further work
tries to derive phrasing from instrument identity.

### What this costs the roadmap

`exprsco`, the third score format, needs a timbre axis. A binary one is
available and honest; a 5-class one is not supported by the evidence. So
milestone 6 can ship **three** score formats if `expressive` uses the validated
binary axis, with the limitation stated — or two, if an open vocabulary is held
to be the requirement.

Voice-role assignment, which this milestone was supposed to subsume, does not
follow: a role needs register and function, and register is exactly what fails
to transfer.

## 6. Publish

- 8-track MIDI (note: VGMTrans already does per-driver SPC→MIDI well; this
  exists for corpus uniformity, not because it is novel)
- all three score formats
- intake JSON trees, consumed by the renderer via `acquire(from_extracted=True)`
- the splits, the manifest, and documentation of what the corpus is derived
  from

**Exit:** a corpus another person could use, with its provenance and its
limitations written down.

---

## What this does not promise

The published artifact is a **dataset and the tools to rebuild it**, not a
model. Training a generative model on it is out of scope here, and worth
knowing why: on the NES side, a clean retrain that improved validation loss by
11.4% produced output a listener called "barely music". Next-token loss does
not measure music. A SNES corpus does not change that argument — it is worth
building for analysis, comparison, and as a public artifact, and those are the
reasons to build it.
