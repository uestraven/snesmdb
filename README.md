# snesmdb

A SNES music database: symbolic SNES game music extracted from SPC files, in
the shape NES-MDB publishes for the NES.

**Status: milestone 1.** The SPC700 runs, every DSP register write is logged
with absolute timestamps, and notes are recovered from that log. Pitch is
still a raw register value, there is no timbre vocabulary, and no real SPC has
been processed yet. See `docs/` for the full design.

## Why this is hard, in one table

NES-MDB is mechanical because the 2A03 gives away everything for free. The
S-DSP gives away none of it.

| what NES-MDB relies on | 2A03 | S-DSP |
|---|---|---|
| channel identity | 5 **fixed** roles, same in every game | 8 **generic** voices, no fixed role |
| timbre vocabulary | **closed set of 4** duty values | **open set** — a per-game BRR sample index |
| pitch | a period register, one universal formula | a **resample ratio** against the sample's own base frequency |
| time grid | **60.0988 Hz frames**, universal | per-driver tick rate |

So the four constants NES hands over are, on SNES, either per-game or absent.
That is the entire problem, and it is why NSF datasets are commonplace while
no SNES equivalent is published.

## Layout

```
tools/spc_dump.cpp      the logger: runs an SPC, emits timestamped DSP writes
tools/make_test_spc.py  generates a synthetic SPC (our own code and sample)
src/snesmdb/voices.py   write log -> notes
vendor/snes_spc/        blargg's SPC700 + S-DSP emulator, UNMODIFIED
```

## Build and run

```sh
make                                   # builds build/spc_dump
python3 tools/make_test_spc.py out.spc --notes 6
./build/spc_dump out.spc writes.jsonl 3.0 --wav out.wav --aram out.bin
pytest                                 # 13 tests, no skips
```

## Two design decisions worth knowing

**The C++ tool is deliberately dumb.** It emits raw register writes and
nothing else — no note detection, no pitch conversion, no grid inference. All
of that is semantics that will change many times, and it belongs in Python
where it is cheap to iterate and test. The only thing that *cannot* be done in
Python is running the SPC700.

Logging writes rather than polling DSP state is also deliberate: the driver's
writes **are** the score. Polling at the output rate would miss a KON set and
cleared between samples, and would confuse the driver's intent with the DSP's
envelope machinery.

**The test fixture is synthetic, and it has to be.** Every real SPC is a
copyrighted game rip, so a project testable only on real SPCs cannot be tested
in CI and cannot ship a fixture. `make_test_spc.py` hand-assembles a real
SPC700 driver that plays a known sequence through our own BRR sample, giving a
deterministic, redistributable round-trip test: what the driver wrote must be
what the extractor recovers. It has to be real executable code rather than a
pre-loaded register dump, because the logger hooks *CPU writes* — a fixture
that configured the DSP through the file's register block would log nothing.

## Vendored code and licensing

`vendor/snes_spc` is blargg's snes_spc, **LGPL-2.1**, kept byte-identical to
upstream. It is never patched: snes_spc already provides the extension point
(`SPC_DSP_WRITE_HOOK`, in `SNES_SPC::dsp_write`), and the Makefile enables it
by defining the macro on the command line with `src/hook.h` force-included.

**SPC files are not in this repository and must not be.** They are copyrighted
game music; snesmusic.org, the main archive, offers them "for educational and
personal non-profit use only... as fair use samples for preservation purposes
only." Put them in `data/spc/`, which is gitignored. Anything derived from
them is research-use-only and does not ship in a product.

This separation from the engine that consumes the output is the reason this is
its own repository: LGPL vendored code and research-only data stay out of a
codebase heading for public release.

## Relationship to the engine

No code dependency, in either direction. The contract is a file format: the
extractor writes intake JSON trees, and the engine ingests them with
`acquire(..., from_extracted=True)`. The three pieces borrowed from it — a BRR
decoder, fundamental-frequency estimation, and onset-grid detection — are
copied rather than imported, because a one-way copy beats a circular
dependency between a dataset tool and its consumer.
