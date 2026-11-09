# SNES-MDB field reference

Every published field: name, type, unit, range, and what a null means.

This page exists because an independent evaluator, directed to
`events/*.json.gz` in bold by two separate documents, found no field-level
schema anywhere in the distribution and had to **measure** the value domains
of `attack_level`, `sustain_level`, `voice`, `pitch_confidence` and
`duration_sec: null` before using them. Each was recoverable in minutes and
each was a guess. One guess in particular — that `attack_level` is `0..127`
rather than the raw signed 8-bit `VOL` of `-128..127` — happened to be right,
and being wrong would have mis-scaled every dynamics statistic with no error
raised.

Ranges below are **measured over the published corpus**, not declared limits.

## Two standing rules for this documentation

Both exist because an independent evaluation found the same two failure modes
repeatedly, and both are checkable rather than aspirational.

**A field name may not assert more than the field measures.** `max_polyphony`
counted distinct pitches among pitched notes; `driver_tick_hz` published an
estimate its own validity flag had refused; `pitch_confidence` reported
confidence in pitches that did not exist. Each read as a stronger claim than
the data supported, and each failed silently because the data was consistent
with itself. All three are fixed, and the rule is now the test: if a name
promises more than the values deliver, the name changes.

**An interpretive instruction must be reproducible from published fields, or
it does not ship.** This documentation once told researchers that interval
work "is not safe for Capcom" on the strength of a figure no recipient could
reproduce and which turned out to be stale by a factor of four. Every
remaining instruction here — use `pitched_attack_count` as the pitch
denominator, use `uniform` to compare across tracks, use unquantised times for
microtiming — rests on fields in the distribution and can be checked against
them. Where a caveat depends on something not measured, it says so: the
per-driver tuning table names `driver` as curated knowledge, and the
gated-voice statistics ship the two numbers that reveal their own confound.

---

## `events/*.json.gz` — `snesmdb.events.v4`

**Start here for most research.** One file per track, flat, in seconds.

### Header

| field | type | meaning |
|---|---|---|
| `schema` | string | `snesmdb.events.v4` |
| `track_id` | string | `<slug>-<number>:<hash>`, unique in the corpus |
| `game` | string | display name, from the SPC's ID666 tag (32-char limit) |
| `game_slug` | string | one of 22; see `index.json` → `games` |
| `track_class` | string | `music`, `jingle`, `effect`, `drone` — **musical**, independent of `extraction_status` |
| `duration_sec` | float | rendered length, from the ID666 "seconds to play" field |
| `extraction_status` | string | `complete_with_pitched_events`, `complete_unpitched_only`, `complete_no_events`, `incomplete` — **data quality**, independent of `track_class` |
| `event_count` | int | rows in `events` |
| `pitched_event_count` | int | rows with `pitch_status == "estimated"` |
| `unpitched_event_count` | int | `event_count - pitched_event_count` |
| `attack_count` | int | rows with `origin == "key_on"` |
| `attacks_with_sample_id` | int | key-ons whose identity was established |
| `attacks_without_sample_id` | int | key-ons published with `sample_id: null`. Read with `sample_id_unresolved_reason` to see why |
| `attacks_identity_observed_at_key_on` | int | key-ons whose identity came from instrumented DSP observation rather than the capture-time directory |
| `legato_step_count` | int | rows with `origin == "legato_step"` |
| `pitched_attack_count` | int | both: a pitched key-on. **Use this as the denominator for "how many notes have a pitch"** |

### Rows

