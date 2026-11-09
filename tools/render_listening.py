#!/usr/bin/env python3
"""Build the blinded listening experiment's audio into a private directory.

    render_listening.py <plan.json> <rows.jsonl...> <dist-dir> <spc-dir>
                        <scratch-dir> [--seconds-pad 2]

Produces, per excerpt: a reference render of the original SPC, and two
candidate renders that differ ONLY in which sample each attack uses.

    reference    the original SPC, rendered by the emulator
    candidate A  published identities, from the frozen baseline
    candidate B  corrected identities, from the validated correction

Timing, duration, pitch, gain and envelope come from the published records
and are identical in both candidates. The audio itself comes from a private
sample bank decoded from the SPC's own ARAM, because `sample_id` is a
CONTENT HASH and not audio -- it can select a sample but cannot supply one.

LICENSING. Every file written here is derived from a copyrighted game rip.
Nothing is written inside a git work tree, nothing is committed, and only
the plan, the answer key and the observations are intended to outlive the
session. The tool refuses to run against a scratch directory inside a
repository.

NO SUBSTITUTION. An attack whose corrected identity is unresolved gets no
sample in candidate B. It is counted, not filled. The excerpt plan already
excludes windows containing such attacks from every stratum, so these
counters should read zero; they exist so that a selection mistake shows up
as a number instead of as a plausible-sounding render.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import brr, identity, render as rnd, spcfile  # noqa: E402

PRODUCTION = ROOT / "build" / "spc_dump"


def refuse_if_in_repo(path: Path) -> None:
    """Audio derived from a rip must not be able to reach a commit."""
    probe = path.resolve()
    for parent in [probe] + list(probe.parents):
        if (parent / ".git").exists():
            raise SystemExit(
                f"refusing to write audio into a git work tree: {parent}. "
                f"These renders are derived from copyrighted SPC rips and "
                f"must stay outside the repository."
            )


def build_bank(aram: bytes, page: int, srcns: set[int],
               extra: set[tuple[int, int]]) -> dict[str, rnd.Sample]:
    """The private sample bank: canonical identity -> decoded audio.

    Two sources, because the two candidates reference different samples:
    the SPC's initial directory supplies the baseline's identities, and the
    runtime-committed `(start, loop)` pairs supply the correction's. Both go
    through `identity.identity_for_entry`, so an implausible entry yields no
    bank entry rather than a hash of unwritten memory.
    """
    # ALL 256 entries, not just the SRCNs the current manifest lists.
    # The frozen baseline was published from an earlier manifest, so six of
    # its identities were unreachable from today's `samples` set and
    # candidate A fell silent on those notes -- an asymmetry a listener
    # would hear as a difference that has nothing to do with identity.
    # Scanning the whole table is still only this track's own ARAM.
    pairs: set[tuple[int, int]] = set(extra)
    for srcn, entry in brr.read_directory(
            aram, page, set(range(256)) | set(srcns)).items():
        pairs.add((entry.start, entry.loop))
    bank: dict[str, rnd.Sample] = {}
    for start, loop in sorted(pairs):
        ident, _ = identity.identity_for_entry(aram, start, loop)
        if ident is None or ident in bank:
            continue
        decoded = brr.decode(aram, start, loop)
        bank[ident] = rnd.Sample(pcm=tuple(decoded.data),
                                 loop_offset=decoded.loop_offset)
    return bank


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("plan", type=Path)
    p.add_argument("rows", type=Path, nargs="+")
    p.add_argument("dist_dir", type=Path)
    p.add_argument("spc_dir", type=Path)
    p.add_argument("scratch", type=Path)
    p.add_argument("--seconds-pad", type=float, default=2.0)
    args = p.parse_args()

    refuse_if_in_repo(args.scratch)
    audio = args.scratch / "audio"
    if audio.exists():
        shutil.rmtree(audio)
    audio.mkdir(parents=True)

    plan = json.loads(args.plan.read_text())
    index = json.loads((args.dist_dir / "index.json").read_text())
    pub = {e["track_id"]: e for e in index["tracks"]}
    spcs = {q.name: q for q in args.spc_dir.rglob("*.spc")}
    manifest = {json.loads(l)["track_id"]: json.loads(l)
                for l in (ROOT / "data" / "out" / "manifest.jsonl")
                .read_text().splitlines() if l.strip()}

    byattack: dict[tuple[str, int, int], dict] = {}
    for path in args.rows:
        for line in path.open():
            row = json.loads(line)
            byattack[(row["track_id"], int(row["voice"]),
                      int(row["ordinal"]))] = row

    rng = random.Random(plan["seed"])
    key: list[dict] = []
    results: list[dict] = []
    failures: list[str] = []

    for ex in plan["excerpts"]:
        tid = ex["track_id"]
        src = spcs[manifest[tid]["source"]]
        spc = spcfile.load(src)
        window = float(ex["window_sec"])
        t0 = float(ex["start_sec"])
        end = t0 + window

        table = json.loads(gzip.decompress(
            (args.dist_dir / pub[tid]["events"]).read_bytes()))

        # Assemble the two candidates' event lists. Identical in every
        # field except `sample_id`.
        ordinals: collections.Counter = collections.Counter()
        a_events: list[rnd.Event] = []
        b_events: list[rnd.Event] = []
        committed: set[tuple[int, int]] = set()
        srcns = {int(k) for k in (manifest[tid].get("samples") or {})}
        unresolved_in_b = 0
        for event in table["events"]:
            if event["origin"] != "key_on":
                continue
            voice = int(event["voice"])
            ordinal = ordinals[voice]
            ordinals[voice] += 1
            onset = float(event["onset_sec"])
            if not (t0 <= onset < end):
                continue
            row = byattack.get((tid, voice, ordinal))
            base = dict(
                onset_sec=onset - t0,
                duration_sec=float(event["duration_sec"] or 0),
                voice=voice,
                pitch_register=int(event["pitch_register"] or 0),
                attack_level=int(event["attack_level"] or 0),
                sustain_level=int(event["sustain_level"] or 0),
            )
            # Normalise "" to None at the boundary: the published records
            # use both spellings for "no identity".
            published = event["sample_id"] or None
            a_events.append(rnd.Event(sample_id=published, **base))

            corrected = published
            if row is not None:
                start, loop = row.get("commit_start"), row.get("commit_loop")
                if start is None:
                    corrected = published
                elif not identity.plausible_entry((start, loop)):
                    corrected = None          # never substituted
                    unresolved_in_b += 1
                else:
                    corrected = row.get("now") or None
                    committed.add((start, loop))
            b_events.append(rnd.Event(sample_id=corrected, **base))

        bank = build_bank(spc.aram, spc.dsp[0x5D], srcns, committed)
        a = rnd.render(a_events, bank, window)
        b = rnd.render(b_events, bank, window)

        # Reference: the emulator's own output, sliced to the window.
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "r.wav"
            log = Path(tmp) / "r.jsonl"
            subprocess.run(
                [str(PRODUCTION), str(src), str(log),
                 str(int(end + args.seconds_pad)), "--wav", str(wav)],
                capture_output=True, timeout=3600,
            )
            raw = wav.read_bytes()[44:]
        # The emulator writes 16-bit stereo at 32 kHz; take the left channel
        # so the reference is mono like the candidates.
        frames = len(raw) // 4
        left = [int.from_bytes(raw[i * 4:i * 4 + 2], "little", signed=True)
                for i in range(frames)]
        lo = int(t0 * rnd.SAMPLE_RATE)
        hi = min(len(left), lo + int(window * rnd.SAMPLE_RATE))
        reference = left[lo:hi] if lo < len(left) else []

        # Blind labels: which of X / Y is the baseline is decided by the
        # plan's seed and recorded only in the answer key.
        swap = rng.random() < 0.5
        x_pcm, y_pcm = (b.pcm, a.pcm) if swap else (a.pcm, b.pcm)
        names = {
            f"{ex['excerpt_id']}-reference.wav": reference,
            f"{ex['excerpt_id']}-X.wav": x_pcm,
            f"{ex['excerpt_id']}-Y.wav": y_pcm,
        }
        for name, pcm in names.items():
            (audio / name).write_bytes(rnd.wav_bytes(list(pcm)))

        # DECLARED ASYMMETRY. Where the baseline had no identity and the
        # correction establishes one, candidate A is silent and B plays. That
        # is a genuine result of the correction -- a recovered note -- but a
        # listener hears "a note appeared", not "a timbre changed", and the
        # two must not be scored as the same observation. Excluding these
        # windows would hide the correction's main benefit, so they are kept
        # and the count is published in the plan and the key instead.
        recovered_in_b = max(
            0, a.skipped_unresolved_identity - b.skipped_unresolved_identity)
        lost_in_b = max(
            0, b.skipped_unresolved_identity - a.skipped_unresolved_identity)
        identical = a.pcm == b.pcm
        # The null strata are identical BY CONSTRUCTION. Checked, not assumed.
        if ex["stratum"].startswith("null_") and not identical:
            failures.append(
                f"{ex['excerpt_id']} ({ex['stratum']}): candidates differ "
                f"but this stratum has no corrected identities, so A and B "
                f"must be byte-identical"
            )
        if ex["stratum"] == "content_differs" and identical:
            failures.append(
                f"{ex['excerpt_id']} (content_differs): candidates are "
                f"byte-identical, so nothing is being tested here"
            )
        if a.skipped_identity_not_in_bank or b.skipped_identity_not_in_bank:
            failures.append(
                f"{ex['excerpt_id']}: {a.skipped_identity_not_in_bank} "
                f"baseline and {b.skipped_identity_not_in_bank} corrected "
                f"identities are absent from the private bank, so one "
                f"candidate falls silent where the other plays -- an "
                f"asymmetry unrelated to sample identity"
            )
        if unresolved_in_b:
            failures.append(
                f"{ex['excerpt_id']}: {unresolved_in_b} attacks have no "
                f"corrected identity; the plan should have excluded this "
                f"window"
            )

        key.append({
            "excerpt_id": ex["excerpt_id"],
            "stratum": ex["stratum"],
            "track_id": tid, "game": ex["game"],
            "start_sec": t0, "window_sec": window,
            "X": "corrected" if swap else "baseline",
            "Y": "baseline" if swap else "corrected",
            "candidates_identical": identical,
            "expected_audible_difference": ex["stratum"] == "content_differs",
            "attacks_in_window": ex["attacks_in_window"],
            "attacks_changed": ex["attacks_changed"],
            "notes_present_only_in_corrected": recovered_in_b,
            "notes_present_only_in_baseline": lost_in_b,
            "difference_kinds_expected": [
                k for k, on in (
                    ("timbre_changed", ex["attacks_changed"] > 0),
                    ("note_appears_in_one_candidate",
                     recovered_in_b > 0 or lost_in_b > 0),
                ) if on
            ],
        })
        results.append({
            "excerpt_id": ex["excerpt_id"],
            "stratum": ex["stratum"],
            "bank_size": len(bank),
            "baseline": {"rendered": a.rendered, "skipped": a.skipped,
                         "unresolved": a.skipped_unresolved_identity,
                         "not_in_bank": a.skipped_identity_not_in_bank,
                         "unusable_event": a.skipped_unusable_event},
            "corrected": {"rendered": b.rendered, "skipped": b.skipped,
                          "unresolved": b.skipped_unresolved_identity,
                          "not_in_bank": b.skipped_identity_not_in_bank,
                          "unusable_event": b.skipped_unusable_event},
            "candidates_identical": identical,
            "notes_present_only_in_corrected": recovered_in_b,
            "notes_present_only_in_baseline": lost_in_b,
            "reference_samples": len(reference),
            "sha256": {n: hashlib.sha256(
                (audio / n).read_bytes()).hexdigest()[:16] for n in names},
        })
        print(f"  {ex['excerpt_id']} {ex['stratum']:16} "
              f"A rendered {a.rendered:4}/skipped {a.skipped:3}  "
              f"B rendered {b.rendered:4}/skipped {b.skipped:3}  "
              f"identical={identical}")

    (args.scratch / "answer_key.json").write_text(json.dumps({
        "schema": "snesmdb.listening_key.v1",
        "seed": plan["seed"],
        "warning": "Do not read before recording observations.",
        "excerpts": key,
    }, indent=1))
    (args.scratch / "render_report.json").write_text(json.dumps({
        "schema": "snesmdb.listening_render.v1",
        "excerpts": results,
        "consistency_failures": failures,
    }, indent=1))

    print(f"\naudio: {audio}")
    print(f"answer key: {args.scratch / 'answer_key.json'}")
    if failures:
        print(f"\n{len(failures)} CONSISTENCY FAILURES:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("\nconsistency checks passed: every null-control pair is "
          "byte-identical, every signal pair differs, no event was "
          "rendered with a substituted sample")


if __name__ == "__main__":
    main()
