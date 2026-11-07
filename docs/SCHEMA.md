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
| `onset_sec` | float | seconds | 0 to `duration_sec`, 6 dp (≈1 µs). Unquantised — taken from the event log, not from a grid |
| `duration_sec` | float or null | seconds | **null means the note was still sounding when the render window ended** (159,584 events), *not* zero length. All 154,910 legato steps are null: a step has no duration of its own |
| `voice` | int | — | `0..7`, the S-DSP hardware voice. **Not a fixed musical part** — assignment can change mid-track |
| `pitch_status` | string | — | `estimated`, `noise`, `pitch_modulated`, `unrecoverable`. **Only `estimated` is a pitch** |
| `midi_note` | float or null | semitones | null unless `pitch_status == "estimated"`. Fractional and **not clamped to MIDI's domain**: measured −34.16 to +131.09 |
| `pitch_confidence` | string or null | — | `high`, `medium`, `low`, `none` — about the *estimate*, not the note |
| `sample_id` | string | — | 16 hex chars, or **empty when no directory entry resolved** (13,680 events). Content identity of the decoded BRR audio — **not an instrument label** |
| `attack_level` | int | — | `0..127`. `VOL` rescaled. **A register value, not perceived loudness** |
| `sustain_level` | int | — | `0..127`. Where the envelope settles; differs from `attack_level` on 19.4% of notes |

### Reading it correctly

- **A pitch histogram** filters `pitch_status == "estimated"`. A missing
  `midi_note` is not a rest and not a zero.
- **Counting notes** filters `origin == "key_on"`. A legato step is a pitch
  change inside a note that is already sounding.
- **Counting simultaneous voices** counts distinct `voice` values active at a
  time, not rows. Include unpitched notes — percussion is a sounding voice.
- **Reassembling a phrase** groups steps on `parent_event_id`.
- `midi_note` outside `0..127` is real and must be filtered for MIDI work:
  776 events, 58 of them negative.

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
| `tracks` | one object per track; same fields as `tracks.csv` plus `midi_summary`, `uniform_hz`, `uniform_n_rows`, `checks_passed`, `sha256_source_spc`, and the relative paths `events`, `scores`, `intake`, `midi` |

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

Per-game performance conventions, keyed by **display name** (not slug).
`performance_music.json` restricts to `track_class == "music"`.

| field | unit | note |
|---|---|---|
| `voices.mean_when_sounding` | voices | mean count of voices gated on, over sounding time |
| `median_volume` | raw register | `|VOLL| + |VOLR|`, so the domain is `0..254` and values above 127 are normal — **not** the `0..127` scale `events` uses |
| `median_feedback` | raw signed register | echo feedback, `-128..127`; negative is normal |
| `phase_inverted_fraction` | fraction | share of notes with opposite-sign left and right volume |

## `splits.json`, `summary.json`, `provenance.json`, `RELEASE.json`

`splits.json` is the composer-disjoint train/valid/test assignment.
`summary.json` is corpus-level extraction statistics including the row-clock
census. `provenance.json` records the commit, cleanliness, interpreter and
platform that built the tree — and deliberately **no hostname or user**.
`RELEASE.json` pins a SHA-256 and byte count for every file; `verify.py`
checks the tree against it.
