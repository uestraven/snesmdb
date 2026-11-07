"""The per-game row clock that replaced the per-track inferred grid.

The property these tests exist to defend is that a clock is NOT a tempo. The
objection that sank the first design is that a game's songs do not share a
tempo -- true, and irrelevant, because the clock is the quantum the sequence is
measured in and the tempo is how many quanta a note lasts. Several tests below
assert exactly that separation, because a future change that conflated them
would look harmless and would quietly destroy the corpus.
"""

from __future__ import annotations

import random

import pytest

from snesmdb import clock as clock_mod, scores
from snesmdb.clock import (
    Clock,
    clock_for,
    nearest_divider,
    period_for_hz,
)

TICKS = clock_mod.TICKS_PER_SECOND

#: Real per-game clocks measured from the corpus, with the divider each one
#: resolves to. Every value here was measured before the constraint was known,
#: so their agreeing with it is a result and not a construction.
REAL_CLOCKS = {
    "Final Fantasy 6": (205.1, "T0/T1/39"),
    "Chrono Trigger": (190.5, "T0/T1/42"),
    "Secret of Mana": (222.2, "T0/T1/36"),
    "Mega Man X": (62.5, "T0/T1/128"),
    "Breath of Fire 2": (62.5, "T0/T1/128"),
    "Donkey Kong Country": (80.0, "T0/T1/100"),
    "Super Metroid": (500.0, "T0/T1/16"),
    "Super Castlevania 4": (250.0, "T0/T1/32"),
    "Dragon Quest 5": (200.0, "T0/T1/40"),
}


def _row(game, hz=None, found=None, ok=True, title="t"):
    tick = {}
    if hz is not None or found is not None:
        tick = {"found": found if found is not None else hz is not None, "hz": hz}
    return {"ok": ok, "tag": {"game": game, "title": title}, "tick": tick}


# --------------------------------------------------------------------------
# the hardware constraint: a timer can only produce base/N
# --------------------------------------------------------------------------

@pytest.mark.parametrize("hz,label", list(REAL_CLOCKS.values()))
def test_every_measured_game_clock_is_an_achievable_timer_rate(hz, label):
    """Timer 0/1 count at 8 kHz, Timer 2 at 64 kHz, each with an 8-bit divider.

    A measured tick that is a real timer read has to land on base/N, and all
    nine of these do. This is the check the inferred grid could never submit
    to, and it is why the clock is trusted at all.
    """
    divider = nearest_divider(hz)
    assert divider is not None, f"{hz} Hz is not an achievable SPC700 rate"
    assert divider.label == label
    assert divider.base_hz in [base for base, _, _ in clock_mod.TIMER_BASES]


def test_the_divider_test_can_fail():
    """It would be worthless if everything passed.

    These values were found by sweeping the real achievable set, not guessed.
    An earlier version of this test guessed, and three of its five fixtures
    were actually valid rates.
    """
    failures = [hz for hz in (0.5 * i for i in range(60, 2000))
                if nearest_divider(hz) is None]
    assert len(failures) > 400, "almost nothing fails: the net has grown too wide"
    assert nearest_divider(41.7) is not None   # 8000/192, to within 0.08%


def test_the_divider_test_is_not_vacuous():
    """The guard against the net growing until it catches everything.

    This is the test that would have caught the real mistake here. Allowing
    both timer bases a total division of 1024 took the enrichment over a
    jitter null from 3.34x to 1.47x -- the signal stayed at ~98% while the
    NULL climbed to 67%, so the measurement looked better while meaning less.
    A sweep of arbitrary frequencies must leave a clear majority failing.
    """
    rng = random.Random(0)
    arbitrary = [rng.uniform(40.0, 600.0) for _ in range(2000)]
    passing = sum(1 for hz in arbitrary if nearest_divider(hz)) / len(arbitrary)
    assert passing < 0.40, (
        f"{passing:.0%} of arbitrary frequencies resolve: the achievable set "
        f"has grown dense enough that passing it proves little"
    )
    assert all(nearest_divider(hz) for hz, _ in REAL_CLOCKS.values())


