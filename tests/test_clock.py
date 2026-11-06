"""The per-game row clock that replaced the per-track inferred grid.

The property these tests exist to defend is that a clock is NOT a tempo. The
objection that sank the first design is that a game's songs do not share a
tempo -- true, and irrelevant, because the clock is the quantum the sequence is
measured in and the tempo is how many quanta a note lasts. Several tests below
assert exactly that separation, because a future change that conflated them
would look harmless and would quietly destroy the corpus.
"""

from __future__ import annotations

import pytest

from snesmdb import clock as clock_mod, scores
from snesmdb.clock import (
    Clock,
    clock_for,
    consensus,
    game_clocks,
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
    assert divider.base_hz in [base for base, _ in clock_mod.TIMER_BASES]


def test_the_divider_test_can_fail():
    """It would be worthless if everything passed.

    41.7 Hz is deliberately NOT in this list: it is 8000/192 to within 0.08%,
    so it passes. That was a fixture I wrote from assumption and had to
    correct against the real divider set -- the test is only meaningful with
    values checked rather than guessed.
    """
    for hz in (137.3, 93.3, 171.1, 29.3, 121.6, 233.6, 472.1):
        assert nearest_divider(hz) is None, f"{hz} Hz was expected to fail"
    assert nearest_divider(41.7) is not None


def test_the_divider_test_is_not_vacuous_across_the_corpus_range():
    """Measured ticks pass far more often than arbitrary frequencies.

    Across 62-500 Hz a random frequency sits within tolerance of some divider
    about 28.5% of the time, so a sweep must leave a clear majority failing.
    If a refactor widened the tolerance this test is what catches it.
    """
    step = (500.0 - 62.0) / 400
    passing = sum(1 for i in range(400) if nearest_divider(62.0 + i * step))
    assert passing / 400 < 0.45, "tolerance has grown until the test proves nothing"
    assert all(nearest_divider(hz) for hz, _ in REAL_CLOCKS.values())


def test_a_divider_beyond_an_eight_bit_register_is_not_achievable():
    """8000/300 would need a divider the hardware cannot hold."""
    assert clock_mod.DIVIDER_MAX == 256
    assert nearest_divider(8000.0 / 300) is None


def test_timer_two_covers_the_fast_rates():
    divider = nearest_divider(64000.0 / 3)
    assert divider is not None and divider.base_name == "T2"


# --------------------------------------------------------------------------
# consensus
# --------------------------------------------------------------------------

def test_one_timer_read_many_times_counts_as_one_rate():
    """Secret of Mana reports 222.1, 222.2 and 222.3 on the same driver."""
    divider, n, agreement = consensus([222.1, 222.2, 222.3, 222.2, 222.1, 222.3])
    assert divider is not None and divider.label == "T0/T1/36"
    assert n == 6 and agreement == 1.0


def test_a_scattered_driver_gets_no_clock():
    """Star Ocean's ticks form a continuum from 12 to 50 Hz."""
    divider, n, agreement = consensus(
        [12.5, 14.7, 15.7, 16.3, 17.9, 20.2, 20.8, 23.5, 49.0]
    )
    assert divider is None


def test_ticks_that_are_not_timer_rates_are_dropped_not_rounded():
    """The distinction that separates a varying timer from a broken extractor.

    Super Turrican puts 25% of its ticks on a divider, against 28.5% expected
    by chance -- if it merely varied its timer the values would still be
    base/N. Rounding them into the nearest bin would manufacture a consensus
    out of noise.
    """
    noise = [137.3, 93.3, 171.1, 29.3, 121.6]
    assert all(nearest_divider(h) is None for h in noise)
    divider, n, _ = consensus(noise)
    assert divider is None and n == 0


def test_two_agreeing_tracks_are_not_a_hardware_constant():
    divider, n, _ = consensus([500.0, 500.0])
    assert divider is None and n == 2


def test_three_agreeing_tracks_are():
    divider, n, agreement = consensus([500.0, 500.0, 500.0])
    assert divider is not None and divider.hz == pytest.approx(500.0)
    assert n == 3 and agreement == 1.0


def test_consensus_ignores_absent_and_nonsense_values():
    divider, n, _ = consensus([62.5, 62.5, 62.5, 0, -1, None])
    assert divider is not None and divider.hz == pytest.approx(62.5)
    assert n == 3


def test_no_ticks_at_all():
    assert consensus([]) == (None, 0, 0.0)


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
        realised = Clock(period_for_hz(hz), clock_mod.SOURCE_GAME).hz
        assert abs(realised - hz) / hz < 1e-3


def test_the_fixed_fallback_divides_the_clock_exactly():
    assert period_for_hz(clock_mod.FALLBACK_HZ) == 10_240
    assert 10_240 * clock_mod.FALLBACK_HZ == TICKS


def test_an_integer_period_cannot_accumulate_drift():
    """The reason the clock is a period and not a float frequency.

    A 205.0 Hz clock held as 4995.12 ticks and rounded per row slides about a
    row over a long track; an integer period lands every row exactly.
    """
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_GAME)
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
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_GAME)
    grid = c.to_grid(render_ticks=60 * TICKS)
    for spacing_in_ticks in (14, 36, 183):
        step = spacing_in_ticks * c.period_ticks
        rows = [grid.row_of(i * step) for i in range(8)]
        assert rows == sorted(set(rows)), "a tempo collapsed onto one row"
        gaps = {b - a for a, b in zip(rows, rows[1:])}
        assert gaps == {spacing_in_ticks}, "tempo not preserved as row spacing"


