# What real SNES music does with its voices, envelopes and echo

> Figures regenerated over the rebuilt 1,316-track corpus, from
> `data/out/performance.json` (all tracks) and `performance_music.json`
> (`track_class == music`, 1,006 tracks). Every number below is the **median
> over games with its range**, never a track-weighted mean, so a game with
> many tracks cannot dominate.
>
> Restricting to music moves nothing material: voices 4.95 → 5.23, silent
> fraction 0.017 → 0.015, median note 0.1685 → 0.1687 s, register correlation
> −0.049 → −0.054. The jingles and effects were not shifting these figures,
> which is itself worth knowing — it means the conventions below are
> properties of the drivers and not artifacts of what counts as a song.

Measured over **1,316 tracks from 22 games**, 1,863,499 notes. Not a milestone:
this is the analysis `docs/design.md` §7 argues is the point of the corpus, and
it is about **performance** rather than composition for the reason recorded
there — composition-rule changes derived from measurement are 0 for 4 with this
listener, and the one axis that has ever landed is how material is *played*.

**Every figure is the median over GAMES, with the range across them.** A
corpus-wide mean weighted by track count would mostly describe Earthbound's
206 tracks, and worse, it would hide the distinction that matters here: a
**convention** is something every driver and composer does, a **house style**
is something one studio does. The range tells them apart and the median alone
does not.

---

## The headline: position-shaped velocity is an invention, not a convention

| | median over games | range |
|---|---|---|
| correlation of note volume with position through the track | **0.006** | −0.047 … 0.066 |

**Zero, in all 22 games.** Real SNES music does not make notes louder or softer
according to where they fall in the piece.

That matters because position-shaped velocity is one of only two changes this
project has ever made that a listener accepted immediately. So it is a good
idea that the source material does not contain — an invention that improves on
the convention rather than a convention waiting to be discovered. Worth knowing
before mining this corpus for more of the same: measurement found it absent,
and measurement would never have proposed it.

The other two volume shapers tested are **house styles, not conventions**:

| shaper | median | range |
|---|---|---|
| volume vs register | **−0.049** | **−0.481 … +0.552** |
| volume vs voice index | −0.083 | **−0.552 … +0.705** |

The register figure was published as **+0.031** on an earlier extraction and is
corrected here. It moved because the corpus was rebuilt after voice state began
being seeded from the SPC's DSP register block, which changed SRCN — and so the
sample, and so the register a note is read as playing — for 148,422 notes
across 619 tracks. The sign flip is not a finding; it is a near-zero median
wobbling about zero, which is the actual result: **register does not shape
volume corpus-wide.**

Breath of Fire II gets steadily louder up the voice indices and Donkey Kong
Country steadily quieter, which is two studios' voice-allocation habits rather
than anything musical. Both are strong within a game and cancel across the
corpus.

## Real conventions — tight across all 22 games

| | median | range |
|---|---|---|
| **ADSR attack rate** | **15 (the maximum)** | 14 … 15 |
| **ADSR sustain level** | **7 (the maximum)** | 3 … 7 |
| ADSR used rather than direct GAIN | 0.979 | 0.000 … 1.000 |
| time with at least one voice sounding | 0.983 | 0.912 … 0.999 |

**Instant attack is universal.** Across 20 games that use ADSR at all, the
median attack rate is the fastest the hardware offers and the range is one
step wide. Nobody shapes an attack with the envelope — the sample's own onset
does that work, and the envelope is left to decay and sustain. For anything
generating SNES music, an attack ramp is a wrong default.

**Sustain is normally wide open**, at the maximum level in most games, so the
envelope's expressive work is in the decay and release rather than the plateau.

Two games use **direct GAIN exclusively and never touch ADSR**: Plok! and
Super Turrican — both Western studios (Software Creations, Factor 5), which is
a suggestive pattern across a sample of two and nothing more.

## Voices: about five of eight, continuously

| | median | range |
|---|---|---|
| mean voices sounding | **4.95** | 3.38 … 7.76 |
| mean when sounding at all | 5.21 | 3.78 … 7.77 |
| silent fraction | 0.017 | 0.001 … 0.088 |

