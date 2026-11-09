#!/usr/bin/env python3
"""Account for every published attack against the MIDI export.

    midi_export_ledger.py <dist-dir> <ledger.json> [--rows rows.jsonl]

Read-only, and reads ONLY the published distribution -- the same files a
researcher downloads. It does not consult extraction records, so its figures
are reproducible by anyone holding the corpus.

"434,574 omitted" is not a finding. What a researcher needs is the
distinction between two different situations:

    FIXED PITCH ESTABLISHED, NOT EXPORTED
        a usable fixed-pitch estimate exists in the published events and no
        MIDI note carries it. This is recoverable, and an exporter concern.

    NO USABLE FIXED PITCH ESTABLISHED
        the published representation does not give a single MIDI note to
        write. Writing one would fabricate it.

The second category is NOT a claim that the underlying sound was unpitched.
`unrecoverable` means the pipeline could not determine a pitch, and some of
those events may well have been pitched; `pitch_modulated` may be musically
pitched material whose changing pitch one static note cannot represent;
only `noise` genuinely lacks a fixed melodic pitch. So the honest conclusion
is that **no additional recoverable fixed-pitch omissions are demonstrated**
-- the rest preserve uncertainty rather than resolve it.

So every attack is classified against the exporter's actual rule, and the
ledger must RECONCILE: classified attacks must equal published attacks. The
exporter's own counters do not reconcile -- `midi_notes_dropped` sums the
unpitched and out-of-range drops and omits the bad-voice drops, and tracks
with no MIDI file at all contribute to no counter -- which is why this
counts from the events rather than trusting them.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path

#: The exporter's rule, mirrored exactly. See `snesmdb.midi`.
#: MIDI note numbers span 0..127; an earlier bound of 1..127 here and in the
#: exporter discarded note 0, a valid note, for four attacks.
N_VOICES = 8
MIDI_LOW, MIDI_HIGH = 0, 127


def count_note_ons(path: Path) -> int:
    """Note-on events in a MIDI file, parsed from the bytes.

    The ledger's written count is checked against THIS rather than against
    any counter the exporter kept, because a counter and the file it
    describes are two different artifacts and only one of them is what a
    researcher loads. Running-status is handled; a note-on with velocity 0
    is a note-off and is not counted.
    """
    data = path.read_bytes()
    total = 0
    pos = 0
    while pos + 8 <= len(data):
        kind = data[pos:pos + 4]
        length = int.from_bytes(data[pos + 4:pos + 8], "big")
        body = data[pos + 8:pos + 8 + length]
        pos += 8 + length
        if kind != b"MTrk":
            continue
        i = 0
        status = 0
        while i < len(body):
            # delta time
            while i < len(body) and body[i] & 0x80:
                i += 1
            i += 1
            if i >= len(body):
                break
            byte = body[i]
            if byte & 0x80:
                status = byte
                i += 1
            if status == 0xFF:                      # meta
                if i >= len(body):
                    break
                i += 1                              # type
                size = 0
                while i < len(body) and body[i] & 0x80:
                    size = (size << 7) | (body[i] & 0x7F)
                    i += 1
                if i < len(body):
                    size = (size << 7) | (body[i] & 0x7F)
                    i += 1
                i += size
                continue
            high = status & 0xF0
            if high in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                if i + 1 < len(body) and high == 0x90 and body[i + 1] != 0:
                    total += 1
                i += 2
            elif high in (0xC0, 0xD0):
                i += 1
            else:
                break
    return total


def classify(event: dict, has_midi_file: bool) -> tuple[str, str]:
    """`(disposition, reason)` for one attack under the exporter's rule."""
    if not has_midi_file:
        # The whole track has no MIDI file, so its attacks are absent from
        # the export without the exporter ever counting them.
        return ("omitted", "track_has_no_midi_file")
    voice = int(event.get("voice", -1))
    if not 0 <= voice < N_VOICES:
        return ("omitted", "voice_outside_exported_range")
    midi = event.get("midi_note")
    if midi is None:
        return ("omitted", "no_pitch_recovered")
    if not MIDI_LOW <= int(round(float(midi))) <= MIDI_HIGH:
        return ("omitted", "pitch_outside_midi_range")
    return ("written", "")