def test_tempo_lives_in_row_spacing_not_in_the_clock():
    """Two tempi on one clock give different spacings, same quantum."""
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_GAME)
    grid = c.to_grid(render_ticks=60 * TICKS)
    slow = grid.row_of(183 * c.period_ticks) - grid.row_of(0)
    fast = grid.row_of(14 * c.period_ticks) - grid.row_of(0)
    assert slow == 183 and fast == 14
    assert c.hz == pytest.approx(205.0, rel=1e-3)   # unchanged by either


def test_no_onset_moves_by_more_than_half_a_row():
    """Phase is zero by construction, so this is the bound that replaces it."""
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_GAME)
    grid = c.to_grid(render_ticks=10 * TICKS)
    for tick in range(0, 10 * TICKS, 7919):      # a prime stride, no alignment
        assert abs(tick - grid.tick_of(grid.row_of(tick))) <= c.period_ticks / 2 + 1


# --------------------------------------------------------------------------
# game_clocks and clock_for: the three tiers
# --------------------------------------------------------------------------

def test_a_consistent_game_gets_a_hardware_clock():
    rows = [_row("Final Fantasy 6", 205.1) for _ in range(59)]
    clocks = game_clocks(rows)
    c = clocks["Final Fantasy 6"]
    assert c.source == clock_mod.SOURCE_GAME and c.is_hardware
    assert c.hz == pytest.approx(205.0, rel=1e-3)
    assert c.n_confident == 59 and c.agreement == 1.0


def test_the_game_clock_applies_to_tracks_with_no_tick_of_their_own():
    """The coverage win: 39% of tracks have a tick, but a game constant
    indexes every track of a game that has one."""
    rows = [_row("Mega Man X", 62.5) for _ in range(34)] + [
        _row("Mega Man X", None) for _ in range(20)
    ]
    clocks = game_clocks(rows)
    silent = _row("Mega Man X", None)
    c = clock_for(silent, clocks)
    assert c.source == clock_mod.SOURCE_GAME
    assert c.hz == pytest.approx(62.5, rel=1e-3)


def test_a_game_constant_outranks_a_tracks_own_tick():
    """The shared quantum is the point; one track's read is the noisier one."""
    rows = [_row("Chrono Trigger", 190.5) for _ in range(58)]
    clocks = game_clocks(rows)
    odd = _row("Chrono Trigger", 381.0)      # the real outlier in that game
    assert clock_for(odd, clocks).hz == pytest.approx(190.5, rel=1e-3)


def test_a_varying_timer_falls_back_to_the_tracks_own_verified_tick():
    """Lufia 2: 84% of ticks on a divider, but only 42% on any single one.

    A driver changing divider per track is real, so the track's own rate is
    both a measurement and the right answer -- provided it passes the
    hardware test.
    """
    rows = [_row("Lufia 2", hz) for hz in
            (64.0, 64.0, 72.07, 88.89, 92.0, 102.56, 103.9, 64.0, 80.0, 100.0)]
    clocks = game_clocks(rows)
    assert not clocks["Lufia 2"].period_ticks
    c = clock_for(_row("Lufia 2", 88.89), clocks)
    assert c.source == clock_mod.SOURCE_TRACK and c.is_hardware
    assert c.divider is not None
    assert c.hz == pytest.approx(88.89, rel=1e-3)


def test_a_tick_that_is_not_a_timer_rate_is_refused_even_as_a_fallback():
    """Star Ocean's values sit at chance, so trusting them would be worse
    than admitting the clock is a convention."""
    clocks = game_clocks([_row("Star Ocean", h) for h in (137.3, 41.7, 93.3, 171.1)])
    c = clock_for(_row("Star Ocean", 137.3), clocks)
    assert c.source == clock_mod.SOURCE_FIXED
    assert not c.is_hardware
    assert "does not resolve" in c.reason


