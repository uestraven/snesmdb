# Changes to the published corpus

Changes to the **distributed artifact** — the shapes and fields a consumer
reads. Internal pipeline work is recorded in the project repository's build
log and is not part of this distribution.

Each published format carries its own schema version, because they move
independently. Check the version of the format you read, not a corpus
version.

| format | version | file |
|---|---|---|
| index | `snesmdb.index.v1` | `index.json` |
| events | `snesmdb.events.v3` | `events/*.json.gz` |
| tracks | `snesmdb.tracks.v1` | `tracks.csv` |
| drivers | `snesmdb.drivers.v1` | `index.json` → `drivers` |
| intake | `snesmdb.intake.v1` | `intake/*.json.gz` |
| sample id | `snesmdb.sample.v1` | the `sample_id` field |
| uniform score | 100 Hz | the `uniform` block in `scores/*.json.gz` |

---

## `gate5-rc5` — two fields now mean what they say

An independent researcher evaluated `gate5-rc3` using only the published
files and returned **READY WITH LIMITATIONS** with eleven findings. Two were
fields that did not mean what they said, and both failed silently: the data
was perfectly self-consistent, which is why 31 audit checks and 422 tests
missed them.

### `snesmdb.events.v3` — BREAKING, and deliberately so

**`midi_note` on a `legato_step` now carries the pitch the step wrote.** It
previously carried the *parent's* pitch — all 154,910 steps, maximum
difference exactly 0.0 — so the field defined as "a pitch change on a voice
that never re-keyed" contained no pitch change. That ruled out the format's
own advertised use (portamento and vibrato study) and made 7% of
`n_pitched_events` duplicate rows, inflating one game's pitch histogram by
1.39×.

The pitch is recovered from the raw registers the extraction records already
carried: `12 · log2(step.pitch / parent.pitch_register)` semitones above the
parent. Not from the step's `semitones` field, which is relative to the
*previous* write — steps chain, and the two readings disagree for most steps
in a chain.

**`event_id` is now a row key.** It previously held the *parent's* id on a
step, so ids were duplicated in **517 of 1,316 tracks** — up to 85% of one
track's rows sharing an id — and `parent_event_id == event_id` for all
2,018,409 rows. A routine `set_index("event_id")` or `drop_duplicates()`
discarded rows with no error. Ids are now unique within a track, and
**`parent_event_id` is null on a key-on** and the parent's id on a step,
which is what the README and this changelog already described.

**If you have results from `v1` or `v2`:** anything counting attacks, or
using only `origin == "key_on"`, is unaffected. Anything that read pitch from
legato steps, or keyed on `event_id`, must be recomputed.

`pitched_attack_count` is added per track and `n_pitched_attacks` to the
corpus block, so "how many notes have a pitch" no longer has to be derived
from a figure that mixes attacks and steps.

### `scores`: `max_polyphony` renamed

It was neither polyphony nor voices: it counted **distinct pitches** on a row,
among **pitched notes only**. Read as voice count it understated exact
concurrency on 571 of 1,006 music tracks (median +1, max +7) and reported
`1` for a Super Turrican track where eight voices sound — and `0` for three
Star Ocean tracks where six do. Now three explicit fields:

| field | meaning |
|---|---|
| `max_distinct_pitched_notes_per_row` | the old `max_polyphony`, honestly named |
| `max_pitched_voices_per_row` | voices holding a pitched note |
| `max_voices_sounding_per_row` | **voices holding any note — the voice count** |

Piano rolls contain pitched notes only and extend a never-released note to the
end of the render; both are now stated beside the fields.

### New: `SCHEMA.md`

A field-level reference for every published format — name, type, unit, range,
null semantics. The evaluator was directed to `events/*.json.gz` in bold by
two documents and had to *measure* the domains of `attack_level`,
`sustain_level`, `voice`, `pitch_confidence` and `duration_sec: null` before
using them. This was the single highest-value page missing from the package.

### New: `drivers` — the one curated field

Which audio engine each game used, in `index.json` → `drivers` and as three
columns in `tracks.csv`. **Curated external knowledge, not derived from the
SPC files and not verifiable from the corpus**, carrying its own caveat and a
`driver_confidence` of `documented` or `attributed`.

It ships because this documentation conditions substantive advice on the
driver in four places — which games are safe for interval work, the
envelope-strategy table, the clock-corroboration list, and the warning to
check a split's driver balance — and published no mapping, so none of it could
be acted on without the recipient supplying their own knowledge of SNES
publishers. Advice that cannot be acted on is worse than no advice.

### `intake` notes carry `sample_id`

They previously carried only `srcn`, which this changelog explicitly tells
researchers *not* to join on, with no path to a `sample_id` at all.

### Documentation corrections

