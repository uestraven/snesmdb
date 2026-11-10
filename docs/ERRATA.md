# Errata

Corrections to **frozen** releases. A frozen release is never edited, so
anything wrong or missing in one is recorded here and fixed in the next
version. Each entry names the affected releases, what is wrong, and the
measured correct value.

Nothing here is a data defect: every corrected figure was recomputed from
the affected release's own artifacts, and the event, score, intake and MIDI
trees are unchanged.

---

## E-001 — the 50-game releases omit their own population row

**Affects:** `snesmdb-50game-rc1`, `expansion-9-rc1` (both ship the same
`DATASET.md`)
**Severity:** documentation gap. No published figure is wrong.

The populations table in the shipped `DATASET.md` ends at the 40-game
combined corpus. A researcher holding `snesmdb-50game-rc1` therefore finds
no row describing the corpus they downloaded, and the 13-game expansion's
successor cohort is absent too.

The missing rows, measured from `snesmdb-50game-rc1`'s own artifacts:

| population | games | tracks | attacks | pitched |
|---|---|---|---|---|
| 10-game expansion (`expansion-9-rc1`) | 10 | 389 | 567,853 | 76.92% |
| **50-game combined** (`snesmdb-50game-rc1`) | **50** | **2,228** | **3,205,461** | **79.11%** |

Identity coverage: 100.00% for the 10-game expansion, 99.52% for the
50-game corpus. Both recomputed from the frozen trees rather than carried
from a prior report -- a first draft of this entry stated 79.60% pitched,
which was itself an unmeasured figure.

Reconciliation, verified against the frozen tree:

```
attacks 3,205,461 + legato steps 294,224 = events 3,499,685
40-game 2,637,608 + 10-game 567,853      = 3,205,461
```

The row-duration table in the same document *does* carry a 50-game row
(1.813–30.500 ms), so only the populations table is short.

**Fixed in:** the repository's `docs/DATASET.md`, and therefore in the next
published release.

---

## E-002 — a 40-game attack count was quoted as a 50-game figure in reporting

**Affects:** no published artifact.
**Severity:** none to the releases; recorded because the figure circulated.

A closing summary described the 50-game corpus as having 2,637,608
attacks. That is the **40-game** count. The 50-game corpus has
**3,205,461**.

The frozen documentation is correct: `2,637,608` appears there only in the
row labelled *40-game combined*. The error was in prose, not in an artifact,
and no release needs reissuing on its account.

---

## E-004 — `index.composition.note` describes 22 games in a 50-game index

**Affects:** `snesmdb-50game-rc1`, `snesmdb-40game-rc1`,
`snesmdb-27game-rc1` — every combined release
**Severity:** misleading prose beside correct data. No published figure is
wrong.

`index.json` → `composition` carries a `note` field reading:

> Descriptive of the collected sample, NOT of SNES music. 22 games of
> roughly 700 commercial titles, JRPG- and first-party-weighted. Weight or
> qualify any corpus-wide figure accordingly.

The same block reports `n_games: 50`. The caveat's *point* still holds and
is still worth heeding — 50 of roughly 700 commercial titles is a biased
sample, JRPG- and first-party-weighted — but the count inside it was never
updated as the corpus grew, so a reader is told the corpus is 22 games by a
field sitting next to the one saying 50.

Nothing computed from `composition` is affected: `tracks_per_game` has 50
entries, `n_credited_composers` is measured over the release's own tracks,
and the concentration shares are correct.

**Fixed in:** the repository's publisher, and therefore the next release.

---

## E-005 — the 50-game release ships documentation scoped to earlier populations

**Affects:** `snesmdb-50game-rc1`, `expansion-9-rc1`, and the 40-game pair
**Severity:** high for a reader who has only the release. No published data
is wrong.

The shipped `DATASET.md` opens with the 22-game cohort's headline
(`1,316 tracks · 22 games · 1,863,499 notes`), says "zero unhandled DSP
registers occur across all 22 games", scopes the MIDI ledger and the
composer-attribution analysis to the 27-game release, labels the 50-game row
a *candidate*, and heads a seven-row populations table "Three statistical
populations". The shipped `SCHEMA.md` documents `game_slug` as "one of 22"
and `index.json` → `games` as covering "all 22", and omits the published
`release_variant` and `game_tag_verbatim` fields entirely.

A researcher holding `snesmdb-50game-rc1` therefore finds documentation
describing a corpus less than half its size, with no statement of which
population each figure belongs to.

The current figures for this release, measured from its own artifacts:

| | |
|---|---|
| tracks / games | 2,228 / 50 |
| events | 3,499,685 = 3,205,461 attacks + 294,224 legato steps |
| pitched attacks | 2,535,863 (79.11%) |
| identity | 3,189,942 (99.52%), 2,118 distinct identities |
| splits (train / valid / test) | 1,785 / 225 / 218 tracks over 33 / 9 / 8 games |
| MIDI files | 2,115 of 2,228 |
| truncated composer credits | 406 tracks |

Note in particular that **split assignments differ from every earlier
release**: splits are recomputed over each population, so a track's split in
the 27-game release is not its split here.

**Fixed in:** the repository's `README.md`, `docs/DATASET.md`,
`docs/SCHEMA.md` and `docs/CHANGELOG.md`, and therefore the next release.
The figures are now produced by `tools/corpus_census.py` and asserted
against the prose by `tests/test_readme_census.py`.

That mechanism is the real correction. Every figure in the stale
documentation was true of *a* population and internally consistent with its
neighbours, which is why three expansion milestones passed without anything
looking wrong. Internal consistency cannot detect a document describing the
wrong corpus; only comparison against a measured artifact can.

---

## E-003 — Killer Instinct: two different correct numbers

**Affects:** no published artifact. Recorded to prevent the two being read
as a discrepancy.

Killer Instinct has **98** distinct sample identities within its own 42
tracks, and contributes **97** identities that are new to the combined
corpus. Both are correct and they measure different things.

The difference is one identity, `931339412de13491`, which also occurs in
**ActRaiser, Donkey Kong Country and Donkey Kong Country 2**. That is
genuine cross-game content reuse: the same decoded BRR audio and loop point
in four games across unrelated studios. It is a clean illustration of the
documented rule that `sample_id` is a **content** identity and not an
instrument label — identical audio implies no shared musical role.
