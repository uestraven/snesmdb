"""The SPC700's own timer configuration, read out of the SPC file.

An SPC dump contains the 64 KB of ARAM, and the SPC700's timer registers live
in its I/O page: `$F1` holds the enable bits and `$FA`, `$FB`, `$FC` hold the
T0, T1 and T2 targets. So the rate the audio CPU woke up at is **stored in the
file** -- it never needed inferring from write cadence at all.

WHY THIS REPLACED THE INFERRED CLOCK. `tick.py` recovers the sequencer rate
from DSP write cadence, which works where a driver re-uploads its register
block every tick and fails where it does not. It failed on 220 tracks, 178 of
them music, and those fell back to a fabricated 100 Hz. Three hypotheses for
the failure were tested against write logs and all three were refused: the
periodic signal is not hidden, it is absent. N-SPC simply does not expose a
tick in its DSP writes.

Reading the register instead reproduces every clock the estimator did find and
supplies one for every game it could not:

    Chrono Trigger   T0 190.48 Hz   = write-cadence 190.48    agrees
    Super Metroid    T0 500.00      = 500.00                  agrees
    Final Fantasy 6  T0 205.13      = 205.13                  agrees
    Secret of Mana   T0 222.22      = 222.22                  agrees
    Donkey Kong C.   T0  80.00      =  80.00                  agrees
    Super Mario World T0 500.00     = (estimator failed)      supplies
    Zelda            T0 500.00      = (estimator failed)      supplies

Four games differ, each by an exact power of two -- Batman Returns 2x, Breath
of Fire 2 and Mega Man X 1/2, Plok! 1/4. That is the software divisor: the
register gives the HARDWARE timer rate and write cadence gives the EFFECTIVE
sequencer rate, which is the timer divided by however many ticks the driver
counts per row. Ten exact agreements and four clean integer ratios corroborate
both measurements rather than conflicting.

ROWS ARE HARDWARE TICKS, AND THAT IS A CHOICE. Indexing rows on the raw timer
means a row is one physical timer tick everywhere, with no inference and no
fallback -- 1,316 of 1,316 tracks have an enabled timer. The cost is that where
a driver counts M ticks per musical row, rows are M times finer than the music
and a note spans several of them. The alternative, dividing by M, is only
available for the drivers whose write cadence can be read, so it would make the
row unit mean different things in different tracks. The uniform definition was
chosen over the musical one deliberately.

Note that a row is a uniform *definition* but not a uniform *duration*: `$FA`
differs per game, so a row is 2.00 ms in Super Mario World and 12.50 ms in
Donkey Kong Country. Cross-game comparison of anything per-row still has to go
through `clock.hz`.

A CAVEAT ON THE SOURCE. `$F1` is write-only on real hardware, so the byte an
SPC file carries there is a convention of the dump format rather than something
the CPU could read back. It is trusted here because it validates: the enables
and targets reproduce ten independently measured clocks exactly, which a
meaningless byte would not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: SPC700 I/O page addresses, as offsets into ARAM.
REG_CONTROL = 0x00F1
REG_T0_TARGET = 0x00FA
REG_T1_TARGET = 0x00FB
REG_T2_TARGET = 0x00FC

#: Timer 0 and Timer 1 share a prescaler and step at 8 kHz; Timer 2 steps at
#: 64 kHz. The same bases `clock.py` tests achievable rates against.
T01_BASE_HZ = 8000.0
T2_BASE_HZ = 64000.0

#: `$F1` bit 0 enables T0, bit 1 enables T1, bit 2 enables T2. The upper bits
#: are port-clear and IPL-ROM controls and carry no timing meaning.
ENABLE_BITS = ((0, "T0", T01_BASE_HZ, REG_T0_TARGET),
               (1, "T1", T01_BASE_HZ, REG_T1_TARGET),
               (2, "T2", T2_BASE_HZ, REG_T2_TARGET))

#: An 8-bit target register where 0 counts as 256.
TARGET_WRAP = 256


@dataclass
class Timers:
    """The timer configuration one SPC file was dumped with."""

    control: int
    targets: dict[str, int]
    #: Enabled timers, in hardware order, as `(name, hz)`.
    enabled: list[tuple[str, float]]

    @property
    def sequencer(self) -> tuple[str, float] | None:
        """The timer taken to drive the sequencer: the lowest enabled one.

        Validated rather than assumed. Chrono Trigger enables both T0 (190.48
        Hz) and T1 (62.5 Hz), and 190.48 is the rate write cadence measures,
        so the lower-numbered timer is the sequencer there. Every game whose
        clock was independently measured agrees under this rule.
        """
        return self.enabled[0] if self.enabled else None

    @property
    def hz(self) -> float:
        pick = self.sequencer
        return pick[1] if pick else 0.0

    @property
    def name(self) -> str:
        pick = self.sequencer
        return pick[0] if pick else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "targets": dict(self.targets),
            "enabled": [{"timer": n, "hz": round(h, 4)} for n, h in self.enabled],
            "sequencer_timer": self.name or None,
            "sequencer_hz": round(self.hz, 4) if self.hz else None,
        }


def rate_for(base_hz: float, target: int) -> float:
    """`base / target`, with a zero target meaning 256."""
    return base_hz / (target if target else TARGET_WRAP)


def read(aram: bytes) -> Timers:
    """The timer configuration in a 64 KB ARAM image."""
    if len(aram) <= REG_T2_TARGET:
        return Timers(0, {}, [])
    control = aram[REG_CONTROL]
    targets = {
        "T0": aram[REG_T0_TARGET],
        "T1": aram[REG_T1_TARGET],
        "T2": aram[REG_T2_TARGET],
    }
    enabled: list[tuple[str, float]] = []
    for bit, name, base, address in ENABLE_BITS:
        if (control >> bit) & 1:
            enabled.append((name, rate_for(base, aram[address])))
    return Timers(control, targets, enabled)
