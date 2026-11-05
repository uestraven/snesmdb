"""Milestone 4: row-grid inference and the two timbre-free scores."""

from __future__ import annotations

import random

import pytest

from snesmdb import grid as grid_mod
from snesmdb import scores as scores_mod
from snesmdb.grid import TICKS_PER_SECOND, Grid

ROW = 8192  # 125 rows/s, a plausible driver tick


def _note(voice, start, end, midi, **extra):
    note = {
        "voice": voice,
        "start": start,
        "end": end,
        "midi_note": midi,
        "srcn": 0,
        "noise": False,
    }
    note.update(extra)
    return note


# --- grid inference -------------------------------------------------------


def test_an_exactly_periodic_track_recovers_its_period() -> None:
    onsets = [1000 + i * ROW for i in range(64)]
    g = grid_mod.infer(onsets, render_ticks=onsets[-1] + ROW)
    assert g.found
    assert g.period_ticks == ROW
    assert g.fit == 1.0
    assert g.median_abs_residual_ticks == 0.0


def test_jitter_is_tolerated_and_reported_rather_than_hidden() -> None:
    rng = random.Random(7)
    onsets = [1000 + i * ROW + rng.randint(-200, 200) for i in range(64)]
    g = grid_mod.infer(onsets, render_ticks=onsets[-1] + ROW)
    assert g.found
    assert g.fit == 1.0
    # The grid is right but the performance is not exact, and the record says so.
    assert 0 < g.median_abs_residual_fraction < grid_mod.ON_GRID_TOLERANCE


def test_a_staggered_chord_does_not_become_the_grid() -> None:
    """The failure that made the first implementation useless.

    A driver key-ons a chord's voices one after another, a few hundred ticks
    apart. Those intra-chord gaps outnumber the musical ones seven to one on an
    eight-voice chord, so an un-clustered histogram reports the stagger as the
    tempo. Donkey Kong Country's Theme gave 3,201 notes, 3,201 distinct onsets
    and a 631-tick mode: 1,600 rows a second.
    """
    onsets = []
    for i in range(48):
        beat = 1000 + i * ROW
        onsets.extend(beat + v * 600 for v in range(8))  # 8 voices, 600 apart
    g = grid_mod.infer(onsets, render_ticks=onsets[-1] + ROW)
    assert g.found
    assert g.period_ticks == ROW, g.to_dict()
    assert g.cluster_ticks > 0, "clustering should have been necessary here"


def test_clustering_is_applied_as_sparingly_as_the_data_allows() -> None:
    """A clean track must not be collapsed at all."""
    onsets = [1000 + i * ROW for i in range(64)]
    g = grid_mod.infer(onsets, render_ticks=onsets[-1] + ROW)
    assert g.cluster_ticks == 0


def test_the_subdivision_guard_prefers_the_musical_period() -> None:
    """Half the period also fits everything, and must not win.

    Fit alone has a degenerate maximum at zero: halve the period and every
    onset still lands on a line. Without the guard the answer is always the
    finest candidate on offer.
    """
    onsets = [i * ROW for i in range(80)]
    g = grid_mod.infer(onsets, render_ticks=80 * ROW)
    assert g.period_ticks == ROW
    assert g.period_ticks != ROW // 2


def test_random_onsets_are_refused_rather_than_fitted() -> None:
    """The control. A method that reports a grid here reports one anywhere."""
    rng = random.Random(11)
    onsets = sorted(rng.randrange(0, 60 * TICKS_PER_SECOND) for _ in range(300))
    g = grid_mod.infer(onsets, render_ticks=60 * TICKS_PER_SECOND)
    assert not g.found
    assert g.fit < grid_mod.MIN_FIT
    assert "below" in g.reason


def test_too_few_onsets_is_a_refusal_with_a_reason() -> None:
    g = grid_mod.infer([0, ROW, 2 * ROW], render_ticks=3 * ROW)
    assert not g.found
    assert str(grid_mod.MIN_DISTINCT_ONSETS) in g.reason
    assert g.period_ticks == 0


def test_no_onsets_at_all_does_not_raise() -> None:
    g = grid_mod.infer([], render_ticks=TICKS_PER_SECOND)
    assert not g.found
    assert g.n_onsets == 0


def test_phase_is_circular_so_onsets_straddling_a_row_average_correctly() -> None:
    """Residuals live on a ring; an arithmetic mean of 0.01 and 0.99 gives 0.5."""
    onsets = []
    for i in range(40):
        onsets.append(i * ROW + 10)
        onsets.append(i * ROW - 10 + ROW)
    g = grid_mod.infer(sorted(onsets), render_ticks=42 * ROW)
    assert g.found
    assert g.median_abs_residual_ticks < ROW * 0.05


