"""The licensing and citation documents must stay true, not just present.

Every claim in this file was wrong at some point in this repository's
history, which is why each is asserted rather than trusted:

  * `LICENSE` once carried an appended "SCOPE OF THIS LICENSE" section.
    Conditions bolted onto MIT make the license non-standard and break the
    automated tooling reviewers rely on, so the boundaries live in
    `RIGHTS.md` and the license text stays verbatim.
  * `CITATION.cff` once named "SNES-MDB contributors" with a `TODO`. A
    fabricated author entity is worse than a missing file.
  * The vendored LGPL file once said its single hook was "the ONLY
    modification". There are three. A change notice that undercounts the
    changes is not a change notice.
  * `make verify-vendor` once diffed against a file in `/tmp`, with `||
    true` swallowing the failure. An LGPL change claim has to be checkable
    by whoever received the copy, not only on the author's machine.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The MIT license body, verbatim from https://opensource.org/license/mit,
#: with only the copyright line removed. `LICENSE` must contain exactly this
#: plus a copyright line, and nothing else.
MIT_BODY = """\
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

VENDOR = ROOT / "vendor" / "snes_spc"
MODIFIED = VENDOR / "snes_spc" / "SPC_DSP.cpp"
UPSTREAM = VENDOR / "upstream" / "SPC_DSP.cpp"

HOOKS = ("SPC_DSP_SAMPLE_HOOK", "SPC_DSP_KON_HOOK", "SPC_DSP_LOOP_HOOK")


def read(path: Path) -> str:
    return path.read_text()


# --------------------------------------------------------------- LICENSE

def test_license_is_unmodified_mit():
    """No custom conditions, no appended scope section, no edits."""
    text = read(ROOT / "LICENSE")
    body = text.replace("MIT License\n", "", 1).strip()
    lines = body.splitlines()
    assert lines[0].startswith("Copyright (c) "), lines[0]
    rest = "\n".join(lines[1:]).strip()
    assert rest == MIT_BODY, "\n".join(difflib.unified_diff(
        MIT_BODY.splitlines(), rest.splitlines(),
        "canonical MIT", "LICENSE", lineterm=""))


def test_license_names_a_holder_and_a_year():
    text = read(ROOT / "LICENSE")
    match = re.search(r"Copyright \(c\) (\d{4})(?:-\d{4})? (.+)", text)
    assert match, "no parseable copyright line"
    year, holder = match.group(1), match.group(2).strip()
    assert 2026 <= int(year) <= 2100, year
    # A collective noun with no legal person behind it is a placeholder.
    assert holder.lower() not in ("contributors", "snes-mdb contributors",
                                  "the authors", "todo"), holder


def test_there_is_exactly_one_license_file_at_the_root():
    """Two MIT files disagreed for five days and no test noticed.

    `LICENSE.txt` predated `LICENSE`, named a different copyright holder
    ("snesmdb contributors"), carried the appended scope text that now lives
    in RIGHTS.md, and asserted the vendored emulator was "kept
    byte-identical to upstream" -- false since the three hooks landed. It was
    referenced by nothing and shipped in nothing, so it was removable, but
    the earlier version of this file only checked `LICENSE` and so could not
    have found it. Two license files is itself the defect: a reader and a
    license scanner can reach different conclusions about the same code.
    """
    found = sorted(p.name for p in ROOT.iterdir()
                   if p.is_file() and p.name.upper().startswith("LICEN"))
    assert found == ["LICENSE"], (
        f"expected exactly one root license file, found {found}")


def test_license_carries_no_extra_sections():
    text = read(ROOT / "LICENSE")
    for banned in ("SCOPE OF THIS LICENSE", "subject to the following "
                   "additional", "NOT COVER", "does NOT cover"):
        assert banned not in text, f"custom restriction in LICENSE: {banned}"


# ---------------------------------------------------------------- RIGHTS

def test_rights_doc_covers_every_boundary():
    """RIGHTS.md, not LICENSE, is where the four exclusions are explained."""
    text = read(ROOT / "RIGHTS.md")
    for topic in ("musical composition", "symbolic dataset", "SPC file",
                  "vendor/snes_spc", "LGPL-2.1"):
        assert topic.lower() in text.lower(), f"RIGHTS.md omits {topic}"


def test_rights_doc_does_not_assert_a_data_license():
    """The data terms are unresolved; saying otherwise would overclaim."""
    text = read(ROOT / "RIGHTS.md")
    assert "unresolved" in text.lower()
    assert not re.search(r"(dataset|corpus|data)\s+is\s+MIT", text, re.I)


