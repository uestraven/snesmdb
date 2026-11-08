"""The sample directory as a function of time, and resolution at key-on.

A driver may populate or replace sample-directory entries DURING playback.
Secret of Evermore leaves all eight of its entries as `$FFFF` at capture and
writes real addresses within seconds, so resolving every key-on against the
initial ARAM lost the samples under 50.6% of its note attacks — and reported
them as "probably percussive or noise". Nothing in the DSP write log revealed
it: `DIR` ($5D) is never written, because the table lives in ARAM and is
filled by CPU writes the DSP hook cannot see.

So `spc_dump` emits the whole 1,024-byte directory whenever it changes, and
this module answers the only question that matters per note: **what did SRCN
mean at the instant this voice was keyed on?**

FOUR OUTCOMES, not two. A missing identity and a WRONG identity are different
failures, and the second is worse because it is invisible:

    newly_resolved      nothing at t=0, a valid sample at key-on
    identity_corrected  valid at t=0, but DIFFERENT audio at key-on
    unchanged           the same canonical identity at both times
    unresolved          no valid sample even at key-on

`identity_corrected` is compared on **canonical sample identity** — the
content hash of the decoded audio and its loop point — not on the directory
address. Two addresses can hold identical audio, and a changed address with
unchanged content is not a correction to anything a researcher can observe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: Four bytes per entry: start address then loop address, little-endian.
ENTRY_BYTES = 4

#: The whole table: 256 entries. A short snapshot covers only part of the
#: SRCN range and the corpus reaches 73.
TABLE_BYTES = 256 * ENTRY_BYTES


@dataclass
class DirectoryState:
    """The directory table as of one instant."""

    tick: int
    page: int
    data: bytes

    def entry(self, srcn: int) -> tuple[int, int] | None:
        """`(start, loop)` for an SRCN, or None when outside the snapshot."""
        off = srcn * ENTRY_BYTES
        if srcn < 0 or off + ENTRY_BYTES > len(self.data):
            return None
        d = self.data
        return (d[off] | (d[off + 1] << 8), d[off + 2] | (d[off + 3] << 8))


@dataclass
class Timeline:
    """Directory states in tick order, queried by key-on time."""

    states: list[DirectoryState] = field(default_factory=list)

    def add(self, tick: int, page: int, data: bytes) -> None:
        self.states.append(DirectoryState(int(tick), int(page), bytes(data)))
        self.states.sort(key=lambda s: s.tick)

    def at(self, tick: int) -> DirectoryState | None:
        """The state last OBSERVED at or before `tick`.

        Snapshots are taken at audio-chunk boundaries, so this is the state
        at the previous boundary, not necessarily the state the DSP used. Use
        `ambiguous` to find out whether that distinction matters for a given
        note; it usually does not, because the entry is the same on both
        sides of the boundary.
        """
        found = None
        for state in self.states:
            if state.tick <= tick:
                found = state
            else:
                break
        # Before the first logged change there is only the initial snapshot,
        # which the caller supplies as the state at tick 0.
        return found or (self.states[0] if self.states else None)

    def initial(self) -> DirectoryState | None:
        return self.states[0] if self.states else None

    def bracket(
        self, tick: int
    ) -> tuple[DirectoryState | None, DirectoryState | None]:
        """The observed states immediately before and after `tick`."""
        prev = nxt = None
        for state in self.states:
            if state.tick <= tick:
                prev = state
            else:
                nxt = state
                break
        return prev or self.initial(), nxt

    def ambiguous(self, tick: int, srcn: int) -> bool:
        """Whether this SRCN's entry cannot be pinned down at `tick`.

        AN ASSUMPTION REPLACED BY A MEASUREMENT. An earlier version of this
        module resolved a note against the latest snapshot at or before its
        key-on and justified it by arguing that the CPU writes behind a change
        observed at tick T must have preceded the key-ons in that chunk. That
        does not follow: a snapshot taken at a chunk boundary cannot establish
        the order of a key-on and a directory write that both fall inside the
        chunk.

        So the ordering is not assumed. A change observed at the NEXT boundary
        happened somewhere in `(prev.tick, next.tick]`, which straddles this
        key-on -- but it only matters if THIS SRCN's entry differs across that
        boundary. When it does not, the ordering is irrelevant and resolution
        is exact. When it does, the case is genuinely ambiguous and is
        reported as such rather than silently resolved one way.
        """
        prev, nxt = self.bracket(tick)
        if prev is None or nxt is None:
            return False
        return prev.entry(srcn) != nxt.entry(srcn)



def read_log(records: Iterable[dict[str, Any]]) -> Timeline:
    """Build a timeline from the `kind == "dir"` records in a write log."""
    timeline = Timeline()
    for record in records:
        if record.get("kind") != "dir":
            continue
        raw = record.get("bytes") or ""
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            continue
        timeline.add(record.get("t", 0), record.get("page", 0), data)
    return timeline


#: The four outcomes, as published in the resolution census.
#: The entry for this SRCN changed across the snapshot boundary containing
#: the key-on, so which value the DSP used cannot be established from
#: chunk-boundary snapshots. Reported, never guessed.
AMBIGUOUS = "ambiguous_boundary"
NEWLY_RESOLVED = "newly_resolved"
IDENTITY_CORRECTED = "identity_corrected"
UNCHANGED = "unchanged"
UNRESOLVED = "unresolved"
OUTCOMES = (NEWLY_RESOLVED, IDENTITY_CORRECTED, UNCHANGED, UNRESOLVED,
            AMBIGUOUS)


def plausible(entry: tuple[int, int] | None) -> bool:
    """Whether an entry looks like a sample rather than unwritten memory.

    `$FFFF/$FFFF` is the 0xFF fill of a table the driver has not populated,
    and a start of zero or a loop before the start is not a sample.
    """
    if entry is None:
        return False
    start, loop = entry
    return start not in (0, 0xFFFF) and loop >= start


def classify(
    initial: tuple[int, int] | None,
    effective: tuple[int, int] | None,
    identify: Any,
) -> tuple[str, str | None]:
    """Compare t=0 against key-on time, returning `(outcome, identity)`.

    `identify(start, loop)` returns a canonical sample identity, or None when
    the block cannot be decoded. Identities are compared, NOT addresses: a
    changed address holding identical audio is not a correction a researcher
    could observe, and reporting it as one would overstate the fix.
    """
    now = identify(*effective) if plausible(effective) else None
    if now is None:
        return UNRESOLVED, None
    before = identify(*initial) if plausible(initial) else None
    if before is None:
        return NEWLY_RESOLVED, now
    if before != now:
        return IDENTITY_CORRECTED, now
    return UNCHANGED, now
