"""The SPC700 timer configuration, read from the SPC file rather than inferred.

The values asserted here come from the corpus and were measured independently
by `tick.py` before this module existed, so their agreeing is a result and not
a construction.
"""

from __future__ import annotations

import pytest

from snesmdb import clock as clock_mod, timers as timers_mod


def _aram(control: int, t0: int = 0xFF, t1: int = 0xFF, t2: int = 0xFF) -> bytes:
    data = bytearray(0x10000)
    data[timers_mod.REG_CONTROL] = control
    data[timers_mod.REG_T0_TARGET] = t0
    data[timers_mod.REG_T1_TARGET] = t1
    data[timers_mod.REG_T2_TARGET] = t2
    return bytes(data)


#: (game, control, T0 target, expected Hz) -- the rate `tick.py` had already
#: measured from write cadence for each of these games.
MEASURED = [
    ("Chrono Trigger", 0x03, 42, 190.476),
    ("Super Metroid", 0x31, 16, 500.0),
    ("Final Fantasy 6", 0x01, 39, 205.128),
    ("Secret of Mana", 0x01, 36, 222.222),
    ("Donkey Kong Country", 0x01, 100, 80.0),
    ("Earthbound", 0x01, 16, 500.0),
    ("Super Castlevania 4", 0x01, 32, 250.0),
    ("Dragon Quest 5", 0x01, 40, 200.0),
]


@pytest.mark.parametrize("game,control,target,expected", MEASURED)
def test_the_register_reproduces_the_independently_measured_clock(
    game, control, target, expected
):
    read = timers_mod.read(_aram(control, t0=target))
    assert read.name == "T0"
    assert read.hz == pytest.approx(expected, rel=1e-3), game


def test_a_zero_target_counts_as_256():
    """An 8-bit register, so 0 is the slowest setting rather than a divide
    by zero."""
    assert timers_mod.rate_for(8000.0, 0) == pytest.approx(8000.0 / 256)
    read = timers_mod.read(_aram(0x01, t0=0))
    assert read.hz == pytest.approx(31.25)


def test_the_lowest_enabled_timer_is_taken_as_the_sequencer():
    """Chrono Trigger enables T0 at 190.48 Hz and T1 at 62.5 Hz, and 190.48
    is the rate write cadence measures, so the lower-numbered timer wins."""
    read = timers_mod.read(_aram(0x03, t0=42, t1=128))
    assert [n for n, _ in read.enabled] == ["T0", "T1"]
    assert read.name == "T0"
    assert read.hz == pytest.approx(190.476, rel=1e-3)


def test_timer_two_uses_the_64_khz_base():
    read = timers_mod.read(_aram(0x04, t2=200))
    assert read.name == "T2"
    assert read.hz == pytest.approx(64000.0 / 200)


def test_a_disabled_timer_is_not_offered():
    read = timers_mod.read(_aram(0x02, t0=42, t1=128))
    assert read.name == "T1", "T0 is disabled despite holding a target"
    assert read.hz == pytest.approx(62.5)


def test_no_enabled_timer_yields_nothing_rather_than_zero_division():
    read = timers_mod.read(_aram(0x00))
    assert read.enabled == [] and read.sequencer is None
    assert read.hz == 0.0
    assert read.to_dict()["sequencer_hz"] is None


def test_a_truncated_aram_does_not_raise():
    assert timers_mod.read(b"\x00" * 8).enabled == []


def test_only_the_low_three_control_bits_mean_anything():
    """The upper bits are port-clear and IPL-ROM controls. 0x31 and 0x01 both
    mean "T0 only", and Super Metroid really does dump 0x31."""
    assert timers_mod.read(_aram(0x31, t0=16)).name == "T0"
    assert len(timers_mod.read(_aram(0x31, t0=16)).enabled) == 1
    assert timers_mod.read(_aram(0xF0)).enabled == []


# --------------------------------------------------------------------------
# the clock prefers it over every inference
# --------------------------------------------------------------------------

