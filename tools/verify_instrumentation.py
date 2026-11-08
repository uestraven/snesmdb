#!/usr/bin/env python3
"""Prove the event-time instrumentation observes without disturbing.

    verify_instrumentation.py [--seconds 20]

The instrumented binary captures the sample-directory entry the DSP actually
consumed, at `voice_V3c` when `kon_delay == 5`. That is only useful if two
things hold, and neither may be assumed:

  1. IT CHANGES NOTHING. Rendered PCM must be bit-identical between the
     production and instrumented binaries, compared on the sample bytes
     rather than on file headers.
  2. EVENTS MATCH ATTACKS ONE TO ONE, per voice. The plan is to pair the nth
     commit on a voice with the nth extracted key-on on that voice, and
     ordering alone does not establish that: the DSP runs KON through its own
     key-on delay, so counting register writes is not the same as counting
     committed sample starts. A repeated KON write, an ineffective one, or a
     rapid retrigger could shift every later pairing by one and corrupt every
     sample identity after it. A mismatch must FAIL here rather than
     propagate silently.

Three contrasting drivers are checked because each stresses a different part:
Super Turrican replaces directory entries continuously, Secret of Evermore
populates them gradually after capture, and Donkey Kong Country 2 has a stable
directory with SRCN values above 63.

OPEN LIMITATION, recorded not fixed: the `loop` value here is the second word
of the directory entry read at sample start. The DSP may read the loop pointer
again later, when playback reaches a BRR end block, so a loop value observed
at start is not proven to be the one eventually used. `sample_id` incorporates
loop information, so a captured loop value does not yet carry the same
evidentiary weight as the captured start pointer.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snesmdb import eventmatch, spcfile, voices  # noqa: E402

PRODUCTION = ROOT / "build" / "spc_dump"
INSTRUMENTED = ROOT / "build" / "spc_dump_evt"

#: One per contrasting driver behaviour.
CASES = (
    ("Super Turrican", "data/spc/SuperTurrican/turr-03.spc",
     "rapid directory replacement"),
    ("Secret of Evermore", "data/spc/SecretofEvermore/soe-01.spc",
     "directory populated after capture"),
    ("Donkey Kong Country 2",
     "data/spc/DonkeyKongCountry2_DiddysKongQuest/dkq-01.spc",
     "stable directory, SRCN above 63"),
)

#: A commit may precede its key-on in logged time by at most this much: the
#: timestamp is the render-chunk base, and at --chunk 1 that is one DSP frame.
CHUNK_CLOCKS = 32


def _wav_pcm(path: Path) -> bytes:
    """The sample bytes of a RIFF/WAVE file, excluding all headers."""
    raw = path.read_bytes()
    at = 12
    while at + 8 <= len(raw):
        tag = raw[at:at + 4]
        size = int.from_bytes(raw[at + 4:at + 8], "little")
        if tag == b"data":
            return raw[at + 8:at + 8 + size]
        at += 8 + size + (size & 1)
    return b""


def _run(binary: Path, spc: Path, out: Path, seconds: int,
         wav: Path | None = None, chunk: int | None = None) -> None:
    cmd = [str(binary), str(spc), str(out), str(seconds)]
    if wav:
        cmd += ["--wav", str(wav)]
    if chunk:
        cmd += ["--chunk", str(chunk)]
    subprocess.run(cmd, capture_output=True, timeout=3600, check=False)


def check(name: str, spc_path: Path, why: str, seconds: int) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        prod_log, prod_wav = t / "p.jsonl", t / "p.wav"
        evt_log, evt_wav = t / "e.jsonl", t / "e.wav"
        _run(PRODUCTION, spc_path, prod_log, seconds, prod_wav)
        _run(INSTRUMENTED, spc_path, evt_log, seconds, evt_wav)

        # 1. The instrumentation must not change the audio.
        a, b = _wav_pcm(prod_wav), _wav_pcm(evt_wav)
        if not a:
            problems.append("production render produced no PCM")
        elif a != b:
            differing = sum(1 for x, y in zip(a, b) if x != y)
            problems.append(
                f"PCM differs: {differing:,} of {len(a):,} bytes, "
                f"lengths {len(a)} vs {len(b)}"
            )

        # 2. The production binary must carry no active sample hook.
        if '"kind":"sample"' in prod_log.read_text():
            problems.append("production binary emitted sample records")

        # 3. Records must be complete and parseable.
        commits: list[dict] = []
        for line in evt_log.read_text().splitlines():
            if '"kind":"sample"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                problems.append("unparseable sample record")
                continue
            if any(k not in record for k in
                   ("t", "voice", "dir_addr", "start", "loop")):
                problems.append(f"incomplete sample record: {record}")
                continue
            commits.append(record)
        if not commits:
            problems.append("instrumented binary emitted no sample records")

        # 4. One-to-one per voice, against the extractor's own key-ons.
        #    Re-rendered at chunk 1 so a commit can be ordered against the
        #    key-on that caused it.
        fine_log = t / "f.jsonl"
        _run(INSTRUMENTED, spc_path, fine_log, seconds, chunk=1)
        fine, writes = [], []
        for line in fine_log.read_text().splitlines():
            record = json.loads(line)
            if record.get("kind") == "sample":
                fine.append(record)
            elif "addr" in record:
                writes.append(record)
        extracted = voices.extract(iter(writes))
        spc = spcfile.load(spc_path)
        outcome = eventmatch.match(
            extracted.notes, fine, spc.dsp[eventmatch.REG_KON],
            [(int(w["t"]), int(w["data"])) for w in writes
             if int(w["addr"]) == eventmatch.REG_KON],
        )
        problems.extend(outcome.problems)
        matched, excluded = len(outcome.pairs), len(outcome.excluded_startup)

    print(f"  {name:22} ({why})")
    for line in problems:
        print(f"      FAIL {line}")
    if not problems:
        print(f"      ok: PCM identical, no production hook, "
              f"{matched} attacks paired one-to-one, {excluded} replay-"
              f"initialisation commit(s) excluded by origin")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()
    for binary in (PRODUCTION, INSTRUMENTED):
        if not binary.is_file():
            raise SystemExit(f"{binary} missing -- run `make {binary.name}`")

    print("instrumentation gate")
    failures = 0
    for name, rel, why in CASES:
        spc = ROOT / rel
        if not spc.is_file():
            print(f"  {name:22} SKIP, {rel} absent")
            continue
        failures += len(check(name, spc, why, args.seconds))
    print()
    if failures:
        print(f"{failures} problem(s): the instrument is not yet trustworthy")
    else:
        print("instrumentation verified: observes without disturbing, and "
              "every DSP sample commit pairs one-to-one with an extracted "
              "key-on on the same voice")
    print("OPEN: the loop pointer captured at sample start is not proven to "
          "be the one the DSP\n      eventually uses at a BRR end block; "
          "sample_id depends on it.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
