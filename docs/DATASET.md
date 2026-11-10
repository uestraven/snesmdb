# SNES-MDB — what this corpus is, where it came from, and where it is wrong

Symbolic SNES music extracted from SPC files by emulating the SPC700 and
logging every DSP register write. The counterpart to NES-MDB, built because no
SNES equivalent has been published.

**1,316 tracks · 22 games · 1,863,499 notes · 109,263 rendered seconds.**

---

## Provenance, and what is not here

Extracted from SPC sets published by **snesmusic.org**. Their terms are
narrower than NES-MDB's research licence: the files are copyrighted by their
owners and offered "for educational and personal non-profit use only", "as fair
use samples for preservation purposes only".

Consequently:

- **No SPC files are distributed here**, and none are in the source repository.
- Everything in this tree is **derived data** plus the tools to regenerate it
  from SPCs you obtain yourself.
- Treat it as `use_class: research_only`. It is not cleared for a product.

Every record carries the **SHA-256 of the SPC it came from**, so any row can be
traced to its source and the extraction reproduced. The extractor is
deterministic: same SPC, same output.

Per-track metadata — title, game, composers, date — comes from the **ID666 tag
inside each SPC**, not from scraping. The archive credits a composer per *set*;
the tag gives one per *track*.

## How it was made

```
SPC ─► emulate SPC700, log every DSP write ─► per-voice note events
         (blargg's snes_spc, unpatched; hook via its own macro)
     ─► decode each BRR sample from ARAM, estimate f0 ─► note numbers
     ─► read the SPC700 timer registers the SPC carries ─► the row clock
     ─► (also: estimate the driver's write cadence, published where it
         passes its own plausibility check, and used for nothing else)
     ─► (also: fit a period to onsets, reported but not used for rows)
     ─► emit

An earlier version of this diagram showed the row clock being *measured from
write cadence* and a *timbre class* being emitted. Neither is what happens:
the clock is read from the `$F1`/`$FA`–`$FC` registers, and the timbre
clustering failed its own validation and ships nothing.
```

No step identifies the driver. Nothing game-specific enters the pipeline, and
**zero unhandled DSP registers** occur across all 22 games — which is the claim
the corpus exists to support, tested against Square's AKAO, Nintendo's N-SPC,
Konami, Capcom, Rare, Chunsoft, HAL, tri-Ace, Namco, Factor 5, Software
Creations and Quintet.

Render length per track comes from the ID666 "seconds to play" field, not a
fixed window. A flat 60 s captured 8.8% of Final Fantasy VI's 683-second
"Dancing Mad (Full)" and truncated 68 of its 82 tracks.

## What is in the tree

| path | contents |
|---|---|
| `index.json` | the manifest: its own schema, each format's schema, corpus-level counts, the slug→game map, and one row per track |
| `tracks.csv` | the same per-track metadata, one line per track — use this if `index.json` is unavailable or damaged |
| `events/*.json.gz` | **start here.** The flat event table, in seconds, pitched and unpitched |
| `scores/*.json.gz` | the three score formats, plus the row clock and the onset grid |
| `midi/*.mid` | 8-track type-1 MIDI, one track per DSP voice |
| `intake/*.json.gz` | per-voice note trees with absolute times |
| `splits.json` | composer-disjoint train/valid/test assignment |
| `summary.json` | corpus-level extraction statistics, including the row-clock census |
| `provenance.json` | the commit, dirty flag and parameters that built this tree |
| `performance.json` | per-game performance conventions, over all tracks |
| `performance_music.json` | the same, restricted to `track_class == music` |

### `index.json`

```json
{
  "schema": "snesmdb.index.v1",
  "formats": {"events": "snesmdb.events.v3", "intake": "snesmdb.intake.v1",
              "sample_id": "snesmdb.sample.v1", "uniform_hz": 100.0,
              "tracks_csv": "snesmdb.tracks.v1"},
  "corpus": {"n_tracks": 1316, "n_games": 22, "n_events": 2018409,
             "n_pitched_events": 1560002, "n_attacks": 1863499,
             "track_classes": {"music": 1006, "jingle": 233,
                               "effect": 60, "drone": 17},
             "extraction_statuses": {"complete_with_pitched_events": 1243,
                                     "complete_unpitched_only": 56,
                                     "complete_no_events": 17}},
  "games": {"actr": "Actraiser", "mo2": "Earthbound", ... },
  "tracks": [ ... ]
}
```

Each format is versioned **separately**, because they move separately: the
event table reached `v2` while the score payload was unchanged. Check the
format you read, not a corpus version.

### Track ids and game slugs

A track id is `<slug>-<number>:<hash>`. The slug names the game and **is not
guessable from it** — `mo2` is Earthbound (Mother 2), `sd2` is Secret of Mana
(Seiken Densetsu 2), `ed2` is Lufia 2, `dkq` is Donkey Kong Country 2. The
mapping is published in `index.json` under `games`, in `tracks.csv` as
`game_slug`, and in each event table's header, so it never has to be inferred:

| slug | game | slug | game |
|---|---|---|---|
| `actr` | Actraiser | `mo2` | Earthbound |
| `axe` | Axelay | `mmx` | Megaman X |
| `bof2` | Breath of Fire 2 | `plok` | Plok! |
| `br` | Batman Returns | `scv4` | Super Castlevania 4 |
| `ct` | Chrono Trigger | `sd2` | Secret of Mana |
| `dkc` | Donkey Kong Country | `sm` | Super Metroid |
| `dkq` | Donkey Kong Country 2 | `smw` | Super Mario World |
| `dq5` | Dragon Quest 5 | `so` | Star Ocean |
| `ed2` | Lufia 2 | `top` | Tales of Phantasia |
| `ff6` | Final Fantasy 6 | `turr` | Super Turrican |
| `kss` | Kirby Super Star | `loz3` | Legend of Zelda: A Link to the P |

Game names come from the SPC files' ID666 tags and inherit their 32-character
limit, which is why Zelda's is cut short.

### No field lives in only one file

`game` and `track_class` appear in `index.json`, in `tracks.csv`, **and** in
every event table's header. The duplication is deliberate. The documentation
tells you to filter a melodic study on `track_class`, and for a while that
field existed in exactly one file — so a single damaged manifest made the
instruction impossible to follow and left only `extraction_status`, which is
the proxy this document explicitly tells you not to use. A field researchers
are directed to filter on should not have a single point of failure.

`tracks.csv` exists for the same reason in the other direction: a truncated
JSON document is unparseable in its entirety, while a truncated CSV loses its
tail and keeps every complete line before it.

Every track row carries both `track_class` (`music`, `jingle`, `effect`,
`drone`) and `extraction_status`, and **neither can be derived from the
other**. 42 sound effects contain recoverable pitch; 11 music tracks contain
none. Filter a melodic study on `track_class`; judge data quality on
`extraction_status`; do not use one as a proxy for the other. Event counts are
on the row too, so a corpus-wide census needs no pass over 1,316 files.

**`timbre_codebook.json` is deliberately not published.** The milestone 5
codebook failed its own validation -- class agreement across games falls to the
shuffled null once the leaking features are removed -- and `timbre_class` is
written as `-1` for every note in this corpus rather than offering a number
from it. Shipping the file would invite a consumer to use a clustering this
project has documented as not transferable. The analysis and the negative
result are in the project's build log, `docs/milestones.md`, which lives in
the repository and is not part of this distribution; the artifact carries
neither the codebook nor a usable class.

### The three score formats

| format | shape | NES-MDB analogue |
|---|---|---|
| `separated` | 8 tracks × rows, cell = MIDI note or 0 | `sepsco` |
| `blended` | rows × sorted distinct notes, voices merged | `blndsco` |
| `expressive` | 8 tracks × rows, cell = (note, velocity, timbre class) | `exprsco` |

**`separated` keeps voice identity but that identity means less than the NES
equivalent.** On the NES, track 0 is always pulse 1. Here, voice 0 is whatever
the driver assigned it to, and the assignment can change mid-song. `blended` is
immune to this and is the more comparable format.

