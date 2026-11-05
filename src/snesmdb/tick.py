"""Recover the driver's tick period from the DSP write cadence.

Milestone 4, and a correction to how it was first attempted.

The design doc's plan was to histogram key-on inter-onset intervals and let the
tick fall out as the dominant spacing. That works on the NES because music
there advances on a universal 60.0988 Hz frame, so onsets and frames coincide.
It does NOT work here, and the corpus said so plainly: the onset grid came out
at 5.4 rows/s for Zelda against a real tick of 62.5 Hz, and 11.0 against 205.4
for Final Fantasy VI -- wrong by 11.6x and 18.7x. Only Donkey Kong Country
agreed, at 1.00x, because its driver keys on so densely that the music
exercises every tick.

The tick is visible in a different place. A driver runs its music engine on a
timer and writes a BURST of registers each time that timer fires, whether or
not a note starts. So the cadence is in ALL DSP writes, which are one to two
orders of magnitude denser than key-ons and far more regular:

    Secret of Mana   4,602 ticks, 3,415 hits   222.4 Hz
    Final Fantasy VI 4,993 ticks,   984 hits   205.4 Hz
    Zelda           16,382 ticks,   561 hits    62.5 Hz
    DKC             12,519 ticks,   231 hits    80.1 Hz

Those are sharp modes with hundreds to thousands of hits, against a key-on
histogram whose mode is noise. 62.5 Hz for Nintendo's N-SPC and 205-222 Hz for
the two AKAO games are recognisable driver timer rates.

Pure stdlib, no I/O: it takes a list of timestamps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

TICKS_PER_SECOND = 1_024_000

#: Burst windows to try, in ticks. A burst window must be narrower than the
#: tick and wider than the spacing of writes WITHIN one tick's burst, and
#: neither is known in advance -- a driver that writes near-continuously
#: collapses into a single burst at 2,048 ticks, which is how the first attempt
#: lost Earthbound entirely. So several are tried and the sharpest wins.
BURST_WINDOWS = (64, 128, 256, 512, 1024, 2048, 4096)

#: Gaps within this fraction of a candidate count as the same gap. Driver
#: timers jitter by a few ticks: Final Fantasy VI's gap appears as 4,993,
#: 4,988 and 4,987, which are one period and not three.
GAP_TOLERANCE = 0.01

#: Plausible driver tick rates. 10 Hz is slower than any music engine; 2 kHz is
#: faster than the SPC700 could service.
MIN_TICK_TICKS = TICKS_PER_SECOND // 2000
MAX_TICK_TICKS = TICKS_PER_SECOND // 10

#: Below this many inter-burst gaps there is not enough cadence to measure.
MIN_GAPS = 20

#: Phase concentration required to call a period the tick. This is a circular
#: resultant length over ALL write times: 1.0 means every write happens at the
#: same phase of the period, and a uniform spread gives ~0. Writes that recur
#: on a timer are concentrated; a period that is slightly wrong makes the phase
#: precess and the concentration collapse, which is exactly the error the
#: burst-gap statistic could not see.
#:
#: The threshold is 0.25 rather than something stricter because of a bound, not
#: a preference. Writes spread uniformly across a fraction f of the period give
#: a resultant of sinc(pi*f), so a driver whose burst occupies 60% of its tick
#: cannot exceed 0.50 however real its timer is -- at 0.50 that driver is
#: refused for its write style rather than for a lack of cadence. 0.25 admits
#: bursts up to ~75% of the tick. The honest validator is not this threshold at
#: all: it is whether every track in a game reports the SAME tick, which the
#: run summary records per game.
MIN_CONCENTRATION = 0.25

#: Accept a larger period when its concentration is within this of the best.
#: A sub-multiple of the tick concentrates just as well -- every write still
#: lands at one phase -- so without this the answer is the finest candidate.
#: Multiples do NOT need a guard: at twice the tick, bursts alternate between
#: opposite phases and the concentration falls on its own.
LARGER_PERIOD_MARGIN = 0.02


@dataclass
class Tick:
    """The driver's timer period, or a reasoned refusal."""

    found: bool
    reason: str = ""
    period_ticks: int = 0
    #: Circular concentration of write phases at this period, 0..1.
    concentration: float = 0.0
    #: Fraction of inter-burst gaps that ARE this period, within tolerance.
    #: Reported for continuity, but it is NOT what selects the period: a burst
    #: window narrow enough to split bursts makes "period minus burst span"
    #: look perfectly regular, which is how this module first read a 4,993
    #: tick timer as 4,393.
    sharpness: float = 0.0
    n_agreeing: int = 0
    n_gaps: int = 0
    #: The burst window that proposed the winning candidate, in ticks.
    burst_window: int = 0
    n_writes: int = 0
    n_candidates: int = 0

    @property
    def hz(self) -> float:
        return TICKS_PER_SECOND / self.period_ticks if self.period_ticks else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "reason": self.reason,
            "period_ticks": self.period_ticks,
            "hz": round(self.hz, 3) if self.period_ticks else 0.0,
            "concentration": round(self.concentration, 4),
            "sharpness": round(self.sharpness, 4),
            "n_candidates": self.n_candidates,
            "n_agreeing": self.n_agreeing,
            "n_gaps": self.n_gaps,
            "burst_window": self.burst_window,
            "n_writes": self.n_writes,
        }


