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
| events | `snesmdb.events.v4` | `events/*.json.gz` |
| tracks | `snesmdb.tracks.v1` | `tracks.csv` |
| drivers | `snesmdb.drivers.v1` | `index.json` → `drivers` |
| intake | `snesmdb.intake.v1` | `intake/*.json.gz` |
| sample id | `snesmdb.sample.v1` | the `sample_id` field |
| uniform score | 100 Hz | the `uniform` block in `scores/*.json.gz` |

---

## `gate5-rc10` — sample identity corrected per attack

**Breaking.** `snesmdb.events.v4`. Read the compatibility section before
upgrading: two fields are added and one changes meaning in a way a v3 reader
will not notice.

### What was wrong

Every release up to `gate5-rc9` resolved a sample from the directory as the
SPC **captured** it, and mapped one identity per SRCN. The hardware does not
work that way. The S-DSP reads the directory entry when a voice is keyed on,
and drivers rewrite those entries while the music plays, so one SRCN can
address different audio at different moments in the same track.

Event-time instrumentation of the DSP — three hooks at the points where it
commits a sample start, accepts a key-on, and takes a loop — was run against
all **1,863,499** published attacks in the 22-game corpus, at 100% coverage:

| outcome | attacks | share |
|---|---|---|
| unchanged | 1,833,879 | 98.411% |
| no identity established (entry is unwritten memory) | 15,165 | 0.814% |
| identity corrected — different audio | 12,326 | 0.661% |
| identity established where none was | 1,941 | 0.104% |
| identity not establishable | 178 | 0.010% |
| identity corrected — loop point only | 10 | 0.001% |

**98.411% of the corpus is unchanged.** All change is confined to Super
Turrican, plus two attacks in one Tales of Phantasia track. No other game in
the corpus is affected.

The 15,165 attacks are the most important row. Their directory entry is
unwritten memory — `$FFFF` fill or address 0 — which still *decodes*: the
bytes are read, hashed, and become sixteen confident-looking hex digits.
`rc9` published those hashes as identities. They are now `null`.

### Field changes

| field | v3 | v4 |
|---|---|---|
| `sample_id` | `""` when unresolved | **`null`** when unresolved |
| `sample_id_source` | — | `observed_at_key_on`, `capture_time_directory`, or `unresolved` |
| `sample_id_unresolved_reason` | — | non-null exactly when `sample_id` is null |

### Compatibility implications

- **A reader testing `sample_id is not None` changes behaviour.** `rc9` used
  the empty string for 13,413 events and `null` for none, so such a reader
  previously counted 13,413 non-identities as identities. It now sees nulls.
  A reader testing truthiness (`if sample_id:`) was already correct and is
  unaffected.
- **Counts of distinct samples per track will fall** on affected tracks, as
  hashes of unwritten memory stop being counted as samples.
- **Joins on `sample_id` lose rows** where the identity is now null. This is
  the intended behaviour: the join previously succeeded against a value that
  did not identify a sample.
- **A legato step follows its parent's corrected identity.** A step does not
  re-key, so it sounds the parent's sample; its identity column moves with
  the parent's.
- `attacks_with_sample_id`, `attacks_without_sample_id` and
  `attacks_identity_observed_at_key_on` are added to each table header so
  the split is readable without scanning events.

### Publication policy

An identity the DSP observations do not establish is published as `null`
with a reason. It is **never** backfilled with a plausible-looking
substitute. Where the evidence establishes an identity, it is corrected;
where it does not, the record says so.

### What this release does not claim

- The BRR bytes at a confirmed address are read from the capture-time ARAM.
  That a sample's bytes were unchanged during playback is **not**
  established, and remains an open limitation.
- 10 attacks differ only in loop point. A note that never reaches a loop has
  no observable loop destination, so for those the loop component of the
  identity rests on the directory word present at key-on.
- `gate5-rc9` is preserved unchanged. Nothing in this release overwrites it.

---

## `gate5-rc7` — the third evaluation

Eleven findings, all documentation. **No corpus data changed**: every row-level
invariant and every published count held, and the evaluator reproduced roughly
twenty named figures to the unit, matched all 22 per-game voice maxima, and
recomputed every headline corpus count from the 1,316 event tables without
consulting `index.json`.