## Splits

Composer-disjoint, with the **whole game** as the unit of assignment.

| split | tracks | share | requested |
|---|---|---|---|
| train | 1,049 | 79.71% | 80% |
| valid | 135 | 10.26% | 10% |
| test | 132 | 10.03% | 10% |

16 components, no composer spanning a split. A game is indivisible because its
tracks share an instrument bank, a driver and an idiom — splitting one leaks
more than splitting a composer would.

**The splits are composer-disjoint; they are NOT driver-balanced.** At a
previous corpus size every AKAO and N-SPC track landed in `train`. Check the
driver distribution before concluding anything from `valid` or `test`.

Composers are matched as **individual people**, not raw tag strings: a field
crediting "Masanori Adachi, Taro Kudou" links to any game crediting either, or
disjointness would pass on a technicality.

---

# Limitations

## How to compare across games without flattening them

Three axes get confused, and they do not have the same standing.

| axis | status in this corpus | safe as a covariate? |
|---|---|---|
| **game genre** | not published; would be curated external knowledge, like `driver` | yes, once labelled and marked as curated |
| **musical function** | partly available — `track_class` separates music / jingle / effect / drone, and `title` often names a role | yes, with the caveat that finer roles are judgement |
| **musical style** | not published, and **not a covariate** | **no** |

**Style is the thing under study, not a control for it.** If style labels come
from someone listening, then grouping by style and then reporting stylistic
differences measures the labeller as much as the music. Genre and function are
properties of the *release* and can be established independently; style is an
outcome. Classify on the first two, compare the third.

### Choose a statistical unit deliberately

This corpus is not balanced, and pooling over tracks hides that:

| | |
|---|---|
| music tracks | 1,006 across 22 games |
| largest single game | **Earthbound, 13.8%** |
| top three games | 28.5% |
| tracks per game | 17 to 139, an **8× spread** |
| credited composers | 37, **many-to-many** — Earthbound's three each appear on all 139 of its tracks |

A per-track pooled mean therefore weights each game by how many tracks it
happens to contribute, which is a fact about what was collected rather than
about SNES music. **Report the unit you used.** `index.json` →
`composition` publishes the full per-game and per-composer counts so a figure
can be weighted, recomputed per game, or qualified. `claims.json` records a
`unit_of_analysis` for every registered claim for the same reason.

Composer-level work needs one further caution: credits are many-to-many and
truncated at 32 characters by the source tags, so one Earthbound credit
appears as `Ke`. Composer-pooled counts sum to more than the track total.

### No corpus-wide figure here generalises

22 games out of roughly 700 commercial SNES titles, weighted toward JRPGs and
first-party releases, with 13.8% from a single game. **Every corpus-wide
statistic in this documentation is descriptive of the collected sample.** It
is not a universal SNES musical convention, and `claims.json` marks every
registered claim `generalises_beyond_corpus: false` rather than leaving that
to be inferred. Three independent evaluations each reached the same limit
unprompted; the honest fix is a broader corpus, not a stronger adjective.

## Known issues, consolidated

Every defect the authors know about, in one place, so a recipient can tell a
discovery from a known problem. The project's full build log is not
distributed; this list is, and it is the authoritative one for the artifact.

| issue | status |
|---|---|
| No cross-game instrument vocabulary; `timbre_class` is the constant `-1` and no codebook ships | **known, unresolved.** Milestone 5 failed its own validation; see "The timbre axis" below |
| `srcn` does not name a fixed sample across a game's tracks | **by design.** Join on `sample_id` instead |
| The 100 Hz uniform grid loses one repeated attack in 1,458,211 pitched notes | **known, quantified.** `axe-03`; original timestamps keep both |
| 21.75% of notes carry no pitch, and out-of-range pitch varies 27× by game | **known, disclosed above** |
| The intake schema is not verified against its intended consumer | **known, flagged** in its own section |
| A row is a hardware timer tick, not always a musical row; `software_divisor_m` is recoverable for only 403 tracks | **known, disclosed** |
| Composer credits truncate at 32 characters in the source tags | **known, flagged per track** |
| 24 tracks extract no events at all (17 drones, 7 effects) | **known, classified** |
| Echo and pitch modulation are effectively unused by these games | **measured, not a defect** |

Fixed in `snesmdb.events.v3` after an independent evaluation, and listed here
because earlier downloads carry them: legato steps published their parent's
pitch rather than their own, and `event_id` was not unique within a track.
Both are corrected; see [CHANGELOG.md](CHANGELOG.md).


Read this section before using the data. Everything here was measured.

## Pitch is usable in bulk, unreliable per note

**78.25% of notes carry a note number.** The rest are percussion, noise,
or samples whose fundamental was not recoverable — labelled unpitched rather
than given a confident wrong number.

**Out-of-range pitch is not uniform across games.** 1.730% of pitched attacks
fall outside MIDI 12–108 corpus-wide, but per game that runs from **0.30% to
8.16%** — a 27× spread, so a per-game study must budget for its own game:

| worst | | best | |
|---|---|---|---|
| Breath of Fire 2 | 8.16% | Zelda: A Link to the Past | 0.30% |
| Super Mario World | 7.84% | Final Fantasy 6 | 0.30% |
| Secret of Mana | 3.78% | Super Turrican | 0.31% |
| Earthbound | 3.46% | Axelay | 0.38% |

**`midi_note` is not clamped to MIDI's domain at all.** A small number of
values fall outside 0–127, including negatives. They are real estimates of
very low or very high fundamentals, they are harmless if filtered and
silently corrupting if not, and the exact counts are in
[SCHEMA.md](SCHEMA.md).

**1.730% of pitched notes land outside MIDI 12–108**, down from 9.1%.
Both estimators are ambiguous by factors of two — autocorrelation can latch
onto twice the period, and the loop refinement's integer period count preserves
whatever octave it was handed — so the octave is resolved against the spectrum
instead: a fundamental an octave too low carries almost no energy at its own
first harmonic. Measured over 179,763 notes, out-of-range fell from 9.11% to
1.96%, against **16.42% for a control that shifted by a random octave**, and
the chosen shifts concentrated at −1 (328 of 356), which is the estimator's
known failure mode rather than a spread of fitted values. An independent check
that touches neither the spectrum nor the in-range test agrees: the span of
simultaneously sounding pitches tightened from 34.1 to 29.8 semitones while the
random control widened it to 41.5.

Two caveats. 237 samples that were already fully in range were also moved, and
the in-range metric cannot adjudicate those; the harmonic-energy margin on
moves is median 2.43× with 77% clearing 1.5×, so roughly a quarter are
marginal. Every estimate carries `octave_shift` and `octave_margin` so a
consumer can see what was moved and on what evidence, and every note carries
`pitch_confidence`.

**Relative pitch within a sample is good everywhere, and the earlier claim to
the contrary was stale.** Median deviation from an exact semitone ladder, per
sample, measured on the published corpus over sample groups with at least 8
notes, with a free offset:

| driver | cents | | driver | cents |
|---|---|---|---|---|
| Factor 5 | 0.33 | | AKAO-derived | 0.46 |
| Software Creations | 0.33 | | Konami | 0.47 |
| AKAO (Square) | 0.34 | | Quintet | 0.74 |
| Chunsoft | 0.37 | | N-SPC (Nintendo) | 0.77 |
| Rare | 0.39 | | Neverland | 1.57 |
| | | | Capcom | **2.46** |

An earlier version of this document reported **10.67 cents for Capcom** and
concluded that *"interval-level work is safe for Rare and Square and is not
safe for Capcom"*. **That instruction is withdrawn.** The figure predates the
voice-seeding fix described below, which corrected sample attribution for
148,422 notes: before it, notes belonging to different samples were pooled
into one sample group, which inflates ladder deviation exactly this way and
hit Capcom hardest. Re-measured, Capcom is 2.46 cents — below the ~5-cent
threshold at which melodic intervals are generally distinguishable — and no
driver in the corpus exceeds 2.5.