The hardware's eight voices are not a budget most music spends. Five is
typical, and the spread is a real stylistic axis: **Breath of Fire II (7.76)
and Mega Man X (7.68)** run nearly full while **Kirby Super Star (3.38) and
Super Mario World (3.40)** use less than half. Silence is almost absent —
these are continuous textures, not arrangements with rests.

## Note lengths: short, and staccato is a house style

| | median | range |
|---|---|---|
| median note length | **0.169 s** | 0.075 … 0.300 |
| share under 100 ms | 0.141 | **0.000 … 0.735** |
| share over 1 s | 0.047 | 0.000 … 0.141 |

The median note is a sixth of a second. But the staccato share spans the whole
range: **Kirby Super Star is 73.5% notes under 100 ms** against games with
none at all, and Dragon Quest V's median note is four times Kirby's. Note
length is not a hardware convention; it is the most game-specific measure here.

## Echo is standard equipment, its settings are not

| | median | range |
|---|---|---|
| tracks with echo enabled | **1.000** | 0.000 … 1.000 |
| voices routed to echo | **6 of 8** | 0 … 8 |
| echo feedback | 18 | **−80 … +100** |

**Echo is on in every track of the median game, on three-quarters of the
voices.** Treating it as an effect to add is backwards; it is the default
acoustic of the platform.

Its settings are the opposite of a convention. Feedback runs from **−80
(ActRaiser) to +100 (Lufia II)** — and negative feedback is a phase-inverted
echo, a different effect rather than less of the same one. Final Fantasy VI and
Chrono Trigger both sit at +85, which is an AKAO house setting.

Three games never enable it at all: **Plok!, Super Castlevania IV and Super
Mario World.**

## Stereo: subtle by default, with two studios as exceptions

| | median | range |
|---|---|---|
| median absolute pan | 0.167 | 0.000 … 0.500 |
| hard-panned share (>0.6) | **0.002** | 0.000 … 0.447 |
| phase-inverted share | **0.000** | 0.000 … 0.558 |

Panning is normally gentle and hard panning essentially unused — except
**Earthbound at 44.7%** and Super Mario World at 35.3%.

Phase inversion (one side's volume negative) is unused in twenty games and
then **Tales of Phantasia at 55.8% and Star Ocean at 52.6%** — both Wolf Team /
tri-Ace with Motoi Sakuraba, so one team's signature on more than half its
notes, and invisible in any corpus-wide average.

## Noise and pitch modulation are effectively unused

**106 noise notes and 727 pitch-modulated notes out of 1,863,499** — 0.006%
and 0.039%. The median game uses neither.

This was initially suspected to be a measurement error, since reading a
register's *last* value misses a driver that sets and clears it per note. It
is not: in a 40-track sample, PMON and NON are written **1,479,800 times each,
always with the value zero**. Drivers re-upload the whole register block every
tick and keep both switched off — the same habit that makes Zelda write KON 365
times a second and mean it 1.6% of the time. Two of the S-DSP's distinctive
features are, in practice, dead hardware in this corpus.

---

## What is worth acting on

1. **Instant attack, full sustain, echo on, about five voices.** Those are the
   platform's defaults and all four are tight across 22 games.
2. **Do not derive velocity shaping from this corpus** — there is none to find.
   The shaping that works is an addition to the idiom, not a recovery of it.
3. **Expect register-, voice- and length-related habits to be per-studio.**
   They are strong inside a game and cancel across the corpus, so a model
   trained on the pooled corpus will learn their average, which is nothing.
4. **Noise and pitch modulation need no support** to match the corpus.

## Limits

Echo, noise and pitch-modulation figures come from the raw write logs and are
sampled at **6 tracks per game**, because those registers sit outside the
per-voice block and need the full log; the rest use every track. The volume
correlations are linear and would miss a shaped curve that is not monotone.
Voice counts are sampled on a 20 ms grid, so a note shorter than that can be
missed. And a "convention" here means consistent across these 22 games, which
are weighted toward JRPGs and first-party titles.