#: Whether an omission is a representational limit or a potential defect.
#: Stated here so the judgement is reviewable rather than buried in prose.
INTERPRETATION = {
    "no_pitch_recovered": (
        "NO USABLE FIXED PITCH ESTABLISHED, which is not the same as "
        "'not a pitched event'. `unrecoverable` means the pipeline could "
        "not determine a pitch and some of these sounds may have been "
        "pitched; `pitch_modulated` may be pitched material no single MIDI "
        "note can represent; only `noise` genuinely lacks a fixed melodic "
        "pitch. Writing a note would fabricate one, so these preserve the "
        "uncertainty instead. The events remain in events.v4."
    ),
    "pitch_outside_midi_range": (
        "FIXED PITCH ESTABLISHED, NOT EXPORTED. The pitch was recovered but falls outside MIDI's 1..127. "
        "Some of these are genuine sub-contra or ultrasonic content; some "
        "are residual octave errors in fundamental estimation. Either way "
        "the event exists in events.v4 and MIDI cannot address it."
    ),
    "voice_outside_exported_range": (
        "NOT EXPORTED, and an exporter limit rather than a hardware one: the S-DSP "
        "has exactly 8 voices, so a voice outside 0..7 indicates an event "
        "the export cannot place. Counted by the exporter but NOT included "
        "in its published `midi_notes_dropped` total."
    ),
    "track_has_no_midi_file": (
        "NOT EXPORTED AT TRACK LEVEL. No MIDI file exists for the track, so no exporter "
        "counter ever saw these attacks. Usually a track with no pitched "
        "events at all, where an empty MIDI would be misleading -- but the "
        "attacks are real and are in events.v4."
    ),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist", type=Path)
    ap.add_argument("ledger", type=Path)
    ap.add_argument("--rows", type=Path)
    args = ap.parse_args()

    index = json.loads((args.dist / "index.json").read_text())
    tracks = index["tracks"]

    disposition: collections.Counter = collections.Counter()
    reasons: collections.Counter = collections.Counter()
    by_status: collections.Counter = collections.Counter()
    by_reason_status: collections.Counter = collections.Counter()
    per_track: list[dict] = []
    index_attacks = 0
    note_ons = 0
    note_zero = 0
    sink = args.rows.open("w") if args.rows else None

    for entry in tracks:
        table = json.loads(gzip.decompress(
            (args.dist / entry["events"]).read_bytes()))
        has_midi = bool(entry.get("midi"))
        index_attacks += int(entry.get("attack_count") or 0)
        counts: collections.Counter = collections.Counter()
        for event in table["events"]:
            if event["origin"] != "key_on":
                continue
            where, why = classify(event, has_midi)
            if (where == "written" and event.get("midi_note") is not None
                    and int(round(float(event["midi_note"]))) == 0):
                # Note 0 is valid MIDI, but the exporter that produced any
                # already-frozen tree gated on 1..127 and discarded it. Held
                # separately so a mismatch against an older artifact is
                # ATTRIBUTABLE rather than merely reported.
                note_zero += 1
            status = event.get("pitch_status")
            disposition[where] += 1
            by_status[(where, status)] += 1
            counts[where] += 1
            if where == "omitted":
                reasons[why] += 1
                by_reason_status[(why, status)] += 1
                counts[why] += 1
        if has_midi:
            note_ons += count_note_ons(args.dist / entry["midi"])
        per_track.append({
            "track_id": entry["track_id"],
            "game": entry.get("game"),
            "track_class": entry.get("track_class"),
            "has_midi_file": has_midi,
            "attacks": int(entry.get("attack_count") or 0),
            "written": counts["written"],
            "omitted": counts["omitted"],
            "reasons": {k: v for k, v in counts.items()
                        if k not in ("written", "omitted")},
        })
        if sink:
            sink.write(json.dumps(per_track[-1]) + "\n")
    if sink:
        sink.close()

    classified = disposition["written"] + disposition["omitted"]
    reconciles = classified == index_attacks

    # The actionable quantity: an omission whose published pitch_status is
    # `estimated`, i.e. a usable fixed pitch exists and no note carries it.
    with_estimate = sum(n for (r, st), n in by_reason_status.items()
                        if st == "estimated")
    without_estimate = disposition["omitted"] - with_estimate

    args.ledger.write_text(json.dumps({
        "schema": "snesmdb.midi_ledger.v1",
        "written_predicted_by_current_rule": disposition["written"],
        "note_ons_observed_in_midi_files": note_ons,
        "written_minus_observed": disposition["written"] - note_ons,
        "attacks_rounding_to_midi_note_zero": note_zero,
        "difference_fully_attributed_to_note_zero": (
            disposition["written"] - note_ons == note_zero),
        "note_on_check": (
            "The written count is checked against note-on events parsed "
            "from the MIDI files, not against any exporter counter. A tree "
            "produced before the 0..127 bound was corrected contains "
            "exactly `attacks_rounding_to_midi_note_zero` fewer note-ons "
            "than the current rule predicts; that is the expected and fully "
            "attributed difference, and any OTHER difference is a defect."
        ),
        "dist": str(args.dist),
        "reconciles": reconciles,
        "published_attacks": index_attacks,
        "attacks_classified": classified,
        "written_to_midi": disposition["written"],
        "omitted_from_midi": disposition["omitted"],
        "omissions_by_reason": dict(reasons),
        "omissions_by_reason_and_pitch_status": {
            f"{r}|{s}": n for (r, s), n in by_reason_status.items()},
        "disposition_by_pitch_status": {
            f"{d}|{s}": n for (d, s), n in by_status.items()},
        "omitted_with_a_fixed_pitch_estimate": with_estimate,
        "omitted_without_a_fixed_pitch_estimate": without_estimate,
        "conclusion": (
            f"{with_estimate} omitted attacks carry a usable fixed-pitch "
            f"estimate. The remaining {without_estimate:,} have no single "
            f"MIDI note to write; that preserves uncertainty and is not a "
            f"claim the underlying sounds were unpitched."
        ),
        "interpretation": INTERPRETATION,
        "tracks": per_track,
    }, indent=1))

    print(f"published attacks   {index_attacks:>10,}")
    print(f"classified          {classified:>10,}   "
          f"{'RECONCILES' if reconciles else 'DOES NOT RECONCILE'}")
    print(f"written to MIDI     {disposition['written']:>10,}   "
          f"{100*disposition['written']/index_attacks:.2f}%")
    print(f"omitted             {disposition['omitted']:>10,}   "
          f"{100*disposition['omitted']/index_attacks:.2f}%")
    gap = disposition["written"] - note_ons
    verdict = ("MATCHES" if gap == 0 else
               f"differs by {gap:+,}, fully attributed to MIDI note 0"
               if gap == note_zero else
               f"differs by {gap:+,}, NOT attributable -- defect")
    print(f"note-ons in files   {note_ons:>10,}   {verdict}")
    print(f"  attacks rounding to note 0: {note_zero}  "
          f"(valid MIDI; discarded by the superseded 1..127 bound)\n")
    print("omissions by reason:")
    for reason, n in reasons.most_common():
        print(f"  {reason:34} {n:>9,}")
    print(f"\n  omitted WITH a fixed-pitch estimate    {with_estimate:>9,}"
          f"   <- recoverable, exporter concern")
    print(f"  omitted WITHOUT one                    "
          f"{without_estimate:>9,}   <- no single note to write; "
          f"uncertainty preserved")
    print("\nomissions by reason x published pitch_status:")
    for (reason, status), n in sorted(by_reason_status.items(),
                                      key=lambda kv: -kv[1]):
        print(f"  {reason:34} {str(status):18} {n:>9,}")
    if not reconciles:
        raise SystemExit(
            f"ledger does not reconcile: {classified:,} classified vs "
            f"{index_attacks:,} published")


if __name__ == "__main__":
    main()