### The field I added last release to prevent this failed the same way

`gated_duty_cycle` shipped in `rc6` to make a confound visible in data rather
than prose. Its denominator — **the voices a track actually uses**, not 8 —
was not stated, and the natural `/8` reading gives errors up to 0.372. Under
that reading Plok! computes 0.588 and looks usable; the published value is
0.960 and it is not. A field added to stop a name promising more than it
measures did exactly that.

Stated now, along with the convention needed to reproduce the aggregates:
**`performance.json` extends a note with `duration_sec: null` to the end of
the render window** rather than dropping it. With both conventions an
evaluator reproduced the published statistics to a median 0.000027.

### A wrong range, published for three releases

`DATASET.md`'s row-duration cell read **"2.00–12.50 ms"**. Those were the two
example games quoted beside the table, printed as if they were the range, and
they contradicted the same table's own 32.8 Hz lower bound — 32.8 Hz is a
30.5 ms row. The true span is **2.000–30.500 ms, median 4.875**, and the
consequence matters: **341 tracks (25.9%) have a hardware row coarser than the
10 ms uniform grid** and 178 (13.5%) are coarser than 12.50 ms. A reader would
reasonably have concluded the hardware grid is always at least as fine as the
uniform one. A release check now compares the documented range against the
corpus.

### `onset_grid` was undocumented, and it is the grid rhythm work needs

The `rc3` rewrite of the row-grids section **deleted its documentation**,
leaving a field published in all 1,316 score files and described nowhere.
Onsets concentrate on it at **R = 0.937** against only 0.262 on the timer
clock, which runs a median 16.5× faster than the music. An evaluator measured
quantisation against `clock`, got 0.26, and nearly reported that this corpus's
onsets are barely quantised. Now documented in all three places, with why it
indexes no row and why that is a different question from whether it describes
the music.

### Corrections

- **The saturation criterion is a threshold, not a list.** Three games exceed
  `gated_duty_cycle` 0.95 — Breath of Fire 2 0.976, Mega Man X 0.972, **Plok!
  0.960** — where the prose named two and an evaluator excluded two and kept
  the third.
- **The gated-voice confound is corpus-wide**, not confined to those games:
  ρ = 0.703 against the gating habit versus 0.277 against an attack-based
  density, and the two definitions disagree on which of a pair of games is
  denser in 40% of pairs. A density comparison should report at least one
  definition independent of key-off timing.
- **The 1 µs rounding overshoot is not one voice.** Drivers key several voices
  on one tick, so a naive sweep reports **9 to 13** simultaneous voices on
  8-voice hardware, and Super Castlevania 4's true peak of 6 reads as 10.
  Means are unaffected; peaks are not. Three remedies are named, plus the
  requirement to process closes before opens at equal timestamps.
- **The 6-dp decimals are not exact in binary float64**, which manufactures
  about 3,640 phantom overlaps of ~1e-16 s on top of the documented 3,695.
  Threshold at 1 µs, or parse with `decimal.Decimal`.
- **`software_divisor_m` is a timer-to-write-cadence ratio, not ticks per
  musical row.** Values run 1–8 while the onset period is a median 16.5× the
  tick, so dividing by M still leaves rows several times finer than the music.
  The derivation always said so; the label did not.
- Legato steps repeating their parent: **4,164 match the PITCH register**, of
  which 2,926 have a recovered pitch at both ends. The published figure was
  the pitched subset.
- A register glossary heads the `performance.json` table — `VOLL/VOLR`,
  `EVOLL/EVOLR`, `EFB`, `EON/NON/PMON`, and the ADSR word layout.

## `gate5-rc6` — the second evaluation's findings

A second independent evaluation of `gate5-rc5` returned **READY WITH
LIMITATIONS** with thirteen findings. It also validated the previous round:
working from `SCHEMA.md` alone the evaluator reconstructed
`performance_music.json`'s per-game voice statistic to a **median error of
0.0079 voices across 22 games**, matched the published per-game maxima on
**22 of 22**, and agreed with the new `max_voices_sounding_per_row` on
**1,315 of 1,316 tracks** — the one exception being a 6.42 ms event both row
grids are too coarse to see.

### Data corrections

