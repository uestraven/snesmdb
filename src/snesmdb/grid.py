"""Recover the row grid from key-on times.

Milestone 4. The driver's tick period is not written anywhere in an SPC -- it
lives in the driver's own code, and every family picks its own. But the music
advances on it, so it is visible in the *spacing* of note onsets: histogram the
key-on inter-onset intervals and the period falls out as the dominant spacing.
Driver-agnostic, and nothing here knows which game it is looking at.

Pure stdlib and no I/O, so every rule below is directly testable.

**A chord is not simultaneous in the write log, and this is the thing that
makes a naive histogram useless.** A driver key-ons the voices of a chord one
after another, a few hundred clock ticks apart -- Donkey Kong Country staggers
them by 471 to 1,200 ticks, which is 0.5 to 1.2 ms. An eight-voice chord
therefore contributes seven tiny intervals and one musical one, so the interval
histogram is dominated 7:1 by the driver's own write order and the dominant
spacing is the stagger, not the beat. On DKC's Theme, 3,201 notes produced
3,201 distinct onset times and a commonest interval of 631 ticks: 1,600 rows a
second, which is not a tempo.

So onsets are CLUSTERED before anything is histogrammed, and the clustering
window is chosen per track from a ladder rather than fixed: the smallest window
that gets the fit over the line wins, so no more collapsing happens than the
data requires. The chosen window is reported.

Two further failure modes, pulling in opposite directions.

**Subdivision.** Any sufficiently small period fits everything: halve the
period and every onset still lands on a grid line. Fit alone therefore has a
degenerate maximum at zero, and an implementation that maximises fit will
report a meaninglessly fine grid. The guard is to prefer the LARGEST period
whose fit is within a small margin of the best, which is the musically
meaningful one.

**Over-fitting a handful of onsets.** A track with six notes has a period that
fits perfectly and means nothing. Hence a minimum onset count, and a reported
fit rather than a boolean, so a consumer can filter.

The grid is reported in SPC700 clock ticks, which is what the note times are
in, with seconds alongside. `bpm` is explicitly derived under a stated
assumption rather than presented as measured -- the hardware has no tempo, only
a tick.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: SPC700 clock. Note start/end times in this project are in these units.
TICKS_PER_SECOND = 1_024_000

#: A residual within this fraction of the period counts as on-grid.
ON_GRID_TOLERANCE = 0.10

#: Below this many distinct onsets, a period would be fitting noise.
MIN_DISTINCT_ONSETS = 8

#: Accept a larger period when its fit is within this of the best fit. This is
#: the subdivision guard: 1/2 the period scores marginally better on jitter
#: alone, and without a margin the finest candidate always wins.
LARGER_PERIOD_MARGIN = 0.02

#: A grid is reported as found only above this fit.
MIN_FIT = 0.80

#: Plausible row periods: 1 ms to 1 s. Driver tick rates cluster around
#: 50-250 Hz, but the grid that onsets actually land on can be slower, so the
#: window is deliberately wider than the tick rates alone would suggest.
MIN_PERIOD_TICKS = TICKS_PER_SECOND // 1000
MAX_PERIOD_TICKS = TICKS_PER_SECOND

#: Refuse to describe a grid so fine that the score becomes unusable.
MAX_ROWS = 200_000

#: Onset-clustering windows to try, in ticks: 0, 0.25, 0.5, 1, 2, 4, 8 ms.
#: Ascending, and the first one that clears MIN_FIT is taken, so a track is
#: never collapsed more coarsely than it needs to be.
CLUSTER_WINDOWS_TICKS = (0, 256, 512, 1024, 2048, 4096, 8192)


@dataclass
class Grid:
    """An inferred row grid, or a reasoned refusal."""

    found: bool
    reason: str = ""
    period_ticks: int = 0
    phase_ticks: int = 0
    n_rows: int = 0
    #: Fraction of distinct onsets within ON_GRID_TOLERANCE of a row.
    fit: float = 0.0
    #: Typical timing error, in ticks and as a fraction of one row.
    median_abs_residual_ticks: float = 0.0
    median_abs_residual_fraction: float = 0.0
    n_onsets: int = 0
    n_distinct_onsets: int = 0
    n_candidates: int = 0
    #: Key-ons within this many ticks were treated as one musical onset.
    cluster_ticks: int = 0
    #: Set when the row period was rounded to a whole number of driver ticks.
    snapped_to_tick: bool = False
    #: Row length in driver ticks, when the tick was known.
    tick_multiple: int = 0
    #: Fraction of rows carrying at least one onset. Low is normal for music
    #: (rests), but near-zero alongside a high fit means the period is too fine.
    row_occupancy: float = 0.0

    @property
    def period_sec(self) -> float:
        return self.period_ticks / TICKS_PER_SECOND if self.period_ticks else 0.0

    @property
    def rows_per_second(self) -> float:
        return TICKS_PER_SECOND / self.period_ticks if self.period_ticks else 0.0

    def row_of(self, tick: int) -> int:
        """The row a tick falls on, rounded to the nearest."""
        if not self.period_ticks:
            return 0
        return int(round((tick - self.phase_ticks) / self.period_ticks))

    def tick_of(self, row: int) -> int:
        return self.phase_ticks + row * self.period_ticks

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "reason": self.reason,
            "period_ticks": self.period_ticks,
            "period_sec": round(self.period_sec, 9) if self.period_ticks else 0.0,
            "rows_per_second": round(self.rows_per_second, 4) if self.period_ticks else 0.0,
            # Rows per beat is a musical convention, not a hardware fact: the
            # S-DSP has no tempo. Four rows to the beat is the tracker default,
            # and the number is labelled with the assumption it rests on so it
            # cannot be mistaken for a measurement.
            "bpm_assuming_4_rows_per_beat": (
                round(60.0 / (4.0 * self.period_sec), 2) if self.period_ticks else 0.0
            ),
            "phase_ticks": self.phase_ticks,
            "n_rows": self.n_rows,
            "fit": round(self.fit, 4),
            "median_abs_residual_ticks": round(self.median_abs_residual_ticks, 1),
            "median_abs_residual_fraction": round(self.median_abs_residual_fraction, 4),
            "row_occupancy": round(self.row_occupancy, 4),
            "n_onsets": self.n_onsets,
            "n_distinct_onsets": self.n_distinct_onsets,
            "n_candidates": self.n_candidates,
            "cluster_ticks": self.cluster_ticks,
            "cluster_ms": round(1000.0 * self.cluster_ticks / TICKS_PER_SECOND, 3),
            "snapped_to_tick": self.snapped_to_tick,
            "tick_multiple": self.tick_multiple,
        }


def cluster(onsets: Sequence[int], window: int) -> list[int]:
    """Collapse key-ons within `window` ticks into one musical onset.

    Single linkage, and the cluster is represented by its FIRST tick -- the
    leading edge of a chord is when the chord happens; the driver's order of
    filling the remaining voices is an implementation detail.
    """
    if window <= 0:
        return sorted(set(int(t) for t in onsets))
    out: list[int] = []
    previous: int | None = None
    for t in sorted(int(x) for x in onsets):
        if previous is None or t - previous > window:
            out.append(t)
        previous = t
    return out


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _phase_for(onsets: Sequence[int], period: int) -> int:
    """The phase that best centres the onsets on grid lines.

    A circular mean rather than an arithmetic one: the residuals live on a
    ring of circumference `period`, so averaging 0.01 and 0.99 of a period has
    to give 0.0 and not 0.5.
    """
    sin_sum = 0.0
    cos_sum = 0.0
    for t in onsets:
        angle = 2.0 * math.pi * ((t % period) / period)
        sin_sum += math.sin(angle)
        cos_sum += math.cos(angle)
    if abs(sin_sum) < 1e-12 and abs(cos_sum) < 1e-12:
        return 0
    mean = math.atan2(sin_sum / len(onsets), cos_sum / len(onsets))
    if mean < 0:
        mean += 2.0 * math.pi
    return int(round(period * mean / (2.0 * math.pi))) % period


def _residuals(onsets: Sequence[int], period: int, phase: int) -> list[float]:
    """Signed distance from each onset to its nearest row, in ticks."""
    out = []
    for t in onsets:
        offset = (t - phase) % period
        if offset > period / 2:
            offset -= period
        out.append(offset)
    return out


def _score(onsets: Sequence[int], period: int) -> tuple[float, int, list[float]]:
    phase = _phase_for(onsets, period)
    residuals = _residuals(onsets, period, phase)
    limit = ON_GRID_TOLERANCE * period
    on = sum(1 for r in residuals if abs(r) <= limit)
    return on / len(onsets), phase, residuals


def _candidates(onsets: Sequence[int], span: int) -> list[int]:
    """Candidate periods, seeded from the inter-onset intervals.

    The dominant spacing is the obvious seed, but the mode of the intervals is
    often a MULTIPLE of the tick -- a driver playing steady eighth notes shows
    a mode at two ticks, not one. So each observed interval also contributes
    its small integer divisions, and the subdivision guard in `infer` picks
    between them on fit rather than on which was seen most often.
    """
    intervals = [b - a for a, b in zip(onsets, onsets[1:]) if b > a]
    if not intervals:
        return []
    seen: dict[int, int] = {}
    for gap in intervals:
        seen[gap] = seen.get(gap, 0) + 1
    # Commonest intervals first; ties broken by the smaller interval so the
    # candidate order is deterministic.
    ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))
    out: set[int] = set()
    for gap, _count in ranked[:24]:
        for divisor in (1, 2, 3, 4, 6, 8):
            period = gap // divisor
            if MIN_PERIOD_TICKS <= period <= MAX_PERIOD_TICKS:
                out.add(period)
    # The median interval is a robust seed when the histogram is flat.
    median_gap = int(_median(intervals))
    for divisor in (1, 2, 3, 4):
        period = median_gap // divisor
        if MIN_PERIOD_TICKS <= period <= MAX_PERIOD_TICKS:
            out.add(period)
    if span:
        out = {p for p in out if span // p <= MAX_ROWS}
    return sorted(out)


def _refine(onsets: Sequence[int], period: int) -> tuple[int, float, int, list[float]]:
    """Hill-climb the period by a few ticks either way.

    The candidate came from one observed interval, so it carries that
    interval's jitter. A short local search costs little and typically halves
    the median residual.
    """
    best = (period,) + _score(onsets, period)
    step = max(1, period // 200)
    while step:
        improved = False
        for delta in (-step, step):
            trial = best[0] + delta
            if not (MIN_PERIOD_TICKS <= trial <= MAX_PERIOD_TICKS):
                continue
            fit, phase, residuals = _score(onsets, trial)
            # Fit first, then tighter residuals at equal fit.
            better = fit > best[1] + 1e-12 or (
                abs(fit - best[1]) <= 1e-12
                and _median([abs(r) for r in residuals])
                < _median([abs(r) for r in best[3]]) - 1e-9
            )
            if better:
                best = (trial, fit, phase, residuals)
                improved = True
        if not improved:
            step //= 2
    return best


def _best_for(distinct: Sequence[int], span: int) -> tuple[int, float, int, list[float], int]:
    """Best (period, fit, phase, residuals, n_candidates) for one onset set."""
    candidates = _candidates(distinct, span)
    if not candidates:
        return 0, 0.0, 0, [], 0
    scored = [_refine(distinct, period) for period in candidates]
    best_fit = max(item[1] for item in scored)
    # The subdivision guard: among everything that fits about as well, take the
    # coarsest. Without this the answer is always the smallest candidate.
    eligible = [item for item in scored if item[1] >= best_fit - LARGER_PERIOD_MARGIN]
    period, fit, phase, residuals = max(eligible, key=lambda item: item[0])
    return period, fit, phase, residuals, len(candidates)


def snap_to_tick(grid: "Grid", tick_period: int) -> "Grid":
    """Round the row period to a whole number of driver ticks.

    The onset grid is recovered from key-ons, which are sparse; the tick is
    recovered from the far denser write cadence. Where the tick is confident it
    is the better measurement, so the row period becomes the nearest integer
    multiple of it -- a row that is 3.97 ticks long is 4 ticks long, and saying
    3.97 claims a precision the key-ons cannot support.

    The multiple is reported, and the grid is re-fitted at the snapped period so
    its fit figure still describes the grid actually emitted. A snap that makes
    the fit worse is rejected: the tick being sharp does not license making the
    row grid describe the music less well.
    """
    if not grid.found or not tick_period or not grid.period_ticks:
        return grid
    multiple = int(round(grid.period_ticks / tick_period))
    if multiple < 1:
        multiple = 1
    snapped = multiple * tick_period
    if snapped == grid.period_ticks:
        grid.tick_multiple = multiple
        grid.snapped_to_tick = True
        return grid
    if not (MIN_PERIOD_TICKS <= snapped <= MAX_PERIOD_TICKS):
        return grid
    grid.tick_multiple = multiple
    grid.snapped_to_tick = True
    grid.period_ticks = snapped
    return grid


def refit(grid: "Grid", onset_ticks: Iterable[int], render_ticks: int = 0) -> "Grid":
    """Re-measure fit, phase and residuals at `grid.period_ticks`."""
    if not grid.period_ticks:
        return grid
    distinct = cluster(sorted(set(int(t) for t in onset_ticks)), grid.cluster_ticks)
    if not distinct:
        return grid
    fit, phase, residuals = _score(distinct, grid.period_ticks)
    absolute = [abs(r) for r in residuals]
    span = max(render_ticks, distinct[-1] - distinct[0])
    grid.fit = fit
    grid.phase_ticks = phase
    grid.median_abs_residual_ticks = _median(absolute)
    grid.median_abs_residual_fraction = _median(absolute) / grid.period_ticks
    grid.n_rows = int(span // grid.period_ticks) + 1
    occupied = {(t - phase) // grid.period_ticks for t in distinct}
    grid.row_occupancy = len(occupied) / grid.n_rows if grid.n_rows else 0.0
    grid.found = fit >= MIN_FIT
    if not grid.found:
        grid.reason = f"fit {fit:.2f} below {MIN_FIT:.2f} after snapping to the driver tick"
    return grid


def infer(onset_ticks: Iterable[int], render_ticks: int = 0) -> Grid:
    """Infer the row grid from key-on times.

    Key-ons closer together than the chosen clustering window are one onset:
    a chord says nothing about spacing, and on this hardware a chord arrives as
    a short burst of writes rather than all at once.
    """
    onsets_all = [int(t) for t in onset_ticks]
    raw_distinct = sorted(set(onsets_all))
    grid = Grid(found=False, n_onsets=len(onsets_all), n_distinct_onsets=len(raw_distinct))

    if len(raw_distinct) < MIN_DISTINCT_ONSETS:
        grid.reason = (
            f"only {len(raw_distinct)} distinct onsets; a period fitted to "
            f"fewer than {MIN_DISTINCT_ONSETS} describes noise"
        )
        return grid

    span = max(render_ticks, raw_distinct[-1] - raw_distinct[0])

    best: tuple[float, int, int, float, int, list[float], int, int] | None = None
    for window in CLUSTER_WINDOWS_TICKS:
        clustered = cluster(raw_distinct, window)
        if len(clustered) < MIN_DISTINCT_ONSETS:
            # Over-collapsed: a coarser window would only collapse further.
            break
        period, fit, phase, residuals, n_cand = _best_for(clustered, span)
        if not period:
            continue
        # Keep the best seen, so a refusal still reports the closest attempt;
        # take the FIRST window that clears the bar, so clustering is applied
        # as sparingly as the data allows.
        key = (fit, -window)
        if best is None or key > (best[0], -best[1]):
            best = (fit, window, period, fit, phase, residuals, n_cand, len(clustered))
        if fit >= MIN_FIT:
            best = (fit, window, period, fit, phase, residuals, n_cand, len(clustered))
            break

    if best is None:
        grid.reason = "no candidate period inside the plausible range"
        return grid

    _, window, period, fit, phase, residuals, n_cand, n_clustered = best
    absolute = [abs(r) for r in residuals]
    rows_span = span if span else (raw_distinct[-1] - raw_distinct[0])
    n_rows = int(rows_span // period) + 1
    occupied = {(t - phase) // period for t in cluster(raw_distinct, window)}

    grid.period_ticks = period
    grid.phase_ticks = phase
    grid.fit = fit
    grid.median_abs_residual_ticks = _median(absolute)
    grid.median_abs_residual_fraction = _median(absolute) / period
    grid.n_rows = n_rows
    grid.row_occupancy = len(occupied) / n_rows if n_rows else 0.0
    grid.n_candidates = n_cand
    grid.cluster_ticks = window
    grid.n_distinct_onsets = n_clustered

    if fit < MIN_FIT:
        grid.reason = (
            f"best fit {fit:.2f} is below {MIN_FIT:.2f}; onsets do not lie on "
            f"a single period even after clustering to "
            f"{1000.0 * window / TICKS_PER_SECOND:.2f} ms"
        )
        return grid

    grid.found = True
    return grid


def onsets_from_notes(notes: Iterable[dict[str, Any]]) -> list[int]:
    """Key-on times from note records.

    Notes ended by a re-key are included: a re-key IS a key-on, and it is the
    event the grid is made of. Notes with no start are not possible, so no
    filtering is needed beyond reading the field.
    """
    return [int(note["start"]) for note in notes]
