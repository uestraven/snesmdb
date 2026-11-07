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
| 3 | Absolute pitch | ✅ done — **78.3% pitched** (1,458,211 of 1,863,499 notes) | medium |
| 4 | Row clock | ✅ done — **all 1,316 tracks**, read from the SPC700 timer register | low |
| 5 | Timbre vocabulary | ❌ **exit criterion not met** — a transferable 2-class split, not an instrument vocabulary | **high — and it was the risk named** |
| 6 | Publish | ✅ done — **[DATASET.md](DATASET.md)**, three scores, MIDI, intake, splits | low |

Milestone 4 was originally "grid inference" and its exit criterion was a
fitted tempo grid per track. That criterion was met for 866 tracks and then
**abandoned as the wrong target**: the row unit is a hardware timer the SPC
file states outright, not something to infer from onsets. The inferred onset
grid is still computed and published as provenance, because the onset period
is a real and separate musical measurement -- it just indexes nothing. See
"The timer is stored in the SPC file" below.

Two figures in this table moved after the voice-state seeding fix and are
worth not confusing. Pitched coverage went 78.7% to 78.3%, slightly DOWN,
because some newly-correct samples fail the f0 plausibility test that the
wrong ones passed. And the old "1.78% octave-suspect" counted a different
thing from today's 42.83% of sample estimates carrying a non-zero
`octave_shift`: the first was a residual-error estimate, the second is how
often the resolver applied a correction. They are not comparable and the
second is not a regression.

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

### The octave error, resolved against the spectrum

**Out-of-range pitched notes fell from 9.1% to 1.78%**, and the count the score
formats had to discard went from 1,589 to **78** on the same corpus.

The ambiguity entered at one line. Both estimators are ambiguous by factors of
two — autocorrelation can latch onto twice the period, and `nearest =
round(periods)` in the loop refinement preserves whatever octave the
autocorrelation handed it. Neither can see its own error.

The spectrum can: **a fundamental an octave too low carries almost no energy at
its own first harmonic.** Summed magnitude at f0 and its first six harmonics,
evaluated at exact frequencies by single-bin DFT rather than quantised into a
transform's bins, peaks at the true fundamental — an octave low misses every
odd harmonic, an octave high misses the fundamental itself.

| over 179,763 notes | outside MIDI 12-108 |
|---|---|
| before | 9.11% |
| after | **1.96%** |
| **control: a random octave shift** | **16.42%** |

The control is what makes the result mean anything, and this project has twice
shipped a measurement that only a control exposed. Two further pieces of
evidence, neither of which is the in-range metric: the chosen shifts
concentrate at **−1 octave (328 of 356)**, matching the estimator's known
failure mode rather than spreading as fitted values would; and the span of
simultaneously sounding pitches tightens from **34.1 to 29.8 semitones** while
the random control widens it to 41.5.

**This is not the semitone-grid fit deleted below.** That tried to recover f0 to
cent precision from PITCH values which are already a semitone ladder among
themselves, so any f0 fitted and a random one fitted equally well. This
resolves one bit per octave from the spectrum, and is checked against a
control that fails.

Honest limits: 237 samples already fully in range were also moved, and the
in-range metric cannot adjudicate those — the harmonic-energy margin on moves
is median 2.43× with 77% clearing 1.5×, so about a quarter are marginal. The
check also roughly doubles extraction time. `octave_shift` and `octave_margin`
ride on every estimate.

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

### Why a third of tracks have no grid: they have more than one

The 450 tracks without a grid are not a threshold problem, and that was worth
establishing before touching the threshold. 58 are legitimately too sparse. For
the other 378 a dense sweep over 701 log-spaced periods finds **median best fit
0.449 — worse than the 0.655 the pipeline already achieves**, and only 2 of 60
sampled tracks clear 0.80 even then. No single period fits their onsets, so
lowering the bar would emit grids that do not describe the music.

**They are multi-section pieces.** The listener's description of Final Fantasy
VI's "Dancing Mad (Full)" — a classical work whose sections are completely
different from one another — is directly testable, and recursive splitting
finds section structure:

| section | onsets | fit |
|---|---|---|
| whole track | 4,480 | **0.39** |
| 0–245 s | 896 | 0.68 |
| 245–446 s | 806 | 0.77 |
| 446–683 s | 1,077 | **0.82 — clears the bar, 17.0 rows/s** |

Boundaries at 245 s and 446 s of a 683-second piece, with the fit rising toward
each section rather than the whole. The other tracks in this population are the
same shape: the longest gridless tracks are "Ending Theme (part 1)" and
"(part 2)", "Thank You, Everyone", "Vows of Marriage" — endings, medleys and
multi-movement set pieces. A single tempo was never going to describe them.

So the honest statement of the milestone's shortfall changes. It is not "the
grid fails on a third of tracks"; it is **"a third of tracks have no single
grid, because they have several, and only one grid per track is emitted."**

### Section count is not movement count, and the boundaries were partly mine

The piece has **four** movements, one per tier of the final battle, each
carrying its own motifs — "Omen" and "Catastrophe" in the first, the "Kefka"
theme in the third, the opening material returning in the fourth. Recursive
splitting found three sections, and it would have been wrong to present that as
three of four found.

A sliding 60-second window, stepped 15 seconds, says why. It reports three
*regimes* rather than four sections:

| | fit | grid recovered |
|---|---|---|
| 0–135 s | 0.65–0.84 | partly — 26.0 and 12.6 rows/s |
| **135–465 s** | **0.29–0.78** | **none, in any window** |
| 465–630 s | 0.79–**1.00** | yes — 17.0 and 5.7 rows/s |

And four of the six boundaries that detector flagged are an artifact of this
code rather than events in the music: **17.0 / 5.7 = 2.98**, so it is switching
between describing the same passage as beats and as triplets. That is the
subdivision guard changing its mind window to window, and it would have been
read as a tempo change by anything keying off period jumps.

**The distinction to keep.** A movement boundary is thematic; a grid boundary
is metric. Four movements can share a tempo, and one movement can change tempo
inside itself, so the two counts need not agree and neither validates the
other. What a grid estimator can honestly claim is where the music admits a
single period, and for this piece that is: the opening partly, the long middle
not at all, the finale almost perfectly.

The useful consequence for a piecewise grid is that it would recover **part** of
such a track rather than all of it. The finale reaches fit 1.00 and would score
cleanly; the 330-second middle resists a grid even in one-minute windows, and
would still be reported as having none.

### What closing this properly needs, and why it is not done here