An independent evaluator could not reproduce the 10.67 figure, measured 2.69
cents by their own method, and found that under a different reading the
ranking inverted. They were right to report it.

**The table is per DRIVER, which pools that driver's games.** Capcom's 2.46
cents is the median over Mega Man X and Breath of Fire 2 together; computed
per *game*, the worst in the corpus is **Mega Man X at 4.06 cents** — still
below the ~5-cent threshold, but a different number, and a replication of
this table failed on exactly that unstated choice before it was written down
here. Both figures are registered in `claims.json`.

Three cautions on this table. It groups by `sample_id`, so it measures
**relative** pitch within one sample and says nothing about absolute tuning,
which remains unreliable. And it is keyed on `driver`, which is
[curated external knowledge](SCHEMA.md) rather than anything measured from
the SPC files — so read it as a hypothesis about engines, not a result.

## Voice state is seeded from the SPC snapshot

An SPC is a dump of a running system, so its DSP register block already holds
the voice parameters the driver set up before the dump — and a driver has no
reason to rewrite a register whose value is already right. Super Mario World's
"Athletic" writes only KON, KOFF, VOL and PITCH for its entire length, never
SRCN, ADSR1, ADSR2 or GAIN.

Extraction originally started every voice register at zero and tracked only
observed *writes*, so anything untouched read as 0. Measured effect of seeding
from the snapshot instead:

| | before | after |
|---|---|---|
| notes reporting `srcn = 0` | 200,515 (10.8%) | 52,093 (2.8%) |
| distinct samples referenced | 7,887 | 8,168 |
| high-confidence f0 estimates | 5,303 | 5,447 |
| implausible PITCH registers | 26,059 | 25,224 |
| sample estimates needing an octave shift | 44.58% | 42.83% |
| tracks reporting a silent envelope | 540 | 0 |

**SRCN changed for 148,422 notes (8.0%) across 619 tracks.** Since f0 is
estimated from the BRR sample at SRCN, each of those was previously pitched
against the wrong sample and assigned the wrong timbre class — "Athletic" has a
snapshot SRCN of `[10,10,10,10,11,8,2,8]` and all 1,164 of its notes were
recorded as sample 0. Worst affected: Super Turrican (100% of its notes),
Dragon Quest 5 (41%), Breath of Fire 2 (37%), Earthbound (30%), Mega Man X
(24%).

Pitched-note coverage fell slightly, from 78.7% to 78.25%, because some of the
newly-correct samples fail the f0 plausibility test that the wrong ones passed.
Fewer and right beats more and wrong.

## The row-rate decision, recorded

**snesmdb uses a 100 Hz uniform score grid as a deliberate analytical
convention.** The rate was selected by empirical evaluation of event
preservation, timing accuracy and storage cost on SNES music. **It does not
represent a universal SNES sequencer frequency** — no such frequency exists;
every driver programs its own timer.

The primary timer-derived grid and the original timestamped event records
remain available for hardware-oriented analysis and higher-resolution
reconstruction.

**100 Hz is not claimed to be optimal for all future SNES recordings.** It is
the best-supported choice among the candidates measured, on the corpus as it
stands. `tools/rate_benchmark.py` reruns the comparison, and
`make verify` re-checks the preservation claim on every rebuild, so the figure
cannot quietly rot as the corpus grows.

### What the benchmark measured

22-game cohort: **1,458,211 pitched notes across the 1,243 cohort tracks that contain
one**, of 1,316. The 405,288 unpitched notes are excluded, and that is the
exact coverage of the claim — an unpitched note carries no note number and so
never enters a piano roll in any format, at any rate.

| rate | exact divisor | events lost | repeat attacks | collisions | notes < 1 row | onset median / p95 |
|---|---|---|---|---|---|---|
| 50 Hz | yes | **94** | 67 | 27 | 0.74% | 4.94 / 9.5 ms |
| **100 Hz** | **yes** | **1** | **1** | **0** | 0.14% | 2.49 / 4.7 ms |
| 200 Hz | yes | **0** | 0 | 0 | 0.03% | 1.26 / 2.4 ms |

**100 Hz loses exactly one event in 1,458,211, and 200 Hz loses none.** So the
price of the rate is one note: doubling to 200 Hz recovers a single attack, at
twice the rows and storage. That is the whole argument, and it is now a known
quantity rather than a bound.

### Three similar totals, and how they relate

The documents use three figures near 1.458 million, and they are different
quantities rather than an inconsistency:

| figure | what it is |
|---|---|
| **1,458,211** | pitched note attacks — the benchmark denominator |
| **1,458,115** | of those, placed on a score row (−91 out of range, −5 unplaced) |
| **1,458,120** | MIDI note-ons written (the 91 out-of-range are dropped) |

An evaluator checked the arithmetic and nearly reported them as a defect; they
reconcile exactly, and the documents had never said so.

## Known quantisation limitation

> The 100 Hz uniform grid loses one repeated-note attack among 1,458,211
> pitched events in the evaluated corpus. The affected passage occurs in
> Axelay, track `axe-03`, where two successive same-pitch attacks are separated
> by approximately 5.1 ms. The second attack merges into the first at 100 Hz
> but remains distinguishable at 200 Hz. Original event timestamps preserve
> both.

Named precisely because a loss that more resolution *cannot* fix would mean
something different — a representation limit rather than quantisation. This one
is plain quantisation.

| | |
|---|---|
| track | `axe-03` — Axelay, "Unkai" |
| notes | voice 5, both MIDI 98.998, `srcn` 1, `event_id` 940 and 941 |
| gap | 5,228 ticks = **5.1055 ms** |

Two consecutive same-pitch attacks 5.1 ms apart, a retrigger around 196 Hz. At
100 Hz a row is 10 ms, so both land on one row and the second attack is
rewritten as duration. At 200 Hz the rows are 5 ms and they separate, which is
why the loss disappears there and nowhere beyond.

**Both notes are present in this distribution**, in
`events/axe-03_*.json.gz`, as two separate `key_on` events 5.1 ms apart. Only
the 100 Hz uniform score drops the second attack. (Earlier versions of this
document pointed at `records/` and `raw/` here, which are not distributed; the
event table carries the same timestamps to microsecond resolution.)

Two figures in this section were wrong before being measured directly, and the
corrections are kept because the pattern is instructive. A 296-track sample
reported "100.000% preserved" — rounding — so the claim is now a count. And
"200 Hz loses the same one" was inferred from a table rounding to 0.000%,
never measured; it loses none.

**Repeated attacks are counted separately from collisions** because the losses
differ in kind. A collision drops a note. A lost repeated attack silently
rewrites rhythm as duration — a tremolo or drum roll becomes one sustained
note — which nothing downstream would detect by counting notes. At 24 Hz, the
rate first considered for NES-MDB comparability, that loss is 174 events.

### For microtiming, do not use the score

Even at 100 Hz a row is 10 ms, and onsets move by 2.49 ms at the median and
4.7 ms at p95. Durations under 10 ms cannot be represented at all (0.14% of
notes). **Anyone studying expressive microtiming should use unquantised
times, not reconstructed score rows.** In this distribution those are:

- `events/*.json.gz` — `onset_sec` and `duration_sec` in seconds to six
  decimal places, about 1 µs, taken straight from the event log and never
  placed on a grid. **This is the one to use.**
- `intake/*.json.gz` — the same absolute times arranged per voice

**Not in this distribution**, and named here because earlier versions of this
document wrongly listed them as published:

- `records/*.json` — notes with `start`/`end` in raw SPC700 clocks, one tick
  being 0.00098 ms. Intermediate extraction output; it stays in the build
  tree (`data/out/`) and is not distributed.
- `raw/*.jsonl.gz` — the full timestamped DSP register write log. Not
  distributed either: it is the compressed-log form that this project's own
  distribution rules exclude.

Both can be regenerated from SPC files you supply yourself, using the tools in
the project repository. Neither is needed for microtiming work: `events`
preserves the same onsets to microsecond resolution.

The event log is the authoritative representation. Both score grids are
derived, lossy views of it, and the uniform grid is additionally a convention
rather than a measurement.

