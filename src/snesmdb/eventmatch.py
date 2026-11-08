"""Pair DSP sample-start commits with extracted note attacks, by origin.

Two event streams describe the same playback and do NOT contain the same
events. The extractor sees CPU writes to KON ($4C). The instrumented DSP
emits a commit every time it assigns a voice's BRR start address -- including
once per voice whose bit is set in the KON register stored in the SPC file,
because `SPC_DSP::load()` seeds `m.new_kon` from that byte and the DSP then
latches it and runs a normal key-on. Verified on three drivers: the surplus
commits fall on exactly the voices with a set bit, one each, and nowhere else
(`$43` -> 3 surplus, `$FF` -> 8, `$01` -> 1).

A replay-initialisation commit is NOT a musical attack. It reproduces a
pending request captured mid-performance, without the DSP state that preceded
it, so it must be excluded from the corpus rather than published as a note.

RECONCILED BY ORIGIN, NOT BY SUBTRACTION. "Drop the first commit per voice"
would give the same answer on the tested tracks and the wrong answer on a
track whose driver keys a voice before the DSP's first latch. The rule here
names a cause: exclude the commit attributable to the snapshot's own KON bits.

AND IT FAILS CLOSED. A CPU write to $4C assigns `m.new_kon`, which the DSP
latches afterwards, so a sufficiently early write can REPLACE the
snapshot-seeded request before it is ever accepted. Where that is possible
the origin of the first commit cannot be established from the evidence, and
this refuses to match rather than excluding a commit on an assumption. An
unexplained match would shift every later sample identity on that voice by
one -- silently, and consistently with every count in the corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: KON lives at DSP $4C.
REG_KON = 0x4C

#: A commit follows its key-on by the DSP's five-cycle key-on delay. The
#: logged timestamp is the render-chunk base, so at `--chunk 1` a commit may
#: appear up to one DSP frame earlier than the write that caused it.
FRAME_CLOCKS = 32


@dataclass
class Match:
    """The outcome of reconciling the two streams for one track."""

    pairs: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    excluded_startup: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def startup_voices(kon_byte: int) -> set[int]:
    """Voices whose key-on is pending in the loaded snapshot."""
    return {voice for voice in range(8) if kon_byte & (1 << voice)}


def match(
    notes: Iterable[Any],
    commits: Iterable[dict[str, Any]],
    kon_byte: int,
    kon_write_ticks: Iterable[int] = (),
) -> Match:
    """Pair attacks with commits per voice, after excluding startup events.

    `notes` are the extractor's attacks (objects with `.voice` and `.start`),
    `commits` the instrumented DSP's sample starts, `kon_byte` the SPC's own
    DSP $4C value, and `kon_write_ticks` the times of CPU writes to $4C.
    """
    result = Match()
    by_voice: dict[int, list[Any]] = {}
    for note in notes:
        by_voice.setdefault(int(note.voice), []).append(note)
    for value in by_voice.values():
        value.sort(key=lambda n: int(n.start))

    commits_by_voice: dict[int, list[dict[str, Any]]] = {}
    for commit in commits:
        commits_by_voice.setdefault(int(commit["voice"]), []).append(commit)
    for value in commits_by_voice.values():
        value.sort(key=lambda c: int(c["t"]))

    pending = startup_voices(kon_byte)
    earliest_write = min(kon_write_ticks, default=None)

    # Pending voices are included even when neither stream mentions them: a
    # set KON bit with no observed commit is a gap in the evidence, and
    # iterating only over observed voices would skip the check entirely.
    for voice in sorted(set(by_voice) | set(commits_by_voice) | pending):
        attacks = list(by_voice.get(voice, []))
        events = list(commits_by_voice.get(voice, []))

        if voice in pending:
            if not events:
                result.problems.append(
                    f"voice {voice}: KON bit set in the snapshot but no "
                    f"commit was observed"
                )
                continue
            first = events[0]
            # FAIL CLOSED: a CPU write at or before the first commit could
            # have replaced the pending snapshot request before the DSP
            # latched it, which makes the commit's origin unestablished.
            if earliest_write is not None and earliest_write <= int(first["t"]):
                result.problems.append(
                    f"voice {voice}: a CPU KON write at t={earliest_write} "
                    f"precedes or coincides with the first commit at "
                    f"t={first['t']}, so it cannot be established whether "
                    f"that commit came from the snapshot's pending KON or "
                    f"from the write -- refusing to match"
                )
                continue
            result.excluded_startup.append(events.pop(0))

        if len(attacks) != len(events):
            result.problems.append(
                f"voice {voice}: {len(attacks)} extracted attacks against "
                f"{len(events)} commits after startup exclusion"
            )
            continue
        for index, (note, commit) in enumerate(zip(attacks, events)):
            if int(commit["t"]) + FRAME_CLOCKS < int(note.start):
                result.problems.append(
                    f"voice {voice} pair {index}: commit at t={commit['t']} "
                    f"precedes its attack at t={note.start}"
                )
                break
            result.pairs.append((note, commit))
    return result