# -------------------------------------------------------------- CITATION

def test_citation_has_no_placeholder_author():
    text = read(ROOT / "CITATION.cff")
    assert "authors:" in text
    for bad in ("TODO", "FIXME", "XXX", "placeholder",
                "SNES-MDB contributors"):
        assert bad not in text, f"placeholder in CITATION.cff: {bad}"


def test_citation_author_is_a_valid_cff_entity():
    """CFF requires either a person (family-names) or an entity (name)."""
    text = read(ROOT / "CITATION.cff")
    block = text.split("authors:", 1)[1].split("\nversion:", 1)[0]
    assert "family-names:" in block or re.search(r"^\s+-\s+name:", block,
                                                 re.M), block


def test_citation_version_is_a_software_version_not_a_corpus_label():
    """`type: software`, so `version` must describe the software.

    An earlier draft put `snesmdb-50game-rc1` here. A reader would have
    cited the frozen dataset while the entry described the code, and the two
    version in different units -- the corpus label advances with each
    expansion, the toolkit's version does not.
    """
    text = read(ROOT / "CITATION.cff")
    match = re.search(r'^version:\s*"?([^"\n]+)"?', text, re.M)
    assert match, "CITATION.cff states no version"
    version = match.group(1).strip()
    assert not re.match(r"^(snesmdb-|expansion-|gate\d)", version), (
        f"version {version!r} is a corpus release label, not a software "
        f"version")
    assert re.match(r"^\d+\.\d+", version), (
        f"version {version!r} does not look like a software version")
    # The corpus release is still named, just not as the software's version.
    assert "snesmdb-50game-rc1" in text


def test_citation_omits_doi_until_assigned():
    text = read(ROOT / "CITATION.cff")
    assert not re.search(r"^doi:", text, re.M), "DOI asserted but not assigned"


def test_citation_records_repository_code():
    text = read(ROOT / "CITATION.cff")
    assert 'repository-code: "https://github.com/uestraven/snesmdb"' in text


def test_citation_does_not_redirect_citers_to_nes_mdb():
    """NES-MDB is an acknowledgement, not a substitute citation."""
    text = read(ROOT / "CITATION.cff")
    message = text.split("message:", 1)[1].split("title:", 1)[0]
    # (?<!S) so SNES-MDB's own name does not match.
    assert not re.search(r"(?<!S)NES-MDB", message), (
        "the citation message directs users to cite NES-MDB; it must ask "
        "them to cite SNES-MDB")
    assert re.search(r"(?<!S)NES-MDB", text), (
        "NES-MDB must still appear as a reference")


def test_citation_required_fields_present():
    text = read(ROOT / "CITATION.cff")
    for field in ("cff-version:", "message:", "title:", "authors:",
                  "version:", "date-released:", "license:"):
        assert field in text, f"CITATION.cff missing {field}"


# --------------------------------------------------- vendor LGPL-2.1

def test_vendor_license_text_is_preserved():
    for name in ("license.txt", "LICENSE"):
        text = read(VENDOR / name)
        assert "GNU LESSER GENERAL PUBLIC LICENSE" in text.upper()
        assert "2.1" in text


def test_vendor_upstream_notices_are_preserved():
    for name in ("readme.txt", "changes.txt"):
        assert (VENDOR / name).is_file(), f"vendor/{name} removed"


def test_vendor_modification_record_exists_and_counts_three():
    text = read(VENDOR / "MODIFICATIONS.md")
    assert "LGPL-2.1" in text
    assert "2026-11-08" in text, "no modification date"
    for hook in HOOKS:
        assert hook in text, f"MODIFICATIONS.md omits {hook}"


def test_modified_vendor_file_carries_a_change_notice():
    """LGPL-2.1 section 2(a): prominent notice that the file changed, dated."""
    header = read(MODIFIED)[:4000]
    assert "MODIFIED FILE NOTICE" in header
    assert "2026-11-08" in header
    # The upstream copyright block must survive, above the added notice.
    assert "Copyright (C) 2007 Shay Green" in header
    assert header.index("Shay Green") < header.index("MODIFIED FILE NOTICE")


def test_no_vendor_file_claims_a_single_modification():
    """The stale claim that bit-rotted when hooks two and three landed."""
    for path in list(VENDOR.rglob("*.cpp")) + list(VENDOR.rglob("*.h")) + \
            list(VENDOR.rglob("*.md")):
        text = read(path)
        for stale in ("the ONLY modification", "the only modification"):
            assert stale not in text, f"{path} still claims {stale!r}"


