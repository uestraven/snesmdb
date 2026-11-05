# Input SPC files

Put `.spc` files here. **This directory is gitignored on purpose** — SPCs are
copyrighted game music, offered by snesmusic.org "for educational and personal
non-profit use only... as fair use samples for preservation purposes only."
Only this README is tracked.

The test suite does not need them: `tools/make_test_spc.py` generates a
synthetic SPC from our own code and our own BRR sample, which is what CI uses.

## File format

| requirement | value |
|---|---|
| extension | `.spc` (case-insensitive) — **nothing else is read** |
| signature | `SNES-SPC700 Sound File Data` at offset 0 |
| minimum size | 65,920 bytes (`0x10180`) — header + ARAM + DSP registers |
| normal size | 66,048 bytes (`0x10200`) |
| ID666 tag | v0.30 text or binary layout; both are handled |

The layout the loader relies on is just the SPC format itself:

```
0x00000  header, 256 bytes  (signature, PC/A/X/Y/PSW/SP, ID666 tag)
0x00100  ARAM, 64 KiB       (BRR sample directory + samples live here)
0x10100  DSP registers, 128 bytes
0x10180  (optional extra RAM — not required)
```

A file failing the signature or size check is recorded in `manifest.jsonl`
with `ok: false` and a reason. It is never silently dropped.

## Directory structure

**Any structure works.** The runner recurses with `rglob`, so nesting by game,
by region, or one flat directory are all equally fine:

```
data/spc/                         data/spc/
  ChronoTrigger/                    ct-01-title.spc
    01-title.spc          or        ct-02-battle.spc
    02-battle.spc                   ff6-01-prelude.spc
  FinalFantasyVI/
    01-prelude.spc
```

Two things the filename does affect:

- The **stem becomes part of the track id** (`<stem>:<sha256[:12]>`), and that
  id names the per-track record file. Use filesystem-safe names. The sha
  suffix handles collisions, but `01.spc` repeated across twenty directories
  makes a manifest nobody can read.
- Nothing else. Game, track title and composer are read from the **ID666 tag
  inside the file**, never from the path.

## ID666 tags matter more than you would expect

The tag is where game, track title and composer come from, and the composer is
what builds the **composer-disjoint splits** that make this corpus comparable
to NES-MDB.

An untagged SPC still extracts — notes, timing and validation all work — but it
gets `game: "unknown:<track_id>"` and an empty composer. Each untagged track
therefore becomes its own game *and* its own composer component, so
composer-disjointness comes out trivially true and **means nothing**. A corpus
of untagged files will report `composer_disjoint: true` while guaranteeing no
such thing.

So prefer tagged SPCs; snesmusic.org's sets are tagged. Check what you have
before running a long extraction:

```sh
PYTHONPATH=src python3 -c "
from pathlib import Path
from snesmdb.spcfile import load
for p in sorted(Path('data/spc').rglob('*.spc')):
    t = load(p).tag
    print(f'{p.name:40} {t.layout:7} {t.game[:24]:24} {t.composer[:24]}')
"
```

Any row showing `unknown` for layout, or a blank game or composer, weakens the
splits.

## RSN files must be unpacked first

snesmusic.org ships sets as `.rsn`, which is **a renamed RAR archive**, and the
whole-archive torrent is RSN as well. `.rsn` is not read. The runner prints a
warning naming the archives it skipped, and exits if that leaves nothing, so a
directory of downloads cannot quietly produce an empty corpus.

Unpack with whichever tool you have:

```sh
7z x set.rsn -o./unpacked/        # p7zip
unrar x set.rsn ./unpacked/       # unrar
unar -o ./unpacked/ set.rsn       # unar  (macOS: brew install unar)
```

RSN support is deliberately not built in: no RAR tooling existed on the machine
where this was written, and shipping an extraction path that was never executed
is how a silent failure gets into a pipeline.

## What to start with

A curated dozen or two, not the full archive — and chosen to **span sound
drivers**, because driver variety is what will break the extractor, not track
count. The major families are Nintendo's N-SPC, Square's AKAO, Rare's,
Konami's, Capcom's and Hudson's. Twenty Square games validate one driver twenty
times.

## Known gap: duplicate dumps

Byte-identical files are deduplicated by sha256, but the *same music* re-dumped
for another region is not detected — NTSC, PAL and NTSC-J are separate sets on
snesmusic.org, each with its own id. NES-MDB records this as `duplicate_of`;
this project has no equivalent yet, so a region-complete corpus will contain
near-duplicates, and the split components will be larger than they appear.