A piecewise grid — a period per section, with the row sequence continuing
across section boundaries exactly as a tracker handles a tempo change. The
segmentation itself works. What blocks it is cost: `infer` is
O(candidates × onsets) with a hill-climb per candidate, so one call on
"Dancing Mad" takes about ten seconds and segmentation needs tens of calls per
track.

Two attempts to make it cheap were reverted because both changed answers.
Ranking candidates on a regular onset subsample took "Dancing Mad" from fit
0.394 to 0.193, because a coarse period fits a sparse subsample better and the
coarsest-wins guard then selects it. Shortlisting on the subsample and deciding
on the full data still moved 2 of 11 spot-checked tracks, including
"Gang-Plank Galleon" from 0.9992 to 0.915 — a regression on a track that was
already correct, which is worse than being slow.

### Why the obvious speed-ups all fail: the hill-climb is doing search

Three attempts, all reverted, and the third explains the first two.

**Subsampling the onsets for ranking** took "Dancing Mad" from fit 0.394 to
0.193. A coarse period fits a sparse subsample better, and the coarsest-wins
guard then selects it.

**Shortlisting on a subsample and deciding on full data** still moved 2 of 11
spot-checked tracks, including "Gang-Plank Galleon" from 0.9992 to 0.915 — a
regression on a track that was already correct.

**Replacing the hill-climb with a closed-form least-squares period fit** looked
like the clean answer: assign each onset to a grid index and the optimal period
is ordinary least squares of time on index, which is exact and converges in
about four passes instead of thirty-two. It made **47 of 68 spot-checked tracks
worse and lost 13 grids**. Restricting the regression to on-grid onsets only —
on the theory that the measure counts inliers while least squares is dominated
by outliers — changed nothing: 46 of 68.

The reason is the one that matters. `_refine` already refuses any period
scoring worse than the candidate it started from, so it cannot regress on its
own input. The losses come from the hill-climb reaching periods the candidate
generator never proposed: stepping outward and halving is a **local search**,
and on most tracks it walks to a better optimum than any seeded candidate.
Those thirty-two scoring passes are not polishing a known answer, they are
finding a different one, and the fit depends on it.

So "refine more cleverly" is the wrong shape of fix. What would work is
attacking the other factor — either **better candidate generation**, so the
search starts near the answer and needs fewer steps, or a formulation that
evaluates every period at once, which an **FFT-based periodogram** over the
onset train does. The second is the real answer and it is a different
algorithm, not an optimisation.

Bounded, but not a small change, and the corpus is usable without it: both
timbre-free scores and the MIDI exist for every track that has a single grid,
and MIDI exists for every track with a pitched note regardless.

### Legato note successions: notes with no key-on, and how many there are

A voice can be given a new note without a KON edge — the driver just writes a
new PITCH. To the DSP a pitch bend, a vibrato cycle, a legato step and a new
note are the same thing: a write to `$x2`/`$x3`. The extractor only creates a
note on a KON write, so any note delivered this way is merged into its
predecessor.

Three candidate boundary rules were tested against write logs. Two of them do
not occur in this corpus at all, which is worth recording so they are not
re-proposed:

**A mid-voice SRCN change never happens.** It would be the ideal splitter — a
driver has no reason to swap the sample on a live voice except to start
something new, so it carries no risk of inventing a note. Measured across 12
tracks spanning seven drivers, including five of the drone tracks: **zero
occurrences**. The rule is sound and useless here.

**The drone tracks contain nothing to recover.** All 17 have no effective
key-on, and the obvious hope is that they are legato-driven music. They are
not. Three of five sampled have **zero pitch updates** across their whole
length, including Final Fantasy VI's "Grand Finale (part 1)" at 31,800 writes;
they are static sustained voices. "Time Vortex" has 11,889 pitch updates at a
**median of 0.031 semitones**, 76% below 0.1 — a continuous sweep, where a
half-step rule would fabricate about 1,200 notes out of an acoustic drone. The
titles say the same thing: "Giygas' Static", "Strong Wind", "Rumbling",
"Ozzie Scream", "Teleport", "Fade Out!". The `drone` class was right.

**Isolated pitch steps inside a sounding note do happen, for some drivers.**
Implemented in `voices.py` as `LegatoStep`, an independent event table keyed to
its parent note. Full corpus, with the 24-semitone ceiling applied:
**154,910 steps against 1,863,499 notes, 8.3%**, in 21 of 22 games, ranging
0.0% to 45.5%.

**That 8.3% is not a melodic figure, and the games with the highest rates are
the ones that prove it.** A driver writes PITCH for notes and for effects.
Equal temperament separates them: a note succession lands on a whole semitone,
while portamento, vibrato and pitch effects are continuous. Per game, the share
of steps within 0.1 st of a whole semitone, against a null that jitters each
interval by +/-6%:

| game | notes | steps | rate | tempered | vs null | verdict |
|---|---|---|---|---|---|---|
| Super Turrican | 38,440 | 4,162 | 10.8% | 99.2% | **2.38x** | melodic |
| Batman Returns | 44,849 | 1,334 | 3.0% | 83.7% | 1.91x | melodic |
| Super Castlevania 4 | 55,823 | 3,771 | 6.8% | 94.7% | 1.75x | melodic |
| Plok! | 66,687 | 12,005 | 18.0% | 78.5% | 1.54x | melodic |
| Breath of Fire 2 | 58,186 | 3,191 | 5.5% | 82.8% | 1.42x | melodic |
| Lufia 2 | 88,644 | 76 | 0.1% | 5.3% | 1.33x | melodic |
| Dragon Quest 5 | 40,014 | 121 | 0.3% | 91.7% | 1.31x | melodic |
| Chrono Trigger | 117,153 | 4,380 | 3.7% | 33.3% | 1.25x | melodic |
| Final Fantasy 6 | 149,512 | 5,653 | 3.8% | 83.3% | 1.18x | melodic |
| Mega Man X | 57,612 | 4,197 | 7.3% | 74.0% | 1.16x | melodic |
| Secret of Mana | 122,553 | 632 | 0.5% | 23.6% | 1.15x | marginal |
| **Earthbound** | 155,212 | **70,633** | **45.5%** | 17.5% | **1.02x** | **not melodic** |
| **Axelay** | 53,315 | **21,512** | **40.3%** | 18.9% | **0.98x** | **not melodic** |
| Star Ocean | 127,948 | 2,987 | 2.3% | 21.4% | 1.01x | not melodic |
| Kirby Super Star | 136,308 | 5,065 | 3.7% | 15.8% | 0.98x | not melodic |
| Donkey Kong Country | 80,367 | 5,931 | 7.4% | 15.1% | 0.94x | not melodic |
| Donkey Kong Country 2 | 124,003 | 6,022 | 4.9% | 8.3% | 0.92x | not melodic |
| Tales of Phantasia | 187,629 | 1,389 | 0.7% | 14.8% | 0.98x | not melodic |
| Super Mario World | 70,142 | 1,529 | 2.2% | 3.5% | 1.06x | not melodic |
| Super Metroid | 28,439 | 0 | 0.0% | — | — | no steps |

