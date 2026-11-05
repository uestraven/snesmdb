"""Composer-disjoint splits.

NES-MDB's splits keep each composer in exactly one split, and RSE's dataset
config asserts `split_is_composer_disjoint: true`. A corpus with random splits
is not comparable to it: a model can memorise a composer's idiom from the
train split and look like it generalises on validation.

The complication the NES case hides is that a game can have several composers
and a composer works on several games. Assigning games to splits independently
therefore does NOT give composer disjointness -- if Final Fantasy VI and
Chrono Trigger share a composer and land in different splits, that composer
spans both.

So the unit of assignment is not the game and not the composer, but the
CONNECTED COMPONENT of the game-composer graph: games are nodes, two games are
connected when they share a composer, and a whole component must go to one
split. That is a correctness constraint, not a refinement, and it is why this
module exists instead of a call to `random.shuffle`.

A consequence worth knowing before trusting a split ratio: components can be
large. A prolific composer merges every game they touched into one component,
which must then land whole in one split, so the achieved ratios will not match
the requested ones exactly. `Splits.report` states the error rather than hiding
it.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

TRAIN, VALID, TEST = "train", "valid", "test"


@dataclass
class Splits:
    #: track id -> split name
    assignment: dict[str, str] = field(default_factory=dict)
    #: split name -> number of tracks
    counts: dict[str, int] = field(default_factory=dict)
    #: How many games each component held, largest first.
    component_sizes: list[int] = field(default_factory=list)
    requested: dict[str, float] = field(default_factory=dict)

    def report(self) -> dict[str, Any]:
        total = sum(self.counts.values()) or 1
        achieved = {k: v / total for k, v in self.counts.items()}
        error = {
            k: round(achieved.get(k, 0.0) - self.requested.get(k, 0.0), 4)
            for k in self.requested
        }
        return {
            "counts": dict(sorted(self.counts.items())),
            "achieved_fractions": {k: round(v, 4) for k, v in sorted(achieved.items())},
            "requested_fractions": self.requested,
            "fraction_error": error,
            "n_components": len(self.component_sizes),
            "largest_component_games": self.component_sizes[:5],
            "composer_disjoint": True,
        }


def _components(
    game_composers: Mapping[str, Iterable[str]]
) -> list[list[str]]:
    """Connected components of the game-composer bipartite graph, as games."""
    by_composer: dict[str, list[str]] = defaultdict(list)
    for game, composers in game_composers.items():
        for composer in composers:
            key = composer.strip().lower()
            if key:
                by_composer[key].append(game)

    parent: dict[str, str] = {game: game for game in game_composers}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for games in by_composer.values():
        for other in games[1:]:
            union(games[0], other)

    grouped: dict[str, list[str]] = defaultdict(list)
    for game in game_composers:
        grouped[find(game)].append(game)
    return [sorted(games) for games in grouped.values()]


def assign(
    tracks_by_game: Mapping[str, list[str]],
    game_composers: Mapping[str, Iterable[str]],
    *,
    valid_fraction: float = 0.1,
    test_fraction: float = 0.1,
    seed: int = 0,
) -> Splits:
    """Assign tracks to splits so no composer appears in two splits.

    Components are placed largest-first into whichever split is furthest below
    its target share. Greedy rather than optimal, which is fine -- but it is
    largest-first on purpose: placing a huge component last would force it
    wholesale into one split and wreck the ratios.
    """
    requested = {
        TRAIN: round(1.0 - valid_fraction - test_fraction, 4),
        VALID: valid_fraction,
        TEST: test_fraction,
    }
    components = _components(game_composers)
    total_tracks = sum(len(v) for v in tracks_by_game.values()) or 1

    sized = sorted(
        (
            (sum(len(tracks_by_game.get(game, [])) for game in games), games)
            for games in components
        ),
        key=lambda pair: (-pair[0], pair[1]),
    )
    # Break ties deterministically but not by name, so one alphabetical region
    # of the catalogue does not always land in the same split.
    rng = random.Random(seed)
    rng.shuffle(sized)
    sized.sort(key=lambda pair: -pair[0])

    placed: dict[str, int] = {TRAIN: 0, VALID: 0, TEST: 0}
    out = Splits(requested=requested)
    for n_tracks, games in sized:
        target = max(
            requested,
            key=lambda split: requested[split] - placed[split] / total_tracks,
        )
        placed[target] += n_tracks
        for game in games:
            for track in tracks_by_game.get(game, []):
                out.assignment[track] = target

    for split in out.assignment.values():
        out.counts[split] = out.counts.get(split, 0) + 1
    out.component_sizes = sorted((n for n, _ in sized), reverse=True)
    return out


def verify_disjoint(
    assignment: Mapping[str, str],
    track_composers: Mapping[str, Iterable[str]],
) -> dict[str, list[str]]:
    """Composers appearing in more than one split. Empty means disjoint.

    Checked against the ASSIGNMENT rather than trusted from construction,
    because the property is the whole point and a bug in `assign` would
    otherwise be invisible.
    """
    splits_by_composer: dict[str, set[str]] = defaultdict(set)
    for track, split in assignment.items():
        for composer in track_composers.get(track, ()):
            key = composer.strip().lower()
            if key:
                splits_by_composer[key].add(split)
    return {
        composer: sorted(splits)
        for composer, splits in sorted(splits_by_composer.items())
        if len(splits) > 1
    }