def test_timer_two_is_held_to_pure_hardware_division():
    """Software-divided T2 is what made the test vacuous.

    64000/(8M) is 8000/M, so allowing T2 a large total division mostly
    re-derives T0/T1 rates and interleaves the gaps. The corpus justifies the
    restriction: of 456 ticks on a pure hardware divider, 455 are T0/T1.
    """
    bounds = {name: k for _, name, k in clock_mod.TIMER_BASES}
    assert bounds["T2"] <= clock_mod.HARDWARE_DIVIDER_MAX
    assert bounds["T0/T1"] > clock_mod.HARDWARE_DIVIDER_MAX
    # 64000/300 would need software division on T2, so it must not resolve.
    assert nearest_divider(64000.0 / 300) is None


def test_software_division_is_recognised_and_reported_as_such():
    """8000/300 needs a divider no 8-bit register holds, so it implies the
    driver polled TnOUT and counted. That is a real driver pattern and the
    rate is achievable -- but the split must be visible, because only the
    hardware half is a register value someone could look up."""
    assert clock_mod.HARDWARE_DIVIDER_MAX == 256
    divider = nearest_divider(8000.0 / 300)
    assert divider is not None
    assert divider.k == 300 and divider.software_divided
    assert divider.n <= clock_mod.HARDWARE_DIVIDER_MAX
    assert divider.n * divider.m == divider.k
    assert "x" in divider.label


def test_a_pure_hardware_rate_is_not_labelled_software_divided():
    divider = nearest_divider(8000.0 / 128)
    assert divider is not None
    assert divider.m == 1 and not divider.software_divided
    assert divider.label == "T0/T1/128"


def test_timer_two_covers_the_fast_rates():
    divider = nearest_divider(64000.0 / 3)
    assert divider is not None and divider.base_name == "T2"


# --------------------------------------------------------------------------
# consensus
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# the clock is an integer tick period
# --------------------------------------------------------------------------

def test_period_is_a_whole_number_of_ticks():
    """SPC700 timers divide a fixed clock, so the period is the faithful form."""
    for hz, _ in REAL_CLOCKS.values():
        period = period_for_hz(hz)
        assert isinstance(period, int) and period > 0


def test_realised_clock_is_within_a_hair_of_the_measurement():
    """Quantising to an integer period may not move the clock audibly."""
    for hz, _ in REAL_CLOCKS.values():
        realised = Clock(period_for_hz(hz), clock_mod.SOURCE_TRACK).hz
        assert abs(realised - hz) / hz < 1e-3


def test_the_fixed_fallback_divides_the_clock_exactly():
    assert period_for_hz(clock_mod.FALLBACK_HZ) == 10_240
    assert 10_240 * clock_mod.FALLBACK_HZ == TICKS


def test_an_integer_period_cannot_accumulate_drift():
    """The reason the clock is a period and not a float frequency.

    A 205.0 Hz clock held as 4995.12 ticks and rounded per row slides about a
    row over a long track; an integer period lands every row exactly.
    """
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_TRACK)
    grid = c.to_grid(render_ticks=200 * TICKS)
    for row in (0, 1, 1000, grid.n_rows - 1):
        assert grid.row_of(grid.tick_of(row)) == row


# --------------------------------------------------------------------------
# a clock is not a tempo -- the objection the design had to answer
# --------------------------------------------------------------------------

def test_one_clock_carries_songs_of_every_tempo():
    """Final Fantasy 6 holds 205.1 Hz while its tempi span 13x.

    Notes spaced 14, 36 and 183 driver ticks apart -- the real corpus range --
    must all land on distinct rows of the same clock. If a shared clock could
    not represent differing tempi, the whole design would be wrong.
    """
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_TRACK)
    grid = c.to_grid(render_ticks=60 * TICKS)
    for spacing_in_ticks in (14, 36, 183):
        step = spacing_in_ticks * c.period_ticks
        rows = [grid.row_of(i * step) for i in range(8)]
        assert rows == sorted(set(rows)), "a tempo collapsed onto one row"
        gaps = {b - a for a, b in zip(rows, rows[1:])}
        assert gaps == {spacing_in_ticks}, "tempo not preserved as row spacing"


def test_tempo_lives_in_row_spacing_not_in_the_clock():
    """Two tempi on one clock give different spacings, same quantum."""
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_TRACK)
    grid = c.to_grid(render_ticks=60 * TICKS)
    slow = grid.row_of(183 * c.period_ticks) - grid.row_of(0)
    fast = grid.row_of(14 * c.period_ticks) - grid.row_of(0)
    assert slow == 183 and fast == 14
    assert c.hz == pytest.approx(205.0, rel=1e-3)   # unchanged by either