## Two row grids: the driver's, and a uniform one for comparability

Each score file carries **two** sets of the three formats.

| | primary | `uniform` |
|---|---|---|
| row rate | this SPC's timer tick | **100 Hz, every track** |
| row duration | **2.000–30.500 ms**, median 4.875, 80 distinct rates | **10.00 ms, always** |
| rows per music track (median) | 18,751 | **9,601** |
| what it is | a hardware measurement | a convention, stated as one |
| use it for | anything about this driver | comparing tracks or games |

### A known MIDI discrepancy, preserved rather than silently corrected

MIDI note numbers span 0–127. The exporter that produced the MIDI files in
these releases gated on `1..127`, an off-by-one that discarded **note 0 — a
valid note** — for **four attacks** in Earthbound `mo2-133:dbaac376f5db`
(`midi_note: -0.0595`, which rounds to 0).

The bound is fixed in the toolkit, and the frozen MIDI files are **not**
re-exported. The published `mo2-133` file contains 472 note-ons; the
corrected rule would write 476.

| | |
|---|---|
| in `events/*.json.gz` | **present** — all four attacks, with their pitch |
| in `midi/*.mid` | **absent** — this release ships the superseded export |
| corrected behaviour | available in `toolkit/`; applies to any re-export |

Replacing the MIDI files here would change the dataset under cover of a
packaging release. The discrepancy is bounded, attributed and now stated, so
a researcher comparing `events` against `midi` can account for it. Any
re-export belongs to an explicitly versioned data release, not to this one.

### MIDI is a fixed-pitch projection of the authoritative events

`events/*.json.gz` is authoritative. `midi/*.mid` is a **projection of the
subset of attacks carrying a usable fixed-pitch estimate**, and it is lossy
by design rather than by defect.

Over the 27-game release, every one of the 2,041,091 attacks is accounted
for — the ledger reconciles exactly:

| disposition | attacks | share |
|---|---|---|
| written to MIDI | 1,606,517 | 78.71% |
| omitted, no usable fixed-pitch estimate | 434,487 | 21.29% |
| omitted despite a fixed-pitch estimate | **87** | 0.004% |

**What the 434,487 are not.** They are not established to be unpitched
sounds. The published `pitch_status` says only what the pipeline could
determine:

- **`unrecoverable`** (433,493) — the pipeline could not determine a pitch.
  Some of these sounds may well have been pitched.
- **`pitch_modulated`** (727) — may be musically pitched material whose
  changing pitch a single static MIDI note cannot represent.
- **`noise`** (267) — genuinely lacks a fixed melodic pitch.

So the correct reading is that **no additional recoverable fixed-pitch
omissions have been demonstrated**. These rows preserve uncertainty instead
of resolving it, and writing a MIDI note for them would fabricate a pitch
the data explicitly declines to assert. For anything in this category, read
`events.v4`.

**The 87 are recoverable and are not hidden.** Their pitch was estimated but
falls outside MIDI's 0–127. Some are genuine extremes; some are residual
octave errors in fundamental estimation, which is a pitch-estimation
question rather than a MIDI one. They stay visible as their own category
rather than folding into "unpitched".

**78 tracks have no MIDI file**, covering 2,795 attacks. All 78 are
`complete_unpitched_only` or `complete_no_events`, and none has a pitched
attack, so no exportable musical content is missing. An empty MIDI file
would have been more misleading than none.

**One published counter does not reconcile, and is left as published.**
`midi_notes_dropped` counts attacks rejected while converting a track that
*does* get a file; it never covered bad-voice rejects or the 2,795 attacks
in file-less tracks. Rather than silently redefine a metric that has
shipped, `midi_attacks_rejected_in_conversion`,
`midi_tracks_without_file` and `midi_attacks_in_tracks_without_file` are
published alongside it, and together they account for every attack.

### Three statistical populations

This corpus has shipped as three distinct populations. A figure quoted
without naming one of them is unattributable.

| population | games | tracks | attacks | identity | pitched |
|---|---|---|---|---|---|
| 22-game frozen cohort | 22 | 1,316 | 1,863,499 | 99.18% | 78.25% |
| 5-game expansion | 5 | 161 | 177,592 | 99.91% | 83.56% |
| 27-game combined | 27 | 1,477 | 2,041,091 | 99.24% | 78.71% |
| 13-game expansion | 13 | 362 | 596,517 | 100.00% | 82.55% |
| 40-game combined | 40 | 1,839 | 2,637,608 | 99.42% | 79.58% |
| 10-game expansion | 10 | 389 | 567,853 | 100.00% | 76.92% |
| **50-game combined** | **50** | **2,228** | **3,205,461** | 99.52% | **79.11%** |

Every row is measured from that population's own published artifacts. The
combined row is **not** derived from the two above it.

**Distinct sample identities make the point concretely.** The cohort has
1,132 and the expansion 166, which sum to 1,298. The combined corpus
measures **1,288**: ten identities occur in both cohorts — the same decoded
audio in Ken Griffey Jr. Baseball and Plok!, in Street Fighter II Turbo and
both Mega Man X and Breath of Fire 2. Adding the two figures would have
overstated sample diversity by ten and quietly asserted that no sample is
shared across cohorts, which is false.

### The combined release mixes two production paths

This is a union of two validated populations. It is **not** evidence that
the two paths produce equivalent pitch statistics, and the combined pitch
figure should not be read as though it were a single method's result.

| half | tracks | how identity was produced | how pitch was produced |
|---|---|---|---|
| 22-game cohort | 1,316 | corrected after extraction, from DSP observations | estimated during extraction from the **capture-time** directory |
| 5-game expansion | 161 | resolved at key-on during extraction | estimated from the sample resolved **at key-on** |

The asymmetry matters because pitch is estimated from a sample's decoded
audio. Correcting an identity afterwards replaces a `sample_id`; it cannot
retroactively give the pitch estimator a sample it did not have. On Secret
of Evermore, whose capture-time directory resolves nothing, that difference
was **40.63% versus 91.72%** pitched attacks over the same audio — so the
timing of identity resolution can dominate pitch recovery.

What follows, stated plainly because it bounds what the combined figure
means: the cohort half's **78.25% pitched may understate what native v4
would recover from the same records**, by an amount nobody has measured.
That measurement is deliberately not in this release. It would change
published figures for 1,316 tracks and deserves its own versioned study
with its own comparison, rather than arriving as a side effect of adding
five games.

Until then, read the 78.71% combined figure as what it is: the pitched share
of a corpus assembled from two cohorts, one of which was produced by a path
now superseded.

### Splits are a property of the population, and this one limits evaluation

Splits are composer-disjoint and recomputed for each population; they are
never concatenated. For the combined corpus: **train 1,186 tracks over 18
games, valid 145 over 4, test 146 over 5.**

The limitation to understand before using them as a benchmark: splits are
assigned by *game*, because composer credits attach to games in the source
metadata. So a held-out score differs from training data in composer AND in
genre, sound driver, and instrument bank simultaneously. **A model scoring
poorly on `test` does not isolate composer generalisation** — those factors
are correlated with the games, and with 27 games they cannot be separated.

The five-game expansion alone is worse and should not be used as a benchmark
at all: its validation split is one racing soundtrack and its test split is
nine tracks of one baseball soundtrack.

### What the 13-game expansion added, measured

`expansion-8-rc1` adds 13 games and 362 tracks to a 27-game corpus. Its
contribution is **breadth**, and the aggregate musical measurements barely
move:

| measurement | 27-game | 13-game expansion |
|---|---|---|
| distinct sample identities | 1,288 | 467 (**+448** new to the combined corpus) |
| recorded composer credits | 53 | 20, of which **16 are new** |
| pitched attacks | 78.71% | 82.55% |
| interval entropy | 3.728 bits | 3.686 bits |
| median note duration | 0.1464 s | 0.1472 s |
| median attack density | 15.1/s | 15.5/s |

