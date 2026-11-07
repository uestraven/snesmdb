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

## `events/*.json.gz` — `snesmdb.events.v3`

**Start here for most research.** One file per track, flat, in seconds.

### Header

| field | type | meaning |
|---|---|---|
| `schema` | string | `snesmdb.events.v3` |
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
| `legato_step_count` | int | rows with `origin == "legato_step"` |
| `pitched_attack_count` | int | both: a pitched key-on. **Use this as the denominator for "how many notes have a pitch"** |

### Rows

| field | type | unit | range / nulls |
|---|---|---|---|
| `event_id` | int | — | **a row key: unique within a track**, across both origins |
| `parent_event_id` | int or null | — | **null on a `key_on`**; on a `legato_step`, the `event_id` of the key-on it continues |
| `origin` | string | — | `key_on` (a new triggered note) or `legato_step` (a pitch change on a voice that never re-keyed) |
| `onset_sec` | float | seconds | 0 to `duration_sec`, 6 dp (≈1 µs). Unquantised — taken from the event log, not from a grid. **`onset_sec` and `duration_sec` are rounded independently, so `onset + duration` can cross the next note's onset on the same voice by exactly 1 µs**: 3,695 consecutive pairs across 106 tracks do, none by more than 1 µs. A naive interval sweep reports two voices gated where one sounds; clamp to the next onset, or ignore overlaps of ≤1 µs |
| `duration_sec` | float or null | seconds | null, never zero length. **159,584 rows are null, of which 154,910 are legato steps** — a step has no duration of its own — leaving **4,674 key-ons that were still sounding when the render window ended.** Budget right-censoring against the 4,674, not the 159,584: their median onset is at 99.64% of the render window |
| `voice` | int | — | `0..7`, the S-DSP hardware voice. **Not a fixed musical part** — assignment can change mid-track |
| `pitch_status` | string | — | `estimated`, `noise`, `pitch_modulated`, `unrecoverable`. **Only `estimated` is a pitch** |
| `midi_note` | float or null | semitones | null unless `pitch_status == "estimated"`. Fractional and **not clamped to MIDI's domain**: measured −36.74 to +131.09 |
| `pitch_confidence` | string or null | — | **null unless `pitch_status == "estimated"`.** In practice binary: among rows that have a pitch only `high` (1,394,511) and `medium` (165,491) occur. `low` and `none` attach to rows with no pitch, where the field is now null, so they are redundant with `pitch_status`. On legato steps it is 98.7% `high` and gives no discrimination. About the *estimate*, not the note |
| `sample_id` | string | — | 16 hex chars, or **empty when no directory entry resolved** (13,680 events). Content identity of the decoded BRR audio — **not an instrument label** |
| `pitch_register` | int or null | raw | the **14-bit PITCH register value this event wrote**, alongside the derived `midi_note`. Published so a surprising pitch can be checked against the hardware value instead of taken on trust. A step's `midi_note` is derived as `parent.midi_note + 12·log2(step.pitch_register / parent.pitch_register)` |
| `attack_level` | int | — | `0..127`. `VOL` rescaled. **A register value, not perceived loudness** |
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
- **2,926 of the 154,910 legato steps do write their parent's exact pitch**
  (1.9%) — a driver rewriting the same PITCH value, typically alongside a
  volume change. That is real data. Before `v3` *all* 154,910 did, which was
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

| `stats` field | meaning |
|---|---|
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

Per-voice note trees with absolute times. Notes carry `start_sec`, `end_sec`,
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

| field | unit | meaning |
|---|---|---|
| `voices.max` | voices | largest voice count seen |
| `voices.mean` | voices | mean over all rendered time, silence included |
| `voices.mean_when_sounding` | voices | mean over time with at least one voice gated. **Read the two fields below before comparing this across games** |
| `voices.median_release_gap_ms` | ms | median silence between a key-off and the next key-on on one voice. **Near zero means the driver holds voices gated, so the gated count overstates audible density**: Breath of Fire 2 and Mega Man X sit at 1.05 and 1.18 ms against 27–49 ms elsewhere |
| `voices.gated_duty_cycle` | fraction | share of voice-time spent gated. **Approaching 1.0 means the gated measure is saturated and cannot discriminate**: the same two games sit at 0.96–0.97 |
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

## `splits.json`, `summary.json`, `provenance.json`, `RELEASE.json`

`splits.json` is the composer-disjoint train/valid/test assignment.
`summary.json` is corpus-level extraction statistics including the row-clock
census. Its `scores.max_distinct_pitched_notes_per_row` was published as
`max_polyphony` before `events.v3`; see the note it carries. `provenance.json` records the commit, cleanliness, interpreter and
platform that built the tree — and deliberately **no hostname or user**.
`RELEASE.json` pins a SHA-256 and byte count for every file; `verify.py`
checks the tree against it.