Earthbound (70,633) and Axelay (21,512) hold **59% of all steps in the corpus**
and neither is melodic: those drivers use PITCH for continuous modulation, so
their steps are real register events that are not notes. **Restricted to games
whose steps pass the test, the rate is 2.1% of notes, not 8.3%** -- and the
honest headline is the smaller number.

Two caveats on the table itself. The 1.10x cutoff is mine, not derived, and two
games sit close enough to it to flip: Super Mario World read melodic at 1.15x
on the pre-ceiling data and 1.06x after, Secret of Mana moved the other way.
For those two the verdict is a coin-toss on an arbitrary threshold. And the
test is a POPULATION statistic -- a single interval sits near a whole semitone
20-30% of the time by chance -- so nothing is filtered on it and no individual
step is labelled.

**Why a separate table rather than more notes.** `notes` stays bound strictly
to KON edges, so every entry remains traceable to a hardware edge with its
attack velocity, SRCN and envelope intact; a step hangs off it by
`parent_note_id` and inherits the parent's sample and envelope by construction,
since it does not re-key. The split exists for bias, not tidiness: a melodic
density question wants `notes + steps`, while a voice-allocation or envelope
question wants `notes` alone, and merging them would make the second
unanswerable. Each step carries `semitones`, `run_length` and
`observed_ticks` so a consumer can re-decide rather than inherit these
thresholds.

### The timer is stored in the SPC file, and reading it beats inferring it

The 220 fixed-clock tracks -- 178 of them music, 17.7% of the music corpus,
concentrated in Super Mario World (64) and Zelda (49) -- were assumed to be an
estimator weakness. Three hypotheses were tested against write logs from 12 of
the failing tracks, and **all three were refused by the data**:

| hypothesis | signature looked for | result |
|---|---|---|
| staggered processing | multi-modal gaps hiding a consistent spacing | gaps are 36-50 clocks, which is intra-block instruction spacing, not a tick |
| clock-doubling | a clean period at 2x or 1/2x | no bounded period beat its null |
| conditional streaming | period present with skipped slots | **no** -- see below |

Conditional streaming was the strongest prior and it is wrong. Grouping writes
into blocks and fitting a periodic grid that allows missing slots, over 30-800
Hz with an ABSOLUTE tolerance of 192 clocks and an occupancy floor, gives fits
of 0.21-0.34 against nulls of 0.19-0.31. At or below chance, for the music
registers and the global registers separately. **N-SPC does not expose a
periodic tick in its DSP write stream.** The estimator is not weak here; the
information is absent, which makes the 100 Hz fallback correct behaviour rather
than a gap.

A warning about the probe, because the first two versions manufactured a
result. Using a RELATIVE tolerance of 10% and preferring the largest period
produced fits of 1.00 at 9.4 Hz -- which is the coarsest-wins artifact already
documented for `grid.py`, since +/-10% of a 108,446-tick period accepts
anything within 10 ms. Any period search needs an absolute tolerance and a
bounded range or it will find whatever it is pointed at.

**THE INFORMATION IS IN THE SPC FILE, NOT THE WRITE LOG.** The SPC700's timer
registers are part of the dump: `$F1` holds the enable bits and `$FA`, `$FB`,
`$FC` hold the T0, T1 and T2 targets. Read directly, `8000/$FA` reproduces
every clock the write-cadence estimator found, and supplies one for every game
it could not:

| game | from `$F1`/`$FA`-`$FC` | write-cadence measurement | |
|---|---|---|---|
| Chrono Trigger | T0 190.48 Hz | 190.48 Hz | agrees |
| Super Metroid | T0 500.00 Hz | 500.00 Hz | agrees |
| Final Fantasy 6 | T0 205.13 Hz | 205.13 Hz | agrees |
| Secret of Mana | T0 222.22 Hz | 222.22 Hz | agrees |
| Donkey Kong Country 1/2 | T0 80.00 Hz | 80.00 Hz | agrees |
| Earthbound, Kirby | T0 500.00 Hz | 500.00 Hz | agrees |
| Dragon Quest 5, Castlevania 4 | T0 200 / 250 Hz | same | agrees |
| **Super Mario World** | **T0 500.00 Hz** | *failed* | **supplies** |
| **Zelda** | **T0 500.00 Hz** | *failed* | **supplies** |
| Actraiser, Axelay | T0 500 / 250 Hz | *failed* | supplies |
| Lufia 2, Star Ocean, Tales of Phantasia | T1 64.00 Hz | *failed* | supplies |
| Batman Returns | T0 250 Hz | 500 Hz | **2x** |
| Breath of Fire 2, Mega Man X | T0 125 Hz | 62.5 Hz | **1/2** |
| Plok! | T2 320 Hz | 80 Hz | **1/4** |

Ten agree exactly and the four disagreements are all exact power-of-two
factors, which is the software divisor M already established for this corpus:
the register gives the HARDWARE timer rate, write cadence gives the EFFECTIVE
sequencer rate, and they differ by however many timer ticks the driver counts
per row. The two measurements corroborate rather than conflict.

T0 is enabled on **1,295 of 1,316 tracks**, so this is a per-track hardware
read with near-total coverage -- and because it is per-track it needs no
per-game consensus at all, which also handles the drivers that reprogram their
divider (Lufia 2, Star Ocean, Tales of Phantasia, Super Turrican all show a
per-track value at 33-50% modal share).

**Not yet implemented.** Switching the row clock to this source would change
the row unit for most of the corpus and needs a decision about whether rows
should sit on the hardware timer or on the effective sequencer rate -- they
differ by M, and only the second is musical. That is a design choice, not a
patch.

### Resolution: the scores are indexed on the driver's clock, and the grid is not the row unit

Everything below this heading was an attempt to make an *inferred* row grid
good enough to index scores on. The attempt was answering the wrong question,
and one query settled it: across 664 tracks the grid produced **346 distinct
row rates, 75% of them unique within a single game**, Final Fantasy VI alone
getting twenty including 2.2 and 2.3 as separate values, a 92× spread. One row
meant 4 ms in one track and 847 ms in another. Row arrays whose unit changes
per track are not a comparable corpus, which is the only reason to have row
arrays at all.