**Read that correctly.** Near-identical entropy, note length and density do
**not** establish that the new compositions lack stylistic diversity. They
establish that *these particular aggregate measurements* did not change.
Harmony, musical form, instrumentation roles, rhythmic organisation and
game-specific musical function can all vary substantially without moving an
interval-entropy figure or a median duration.

What the evidence does not support is the opposite claim either: there is no
basis for saying the expansion opened a new symbolic music distribution. Its
demonstrated contribution is 13 games, 16 new recorded composer credits and
448 new sample identities.

### Per-game observations from the 10-game cohort

Two figures in the Milestone 9 cohort stand out, and leave-one-game-out
analysis shows they are **per-game properties, not corpus trends**. Both are
recorded here as per-game observations and are deliberately NOT promoted to
corpus-level research conclusions.

**Super Bomberman 2 dominates the corpus legato rate.** It supplies 3.2% of
corpus attacks but 41,421 legato steps from 22 tracks. Removing it moves the
50-game pooled rate from **91.79 to 81.47 steps per 1,000 attacks** — a
12.7% swing, four times its share of attacks, and the only rate any single
game in the cohort dominates. So "SNES music shows more in-note pitch
movement than previously measured" is NOT supported; "Super Bomberman 2
shows markedly more than any other game measured" is.

The new cohort does sit higher on both weightings — pooled 133.08 and
game-balanced 114.89 steps/1,000 against the earlier cohorts' 82.90 and
77.61 — so the direction is real even game-balanced. The *magnitude* in the
pooled view is inflated by one soundtrack.

**Killer Instinct has the corpus's highest sample density**: 97 distinct
identities from 42 tracks, 4.6% of the corpus's 2,118 identities from 1.0%
of its attacks. Stated as density, not influence: sample banks do not cross
games, so the corpus total is the SUM of per-game banks and every game moves
it by its own contribution. A leave-one-out delta on that count measures the
metric's additivity, not a game's effect on the corpus.

**Pooled and game-balanced figures disagree on interval entropy**: 3.7193
bits pooled against 3.5629 game-balanced over 50 games. Pooling mixes 50
games' distributions, which raises entropy above any individual game's, so
the pooled figure overstates *within-game* interval variety. Quote the
game-balanced figure for claims about musical practice.

### The 50-game splits finally give evaluation non-baseline representation

| split | tracks | games | 22-game | M6 | M8 | M9 |
|---|---|---|---|---|---|---|
| train | 1,785 | 33 | 1,174 | 81 | 230 | 300 |
| valid | 225 | 9 | 123 | 36 | 46 | 20 |
| test | 218 | 8 | **19** | 44 | 86 | 69 |

This is the first partition in which the test split is **not** dominated by
the original cohort. At 40 games, test was 181 baseline tracks and **zero**
expansion. Here it is 19 baseline and **199 from the three expansion
cohorts** — Alien 3 and Star Fox from Milestone 9, Adventure Island,
Shadowrun and Tactics Ogre from Milestone 8, F-Zero and Tetris 2 from
Milestone 6.

That is a real improvement in evaluation diversity, and it was not designed:
the split assignment is deterministic and composer-driven, so the newly
added sole-composer games were eligible to land in evaluation as independent
units. The reverse caution now applies — test is only 8.7% original-cohort
material, so results on it say little about the games the corpus started
with.

### The 40-game splits, and what they cannot support

| split | games | tracks |
|---|---|---|
| train | 27 | 1,472 |
| valid | 7 | 186 |
| test | 6 | 181 |

Deterministic, composer-disjoint by recorded credit, and recomputed over the
40-game population — never concatenated from the cohorts. Regional releases
of one game are a single unit, so a game family cannot straddle the
partition.

Two limitations to carry into any experiment on these splits:

- **The test split is entirely from the original 27-game corpus** (181
  baseline tracks, 0 expansion). So results on it say nothing about
  generalisation to the newly added games, which appear only in train and
  validation.
- **Recorded-credit separation is not proven author separation.** 369 of
  1,839 tracks carry a credit truncated at 32 bytes, and the unresolved
  `Ke` / `Kenji Yamamoto` overlap affecting 206 tracks is unchanged.

The splits were **not** reassigned to balance them. A future benchmark may
define a different evaluation protocol; it should do so explicitly rather
than rewrite this one.

Cross-split musical content is unchanged from the 27-game corpus: the same
one confirmed Capcom-fanfare cluster, with the conditional exclusion still
applying (`sf2t-01` in validation, both training copies in train). Demon's
Crest, also a Capcom title, does **not** join it. Two new similarities —
Bahamut Lagoon ↔ Plok! and Secret of Evermore ↔ Terranigma — are recorded as
**unconfirmed candidates and are not evaluation exclusions**.

### A reproducible baseline, and what it shows

`tools/baseline_interval_ngram.py` answers one question on the published
artifacts alone: **can a smoothed interval n-gram predict the next melodic
interval in an unseen SNES game better than a frequency-only baseline?**
Results are in `docs/baseline_interval_ngram_results.json`, measured against
release **`snesmdb-27game-rc1`** and its 27-game splits.

**These are 27-game experiment results and do not transfer to the 40-game
splits.** The 40-game partition is a different population with a different
assignment, so the published figures below describe neither its training set
nor its test set. Re-running the experiment on 40 games would be a new
experiment, declared and reported separately.

**Yes, by a clear margin.**

| model | test accuracy | test NLL (bits) |
|---|---|---|
| interval 3-gram | **0.4309** | **3.2799** |
| frequency only | 0.3223 | 4.0150 |

+0.1086 accuracy, 0.735 bits lower NLL. The n-gram wins on **all five test
games** — Axelay, Batman Returns, F-Zero, Super Castlevania 4, Super Metroid
— so the result is not carried by one soundtrack.

**The learning population, stated exactly.** 1,112 music-class tracks,
7,099 voices, 1,584,465 intervals, from 882 / 111 / 119 tracks across
train / valid / test. Excluded by definition and counted rather than
dropped: 353 non-music tracks, 12 tracks with no usable sequence, 160,852
legato steps, 429,458 attacks with no pitch estimate.

**A melody is voice-local.** Sequences are built per `(track, voice)` from
pitched key-ons. A global time-sorted stream would place adjacent events in
different voices or inside one chord, so its "intervals" would describe the
arrangement rather than a melody. Legato steps are excluded: a step is a
pitch change inside a sounding note, derived from a register ratio rather
than re-keyed. Intervals beyond two octaves collapse into one bucket per
direction, giving a 51-symbol closed vocabulary.

**The duplicate exclusion did NOT fire, and that is reported as such.** The
confirmed cross-split duplicate is jingle-class; music-class filtering
removes its training copies, so the condition is not met. The experiment is
**not** described as corrected for leakage, because no correction was
exercised.

**The cohort confound is visible in the result, not normalised away.** On
test, the expansion cohort scores 0.5349 accuracy / 2.4014 bits against the
baseline cohort's 0.4159 / 3.4069 — but the expansion cohort here is F-Zero
alone, 14 tracks, so that gap confounds game with production path and cannot
be read as either.

**Selection touched validation only**, over a grid declared in the source
before any evaluation. It chose order 3, alpha 1.0 — **both at the grid
maximum**. These figures therefore describe the selected configuration under
that grid, and **the effect of a broader search is unmeasured**: a boundary
selection suggests a wider search would be informative, but it does not
establish that wider tuning would improve held-out performance. The grid was
deliberately not widened after test was evaluated — selection would still
have been clean, but re-running test after seeing a result is how a held-out
set stops being held out.

**What this does not show.** Held-out-*game* interval prediction only. Not
composer generalisation, not musical quality, not generation. The splits are
not interchangeable samples: pitched share runs 77.49% / 81.75% / 85.48%
across the three, validation is 43% expansion-cohort against train's 6.8%,
and test median max polyphony is 6 against 8.

### What the splits support, and what they do not

The claim the evidence supports:

> Game-disjoint, recorded-credit-disjoint splits for **held-out-game**
> symbolic music evaluation. Composer-level generalisation is **not
> established**. One cross-split duplicated composition has been identified
> and must be controlled for.

Three things stand behind that wording.

