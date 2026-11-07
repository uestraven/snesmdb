# The SNES Music Database

snesmdb is a dataset of music from the Super Nintendo Entertainment System
(Super Famicom), intended for building automatic music composition systems for
the SNES sound hardware. It is the SNES counterpart to
[NES-MDB](https://github.com/chrisdonahue/nesmdb), and it follows that
project's design closely on purpose: the goal is to let researchers study SNES
music while shielding them from the inner workings of the S-DSP.

That shielding is harder here than on the NES, and the reasons are worth
understanding before choosing a format — see the
[SNES Synthesizer Primer](#snes-synthesizer-primer).

**Status: five of six [milestones](docs/milestones.md) met, one failed;
publication gates 0–4 closed.**
**1,316 tracks from 22 games**, composer-disjoint splits (1,049 / 135 / 132),
every track clocked from its own SPC700 timer register. The corpus publishes
**2,018,409 events** — 1,863,499 note attacks plus 154,910 legato steps, of
which 1,560,002 carry a recovered pitch. `make verify` gates a build on 26
checks and `make audit` opens every published file for 27.

**If you are here to do research, start with `events/*.json.gz`**, the flat
event table in seconds described in [DATASET.md](docs/DATASET.md). The score,
MIDI and intake formats below are the hardware-indexed views and need more
context to read correctly.

**Milestone 5 — the timbre vocabulary — did not work**, and that is the headline
rather than a footnote. A cross-game instrument vocabulary was the one piece
NES-MDB gets free and this project had to construct, it was named as the
project's main risk at the outset, and the risk landed: class agreement across
games collapses to the shuffled null once features that leak are removed. No
codebook is shipped.

`timbre_class` is therefore an **inert field**, written as `-1` everywhere it
appears, and where it appears is worth being exact about:

| format | `timbre_class` |
|---|---|
| `events/*.json.gz` | **absent.** The researcher-facing table has no such field |
| `scores/*.json.gz` | present as the expressive score's third channel, always `-1` |
| `intake/*.json.gz` | present per note, always `-1` |

It remains in the two older formats because removing a field from a published
shape is a breaking change, and it is flagged there rather than quietly
carried: each expressive block reports
`timbre_validated: "tonal_vs_percussive_only"` and
`timbre_classes_present: [-1]`. See [the analysis](docs/milestones.md).

Known defects are listed in one place in
[milestones.md](docs/milestones.md) rather than scattered: nine of them, all
measured and reproducible.

## Contents

- [Dataset information](#dataset-information)
  - [Voice event log](#voice-event-log)
  - [Score formats](#score-formats)
  - [MIDI](#midi)
  - [Raw format](#raw-format)
- [The snesmdb tools](#the-snesmdb-tools)
- [SNES Synthesizer Primer](#snes-synthesizer-primer)
- [Design decisions](#design-decisions)
- [Licensing and the source data](#licensing-and-the-source-data)
- [Relationship to the renderer](#relationship-to-the-renderer)
- [Attribution](#attribution)

Docs: [DATASET.md](docs/DATASET.md) is the deliverable — what the corpus
contains and what it gets wrong. [CHANGELOG.md](docs/CHANGELOG.md) records
changes to the published formats, including the one breaking change so far.
[milestones.md](docs/milestones.md) is the
build log, including the open-defect list and the things that were tried and
reverted. [design.md](docs/design.md) is the original plan.
[performance-conventions.md](docs/performance-conventions.md) is the analysis
the corpus exists to support.

## Dataset information

Pick a format by background. If you want to do algorithmic composition, use a
score format or MIDI. If you are coming from sequence modelling, the voice
event log is the closest thing to a token stream. If you want to build your own
representation, start from the raw format.

### Voice event log

**Implemented.** One record per sounding voice: key-on and key-off times in
SPC700 clocks, the 14-bit PITCH register, the sample index (SRCN), left and
right volume, and the envelope registers (ADSR1, ADSR2, GAIN).

Each note also carries a `midi_note` where absolute pitch could be recovered —
**78.3% of notes** — by decoding the BRR sample and estimating its fundamental,
then applying the PITCH ratio. The rest keep the raw register value only.

Caveats, because they decide whether this format suits you. Voices playing
noise (NON) or under pitch modulation (PMON) are flagged rather than given a
pitch, since the PITCH register does not describe what sounded. A note still
running when the log ends is marked unfinished rather than given an invented
end time. Velocity is the two side volumes and so is the **attack** only — the
envelope is the other half of loudness, and 20% of notes settle below full
scale (see the sustain channel below).

A parallel `legato_steps` table records notes the driver delivered by writing
PITCH to an already-sounding voice, with no key-on — **154,910 of them**. They
are kept out of the note stream deliberately: a note is observed at a hardware
edge, a step is inferred from a register write the DSP cannot distinguish from
a pitch bend, and the two are not equally strong claims. Each step names its
parent note. Only about a third of them look melodic; the rest come from
drivers using PITCH for continuous modulation, and the per-game breakdown is in
the docs.

### Score formats

These are the **hardware-indexed** views, kept for comparability with NES-MDB
and for work that needs the chip's own time base. For most research questions
`events/*.json.gz` is the better starting point: it is flat, in seconds, and
explains every absent pitch.

**Implemented**, for all 1,316 tracks, in the same three flavours NES-MDB
publishes:

- *expressive* — per voice-row: `(note, velocity, timbre_class, sustain)`
- *separated* — one row-indexed track per DSP voice, notes only
- *blended* — voices flattened into chords, derived *from* separated so
  polyphony above eight voices is arithmetically impossible

These are lossy, as NES-MDB's are. The blended score loses voice information
and is not recommended for generating novel SNES music; it is included for
comparability.

Two things to know before using the expressive score. **`timbre_class` is `-1`
everywhere** — the codebook failed (see Status), so that channel is inert.
And the fourth channel, `sustain`, exists because `velocity` is only half of
loudness: the DSP computes `env × VOL`, and 20% of notes settle below full
envelope scale. Channel 3 is the sustained amplitude on velocity's own 0..127
scale, so equal means the note holds and lower means it decays to that level.

**Each score file carries two row grids.** The primary one is one SPC700 timer
tick, read from the `$F1`/`$FA`–`$FC` registers the SPC file carries — a
uniform *definition* but not a uniform *duration*, since the rate differs per
game (2.00 ms in Super Mario World against 12.50 ms in Donkey Kong Country,
78 rates corpus-wide).

The `uniform` block re-indexes the same notes at a fixed **100 Hz**, so a row
means exactly 10 ms in every track. **Use `uniform` for anything that compares
tracks or games.** The rate was chosen by benchmarking the corpus at 24, 50,
100 and 200 Hz rather than borrowed: 100 Hz divides the 1,024,000-tick second
exactly (10,240 ticks per row), is achievable on the hardware as T0/T1 ÷ 80,
and loses **one** repeated-note attack among 1,458,211 pitched events — in
Axelay `axe-03`, where two same-pitch attacks fall about 5.1 ms apart. 50 Hz
lost 1,275; 24 Hz lost far more.

It is **not** NES-MDB's rate and makes no claim to cross-corpus
comparability. NES-MDB's scores are 24 Hz. An earlier version of this file
documented 60.0988 Hz here and attributed it to NES-MDB, which was wrong twice
over: that figure is the NES's NTSC *video* frame rate, and it means nothing on
SNES hardware, where the audio CPU runs off its own 1.024 MHz clock.

An earlier design inferred the row period from note onsets instead; it produced
346 distinct rates across 664 tracks and was abandoned. The onset period is
still computed and published as `onset_grid`, because it is a real musical
measurement, but it indexes nothing.

### MIDI

**Implemented** — 1,243 files, one per track with at least one pitched note.
Eight tracks, one per DSP voice, type 1, with no GM program change emitted
because this corpus has no trustworthy instrument mapping to offer. Note that
[VGMTrans](https://github.com/vgmtrans/vgmtrans) already produces good
per-driver SPC→MIDI conversions and exports instrument data as SF2/DLS; if MIDI
is all you need, use that rather than waiting for this.

### Raw format

**Implemented.** The timestamped DSP register write stream as JSONL, plus the
rendered WAV and a dump of the 64K ARAM (which carries the BRR sample directory
and the samples themselves). This is the log everything else is derived from,
provided for anyone who wants to build their own formats.

## The snesmdb tools

You only need to build the C++ tool if you want to process SPCs yourself; the
Python extractor works on an existing log.

```sh
make                        # builds build/spc_dump
make test                   # 399 tests, no skips (bootstraps .venv for pytest)
make corpus                 # full rebuild: ~80 min on 8 jobs
make verify                 # 26 checks on an existing corpus and dist tree
make audit                  # 27 checks, opening EVERY published file
make workflows              # the three dist-only research workflows
make freeze LABEL=rc1       # pin the published tree by file hash
make check-freeze           # re-hash the tree against its pin
```

**pytest is the only Python dependency**, and `make test` creates a `.venv`
for it on first run rather than assuming it is installed. That is not
hypothetical tidiness: the suite was being run through a venv in `/tmp` while
`make test` itself was broken, so the command documented here failed for
anyone who typed it even as the tests were reported passing. Everything else
is the standard library plus one C++ build of vendored unpatched `snes_spc`.

`make corpus` is the only entry point that guarantees the ordering, and the
ordering used to be documented as prose that was **wrong** — it omitted the
step that derived the row clock, which produced a corpus with zero scored
tracks, silently. A recipe that executes cannot drift from the recipe that is
written down, which is why the sequence lives in the Makefile now. `make
verify` exists for the same reason: every one of its checks corresponds to a
defect that really shipped from this pipeline, and not one of them announced
itself.

To poke at a single SPC without building a corpus:

```sh
python3 tools/make_test_spc.py out.spc --notes 6
./build/spc_dump out.spc writes.jsonl 3.0 --wav out.wav --aram out.bin
```

## SNES Synthesizer Primer

The NES's 2A03 hands four constants to anyone extracting music from it. The
SNES's S-DSP hands over none of them, and every difficulty in this project
traces back to this table.

| what an extractor needs | 2A03 | S-DSP |
|---|---|---|
| channel identity | **5 fixed roles** — pulse 1, pulse 2, triangle, noise, DMC — the same in every game | **8 generic voices**, no fixed role, assignment varies per game and can change mid-song |
| timbre vocabulary | a **closed set of 4** duty values, meaning the same thing in all 397 games | an **open set** — "BRR sample #N in this game's ARAM", an arbitrary index with no cross-game meaning |
| pitch | a period register, **one universal formula** to Hz | a 14-bit **resample ratio** relative to each sample's own base frequency, which lives in the game's private instrument table |
| time grid | **60.0988 Hz video frames**, universal; most engines run off the vblank NMI | a **per-track timer**, but it is *stored in the SPC file* — `$FA` over 8 kHz — so it is read, not inferred |

The S-DSP has eight voices, each playing a BRR-compressed sample: 9 bytes per
16 samples, a 4-bit range and 2-bit filter per block, with four integer
predictors. Voices have hardware ADSR envelopes, signed per-channel volume
(negative inverts phase, which drivers use for stereo), optional noise and
pitch modulation, and a global echo unit.

Two consequences for anyone reading the extracted data. Absolute pitch requires
recovering each sample's fundamental from the sample data itself, because no
standard field records it. And a cross-game timbre vocabulary has to be
*constructed* — by decoding every sample in the corpus and clustering them into
classes — where the NES simply has four duty cycles. The first worked for 78.3%
of notes. **The second did not work at all**, which is milestone 5's failure
above.

One row of that table was wrong for most of this project's life, and the
correction is the single most useful thing in it. The time grid was treated as
something to *infer* — fit a period to note onsets, or recover the driver's
tick from its write cadence — and both approaches fought the hardware for
months. The SPC700's timer configuration is part of the dump: `$F1` holds the
enable bits and `$FA`/`$FB`/`$FC` the targets, so the rate the audio CPU woke
up at is simply `8000/$FA`. Reading it reproduced every clock the write-cadence
estimator had found *and* supplied one for the eight games it could not. Three
hypotheses about why inference failed on N-SPC were tested against write logs
and all three were refused: the periodic signal is not hidden, it is absent.

A note on the SRCN column, because it bites harder than it reads. An index does
not name a fixed instrument even *within one game* — each SPC is its own ARAM
snapshot and drivers reload their bank per track, so Super Turrican's 8 indices
resolve to 48 distinct samples across 12 tracks. Identify samples by the hash
of their decoded BRR block, not by index.

## Design decisions

**The C++ tool is deliberately dumb.** It emits raw register writes and nothing
else: no note detection, no pitch conversion, no grid inference. That is all
semantics, it will change many times, and it belongs in Python where it is
cheap to iterate and test. The only thing that cannot be done in Python is
running the SPC700.

**Writes, not polled state.** The driver's register writes *are* the score.
Polling voice state at the output rate would miss a key-on set and cleared
between samples, and would confuse the driver's intent with the DSP's envelope
machinery.

**The test fixture is synthetic, and has to be.** Every real SPC is a
copyrighted game rip, so a project testable only on real SPCs cannot run in CI
or ship a fixture. `tools/make_test_spc.py` hand-assembles a real SPC700 driver
that plays a known sequence through our own BRR sample, giving a deterministic,
redistributable round-trip test: what the driver wrote must be what the
extractor recovers. It has to be executable code rather than a pre-loaded
register dump, because the logger hooks *CPU writes* — a fixture that
configured the DSP through the file's register block would log nothing.

## Licensing and the source data

The code in this repository is MIT licensed, matching NES-MDB.
`vendor/snes_spc` is blargg's snes_spc emulator, **LGPL-2.1**, kept
byte-identical to upstream and never patched — snes_spc already provides the
extension point (`SPC_DSP_WRITE_HOOK`), which the Makefile enables by defining
the macro on the command line.

**SPC files are not in this repository and must not be added.** This is where
snesmdb deliberately departs from NES-MDB's README, which does not address the
copyright of the original game music. The position here is explicit because the
situation is narrower: snesmusic.org, the main SPC archive, offers its files
"for educational and personal non-profit use only... as fair use samples for
preservation purposes only."

So: put SPCs in `data/spc/`, which is gitignored. Treat anything derived from
them as research-use-only. Do not ship models, audio, or datasets derived from
this data commercially without a rights review. If you publish a corpus built
with these tools, say what it was derived from.

`tools/publish.py` enforces a weak form of this by **refusing to write inside a
git work tree**, so a built corpus cannot be committed by accident. That is all
it can enforce. The scores, MIDI and intake trees are derived works of
copyrighted material, and `make verify` additionally fails if any audio or SPC
file is found in a published tree.

## Relationship to the renderer

snesmdb has **no code dependency** on the SNES renderer that consumes its
output, in either direction. The contract is a file format: the extractor
writes intake JSON trees, and the renderer ingests them. The pieces borrowed
from it — a BRR decoder, fundamental-frequency estimation, and onset-grid
detection — are copied rather than imported, because a one-way copy beats a
circular dependency between a dataset tool and its consumer.

The borrowed onset-grid detection is still here and still runs, but it no
longer decides anything: rows are indexed on the SPC700 timer register
instead. The intake schema's shape is documented and is **not** verified
against the renderer's `acquire(from_extracted=True)`, which lives in a
sibling project not present here — that is recorded as a limitation rather
than assumed compatible.

## Attribution

This project's design is taken directly from NES-MDB, including its format
family and its composer-disjoint split convention. If you use snesmdb, please
also cite the work it is modelled on:

```
@inproceedings{donahue2018nesmdb,
  title={The {NES} {M}usic {D}atabase: A multi-instrumental dataset with expressive performance attributes},
  author={Donahue, Chris and Mao, Huanru Henry and McAuley, Julian},
  booktitle={ISMIR},
  year={2018}
}
```

The emulator that makes extraction possible is Shay Green's (blargg's)
snes_spc.
