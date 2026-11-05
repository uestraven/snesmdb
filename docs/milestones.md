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
| 2 | Real SPCs and corpus plumbing | ✅ done — 232 tracks, 5 drivers, splits clean | medium |
| 3 | Absolute pitch | ⚠️ partial — 83% pitched, ~9% octave-suspect | medium |
| 4 | Grid inference | tracker rows; *separated* and *blended* scores | low |
| 5 | Timbre vocabulary | a closed codebook; *expressive* score | **high — the research problem** |
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
SET, the tag gives it per TRACK, and it needs no network. All 232 files carry
one.

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

**Exit: partially met.** 315,349 of 379,821 notes (83%) carry a note number;
373 of 500 distinct samples (75%) yield a usable fundamental, the rest being
percussion and noise as expected. But **8.7% of pitched notes land outside
MIDI 12-108**, which is the signature of a residual octave error: two
estimators can agree and both still be an octave out. Treat `midi_note` as
usable in bulk and unreliable per note; `pitch_confidence` is on every note.

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