**The analogy to NES-MDB that motivated the grid was wrong in its mechanism.**
The NES's shared 60.0988 Hz is the **PPU** frame rate — a consequence of the
PPU dropping one dot on the pre-render scanline of odd frames — and music
engines inherit it by running off the vblank NMI. It is not the APU frame
counter, which is a separate divider off the CPU clock resetting every 29,830
cycles for a 240 Hz quarter-frame step, driving envelopes and sweeps rather
than sequencing. Even on the NES the gift is regional: PAL runs a different CPU
clock at 50.007 Hz and forces a retime.

**The SNES has no such shared signal, which is the whole point.** The SPC700
and DSP sit on their own crystal, isolated from CPU and PPU, so SNES music
timing has no relation to the video frame rate. Drivers sequence off the
SPC700's own timers: Timer 0 and Timer 1 at a base 8 kHz, Timer 2 at 64 kHz,
each scaled by an 8-bit divider. There is no universal rate to borrow, so the
clock has to be *established per game* rather than assumed or fitted.

`src/snesmdb/clock.py` does that, and the hardware supplies a test the grid
could never submit to: a real timer read must land on base/N. Across the
corpus's range a random frequency does so 20.4% of the time; **89% of the 519
measured ticks do**, and all fourteen per-game clocks resolve to a plain
Timer 0/1 divider (FF6 8000/39, Chrono Trigger 8000/42, Secret of Mana 8000/36,
Mega Man X 8000/128, Super Metroid 8000/16).

| | inferred onset grid | per-game driver clock |
|---|---|---|
| tracks with row scores | 866 (65.8%) | **1,316 (100%)** |
| hardware-grounded | none | **1,066 (81.0%)** |
| distinct row rates | 346 | **60** |
| notes snapped (onset moved) | **11.3%**, to 32.4% worst game | **0.03%** |
| contested cells | — | 16 of 1,863,499 |

The snap rate is the result that matters: the fitted period was *coarser than
the music it described* and was displacing one note in nine. A driver tick is a
fine subdivision, so almost nothing moves. Rows per track rise from ~1,020 to
~9,001, which is NES-MDB-comparable (a three-minute NES track at 60 Hz is
~10,800 rows) because one row is now one driver tick, exactly as NES-MDB's row
is one frame.

**A clock is not a tempo, and the objection that it must be was the right
objection.** A game's songs do not share a tempo and nothing here claims they
do: the clock is the quantum, tempo is how many ticks a note consumes. FF6
holds 205.13 Hz across all 55 music tracks while its median inter-onset spacing
runs 13.8 to 183.0 driver ticks — a 13× tempo spread, clustering near 24, 36,
48 and 72, which are tracker row durations.

Where the objection bites is the eight games with no per-game clock, and for
five of them the driver is the reason: Star Ocean, Tales of Phantasia, Lufia 2,
Super Turrican and Plok! put 63–100% of their ticks on real dividers but spread
them across 4–23 distinct rates. Those drivers set tempo by reprogramming the
divider instead of counting a fixed tick. They fall back to the track's own
verified rate, which for such a driver is not a degradation but the correct
answer.

**A correction worth recording.** Those five games were briefly diagnosed as
*extractor failures* — "not timer reads at all, at the chance rate" — on a
measurement that rounded each tick to 0.5 Hz before testing it against the
divider set. Rounding knocks a genuine rate off its divider: 222.22 becomes
222.0, a 0.1% error against a 0.11% tolerance. The quantisation destroyed the
thing being tested and turned 78–100% into 25–37%. Nothing is rounded before
the divider test now, and a test asserts that rounding breaks it.

**What this supersedes.** The threshold question below, the 450 gridless
tracks, the piecewise grid, the FFT periodogram and the cheaper `infer` were
all work on inferring a row unit that the hardware states directly. None of it
is needed for the scores. The grid is kept and still reported, because the
*onset* period is a real and separate measurement — a musical question, which
is what the listening set actually tests — but it is no longer the row unit,
and milestone 4's exit no longer depends on any of it.

The analysis below is left as written, including the threshold argument that
the clock makes moot. It is the record of how the wrong question got asked for
as long as it did.

### The driver tick is an independent witness, and it puts the bar at 0.70

Everything above argues about the threshold using fit, which is circular. The
driver tick is not: it comes from DSP write cadence, which the grid estimator
never sees. If a grid is metrically real it should sit on a whole number of
driver ticks, because that is how a driver advances a sequence. So on the 366
music tracks that have both a confident tick and a grid, how close is
`period_ticks / tick_period` to an integer?

| fit band | n | median &#124;ratio − nearest integer&#124; | within 0.05 of an integer |
|---|---|---|---|
| 0.45–0.60 | 37 | 0.200 | 27% |
| 0.60–0.70 | 42 | 0.252 | 31% |
| **0.70–0.80** | **45** | **0.008** | **56%** |
| 0.80–0.90 | 75 | 0.000 | 71% |
| 0.90–1.01 | 144 | 0.001 | 58% |
| *random ratios (control)* | 5,000 | 0.250 | 9% |

**The break is at 0.70, not 0.80.** Below it the median residual, 0.20–0.25, is
indistinguishable from the 0.25 of uniformly random ratios — those grids are
not tick-locked at all, and the 27–31% hit rate against a 9% control is weak
corroboration at best. At 0.70 the median residual collapses by a factor of
twenty-five and the hit rate roughly doubles. The 0.70–0.80 band, which the
pipeline currently discards, is as tick-locked as the 0.90+ band (56% at median
0.008 against 58% at 0.001).

Moving the bar to 0.70 would admit **124 more tracks overall (65.8% → 75.2%)
and 111 more music tracks (66.0% → 77.0%)**. That is not done yet, because a
hardware witness is evidence about *metric reality* and the bar is also doing a
second job — guaranteeing the emitted score is usable — and 366 of 1,006 music
tracks is a biased sample, confined to the four or five drivers whose write
style yields a confident tick at all.

Two further things fall out of the same table. **Fit is not monotone**:
0.80–0.90 beats 0.90–1.01 on both statistics, which suggests fit saturates and
the top band is partly sparse tracks that are easy to fit rather than
well-measured ones. And the corpus **row rates are not beats** — they run 1.2
to 1,000 per second with a median of 13.3, and 74% exceed 8/second, so the
inferred period is generally a tracker row several subdivisions below the beat.
Any consumer reading `rows_per_second` as a tempo is reading it wrong, which is
why `bpm_assuming_4_rows_per_beat` carries its assumption in its name.

### The listening set, and why a statistic could not have caught its first bug

