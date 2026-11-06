"""Decoding the S-DSP envelope from ADSR1, ADSR2 and GAIN.

WHY THIS EXISTS. The DSP's output for one voice is

    out  = (sample * env) >> 11          # env is the 11-bit internal envelope
    amp  = (out * VOL) >> 7              # VOL is signed 8-bit, per side

so loudness is **env x VOL**, and this corpus's `velocity` uses VOL alone. The
envelope is the missing factor. (Register offsets and shifts here are read off
the vendored SPC_DSP.cpp, not from memory: `run_envelope` at line 206 and
`voice_output` at 456/488.)

WHAT IS AND IS NOT RECOVERABLE. Velocity in the MIDI sense is attack intensity,
and in ADSR mode the attack always drives env to full scale, so peak loudness
really is VOL and the existing velocity is right for it. What VOL alone cannot
express is the SUSTAIN plateau -- where the note settles and holds -- which is
an articulation property. Measured over 539,836 notes:

    95.5% of notes are in ADSR mode
      of those, 86.4% have sustain level 7, which is no decay at all
      the other 13.6% (13.0% of all notes) settle below full scale,
      down to silence at SL=0
     4.5% are in GAIN direct mode, where the level is a plain number

So a staccato pluck and a held horn with equal VOL are currently
indistinguishable, and for one note in eight that is wrong.

THE SUSTAIN LEVEL IS SL*256, NOT (SL+1)*256. The hardware leaves decay when
`(env >> 8) == (adsr2 >> 5)`, so the plateau is the bottom of a 256-wide band
starting at SL*256. SL=7 is the special case: env starts at 0x7FF after the
attack, 0x7FF >> 8 is already 7, so decay never runs and the note holds full.

GAIN MODES THAT RAMP ARE NOT DECIDABLE HERE. Modes 4-7 move env over time from
wherever it was, so a single key-on reading cannot name a level, and this
module returns None rather than a number. Those drivers run their own envelope
in software -- Mega Man X writes GAIN 390 times against 26 SRCN writes in ten
seconds -- and pinning their level needs the peak across the note's span, which
needs the write log retained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: ADSR1 bit 7 selects ADSR mode; clear selects GAIN.
ADSR_ENABLE = 0x80

#: The internal envelope is 11-bit. The ENVX register reports `env >> 4`.
ENV_MAX = 0x7FF

#: Sustain level maps to the top three bits of ADSR2, and the plateau is the
#: bottom of the 256-wide band the hardware compares against.
SUSTAIN_STEP = 0x100

MODE_ADSR = "adsr"
MODE_GAIN_DIRECT = "gain_direct"
MODE_GAIN_LINEAR_DECREASE = "gain_linear_decrease"
MODE_GAIN_EXP_DECREASE = "gain_exp_decrease"
MODE_GAIN_LINEAR_INCREASE = "gain_linear_increase"
MODE_GAIN_BENT_INCREASE = "gain_bent_increase"

#: GAIN mode is the top three bits; 0-3 is direct level, 4-7 are ramps.
_GAIN_RAMPS = {
    4: MODE_GAIN_LINEAR_DECREASE,
    5: MODE_GAIN_EXP_DECREASE,
    6: MODE_GAIN_LINEAR_INCREASE,
    7: MODE_GAIN_BENT_INCREASE,
}

MODES = (
    MODE_ADSR,
    MODE_GAIN_DIRECT,
    MODE_GAIN_LINEAR_DECREASE,
    MODE_GAIN_EXP_DECREASE,
    MODE_GAIN_LINEAR_INCREASE,
    MODE_GAIN_BENT_INCREASE,
)


@dataclass
class Envelope:
    """The envelope in force for one note, as far as a key-on can say.

    `peak_env` and `sustain_env` are None when the mode ramps from an unknown
    starting level. None means "not decidable from this", and a consumer must
    not read it as zero.
    """

    mode: str
    #: 0..ENV_MAX, or None when a ramp makes it undecidable.
    peak_env: int | None
    sustain_env: int | None
    #: ADSR fields, None in GAIN mode.
    attack_rate: int | None = None
    decay_rate: int | None = None
    sustain_level: int | None = None
    sustain_rate: int | None = None
    #: GAIN mode number 0-7, None in ADSR mode.
    gain_mode: int | None = None

    @property
    def holds_full(self) -> bool:
        """True when the note never decays, so VOL alone is its loudness."""
        return self.sustain_env == ENV_MAX

    @property
    def sustain_fraction(self) -> float | None:
        """The sustain plateau as a fraction of full scale."""
        if self.sustain_env is None:
            return None
        return self.sustain_env / ENV_MAX

    @property
    def peak_fraction(self) -> float | None:
        if self.peak_env is None:
            return None
        return self.peak_env / ENV_MAX

    def to_dict(self) -> dict[str, Any]:
        return {
            "env_mode": self.mode,
            "env_peak": self.peak_env,
            "env_sustain": self.sustain_env,
            "env_sustain_fraction": (
                round(self.sustain_fraction, 4)
                if self.sustain_fraction is not None else None
            ),
            "env_holds_full": self.holds_full,
            "attack_rate": self.attack_rate,
            "decay_rate": self.decay_rate,
            "sustain_level": self.sustain_level,
            "sustain_rate": self.sustain_rate,
            "gain_mode": self.gain_mode,
        }


def sustain_env_for(sustain_level: int) -> int:
    """The env the decay phase settles at, for a 3-bit sustain level.

    SL=7 holds at full scale because env is already 0x7FF when the attack
    ends and `0x7FF >> 8 == 7`, so the decay comparison matches immediately.
    """
    level = sustain_level & 0x07
    if level == 0x07:
        return ENV_MAX
    return level * SUSTAIN_STEP


def decode(adsr1: int, adsr2: int, gain: int) -> Envelope:
    """The envelope described by one voice's three envelope registers.

    `adsr1` is `$x5` and `adsr2` is `$x6`. Note that the vendored emulator
    names these `adsr0` and `adsr1`, offset by one from the convention used
    here and in `voices.py`; the offsets, not the names, are what match.
    """
    adsr1 &= 0xFF
    adsr2 &= 0xFF
    gain &= 0xFF

    if adsr1 & ADSR_ENABLE:
        sustain_level = (adsr2 >> 5) & 0x07
        return Envelope(
            mode=MODE_ADSR,
            # The attack phase runs env up to full scale regardless of rate,
            # so the peak is not a function of the registers.
            peak_env=ENV_MAX,
            sustain_env=sustain_env_for(sustain_level),
            attack_rate=adsr1 & 0x0F,
            decay_rate=(adsr1 >> 4) & 0x07,
            sustain_level=sustain_level,
            sustain_rate=adsr2 & 0x1F,
        )

    gain_mode = (gain >> 5) & 0x07
    if gain_mode < 4:
        # Direct: the hardware assigns env = (gain & 0x7F) * 0x10 every tick,
        # so the level is static and fully known.
        level = (gain & 0x7F) * 0x10
        return Envelope(
            mode=MODE_GAIN_DIRECT,
            peak_env=level,
            sustain_env=level,
            gain_mode=gain_mode,
        )

    mode = _GAIN_RAMPS[gain_mode]
    increasing = mode in (MODE_GAIN_LINEAR_INCREASE, MODE_GAIN_BENT_INCREASE)
    return Envelope(
        mode=mode,
        # An increase mode ends at full scale; a decrease mode starts from
        # whatever was already there, which a key-on reading cannot say.
        peak_env=ENV_MAX if increasing else None,
        sustain_env=None,
        gain_mode=gain_mode,
    )


def of_note(note: dict[str, Any]) -> Envelope:
    """The envelope for a note record from `voices.Note.to_dict()`."""
    return decode(
        int(note.get("adsr1") or 0),
        int(note.get("adsr2") or 0),
        int(note.get("gain") or 0),
    )


def census(notes: Any) -> dict[str, Any]:
    """Counts per mode plus how many notes hold at full scale.

    `n_decidable` is the honest denominator for any loudness correction: the
    ramping GAIN modes are excluded rather than counted as silent.
    """
    modes = {name: 0 for name in MODES}
    total = holds = decidable = 0
    sustain_sum = 0.0
    for note in notes:
        env = of_note(note)
        total += 1
        modes[env.mode] = modes.get(env.mode, 0) + 1
        if env.sustain_env is not None:
            decidable += 1
            sustain_sum += env.sustain_fraction or 0.0
            if env.holds_full:
                holds += 1
    return {
        "n_notes": total,
        "modes": modes,
        "n_decidable": decidable,
        "n_holds_full": holds,
        "mean_sustain_fraction": (
            round(sustain_sum / decidable, 4) if decidable else None
        ),
    }
