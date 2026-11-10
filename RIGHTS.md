# Rights

`LICENSE` is the unmodified MIT license. It carries no extra conditions, and
nothing in this document adds any — a condition bolted onto MIT would make the
license non-standard and unusable by the automated tooling that researchers
and legal reviewers rely on.

What this document does instead is state **what MIT in this repository
actually covers**, because the scope of a license is set by what the licensor
owns, not by where the file sits. A `LICENSE` file at the root of a repository
is routinely read as covering everything beside it. Here it does not, and the
difference matters before anyone redistributes.

## MIT covers the code

The MIT grant applies to the original SNES-MDB software: `src/snesmdb/`,
`tools/`, `tests/`, the `Makefile`, and the documentation in this repository.
Use it, modify it, redistribute it, build on it commercially — MIT terms,
no further permission needed.

## MIT does not cover four other things

### 1. The musical compositions

The music these tools analyse is copyrighted commercial work by its
composers and publishers. Extracting a symbolic representation does not
transfer, dilute, or exhaust that copyright, and this project holds no
rights in it to license. **No permission to use the underlying compositions
is granted here, and none is implied.**

### 2. The symbolic datasets

The published event tables, scores, MIDI files, intake trees and derived
statistics are derived works of those compositions. Their redistribution
terms are **unresolved**, pending a rights review that has not happened.

This is a deliberate open question, not an oversight. Symbolic transcription
sits in genuinely unsettled territory: a pitch-and-timing representation is
not a recording, but it is also not an independent work. Resolving it
requires a rights determination this project is not in a position to make,
so the frozen releases are held locally and no data license is asserted.

Treat the corpus and anything trained on it as **research use only** until
that review concludes. If you publish work built from it, say what it was
derived from. Do not assume MIT extends to it because `LICENSE` is nearby.

### 3. SPC files

SPC files are rips of copyrighted game audio. They are **never present in
this repository and never ship in any published artifact** — `data/spc/` is
gitignored, `tools/publish.py` refuses to write inside a git work tree, and
`make verify` fails if an SPC or audio file appears in a published tree.

snesmusic.org, the principal archive, offers its files "for educational and
personal non-profit use only... as fair use samples for preservation
purposes only." Obtain them yourself under those terms; this project
distributes none of them.

### 4. `vendor/snes_spc`

Shay Green's (blargg's) snes_spc emulator, licensed **LGPL-2.1** — not MIT.
Its own license governs it. The LGPL-2.1 text is preserved at
`vendor/snes_spc/license.txt` and `vendor/snes_spc/LICENSE`, and the
modifications made for this project are listed with dates in
[`vendor/snes_spc/MODIFICATIONS.md`](vendor/snes_spc/MODIFICATIONS.md).

LGPL-2.1 is compatible with MIT-licensed code that uses it, and the two
coexist here without conflict. It does impose its own obligations on anyone
redistributing the emulator or a binary built from it; that document states
them.

## In short

A frozen release directory containing a copy of `LICENSE` licenses the
**code** inside it. It does not license the data beside it.