`tools/grid_calibration.py` emits 25 MIDI files sampled across fit bands
straddling 0.70, each with a metronome on channel 10 at the inferred period and
phase, plus a `calibration.csv` with blank verdict columns. The point is to get
at the one thing no measurement here reaches: whether a high-fit grid is *the
beat*, and whether a low-fit grid is wrong or merely ornamented.

The first version clicked the raw grid period, and at a median 13.3 rows/second
that is a 13 Hz buzz, not a metronome — 74% of the corpus was unjudgeable. Every
file parsed as valid Type-1 MIDI; the defect was purely audible. The fix clicks
an integer multiple of the row chosen to land near 120 BPM, recorded per track
as `rows_per_beat`, so the subdivision assumption is explicit in the CSV rather
than buried in the period. A verdict of "subdivision" therefore indicts
`rows_per_beat` and not necessarily the grid, while "drifts" — a wrong period
with a right phase, which fits the opening bars and slides out, and which
whole-track fit still scores well — indicts the grid and cannot be fixed by
remultiplying.

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

### Refitting on corrected pitch made the register axis worse, not better

Milestone 3's octave fix changed `median_midi` for a large share of samples,
which is one of the three usage axes this validation turns on, so the codebook
was refitted and the tests re-run. A reader would reasonably expect cleaner
pitch to help. It did the opposite on the axis that matters:

| test 2, cross-game agreement *(lower is better)* | before the pitch fix | after |
|---|---|---|
| median register, real | 0.526 | **0.546** |
| median register, shuffled null | 0.554 | **0.505** |
| verdict | marginally better than null | **worse than null** |

Duration and pitchedness are unchanged (0.255 against 0.328, and 0.509 against
0.552), and held-out transfer is unchanged too: register 0.444 SD, duration
0.202 SD, pitchedness 0.0 SD.

So the earlier marginal "slightly better than chance" on register was partly an
artifact of the octave errors themselves. Samples sharing an octave error
clustered together and their registers agreed for that reason. With the pitch
corrected the register signal is gone outright, and the codebook now agrees
across games *less* well than random labels do.

This strengthens the negative rather than changing it, and it belongs on
record: fixing an upstream milestone made a downstream result worse, because
the downstream result had been partly measuring the upstream error.

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

### Exit: met

**[DATASET.md](DATASET.md)** is the deliverable the exit criterion actually
names — "a corpus another person could use, with its provenance and its
limitations written down". Half of it is limitations, because that is the half
that makes a corpus usable rather than merely available.

`tools/publish.py` assembles the tree: per track the three score formats, an
8-track MIDI and an intake JSON; once, the splits, the manifest, the codebook
and the performance figures.

**All three score formats now exist.** `expressive` was blocked on milestone 5
and ships using the one timbre claim that survived validation — a binary
tonal/percussive flag — with `timbre_validated:
"tonal_vs_percussive_only"` carried on every score so a consumer cannot mistake
class 3 for an instrument. Writing the finer class anyway is deliberate: it is
real information about this corpus, and the field next to it says how far to
trust it.

**MIDI claims as little as possible.** No General MIDI program is set, because
milestone 5 showed sample identity does not transfer and a program number would
be fabricated. Channel 9 is never used, so nothing is implicitly a drum. The
one real loss is phase inversion — a negative side volume inverts that side's
phase and MIDI has no way to say so — and it is not a corner case, since Tales
of Phantasia inverts on 55.8% of its notes. Every drop is counted per track
rather than silently absorbed.

**The licensing rule is enforced, not just documented.** `publish.py` refuses
to write into a git work tree, because the output is derived from SPCs that are
"educational and personal non-profit use only" and must never be committed. The
published artifact is derived data plus the tools to rebuild it from files the
user supplies.

**One thing is explicitly unverified.** The intake tree is `snesmdb.intake.v1`,
intended for the sibling renderer's `acquire(from_extracted=True)` — which is
not in this repository and against which it has never been tested. It is
labelled proposed rather than assumed compatible, in DATASET.md and in the
schema field itself.

## Performance conventions — not a milestone, and the point of the corpus

`docs/design.md` §7 argues that if this is built for analysis, the thing to
extract is **performance** conventions rather than progressions and form, on
the record that composition-rule changes are 0 for 4 with this listener while
per-song duty and position-shaped velocity landed immediately. That analysis
sits outside the six milestones and is now done:
**[performance-conventions.md](performance-conventions.md)**, over all 1,316
tracks.

The result that matters most is a negative. **Position-shaped velocity does not
exist in real SNES music** — correlation of note volume with position through
the track is 0.006, and the range across 22 games is −0.047 to 0.066. One of
the only two changes a listener has ever accepted from this project is
therefore an invention that improves on the idiom, not a convention waiting to
be recovered. Measurement found it absent and would never have proposed it.

Four things are genuine conventions, tight across every game: **instant ADSR
attack** (median 15 of 15, range 14-15), **full sustain** (median 7 of 7),
**echo on** (every track of the median game, six of eight voices), and **about
five of eight voices sounding** with silence almost absent. Those are the
platform's defaults.

Volume-vs-register and volume-vs-voice are **house styles, not conventions** —
Breath of Fire II is +0.71 on voice index where DKC2 is −0.55, so they are
strong inside a game and cancel across the corpus. Same for staccato, which
runs from 0% to 73.5% of notes under 100 ms.

And two of the S-DSP's distinctive features are dead hardware here: **106 noise
notes and 727 pitch-modulated notes out of 1,863,499**. Drivers write NON and
PMON 1.48 million times in a 40-track sample, always zero.

## The pipeline is one pass, and the equivalence was proved not assumed

Dropping the per-game clock consensus removed the only thing that needed a
whole-corpus pass, so the second tool folded into extraction. The claim that
had to be checked is that the single pass produces the SAME corpus, because a
silent divergence between two code paths is exactly the failure this change
exists to remove -- it would have been self-defeating to take it on faith.

Diffed across all 1,316 tracks, against the two-pass manifest kept for the
purpose:

| compared | result |
|---|---|
| track ids | identical set |
| `clock.period_ticks`, `.source`, `.hz` | match |
| `scores.n_rows`, `max_polyphony`, `n_notes_represented`, `n_cells_filled` | match |
| `envelope.n_holds_full`, `summary.n_notes`, `n_legato_steps` | match |
| `track_class`, `split`, `timers.sequencer_hz` | match |
| `separated`, `blended`, `expressive` payloads | byte-identical, 40 sampled |
| note and `legato_steps` records | byte-identical |

The only difference corpus-wide is the two fields deliberately removed with
the consensus, `agreement` and `n_confident_tracks`. Every shared field
matches, including the reason strings. `make verify` passes 13/13 on the
result.

