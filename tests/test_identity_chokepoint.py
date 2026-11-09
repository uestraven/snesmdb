"""Every path to a canonical sample identity applies the same rules.

The lesson being locked down is narrow and was learned the expensive way: a
CORRECT validation function is not enough if a reporting or publishing path
can forget to call it.

Two concrete failures motivated this file.

1.  The plausibility rule had two implementations that DISAGREED.
    `brr.DirectoryEntry.plausible` rejected only a zero start;
    `dirtimeline.plausible` also rejected the `$FFFF` fill of an
    unpopulated table. The publisher used the first, the analysis tools the
    second. Neither was wrong on its own terms, and nothing detected the
    divergence.

2.  Three analysis tools called `sampleid.sample_id` with NO gate. The
    corpus-wide validation pass therefore reported 15,165 hashes of
    unwritten memory as established identities -- 11,294 of them as
    "recoveries" over a correctly published null. Address 0 holds bytes,
    `brr.decode` reads them, and the hash looks exactly as confident as a
    real one.

So these tests are structural, not behavioural: they assert that only one
function can mint an identity and that only one predicate decides whether an
entry is real. A behavioural test cannot catch a path that forgot to ask.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import brr, dirtimeline, identity, sampleid  # noqa: E402

# The one module allowed to call `sampleid.sample_id`.
CHOKEPOINT = "identity.py"

# A single, narrow exemption, listed here so that adding another requires
# editing this file and justifying it.
#
# `verify_publisher_rule_change.py` exists to answer "did unifying the
# plausibility rule change the publisher's output". Answering that means
# executing the OLD, pre-chokepoint path verbatim -- gate, decode, mint --
# and recording what it actually emitted. Routing it through the chokepoint
# would make it test the new behaviour against itself and always pass.
#
# It is a measurement harness, not a producer: nothing it mints is published
# or compared against published data.
EXEMPT = {"verify_publisher_rule_change.py"}


def _python_sources() -> list[Path]:
    return sorted(
        [p for p in (ROOT / "src" / "snesmdb").glob("*.py")]
        + [p for p in (ROOT / "tools").glob("*.py")]
    )


def _calls_sample_id(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "sample_id":
            return True
        if isinstance(fn, ast.Name) and fn.id == "sample_id":
            return True
    return False


# ---------------------------------------------------------------------------
# One producer
# ---------------------------------------------------------------------------

def test_only_the_chokepoint_mints_a_sample_identity():
    """Enforced by reading the source, because the defect is an ABSENCE: a
    tool that never calls the gate cannot be caught by calling it."""
    offenders = []
    for path in _python_sources():
        if path.name in (CHOKEPOINT, "sampleid.py") or path.name in EXEMPT:
            continue
        if _calls_sample_id(ast.parse(path.read_text())):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "these modules mint a sample identity without going through "
        f"identity.identity_for_entry: {offenders}. Route them through the "
        "chokepoint so the plausibility rule cannot be skipped."
    )


def test_the_exemption_list_stays_small_and_is_justified():
    """An exemption list is a hole in the guarantee. One entry with a stated
    reason is a judgement; a growing list is the defect coming back."""
    assert len(EXEMPT) <= 1, (
        f"exemptions have grown to {sorted(EXEMPT)}. Each one is a path that "
        f"can mint an identity without the plausibility rule."
    )
    for name in EXEMPT:
        assert (ROOT / "tools" / name).is_file(), (
            f"{name} is exempted but no longer exists; drop the exemption"
        )


def test_the_chokepoint_really_does_call_sample_id():
    """Guards the guard: if `identity.py` stopped minting identities, the
    test above would pass vacuously while nothing worked."""
    tree = ast.parse((ROOT / "src" / "snesmdb" / CHOKEPOINT).read_text())
    assert _calls_sample_id(tree)


def test_the_production_publisher_routes_through_the_chokepoint():
    """`publish.py` is the path whose output researchers actually read."""
    text = (ROOT / "tools" / "publish.py").read_text()
    assert "identity.identity_for_entry(" in text
    assert "sampleid.sample_id(" not in text


# ---------------------------------------------------------------------------
# One rule
# ---------------------------------------------------------------------------

def test_the_plausibility_rule_has_exactly_one_definition():
    """Not merely "they agree today" -- the SAME function object. Agreement
    between two copies is a property that decays silently."""
    assert identity.plausible_entry is brr.plausible_entry
    assert dirtimeline.plausible((0xFFFF, 0xFFFF)) is False
    assert brr.plausible_entry((0xFFFF, 0xFFFF)) is False


def test_every_predicate_agrees_across_the_whole_address_space():
    """The divergence that existed was exactly one value, `$FFFF`, so a
    sparse example-based check could easily have missed it. This sweeps the
    boundaries plus a stride across all 16 bits."""
    candidates = [None]
    for start in list(range(0, 8)) + list(range(0xFFF8, 0x10000)) + \
            list(range(0, 0x10000, 1021)):
        for loop in (0, start, max(0, start - 1), start + 1, 0xFFFF):
            candidates.append((start, loop))
    for entry in candidates:
        a = brr.plausible_entry(entry)
        b = dirtimeline.plausible(entry)
        c = identity.plausible_entry(entry)
        assert a == b == c, f"{entry}: brr={a} dirtimeline={b} identity={c}"


def test_the_directory_entry_property_uses_the_shared_rule():
    assert not brr.DirectoryEntry(index=0, start=0, loop=0).plausible
    assert not brr.DirectoryEntry(
        index=0, start=0xFFFF, loop=0xFFFF).plausible
    assert not brr.DirectoryEntry(index=0, start=0x2000, loop=0x1000).plausible
    assert brr.DirectoryEntry(index=0, start=0x2000, loop=0x2000).plausible


# ---------------------------------------------------------------------------
# The rule's actual content
# ---------------------------------------------------------------------------

def test_an_implausible_entry_yields_no_identity_rather_than_a_hash():
    """The whole point. ARAM address 0 decodes; it must still produce None.

    Donkey Kong Country 2 keys on SRCN 140 whose directory entry is (0, 0).
    The baseline published null and was RIGHT; an ungated analysis reported
    211 recovered identities there.
    """
    aram = bytes(range(256)) * 256           # decodable bytes everywhere
    assert identity.identity_for_entry(aram, 0, 0) == (None, None)
    assert identity.identity_for_entry(aram, 0xFFFF, 0xFFFF) == (None, None)
    assert identity.identity_for_entry(aram, 0x2000, 0x1000) == (None, None)


def test_a_plausible_entry_still_yields_an_identity():
    """The gate must not be so strict that it suppresses real samples."""
    aram = bytes(range(256)) * 256
    ident, content = identity.identity_for_entry(aram, 0x2000, 0x2000)
    assert ident is not None and len(ident) == sampleid.ID_LENGTH
    assert content is not None


def test_an_undecodable_block_yields_no_identity():
    ident, content = identity.identity_for_entry(b"\x00" * 4, 2, 2)
    assert (ident, content) == (None, None)


def test_content_hash_ignores_the_loop_point_but_identity_does_not():
    """Both questions are needed and they differ: on Super Turrican 16,195
    attacks differ in CONTENT while only 10 differ in loop alone."""
    data = [1, -2, 3, 4]
    assert identity.content_hash(data) == identity.content_hash(list(data))
    assert sampleid.sample_id(data, 0) != sampleid.sample_id(data, 2)


def test_content_hash_accepts_signed_pcm():
    """`bytes()` raises on negative samples, and a bare `except` around it
    once made all 38,440 attacks read as content_unresolved."""
    assert isinstance(identity.content_hash([-32768, 32767, -1]), int)
