"""Regional releases of one game, grouped without losing which is which.

A track's slug comes from its source filename and its game name from the
SPC's ID666 tag, and for most games those agree. They do not always: the
supplied Tetris Attack set contains five tracks ripped from **Panel de Pon**,
the Japanese original, under slug `pdp`, alongside 48 from the Western
release under `ta`.

Three facts have to coexist, and the earlier shape lost one of them:

    the two are ONE GAME for corpus purposes    - counting them as two
                                                  games inflates the game
                                                  count and splits a single
                                                  soundtrack across the
                                                  partition
    the two are DIFFERENT RELEASES              - the rips differ, and a
                                                  researcher comparing
                                                  regional versions needs to
                                                  know which is which
    the TRACK IDS are permanent                 - `pdp-01a` keeps its id.
                                                  Rewriting published
                                                  identifiers to tidy a
                                                  grouping would break every
                                                  reference to them

So the family is a GROUPING applied at publication: `game_slug` and `game`
become the family's, while `release_variant` records the member and
`game_tag_verbatim` keeps the ID666 string exactly as the rip carried it --
including its inconsistent capitalisation, which is a property of the source
and not ours to correct.

The map is curated and deliberately tiny. It is not a place to normalise
spelling or to merge games that merely resemble one another; each entry
asserts that two slugs are regional releases of the same work.
"""

from __future__ import annotations

from typing import NamedTuple


class Family(NamedTuple):
    slug: str
    name: str


#: member slug -> family. Only for slugs that are NOT their own family.
#: `pdp` (Panel de Pon, Japan) is the original of `ta` (Tetris Attack, West).
MEMBERS: dict[str, Family] = {
    "pdp": Family("ta", "Tetris Attack"),
}

#: Family slug -> the canonical name to publish. Needed because the ID666
#: tags within a family disagree, so the tag cannot decide the label.
CANONICAL_NAME: dict[str, str] = {
    "ta": "Tetris Attack",
}

#: Member slug -> the regional release it came from. Recorded per track so
#: grouping does not erase provenance.
VARIANT: dict[str, str] = {
    "pdp": "Panel de Pon (JP)",
    "ta": "Tetris Attack (US/EU)",
}


def resolve(slug: str, game_tag: str) -> tuple[str, str, str | None]:
    """`(family_slug, published_game_name, release_variant)`.

    A slug with no family entry is its own family and keeps its tag name, so
    every other game in the corpus is unaffected by this module.
    """
    family = MEMBERS.get(slug)
    family_slug = family.slug if family else slug
    name = CANONICAL_NAME.get(family_slug) or (
        family.name if family else game_tag)
    return family_slug, name, VARIANT.get(slug)


def is_grouped(slug: str) -> bool:
    """Whether this slug publishes under a different family slug."""
    return slug in MEMBERS