Cost: one pass of about 53 minutes against the old 50 plus 10, so the fold is
slightly faster as well as being a step that can no longer be forgotten --
which was not hypothetical, since the shipped rebuild recipe forgot it and
produced a corpus with zero scored tracks, silently.

## Research Publication Contract — gates 0 to 5

The milestones above are about extraction being correct. These are about the
PUBLISHED ARTIFACT containing what the pipeline claims, and then being usable
by someone who does not know how an SPC700 works. The distinction earned its
own section because the same defect shipped three times: `scores.expressive`
was dead code for two milestones, the documented rebuild recipe omitted the
step that derived the row clock, and the 100 Hz uniform grid was benchmarked
at length and never reached `publish.py`. Each time the internal measurement
was correct and the artifact did not have it.

**Every gate introduces its own failing acceptance test before its
implementation, and those tests open files under `dist`.** They do not call
extraction or scoring functions to reconstruct the expected output — a test
that called `scores.build` would have agreed with the broken publisher and
reported success. `tests/test_dist_contract.py` is where they live.

| gate | what it establishes | state |
|---|---|---|
| 0 | repository carries no licensed or derived material | ✅ closed |
| 1 | the 100 Hz uniform scores are present in `dist`, with contents checked against `data/out` | ✅ closed |
| 2 | `events.v1`: flat event list in seconds, pitch uncertainty, sample content identity, amplitude semantics | ✅ closed |
| 3 | `track_class`, extraction status, event counts, schema versions; legacy contracts preserved | ✅ closed |
| 4 | end-to-end researcher workflows using only `dist` | |
| 5 | **blind researcher acceptance** | |

### Gate 2 schema decisions, settled before implementation

**`pitch_status` uses `estimated`, not `measured`.** A sample's fundamental is
ESTIMATED from its BRR content; calling it measured would claim a certainty the
pipeline does not establish. The values are `estimated`, `noise`,
`pitch_modulated`, `unrecoverable`. `pitch_confidence` stays a separate field,
the underlying `noise` and `pitch_modulated` flags are preserved rather than
collapsed into the status, and the resolution order for overlapping conditions
is documented.

**`extraction_status` is independent of `track_class`.** An absence of
recovered pitches must never imply extraction failure or musical silence. Four
states are distinguished: successful with pitched events, successful with only
unpitched events, successful with no detected events, and incomplete or failed.
A sound effect can contain recoverable pitch and a music track can contain only
unpitched observations, so a musical label must never double as a data-quality
indicator. Defined in gate 2 so the event schema can express "empty" versus
"failed" from the start; published to `index.json` in gate 3.

**`attack_level` and `sustain_level`** replace the velocity/sustain naming in
the new schema, documented as: *register-derived amplitude controls at attack
and sustain. They are not measurements of perceived loudness, acoustic
intensity, or standardized MIDI velocity.*

**`sample_id` is a content hash, not an instrument label.** It identifies the
decoded BRR block reproducibly, which `srcn` does not — Super Turrican's 8
indices resolve to 48 distinct samples across 12 tracks. It is not evidence
that a sample always performs the same musical role.

### Gate 3: the index describes itself — closed

`index.json` was a bare JSON list. That is enough to find a file and not
enough to be a published artifact: it could not state which contract it
followed, so two downloads were distinguishable only by diffing them, and
"how big is this corpus" needed a pass over 1,316 gzipped files. It is now
`{schema, formats, corpus, tracks}`, where `tracks` is the old list unchanged.

**This is a published-shape change.** A consumer doing `json.load(...)` and
iterating must now read `["tracks"]`. Nothing inside a track row was renamed
or removed — `test_legacy_index_fields_survive` and
`test_legacy_score_payload_keys_survive` assert that per row, and the verifier
still reads a bare list so that a corpus published before this change can
still be checked.

**Each format is versioned separately** — `events`, `intake`, `sample_id`,
`uniform_hz` — because they move separately: `events.v1` landed while the
score payload was untouched. A single corpus version would force a choice
between a false bump for consumers that were unaffected and a silent one for a
change that mattered. The versions are read from the modules that own them, so
a future `events.v2` reaches the index without anyone remembering to edit it;
`test_a_schema_bump_in_a_format_module_reaches_the_index` pins that.

`track_class` had been computed since milestone 1 and never published, so a
researcher could not exclude sound effects from a melodic study without
re-deriving it. Published now alongside `extraction_status`, and the two are
**demonstrably independent** rather than merely declared so:

| | pitched events | unpitched only | no events |
|---|---|---|---|
| music | 995 | 11 | — |
| jingle | 206 | 27 | — |
| effect | 42 | 18 | — |
| drone | — | — | 17 |

42 sound effects contain recoverable pitch and 11 music tracks contain none,
so neither field can serve as a proxy for the other. `drone` maps to a single
status because a voice that never re-keys produces no events at all — that is
the class meaning, not a redundancy. Both the contract test and the audit
check `dist_class_and_status_independent` fail if every class collapses to one
status.

Corpus-level counts are published: 1,316 tracks, 22 games, 2,018,409 events,
1,560,002 pitched, 1,863,499 attacks. The attack total is separate from the
event total because **an event is not an attack** — the remaining 154,910 are
legato steps, pitch changes on voices that never re-keyed.

**A coupling removed in passing.** The event table was being built inside
`if track_clock.period_ticks:`, so a format whose every timestamp is in
seconds depended on a row clock it never reads. Every track in this corpus has
a clock, so the coupling cost nothing and was invisible — but the published
contract says every track has an event table, and that claim must not rest on
a coincidence in the current corpus. Hoisting it left all counts identical
(2,018,409 events, 1,316 tables), which is the evidence that it was inert.

Closed on 34 dist contract tests with no skips, 8 new library tests for the
index document, and a 27-check exhaustive audit over all 1,316 published
tracks.

### Gate 4: the published corpus supports research — closed

Gate 4 asks an **engineering** question: can the distributed artifact be read
correctly, and do the numbers it yields match the extraction it came from?
Gate 5 asks whether a researcher can use it. These are not interchangeable,
and Gate 4 is deliberately scoped so it cannot stand in for Gate 5.

Three workflows in [`examples/workflows.py`](../examples/workflows.py), run
against `dist` with the standard library alone:

1. **Corpus discovery** — filter the index by game, `track_class` and
   extraction status, then load the named event tables. Loading verifies each
   table against the index row that named it, because the index carries the
   counts so a census needs no pass over the corpus, and that is only safe if
   the two agree.
2. **Pitch distribution and range** — reported separately for pitched attacks
   and for all sounded pitches, with every excluded event attributed to one of
   the three reasons it has no pitch.
