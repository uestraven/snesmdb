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

**Status: [milestone 1 of 6](docs/milestones.md).** The SPC700 runs, every DSP register write is
logged with absolute timestamps, and notes are recovered from that log. No real
SPC has been processed yet, pitch is still a raw register value, and there is
no timbre vocabulary. Formats below are marked accordingly. Nothing here is a
published dataset yet.

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

Planning docs: [milestones](docs/milestones.md), [design](docs/design.md).

## Dataset information

Pick a format by background. If you want to do algorithmic composition, use a
score format or MIDI. If you are coming from sequence modelling, the voice
event log is the closest thing to a token stream. If you want to build your own
representation, start from the raw format.

### Voice event log

**Implemented.** One record per sounding voice: key-on and key-off times in
SPC700 clocks, the 14-bit PITCH register, the sample index (SRCN), left and
right volume, and the envelope registers (ADSR1, ADSR2, GAIN).

Caveats, because they decide whether this format suits you. Pitch is the raw
register value — a *resample ratio*, not a note number — so intervals are
exact but absolute pitch is not yet available. Voices playing noise (NON) or
under pitch modulation (PMON) are flagged rather than given a pitch, since the
PITCH register does not describe what sounded. A note still running when the
log ends is marked unfinished rather than given an invented end time.

### Score formats

**Planned (milestones 3–5).** Dense piano-roll representations on an inferred
tracker grid, in the same three flavours NES-MDB publishes:

- *expressive* — full per-voice state: pitch, velocity, and timbre class
- *separated* — notes only, velocity and timbre dropped
- *blended* — voices flattened into chords

These are lossy, as NES-MDB's are. The blended score loses voice information
and is not recommended for generating novel SNES music; it is included for
comparability.

The expressive score needs a **timbre vocabulary**, which the NES gets for free
and the SNES does not (see the primer). Building one is the main open research
problem in this project, not a detail.

### MIDI

**Planned (milestone 6).** Eight tracks, one per voice. Note that
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
make                                   # builds build/spc_dump
python3 tools/make_test_spc.py out.spc --notes 6
./build/spc_dump out.spc writes.jsonl 3.0 --wav out.wav --aram out.bin
pytest                                 # 13 tests, no skips
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
| time grid | **60.0988 Hz video frames**, universal; music advances on frames | a **per-driver tick rate** — N-SPC, AKAO, Rare, Konami, Capcom and Hudson all differ |

The S-DSP has eight voices, each playing a BRR-compressed sample: 9 bytes per
16 samples, a 4-bit range and 2-bit filter per block, with four integer
predictors. Voices have hardware ADSR envelopes, signed per-channel volume
(negative inverts phase, which drivers use for stereo), optional noise and
pitch modulation, and a global echo unit.

Two consequences for anyone reading the extracted data. Absolute pitch requires
recovering each sample's fundamental from the sample data itself, because no
standard field records it. And a cross-game timbre vocabulary has to be
*constructed* — by decoding every sample in the corpus and clustering them into
classes — where the NES simply has four duty cycles.

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

## Relationship to the renderer

snesmdb has **no code dependency** on the SNES renderer that consumes its
output, in either direction. The contract is a file format: the extractor
writes intake JSON trees, and the renderer ingests them. The pieces borrowed
from it — a BRR decoder, fundamental-frequency estimation, and onset-grid
detection — are copied rather than imported, because a one-way copy beats a
circular dependency between a dataset tool and its consumer.

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