| field | type | unit | range / nulls |
|---|---|---|---|
| `event_id` | int | — | **a row key: unique within a track**, across both origins |
| `parent_event_id` | int or null | — | **null on a `key_on`**; on a `legato_step`, the `event_id` of the key-on it continues |
| `origin` | string | — | `key_on` (a new triggered note) or `legato_step` (a pitch change on a voice that never re-keyed) |
| `onset_sec` | float | seconds | 0 to `duration_sec`, 6 dp (≈1 µs). Unquantised — taken from the event log, not from a grid. **`onset_sec` and `duration_sec` are rounded independently, so `onset + duration` can cross the next note's onset on the same voice by exactly 1 µs**: 3,695 consecutive pairs across 106 tracks, none by more than 1 µs. **The overshoot is not limited to one voice.** SNES drivers key several voices on the same sequencer tick, so one crossing instant can affect up to 5 voices at once — a naive sweep reports **9 to 13** simultaneous voices on hardware that has 8, and Super Castlevania 4's true peak of 6 reads as 10. Means are unaffected (+0.00000 at five decimals); **peaks are not**. Three remedies each remove it completely: clamp a note's end to the next onset on its voice, ignore overlaps ≤1 µs, or union each voice's intervals. Half-open intervals also need **closes processed before opens** at equal timestamps, which alone takes 9 games over the limit down to 6. **And read the decimals exactly**: these 6-dp literals are not representable in binary float64, so parsing as `float` manufactures about 3,640 further overlaps of ~1e-16 s that do not exist in the data. Use `decimal.Decimal`, or threshold at 1 µs rather than at zero |
| `duration_sec` | float or null | seconds | null, never zero length. **159,584 rows are null, of which 154,910 are legato steps** — a step has no duration of its own — leaving **4,674 key-ons that were still sounding when the render window ended.** Budget right-censoring against the 4,674, not the 159,584: their median onset is at 99.64% of the render window |
| `voice` | int | — | `0..7`, the S-DSP hardware voice. **Not a fixed musical part** — assignment can change mid-track |
| `pitch_status` | string | — | `estimated`, `noise`, `pitch_modulated`, `unrecoverable`. **Only `estimated` is a pitch** |
| `midi_note` | float or null | semitones | null unless `pitch_status == "estimated"`. Fractional and **not clamped to MIDI's domain**: measured −36.74 to +131.09 |
| `pitch_confidence` | string or null | — | **null unless `pitch_status == "estimated"`.** In practice binary: among rows that have a pitch only `high` (1,394,511) and `medium` (165,491) occur. `low` and `none` attach to rows with no pitch, where the field is now null, so they are redundant with `pitch_status`. On legato steps it is 98.7% `high` and gives no discrimination. About the *estimate*, not the note |
| `sample_id` | string or **null** | — | 16 hex chars, or **null when no identity was established**. Content identity of the decoded BRR audio — **not an instrument label**. Resolved AT KEY-ON from the directory entry the DSP actually read, not from the entry present when the SPC was captured: drivers rewrite entries during playback, so one SRCN can address different audio at different moments. **v3 and earlier used `""` and never null** — a reader testing `is not None` read 13,413 non-identities as identities |
| `sample_id_source` | string | — | `observed_at_key_on` (the DSP was instrumented and its committed entry used), `capture_time_directory` (no observation; the entry present at capture), or `unresolved` |
| `sample_id_unresolved_reason` | string or null | — | non-null **exactly when `sample_id` is null**. `directory_entry_unwritten` (the entry is `$FFFF` fill or address 0 — it still *decodes*, which is why earlier releases published a hash of unwritten memory), `not_established`, or `no_directory_entry_at_capture`. An uncertain identity is published as null and **never** backfilled with a plausible-looking substitute |
| `pitch_register` | int or null | raw | the **14-bit PITCH register value this event wrote**, alongside the derived `midi_note`. Published so a surprising pitch can be checked against the hardware value instead of taken on trust. A step's `midi_note` is derived as `parent.midi_note + 12·log2(step.pitch_register / parent.pitch_register)` |
| `attack_level` | int | — | `0..127`. `VOL` rescaled. **A register value, not perceived loudness** |

> **`midi_note` is an estimate, and its calibration is per sample.**
>
> No SNES field records a sample's base frequency, so `midi_note` is derived
> from the 14-bit `pitch_register` ratio and a fundamental **estimated from
> that sample's own decoded audio**. Each sample therefore carries its own
> tuning offset, and the offsets are independent across samples and games.
>
> What that means in practice:
>
> - **Relative intervals within one voice on one sample are reliable** — the
>   register ratio is exact and the sample's offset cancels. This is why the
>   published interval-prediction baseline works on intervals rather than
>   absolute pitches.
> - **Absolute pitch and key analyses inherit the per-sample offset.** Two
>   voices playing the same concert pitch from different samples can report
>   different `midi_note` values, so a key estimate pooled across samples
>   mixes several calibrations.
> - **Cross-game absolute comparisons are the weakest case**, since no two
>   games share a sample bank.
>
> The corpus measures `midi_note` from −34.2 to 131.1, outside MIDI's domain
> at both ends, and 1.73% of pitched attacks fall outside a musical register
> — residual octave errors in fundamental estimation rather than notated
> extremes. `pitch_confidence` describes confidence in the *estimate*, not in
> the note.
>
> This is a property of the published estimates, not a defect to be
> corrected here: SNES-MDB publishes pitch estimates, not guaranteed
> concert-pitch transcription.
| `sustain_level` | int | — | `0..127`. Where the envelope settles; differs from `attack_level` on 19.4% of notes |