3. **Sample recurrence** — which sample content recurs across tracks and
   games, with the pitch span of each recurring sample.

**The workflows import nothing from this project, and a test enforces it** by
reading their import statements. A researcher who downloads the corpus does
not have `src/snesmdb`; a workflow that needed it would demonstrate only that
our code can read our own output, which is not the claim Gate 4 makes.

Every reference figure is recomputed from `data/out` by a different route —
pitched attacks come from the `notes` records, which never touch the
legato-step handling they are used to check — so an agreement is two paths
meeting rather than one path checking itself. Confirmed by mutation: forcing
the workflow to accept every `pitch_status` as a pitch fails three tests.

Workflow 3 produced the evidence for a claim the documentation had only
asserted. One Actraiser sample recurs across 14 tracks spanning **65
semitones**, over five octaves. A recurring `sample_id` means two tracks
played the same sound; it is not an instrument, and the corpus now shows that
rather than saying it. `test_a_recurring_sample_is_not_evidence_of_one_instrument`
fails if no recurring sample spans more than two octaves — if that ever
happens, the documented reading is the thing to change.

**Explicitly out of scope: polyphony and simultaneous voices.** Reserved for
Gate 5. Constructing that analysis here would convert the independent
evaluation into a confirmation of our own assumptions. General invariants that
touch it — valid durations, resolvable event identities, polyphony within
eight voices — are still checked, in the audit.

Closed on 13 Gate 4 tests, 367 in the suite, and a 27-check exhaustive audit.

### Release freeze

`tools/freeze_release.py` writes `RELEASE.json` into the published tree: the
commit, the corpus counts, and a SHA-256 for every file. `--verify` re-hashes
and reports anything changed, missing or added.

Without it a corpus is whatever the last `make corpus` produced, so a
disagreement between an evaluator's number and ours could not be separated
into "they read it differently" and "they read something else" — which is the
whole value of an independent evaluation. `provenance.json` records the commit
but cannot detect a tree touched or rebuilt afterwards.

It **refuses to freeze a dirty working tree** unless forced: a pin naming a
commit that does not contain the code which built the corpus cannot be
reproduced, which is the one thing a release candidate has to offer.

### Pre-flight: documentation defects in `gate5-rc1`

A review of the **frozen** RC1 commit found researcher-facing documentation
defects. They are recorded here because they are the kind of failure Gate 5
exists to find, and finding them in review instead means RC1 would have spent
the evaluation's budget on problems already known.

| defect | state at RC1 | corrected |
|---|---|---|
| uniform score rate | documented as **60.0988 Hz, "the NES-MDB row rate"** | 100 Hz, 10.00 ms |
| uniform row counts | 16.639 ms, 4,658 rows/track, 4.03× fewer rows | 10.00 ms, 9,601 rows, 1.95× |
| `make test` | 287 tests | 388 |
| `make verify` | 13 checks | 26, plus `make audit` at 27 |
| `timbre_class` | "published as -1 for every note" | located per format; absent from `events.v1` |

**The rate defect was the serious one.** It appeared in both `README.md` and
`DATASET.md` — the latter ships inside `dist` — in a passage instructing
researchers to use the uniform block for cross-game comparison. 60.0988 Hz is
the NES's NTSC *video* frame rate; NES-MDB's scores are 24 Hz; this corpus
publishes 100 Hz. Anyone following that sentence would have mistimed every
uniform row by 66%, and `DATASET.md` contradicted itself, stating 10 ms in one
section and 16.639 ms in another.

Correcting prose by hand is what produced the defect, so the claims are now
checked: `tests/test_docs_accuracy.py` asserts the stated test count against
what the session collected, the documented row duration against
`scores.UNIFORM_HZ`, and that no stale rate is ever attached to the uniform
grid again. The first version of that last check only looked for `"100"`
somewhere in `DATASET.md`, which is true of almost any document and missed the
whole stale section; it now checks the row-duration claim, which cannot be
satisfied by coincidence.

`CHANGELOG.md` now ships inside `dist` as well. A download whose migration
note stayed in the repository would leave a consumer to discover the index's
shape change by crashing.

Also reclassified: the recurring-sample pitch-span check moved out of the Gate
4 contract tests into `tests/test_corpus_characterization.py`. `sample_id` is
not an instrument label **by definition**, whatever a corpus's pitch-span
statistics show, and a definition that could be falsified by a statistic would
be a weak definition rather than a strong test. The measurement is still
recorded — it is good evidence that the distinction matters on real data — but
as a corpus characterization whose failure means the corpus changed.

RC1 is preserved for comparison at `~/snesmdb-corpus/dist-gate5-rc1` with its
own pin. `freeze_release.py` now refuses to write a differently-labelled pin
over an existing one without `--replace`, and archives every pin under
`releases/<label>.json`: an evaluation in progress names a label, and silently
repointing it at a different tree would invalidate the evaluation without
leaving a trace.

### The `gate5-rc2` transfer incident, and what it exposed

An evaluator reported `gate5-rc2` as corrupt: `index.json` truncated to 56.0%
of its length, mid-string, at exactly 768 KiB (`0xC0000`), with
`json.load` failing on an unterminated string. The report was careful,
reproducible, and correct about everything it measured.

**The release was not corrupt.** `index.json` in both the source tree and the
delivered package is 1,405,102 bytes with sha256 `577f089bb0923ae0…`, exactly
as `RELEASE.json` declares, and parses cleanly; both trees verify 5,200 of
5,200 intact. The damage was introduced by the copy that created the
evaluator's working tree — a short write, as the clean binary boundary
suggested.

One inference in the report inverted: it read `index.json`'s mtime as *later*
than the freeze and concluded something had rewritten it afterwards. In the
delivered package `index.json` carries mtime 07:05:22, preserved from publish
by `copytree`, while `RELEASE.json` carries 07:28:07 matching `frozen_utc` —
index older than freeze, as it should be. The `07:34`/`07:35` stamps belonged
to the copy operation that damaged the tree.

**That an evaluator could not distinguish a damaged transfer from a damaged
release is the real finding, and it is ours.** Four defects followed from it:

1. **`make_research_package.py` never verified the copy.** It checked the
   source pin before copying and audited exclusions after, but never re-hashed
   the copied bytes — so a short write during *our* copy would have shipped
   silently. It now verifies the copied tree and deletes the package on
   mismatch.
2. **No verifier shipped.** The blanket `.py` exclusion denied the recipient
   any supplied way to answer the question, so they wrote their own. An
   integrity checker is not the extraction source under evaluation;
   excluding it was over-broad. `verify.py` now ships, reports a wrong
   *length* as a damaged copy and a wrong *hash* as altered content, and says
   "re-copy before reporting anything".