def test_row_and_tick_round_trip() -> None:
    onsets = [500 + i * ROW for i in range(32)]
    g = grid_mod.infer(onsets, render_ticks=onsets[-1])
    assert g.found
    for row in (0, 1, 17, 31):
        assert g.row_of(g.tick_of(row)) == row


def test_bpm_is_labelled_with_the_assumption_it_rests_on() -> None:
    """The hardware has no tempo, only a tick. The field name must say so."""
    g = grid_mod.infer([i * ROW for i in range(40)], render_ticks=40 * ROW)
    d = g.to_dict()
    assert "bpm_assuming_4_rows_per_beat" in d
    assert d["rows_per_second"] == pytest.approx(TICKS_PER_SECOND / ROW, rel=1e-3)
    assert d["bpm_assuming_4_rows_per_beat"] == pytest.approx(
        60.0 / (4.0 * ROW / TICKS_PER_SECOND), rel=1e-3
    )


def test_inference_is_deterministic() -> None:
    rng = random.Random(3)
    onsets = [i * ROW + rng.randint(-100, 100) for i in range(60)]
    first = grid_mod.infer(onsets, render_ticks=60 * ROW).to_dict()
    second = grid_mod.infer(list(onsets), render_ticks=60 * ROW).to_dict()
    assert first == second


def test_clustering_keeps_the_leading_edge_of_a_chord() -> None:
    assert grid_mod.cluster([100, 300, 500, 9000], 600) == [100, 9000]
    assert grid_mod.cluster([100, 300, 500, 9000], 0) == [100, 300, 500, 9000]


# --- the two score formats ------------------------------------------------


def _grid_for(onsets, render):
    g = grid_mod.infer(onsets, render_ticks=render)
    assert g.found
    return g


def test_a_held_note_repeats_down_its_column() -> None:
    notes = [_note(0, 0, 4 * ROW, 60)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=8)
    s = scores_mod.build(notes, g, render_ticks=8 * ROW)
    assert s.separated[0][:4] == [60, 60, 60, 60]
    assert s.separated[0][4] == 0
    assert s.n_notes_represented == 1


def test_blended_can_never_exceed_the_eight_voices_the_hardware_has() -> None:
    """Accumulated independently this reported nine on eight-voice hardware.

    Two key-ons on one voice at the same tick each contributed a number to the
    same row. Deriving the blended score from the separated grid makes more
    than eight arithmetically impossible.
    """
    notes = []
    for voice in range(8):
        notes.append(_note(voice, 0, 2 * ROW, 60 + voice))
        notes.append(_note(voice, 0, 2 * ROW, 80 + voice))  # same voice, same tick
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    s = scores_mod.build(notes, g, render_ticks=4 * ROW)
    assert s.max_polyphony <= scores_mod.N_VOICES
    assert all(len(row) <= scores_mod.N_VOICES for row in s.blended)
    assert s.n_cells_contested > 0, "the collision should be counted, not hidden"


def test_blended_is_the_distinct_pitches_of_the_separated_grid() -> None:
    notes = [_note(0, 0, ROW, 60), _note(1, 0, ROW, 64), _note(2, 0, ROW, 60)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=2)
    s = scores_mod.build(notes, g, render_ticks=2 * ROW)
    assert s.blended[0] == [60, 64]  # the duplicate 60 collapses


def test_an_unpitched_note_is_counted_not_silently_dropped() -> None:
    notes = [_note(0, 0, ROW, None), _note(1, 0, ROW, 60)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=2)
    s = scores_mod.build(notes, g, render_ticks=2 * ROW)
    assert s.n_notes_unpitched == 1
    assert s.n_notes_represented == 1
    assert s.coverage == 0.5


def test_a_pitch_outside_the_format_is_counted_separately() -> None:
    """An octave error showing through. Writing it in would put a wrong number
    in the corpus; dropping it without a count would hide how often that is."""
    notes = [_note(0, 0, ROW, 140.0), _note(1, 0, ROW, -3.0), _note(2, 0, ROW, 60)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=2)
    s = scores_mod.build(notes, g, render_ticks=2 * ROW)
    assert s.n_notes_out_of_range == 2
    assert s.n_notes_unpitched == 0
    assert s.n_notes_represented == 1