### Reading it correctly

- **A pitch histogram** filters `pitch_status == "estimated"`. A missing
  `midi_note` is not a rest and not a zero.
- **Counting notes** filters `origin == "key_on"`. A legato step is a pitch
  change inside a note that is already sounding.
- **Counting simultaneous voices** counts distinct `voice` values active at a
  time, not rows. Include unpitched notes — percussion is a sounding voice.
- **A gated voice is not an audible voice, and the difference is not
  uniform across games.** `duration_sec` runs from key-on to key-off, and some
  drivers never release a voice: Breath of Fire 2 and Mega Man X hold a median
  gap of **1.1–1.2 ms** between a key-off and the next key-on on the same
  voice, against **27–64 ms** elsewhere — a 50× spread — and a duty cycle of
  0.97. Those two games therefore saturate any gated-voice measure for a
  reason that is **not musical**. An evaluator nearly published a density
  comparison on this basis before catching it. Per-game concurrency figures,
  including the published `performance.json` → `voices.mean_when_sounding`,
  carry the same exposure. Deciding when a voice became *inaudible* needs an
  envelope-release model, and no published field carries the ADSR rates it
  would require.
- **Reassembling a phrase** groups steps on `parent_event_id`.
- `midi_note` outside `0..127` is real and must be filtered for MIDI work:
  **184 events, 114 of them negative.**
- **4,164 of the 154,910 legato steps write their parent's exact PITCH
  register**, of which **2,926 have a recovered pitch at both ends** and so
  repeat the parent's `midi_note`; the other 1,238 are unpitched. A driver
  rewriting the same register value, typically alongside a volume change. That is real data. Before `v3` *all* 154,910 did, which was
  a defect; a step matching its parent is now the exception rather than the
  rule.

---

## `index.json` — `snesmdb.index.v1`

`{schema, formats, corpus, games, drivers, tracks}`. **`tracks` is a list; it
was a bare top-level array before `v1`.**

| block | contents |
|---|---|
| `formats` | the schema version of every format in the tree. Check the one you read |
| `corpus` | `n_tracks`, `n_games`, `n_events`, `n_pitched_events`, `n_pitched_attacks`, `n_attacks`, `track_classes`, `extraction_statuses` |
| `games` | slug → display name, for all 22 |
| `drivers` | **curated external knowledge** — see below |
| `tracks` | one object per track: every `tracks.csv` column (including `game_slug` and the three `driver*` fields), plus `midi_summary`, `uniform_hz`, `uniform_n_rows`, `checks_passed`, `composer_truncated`, `sha256_source_spc`, and the relative paths `events`, `scores`, `intake`, `midi` |

`midi` is absent on the 73 tracks with no pitched note.

## `tracks.csv` — `snesmdb.tracks.v1`

The per-track metadata, one line each, so a partial copy degrades row by row.
Columns: `track_id`, `game_slug`, `game`, `title`, `composers`
(semicolon-separated), `track_class`, `extraction_status`, `split`,
`render_seconds`, `n_notes`, `event_count`, `pitched_event_count`,
`pitched_attack_count`, `attack_count`, `legato_step_count`, `driver`,
`driver_vendor`, `driver_confidence`.

## `drivers` — `snesmdb.drivers.v1`

**The one curated field in the distribution.** Which audio engine each game
used, from published documentation and game credits — **not derived from the
SPC files and not verifiable from anything in the corpus.** No extraction step
identifies a driver. `driver_confidence` is `documented` or `attributed`.
Treat a label as a hypothesis to test, not a measurement; publishers reuse and
replace engines between titles. It ships because this documentation conditions
advice on the driver in four places, and an evaluator could not act on any of
it without supplying the mapping themselves.

## `scores/*.json.gz`

Row-indexed piano rolls, two grids: the primary one is this driver's own
SPC700 timer tick (rate differs per track), and `uniform` is a fixed 100 Hz.
**Use `uniform` to compare tracks or games.**

