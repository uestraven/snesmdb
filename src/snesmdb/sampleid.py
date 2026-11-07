"""`sample_id` — a reproducible identity for a BRR sample's content.

WHY NOT `srcn`. An SRCN is an index into the sample directory in a given SPC's
ARAM, and it does not name a fixed sample even within one game: each SPC is its
own snapshot and drivers reload their bank per track, so Super Turrican's 8
indices resolve to 48 distinct samples across 12 tracks, and Final Fantasy VI's
11 resolve to 60. Publishing an index as instrument identity invites a wrong
join; only Plok! in this corpus happens to share one bank throughout.

THE DEFINITION, stated because a hash whose inputs are not written down is not
reproducible:

    sample_id = SHA-256(
        b"snesmdb.sample.v1\\0"
        + loop_offset_field
        + decoded PCM as signed 16-bit little-endian
    ) truncated to the first 16 hex characters (64 bits)

  * The PCM is the DECODED sample -- the BRR blocks run through the ADPCM
    decoder -- not the compressed bytes. Two different encodings that decode
    to identical audio are the same sample, which is the useful notion for
    research.
  * `loop_offset_field` is the loop point in samples, as 8 bytes
    little-endian, or 8 bytes of 0xFF when the sample does not loop. IT IS
    PART OF THE IDENTITY. Two identical audio payloads with different loop
    points sound different when held -- one sustains, one is a one-shot -- so
    treating them as the same sample would be wrong. An earlier version
    hashed only the audio and would have conflated them.
  * The version prefix means a future change to what is hashed produces
    visibly different ids rather than silently incompatible ones.
  * Truncation to 64 bits is a convenience for reading and joining. At the
    corpus's scale -- about 8,200 distinct samples -- the chance of any
    collision is on the order of 2e-12. `check_unique` verifies it rather
    than assuming it, and a collision would be a publication failure, not a
    tolerable accident.

WHAT IT IS NOT. A sample_id identifies a SOUND SOURCE reproducibly. It is not
an instrument label, and it carries no claim that a sample performs a
consistent musical role: a game may use one sample as a bass in one track and
a lead two octaves up in another, and the id is the same in both.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Any, Iterable

SCHEMA = "snesmdb.sample.v1"

#: Hex characters kept. 16 is 64 bits.
ID_LENGTH = 16

#: Written in place of the loop offset when a sample does not loop, so that a
#: one-shot and a looping sample with identical audio cannot collide.
NO_LOOP = b"\xff" * 8


def sample_id(pcm: Iterable[int], loop_offset: int | None) -> str:
    """The identity of one decoded BRR sample. See the module docstring."""
    digest = hashlib.sha256()
    digest.update(SCHEMA.encode() + b"\0")
    digest.update(
        NO_LOOP if loop_offset is None
        else struct.pack("<q", int(loop_offset))
    )
    # Signed 16-bit little-endian, clamped, so the input is a defined byte
    # sequence rather than a Python repr. The previous implementation hashed
    # `repr(list_of_ints)`, which is implementation-defined and would change
    # every id if the container or int formatting ever changed.
    digest.update(b"".join(
        struct.pack("<h", max(-32768, min(32767, int(value))))
        for value in pcm
    ))
    return digest.hexdigest()[:ID_LENGTH]


def check_unique(
    by_id: dict[str, Any], describe: Any = repr
) -> list[tuple[str, Any, Any]]:
    """Collisions among published ids: `(id, first, second)` per clash.

    Truncation makes a collision astronomically unlikely and not impossible,
    and an id that silently covers two different samples would corrupt every
    join a researcher makes on it. So it is checked rather than assumed.
    """
    seen: dict[str, Any] = {}
    clashes: list[tuple[str, Any, Any]] = []
    for key, value in by_id.items():
        if key in seen and describe(seen[key]) != describe(value):
            clashes.append((key, seen[key], value))
        else:
            seen.setdefault(key, value)
    return clashes
