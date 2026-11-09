# Delayed voice doubling in SNES-MDB

**Contributed exploratory research. Not an established corpus finding.**

| | |
|---|---|
| status | exploratory, pending independent reproduction |
| contributed by | independent researcher, blind usability evaluation (Milestone 7D) |
| data | `snesmdb-27game-rc1` / `snesmdb-27game-toolkit-rc1`, 1,477 tracks, 27 games |
| analysis code | **not preserved** — see [Reproduction status](#reproduction-status) |

This is in `research/case_studies/` and not in `DATASET.md` or the README's
verified findings on purpose. It was produced by a researcher working only
from the published release during an independent usability evaluation, it has
not been reproduced from the frozen distribution by anyone else, and its
analysis code was not retained. It is recorded because the observation is
interesting and testable, not because it is settled.

## The observation

| | |
|---|---|
| candidate doubled voice pairs | **172** |
| music tracks affected | **134** |
| games represented | **22 of 27** |
| delayed pitch-sequence restatement | **152** |
| near-simultaneous layering | **20** |

Among the 152 delayed pairs, **137 of 152 lagging voices carried a lower
attack level**, with a reported median level ratio of about **0.45**. Delays
were reported as aligning with estimated rhythmic grids.

## The research finding, stated at the strength the evidence supports

> Across the 27-game SNES-MDB corpus, an independent symbolic analysis
> identified 172 candidate doubled voice pairs across 134 music tracks. Of
> these, 152 exhibited delayed pitch-sequence restatement and 20 exhibited
> near-simultaneous layering. Delayed pairs frequently showed lower attack
> levels in the following voice, with timing aligned to estimated rhythmic
> grids.
>
> These observations suggest that time-shifted voice doubling was a
> recurring arrangement technique in SNES music. They do **not**
> independently establish audible echo, stereo widening, a particular DSP
> implementation, or composer intent.

## What this evidence cannot establish

The gap between "detectable in symbolic data" and "deliberate compositional
choice" is where this analysis stops, and the reasons are specific:

- **Rhythmic alignment is not evidence of notation.** The onset grid is
  itself *fitted from note timings*, so alignment between a delay and that
  grid is partly circular. A delay could equally be an implementation
  artefact of how a driver schedules voices.
- **Attack level is a register value, not loudness.** `attack_level` is
  rescaled `VOL`; it carries no perceptual calibration and no stereo
  information. A 0.45 level ratio does not establish that the second voice
  was *heard* as subordinate.
- **Nothing here is audible evidence.** The analysis reads symbolic events.
  Whether a pair produces audible echo, chorusing or stereo width depends on
  panning, the echo/FIR unit and envelope behaviour, none of which are in
  the published representation.
- **Pitch recovery is uneven.** 21.29% of corpus attacks carry no
  fixed-pitch estimate, and recovery differs between the 22-game cohort and
  the 5-game expansion, so the two halves are not equally observable by a
  pitch-sequence method.
- **Per-sample tuning offsets apply.** Two voices doubling the same written
  line from *different* samples can report different `midi_note` values, so
  a pitch-sequence match across samples is a weaker signal than one within
  a single sample.

## Reproduction status

**The analysis code and parameter settings were not preserved.** The figures
above are therefore a report of a result, not a reproducible measurement,
and the matching thresholds, null controls and affected track IDs are not
recorded here because they were not captured.

Promoting this to an established dataset finding requires, in order:

1. the analysis code and its parameters, preserved;
2. a reproduction from the frozen distribution by someone other than its
   author;
3. the matched track IDs and voice pairs published so a reader can inspect
   individual cases rather than a count.

That is future researcher-contributed validation. It is **not** a release
blocker and does not affect any published claim.

## Why it is worth keeping anyway

The question it raises is a real musicological one that the corpus is well
suited to answer: how did composers working with eight hardware voices use
duplication and delay to create texture and space? A method that detects
time-shifted duplicate pitch sequences across 22 games and multiple sound
drivers is a reasonable starting point for that question, whatever the
mechanism turns out to be.

It is also the clearest evidence so far that the corpus supports research
its authors did not anticipate — the point of publishing it.