def _row(game, timer_hz=None, tick_hz=None):
    row = {"ok": True, "tag": {"game": game, "title": "t"}}
    if timer_hz:
        row["timers"] = {
            "sequencer_timer": "T0", "sequencer_hz": timer_hz,
            "targets": {"T0": 16}, "enabled": [{"timer": "T0", "hz": timer_hz}],
        }
    if tick_hz:
        row["tick"] = {"found": True, "hz": tick_hz}
    return row


def test_the_register_outranks_a_measured_tick():
    """A stored configuration beats an inference from write cadence."""
    got = clock_mod.clock_for(_row("G", timer_hz=500.0, tick_hz=62.5))
    assert got.source == clock_mod.SOURCE_TIMER
    assert got.is_register_read and got.is_hardware
    assert got.hz == pytest.approx(500.0, rel=1e-3)


def test_the_register_replaces_the_fabricated_fallback():
    """The 220 fixed-clock tracks: 178 music, now all on a real timer."""
    got = clock_mod.clock_for(_row("Super Mario World", timer_hz=500.0))
    assert got.source == clock_mod.SOURCE_TIMER
    assert got.hz == pytest.approx(500.0, rel=1e-3)
    assert "not an\ninference" in got.reason or "not an inference" in got.reason


def test_without_a_register_the_old_chain_still_applies():
    got = clock_mod.clock_for(_row("G", tick_hz=62.5))
    assert got.source == clock_mod.SOURCE_TRACK
    assert not got.is_register_read


def test_per_track_registers_need_no_per_game_consensus():
    """Star Ocean dumps 26 distinct timer values across its tracks, and each
    track now gets its own instead of a per-game average or a fallback."""
    rates = [48.78, 64.0, 89.89, 125.0, 250.0]
    got = [
        clock_mod.clock_for(_row("Star Ocean", timer_hz=hz)) for hz in rates
    ]
    assert all(c.source == clock_mod.SOURCE_TIMER for c in got)
    assert len({c.period_ticks for c in got}) == len(rates)


def test_a_register_clock_still_reports_its_divider():
    got = clock_mod.clock_for(_row("G", timer_hz=500.0))
    assert got.divider is not None
    assert got.divider.label == "T0/T1/16"


# --------------------------------------------------------------------------
# The software divisor M, recovered from the two clocks disagreeing
# --------------------------------------------------------------------------

def _publish_module():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "publish", Path(__file__).resolve().parent.parent / "tools" / "publish.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_m_is_the_ratio_of_the_timer_to_the_sequencer():
    """Mega Man X: register 125 Hz, write cadence 62.5 Hz, so M = 2.

    The register gives the hardware timer and the cadence gives the sequencer,
    so their ratio is how many ticks the driver counts per musical row.
    """
    pub = _publish_module()
    row = {"tick": {"found": True, "hz": 62.5}}
    assert pub._software_divisor(row, 125.0) == 2


def test_m_is_one_when_the_two_clocks_agree():
    pub = _publish_module()
    row = {"tick": {"found": True, "hz": 190.476}}
    assert pub._software_divisor(row, 190.476) == 1


def test_m_is_none_rather_than_one_when_unknown():
    """Assuming 1 would claim the row IS the musical row for two thirds of
    the corpus. None is the honest answer."""
    pub = _publish_module()
    assert pub._software_divisor({}, 500.0) is None
    assert pub._software_divisor({"tick": {"found": False, "hz": 62.5}}, 500.0) is None
    assert pub._software_divisor({"tick": {"found": True, "hz": 62.5}}, 0.0) is None


def test_a_non_integer_ratio_is_refused():
    """The 11% where the tick is not a clean multiple -- including the 20
    tracks carrying the 2,048-tick artifact -- must not yield a divisor."""
    pub = _publish_module()
    row = {"tick": {"found": True, "hz": 18.574}}
    assert pub._software_divisor(row, 500.0) is None     # ratio 26.9
    row = {"tick": {"found": True, "hz": 1196.26}}
    assert pub._software_divisor(row, 80.0) is None      # tick faster than clock
