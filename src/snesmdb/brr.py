"""BRR decoding, in the S-DSP's own arithmetic.

Pure Python and dependency-free on purpose: a dataset tool that needs numpy to
read its own source format is harder to run than it should be, and the volume
here is small (a few dozen samples per game, decoded once).

The arithmetic is the hardware's, not the textbook form. Each decoded sample
ends with

    CLAMP16( s );            # saturate the HALF-SCALE accumulator
    s = (int16_t) (s * 2);   # double, WRAPPING to 16 bits

so every sample the hardware emits is EVEN, and a loud sample past the rail
flips sign rather than pinning to it. A sibling project shipped a BRR codec
that saturated instead, and 67-72% of its sustained instruments would have
wrapped on real hardware -- hidden for three rounds of green tests because the
codec was only ever checked against its own decoder. Starting from the
hardware form here costs nothing and avoids inheriting that.

Reference: blargg's snes_spc `SPC_DSP::decode_brr`, which this repository
vendors and which is the authority used to verify the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

BYTES_PER_BLOCK = 9
SAMPLES_PER_BLOCK = 16

#: Block header flags.
FLAG_END = 0x01
FLAG_LOOP = 0x02


def _wrap16(value: int) -> int:
    return ((value + 0x8000) & 0xFFFF) - 0x8000


def decode_sample(filter_index: int, p1: int, p2: int, nybble: int, shift: int) -> int:
    """One decoded sample. `nybble` is sign-extended to -8..7.

    Python's `>>` floors, which is the arithmetic shift the hardware performs,
    so the shifts transcribe directly from the reference implementation.
    """
    s = nybble
    if shift < 0xD:
        s = (s << shift) >> 1
    else:
        # An out-of-range shift does not encode a large sample; the hardware
        # collapses it to a rail.
        s = -0x800 if s < 0 else 0
    big = p1
    small = p2 >> 1
    if filter_index == 1:
        s += (big >> 1) + ((-big) >> 5)
    elif filter_index == 2:
        s += big - small + (small >> 4) + ((big * -3) >> 6)
    elif filter_index == 3:
        s += big - small + ((big * -13) >> 7) + ((small * 3) >> 4)
    s = max(-32768, min(32767, s))
    return _wrap16(s * 2)


@dataclass
class Decoded:
    """A decoded BRR sample.

    `loop_offset` is in SAMPLES from the start of `data`, or None for a
    one-shot. `blocks` counts what was actually decoded, which can be fewer
    than the data allows if an END flag arrived early.
    """

    data: list[int]
    loop_offset: int | None
    blocks: int
    truncated: bool = False

    @property
    def loop_length(self) -> int | None:
        if self.loop_offset is None:
            return None
        return len(self.data) - self.loop_offset


#: ARAM is 64 KiB, so no sample can exceed this many blocks. The cap exists
#: only to stop a runaway on corrupt data -- an earlier value of 512 silently
#: truncated real samples, and Final Fantasy VI has one of 1,046 blocks.
MAX_BLOCKS = 0x10000 // BYTES_PER_BLOCK


def decode(
    aram: bytes, start: int, loop: int | None = None, *, max_blocks: int = MAX_BLOCKS
) -> Decoded:
    """Decode the BRR sample at `start`, stopping at its END flag.

    `loop` is an ARAM ADDRESS (as the sample directory stores it), converted
    here to a sample offset. A loop address that is not block-aligned relative
    to `start`, or points outside the decoded region, is reported by leaving
    `loop_offset` None rather than producing a bogus offset -- the loop length
    is used downstream to estimate pitch, so a wrong one is worse than none.
    """
    out: list[int] = []
    p1 = p2 = 0
    blocks = 0
    truncated = False
    address = start
    while blocks < max_blocks:
        if address + BYTES_PER_BLOCK > len(aram):
            truncated = True
            break
        header = aram[address]
        shift = (header >> 4) & 0xF
        filter_index = (header >> 2) & 0x3
        for byte in aram[address + 1 : address + BYTES_PER_BLOCK]:
            for nybble in ((byte >> 4) & 0xF, byte & 0xF):
                value = nybble - 16 if nybble >= 8 else nybble
                decoded = decode_sample(filter_index, p1, p2, value, shift)
                out.append(decoded)
                p2, p1 = p1, decoded
        blocks += 1
        address += BYTES_PER_BLOCK
        if header & FLAG_END:
            break
    else:
        truncated = True

    loop_offset: int | None = None
    if loop is not None and loop >= start:
        delta = loop - start
        if delta % BYTES_PER_BLOCK == 0:
            offset = (delta // BYTES_PER_BLOCK) * SAMPLES_PER_BLOCK
            if 0 <= offset < len(out):
                loop_offset = offset
    return Decoded(
        data=out, loop_offset=loop_offset, blocks=blocks, truncated=truncated
    )


# The byte an unpopulated directory reads as. A table the driver has not
# filled is 0xFF bytes, so an entry of $FFFF/$FFFF is the ABSENCE of an
# entry -- not a sample at address 65,535.
ENTRY_FILL = 0xFFFF


def plausible_entry(entry: tuple[int, int] | None) -> bool:
    """Whether `(start, loop)` describes a sample at all.

    THE canonical rule, defined once. `DirectoryEntry.plausible`,
    `dirtimeline.plausible` and `identity.plausible_entry` all delegate here.

    They did not always. This predicate had two independent implementations
    that disagreed about `$FFFF`: the publisher's accepted it, the analysis
    tools' rejected it. Rejected cases, each one observed:

        None              no entry was read
        start == 0        address 0 is the start of ARAM, not a sample.
                          Donkey Kong Country 2 keys on SRCN 140 whose entry
                          is (0, 0); the baseline published null and was
                          right, while an ungated analysis "recovered" 211
                          hashes of ARAM's first bytes.
        start == $FFFF    the fill of an unpopulated table. Secret of
                          Evermore leaves most of it unwritten at capture.
        loop < start      a loop point before the sample is not a loop.
    """
    if entry is None:
        return False
    start, loop = entry
    return start not in (0, ENTRY_FILL) and loop >= start


@dataclass
class DirectoryEntry:
    index: int
    start: int
    loop: int

    @property
    def plausible(self) -> bool:
        """Whether this looks like a real entry rather than unused memory."""
        return plausible_entry((self.start, self.loop))


def read_directory(aram: bytes, dir_page: int, indices: set[int]) -> dict[int, DirectoryEntry]:
    """Read the sample-directory entries for the given SRCN values.

    The directory sits at `dir_page << 8` with four bytes per entry: start
    address then loop address, both little-endian. Only the entries actually
    referenced by a key-on are read, because the rest of the table is whatever
    was in memory.
    """
    base = (dir_page & 0xFF) << 8
    out: dict[int, DirectoryEntry] = {}
    for index in sorted(indices):
        offset = base + index * 4
        if offset + 4 > len(aram):
            continue
        start = aram[offset] | (aram[offset + 1] << 8)
        loop = aram[offset + 2] | (aram[offset + 3] << 8)
        out[index] = DirectoryEntry(index=index, start=start, loop=loop)
    return out