def test_a_note_shorter_than_a_row_is_snapped_rather_than_lost() -> None:
    notes = [_note(0, ROW + 100, ROW + 300, 60)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    s = scores_mod.build(notes, g, render_ticks=4 * ROW)
    assert s.n_notes_snapped == 1
    assert s.n_notes_represented == 1
    assert 60 in s.blended[1]


def test_an_unterminated_note_stops_where_its_voice_next_speaks() -> None:
    """Otherwise it overlaps every later note on its own voice."""
    notes = [_note(0, 0, None, 60), _note(0, 2 * ROW, 3 * ROW, 67)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=4)
    s = scores_mod.build(notes, g, render_ticks=4 * ROW)
    assert s.separated[0][0] == 60
    assert s.separated[0][1] == 60
    assert s.separated[0][2] == 67
    assert s.n_cells_contested == 0


def test_no_grid_means_no_score_rather_than_a_guessed_one() -> None:
    g = Grid(found=False, reason="refused")
    s = scores_mod.build([_note(0, 0, ROW, 60)], g, render_ticks=ROW)
    assert s.n_rows == 0
    assert s.separated == []
    assert s.blended == []
    assert s.n_notes == 1
    assert s.n_notes_represented == 0


def test_score_stats_exclude_the_scores_themselves() -> None:
    """`stats()` rides on the manifest; the arrays go to their own file."""
    notes = [_note(0, 0, ROW, 60)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=2)
    s = scores_mod.build(notes, g, render_ticks=2 * ROW)
    stats = s.stats()
    assert "separated" not in stats and "blended" not in stats
    assert stats["n_rows"] == 2
    assert set(scores_mod.Scores().to_dict()) >= set(stats)


def test_voices_outside_the_eight_are_refused() -> None:
    notes = [_note(9, 0, ROW, 60)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=2)
    s = scores_mod.build(notes, g, render_ticks=2 * ROW)
    assert s.n_notes_unplaced == 1
    assert s.n_notes_represented == 0


def test_separated_has_one_track_per_dsp_voice() -> None:
    notes = [_note(0, 0, ROW, 60)]
    g = Grid(found=True, period_ticks=ROW, phase_ticks=0, n_rows=3)
    s = scores_mod.build(notes, g, render_ticks=3 * ROW)
    assert len(s.separated) == scores_mod.N_VOICES == 8
    assert all(len(track) == s.n_rows for track in s.separated)
    assert len(s.blended) == s.n_rows


# --- the driver tick, from the write cadence -------------------------------


def _cadence(period, n, *, burst=6, spacing=120, jitter=0, seed=5):
    """Writes as a driver makes them: a burst of registers every tick."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        base = i * period + (rng.randint(-jitter, jitter) if jitter else 0)
        out.extend(base + v * spacing for v in range(burst))
    return out


def test_a_regular_write_cadence_recovers_the_timer_period() -> None:
    from snesmdb import tick as tick_mod

    t = tick_mod.infer(_cadence(4993, 200))
    assert t.found
    assert t.period_ticks == 4993
    assert t.hz == pytest.approx(TICKS_PER_SECOND / 4993, rel=1e-6)
    assert t.concentration > 0.9


def test_timer_jitter_of_a_few_ticks_is_one_period_not_three() -> None:
    """Final Fantasy VI's gap appears as 4,993, 4,988 and 4,987."""
    from snesmdb import tick as tick_mod

    t = tick_mod.infer(_cadence(4993, 200, jitter=6))
    assert t.found
    assert abs(t.period_ticks - 4993) <= 60
    assert t.n_agreeing > 0.8 * t.n_gaps


def test_a_driver_writing_twice_a_tick_is_not_read_as_double_speed() -> None:
    """Ties on agreement go to the larger period."""
    from snesmdb import tick as tick_mod

    period = 8000
    writes = []
    for i in range(200):
        writes.extend([i * period, i * period + 60, i * period + 120])
        writes.extend([i * period + period // 2, i * period + period // 2 + 60])
    t = tick_mod.infer(writes)
    assert t.found
    # Either the full period or the half, but reported with its sharpness so a
    # consumer can tell. What must NOT happen is a silent factor-of-two error
    # with high confidence in a sub-multiple.
    assert t.period_ticks in (period, period // 2)
    if t.period_ticks == period // 2:
        assert t.concentration >= 0.9  # genuinely regular at the half period


def test_irregular_writes_are_refused_with_a_reason() -> None:
    """A driver that writes only when it has something to say has no cadence.

    Donkey Kong Country is the real case: its tick of 80.0 Hz is CORRECT, and
    it still scores only 0.30 sharpness, because Rare writes on demand. So
    sharpness measures regularity, not correctness, and the refusal threshold
    is a statement about confidence rather than about the number being wrong.
    """
    from snesmdb import tick as tick_mod

    rng = random.Random(9)
    writes = sorted(rng.randrange(0, 30 * TICKS_PER_SECOND) for _ in range(4000))
    t = tick_mod.infer(writes)
    assert not t.found
    assert t.concentration < tick_mod.MIN_CONCENTRATION
    assert "cadence" in t.reason


def test_too_few_writes_is_a_refusal() -> None:
    from snesmdb import tick as tick_mod

    t = tick_mod.infer([0, 100, 200])
    assert not t.found
    assert "too few" in t.reason
    assert t.period_ticks == 0


def test_a_widely_spaced_burst_makes_the_tick_unidentifiable() -> None:
    """A real limitation, stated rather than papered over.

    When a driver spreads its writes EVENLY across its tick -- three writes
    1,500 ticks apart inside a 6,000-tick timer -- the write times are
    indistinguishable from a 1,500-tick timer: both put every write at the same
    phase. No statistic over write times alone can separate them, so the
    module reports the sub-multiple, and a consumer reading 4x the true rate
    for such a driver is reading the data correctly.

    The tick is identifiable only when writes CLUSTER within it, which is what
    a driver servicing a timer actually does.
    """
    from snesmdb import tick as tick_mod

    t = tick_mod.infer(_cadence(6000, 200, burst=3, spacing=1500))
    assert t.found
    assert t.period_ticks == 1500  # the sub-multiple, honestly
    assert t.concentration > 0.95

    # Cluster the same three writes into the first fifth of the tick and the
    # tick becomes identifiable again.
    clustered = tick_mod.infer(_cadence(6000, 200, burst=3, spacing=200))
    assert clustered.found
    assert abs(clustered.period_ticks - 6000) <= 60


def test_bursts_keep_their_leading_edge() -> None:
    from snesmdb import tick as tick_mod

    assert tick_mod.bursts([10, 20, 30, 5000], 100) == [10, 5000]


def test_the_tick_report_carries_its_own_evidence() -> None:
    from snesmdb import tick as tick_mod

    t = tick_mod.infer(_cadence(4993, 200))
    d = t.to_dict()
    assert d["n_agreeing"] <= d["n_gaps"]
    assert d["sharpness"] == pytest.approx(d["n_agreeing"] / d["n_gaps"], rel=1e-6)
    assert 0.0 <= d["concentration"] <= 1.0
    assert d["n_writes"] == 200 * 6
    assert d["burst_window"] in tick_mod.BURST_WINDOWS


# --- using the tick to correct the row grid --------------------------------


def test_snapping_makes_the_row_a_whole_number_of_ticks() -> None:
    g = Grid(found=True, period_ticks=4100, phase_ticks=0, n_rows=10, fit=0.9)
    snapped = grid_mod.snap_to_tick(g, 1000)
    assert snapped.snapped_to_tick
    assert snapped.tick_multiple == 4
    assert snapped.period_ticks == 4000


def test_snapping_is_a_no_op_without_a_tick() -> None:
    g = Grid(found=True, period_ticks=4100, phase_ticks=0, n_rows=10, fit=0.9)
    assert grid_mod.snap_to_tick(g, 0).period_ticks == 4100
    assert not grid_mod.snap_to_tick(g, 0).snapped_to_tick


def test_a_refused_grid_is_not_snapped() -> None:
    g = Grid(found=False, period_ticks=0)
    assert grid_mod.snap_to_tick(g, 1000).period_ticks == 0


def test_refit_remeasures_the_grid_it_actually_emits() -> None:
    """After snapping, the reported fit must describe the snapped period."""
    onsets = [i * 4000 for i in range(40)]
    g = Grid(found=True, period_ticks=4100, phase_ticks=0, n_rows=40, fit=0.0)
    g = grid_mod.refit(grid_mod.snap_to_tick(g, 1000), onsets, 40 * 4000)
    assert g.period_ticks == 4000
    assert g.fit == 1.0
    assert g.median_abs_residual_ticks == 0.0


def test_a_split_burst_cannot_pass_as_the_tick() -> None:
    """The bug this scorer replaced.

    A burst window narrower than the spacing WITHIN a burst makes every write
    its own burst, so the only surviving gap is from the last write of one
    burst to the first of the next -- the period minus the burst span. It is
    perfectly regular, so the old burst-gap statistic scored it 1.0 and read a
    4,993-tick timer as 4,393.
    """
    from snesmdb import tick as tick_mod

    writes = []
    for i in range(200):
        writes.extend(i * 4993 + v * 120 for v in range(6))
    t = tick_mod.infer(writes)
    assert t.found
    assert t.period_ticks == 4993
    # And the wrong answer must be measurably worse on the statistic that now
    # decides, even though it was indistinguishable on the old one.
    assert tick_mod.concentration(writes, 4993) > tick_mod.concentration(writes, 4393)


def test_concentration_separates_a_timer_from_noise() -> None:
    from snesmdb import tick as tick_mod

    period = 5000
    on_timer = [i * period + (i % 3) * 50 for i in range(500)]
    rng = random.Random(4)
    scattered = sorted(rng.randrange(0, 500 * period) for _ in range(500))
    assert tick_mod.concentration(on_timer, period) > 0.95
    assert tick_mod.concentration(scattered, period) < 0.2