- The instruction to use `timbre_class` as a tonal/percussive flag is
  **withdrawn**; the field is the constant `-1`, so a split computed from it
  partitions nothing. This was the one place where following the
  documentation produced a *false* result rather than an unclear one.
- MIDI counts corrected: **1,458,120** written, **402,635** dropped, **1,243**
  files (was 1,465,863 / 382,544 / 1,252, a triple that did not even sum).
- "78 distinct rates" → **80**. "78.7% of notes carry a note number" →
  **78.25%**.
- MIDI files are described as **nine chunks** (a conductor track plus eight
  voice tracks), not eight, with the channel-8 detail stated.
- Out-of-range pitch is now disclosed **per game** (0.30%–8.16%, a 27×
  spread) rather than only corpus-wide, and the fact that `midi_note` is not
  clamped to 0–127 is stated.
- A consolidated **known-issues list now ships** in `DATASET.md`, so a
  recipient can tell a discovery from a defect the authors already knew.

## `snesmdb.index.v1` — BREAKING: `index.json` is a document, not an array

*Earlier release. Listed after the newer entries above.*

`index.json` was a bare JSON array of track rows. It is now an object. **Any
consumer that loads it and iterates must change.**

```python
# Before
tracks = json.load(handle)

# Now
tracks = json.load(handle)["tracks"]
```

To accept either, which is what the published example workflows do:

```python
raw = json.load(handle)
tracks = raw if isinstance(raw, list) else raw["tracks"]
```

**No field inside a track row was renamed, moved or removed.** The contents of
`tracks` are exactly what the old array held, plus new fields. The break is
only in the top-level type — but that is a real break, and preserving the row
fields does not make it backward compatible.

### Why

A bare array cannot say what it is. Two downloads of different vintages were
distinguishable only by diffing them, and "how big is this corpus" required
reading 1,316 gzipped files. The document carries:

- `schema` — this index's own version, `snesmdb.index.v1`. Distinct from the
  per-format versions below: changing the index's top-level type is not a
  change to `events.v1`.
- `formats` — the schema of every format in the tree, so compatibility can be
  checked per format.
- `corpus` — corpus-level counts and censuses, so a summary needs no pass over
  the corpus: 1,316 tracks, 22 games, 2,018,409 events, 1,560,002 pitched,
  1,863,499 attacks.
- `tracks` — the former array.

### Added to every track row

| field | meaning |
|---|---|
| `track_class` | `music`, `jingle`, `effect`, `drone` — a MUSICAL label |
| `extraction_status` | a DATA-QUALITY statement; see below |
| `event_count`, `pitched_event_count`, `unpitched_event_count` | |
| `attack_count`, `legato_step_count` | an event is not an attack |
| `events` | path to the event table |

`track_class` and `extraction_status` are **independent and neither implies
the other.** 42 sound effects contain recoverable pitch; 11 music tracks
contain none. Filter a melodic study on `track_class`; judge data quality on
`extraction_status`; do not use either as a proxy for the other.

---

## `snesmdb.events.v1` — new format *(historical; see `v3` above)*

A flat, per-track event table in seconds: `events/*.json.gz`. **Start here.**
It replaces nothing; the scores, MIDI and intake trees are unchanged.

It exists because the previous artifacts required SPC700 knowledge to read
correctly. In particular, 405,288 events carried `midi_note: null` with no
stated reason, so percussion, hardware noise, a pitch-modulated voice and a
failed estimate were indistinguishable.

- `pitch_status` is one of `estimated`, `noise`, `pitch_modulated`,
  `unrecoverable`. Only `estimated` is a pitch. **It says `estimated`, never
  `measured`** — a fundamental is estimated from decoded BRR content, and
  `pitch_confidence` is a separate field because a confident estimate is still
  an estimate.
- `origin` is `key_on` or `legato_step`. A legato step is a pitch change on a
  voice that never re-keyed, so it is a sounded pitch but not a new note.
  Group on `parent_event_id` to reassemble a phrase.
- `attack_level` and `sustain_level` are **register-derived amplitude
  controls**, not perceived loudness, acoustic intensity, or standardised MIDI
  velocity.
- `sample_id` identifies decoded audio content reproducibly. It is **not an
  instrument label** and carries no claim of a consistent musical role: one
  Actraiser sample is used across 14 tracks spanning over five octaves.

## `snesmdb.sample.v1` — sample identity defined

`sample_id` is `SHA-256(b"snesmdb.sample.v1\0" + loop_offset + PCM as signed
16-bit LE)`, truncated to 16 hex characters. The loop offset **is part of the
identity**: identical audio with different loop points sounds different when
held, so the two are not the same sample.

Use this, not `srcn`, to join across tracks. An SRCN is an ARAM directory
index and does not name a fixed sample even within one game — Super Turrican's
8 indices resolve to 48 distinct samples across its 12 tracks.

