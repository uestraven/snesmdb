# Changes to the published corpus

Changes to the **distributed artifact** — the shapes and fields a consumer
reads. Internal pipeline work is in [milestones.md](milestones.md).

Each published format carries its own schema version, because they move
independently. Check the version of the format you read, not a corpus
version.

| format | version | file |
|---|---|---|
| index | `snesmdb.index.v1` | `index.json` |
| events | `snesmdb.events.v1` | `events/*.json.gz` |
| intake | `snesmdb.intake.v1` | `intake/*.json.gz` |
| sample id | `snesmdb.sample.v1` | the `sample_id` field |
| uniform score | 100 Hz | the `uniform` block in `scores/*.json.gz` |

---

## `snesmdb.index.v1` — BREAKING: `index.json` is a document, not an array

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

## `snesmdb.events.v1` — new format

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