def test_a_track_with_nothing_falls_back_to_the_fixed_clock():
    clocks = game_clocks([_row("Plok!", 80.0), _row("Plok!", 44.0)])
    c = clock_for(_row("Plok!", None), clocks)
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
    clocks = game_clocks([])
    for row in (_row("Unknown", None), _row("", None), _row("X", 62.5)):
        assert clock_for(row, clocks).period_ticks > 0


def test_a_no_consensus_game_explains_which_bar_it_missed():
    few = game_clocks([_row("Axelay", 250.0), _row("Axelay", 250.0)])["Axelay"]
    assert str(clock_mod.MIN_CONFIDENT_TRACKS) in few.reason
    assert "divider" in few.reason

    # The extractor looks unreliable: the values are not timer rates at all.
    # Synthetic -- no game in the real corpus reaches this branch, which is
    # the point of keeping it.
    broken = game_clocks(
        [_row("Hypothetical", h) for h in (137.3, 93.3, 171.1, 29.3, 121.6, 233.6)]
    )["Hypothetical"]
    assert "looks unreliable" in broken.reason

    # The driver is varying a real timer: the values ARE rates, but differ.
    # This is the real case, and it covers five games.
    varying = game_clocks(
        [_row("Lufia 2", h) for h in (64.0, 72.07, 88.89, 92.0, 102.56, 200.0)]
    )["Lufia 2"]
    assert "real timer reads" in varying.reason
    assert "reprogramming its divider" in varying.reason


def test_a_divider_varying_driver_is_not_called_a_broken_one():
    """The correction this file exists to lock in.

    Super Turrican, Lufia 2 and Star Ocean were briefly diagnosed as extractor
    failures because the divider share had been computed on ticks rounded to
    0.5 Hz first -- which pushes a genuine rate off its divider (222.22 ->
    222.0 is 0.1% at a 0.11% tolerance). On raw values they score 100%, 100%
    and 78%. A reasonable-looking quantisation destroyed the measurement.
    """
    super_turrican = [91.9, 98.8, 101.3, 108.1, 114.3, 121.2, 129.0, 137.9]
    assert all(nearest_divider(h) for h in super_turrican), "these are real rates"
    rounded = [round(h * 2) / 2 for h in super_turrican]
    assert not all(nearest_divider(h) for h in rounded), (
        "rounding must be shown to break the test, or this guard is vacuous"
    )
    clock = game_clocks([_row("Super Turrican", h) for h in super_turrican])
    assert "real timer reads" in clock["Super Turrican"].reason


def test_failed_tracks_do_not_contribute_a_tick():
    rows = [_row("G", 500.0, ok=False) for _ in range(9)] + [_row("G", 62.5) for _ in range(3)]
    assert game_clocks(rows)["G"].hz == pytest.approx(62.5, rel=1e-3)


def test_source_is_recorded_on_every_clock_dict():
    """A consumer must be able to tell a measurement from a convention."""
    clocks = game_clocks([_row("A", 62.5) for _ in range(3)])
    for row in (_row("A", 62.5), _row("B", 80.0), _row("C", None)):
        d = clock_for(row, clocks).to_dict()
        assert d["source"] in clock_mod.SOURCES
        assert d["is_hardware"] == (d["source"] != clock_mod.SOURCE_FIXED)
        assert d["reason"]


def test_fit_is_not_reported_for_a_measured_clock():
    """Reporting a goodness-of-fit here would invite the old mistake."""
    grid = Clock(period_for_hz(205.0), clock_mod.SOURCE_GAME).to_grid(10 * TICKS)
    assert grid.found
    assert grid.fit == 0.0 and grid.median_abs_residual_ticks == 0.0


def test_census_counts_every_row():
    rows = [{"clock": {"source": s}} for s in
            ("game_tick", "game_tick", "track_tick", "fixed")]
    counts = clock_mod.census(rows)
    assert counts == {"game_tick": 2, "track_tick": 1, "fixed": 0 + 1}
    assert sum(counts.values()) == len(rows)


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
    c = Clock(period_for_hz(100.0), clock_mod.SOURCE_GAME)
    render = 4 * TICKS
    step = c.period_ticks * 10
    notes = [_note(0, i * step, i * step + step, 60 + i % 12) for i in range(20)]
    built = scores.build(notes, c.to_grid(render), render)
    assert built.n_rows > 0
    assert built.stats()["max_polyphony"] <= scores.N_VOICES


def test_a_slow_and_a_fast_track_on_one_clock_both_score():
    """Two tempi, one quantum, both representable -- end to end."""
    c = Clock(period_for_hz(205.0), clock_mod.SOURCE_GAME)
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