def test_all_three_hooks_are_present_and_marked():
    text = read(MODIFIED)
    for i, hook in enumerate(HOOKS, 1):
        assert hook in text, f"{hook} missing from the vendored DSP"
    # Each site opens a comment with `/* snesmdb:`. The header notice
    # mentions the marker in prose and must not be counted as a site.
    sites = text.count("/* snesmdb:")
    assert sites == 3, f"expected 3 marked modification sites, found {sites}"


def test_hook_noop_defaults_live_outside_the_vendor_tree():
    """So vendor/ contains no snesmdb-authored code."""
    hook_h = read(ROOT / "src" / "hook.h")
    for hook in HOOKS:
        assert f"#ifndef {hook}" in hook_h, f"{hook} has no no-op default"


def test_upstream_reference_is_present_and_pristine():
    """An LGPL change notice needs the original available to the recipient."""
    assert UPSTREAM.is_file(), (
        "vendor/snes_spc/upstream/SPC_DSP.cpp missing: the modification "
        "cannot be verified by anyone who received this copy")
    text = read(UPSTREAM)
    assert "snesmdb" not in text, "the 'upstream' reference is modified"
    assert text.startswith("// snes_spc 0.9.0.")


def test_makefile_hash_matches_the_upstream_reference():
    makefile = read(ROOT / "Makefile")
    match = re.search(r"VENDOR_ORIG_SHA = ([0-9a-f]{64})", makefile)
    assert match, "Makefile declares no upstream hash"
    actual = hashlib.sha256(UPSTREAM.read_bytes()).hexdigest()
    assert match.group(1) == actual, (
        f"Makefile pins {match.group(1)} but the file hashes to {actual}")


def test_modifications_doc_quotes_the_same_hash():
    doc = read(VENDOR / "MODIFICATIONS.md")
    actual = hashlib.sha256(UPSTREAM.read_bytes()).hexdigest()
    assert actual in doc, "MODIFICATIONS.md quotes a stale hash"


def test_vendor_change_adds_lines_and_removes_none():
    """The substantive LGPL claim: no upstream logic was altered.

    Insertions only means every original line survives in order, so the
    hooks cannot have changed emulation behaviour by edit -- only by what
    the macros expand to, which `make verify-instrumentation` covers.
    """
    old = read(UPSTREAM).splitlines()
    new = read(MODIFIED).splitlines()
    removed = [line for line in difflib.unified_diff(old, new, n=0)
               if line.startswith("-") and not line.startswith("---")]
    assert not removed, (
        "lines were removed from or altered in the vendored LGPL file; "
        "MODIFICATIONS.md claims insertions only:\n" + "\n".join(removed[:10]))


def test_verify_vendor_target_fails_loudly_on_a_missing_reference():
    """`|| true` once made this target pass with no reference at all."""
    makefile = read(ROOT / "Makefile")
    body = makefile.split("verify-vendor:", 1)[1].split("\n\n", 1)[0]
    assert "/tmp/" not in body, (
        "verify-vendor references /tmp, which exists only on the author's "
        "machine")
    assert "exit 1" in body, "a missing upstream reference must be an error"


# ------------------------------------------------------------------ README

@pytest.mark.parametrize("target", ["LICENSE", "RIGHTS.md", "CITATION.cff"])
def test_readme_links_to_the_licensing_documents(target):
    readme = read(ROOT / "README.md")
    assert f"({target})" in readme, f"README does not link to {target}"


def test_readme_mentions_the_vendor_record_without_linking_to_it():
    """It is repository-only: a data distribution ships no emulator source.

    `test_no_shipped_document_links_to_something_that_is_not_shipped` would
    fail on a link, and correctly so -- a reader of a download cannot tell a
    missing file from a missing feature.
    """
    readme = read(ROOT / "README.md")
    assert "vendor/snes_spc/MODIFICATIONS.md" in readme
    assert "(vendor/snes_spc/MODIFICATIONS.md)" not in readme


@pytest.mark.parametrize("doc", ["LICENSE", "RIGHTS.md", "CITATION.cff"])
def test_the_packager_actually_ships_the_licensing_documents(doc):
    """A README link that resolves only in the checkout is a dangling link.

    Asserted against the packager's own inventory rather than a second list,
    so adding the link without adding the file fails here.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "package_toolkit", ROOT / "tools" / "package_toolkit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert doc in module.INVENTORY, (
        f"README links to {doc} but package_toolkit does not ship it")


def test_readme_states_mit_does_not_cover_the_data():
    readme = read(ROOT / "README.md")
    section = readme.split("## Licensing and the source data", 1)[1]
    assert "covers the code and nothing else" in section
    assert "RIGHTS.md" in section
