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

**2,228 tracks from 50 games.** 3,499,685 events, composer-disjoint splits,
every track clocked from its own SPC700 timer register. Event schema
`snesmdb.events.v4`. Current release: **`snesmdb-50game-rc1`**.

The corpus has grown through four extraction cohorts and three combined
releases, so **a figure belongs to one population and is not portable
between them.** Everything below is measured from `snesmdb-50game-rc1`'s own
artifacts; the full table of seven populations is in
[DATASET.md](docs/DATASET.md). Earlier releases are immutable and remain
correct about their own populations — a paper citing the 27-game release
needs no revision.

Do not add figures across populations. The four cohorts partition the corpus
by *track* (1,316 + 161 + 362 + 389 = 2,228) and by nothing else: sample
banks overlap, so even the distinct-identity count is not a sum.

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
  - [Raw format — not distributed](#raw-format--not-distributed)
- [Verified research results](#verified-research-results)
- [Audio rendering](#audio-rendering)
- [Tools](#tools)
- [SNES Synthesizer Primer](#snes-synthesizer-primer)
- [Limitations](#limitations)
- [Licensing and the source data](#licensing-and-the-source-data)
- [Citing SNES-MDB](#citing-snes-mdb)
- [Attribution](#attribution)

## Installation

**pytest is the only Python dependency**, and `make test` creates a `.venv`
for it on first run. Everything else is the standard library plus one C++
build of vendored `snes_spc`.

```sh
git clone https://github.com/uestraven/snesmdb.git && cd snesmdb
make                  # builds build/spc_dump
make test             # 664 tests, no skips
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

`midi/*.mid`, for **2,115 of the 2,228 tracks**. Only attacks carrying a
usable fixed-pitch estimate can be written, so **669,685 of 3,205,461
attacks (20.89%) are absent** — see the MIDI section of
[DATASET.md](docs/DATASET.md) for the full reconciliation. MIDI is a lossy
projection, not the dataset.

Every omitted attack is accounted for:

| reason | attacks |
|---|---|
| no pitch recovered | 664,538 |
| track has no MIDI file at all | 5,060 |
| pitch outside the MIDI range | 87 |
| **total omitted** | **669,685** |

Only the last 87 carry a fixed-pitch estimate that an exporter could have
written; the other 669,598 have no single note to write, and writing one
would fabricate it. **That is not a claim they were unpitched** —
`unrecoverable` means the pipeline could not determine a pitch, and
`pitch_modulated` may be musically pitched material that one static note
cannot represent.

The 113 tracks without a MIDI file are all `complete_unpitched_only` (78) or
`complete_no_events` (35); none has a pitched attack, so no exportable
musical content is missing.

### Raw format — **not distributed**

The timestamped DSP register write stream as JSONL, plus a dump of the 64K
ARAM carrying the BRR sample directory and the samples. Everything else is
derived from this.

**No release contains it.** The ARAM dump holds the game's BRR samples —
copyrighted audio — so shipping it would ship the music itself, and the
write log is large enough that distributing it is a separate decision
nobody has made. `records/` and `raw/` exist only inside a build tree.

It is documented because it is the input the rest of the pipeline is defined
against, and because a reader comparing their own extraction needs to know
what the stages consume. To obtain it, run the extractor over SPC files you
supply yourself:

```sh
./build/spc_dump track.spc writes.jsonl 30 --aram out.bin
```

## Verified research results

All figures are for **`snesmdb-50game-rc1`**, the current release, and are
measured from its own published artifacts — not combined from the cohorts it
contains.

They are not transcribed by hand. In a source checkout,
`make census RELEASE=<dir>` recomputes every one of them from a release
directory into `docs/corpus_census_50game.json`, and the test suite asserts
this table matches that artifact. The README fell three expansions behind
once; it cannot now do so silently. (That artifact is a repository build
product and is not shipped — a release already carries the same authoritative
figures in `index.json` and `RELEASE.json`.)

| | |
|---|---|
| tracks / games | 2,228 / 50 |
| splits (train / valid / test) | 1,785 / 225 / 218 tracks over 33 / 9 / 8 games, composer-disjoint |
| events | 3,499,685 — 3,205,461 attacks + 294,224 legato steps |
| attacks with a recovered pitch | 2,535,863 (**79.11%**) |
| attacks with an established sample identity | 3,189,942 (**99.52%**) |
| attacks published with `sample_id: null` | 15,519 |
| distinct sample identities | 2,118 |
| tracks with a clock read from a timer register | 2,228 (**100%**) |
| tracks with a MIDI file | 2,115 |
| tracks carrying a truncated composer credit | 406 |

Per-population figures, including every superseded release's, are in
[DATASET.md](docs/DATASET.md).

In a source checkout these are re-checked by `make audit`, which opens every
published file. From a release archive alone, the reproducible check is the
interval baseline in `toolkit/` (see `REPRODUCE.md`) — **whose figures are
scoped to the 27-game population it was run on and were not recomputed for
this release.**

**This corpus unions four cohorts; it is not a demonstration that their
extraction paths agree.** The 22-game cohort's identities were corrected
after extraction, so its pitch estimates come from the capture-time sample
directory; the three later cohorts resolved identity at key-on, so their
pitch comes from the sample actually used. Because pitch is estimated from a
sample's audio, the oldest cohort's pitched share may understate what the
newer path would recover — on one game the same audio yielded 40.63% versus
91.72%. Quantifying that for the 1,316-track cohort is a separate versioned
study, not part of this release, so **the corpus-wide 79.11% is a mixture of
two methods** rather than one method's result.

**Absolute pitch is recoverable for 79.11% of attacks.** No SNES field records
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
make test                   # 664 tests, no skips (bootstraps .venv for pytest)
make corpus                 # full rebuild: ~80 min on 8 jobs
make verify                 # schema, reconciliation and contract checks, sampled
make audit                  # the same checks exhaustively, opening EVERY published file
make census RELEASE=<dir>   # measure the figures this documentation quotes
make workflows              # dist-only research workflows
make freeze LABEL=rc1       # pin a published tree by file hash
make check-freeze           # re-hash a tree against its pin
```

`verify` and `audit` run the same assertions; the difference is coverage.
`verify` samples, so it is fast enough to run on every build and reports
`n/a` for anything a sample cannot establish. `audit` opens every published
file and is the gate before a release is frozen. Both print one line per
check with its own count, so the count to trust is the one they print —
neither this README nor any other document hardcodes how many checks exist,
because that number changes whenever an assertion is added.

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

- **The splits are assigned by game, so held-out evaluation confounds
  several factors.** Composer credits attach to games in the source
  metadata, so a held-out score differs from training data in composer *and*
  in genre, sound driver and instrument bank at once. A model scoring poorly
  on `test` does not isolate composer generalisation. The defensible claim
  is held-out-**game** evaluation.
- **Split assignments are recomputed per population and do not carry across
  releases.** A split is a property of the population it was drawn from, so
  the 50-game assignment (1,785 / 225 / 218 tracks over 33 / 9 / 8 games) is
  not an extension of the 27-game one: a track in `test` there may be in
  `train` here. Results are comparable only within one release. Splits are
  also assigned per **game family**, so regional releases of one game cannot
  land on both sides of the partition.
- **406 of 2,228 tracks carry a truncated composer credit**, cut mid-name at
  the ID666 32-byte limit. `composer_truncated` marks them. A truncated tag
  is not a confirmed identity, and a game-level credit does not establish
  track-level authorship. The corpus records **80 distinct credit strings**
  (72 of them on music tracks), of which **10 are truncation fragments**
  rather than names and cover all 406 of those tracks. No credit string
  spans two splits, but **three fragments are prefixes of complete credits
  on the other side of the partition** — `Ke` (train) of both
  `Kenji Yamamoto` and `Kemco sound team` (valid), and `Yoko Shimom`
  (valid) of `Yoko Shimomura` (train). Whether they name the same person is
  not decidable from the published data, so disjointness is a property of
  the **strings**, which is weaker than disjoint authorship. 725 tracks
  credit several contributors, so even a complete credit does not establish
  who wrote a given track.
- **No cross-game instrument vocabulary.** See
  [Verified research results](#verified-research-results).
- **20.89% of attacks have no recovered pitch.** Filter on `pitch_status`.
- **15,519 attacks have no sample identity** (0.48%), and they are not spread
  evenly: **only 5 of the 50 games have any**, and **96.4% are Super
  Turrican alone** (14,954), whose driver rewrites the sample directory
  continuously. The rest are Donkey Kong Country 2 (211), Earthbound (178),
  Secret of Evermore (161) and Shadowrun (15). Their directory entry was
  unwritten memory at key-on (15,341) or no entry existed (178). Published
  as `null` with `sample_id_unresolved_reason` — so a study that excludes
  one game loses almost all of the corpus's identity uncertainty, and one
  that pools games inherits it from a single soundtrack.
- **The `drivers` block covers 22 of the 50 games.** Those labels are
  curated external knowledge and were not extended to the later cohorts. A
  missing label means nobody recorded the engine, not that the track lacks
  one; and a label is a hypothesis to test, not a measurement.
- **Sample bytes are read from the capture-time ARAM.** A confirmed directory
  address does not establish that the sample's bytes were unchanged during
  playback. This remains open.
- **10 attacks differ only in loop point.** A note that never reaches its loop
  has no observable loop destination, so for those the loop component of the
  identity rests on the directory word present at key-on. (Measured on the
  22-game cohort; not recomputed for the full corpus.)
- **The uniform 100 Hz grid loses one attack** in 1,863,499 — two events
  5.1 ms apart in one Axelay track. (Also a 22-game cohort measurement. The
  grid's resolution is unchanged, so the failure mode still applies; the
  count does not cover the later cohorts.)
- **Several limitations above were measured on one population.** Where a
  figure is cohort-scoped it says so. A limitation stated for the cohort has
  not been shown absent from the rest of the corpus — it has not been
  re-measured there.
- **The intake schema is not verified against the renderer** it was designed
  for, which lives in a separate project.
- `timbre_class` is inert, and `max_polyphony` carries a note about its
  pre-v3 meaning.

A fuller account of what the corpus gets wrong is in
[DATASET.md](docs/DATASET.md).

## Licensing and the source data

The code in this repository is MIT licensed ([`LICENSE`](LICENSE)), matching
NES-MDB. **That license covers the code and nothing else** — not the musical
compositions, not the symbolic datasets, not SPC files, and not the vendored
emulator. [`RIGHTS.md`](RIGHTS.md) sets out each boundary; read it before
redistributing anything built with these tools.

`vendor/snes_spc` is blargg's snes_spc emulator, **LGPL-2.1**, governed by its
own license. The production extractor uses snes_spc's own extension point
(`SPC_DSP_WRITE_HOOK`), enabled by a macro definition. One vendored file
carries **three marked instrumentation hooks** used only by the
`spc_dump_evt` research build, which observe when the DSP commits a sample
start, accepts a key-on, and takes a loop. Those changes, their dates and the
LGPL obligations they create are documented in
`vendor/snes_spc/MODIFICATIONS.md` in the source repository, alongside an
unmodified copy of the upstream file; `make verify-vendor` diffs the two, and
`make verify-instrumentation` proves the instrumented build produces
bit-identical audio to the production one. A data distribution ships no
emulator source, so neither that document nor the vendored tree is present in
one.

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

## Citing SNES-MDB

Citation metadata is in [`CITATION.cff`](CITATION.cff), which GitHub and most
reference managers read directly. It carries no DOI yet; one requires a
hosting decision that is gated on the rights review above.

## Attribution

This project's design is taken directly from NES-MDB, including its format
family and its composer-disjoint split convention. Cite SNES-MDB for
SNES-MDB; cite NES-MDB **in addition** if the design lineage or the split
convention matters to your work:

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
