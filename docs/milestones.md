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
| 2 | Real SPCs and corpus plumbing | a curated set extracted, each track audio-validated | **medium — first contact with reality** |
| 3 | Absolute pitch | note numbers, with per-sample confidence | medium |
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

**Exit:** a curated set extracted end to end, every track carrying an audio
validation score, splits built and verified disjoint.

**Open dependency:** whether per-track composer metadata is obtainable at
scale. snesmusic.org lists 3,255 composers, but that it is parseable per track
is unverified, and it gates the split property. Check this before writing
extraction code against it.

**Why this is medium risk:** every driver is different. Expect this milestone
to find that some assumption in milestone 1 only held for my own fixture.

### What first contact actually found

Two games, two driver families, 111 tracks, 229,879 notes, 108 of 111 passing
every check and **zero unhandled registers in either**.

| | Donkey Kong Country (Rare) | Final Fantasy VI (AKAO) |
|---|---|---|
| notes/sec | 21.0 | 13.4 |
| KON *writes*/sec | 21.0 | 204.5 |
| effective / all KON | **100.0%** | **2.7%** |
| mean voices used | 7.4 | 7.3 |

**The two drivers could not be more different in idiom, and it does not
matter.** Rare writes KON only when it means it. AKAO re-uploads the whole DSP
register block about 205 times a second, so 97.3% of its KON writes carry a
zero mask. Anything that measured register *activity* would have called FF6
ten times denser than DKC when it is actually sparser. Counting set bits
rather than writes was the decision that made both work.

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

**Still blocking the exit criterion:** splits. Two games with disjoint
composers give two components, so `test` is empty. This is a corpus-size
problem, not an algorithm problem, and the fix is more games rather than a
weaker split rule -- see the note below.

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

**Exit:** note numbers for pitched voices, with confidence, validated against
samples whose pitch is independently known.

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
