"""Reading the SPC container: header, ID666 metadata, and ARAM.

Metadata comes from the ID666 tag inside each SPC rather than from scraping
snesmusic.org. Three reasons. It is per TRACK, where the site gives composer
per set. It needs no network, so extraction is reproducible and does not
hammer somebody's archive. And it travels with the file, so a corpus built
from a user's own SPCs carries its own provenance.

The site remains useful as a cross-check (it has stable numeric game and
composer ids, e.g. `profile.php?profile=composer&selected=1005`), but it is
not a dependency.

The awkward part of ID666 is that it has two incompatible layouts -- "text"
and "binary" -- occupying the same bytes, with no flag saying which. Rather
than guess and silently emit wrong dates and lengths, `parse_id666` reports
which layout it believes and how confident it is, and callers can treat a
low-confidence tag as unknown.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SPC_SIZE = 0x10200
ARAM_OFFSET = 0x100
ARAM_SIZE = 0x10000
DSP_OFFSET = 0x10100
DSP_SIZE = 0x80

SIGNATURE = b"SNES-SPC700 Sound File Data"

# ID666 text-layout field offsets and widths.
_TITLE = (0x2E, 32)
_GAME = (0x4E, 32)
_DUMPER = (0x6E, 16)
_COMMENTS = (0x7E, 32)
_DATE = (0x9E, 11)
_SECONDS = (0xA9, 3)
_FADE = (0xAC, 5)
_ARTIST = (0xB1, 32)


class SpcError(ValueError):
    """The file is not a usable SPC."""


def _text(data: bytes, where: tuple[int, int]) -> str:
    offset, width = where
    raw = data[offset : offset + width]
    return raw.split(b"\x00", 1)[0].decode("latin-1", "replace").strip()


@dataclass
class Id666:
    """The ID666 tag, with an honest account of how well it was read."""

    title: str = ""
    game: str = ""
    dumper: str = ""
    comments: str = ""
    artist: str = ""
    date: str = ""
    seconds: int | None = None
    fade_ms: int | None = None
    #: "text", "binary", or "unknown".
    layout: str = "unknown"
    #: Why the layout was chosen, so a surprising corpus row can be explained.
    layout_reason: str = ""

    @property
    def composer(self) -> str:
        """ID666 calls it the artist; everywhere else calls it the composer."""
        return self.artist

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "game": self.game,
            "composer": self.composer,
            "dumper": self.dumper,
            "comments": self.comments,
            "date": self.date,
            "seconds": self.seconds,
            "fade_ms": self.fade_ms,
            "layout": self.layout,
            "layout_reason": self.layout_reason,
        }


def parse_id666(data: bytes) -> Id666:
    """Read the ID666 tag, deciding between its two layouts by evidence.

    The text layout stores the dump date and play length as ASCII digits; the
    binary layout stores them as little-endian integers in overlapping bytes.
    Nothing in the file says which is in use, and the usual heuristic -- "are
    the date bytes printable digits" -- is what we use here, but it is a
    heuristic, so the verdict and its reason are recorded rather than assumed.

    A tag with no ID666 at all (header byte 0x23 == 0x1A) is reported as
    `layout="unknown"` with empty fields, which is different from a tag that
    was present and unreadable.
    """
    tag = Id666()
    if len(data) < ARAM_OFFSET:
        tag.layout_reason = "file too short to contain a tag"
        return tag

    if data[0x23] == 0x1A:
        tag.layout_reason = "header says no ID666 tag present"
        return tag

    tag.title = _text(data, _TITLE)
    tag.game = _text(data, _GAME)
    tag.dumper = _text(data, _DUMPER)
    tag.comments = _text(data, _COMMENTS)

    date_raw = data[_DATE[0] : _DATE[0] + _DATE[1]]
    printable = sum(1 for b in date_raw if b in b"0123456789/- \x00")
    if printable == len(date_raw):
        tag.layout = "text"
        tag.layout_reason = "date field is ASCII digits/separators"
        tag.date = _text(data, _DATE)
        seconds = _text(data, _SECONDS)
        fade = _text(data, _FADE)
        tag.seconds = int(seconds) if seconds.isdigit() else None
        tag.fade_ms = int(fade) if fade.isdigit() else None
        tag.artist = _text(data, _ARTIST)
    else:
        # Binary layout: date is 4 bytes at 0x9E, length 3 at 0xA9, fade 4 at
        # 0xAC, artist 32 at 0xB0 -- note the artist shifts by one byte.
        tag.layout = "binary"
        tag.layout_reason = "date field is not ASCII; assuming binary layout"
        year = int.from_bytes(data[0xA0:0xA2], "little")
        month, day = data[0x9F], data[0x9E]
        if 1980 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
            tag.date = f"{year:04d}-{month:02d}-{day:02d}"
        tag.seconds = int.from_bytes(data[0xA9:0xAC], "little") or None
        tag.fade_ms = int.from_bytes(data[0xAC:0xB0], "little") or None
        tag.artist = _text(data, (0xB0, 32))
    return tag


@dataclass
class Spc:
    """A loaded SPC file."""

    path: Path
    sha256: str
    size: int
    pc: int
    tag: Id666
    aram: bytes = field(repr=False)
    dsp: bytes = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "size": self.size,
            "pc": self.pc,
            "tag": self.tag.to_dict(),
        }


def load(path: str | Path) -> Spc:
    """Read and validate an SPC file."""
    path = Path(path)
    data = path.read_bytes()
    if not data.startswith(SIGNATURE):
        raise SpcError(f"{path}: missing SPC signature")
    if len(data) < DSP_OFFSET + DSP_SIZE:
        raise SpcError(
            f"{path}: {len(data)} bytes, too short for header + ARAM + DSP "
            f"(need at least {DSP_OFFSET + DSP_SIZE})"
        )
    return Spc(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        pc=int.from_bytes(data[0x25:0x27], "little"),
        tag=parse_id666(data),
        aram=data[ARAM_OFFSET : ARAM_OFFSET + ARAM_SIZE],
        dsp=data[DSP_OFFSET : DSP_OFFSET + DSP_SIZE],
    )
