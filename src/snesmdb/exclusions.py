"""Evaluation exclusions, applied by rule rather than by hand.

The corpus is immutable and its splits are published. When an evaluation
track turns out to duplicate training material, the dataset is not the thing
to change -- the SCORE is. So the exclusion lives in a record keyed by
`track_id` and is applied here, once, by every experiment that needs it.

Two properties matter more than convenience.

CONDITIONAL. An exclusion names the training tracks that make it apply. The
Street Fighter II Turbo logo track is only unusable as a score for a model
that trained on the Mega Man X or Breath of Fire 2 copies; for an experiment
that trained on neither it is ordinary validation data. An unconditional
drop would quietly shrink the evaluation set for everyone.

NOT A DELETION. Nothing here removes a track from the corpus or from corpus
statistics. `exclude` returns the tracks to leave out of a metric, and the
caller reports what it left out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SCHEMA = "snesmdb.evaluation_exclusions.v1"

def _find_record() -> Path:
    """Locate the exclusion record without assuming a repository layout.

    This used to be `parent.parent.parent / "docs" / ...`, which is the
    source checkout's shape and nothing else. In a standalone release the
    module sits beside the record rather than three levels under a `docs`
    directory, so the hard-coded path pointed outside the archive and the
    published experiment could not run from a download at all.

    Candidates are tried in order and the first that exists wins, so the
    same module works in a checkout and in a release without either being
    special-cased.
    """
    here = Path(__file__).resolve()
    candidates = (
        here.parent / "evaluation_exclusions.json",            # packaged
        here.parent.parent / "evaluation_exclusions.json",     # toolkit root
        here.parent.parent.parent / "evaluation_exclusions.json",
        here.parent.parent.parent / "docs" / "evaluation_exclusions.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # Nothing found: return the checkout location so the error names a real
    # path rather than a guess.
    return candidates[-1]


DEFAULT_PATH = _find_record()


@dataclass(frozen=True)
class Exclusion:
    track_id: str
    split: str
    cluster_id: str
    conditional_on: tuple[str, ...]
    rationale: str

    def applies(self, training_tracks: Iterable[str]) -> bool:
        """Does this exclusion bite, given what was actually trained on?

        True when ANY named training track is present. One copy in the
        training set is enough to make the evaluation track a recall test.
        """
        present = set(training_tracks)
        if not self.conditional_on:
            return True
        return any(t in present for t in self.conditional_on)


@dataclass
class Record:
    exclusions: list[Exclusion] = field(default_factory=list)
    unconfirmed: list[dict] = field(default_factory=list)
    claim: str = ""
    limits: list[str] = field(default_factory=list)

    def excluded(self, training_tracks: Iterable[str]) -> set[str]:
        """Track ids to leave out of a score, given the training set."""
        present = list(training_tracks)
        return {e.track_id for e in self.exclusions if e.applies(present)}

    def report(self, training_tracks: Iterable[str]) -> list[dict]:
        """What was excluded and why, for the experiment to publish.

        An exclusion a reader cannot see is indistinguishable from a
        convenient subset, so every experiment reports this alongside its
        numbers.
        """
        present = list(training_tracks)
        return [
            {"track_id": e.track_id, "split": e.split,
             "cluster_id": e.cluster_id, "rationale": e.rationale}
            for e in self.exclusions if e.applies(present)
        ]


def load(path: Path | None = None) -> Record:
    data = json.loads((path or DEFAULT_PATH).read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError(
            f"expected {SCHEMA}, found {data.get('schema')!r}")
    record = Record(
        claim=data.get("supported_research_claim", ""),
        limits=list(data.get("search_coverage_limits") or []),
        unconfirmed=list(data.get("unconfirmed_candidates") or []),
    )
    for cluster in data.get("duplicate_clusters") or []:
        if cluster.get("status") != "confirmed":
            # An unconfirmed cluster must never silently shrink an
            # evaluation set. It is recorded for review, not applied.
            continue
        for item in cluster.get("exclusions") or []:
            record.exclusions.append(Exclusion(
                track_id=item["track_id"],
                split=item.get("split", ""),
                cluster_id=cluster["cluster_id"],
                conditional_on=tuple(
                    item.get("conditional_on_training_tracks_present") or ()),
                rationale=item.get("rationale", ""),
            ))
    return record