def test_no_onset_moves_by_more_than_half_a_row():
    """Phase is zero by construction, so this is the bound that replaces it."""
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_TRACK)
    grid = c.to_grid(render_ticks=10 * TICKS)
    for tick in range(0, 10 * TICKS, 7919):      # a prime stride, no alignment
        assert abs(tick - grid.tick_of(grid.row_of(tick))) <= c.period_ticks / 2 + 1


# --------------------------------------------------------------------------
# game_clocks and clock_for: the three tiers
# --------------------------------------------------------------------------

def test_a_tick_that_is_not_a_timer_rate_is_refused_even_as_a_fallback():
    """Star Ocean's values sit at chance, so trusting them would be worse
    than admitting the clock is a convention."""
    bad = [hz for hz in (0.5 * i for i in range(60, 1200))
           if nearest_divider(hz) is None][:4]
    c = clock_for(_row("Star Ocean", bad[0]))
    assert c.source == clock_mod.SOURCE_FIXED
    assert not c.is_hardware
    assert "does not resolve" in c.reason


def test_a_track_with_nothing_falls_back_to_the_fixed_clock():
    c = clock_for(_row("Plok!", None))
    assert c.source == clock_mod.SOURCE_FIXED
    assert not c.is_hardware
    assert c.hz == pytest.approx(clock_mod.FALLBACK_HZ)


def test_the_fallback_clock_is_itself_achievable():
    """100 Hz is 8000/80, so even the convention is a rate the hardware
    could have produced -- it is not a number from nowhere."""
    divider = nearest_divider(clock_mod.FALLBACK_HZ)
    assert divider is not None and divider.label == "T0/T1/80"


def test_every_track_gets_some_clock():
    """Coverage is total; what varies is the strength of the evidence."""
    for row in (_row("Unknown", None), _row("", None), _row("X", 62.5)):
        assert clock_for(row).period_ticks > 0


def test_source_is_recorded_on_every_clock_dict():
    """A consumer must be able to tell a measurement from a convention."""
    for row in (_row("A", 62.5), _row("B", 80.0), _row("C", None)):
        d = clock_for(row).to_dict()
        assert d["source"] in clock_mod.SOURCES
        assert d["is_hardware"] == (d["source"] != clock_mod.SOURCE_FIXED)
        assert d["reason"]


def test_fit_is_not_reported_for_a_measured_clock():
    """Reporting a goodness-of-fit here would invite the old mistake."""
    grid = Clock(period_for_hz(205.0), clock_mod.SOURCE_TRACK).to_grid(10 * TICKS)
    assert grid.found
    assert grid.fit == 0.0 and grid.median_abs_residual_ticks == 0.0


def test_census_counts_every_row():
    rows = [{"clock": {"source": s}} for s in
            ("timer_register", "track_tick", "fixed")]
    counts = clock_mod.census(rows)
    assert counts == {"timer_register": 1, "track_tick": 1, "fixed": 1}
    assert sum(counts.values()) == len(rows), "every row must be counted once"


# --------------------------------------------------------------------------
# it has to actually drive the score builder
# --------------------------------------------------------------------------

def _note(voice, start, end, note):
    return {
        "voice": voice, "start": start, "end": end, "midi_note": note,
        "volume_left": 40, "volume_right": 40, "srcn": 0, "noise": False,
        "start_sec": start / TICKS, "end_sec": end / TICKS,
    }


def test_scores_build_on_a_clock_without_modification():
    c = Clock(period_for_hz(100.0), clock_mod.SOURCE_TRACK)
    render = 4 * TICKS
    step = c.period_ticks * 10
    notes = [_note(0, i * step, i * step + step, 60 + i % 12) for i in range(20)]
    built = scores.build(notes, c.to_grid(render), render)
    assert built.n_rows > 0
    assert built.stats()["max_voices_sounding_per_row"] <= scores.N_VOICES


def test_a_slow_and_a_fast_track_on_one_clock_both_score():
    """Two tempi, one quantum, both representable -- end to end."""
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_TRACK)
    render = 20 * TICKS
    out = []
    for spacing in (14, 183):
        step = spacing * c.period_ticks
        n = int(render // step)
        notes = [_note(0, i * step, i * step + step, 60) for i in range(n)]
        built = scores.build(notes, c.to_grid(render), render)
        out.append(built.stats()["n_notes_represented"])
    assert all(x > 0 for x in out)
    assert out[0] > out[1], "the faster tempo must place more notes"
    assert out[0] / out[1] == pytest.approx(183 / 14, rel=0.1)