| top-level key | contents |
|---|---|
| `separated`, `blended`, `expressive` | the three formats on the primary grid |
| `uniform` | the same three on the fixed 100 Hz grid, plus its own `stats` |
| `clock` | the SPC700 timer this track's rows are indexed on |
| `timers`, `envelope`, `tick`, `software_divisor_m` | hardware context; see `DATASET.md` |
| `onset_grid` | **the period the music's onsets actually lie on** — see below |
| `stats` | the counters in the next table |

### `onset_grid` — use this for rhythm and quantisation work

Published on every track and **not** used to index any row. It carries
`found`, `period_ticks`, `period_sec`, `rows_per_second`,
`bpm_assuming_4_rows_per_beat`, `phase_ticks`, `n_rows`, `fit` and
`median_abs_residual_ticks`.

**If you are studying rhythm, start here, not with `clock`.** Onsets
concentrate on `onset_grid` far more than on the timer clock — R = 0.937
against 0.262 by one estimator, 0.779 against 0.344 by another — and a period
fitted on half a track and tested on the other half reaches 0.853 against the
tick's 0.188. **The value is estimator-dependent; the ordering and the size of
the gap are the finding**, and both are registered in `claims.json` and
checked by `replicate.py`. `clock` is a hardware fact — one row
is one timer tick — and the timer runs several times faster than the music: the
measured onset period is a median 16.5× the tick. An evaluator measured
quantisation against `clock` first, got R = 0.26, and nearly reported that this
corpus's onsets are barely quantised.

It is not used as a row index because the fitted period is not stable enough
across tracks to build a comparable corpus-wide score on — 346 distinct rates
across 664 tracks when that was attempted. That is a different question from
whether it describes the music, and it does.

| `stats` field | meaning |
|---|---|
| `n_cells_filled` | voice-rows holding a pitched note |
| `separated_density` | `n_cells_filled / (n_rows × 8)` |
| `n_rows_sounding` | rows with at least one pitched note |
| `rows_sounding_fraction` | `n_rows_sounding / n_rows` |
| `coverage` | `n_notes_represented / n_notes` — the share of notes the grid could place |
| `n_notes_unpitched` | notes with no recovered pitch, which a piano roll cannot hold |
| `n_notes_out_of_range` | pitched notes outside the roll's MIDI range |
| `n_rows`, `n_notes`, `n_notes_represented`, `n_notes_snapped`, `n_notes_unplaced` | placement accounting |
| `n_cells_contested` | voice-rows where two notes collided; the later won |
| `max_distinct_pitched_notes_per_row` | **largest number of distinct PITCHES on a row, over pitched notes only.** Renamed from `max_polyphony`, which was read as voice count and is not |
| `max_pitched_voices_per_row` | voices holding a pitched note |
| `max_voices_sounding_per_row` | **voices holding any note, pitched or not — the voice-concurrency figure** |

**Piano rolls contain pitched notes only**, so a percussion track can show
zero pitched activity while eight voices sound, and they **extend a
never-released note to the end of the render** where `events` leaves
`duration_sec` null.

## `intake/*.json.gz` — `snesmdb.intake.v1`

Per-voice note trees with absolute times.

Its `timing` block: `ticks_per_second` is the SPC700 clock, 1,024,000.
`row_period_ticks` and `rows_per_second` describe this track's primary row
grid, and `row_clock_source` names where the clock came from
(`timer_register`). `sequencer_timer` names which hardware timer the driver
drove the sequencer from (`T0/T1` or `T2`). `software_divisor_m` is the
timer-to-write-cadence ratio — see `DATASET.md`, and note it is **not** ticks
per musical row. `driver_tick_hz` is the sequencer write-cadence estimate, and
**`driver_tick_found` says whether it passed its own plausibility check** —
`driver_tick_hz` is null on the 797 tracks where it did not, so the absence is
self-describing without opening another file.

