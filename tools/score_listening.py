#!/usr/bin/env python3
"""Score the blinded listening observations against the answer key.

    score_listening.py <observations.md> <answer_key.json> <result.json>

Two populations are scored separately and must not be pooled.

    NULL CONTROLS   the two candidates are byte-identical, so any claim that
                    one is closer to the reference is a false positive. These
                    measure the PROCEDURE, not the data. A listener who
                    discriminates here invalidates their own signal scores.
    SIGNAL          the candidates differ only in sample identity. Here the
                    question is whether the corrected assignment is chosen.

"cannot tell" and "no difference detected" both count as NOT discriminating.
They are correct on a null control and uninformative on a signal excerpt --
never wrong, and never evidence for the correction either.

The binomial p-value is reported for the signal excerpts alone, under the
null that the listener is guessing. With four excerpts the floor is 0.0625,
so a unanimous result is suggestive and cannot be conclusive on its own.
That limit is a property of the experiment's size and is stated rather than
glossed.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

NOT_DISCRIMINATING = {"no difference detected", "cannot tell"}


def parse(form: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    current = None
    for line in form.splitlines():
        header = re.match(r"^##\s+(ex\d+)\b", line)
        if header:
            current = header.group(1)
            out[current] = {}
            continue
        if current and line.startswith("|") and line.count("|") >= 3:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in ("field", "---"):
                key = cells[0].lower()
                if not set(key) <= set("-"):
                    out[current][key] = cells[1]
    return out


def binom_at_least(k: int, n: int, p: float = 0.5) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i)
               for i in range(k, n + 1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("observations", type=Path)
    ap.add_argument("answer_key", type=Path)
    ap.add_argument("result", type=Path)
    args = ap.parse_args()

    obs = parse(args.observations.read_text())
    key = {e["excerpt_id"]: e
           for e in json.loads(args.answer_key.read_text())["excerpts"]}

    rows = []
    for ex in sorted(key):
        answer = obs.get(ex, {})
        choice = (answer.get("closer to reference") or "").strip()
        k = key[ex]
        discriminated = choice.lower() not in NOT_DISCRIMINATING and choice
        picked = None
        if discriminated and choice in ("X", "Y"):
            picked = k[choice]
        rows.append({
            "excerpt_id": ex,
            "stratum": k["stratum"],
            "track_id": k["track_id"],
            "game": k["game"],
            "candidates_identical": k["candidates_identical"],
            "choice": choice,
            "confidence": answer.get("confidence", ""),
            "kind": answer.get("kind of difference", ""),
            "comment": (answer.get("what you heard")
                        or answer.get("where (seconds into excerpt)") or ""),
            "discriminated": bool(discriminated),
            "picked": picked,
            "attacks_changed": k["attacks_changed"],
            "notes_only_in_corrected": k["notes_present_only_in_corrected"],
        })

    nulls = [r for r in rows if r["candidates_identical"]]
    signal = [r for r in rows if not r["candidates_identical"]]
    false_positives = [r for r in nulls if r["discriminated"]]
    picked_corrected = [r for r in signal if r["picked"] == "corrected"]
    picked_baseline = [r for r in signal if r["picked"] == "baseline"]
    abstained = [r for r in signal if r["picked"] is None]

    decided = len(picked_corrected) + len(picked_baseline)
    p = (binom_at_least(len(picked_corrected), decided)
         if decided else None)

    if false_positives:
        verdict = (
            f"PROCEDURE NOT VALIDATED: {len(false_positives)} of "
            f"{len(nulls)} null controls were discriminated, though their "
            f"candidates are byte-identical. The signal scores cannot be "
            f"interpreted."
        )
    elif decided == 0:
        verdict = ("INCONCLUSIVE: no signal excerpt was discriminated.")
    elif len(picked_baseline) == 0:
        verdict = (
            f"CORRECTION SUPPORTED: {len(picked_corrected)}/{decided} signal "
            f"excerpts chose the corrected assignment as closer to the "
            f"original, with 0 false positives across {len(nulls)} "
            f"byte-identical null controls (one-tailed p = {p:.4f})."
        )
    else:
        verdict = (
            f"MIXED: corrected chosen {len(picked_corrected)}/{decided}, "
            f"baseline chosen {len(picked_baseline)}/{decided} "
            f"(one-tailed p = {p:.4f})."
        )

    args.result.write_text(json.dumps({
        "schema": "snesmdb.listening_result.v1",
        "verdict": verdict,
        "null_controls": {
            "count": len(nulls),
            "false_positives": len(false_positives),
            "excerpts_discriminated": [r["excerpt_id"]
                                       for r in false_positives],
        },
        "signal": {
            "count": len(signal),
            "chose_corrected": len(picked_corrected),
            "chose_baseline": len(picked_baseline),
            "abstained": len(abstained),
            "one_tailed_p": p,
            "p_floor_at_this_size": binom_at_least(len(signal), len(signal))
            if signal else None,
        },
        "limits": [
            "Four signal excerpts put the binomial floor at p = 0.0625, so "
            "a unanimous result is suggestive and not conclusive alone.",
            "One listener. No inter-rater agreement is measurable.",
            "All four signal excerpts are Super Turrican, because only 21 "
            "clean windows exist corpus-wide and the affected population is "
            "almost entirely one game.",
            "The loop_only stratum could not be populated at all.",
            "A loudness difference between candidates can drive a 'closer' "
            "judgement without timbral correctness; where a comment cites "
            "loudness, the judgement rests partly on that cue.",
        ],
        "rows": rows,
    }, indent=2))

    print(verdict)
    print(f"\nnull controls: {len(nulls)}, false positives: "
          f"{len(false_positives)}")
    print(f"signal: corrected {len(picked_corrected)}, baseline "
          f"{len(picked_baseline)}, abstained {len(abstained)}")
    print()
    for r in rows:
        mark = "" if r["candidates_identical"] else " *"
        print(f"  {r['excerpt_id']}{mark:2} {r['stratum']:16} "
              f"choice={r['choice']:22} -> {str(r['picked']):10} "
              f"{r['confidence']}")


if __name__ == "__main__":
    main()