**Composer separation is by recorded credit, not by author.** 287 of 1,477
tracks carry a credit truncated at ID666's 32-byte field, and six of the 53
distinct "composers" are truncation fragments rather than names. The largest
is `Ke`, which covers **206 Earthbound tracks in train** and is a prefix of
`Kenji Yamamoto`, a complete credit in **test**. Whether they name the same
person is not decidable from published data. 501 tracks list several
contributors, so even a complete credit does not establish who wrote a given
track. Splits were assigned from these strings, so disjointness is a
property of the strings.

**One cross-split duplicate is confirmed.** The Capcom startup fanfare is a
complete track in Mega Man X and Breath of Fire 2 (train) and in Street
Fighter II Turbo (valid) — 24 notes matching on **absolute pitch** at full
coverage of each track, across eight voices and two independent matching
methods, with no internal repetition. A model trained on either training
copy has seen the validation copy in full.

The response is a change to the **evaluation protocol**, not the dataset.
All three tracks stay in the corpus and keep their published splits.
`docs/evaluation_exclusions.json` records the cluster and the rule, keyed by
`track_id`:

| track | split | role |
|---|---|---|
| `mmx-01:4c67c8f50c56` | train | training material |
| `bof2-s01:63651d0deeed` | train | training material |
| `sf2t-01:e5fe428a1b8c` | valid | **excluded from scoring** |

The exclusion is **conditional**: it applies only when a training copy is
actually in the training set. For an experiment that trained on neither, the
validation track is ordinary evaluation data, and dropping it
unconditionally would shrink everyone's evaluation set for one experiment's
problem. Restricting a task to `music`-class tracks also excludes all three,
since they are jingles — but the record is still needed by anyone evaluating
jingles or all classes.

**One candidate is recorded and NOT excluded.** A 31-interval agreement
between Lufia 2's "Rumbling" (valid) and Secret of Mana's "Monarch on the
Shore" (train) repeats every 8 notes and covers 7% and 4% of two long
tracks. That is a shared accompaniment figure, a convention of the idiom.
Treating it as leakage would discard valid evaluation data on weak evidence.

**What the search cannot tell you.** It reads published symbolic events, so
the 21.29% of attacks with no fixed-pitch estimate cannot match; pitch
recovery differs between the two cohorts, so they are not equally
observable; it matches note sequences, so a re-orchestrated or re-harmonised
quotation need not match; and sequences are built per voice, so material
redistributed across voices will not match. Sensitivity was verified by
planting a transposed composition in another split and confirming it is
found; specificity by confirming that ostinati, looping arpeggios and scales
are not. **A negative result bounds the method and does not establish that
no shared composition exists.**

### Composer attribution is tiered, and one tier is not an identity

Disjointness is only as strong as the attribution it is computed from.

| tier | combined tracks | what it is |
|---|---|---|
| full ID666 credit | 1,190 | the tag fits in the field |
| **truncated** ID666 credit | 287 | cut at the 32-byte limit, mid-name |

A truncated credit such as `Yoshihiro Sakaguchi, Yoko Shimom` or
`Chris Jojo, Paul Tonge, Matthew` is an **incomplete tag string, not a
confirmed identity**. `composer_truncated` carries this per track. A
game-level credit does not establish track-level authorship, and nothing in
this corpus asserts that it does: a track's credit is the credit its SPC
carried, at whatever completeness the dumper recorded.

### Row duration is stated per population, not corpus-wide

The span above describes the **22-game frozen cohort** (`gate5-rc10`, 1,316
tracks). It is a property of that sample, not of the SNES, and it is not
amended when a new game is measured outside it.

| population | tracks | row duration |
|---|---|---|
| 22-game frozen cohort | 1,316 | **2.000–30.500 ms** |
| 5-game expansion | 161 | **1.813–20.000 ms** |
| 27-game combined | 1,477 | **1.813–30.500 ms** |
| 13-game expansion (`expansion-8-rc1`) | 362 | **2.000–26.500 ms** |
| 40-game combined (`snesmdb-40game-rc1`) | 1,839 | **1.813–30.500 ms** |
| 10-game expansion candidate | 389 | **2.000–22.000 ms** |
| 50-game combined candidate | 2,228 | **1.813–30.500 ms** |

The 40-game figure coincides with the 27-game one because the widest and
narrowest rows in the corpus both come from games the 13-game expansion did
not displace. It is measured over the 40-game artifacts, not inherited.

The combined figure is **measured over the combined artifacts**, not taken
as the union of the two rows above. For a minimum and a maximum the two
happen to coincide — an envelope of mins and maxes is the union by
construction — but that is not true of anything else a reader might want:
the median, the count of distinct rates, and every per-population share have
to be measured, and a release that unioned them would be publishing
arithmetic rather than measurement.

The expansion's 1.813 ms minimum is a **verified extension**, observed in one
Ken Griffey Jr. Baseball track, not a correction to the figure above. Its
20.000 ms maximum is lower than the cohort's simply because no expansion
driver runs as coarse as Star Ocean's; a narrower span in a smaller sample is
not evidence of anything.

Reading either figure as "the SNES row duration range" is the sampling-frame
error this table is split to prevent. A combined 27-game release would have
to state the range measured over the combined artifacts rather than take the
union of these two rows.

The primary grid is the honest hardware answer and it **cannot be compared
across games**: the rate differs per track, so "notes per row" means something
different in every one.

**The hardware row is not always finer than the uniform one.** An earlier
version of this table gave the row duration as "2.00–12.50 ms", which were in
fact the two example games quoted beside it printed as if they were the range
— and which contradicted the same table's own 32.8 Hz lower rate bound, since
32.8 Hz is a 30.5 ms row. The true span is 2.000–30.500 ms. **341 tracks
(25.9%) have a hardware row coarser than the 10 ms uniform grid, and 178
(13.5%) are coarser than 12.50 ms**; Star Ocean and Tales of Phantasia sit
around 20.5 ms, two to three times coarser than uniform. So "use the primary
grid for anything about this driver" does not mean within-driver timing work
loses nothing — for a quarter of the corpus the uniform grid is the finer of
the two. An evaluator caught this. That is what the uniform grid exists to fix — one row
means 10 ms in every track in the corpus.

**100 Hz was chosen by measurement, not borrowed.** The corpus was scored at
24, 50, 100 and 200 Hz and the costs compared:

- it divides the SPC700's 1,024,000-tick second **exactly** — 10,240 ticks per
  row, so no rounding accumulates across a long track
- it is **achievable on the hardware**: T0/T1 at 8 kHz divided by 80
- it loses **one** repeated-note attack in 1,458,211 pitched events. 50 Hz
  loses 1,275; 24 Hz loses far more. 200 Hz loses none but doubles the rows
  for that single event
- about **1.95× fewer rows** than the primary grid at the median
- max polyphony 8, within the hardware

Quantisation error against the exact placement is 2.49 ms at the median and
4.7 ms at p95, and durations under 10 ms cannot be represented at all (0.14%
of notes). For microtiming, use the original timestamps — see above.

### A third grid is published and indexes nothing: `onset_grid`

Every score file carries `onset_grid` — a period fitted to the note onsets
themselves. **No row is derived from it**, and it is **the right starting
point for rhythm and quantisation work.** Onsets concentrate on it at
R = 0.937 against only 0.262 on the timer `clock`, and a period fitted on one
half of a track and tested on the other reaches 0.853 against the tick's
0.188.

The timer clock is a hardware fact — one row is one timer tick — and the timer
runs a median **16.5× faster than the music**, so measuring quantisation
against it makes the onsets look barely quantised. An evaluator did exactly
that, measured R = 0.26, and nearly published that conclusion. It was
abandoned as a *row index* because 346 distinct fitted rates across 664 tracks
cannot carry a comparable corpus-wide score; that is a different question from
whether it describes the music. Fields: `found`, `period_ticks`, `period_sec`,
`rows_per_second`, `bpm_assuming_4_rows_per_beat`, `phase_ticks`, `n_rows`,
`fit`, `median_abs_residual_ticks`.