Notes carry `start_sec`, `end_sec`,
`midi_note` (full float precision, unlike `events`' 4 dp), `velocity`,
`sustain`, `srcn`, `sample_id`, and an inert `timbre_class`. **Flagged as
proposed**: its shape is not verified against the renderer that is meant to
consume it.

## `midi/*.mid`

Type 1, **nine chunks: a conductor track followed by eight voice tracks**, so
chunk *n+1* is voice *n*. Each voice track carries a `voice N` text name, and
voice 7 is written to MIDI channel 8 (1-based), skipping channel 7, so
0-based channel 9 — GM percussion — is absent from all 1,243 files. No
program changes: the corpus has no trustworthy instrument mapping. 1,243 files
for the tracks with at least one pitched note; 1,458,120 note-ons written and
402,635 notes dropped as unpitched or out of range.

## `performance.json`, `performance_music.json`

Per-game performance conventions. `performance_music.json` restricts to
`track_class == "music"`; otherwise identical in shape.

**The shape, stated correctly.** An earlier version of this page described the
display-name keying at the top level and three of its four named fields at the
wrong depth, so a reader's first script found zero games and printed nothing:

```
{
  "corpus":      { ... the same blocks, pooled over all games ... },
  "n_tracks":    int,
  "track_class": "all" | "music",
  "per_game": {
     "<game display name>": {        <- display name, NOT slug
        "n_tracks":     int,
        "voices":       { max, mean, mean_when_sounding, silent_fraction,
                          median_release_gap_ms, gated_duty_cycle },
        "note_lengths": { median_sec, under_100ms, over_1s },
        "velocity":     { median_volume, median_abs_pan, hard_panned_fraction,
                          phase_inverted_fraction, corr_volume_vs_register,
                          corr_volume_vs_position, corr_volume_vs_voice },
        "envelopes":    { adsr_fraction, distinct_adsr_words,
                          attack_rate_median, sustain_level_median },
        "echo":         { n_sampled, echo_on_fraction, median_echo_voices,
                          median_echo_volume, median_feedback,
                          median_noise_voices, median_pitch_mod_voices }
     }
  }
}
```

Every value is a **median over that game's tracks** of a per-track statistic,
except the counts and fractions noted below.

**Censoring convention.** These aggregates **extend a note with
`duration_sec: null` to the end of the render window**; they do not drop it.
Both treatments are defensible and the files had not said which they used, so
a researcher comparing their own figures could not tell a method difference
from an error. Dropping the 4,674 censored notes instead moves `voices.max` on
at least one game and lowers `mean` across the board; with this convention an
evaluator reproduced all 22 per-game maxima exactly and `mean_when_sounding`
to a median 0.0076 voices.

Register names used below, since this table assumes them: **VOLL/VOLR** are
the per-voice left and right volumes (signed, −128..127); **EVOLL/EVOLR** are
the echo output volumes and **EFB** the echo feedback, all signed; **EON**,
**NON** and **PMON** are the per-voice enable bitmasks for echo, noise and
pitch modulation; an **ADSR word** is the 16 bits of ADSR1+ADSR2, whose fields
are a 4-bit attack rate, 3-bit decay rate, 3-bit sustain level and 5-bit
sustain rate.

| field | unit | meaning |
|---|---|---|
| `voices.max` | voices | largest voice count seen |
| `voices.mean` | voices | mean over all rendered time, silence included |
| `voices.mean_when_sounding` | voices | mean over time with at least one voice gated. **Read the two fields below before comparing this across games** |
| `voices.median_release_gap_ms` | ms | median silence between a key-off and the next key-on **on the same voice**. Near zero means the driver holds voices gated, so a gated count overstates audible density |
| `voices.gated_duty_cycle` | fraction | gated voice-time **divided by (rendered seconds × the number of voices the track actually uses)** — NOT by 8. The distinction matters: under a `/8` reading Plok! computes 0.588 and looks usable, where the published value is 0.960 and is not |

**Apply a threshold, do not use a list.** An earlier version of this page named
two games as saturated. Measured on `performance_music.json`, three exceed a
`gated_duty_cycle` of 0.95 — Breath of Fire 2 **0.976**, Mega Man X **0.972**,
Plok! **0.960** — and Dragon Quest 5 (0.906) and Batman Returns (0.898) are not
far behind. An evaluator following the prose excluded two games and kept a
third that the field flags equally. Pick a threshold, apply it to the field,
and say which one you used.
| `voices.silent_fraction` | fraction | share of rendered time with no voice gated |
| `note_lengths.median_sec` | seconds | median note duration |
| `note_lengths.under_100ms`, `over_1s` | fraction | share of notes shorter / longer |
| `velocity.median_volume` | raw register | `\|VOLL\| + \|VOLR\|`, so the domain is `0..254` and values above 127 are normal — **not** the `0..127` scale `events` uses |
| `velocity.median_abs_pan` | fraction | median of `\|VOLL−VOLR\| / (\|VOLL\|+\|VOLR\|)` |
| `velocity.hard_panned_fraction` | fraction | share of notes with one side at or near zero |
| `velocity.phase_inverted_fraction` | fraction | share with opposite-sign left and right volume |
| `velocity.corr_volume_vs_register` | Pearson r | volume against MIDI number, per track |
| `velocity.corr_volume_vs_position` | Pearson r | volume against position through the track |
| `velocity.corr_volume_vs_voice` | Pearson r | volume against voice index |
| `envelopes.adsr_fraction` | fraction | share of notes using ADSR rather than direct GAIN |
| `envelopes.distinct_adsr_words` | count | distinct 16-bit ADSR1+ADSR2 words used |
| `envelopes.attack_rate_median` | ADSR field | raw 0..15 attack-rate nibble; higher is faster |
| `envelopes.sustain_level_median` | ADSR field | raw 0..7 sustain-level field; the plateau is `SL × 256` of 2047 |
| `echo.n_sampled` | count | **tracks contributing to this echo block**, not notes or voices |
| `echo.echo_on_fraction` | fraction | share of sampled tracks with `EON` set on any voice |
| `echo.median_echo_voices` | voices | voices with echo enabled |
| `echo.median_echo_volume` | raw register | `(\|EVOLL\| + \|EVOLR\|) / 2` |
| `echo.median_feedback` | raw signed register | `EFB`, `-128..127`; negative is normal and not an error |
| `echo.median_noise_voices` | voices | voices with `NON` set |
| `echo.median_pitch_mod_voices` | voices | voices with `PMON` set |

## Claim verification — a repository tool, not a distribution artifact

`claims.json` and `replicate.py` are **not included in a published
distribution**, and earlier revisions of this document described them as if
they were. They live in the source repository (`docs/claims.json`,
`tools/replicate.py`).

They are also **scoped to the 22-game frozen cohort**: every `reported`
figure in the registry was measured on `gate5-rc10` (1,316 tracks), and each
claim now records that in a `measured_on` block. Run against that release,
11 of 11 applicable claims reproduce. Run against the 27-game corpus, all 11
report **not applicable** — recomputing a 22-game figure over 1,477 tracks
and calling the difference a defect would be a sampling-frame error, not a
replication failure.

There is **no claims registry for the 27-game corpus yet**. Until there is,
the reproducible artifact shipped with a release is the interval baseline in
`toolkit/` (see `REPRODUCE.md`), not the claim runner.

The registry's own structure, for reference:

## `claims.json` — `snesmdb.claims.v1` (repository only)

Every quantitative claim in this documentation that could change a
methodological choice, with its evidence and the method to recompute it. Each
is one of three kinds, and the distinction is the point:

| kind | meaning |
|---|---|
| `measurement` | recomputable from the distribution. A discrepancy is a defect |
| `estimate` | recomputable only under a named assumption, recorded in `assumes` |
| `interpretation` | a statement about what a field *means*; not mechanically checkable, listed so you know which claims rest on judgement |

**`replicate.py` in the repository checks them.** It reads only the
distribution, imports nothing from this project, and where possible reads a
*different* published representation from the one a claim's own figure came
from — the MIDI note-on total is recovered by parsing the binary files, which
no JSON table touches. Claims it cannot check that way are marked
`same_representation`, and prove correspondingly less.

```sh
# From a source checkout, against the release the claims were measured on:
python3 tools/replicate.py /path/to/gate5-rc10
```

Reproducing a measurement does not establish that it measures the musical
concept it is named for, nor that a conclusion generalises beyond these 22
games. Those are separate claims and no runner settles them.

## `splits.json`, `summary.json`, `provenance.json`, `RELEASE.json`

`splits.json` is the composer-disjoint train/valid/test assignment.
`summary.json` is corpus-level extraction statistics including the row-clock
census. Its `scores.max_distinct_pitched_notes_per_row` was published as
`max_polyphony` before `events.v3`; see the note it carries. `provenance.json` records the commit, cleanliness, interpreter and
platform that built the tree — and deliberately **no hostname or user**.
`RELEASE.json` pins a SHA-256 and byte count for every file. There is no
`verify.py`; the checker is `tools/freeze_release.py --verify` in the source
repository. Generated bytecode (`__pycache__`) is deliberately excluded from
the pin, so running the packaged toolkit does not make the archive report
itself as modified.

`summary.json` is present in single-cohort releases and **absent from the
combined 27-game distribution**, whose out-tree is assembled from two
cohorts rather than produced by one extraction run.
