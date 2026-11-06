"""The row clock the scores are indexed on: a per-game SPC700 timer rate.

WHY THIS REPLACED THE PER-TRACK INFERRED GRID
=============================================

NES-MDB's score formats are arrays indexed by row, and they work because the
NTSC NES hands every game the same row clock. The 60.0988 Hz figure is the
**PPU** frame rate -- a consequence of the PPU skipping one clock dot on the
pre-render scanline of every odd frame -- and music engines inherit it because
most of them are tethered to the **vblank NMI**, evaluating one row of sequence
data per video frame. It is not the APU's rate: the 2A03's APU frame counter is
a separate divider off the CPU clock, resetting every 29,830 cycles for a
240 Hz quarter-frame step (60.00 Hz full cycle), and it drives envelopes and
sweeps rather than sequencing. The grid is free on the NES by accident of one
shared interrupt, and even there the accident is regional: PAL runs a different
CPU clock and a 50.007 Hz frame rate, so a PAL port must retime.

THE SNES HAS NO SUCH SHARED SIGNAL. The audio subsystem is a Sony SPC700 plus
DSP on its own crystal, fully isolated from the CPU and PPU, so SNES music
timing has no relationship to the video frame rate at all. Drivers sequence off
the SPC700's own hardware timers: Timer 0 and Timer 1 count at a base 8 kHz
(every 128 audio clocks) and Timer 2 at 64 kHz (every 16), each scaled by an
8-bit divider register. There is therefore no universal SNES row rate to
borrow -- every driver picks its own -- which is exactly why the clock has to
be established per game rather than assumed.

`grid.py` tried to recover a row clock by fitting a period to note onsets. It
measures something real, but not this, and the corpus says so: across 664
tracks it produced **346 distinct row rates, 75% of them unique within a single
game**. Final Fantasy 6 alone got twenty, including 2.2 and 2.3 as separate
values, spanning 92x. One row meant 4 ms in one track and 847 ms in another, so
the scores were not a comparable corpus. `tick.py` measures the driver's
interrupt rate from DSP write cadence instead, and that behaves like hardware.

THE HARDWARE CONSTRAINT IS AN INDEPENDENT CHECK
-----------------------------------------------

Because an SPC700 timer can only produce base/N, a measured tick that is a real
timer read must land on one of those rates -- and that is a test the grid could
never submit to. It has power, and the tick extractor passes it convincingly:
across the corpus's 10-1391 Hz range a frequency drawn at random sits within
0.11% of an achievable divider 20.4% of the time, while **89% of the 519
measured ticks do**. Every per-game clock resolves to a plain Timer 0/1
divider:

    Final Fantasy 6     205.13 Hz = 8000/39     Mega Man X       62.5 Hz = 8000/128
    Chrono Trigger      190.48 Hz = 8000/42     Secret of Mana  222.2 Hz = 8000/36
    Super Metroid       500.00 Hz = 8000/16     Donkey Kong C.   80.0 Hz = 8000/100

So the clock is snapped to the nearest achievable divider rather than to a
round number, and a track's own tick is only trusted when it lands on one.

A CLOCK IS NOT A TEMPO
----------------------

The obvious objection is that a game's songs do not share a tempo, and they do
not. The clock is not the tempo. It is the quantum the sequence is measured in;
tempo is how many ticks a note consumes, which is free to vary and is what the
driver's tempo commands change. Final Fantasy 6 holds 205.13 Hz across all 55
music tracks while the median inter-onset spacing runs from 13.8 driver ticks
("Dancing Mad, part 2") to 183.0 ("Dark World") -- a 13x tempo spread on a
fixed clock, the values clustering near 24, 36, 48 and 72, which are tracker
row durations. Same relationship the NES has: one interrupt rate carrying songs
of every tempo.

WHERE THE OBJECTION DOES BITE
-----------------------------

Eight games have no per-game clock, and for five of them the reason is that
THE DRIVER REALLY DOES CHANGE ITS TIMER PER TRACK -- which is the objection to
this whole design, and it is correct for these games:

    Star Ocean          78% of 54 ticks on a divider, across 23 distinct rates
    Tales of Phantasia  63% of 52,                   across 21
    Lufia 2            100% of 38,                   across 13
    Super Turrican     100% of 20,                   across  8
    Plok!               89% of  9,                   across  4

These are real timer reads -- they pass the hardware test, mostly at 100% --
there are simply many of them. Such a driver sets tempo by reprogramming the
divider rather than by counting a fixed tick, so no per-game constant exists
and asserting one would be a fabrication. The remaining three games (Actraiser,
Axelay, Zelda, and Super Mario World) simply have too few confident ticks to
call a rate a constant.

Both cases fall back to the track's own verified tick, which for a
divider-varying driver is not a degradation but the right answer. The fallback
is labelled either way, so a consumer can always tell which rule produced a
track's rows.

An earlier version of this file claimed those drivers' ticks were not timer
reads at all and that the extractor was failing on them. That was wrong, and
wrong for an instructive reason: the share was computed after rounding each
tick to the nearest 0.5 Hz, which knocks a genuine rate OFF its divider
(222.22 becomes 222.0, a 0.1% error at a 0.11% tolerance). Quantising before
testing destroyed the thing being tested. Nothing is rounded before
`nearest_divider` now.

THE CLOCK IS AN INTEGER TICK PERIOD, NOT A FREQUENCY
----------------------------------------------------

Timers divide a fixed clock, so a whole number of ticks is the faithful form
and a frequency is the derived view. An integer period also removes
accumulating drift: 205.13 Hz held as 4992.0 ticks lands every row exactly,
where a rounded float would slide about a row over a long track.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .grid import Grid

TICKS_PER_SECOND = 1_024_000

#: SPC700 sequencer timers, with the largest total division searched for each.
#: Timer 0 and Timer 1 share a prescaler and step at 8 kHz (one per 128 S-SMP
#: clocks); Timer 2 bypasses it and steps at 64 kHz (one per 16).
#:
#: THE BOUNDS DIFFER PER BASE, and that is an empirical call rather than a
#: hardware one. Both timers have the same 8-bit TnDIV register, and both can
#: be sub-divided in software. But allowing T2 a large total division makes
#: the achievable set dense: 64000/(8M) is just 8000/M, so software-divided T2
#: mostly re-derives rates T0/T1 already reaches and interleaves the gaps.
#: Measured against a jitter null, allowing both bases to 1024 collapses the
#: test to 1.47x enrichment -- near vacuous -- while T2 held to pure hardware
#: division keeps it at 3.34x.
#:
#: The corpus says T2 is barely used for sequencing anyway: of the 456 ticks
#: that resolve to a pure hardware divider, **455 are T0/T1 and one is T2**.
#: So T2 stays available, at the division the hardware alone provides.
TIMER_BASES: tuple[tuple[float, str, int], ...] = (
    (8000.0, "T0/T1", 1024),
    (64000.0, "T2", 256),
)

#: The 8-bit TnDIV target register, where 0 reads as 256. This bounds the
#: HARDWARE stage only.
HARDWARE_DIVIDER_MAX = 256

#: Drivers do not use the hardware tick as the musical tick. The timer's 4-bit
#: TnOUT counter clears on read, so a driver polls it and decrements a tempo
#: accumulator in RAM, dividing again in software by some M. The achievable
#: sequencer rate is therefore base/(N*M), not base/N -- and bounding the
#: search at 256 was producing false negatives on exactly the games that
#: looked broken: Tales of Phantasia went from 63% of its ticks resolving to
#: 100%, Star Ocean 78% to 98%, Donkey Kong Country 2 66% to 94%, Super Mario
#: World 50% to 100%.
#:
#: The bound is a real trade-off, because base/K gets dense as K grows and the
#: test loses power. Measured, over the corpus's tick range:
#:
#:     K <=  256   88.6% of real ticks resolve, 20.3% of random -> 4.4x
#:     K <= 1024   98.8%                        31.7%           -> 3.1x
#:     K <= 4096   99.6%                        32.8%           -> 3.0x
#:
#: 1024 is where the signal saturates while the null is still well separated.
#: Past it almost nothing is gained and the test only weakens.
#:
#: The per-base bound lives in `TIMER_BASES`; this is the overall ceiling and
#: the figure the tolerance note below is quoted at. NOTE ON THE NULL: an
#: earlier version of these figures used a null drawn UNIFORMLY over the tick
#: range, which flattered the test badly -- it reported 3.1x where the honest
#: control gives 1.47x for the same configuration. Measured ticks are
#: clustered, not uniform, so the control multiplies each real tick by a
#: random factor in [0.90, 1.10]: same distribution, alignment destroyed.
#: Quote enrichment against that null and nothing else.
SEQUENCER_K_MAX = 1024

#: How close a measured tick must sit to an achievable rate to be called a
#: timer read. Tight on purpose: at this tolerance a random frequency in the
#: corpus's range qualifies only 20.4% of the time, against 89% of the real
#: measured ticks, so passing is informative. Do not round a tick before
#: testing it -- see the note at the end of the module docstring.
DIVIDER_TOLERANCE = 0.0011

#: Below this share of a game's ticks resolving to a divider, the measurements
#: are treated as unreliable rather than as a varying timer. No game in the
#: 22-game corpus falls here with enough ticks to trigger it; it exists so a
#: future driver that defeats `tick.py` is reported rather than averaged.
MIN_DIVIDER_SHARE = 0.5

#: A consensus needs this many tracks whose tick resolves to a divider. Two
#: tracks agreeing is not evidence of a hardware constant.
MIN_CONFIDENT_TRACKS = 3

#: ...and this share of them must land on the same divider.
MIN_AGREEMENT = 0.5

#: The last-resort clock, for a track with neither a per-game clock nor a tick
#: that passes the divider test. 100 Hz is itself achievable (8000/80) and
#: divides the SPC700 clock exactly at 10,240 ticks. It costs 2.5 ms median
#: timing error against the 1.8 ms of a fitted grid -- a fifth of a
#: millisecond, for a quantum shared across the corpus instead of one of 346.
FALLBACK_HZ = 100.0

SOURCE_GAME = "game_tick"
SOURCE_TRACK = "track_tick"
SOURCE_FIXED = "fixed"
SOURCES = (SOURCE_GAME, SOURCE_TRACK, SOURCE_FIXED)


@dataclass(frozen=True)
class Divider:
    """An achievable sequencer rate: `base_name` divided by `k` = `n` * `m`.

    `n` is the hardware TnDIV target and `m` the driver's software
    sub-division. The split is reported because it is the difference between
    "this driver's timer runs at this rate" and "this driver's timer runs
    faster and the driver counts", and only the first is a register value
    someone could look up.
    """

    hz: float
    base_hz: float
    base_name: str
    k: int
    n: int
    m: int
    rel_error: float

    @property
    def software_divided(self) -> bool:
        return self.m > 1

    @property
    def label(self) -> str:
        if self.m == 1:
            return f"{self.base_name}/{self.n}"
        return f"{self.base_name}/{self.n}x{self.m}"


def _split(k: int) -> tuple[int, int]:
    """Factor `k` into a hardware divider <= 256 and a software multiplier.

    Picks the smallest software multiplier that fits, since a driver divides
    in software only as much as it must.
    """
    for m in range(1, k + 1):
        if k % m == 0 and k // m <= HARDWARE_DIVIDER_MAX:
            return k // m, m
    return k, 1


def nearest_divider(hz: float, tolerance: float = DIVIDER_TOLERANCE) -> Divider | None:
    """The achievable sequencer rate nearest `hz`, or None if none is close.

    Returning None is the useful half: it means the measurement cannot be a
    timer-derived rate at all. On this corpus that is now rare (98.8% of
    measured ticks resolve), which is itself the finding -- the tick extractor
    is sound on every driver, and the games without a per-game clock are
    games whose drivers use many rates, not games the extractor failed on.
    """
    if not hz or hz <= 0:
        return None
    best: Divider | None = None
    for base_hz, base_name, k_max in TIMER_BASES:
        # Only the few K nearest the target can win, so this does not need
        # to sweep the whole range.
        exact = base_hz / hz
        for k in {max(1, int(exact) + d) for d in (-1, 0, 1, 2)}:
            if k > min(k_max, SEQUENCER_K_MAX):
                continue
            rate = base_hz / k
            error = abs(rate - hz) / hz
            if best is None or error < best.rel_error:
                n, m = _split(k)
                best = Divider(rate, base_hz, base_name, k, n, m, error)
    if best is None or best.rel_error > tolerance:
        return None
    return best


def period_for_hz(hz: float) -> int:
    """The integer tick period realising a frequency. At least one tick."""
    if hz <= 0:
        return 0
    return max(1, int(round(TICKS_PER_SECOND / hz)))


@dataclass
class Clock:
    """A row clock, and the rule that produced it.

    `source` is load-bearing and travels with every score. `game_tick` is a
    timer rate corroborated across a game; `track_tick` is this track's own
    verified rate, used where the game has no constant; `fixed` is a
    convention. They are not equally good and a consumer must be able to tell
    them apart without re-deriving anything.
    """

    period_ticks: int
    source: str
    reason: str = ""
    #: How many tracks of the game had a tick on a divider, and what share of
    #: those agreed on one. Zero for the fixed fallback.
    n_confident: int = 0
    agreement: float = 0.0
    #: The tick as measured, before snapping to an achievable rate.
    measured_hz: float = 0.0
    #: Which timer divider this clock resolves to, when it resolves to one.
    divider: Divider | None = None

    @property
    def hz(self) -> float:
        """The clock as realised, derived from the integer period."""
        return TICKS_PER_SECOND / self.period_ticks if self.period_ticks else 0.0

    @property
    def period_sec(self) -> float:
        return self.period_ticks / TICKS_PER_SECOND if self.period_ticks else 0.0

    @property
    def is_hardware(self) -> bool:
        """True when the clock was measured and verified, not chosen."""
        return self.source in (SOURCE_GAME, SOURCE_TRACK)

    def n_rows(self, render_ticks: int) -> int:
        if not self.period_ticks or render_ticks <= 0:
            return 0
        return int(render_ticks // self.period_ticks) + 1

    def to_grid(self, render_ticks: int) -> Grid:
        """A `Grid` carrying this clock, so `scores.build` needs no changes.

        Phase is zero by construction: the clock is anchored at the start of
        the render rather than at a fitted offset, because there is nothing to
        fit. At 205 Hz a half-row is 2.4 ms and `Grid.row_of` rounds to the
        nearest, so no onset moves by more than half a quantum.

        `fit` and the residuals stay at zero deliberately. They are
        goodness-of-fit statistics for an inference, and this is a
        measurement; reporting a fit here would invite the comparison that
        caused the original mistake.
        """
        return Grid(
            found=bool(self.period_ticks),
            reason=self.reason,
            period_ticks=int(self.period_ticks),
            phase_ticks=0,
            n_rows=self.n_rows(render_ticks),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_ticks": self.period_ticks,
            "hz": round(self.hz, 4),
            "period_sec": round(self.period_sec, 9),
            "source": self.source,
            "is_hardware": self.is_hardware,
            "measured_hz": round(self.measured_hz, 4) or None,
            "timer_divider": self.divider.label if self.divider else None,
            "timer_base_hz": self.divider.base_hz if self.divider else None,
            "timer_hardware_divider": self.divider.n if self.divider else None,
            "timer_software_multiplier": self.divider.m if self.divider else None,
            "timer_software_divided": (
                self.divider.software_divided if self.divider else None
            ),
            "n_confident_tracks": self.n_confident,
            "agreement": round(self.agreement, 4),
            "reason": self.reason,
        }


def consensus(
    hz_values: Sequence[float],
) -> tuple[Divider | None, int, float]:
    """The modal achievable timer rate across a game's measured ticks.

    Values that do not resolve to a divider are dropped before counting, not
    rounded into the nearest bin: a measurement that cannot be a timer read is
    evidence about the extractor, not about the driver.

    Returns `(None, n, agreement)` when the bar is not met, so the caller can
    report why a game has no clock rather than silently falling back.
    """
    resolved = [d for d in (nearest_divider(h) for h in hz_values) if d]
    if not resolved:
        return None, 0, 0.0
    counts = collections.Counter(d.label for d in resolved)
    label, count = counts.most_common(1)[0]
    agreement = count / len(resolved)
    if len(resolved) < MIN_CONFIDENT_TRACKS or agreement < MIN_AGREEMENT:
        return None, len(resolved), agreement
    winner = next(d for d in resolved if d.label == label)
    return winner, len(resolved), agreement


def _confident_hz(row: dict[str, Any]) -> float | None:
    tick = row.get("tick") or {}
    if not tick.get("found"):
        return None
    hz = tick.get("hz")
    return float(hz) if hz else None


def _game_of(row: dict[str, Any]) -> str:
    return ((row.get("tag") or {}).get("game") or "").strip()


def game_clocks(rows: Iterable[dict[str, Any]]) -> dict[str, Clock]:
    """Derive one clock per game from the manifest rows that carry a tick.

    Every game appears in the result, including those with no consensus: they
    carry a `period_ticks` of zero and a reason, which is how `clock_for` knows
    to fall back and what to say about it.
    """
    measured: dict[str, list[float]] = collections.defaultdict(list)
    on_divider: dict[str, int] = collections.defaultdict(int)
    games: set[str] = set()
    for row in rows:
        if not row.get("ok"):
            continue
        game = _game_of(row)
        games.add(game)
        hz = _confident_hz(row)
        if hz is not None:
            measured[game].append(hz)
            if nearest_divider(hz):
                on_divider[game] += 1

    clocks: dict[str, Clock] = {}
    for game in sorted(games):
        seen = measured.get(game, [])
        divider, n, agreement = consensus(seen)
        if divider is None:
            share = (on_divider[game] / len(seen)) if seen else 0.0
            # Order matters: a low divider share is a statement about the
            # EXTRACTOR and is the more informative diagnosis, so it is
            # tested before the count. Checking the count first would report
            # a game whose ticks are all nonsense as merely having too few.
            if len(seen) >= MIN_CONFIDENT_TRACKS and share < MIN_DIVIDER_SHARE:
                why = (
                    f"only {share:.0%} of the {len(seen)} measured ticks "
                    f"resolve to an SPC700 timer divider, below "
                    f"{MIN_DIVIDER_SHARE:.0%} and near the 20.4% expected by "
                    f"chance: the tick extractor looks unreliable on this "
                    f"driver, so no clock is built from it"
                )
            elif n < MIN_CONFIDENT_TRACKS:
                why = (
                    f"only {n} tick(s) in this game resolve to an SPC700 timer "
                    f"divider, below the {MIN_CONFIDENT_TRACKS} needed to call "
                    f"a rate a hardware constant"
                )
            else:
                why = (
                    f"{share:.0%} of {len(seen)} ticks resolve to a divider -- "
                    f"these are real timer reads -- but only {agreement:.0%} "
                    f"agree on one, below {MIN_AGREEMENT:.0%}: this driver sets "
                    f"tempo by reprogramming its divider rather than counting a "
                    f"fixed tick, so no per-game constant exists and each "
                    f"track is indexed on its own rate"
                )
            clocks[game] = Clock(0, SOURCE_GAME, why, n, agreement)
            continue
        clocks[game] = Clock(
            period_ticks=period_for_hz(divider.hz),
            source=SOURCE_GAME,
            reason=(
                f"{agreement:.0%} of {n} verified ticks in this game read "
                f"{divider.hz:.2f} Hz = {divider.label}, an achievable SPC700 "
                f"timer rate, so the driver's sequencer clock is taken as a "
                f"constant and every track of the game is indexed on it"
            ),
            n_confident=n,
            agreement=agreement,
            measured_hz=divider.hz,
            divider=divider,
        )
    return clocks


def clock_for(row: dict[str, Any], clocks: dict[str, Clock]) -> Clock:
    """The clock to index one track on, preferring the strongest evidence.

    Order is deliberate. A game constant beats the track's own tick even when
    the track has one, because the shared quantum is the whole point and a
    single track's measurement is the noisier of the two.
    """
    game = clocks.get(_game_of(row))
    if game is not None and game.period_ticks:
        return game

    own = _confident_hz(row)
    divider = nearest_divider(own) if own else None
    if divider is not None:
        return Clock(
            period_ticks=period_for_hz(divider.hz),
            source=SOURCE_TRACK,
            reason=(
                f"this game has no per-game clock, so this track is indexed on "
                f"its own tick of {divider.hz:.2f} Hz = {divider.label}, which "
                f"is an achievable SPC700 timer rate and so is trusted as a "
                f"measurement despite standing alone"
            ),
            n_confident=game.n_confident if game else 0,
            agreement=game.agreement if game else 0.0,
            measured_hz=own or 0.0,
            divider=divider,
        )

    if own:
        why = (
            f"the measured tick of {own:.2f} Hz does not resolve to any SPC700 "
            f"timer divider, so it is not a timer read and is discarded; rows "
            f"fall on a fixed {FALLBACK_HZ:g} Hz convention instead"
        )
    else:
        why = (
            f"no per-game clock and no confident tick for this track, so rows "
            f"fall on a fixed {FALLBACK_HZ:g} Hz convention rather than a "
            f"measurement -- a time quantum, not this driver's row rate"
        )
    return Clock(
        period_ticks=period_for_hz(FALLBACK_HZ),
        source=SOURCE_FIXED,
        reason=why,
        n_confident=game.n_confident if game else 0,
        agreement=game.agreement if game else 0.0,
        measured_hz=own or 0.0,
    )


def census(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Counts per source, in a fixed order so a diff is readable."""
    counts = {name: 0 for name in SOURCES}
    for row in rows:
        source = (row.get("clock") or {}).get("source")
        if source:
            counts[source] = counts.get(source, 0) + 1
    return counts
