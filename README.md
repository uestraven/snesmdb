# The SNES Music Database

snesmdb is a dataset of music from the Super Nintendo Entertainment System
(Super Famicom), for research on automatic music composition and analysis.
It is the SNES counterpart to
[NES-MDB](https://github.com/chrisdonahue/nesmdb), and follows that project's
design closely: the goal is to let researchers study SNES music without
working through the inner workings of the S-DSP.

That shielding is harder on the SNES than on the NES, and the reasons shape
every format choice here — see the
[SNES Synthesizer Primer](#snes-synthesizer-primer).

**1,316 tracks from 22 games.** 2,018,409 events, composer-disjoint splits,
every track clocked from its own SPC700 timer register. Current release
`gate5-rc10`, event schema `snesmdb.events.v4`.

**If you are here to do research, start with `events/*.json.gz`** — the flat
event table in seconds, described in [DATASET.md](docs/DATASET.md). The score,
MIDI and intake formats are hardware-indexed views that need more context to
read correctly.

## Contents

- [Installation](#installation)
- [Dataset](#dataset)
  - [Voice event log](#voice-event-log)
  - [Score formats](#score-formats)
  - [MIDI](#midi)
  - [Raw format](#raw-format)
- [Verified research results](#verified-research-results)
- [Audio rendering](#audio-rendering)
- [Tools](#tools)
- [SNES Synthesizer Primer](#snes-synthesizer-primer)
- [Limitations](#limitations)
- [Licensing and the source data](#licensing-and-the-source-data)
- [Attribution](#attribution)

## Installation

**pytest is the only Python dependency**, and `make test` creates a `.venv`
for it on first run. Everything else is the standard library plus one C++
build of vendored `snes_spc`.

```sh
git clone <repo> && cd snesmdb
make                  # builds build/spc_dump
make test             # 543 tests, no skips
```

You only need the C++ tool to process SPC files yourself; the Python
extractor works from an existing register log.

SPC files are **not** included and must not be added to the repository — see
[Licensing](#licensing-and-the-source-data). Place them in `data/spc/`, which
is gitignored, then:

```sh
make corpus           # extract, score, publish, verify
```

## Dataset

Pick a format by background. For algorithmic composition, use a score format
or MIDI. For sequence modelling, the voice event log is closest to a token
stream. To build your own representation, start from the raw format.

### Voice event log

One record per sounding voice: key-on and key-off times in SPC700 clocks, the
14-bit PITCH register, the sample identity, left and right volume, and
envelope parameters. `events/*.json.gz` is the researcher-facing view of this
in seconds, one flat row per event.

Each key-on carries a **`sample_id`**: a content hash of the decoded BRR
audio, and the field most likely to be misread. It identifies a *sound
source* reproducibly; it is **not an instrument label**, and carries no claim
that a sample plays a consistent musical role.

`sample_id` is `null` where no identity could be established, with
`sample_id_unresolved_reason` saying why. An uncertain identity is published
as null and never filled in with a plausible-looking substitute. Test
truthiness, not `is not None`.

### Score formats

Two views indexed on hardware rows rather than seconds: an *expressive* score
preserving the driver's own row timing, and a *uniform* score resampled to a
**100 Hz grid — one row every 10 ms**, exactly 10,240 SPC700 clocks. Both are
in `scores/*.json.gz`.

The expressive score's row duration is the driver's own and varies across the
corpus; the uniform score's does not. Use the uniform score when rows must be
comparable across tracks, and the expressive one when the driver's timing is
the object of study.

### MIDI

`midi/*.mid`, for 1,243 tracks. Only notes with a recovered pitch can be
written, so 402,635 of 1,863,499 attacks are absent — unpitched percussion
and noise mostly. MIDI is a lossy convenience view, not the dataset.

### Raw format

The timestamped DSP register write stream as JSONL, plus a dump of the 64K
ARAM carrying the BRR sample directory and the samples. Everything else is
derived from this.

## Verified research results

Figures below are measured from the published release and re-checked by
`make audit`, which opens every file.

| | |
|---|---|
| tracks / games | 1,316 / 22 |
| splits (train / valid / test) | 1,049 / 135 / 132, composer-disjoint |
| events | 2,018,409 — 1,863,499 attacks + 154,910 legato steps |
| attacks with a recovered pitch | 1,458,211 (**78.3%**) |
| attacks with an established sample identity | 1,848,156 (**99.177%**) |
| attacks published with `sample_id: null` | 15,343 |
| distinct sample identities | 1,132 |
| tracks with a clock read from hardware | 1,316 (**100%**) |

**Absolute pitch is recoverable for 78.3% of attacks.** No SNES field records
a sample's base frequency, so pitch requires estimating each sample's
fundamental from its decoded audio. The remainder are unpitched or
unrecoverable and are marked as such — `pitch_status` is the field to filter
on, and only `estimated` is a pitch.

**Every published sample identity was observed at key-on.** Sample identity is
resolved from the directory entry the S-DSP actually read when the voice was
keyed on, captured by instrumenting the emulator's DSP at the point it
commits a sample start. This matters because drivers rewrite directory entries
during playback, so one SRCN index can address different audio at different
moments in the same track. No identity in this release rests on the
capture-time directory alone.

**A cross-game timbre vocabulary is not achievable from this data**, and the
dataset says so rather than shipping a weak one. Class agreement across games
collapses to the shuffled null once features that leak game identity are
removed. No codebook is shipped, and `timbre_class` is an inert field:

| format | `timbre_class` |
|---|---|
| `events/*.json.gz` | **absent** |
| `scores/*.json.gz` | present as the expressive score's third channel, always `-1` |
| `intake/*.json.gz` | present per note, always `-1` |

It remains in the two older formats because removing a published field is a
breaking change. Each expressive block reports
`timbre_validated: "tonal_vs_percussive_only"` and
`timbre_classes_present: [-1]` so the limitation travels with the data.

**A sample index is not an instrument.** Each SPC is its own ARAM snapshot and
drivers reload their bank per track, so Super Turrican's 8 indices resolve to
dozens of distinct samples across its tracks. Identify samples by
`sample_id`, never by index.

## Audio rendering

Two separate things can produce audio, and they answer different questions.

**The emulator** renders a track the way the hardware does:

```sh
./build/spc_dump track.spc writes.jsonl 30 --wav out.wav --aram out.bin
```

This is the reference. It requires an SPC file.

**`snesmdb.render`** is a minimal, deterministic playback engine that sounds
the *published records* — note times, durations, pitches and levels — using
sample audio you supply. It exists to check that the dataset represents what
a listener hears, and it is intentionally not a synthesizer: it models no
stereo image, no echo unit, no ADSR rates, no pitch modulation or noise, and
resamples by nearest neighbour. None of those are in the published
representation, so a render cannot recover them.

It needs a sample bank because **`sample_id` is a content hash, not audio**.
The dataset ships no audio (see [Licensing](#licensing-and-the-source-data)),
so the bank must be decoded locally from your own SPC files, keyed by
`sample_id`. Where a record's identity is `null`, the engine renders silence
and reports it rather than substituting a sample.

## Tools

```sh
make                        # build build/spc_dump
make test                   # 543 tests, no skips (bootstraps .venv for pytest)
make corpus                 # full rebuild: ~80 min on 8 jobs
make verify                 # 37 checks on an existing corpus and dist tree
make audit                  # 39 checks, opening EVERY published file
make workflows              # dist-only research workflows
make freeze LABEL=rc1       # pin a published tree by file hash
make check-freeze           # re-hash a tree against its pin
```

`make corpus` is the only entry point that guarantees the correct ordering of
extraction, scoring and publication.

To inspect a single SPC without building a corpus:

```sh
python3 tools/make_test_spc.py out.spc --notes 6
./build/spc_dump out.spc writes.jsonl 3.0 --wav out.wav --aram out.bin
```

**Docs that ship with the corpus.** [DATASET.md](docs/DATASET.md) is the
deliverable — what the corpus contains and what it gets wrong.
[SCHEMA.md](docs/SCHEMA.md) is the field-by-field contract.
[CHANGELOG.md](docs/CHANGELOG.md) carries the release notes, including every
breaking change and its compatibility implications. All three are copied into
every published tree, so a download is self-describing.

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
16 samples, with a 4-bit range and 2-bit filter per block and four integer
predictors. Voices have hardware ADSR envelopes, signed per-channel volume
(negative inverts phase, which drivers use for stereo), optional noise and
pitch modulation, and a global echo unit.

Three consequences for anyone reading the extracted data. Absolute pitch has
to be recovered from the sample audio, because no field records it. A
cross-game timbre vocabulary has to be *constructed* rather than read off,
and does not survive validation. And sample identity is a property of a
*moment*, not of an index: the DSP reads the directory entry at key-on, and
drivers rewrite those entries while the music plays.

The time grid is the one row where the hardware is generous, and it is worth
stating plainly because it is easy to miss. The SPC700's timer configuration
is part of the dump — `$F1` holds the enable bits and `$FA`/`$FB`/`$FC` the
targets — so the rate the audio CPU woke at is `8000/$FA`. It is read
directly, not inferred from note onsets.

## Limitations

Stated here because they bound what the data supports, not as caveats to skim:

- **No cross-game instrument vocabulary.** See
  [Verified research results](#verified-research-results).
- **21.7% of attacks have no recovered pitch.** Filter on `pitch_status`.
- **15,343 attacks have no sample identity.** Their directory entry was
  unwritten memory at key-on, or no entry existed. Published as `null`.
- **Sample bytes are read from the capture-time ARAM.** A confirmed directory
  address does not establish that the sample's bytes were unchanged during
  playback. This remains open.
- **10 attacks differ only in loop point.** A note that never reaches its loop
  has no observable loop destination, so for those the loop component of the
  identity rests on the directory word present at key-on.
- **The uniform 100 Hz grid loses one attack** in 1,863,499 — two events
  5.1 ms apart in one Axelay track.
- **The intake schema is not verified against the renderer** it was designed
  for, which lives in a separate project.
- `timbre_class` is inert, and `max_polyphony` carries a note about its
  pre-v3 meaning.

A fuller account of what the corpus gets wrong is in
[DATASET.md](docs/DATASET.md).

## Licensing and the source data

The code in this repository is MIT licensed, matching NES-MDB.
`vendor/snes_spc` is blargg's snes_spc emulator, **LGPL-2.1**. The production
extractor uses snes_spc's own extension point (`SPC_DSP_WRITE_HOOK`), enabled
by a macro definition. The vendored DSP additionally carries **three marked
instrumentation hooks** used only by the `spc_dump_evt` research build, which
observe when the DSP commits a sample start, accepts a key-on, and takes a
loop; `make verify-vendor` shows the diff against upstream, and
`make verify-instrumentation` proves the instrumented build produces
bit-identical audio to the production one.

**SPC files are not in this repository and must not be added.** This is a
deliberate departure from NES-MDB's README, which does not address the
copyright of the original game music. snesmusic.org, the main SPC archive,
offers its files "for educational and personal non-profit use only... as fair
use samples for preservation purposes only."

So: put SPCs in `data/spc/`, which is gitignored. Treat anything derived from
them as research-use-only. Do not ship models, audio, or datasets derived from
this data commercially without a rights review. If you publish a corpus built
with these tools, say what it was derived from.

`tools/publish.py` enforces a weak form of this by **refusing to write inside
a git work tree**, so a built corpus cannot be committed by accident. The
score, MIDI and intake trees are derived works of copyrighted material, and
`make verify` fails if any audio or SPC file is found in a published tree.

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