**This is not NES-MDB's rate and makes no claim of cross-corpus
comparability.** NES-MDB's scores are 24 Hz. An earlier version of this
document specified 60.0988 Hz and attributed it to NES-MDB; that was wrong
twice over, since 60.0988 Hz is the NES's NTSC *video* frame rate and the
SPC700 has no relationship to it. A model training across both corpora must
rescale.

## Rows are indexed on the SPC700's own timer register

Every one of the **1,316 tracks** is clocked from a hardware register read out
of the SPC file. Nothing is inferred and nothing is averaged:

| `clock.source` | tracks | |
|---|---|---|
| `timer_register` | **1,316 (100%)** | read from `$F1`/`$FA`-`$FC` |
| `game_tick` | 0 | inferred from write cadence (fallback) |
| `track_tick` | 0 | inferred, single track (fallback) |
| `fixed` | **0** | a fabricated 100 Hz convention |

An SPC dump carries the whole 64 KB of ARAM, and the SPC700's timer registers
live in its I/O page: `$F1` holds the enable bits, `$FA`/`$FB`/`$FC` the T0, T1
and T2 targets. T0/T1 count at 8 kHz and T2 at 64 kHz, each divided by an
8-bit target where 0 means 256. The lowest enabled timer is taken as the
sequencer: **T0 for 1,295 tracks, T2 for 20, T1 for 1**.

**One row is one physical timer tick.** That is a deliberate choice over the
musical alternative. Where a driver counts M timer ticks per sequencer row,
rows are M times finer than the music and a note spans several of them; but M
is only recoverable from write cadence, which fails on 220 tracks, so dividing
by it would make a row mean different things in different tracks. The uniform
definition won.

**A row is a uniform definition, not a uniform duration.** `$FA` differs per
game, so a row is 2.00 ms in Super Mario World and 12.50 ms in Donkey Kong
Country — 80 distinct clock rates across the corpus, 32.8 Hz to 500.0 Hz,
median 205.1 Hz. Any cross-game comparison of a per-row quantity has to divide
by `clock.hz`.

**Why this replaced an inferred clock, twice over.** The first design fitted a
period to note onsets, which produced 346 distinct row rates across 664
tracks, 75% of them unique within a single game. The second measured the
driver's tick from DSP write cadence, which worked for most drivers and failed
for 220 tracks — 178 of them music — that fell back to a fabricated 100 Hz.
Three hypotheses for that failure were tested against write logs and all three
were refused: N-SPC does not expose a periodic tick in its DSP writes at all,
in either the music or the global registers, at any rate between 30 and 800 Hz.
The information was never in the write log; it was in the file.

**The register corroborates the estimator where both exist.** `8000/$FA`
reproduces every clock write cadence found — Chrono Trigger 190.48 Hz, Super
Metroid 500, Final Fantasy VI 205.13, Secret of Mana 222.22, Donkey Kong
Country 80, Earthbound 500, Kirby 500, Dragon Quest 5 200, Castlevania IV 250
— and four games differ by an exact power of two (Batman Returns 2x, Breath of
Fire 2 and Mega Man X ½, Plok! ¼), which is the software divisor M. Ten exact
agreements and four clean ratios.

Being per-track, the read also handles the drivers that reprogram their
divider mid-game: Tales of Phantasia dumps 31 distinct timer values across its
tracks, Star Ocean 26, Lufia 2 21, Super Turrican 13, Plok! 10. Each track gets
its own rate rather than a per-game average or a fallback.

**Caveat on the source.** `$F1` is write-only on real hardware, so the byte an
SPC carries there is a convention of the dump format rather than something the
CPU could read back. It is trusted because it validates against those ten
independent measurements, which is empirical corroboration and not a guarantee.

**Quantisation cost is negligible.** 529 of 1,458,115 placed notes (0.036%)
are shorter than one row and were snapped to the nearest; 5 notes went
unplaced and 2 cells are contested. The `grid` block is still reported as the
**onset** period — a real and separate musical measurement — but it no longer
indexes anything.

## A row is a hardware tick; the musical row needs `software_divisor_m`

One row is one SPC700 timer tick. Where a driver counts M ticks per sequencer
row, rows are M times finer than the music and a note spans several of them.

`timing.software_divisor_m` in the intake tree, and `software_divisor_m` in
each score, carries M where it can be recovered: it is the ratio of the
register clock to the rate `tick.py` measures from DSP write cadence, since the
first is the timer and the second is the sequencer. That ratio is a clean
integer for **403 of 1,316 tracks (31%)** -- 462 of the 519 that have a
write-cadence estimate at all, 89% of them, median ratio exactly 1.00.

**It is `null`, never 1, where unknown.** Defaulting to 1 would silently assert
that the row IS the musical row for the other 913 tracks. A consumer wanting
musical rows must either restrict to tracks where M is known or accept rows at
timer resolution.

**M is a timer-to-write-cadence ratio, not ticks per musical row.** The label
promises the musical row and the field does not deliver it: published values
run `{1, 2, 3, 4, 8}` with a maximum of 8, while the measured onset period is a
median **16.5× the timer tick** (p95 80×) — so dividing rows by M still leaves
them several times finer than the music. The derivation below says so
honestly; the description above it did not. **If you want the period the music
is actually on, use `onset_grid`** — see below.

`driver_tick_hz` is published beside it as the quantity M derives from. It is
the SEQUENCER rate rather than the timer, and it is **null on the 797 tracks
where the estimate did not pass its own plausibility check** — 519 carry a
value. Each record also carries `driver_tick_found`, so the absence is
self-describing without consulting a second file.

This field previously published the *refused* estimate on all 1,316 tracks
while this paragraph promised it was absent for 797, so a filter on non-null
returned every track and silently admitted 797 rejected values — Actraiser
tracks with a 500 Hz timer carried 157.079 Hz. An evaluator found it. The
guard existed in `scores[*].tick.found` and this field had escaped it;
`software_divisor_m` beside it kept the contract exactly, null on 913 and set
on 403.

A further 20 tracks report exactly 2,048 ticks -- intra-burst write spacing
mistaken for a timer. Those are refused a divisor because their ratio is not
a clean integer, which is the guard working rather than an accident.

## Velocity is the attack; sustain is a separate channel

The DSP computes

    out = (sample * env) >> 11        # env is the 11-bit internal envelope
    amp = (out * VOL) >> 7            # VOL signed 8-bit, per side

so amplitude is **env x VOL**, and `velocity` carries VOL alone. That is
correct for the ATTACK: in ADSR mode the attack phase drives env to full scale
whatever the rate, so peak loudness really is VOL. What VOL cannot express is
where the note SETTLES, which is why the expressive score has a fourth
channel.

`expressive.channels` is `(note, velocity, timbre_class, sustain)`. Channel 3
is the sustained amplitude on the same 0..127 scale as velocity, so the two
compare directly: equal means the note holds, lower means it decays to that
level. **-1 means the envelope cannot be read from the key-on state** -- a
ramping GAIN mode -- and is not zero, because zero means silent. No note in
this corpus uses a ramping mode, so -1 should not appear.

Corpus-wide over 1,863,499 notes: **93.73% ADSR, 6.27% GAIN direct, no ramping
modes**, so the envelope is 100% decidable. **80.0% of notes hold at full
scale** and need no correction; the other **20.0% (372,538 notes)** settle
below, down to silence at sustain level 0. Measured over expressive CELLS,
which are duration-weighted rather than note-weighted, 90.3% hold, 6.2% decay
and 3.5% are silent.

Sustain level is `ADSR2 >> 5`, and the hardware leaves decay when
`(env >> 8) == SL`, so **the plateau is `SL x 256`** -- the bottom of a
256-wide band, not `(SL+1) x 256`, which is that band's top edge. SL=7 is
special: env is already `0x7FF` when the attack ends and `0x7FF >> 8` is 7, so
decay never runs.

Note that the expressive score was present in `scores.py` from milestone 6 but
**was never emitted to disk until this change**, so neither it nor the sustain
channel reached any published file before now. `timbre_class` is written as -1
throughout: the milestone 5 codebook failed its own cross-game validation, so
no class number from it is offered.