## `gate5-rc3` — redundancy for the fields you filter on

Prompted by a defect report. A copy of `gate5-rc2` reached an evaluator with
`index.json` truncated mid-string by a short write at a 768 KiB boundary. The
corpus data was perfect — every per-track file was byte-identical to its
frozen hash — but `game` and `track_class` lived in `index.json` and **nowhere
else**, so 44% of tracks lost both, and `track_class` was unrecoverable from
any other published file. The only field still available was
`extraction_status`, which this documentation explicitly tells researchers not
to use as a proxy for it.

The transfer was at fault, not the release. The design was still wrong: a
field researchers are instructed to filter on must not have a single point of
failure.

### `snesmdb.events.v2`

`game`, `game_slug` and `track_class` are now in every event table's header.
**Purely additive** — nothing renamed, moved or removed. The version is bumped
anyway, because the version exists so a consumer can tell which fields to
expect, and two trees both claiming `v1` while carrying different fields is
the silent incompatibility versioning is meant to prevent.

**What this does and does not break.** Every field a `v1` reader accesses is
unchanged, so code that reads fields keeps working. But a reader that tests
the schema string for *equality* with `snesmdb.events.v1` will reject these
tables — this project's own example script did exactly that and had to be
fixed. If you pin the version, add `snesmdb.events.v2` to the set you accept;
accepting every version you know is the more durable pattern.

### `snesmdb.tracks.v1` — `tracks.csv`

The per-track metadata as one line per track: `track_id`, `game_slug`, `game`,
`title`, `composers`, `track_class`, `extraction_status`, `split`,
`render_seconds`, `n_notes`, and the four event counts. A truncated CSV loses
its tail and keeps every complete line; a truncated JSON document is
unparseable in full.

### `index.json` gained a `games` block

Slug to game name. The slugs are not guessable — `mo2` is Earthbound (Mother
2), `sd2` is Secret of Mana (Seiken Densetsu 2), `ed2` is Lufia 2, `dkq` is
Donkey Kong Country 2 — and an evaluator who needed the mapping had to
reconstruct it by matching per-game track counts, then break a tie between two
66-track games from their clock rates. It should never have had to be
inferred.

### Documentation corrections

`DATASET.md`'s microtiming section told researchers to use `records/*.json`
and `raw/*.jsonl.gz`, describing them as "preserved and published". **Neither
is in the distribution**: `records/` is intermediate build output and `raw/` is
the compressed-log form this project's distribution rules exclude. The section
now points at `events/*.json.gz`, which carries the same onsets in seconds to
microsecond resolution and was always the right answer. The `axe-03`
quantisation example pointed at the same two absent trees; both of its notes
are in `events/axe-03_*.json.gz` as `event_id` 940 and 941, 5.106 ms apart.

References to the project's build log as the authoritative defect list have
also been removed from the distributed documents, since that log is
deliberately not distributed.

### A verifier now ships

`verify.py` at the package root re-hashes every file against
`dist/RELEASE.json`. A recipient previously had no supplied way to tell a
damaged transfer from a damaged release, and distinguishing those is a
one-command question.

## Documentation correction, `gate5-rc2`

No data or schema changed between `gate5-rc1` and `gate5-rc2`. The documents
did.

`README.md` and `DATASET.md` described the uniform score as **60.0988 Hz**,
attributing that rate to NES-MDB, in a passage recommending it for cross-game
comparison. The published rate is and was **100 Hz**. 60.0988 Hz is the NES's
NTSC *video* frame rate, NES-MDB's scores are 24 Hz, and `DATASET.md`
contradicted itself by stating 10 ms elsewhere. **If you read either document
at `gate5-rc1`, re-read the uniform-score section.** The data was correct
throughout; only its description was wrong.

Also corrected at rc2: stale tool counts, and an imprecise description of
`timbre_class` as simply "published", which is now located per format — it is
absent from `events.v1` and present as an inert `-1` in the score and intake
trees.

## Uniform 100 Hz scores

`scores/*.json.gz` gained a `uniform` block: the three score formats on a
fixed 100 Hz grid, so a row means the same thing in every track. Use it for
anything that compares tracks or games; the primary score is indexed on each
driver's own timer tick and its rate differs per track.

Known quantization limit: the 100 Hz grid loses one repeated-note attack among
1,458,211 pitched events — in Axelay, track `axe-03`, where two successive
same-pitch attacks fall about 5.1 ms apart. The original event timestamps
preserve both.

## Not published

`timbre_codebook.json` and `timbre_assignments.json`. The clustering failed its
own cross-game validation, and `timbre_class` is `-1` for every note. Shipping
them would invite a join this project has documented as not transferable.
