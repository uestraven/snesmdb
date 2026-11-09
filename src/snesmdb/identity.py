"""The single path from a directory entry to a canonical sample identity.

This module exists because of a specific failure, not for tidiness.

The plausibility rule had TWO independent implementations -- one on
`brr.DirectoryEntry.plausible`, used by the publisher, and one in
`dirtimeline.plausible`, used by the analysis tools -- and they disagreed:
`brr` rejected only a zero start, while `dirtimeline` also rejected the
`$FFFF` fill of an unpopulated table. Meanwhile three analysis tools called
`sampleid.sample_id` with no gate at all, and the corpus-wide validation
pass consequently reported 15,165 hashes of unwritten memory as established
identities -- 11,294 of them as "recoveries" over a correctly published
null.

Nothing crashed. ARAM address 0 holds bytes, `brr.decode` reads them, and
`sampleid` hashes the result into sixteen confident-looking hex digits.

So the rule now has one definition and the identity has one producer. A
correct predicate is not enough if a reporting or publishing path can
forget to call it; the way to make "every path applies the rule" testable
is to leave only one path.
"""

from __future__ import annotations

from typing import Iterable

from . import brr, sampleid

# Re-exported so callers need only one import. The DEFINITION lives in
# `brr.plausible_entry`, because `brr` is the lowest layer that knows what a
# directory entry is and this module already depends on it.
ENTRY_FILL = brr.ENTRY_FILL
plausible_entry = brr.plausible_entry


def identity_for_entry(
    aram: bytes, start: int, loop: int
) -> tuple[str | None, int | None]:
    """`(canonical identity, content hash)` for one directory entry.

    The ONLY supported way to turn an entry into an identity. Returns
    `(None, None)` -- never a hash -- when the entry is implausible, when the
    BRR will not decode, or when it decodes to nothing.

    The content hash covers the WHOLE signed waveform. An earlier comparison
    used `bytes((v & 0xFF) for v in data[:4096])`, which discards the high
    byte of every sample and everything past 4,096 samples, and so reported
    unrelated instruments as identical content.

    `None` here means "not established". It must be published as null and
    never backfilled with a plausible-looking substitute.
    """
    if not plausible_entry((start, loop)):
        return (None, None)
    try:
        decoded = brr.decode(aram, start, loop)
    except (ValueError, IndexError):
        return (None, None)
    if not decoded.data:
        return (None, None)
    return (
        sampleid.sample_id(decoded.data, decoded.loop_offset),
        content_hash(decoded.data),
    )


def content_hash(data: Iterable[int]) -> int:
    """A hash of decoded PCM that ignores the loop point.

    Separate from `sample_id` on purpose: the identity includes the loop
    offset, so comparing identities cannot tell "different audio" from "same
    audio, different loop". Both questions matter and they have different
    answers -- on Super Turrican, 16,195 attacks differ in content while only
    10 differ in loop alone.

    Hashed as a tuple rather than via `bytes()`, because PCM is SIGNED and
    `bytes()` raises on any negative sample.
    """
    return hash(tuple(data))