**Driver envelope strategies differ, which is why one rule would not serve.**
Measured over ten seconds of one track per game, counting register writes:

| driver behaviour | games | signature |
|---|---|---|
| full voice patch per note | DKC, Kirby, Super Metroid, Star Ocean, Tales of Phantasia, Super Mario World | SRCN/ADSR1/ADSR2/GAIN written in lockstep |
| ADSR per note, no GAIN | Chrono Trigger, Secret of Mana | GAIN never written |
| software envelope | Mega Man X | GAIN written 390x against 26 SRCN writes |
| set once, VOL does everything | Earthbound (one track: one write of each) | VOL written 274x, patch 1x |

That last row is why voice state must be seeded from the SPC's DSP block --
see the note on SRCN above. Before it was, 540 tracks reported ADSR disabled
with GAIN 0, i.e. a silent envelope, purely because their drivers never
rewrote those registers. That artifact was 5.74% of notes; it is now 0.05%.

**The voice patch is always written before the key-on, never after**, so
reading the registers at the key-on instant captures the authoritative block.
Measured: Mega Man X 174/174 key-ons have the patch already in place (median
400 clocks earlier), Star Ocean 139/139 (4,281), Super Mario World 121/200
(2,202), and no driver writes a patch register in the 64-128 clocks following
a KON.

Phase inversion is still lost: velocity takes the magnitude, and a negative
side volume inverts that side's phase, which two games do on over half their
notes.

## There is no usable timbre field

**`timbre_class` is the constant `-1` in every published file.** Nothing can be
derived from it. No codebook ships. If you are looking for instrument identity,
use `sample_id` — a content hash of the decoded audio, which identifies a sound
source but is explicitly *not* an instrument label.

### Why, and what the earlier claim was

Milestone 5 fitted a 5-class codebook over 1,162 distinct samples and found
that only the tonal/percussive split transferred across games: fitted on 16
train games and applied to 6 unseen ones, the pitched/unpitched division
transferred exactly, while register did not — one class moved **16 semitones**
between training and held-out games. Cross-game agreement over the whole
corpus sits at the shuffled-label null on every axis, so the finer structure
describes each game's own sample bank and not a vocabulary.

On that basis an earlier version of this document told researchers to *"use
the class as a binary tonal/percussive flag"*. **That instruction was wrong
and is withdrawn.** The classes were never written into the published files —
every note carries `-1` — so a tonal/percussive split computed from the field
partitions nothing. It was the one place in this documentation where following
the instructions produced a *false* result rather than an unclear one, and an
independent evaluator reported it as such.

`expressive.timbre_validated` still reads `"tonal_vs_percussive_only"`. That
describes **how far the analysis got**, not a capability of the data, and it
will be removed when the score payload next changes shape.

**Voice roles are not provided either.** A role needs register and function,
and register is exactly what failed to transfer.

## MIDI drops things, and names them

Only notes with a recovered pitch appear — 1,458,120 of 1,863,499 notes are
written and 402,635 dropped, across 1,243 of the 1,316 tracks (a track with no
pitched note at all gets no file). Each file is **type 1 with nine chunks**:
a conductor track followed by eight voice tracks, so chunk *n+1* is voice
*n* — indexing chunks 0–7 as voices 0–7 is off by one. Each voice track
carries a `voice N` text name, so the mapping is self-correcting from the
file. Voice 7 is written to MIDI channel 8 (1-based), skipping channel 7, so
that 0-based channel 9 — GM percussion — stays empty. No General MIDI
program is set, because sample identity does not transfer and a program number
would be fabricated. Channel 9 is never used, so nothing is implicitly a drum.
**Phase inversion is lost**: a negative side volume inverts that side's phase
and MIDI cannot express it, so magnitude is written. That is not a corner case
— Tales of Phantasia inverts on 55.8% of its notes and Star Ocean on 52.6%. The
per-track `midi_summary` counts every drop.

A fixed 120 BPM at 480 PPQ is written because the S-DSP has no tempo. Timing is
absolute, not quantised to the row grid.

## The intake schema is not verified against a consumer

`intake/*.json.gz` is `snesmdb.intake.v1`, documented by its own fields. The
design intends it for the sibling renderer's `acquire(from_extracted=True)`,
**which is not present in this repository and against which it has not been
tested.** Treat the schema as proposed.

## Composer credits truncate

The ID666 composer field is 32 bytes and overflows silently. **242 of 1,316
tracks (18.4%)** carry a truncated credit, concentrated in Earthbound's 206
(`Akio Ohmori, Ritsuo Kamimura, Ke` — a third contributor unrecoverable).
Disjointness still passes for those tracks, but it passes on the names that
happened to fit. `composer_truncated` flags each one.

## Structural failures

**24 of 1,316 tracks (1.8%)** fail a structural check. 17 share one cause: an
SPC is a snapshot of a running system, so a track already sounding and never
re-keyed has no key-on to recover and the note model cannot represent it. Every
such track is a drone, a jingle or an effect. Two more are sub-second jingles
whose ID666 length rounds up to a whole second, tripping a check that expects
register writes to span the window.

## Corpus composition

22 games, weighted toward JRPGs and first-party titles, with Earthbound at
206 tracks (15.7%) the largest single game. Not a random sample of the SNES
library, and not balanced by genre, year or region.

## Two of the hardware's features are effectively unused

**106 noise notes and 727 pitch-modulated notes out of 1,863,499** — 0.006% and
0.039%. Drivers write the NON and PMON registers constantly and always with
zero. If you are modelling the S-DSP, this corpus will not exercise either.

---

## Rebuilding

```sh
make corpus          # the whole thing: ~80 min on 8 jobs
```

That is the only entry point that guarantees the ordering, and the ordering is
load-bearing. The steps, if you need them individually:

```sh
make                 # build/spc_dump
make extract         # ~50 min  SPCs -> manifest, records, scores, clock
make performance     #          the §7 analysis, all tracks and music-only
make publish         # ~18 min  -> DIST_DIR
make verify          #          26 checks; exits non-zero on any failure
make audit           #          27 checks, opening EVERY published file
make freeze LABEL=.. #          pin the tree by file hash for an evaluation
```

Override with `SPC_DIR=`, `OUT_DIR=`, `DIST_DIR=`, `JOBS=`.

**This used to need a second whole-corpus pass, and it was easy to forget.**
A `reclock` step derived the row clock after extraction, and the recipe
documented here omitted it -- which produced a corpus with **zero** scored
tracks, silently, because publish found no clock and wrote nothing without
erroring. Anyone reproducing the corpus from these instructions would have
gotten an empty tree and no explanation.

The step is now **gone rather than documented more loudly.** It existed
because the row clock came from a per-game consensus over write-cadence
ticks, and no track's clock could be settled until every track of its game
had been seen -- a genuine reason for a second pass. The clock is now read
from each SPC's own timer register, so it is a pure function of one track and
is decided inside the extraction loop. One pass, nothing to forget.

Two things follow from that, and they are the reason it was worth doing rather
than just fixing the prose. `make corpus` is the ordering instead of a list of
commands, so a recipe that executes cannot drift from the recipe that is
written down. And `make verify` gates it: every one of its checks corresponds
to a defect that really shipped from this pipeline, and **not one of them
announced itself** -- each was found by reading output that looked fine.

`tools/timbre_features.py` and `tools/timbre_codebook.py` are deliberately
absent from this sequence. They still run, and the analysis is in
the repository's `docs/milestones.md`, but their output is not published -- see the
note on `timbre_codebook.json` above.

`publish.py` refuses to write inside a git work tree, because the output is
derived from research-only material.

## What this is not

**Not a training corpus for a generative model.** On the NES side a clean
retrain improved validation loss by 11.4% and produced output a listener called
"barely music". Next-token loss does not measure music, and more data does not
change that argument.

It is a dataset and the tools to rebuild it, for analysis, comparison, and as a
public artifact. `performance-conventions.md` is what it was built to produce.