3. **`game` and `track_class` lived in `index.json` and nowhere else**, while
   the documentation emphatically instructs filtering a melodic study on
   `track_class`. Losing one file made that instruction impossible to follow
   for 582 tracks and left only `extraction_status` — the proxy the same
   documentation forbids. Both fields now travel in every event table header
   (`events.v2`, purely additive) and in a new `tracks.csv`, which degrades
   line by line where a truncated JSON document does not degrade at all.
4. **`DATASET.md` named `records/*.json` and `raw/*.jsonl.gz` as "preserved
   and published".** Neither is distributed — one is intermediate build
   output, the other the compressed-log form this project's own rules exclude
   — so the microtiming section directed researchers to two trees that do not
   exist in the distribution, as did the `axe-03` example. Both now point at
   `events/*.json.gz`, which carries the same onsets to microsecond
   resolution and was always the right answer. Verified directly: `axe-03`
   carries `event_id` 940 and 941, 5.106 ms apart, matching the documented
   figures.

Also fixed: the slug→game map is published (`index.json` → `games`,
`tracks.csv` → `game_slug`, and every event header). The evaluator had to
reconstruct it by matching per-game track counts and then break a tie between
two 66-track games from their clock rates — ingenious, and reverse
engineering of something this project already knew. The slugs are not
guessable: `mo2` is Earthbound (Mother 2), `sd2` is Secret of Mana (Seiken
Densetsu 2), `ed2` is Lufia 2, `dkq` is Donkey Kong Country 2. References to
this build log as the authoritative defect list were removed from the
distributed documents, since the log is deliberately not distributed.

What the incident did **not** touch: every corpus-level total the evaluator
recomputed from the 1,316 intact event files matched the declared `corpus`
block exactly — events, pitched events, attacks, legato steps, rendered
seconds and the status census. The extraction and the data were never in
question.

### Gate 5: researcher acceptance

The first test of whether this is what was intended, rather than whether the
code behaves as designed.

An evaluator gets the published corpus, `README.md` and `DATASET.md`, and
answers research questions with those alone: longest melodic tracks, pitch
ranges across games, rhythmic note density, simultaneous voice counts, and the
tracks containing events with no recovered pitch. At least one question should
be the evaluator's own, because a prescribed task can only confirm what was
anticipated.

The question designed to expose silent interpretation errors: *which games use
the greatest average number of simultaneous musical voices?* Counting only
pitched MIDI notes gives an incomplete answer, since 405,288 events carry no
note number. **If a researcher confidently produces the wrong answer because
the documentation or the schema led them there, that is a database failure,
not a researcher failure.** That is the standard the gate holds the artifact
to.

Success is not perfection on the first run. It is that the analyses can be
completed without chip-specific knowledge, that missing information is
distinguishable from genuinely absent musical activity, and that results are
reproducible without unknowingly using an inappropriate representation. Every
failure becomes a documented issue and then a regression test.

One rule worth keeping: the schema is not adjusted just before the test to
make the tasks easier. Freeze the candidate, run the evaluation, let the
findings decide what changes.

## Open defects, in one place

Everything here is measured, reproducible and unfixed. None of it is hidden in
a subsection.

**The row clock is a hardware tick, not a sequencer row, and M is recoverable
for only about a third of the corpus.** Where a driver counts M timer ticks per
musical row, rows are M times finer than the music and a note spans several of
them. M is the ratio between the register clock and the write-cadence estimate,
since the first is the timer and the second is the sequencer -- and that ratio
is a clean integer for **462 of the 519 tracks that have a tick at all (89%)**,
roughly a third of the corpus. It is published as
`timing.software_divisor_m`, and is **null** rather than 1 where unknown,
because assuming 1 would silently claim the row IS the musical row for the
other two thirds.

An earlier version of this entry said M was "not recoverable" at all. That was
wrong: the vestigial `tick` field turned out to encode it, with a median ratio
of exactly 1.00 against the register clock. The limitation is real but
narrower than first stated.

**The 100 Hz uniform grid loses one repeated-note attack.** Among 1,458,211
pitched events: Axelay `axe-03`, two successive same-pitch attacks about 5.1 ms
apart, which a 10 ms row cannot separate. Distinguishable at 200 Hz, and both
notes keep exact timestamps in `records/` and `raw/`. Ordinary quantisation
rather than a representation limit, and the full statement is in
[DATASET.md](DATASET.md).

**A modulation that stops mid-note is read as a legato step.** If a driver
modulates pitch and then holds its final excursion to the key-off, that is
indistinguishable from a note succession: the pitch moved and did not come
back. Pinned by a test. Drivers in this corpus modulate to the key-off, so it
is a limitation rather than an observed error.

**2.8% of notes report `srcn = 0`** (52,093 of 1,863,499). Seeding voice state
from the SPC's DSP block fixed 8.0% of notes, and this floor is what remains.
Sample 0 is a legitimate index, so some of these are correct and the residual
is not separable.

**The 2,048-tick artifact.** 20 tracks across six unrelated games report a
driver tick of exactly 2,048 ticks, which is intra-burst write spacing and not
a timer. It survives in the `tick` field, which is now vestigial -- the row
clock comes from the timer register -- so it misleads only a consumer reading
`tick` directly.

**The timbre codebook does not transfer across games** and milestone 5's exit
criterion is not met. Class agreement across games falls to the shuffled null
once the leaking features are removed. `timbre_class` is published as -1
throughout rather than offering a number from it.

**The 1.10x enrichment cutoff for "melodic" legato is arbitrary.** Two games
sit close enough to flip on it, and did: Super Mario World read melodic before
the interval ceiling and not after, Secret of Mana the reverse.

**`$F1` is write-only on real hardware.** The byte an SPC carries there is a
convention of the dump format, not something the CPU could read back. It is
trusted because it reproduces ten independently measured clocks exactly, which
is empirical corroboration and not a guarantee.

**Phase inversion is lost.** Velocity takes the magnitude of the side volumes,
and a negative side volume inverts that side's phase, which two games do on
over half their notes.

**The intake schema is unverified against its consumer.** Its shape is
documented but is not checked against the renderer's `acquire(from_extracted=
True)`, which lives in a sibling project not present here.

## What this does not promise

The published artifact is a **dataset and the tools to rebuild it**, not a
model. Training a generative model on it is out of scope here, and worth
knowing why: on the NES side, a clean retrain that improved validation loss by
11.4% produced output a listener called "barely music". Next-token loss does
not measure music. A SNES corpus does not change that argument — it is worth
building for analysis, comparison, and as a public artifact, and those are the
reasons to build it.
