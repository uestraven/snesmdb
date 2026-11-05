#!/usr/bin/env python3
"""Generate a synthetic SPC file: a tiny hand-assembled SPC700 driver.

Why this exists. Every real SPC is a copyrighted game rip, so a project that
can only be tested on real SPCs cannot be tested in CI, cannot ship a fixture,
and cannot be verified by anyone who has not separately acquired the data.
This writes an SPC from scratch -- our own code, our own BRR sample -- so the
whole extraction path has a deterministic, redistributable test case.

It also has to be a REAL SPC700 program rather than a pre-loaded register
dump, because the logger hooks CPU writes to the DSP. A fixture that set up
the DSP purely through the file's register block would produce an empty log
and prove nothing.

The generated driver plays a short sequence of key-ons at known delays, which
is exactly the signal the extractor has to recover.

    usage: make_test_spc.py <out.spc> [--notes 4]
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

SPC_SIZE = 0x10200
ARAM_OFFSET = 0x100
DSP_OFFSET = 0x10100

CODE_ADDR = 0x0200
DIR_ADDR = 0x1000  # sample directory (page-aligned: DIR holds the high byte)
BRR_ADDR = 0x1100  # BRR sample data
#: Driver code lives at CODE_ADDR and must not reach DIR_ADDR. A six-note
#: sequence with realistic delays is ~700 bytes, so 0x0400 was too tight.

DSPADDR = 0xF2
DSPDATA = 0xF3

# DSP registers
R_KON, R_FLG, R_DIR = 0x4C, 0x6C, 0x5D
R_MVOLL, R_MVOLR = 0x0C, 0x1C
R_EVOLL, R_EVOLR, R_EON, R_EDL, R_EFB = 0x2C, 0x3C, 0x4D, 0x7D, 0x0D
R_KOFF, R_PMON, R_NON = 0x5C, 0x2D, 0x3D


class Asm:
    """A very small SPC700 assembler -- only the opcodes this driver needs."""

    def __init__(self, origin: int) -> None:
        self.origin = origin
        self.code = bytearray()

    @property
    def pc(self) -> int:
        return self.origin + len(self.code)

    def mov_a_imm(self, value: int) -> None:
        self.code += bytes([0xE8, value & 0xFF])

    def mov_dp_a(self, dp: int) -> None:
        self.code += bytes([0xC4, dp & 0xFF])

    def mov_x_imm(self, value: int) -> None:
        self.code += bytes([0xCD, value & 0xFF])

    def mov_y_imm(self, value: int) -> None:
        self.code += bytes([0x8D, value & 0xFF])

    def dec_x(self) -> None:
        self.code += bytes([0x1D])

    def dbnz_y(self, target: int) -> None:
        self.code += bytes([0xFE, self._rel(target, 2)])

    def bne(self, target: int) -> None:
        self.code += bytes([0xD0, self._rel(target, 2)])

    def bra(self, target: int) -> None:
        self.code += bytes([0x2F, self._rel(target, 2)])

    def _rel(self, target: int, size: int) -> int:
        offset = target - (self.pc + size)
        assert -128 <= offset <= 127, f"branch out of range: {offset}"
        return offset & 0xFF

    # --- helpers -----------------------------------------------------------

    def dsp(self, addr: int, data: int) -> None:
        """Write one DSP register the way a real driver does."""
        self.mov_a_imm(addr)
        self.mov_dp_a(DSPADDR)
        self.mov_a_imm(data)
        self.mov_dp_a(DSPDATA)

    def delay(self, outer: int, repeats: int = 1) -> None:
        """Roughly `outer` x 255 DBNZ iterations, emitted `repeats` times.

        `outer` is one byte, and one pass at the maximum is only ~52 ms, so a
        musically plausible note length needs the block repeated. Measured:
        outer=40 gives 8,312 SPC clocks (~8 ms), which is far too short to
        stand in for a real note.
        """
        for _ in range(max(1, repeats)):
            self.mov_x_imm(outer)
            top = self.pc
            self.mov_y_imm(0xFF)
            inner = self.pc
            self.dbnz_y(inner)
            self.dec_x()
            self.bne(top)


def brr_sample() -> bytes:
    """A one-block looping BRR sample: our own content, trivially periodic.

    Filter 0 so it decodes identically every pass, with the END and LOOP flags
    set so the voice sustains instead of stopping after 16 samples.
    """
    header = (0x0C << 4) | (0 << 2) | 0x03  # shift 12, filter 0, END | LOOP
    # A crude triangle over 16 nibbles, as 4-bit signed values.
    nibbles = [0, 2, 4, 6, 7, 6, 4, 2, 0, -2, -4, -6, -7, -6, -4, -2]
    payload = bytes(
        ((nibbles[i] & 0xF) << 4) | (nibbles[i + 1] & 0xF)
        for i in range(0, 16, 2)
    )
    return bytes([header]) + payload


def _id666(out: bytearray, title: str, game: str, composer: str) -> None:
    """Write a text-layout ID666 tag.

    The fixture carries a tag so the metadata path -- and the
    composer-disjoint split built on it -- is testable without real SPCs,
    whose tags are the only place per-track composer data exists.
    """
    def put(offset: int, width: int, text: str) -> None:
        # The full width is usable. Reserving a byte for a NUL terminator
        # truncated the fixed-width numeric fields -- "030" seconds became
        # "03" and "05000" ms fade became "0500" -- because ID666 pads those
        # with digits, not with a terminator.
        raw = text.encode("latin-1", "replace")[:width]
        out[offset : offset + width] = raw + b"\x00" * (width - len(raw))

    # 0x1A means the header CONTAINS ID666 info; 0x1B means it does not.
    # This generator had it inverted, matching an inverted parser, so the
    # fixture and the bug agreed and the suite stayed green.
    out[0x23] = 0x1A if title else 0x1B
    put(0x2E, 32, title)        # song title
    put(0x4E, 32, game)         # game title
    put(0x6E, 16, "snesmdb")    # dumper
    put(0x7E, 32, "synthetic fixture")
    put(0x9E, 11, "2026-11-05")  # date, ASCII -> text layout
    put(0xA9, 3, "030")         # seconds
    put(0xAC, 5, "05000")       # fade ms
    put(0xB1, 32, composer)     # artist / composer


def build(
    notes: int,
    *,
    title: str = "Synthetic Test Track",
    game: str = "Synthetic Test Game",
    composer: str = "snesmdb fixture",
) -> bytes:
    aram = bytearray(0x10000)
    dsp_regs = bytearray(0x80)

    sample = brr_sample()
    aram[BRR_ADDR : BRR_ADDR + len(sample)] = sample
    # Directory entry 0: start address, loop address.
    aram[DIR_ADDR : DIR_ADDR + 4] = struct.pack("<HH", BRR_ADDR, BRR_ADDR)

    a = Asm(CODE_ADDR)
    # Global setup, written by the CPU so the logger sees it.
    a.dsp(R_FLG, 0x20)  # echo writes off, not muted, no reset
    a.dsp(R_MVOLL, 0x7F)
    a.dsp(R_MVOLR, 0x7F)
    a.dsp(R_EVOLL, 0x00)
    a.dsp(R_EVOLR, 0x00)
    a.dsp(R_EON, 0x00)
    a.dsp(R_EDL, 0x00)
    a.dsp(R_EFB, 0x00)
    a.dsp(R_PMON, 0x00)
    a.dsp(R_NON, 0x00)
    a.dsp(R_KOFF, 0x00)
    a.dsp(R_DIR, DIR_ADDR >> 8)

    # A short sequence: each note is a different voice at a different pitch,
    # so the extractor has something with structure to recover.
    pitches = [0x0800, 0x0A00, 0x0C00, 0x1000, 0x1400, 0x1800, 0x0600, 0x0900]
    for index in range(notes):
        voice = index % 8
        base = voice * 0x10
        pitch = pitches[index % len(pitches)]
        a.dsp(base + 0x00, 0x60)  # VOLL
        a.dsp(base + 0x01, 0x60)  # VOLR
        a.dsp(base + 0x02, pitch & 0xFF)  # PITCHL
        a.dsp(base + 0x03, (pitch >> 8) & 0xFF)  # PITCHH
        a.dsp(base + 0x04, 0x00)  # SRCN
        a.dsp(base + 0x05, 0x00)  # ADSR1: GAIN mode
        a.dsp(base + 0x07, 0x7F)  # GAIN: direct, maximum
        a.dsp(R_KON, 1 << voice)
        a.delay(150)              # ~150 ms note
        a.dsp(R_KOFF, 1 << voice)
        a.delay(50)               # ~50 ms gap
        a.dsp(R_KOFF, 0x00)

    loop_here = a.pc
    a.bra(loop_here)

    assert CODE_ADDR + len(a.code) < DIR_ADDR, "code ran into the directory"
    aram[CODE_ADDR : CODE_ADDR + len(a.code)] = a.code

    # The register block the file loads; the driver overwrites what it needs.
    dsp_regs[R_FLG] = 0xE0  # start muted/reset until the driver runs
    dsp_regs[R_DIR] = DIR_ADDR >> 8

    out = bytearray(SPC_SIZE)
    sig = b"SNES-SPC700 Sound File Data v0.30"
    out[0 : len(sig)] = sig
    out[0x21] = 0x1A
    out[0x22] = 0x1A
    out[0x23] = 0x1A  # no ID666 tag
    out[0x24] = 30
    struct.pack_into("<H", out, 0x25, CODE_ADDR)  # PC
    out[0x27] = 0x00  # A
    out[0x28] = 0x00  # X
    out[0x29] = 0x00  # Y
    out[0x2A] = 0x00  # PSW
    out[0x2B] = 0xEF  # SP
    _id666(out, title, game, composer)
    out[ARAM_OFFSET : ARAM_OFFSET + 0x10000] = aram
    out[DSP_OFFSET : DSP_OFFSET + 0x80] = dsp_regs
    return bytes(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--notes", type=int, default=4)
    parser.add_argument("--title", default="Synthetic Test Track")
    parser.add_argument("--game", default="Synthetic Test Game")
    parser.add_argument("--composer", default="snesmdb fixture")
    args = parser.parse_args()
    data = build(
        args.notes, title=args.title, game=args.game, composer=args.composer
    )
    assert len(data) == SPC_SIZE, len(data)
    args.out.write_bytes(data)
    print(f"wrote {args.out} ({len(data)} bytes, {args.notes} notes)")


if __name__ == "__main__":
    main()
