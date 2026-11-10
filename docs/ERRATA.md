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