def bursts(times: Sequence[int], window: int) -> list[int]:
    """Collapse writes within `window` ticks into one burst, keeping its start."""
    out: list[int] = []
    previous: int | None = None
    for t in times:
        if previous is None or t - previous > window:
            out.append(t)
        previous = t
    return out


def _agreement(gaps: Sequence[int], candidate: int) -> int:
    """How many inter-burst gaps are this period, within tolerance."""
    slack = max(1, int(candidate * GAP_TOLERANCE))
    return sum(1 for g in gaps if abs(g - candidate) <= slack)


def concentration(times: Sequence[int], period: int) -> float:
    """Circular resultant length of write phases at `period`.

    The statistic that actually identifies a timer. Each write contributes a
    unit vector at angle 2*pi*(t mod period)/period; if the driver writes at
    the same phase every period those vectors align and the mean length is near
    1, and if the period is wrong by even a per cent the phase precesses
    through the whole circle and the mean length collapses toward 0.

    Window-independent, which is the point: it reads the original write times,
    so no choice of burst window can flatter a wrong period.
    """
    if not period:
        return 0.0
    sin_sum = 0.0
    cos_sum = 0.0
    for t in times:
        angle = 2.0 * math.pi * ((t % period) / period)
        sin_sum += math.sin(angle)
        cos_sum += math.cos(angle)
    n = len(times)
    return math.sqrt(sin_sum * sin_sum + cos_sum * cos_sum) / n if n else 0.0


def _candidates(times: Sequence[int]) -> dict[int, int]:
    """Candidate periods, each mapped to the burst window that proposed it.

    Bursts are used only to PROPOSE: several windows are tried because the
    right one is unknown, and a wrong window merely contributes a candidate
    that the concentration test then rejects.
    """
    out: dict[int, int] = {}
    for window in BURST_WINDOWS:
        burst_starts = bursts(times, window)
        gaps = [b - a for a, b in zip(burst_starts, burst_starts[1:]) if b > a]
        gaps = [g for g in gaps if MIN_TICK_TICKS <= g <= MAX_TICK_TICKS]
        if len(gaps) < MIN_GAPS:
            continue
        counts: dict[int, int] = {}
        for g in gaps:
            counts[g] = counts.get(g, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
        for gap, _count in ranked:
            # A split burst under-reports by the burst span, so each candidate
            # also offers small multiples; the concentration test picks.
            for factor in (1, 2, 3):
                period = gap * factor
                if MIN_TICK_TICKS <= period <= MAX_TICK_TICKS:
                    out.setdefault(period, window)
    return out


def infer(write_times: Iterable[int]) -> Tick:
    """Infer the driver's timer period from DSP write timestamps."""
    times = sorted(int(t) for t in write_times)
    result = Tick(found=False, n_writes=len(times))
    if len(times) < MIN_GAPS * 2:
        result.reason = "too few DSP writes to show a cadence"
        return result

    candidates = _candidates(times)
    result.n_candidates = len(candidates)
    if not candidates:
        result.reason = "no candidate period inside the plausible range"
        return result

    # Concentration is O(n) per candidate, so a long track with many
    # candidates is sampled rather than fully scanned. The statistic is a mean
    # over writes and converges quickly.
    sample = times if len(times) <= 20000 else times[:: len(times) // 20000]

    scored = [(period, concentration(sample, period), window)
              for period, window in candidates.items()]
    best = max(c for _p, c, _w in scored)
    eligible = [item for item in scored if item[1] >= best - LARGER_PERIOD_MARGIN]
    period, conc, window = max(eligible, key=lambda item: item[0])

    burst_starts = bursts(times, window)
    gaps = [b - a for a, b in zip(burst_starts, burst_starts[1:]) if b > a]
    result.period_ticks = period
    result.concentration = conc
    result.burst_window = window
    result.n_gaps = len(gaps)
    result.n_agreeing = _agreement(gaps, period) if gaps else 0
    result.sharpness = result.n_agreeing / result.n_gaps if result.n_gaps else 0.0

    if conc < MIN_CONCENTRATION:
        result.reason = (
            f"the write cadence has no single period: phase concentration "
            f"{conc:.2f} at its best candidate, below {MIN_CONCENTRATION:.2f}"
        )
        return result

    result.found = True
    return result


def read_write_times(path: Any) -> list[int]:
    """Timestamps from a DSP write log, gzipped or not.

    Kept here rather than in the extractor so the tick can be re-measured from
    an archived `raw/*.jsonl.gz` without re-emulating the SPC.
    """
    import gzip
    import json
    from pathlib import Path

    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else open
    times: list[int] = []
    with opener(p, "rt") as handle:  # type: ignore[operator]
        for line in handle:
            if not line.strip():
                continue
            times.append(int(json.loads(line)["t"]))
    return times
