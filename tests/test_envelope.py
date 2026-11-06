"""The S-DSP envelope decoder.

The values asserted here are read off the vendored SPC_DSP.cpp rather than
recalled, because the two mistakes this module exists to avoid both came from
plausible-sounding recollection: that the sustain plateau is (SL+1)*256, and
that the output multiply uses the 7-bit ENVX readback rather than the full
11-bit internal envelope.
"""

from __future__ import annotations

import pytest

from snesmdb import envelope as env_mod
from snesmdb.envelope import ENV_MAX, decode, sustain_env_for


# --------------------------------------------------------------------------
# sustain level
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "sustain_level,expected",
    [(0, 0), (1, 256), (2, 512), (3, 768), (4, 1024), (5, 1280), (6, 1536), (7, 2047)],
)
def test_sustain_plateau_is_sl_times_256(sustain_level, expected):
    """Not (SL+1)*256.

    The hardware leaves decay when `(env >> 8) == (adsr2 >> 5)`, so the
    plateau is the BOTTOM of a 256-wide band at SL*256. The commonly quoted
    (SL+1)/8 is that band's top edge.
    """
    assert sustain_env_for(sustain_level) == expected


def test_sustain_level_seven_holds_full_scale():
    """The 86.4% case, and the reason VOL-only velocity is mostly fine.

    After the attack env is 0x7FF, and 0x7FF >> 8 is already 7, so the decay
    comparison matches on the first tick and the note never decays.
    """
    assert sustain_env_for(7) == ENV_MAX
    assert decode(0x80, 0xE0, 0).holds_full


def test_sustain_level_zero_decays_to_silence():
    assert sustain_env_for(0) == 0
    env = decode(0x80, 0x00, 0)
    assert env.sustain_env == 0 and not env.holds_full
    assert env.sustain_fraction == 0.0


def test_sustain_level_is_the_top_three_bits_of_adsr2():
    for level in range(8):
        assert decode(0x80, level << 5, 0).sustain_level == level


# --------------------------------------------------------------------------
# ADSR mode
# --------------------------------------------------------------------------

def test_adsr_is_selected_by_bit_seven_of_adsr1():
    assert decode(0x80, 0, 0).mode == env_mod.MODE_ADSR
    assert decode(0x7F, 0, 0).mode != env_mod.MODE_ADSR


def test_attack_always_reaches_full_scale():
    """Which is why `velocity` from VOL alone is correct as ATTACK intensity.

    The attack phase runs env up to 0x7FF whatever the rate, so the peak is
    not a function of the registers and carries no dynamics.
    """
    for attack in range(16):
        assert decode(0x80 | attack, 0xE0, 0).peak_env == ENV_MAX


def test_adsr_rate_fields_decode_to_their_registers():
    env = decode(0x80 | (0x05 << 4) | 0x0A, (0x03 << 5) | 0x11, 0)
    assert env.attack_rate == 0x0A
    assert env.decay_rate == 0x05
    assert env.sustain_level == 0x03
    assert env.sustain_rate == 0x11


def test_gain_fields_are_absent_in_adsr_mode():
    env = decode(0x80, 0xE0, 0xB8)
    assert env.gain_mode is None


# --------------------------------------------------------------------------
# GAIN mode
# --------------------------------------------------------------------------

def test_direct_gain_is_a_static_level():
    """The hardware assigns env = (gain & 0x7F) * 0x10 every tick."""
    for raw in (0, 1, 48, 64, 127):
        env = decode(0x00, 0, raw)
        assert env.mode == env_mod.MODE_GAIN_DIRECT
        assert env.peak_env == raw * 0x10 == env.sustain_env


def test_direct_gain_covers_modes_zero_to_three():
    for mode in range(4):
        env = decode(0x00, 0, (mode << 5) | 0x10)
        assert env.mode == env_mod.MODE_GAIN_DIRECT
        assert env.gain_mode == mode


def test_a_zero_direct_gain_really_is_silent():
    """Only 0.05% of notes after the snapshot-seeding fix, down from 5.74%.

    Before voice state was seeded from the SPC's DSP block, any driver that
    never rewrote GAIN produced this reading spuriously -- 540 whole tracks
    of it.
    """
    env = decode(0x00, 0, 0x00)
    assert env.peak_env == 0 and env.sustain_env == 0


@pytest.mark.parametrize("mode,name,peak", [
    (4, env_mod.MODE_GAIN_LINEAR_DECREASE, None),
    (5, env_mod.MODE_GAIN_EXP_DECREASE, None),
    (6, env_mod.MODE_GAIN_LINEAR_INCREASE, ENV_MAX),
    (7, env_mod.MODE_GAIN_BENT_INCREASE, ENV_MAX),
])
def test_ramping_gain_modes_are_named_and_not_guessed(mode, name, peak):
    """A ramp moves env from wherever it was, so a key-on cannot name a level.

    None must mean "not decidable", never zero -- reading it as zero would
    silence exactly the notes whose drivers are most expressive.
    """
    env = decode(0x00, 0, (mode << 5) | 0x18)
    assert env.mode == name
    assert env.peak_env == peak
    assert env.sustain_env is None
    assert env.sustain_fraction is None
    assert not env.holds_full


def test_undecidable_is_not_reported_as_full_either():
    env = decode(0x00, 0, (4 << 5) | 0x18)
    assert env.to_dict()["env_sustain"] is None
    assert env.to_dict()["env_sustain_fraction"] is None


# --------------------------------------------------------------------------
# note records and census
# --------------------------------------------------------------------------

def _note(adsr1=0, adsr2=0, gain=0):
    return {"adsr1": adsr1, "adsr2": adsr2, "gain": gain}


def test_of_note_tolerates_missing_fields():
    assert env_mod.of_note({}).mode in env_mod.MODES


def test_census_excludes_undecidable_from_its_denominator():
    """The honest denominator for any loudness correction."""
    notes = [
        _note(adsr1=0x80, adsr2=0xE0),              # ADSR, SL=7, holds full
        _note(adsr1=0x80, adsr2=0x00),              # ADSR, SL=0
        _note(adsr1=0x00, gain=0x40),               # direct GAIN, decidable
        _note(adsr1=0x00, gain=(4 << 5) | 0x18),    # ramp, undecidable
    ]
    out = env_mod.census(notes)
    assert out["n_notes"] == 4
    assert out["n_decidable"] == 3, "the ramp must not be counted"
    assert out["n_holds_full"] == 1
    assert out["modes"][env_mod.MODE_ADSR] == 2
    assert out["modes"][env_mod.MODE_GAIN_LINEAR_DECREASE] == 1


def test_census_totals_are_preserved():
    notes = [_note(adsr1=0x80, adsr2=(i % 8) << 5) for i in range(40)]
    out = env_mod.census(notes)
    assert sum(out["modes"].values()) == out["n_notes"] == 40


def test_census_of_nothing():
    out = env_mod.census([])
    assert out["n_notes"] == 0 and out["mean_sustain_fraction"] is None


def test_the_corpus_majority_needs_no_correction():
    """86.4% of ADSR notes hold at full scale; this encodes why that matters.

    For those notes env is a constant 0x7FF, so `amp = ((sample * env) >> 11)
    * VOL >> 7` reduces to VOL, and the existing velocity is exactly right.
    """
    env = decode(0x80, 0xE0, 0)
    assert env.sustain_fraction == pytest.approx(1.0)
    assert env.peak_fraction == pytest.approx(1.0)