**`driver_tick_hz` is now null where the estimate was refused.** It published
the rejected value on all 1,316 tracks while the documentation beside it
promised "absent for 797" and "null, never 1, where unknown" — so a filter on
non-null returned 1,316 instead of 519 and admitted 797 refused estimates
with no error. Actraiser tracks with a 500 Hz timer carried 157.079 Hz. Each
intake record now also carries **`driver_tick_found`**, so the absence is
self-describing.

**`pitch_confidence` is null where there is no pitch.** 341 rows published
`pitch_status: unrecoverable` with a `high` or `medium` confidence —
confidence in a pitch that does not exist.

**`summary.json` no longer publishes `max_polyphony`.** The field the previous
release renamed survived under the old name in a file the extractor writes,
with no caveat, so a reader starting there could revive exactly the
misreading the rename was made to prevent. It now appears as
`max_distinct_pitched_notes_per_row` with a note.

**Index track rows carry `game_slug` and the three `driver*` fields.**
`SCHEMA.md` said a row held the same fields as `tracks.csv`; four columns were
missing, so a documented join by slug failed.

**New: `pitch_register` on every event** — the raw 14-bit PITCH value the
event wrote, beside the derived `midi_note`. The evaluator found deep, fast
pitch oscillations in the step table, could not determine whether they were
real driver sound design or a derivation artefact, and named this field as
what would settle it.

### A withdrawn claim

**The Capcom interval-safety instruction is withdrawn.** This documentation
said median deviation from a semitone ladder was "0.30 cents for Rare and
10.67 cents for Capcom" and concluded interval work "is not safe for Capcom".
Re-measured on the published corpus, **Capcom is 2.46 cents** and no driver
exceeds 2.5. The 10.67 figure predates the voice-seeding fix, which corrected
sample attribution for 148,422 notes — before it, notes from different samples
pooled into one group, which inflates ladder deviation exactly this way. A
researcher following the instruction would have excluded 77 sound Capcom
tracks. The full per-driver table now ships, with its method and its two
caveats.

### A confound now documented

**A gated voice is not an audible voice, and the gap is not uniform.** Breath
of Fire 2 and Mega Man X hold a median 1.1–1.2 ms between a key-off and the
next key-on on the same voice, against 27–64 ms elsewhere — a 50× spread — so
any gated-voice measure saturates for those two games for a reason that is not
musical. The evaluator nearly published a density comparison on that basis.
`performance.json`'s own voice statistic carries the same exposure, and this is
now stated where the measure is prescribed.

### Documentation corrections

- **`performance.json` is described at the right path and in full.** The
  previous page put the display-name keying at the top level and three of its
  four named fields at the wrong depth, so a reader's first script found zero
  games; and it documented 4 of about 25 fields. All of them now have a unit
  and a definition, including what `echo.n_sampled` counts.
- The `duration_sec: null` count is attached to the right clause: of 159,584
  nulls, **154,910 are legato steps and only 4,674 are truncated notes** — the
  figure overstated right-censoring by 34×.
- **`onset_sec` and `duration_sec` are rounded independently**, so a note can
  cross the next onset on its voice by exactly 1 µs; 3,695 pairs across 106
  tracks do. Documented, with how to handle it.
- `pitch_confidence` is **binary in practice** — only `high` and `medium`
  occur on rows that have a pitch.
- The timbre section was left **syntactically broken** by the previous
  release's own edit: an orphaned `**`, a sentence cut mid-clause, and an
  opening that still asserted a usable codebook. Rewritten.
- The pipeline diagram still showed the row clock being measured from write
  cadence and a timbre class being emitted. Neither happens.
- `README.md` said "78 rates"; there are 80. The `index.json` example still
  showed `events.v2`. "1.78% outside MIDI 12–108" is **1.730%**, which the
  same document already stated correctly elsewhere.
- `README.md` pointed at a per-game legato breakdown that is not in the
  distribution; replaced with the caveat that the share depends on the
  definition — 54.7% of chains against 10.7% of steps under one reading.
- The three figures near 1.458 million are now explained rather than left to
  look inconsistent: 1,458,211 pitched attacks, 1,458,115 placed on a row,
  1,458,120 MIDI note-ons. They reconcile exactly.

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
