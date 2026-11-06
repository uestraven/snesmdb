#!/usr/bin/env python3
"""Emit a listening set for judging inferred grids by ear.

    grid_calibration.py <out-dir> <dist-dir> [--per-band 4] [--seed 0]

Milestone 4 has no ground truth, and `fit` is not a measure of musical
correctness. It counts the fraction of onsets within 10% of a grid line, which
comes apart from "is this the beat" in both directions:

  * high fit, wrong grid -- "Dancing Mad" alternates between 17.0 and 5.7
    rows/s, a ratio of 2.98, which is the same passage read as beats or as
    triplets. Both score well. Fit cannot say which is the beat.
  * low fit, right grid -- ornamented or syncopated music decorates a correct
    meter with off-grid onsets.

NES-MDB never faced this because the grid was GIVEN: music there advances on a
universal 60.0988 Hz frame. On the SNES the meter has to be inferred, and SNES
music is doing considerably more.

So this produces something a listener can judge. Per track, a MIDI file with
the music on channels 0-8 and a **metronome on channel 9** clicking at the
inferred period and phase. If the click sits on the beat, the grid is right. If
it sits on a triplet subdivision, or drifts, it is wrong, and which of those it
is cannot be recovered from any statistic computed here.

Tracks are sampled across FIT BANDS, including bands below the 0.80 threshold,
because the question the set exists to answer is whether 0.80 is the right bar.
`calibration.csv` has a blank verdict column to fill in.
"""

from __future__ import annotations

import argparse
import json
import random
import struct
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import grid as grid_mod, midi as midi_mod  # noqa: E402

TICKS = grid_mod.TICKS_PER_SECOND

#: Fit bands to sample from, concentrated either side of 0.70 rather than 0.80.
#: The driver tick already gives an independent read: on the 366 music tracks
#: that have both a grid and a confident tick, the grid period sits within 5%
#: of a whole number of driver ticks for 27-31% of tracks below fit 0.70
#: (chance is 9%, and the median residual 0.20-0.25 is indistinguishable from
#: the 0.25 of random ratios) but 56-71% above it, with a median residual of
#: 0.00. The break is at 0.70, and 0.70-0.80 looks as tick-locked as 0.90+.
#: That is a hardware-side witness, not a restatement of fit, so the listening
#: set is pointed where the two disagree.
BANDS = ((0.55, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 0.85), (0.85, 1.01))

#: General MIDI percussion channel, and the one note that reads as a click.
CLICK_CHANNEL = 9
CLICK_NOTE = 37        # side stick: short, dry, audible against music
CLICK_ACCENT = 76      # high wood block, for the downbeat
CLICK_VELOCITY = 100

#: Accent every Nth beat, so a listener hears a bar and not just a pulse.
ACCENT_EVERY = 4

#: THE GRID PERIOD IS A ROW, NOT A BEAT. Across the 1,006 music tracks with a
#: grid the row rate runs 1.2 to 1000 per second, median 13.3, and 74% are
#: above 8 Hz. Clicking the raw period produces a buzz nobody can judge. So the
#: click goes on an integer multiple of the row, chosen to land in a plausible
#: beat range -- which is exactly the subdivision ambiguity this set exists to
#: test, now made audible and explicit instead of hidden in the period.
#: Runs to 1024 because the corpus does: the fastest grid is 1000 rows/second,
#: where the beat is three orders of magnitude above the row. Only powers of
#: two and their triples, so the multiple is always a subdivision a musician
#: would recognise rather than an arbitrary integer that happens to fit.
BEAT_MULTIPLES = (
    1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024
)
TARGET_BEAT_SECONDS = 0.5      # 120 BPM, the middle of the plausible range
MIN_BEAT_SECONDS = 0.25        # 240 BPM
MAX_BEAT_SECONDS = 1.2         # 50 BPM


def beat_multiple(period_ticks: int) -> int:
    """How many rows to a beat, so the click is a metronome and not a buzz.

    Picks the multiple whose resulting beat is closest to 120 BPM, preferring
    one inside the plausible range. Returns the multiple, which the CSV records
    so a listener's verdict can be read against the assumption it encodes.
    """
    seconds = period_ticks / TICKS
    inside = [m for m in BEAT_MULTIPLES
              if MIN_BEAT_SECONDS <= seconds * m <= MAX_BEAT_SECONDS]
    pool = inside or list(BEAT_MULTIPLES)
    return min(pool, key=lambda m: abs(seconds * m - TARGET_BEAT_SECONDS))


def _vlq(value: int) -> bytes:
    if value < 0:
        value = 0
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def _click_track(
    period_ticks: int, phase_ticks: int, end_ticks: int, rows_per_beat: int
) -> bytes:
    """A metronome track on the inferred grid, one click per `rows_per_beat`."""
    events: list[tuple[int, bytes]] = []
    beat_ticks = period_ticks * rows_per_beat
    beat = 0
    tick = phase_ticks
    # Beats before the phase still need clicking, or the opening is silent.
    while tick - beat_ticks >= 0:
        tick -= beat_ticks
    while tick < end_ticks:
        if tick >= 0:
            pulse = int(round((tick / TICKS) * (midi_mod.BPM / 60.0) * midi_mod.PPQ))
            note = CLICK_ACCENT if beat % ACCENT_EVERY == 0 else CLICK_NOTE
            events.append((pulse, bytes([0x90 | CLICK_CHANNEL, note, CLICK_VELOCITY])))
            # A click must be audible but must not mask the next one.
            off = pulse + max(1, min(24, int(0.3 * beat_ticks / TICKS * 960)))
            events.append((off, bytes([0x80 | CLICK_CHANNEL, note, 0])))
        tick += beat_ticks
        beat += 1

    events.sort(key=lambda item: item[0])
    body = bytearray()
    label = b"grid click"
    body += _vlq(0) + b"\xff\x03" + _vlq(len(label)) + label
    previous = 0
    for pulse, payload in events:
        body += _vlq(max(0, pulse - previous)) + payload
        previous = pulse
    body += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def with_click(
    music: bytes,
    period_ticks: int,
    phase_ticks: int,
    end_ticks: int,
    rows_per_beat: int = 1,
) -> bytes:
    """Append a click track to an existing MIDI file and fix its header."""
    assert music[:4] == b"MThd"
    header_len = struct.unpack(">I", music[4:8])[0]
    fmt, n_tracks, ppq = struct.unpack(">HHH", music[8 : 8 + header_len])
    body = music[8 + header_len :]
    click = _click_track(period_ticks, phase_ticks, end_ticks, rows_per_beat)
    new_header = b"MThd" + struct.pack(">I", 6) + struct.pack(
        ">HHH", fmt, n_tracks + 1, ppq
    )
    return new_header + body + click


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--per-band", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rows = [json.loads(line) for line in (args.out_dir / "manifest.jsonl").open()]
    # Music only: judging a grid against a door chime answers nothing.
    pool = [
        r for r in rows
        if r.get("ok") and r.get("record_path")
        and r.get("track_class") == "music"
        and r.get("grid", {}).get("period_ticks")
    ]
    print(f"{len(pool)} music tracks with a period to judge", file=sys.stderr)

    rng = random.Random(args.seed)
    chosen: list[dict[str, Any]] = []
    for low, high in BANDS:
        band = [r for r in pool if low <= r["grid"]["fit"] < high]
        rng.shuffle(band)
        picked = band[: args.per_band]
        for r in picked:
            r["_band"] = f"{low:.2f}-{high:.2f}"
        chosen.extend(picked)
        print(f"  fit {low:.2f}-{high:.2f}: {len(band):4d} available, "
              f"{len(picked)} chosen", file=sys.stderr)

    args.dist_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "file,game,title,track_class,fit,rows_per_second,rows_per_beat,"
        "click_bpm,tick_hz,onset_grid_over_tick,band,verdict_on_beat,verdict_notes"
    ]
    for r in chosen:
        record = json.loads((args.out_dir / r["record_path"]).read_text())
        notes = record["notes"]
        end_ticks = int(r["render_seconds"] * TICKS)
        music = midi_mod.from_notes(
            notes, render_ticks=end_ticks,
            name=f"{r['tag']['game']} - {r['tag']['title']}",
        )
        period = r["grid"]["period_ticks"]
        rows_per_beat = beat_multiple(period)
        click_bpm = 60.0 / (period * rows_per_beat / TICKS)
        data = with_click(
            music, period, r["grid"]["phase_ticks"], end_ticks, rows_per_beat
        )
        stem = r["track_id"].replace(":", "_")
        name = f"{stem}_fit{r['grid']['fit']:.2f}_{click_bpm:.0f}bpm.mid"
        (args.dist_dir / name).write_bytes(data)
        tick = r.get("tick") or {}
        lines.append(
            ",".join(
                str(x) for x in (
                    name,
                    '"' + (r["tag"]["game"] or "") + '"',
                    '"' + (r["tag"]["title"] or "").replace('"', "") + '"',
                    r.get("track_class", ""),
                    r["grid"]["fit"],
                    r["grid"].get("rows_per_second", ""),
                    rows_per_beat,
                    round(click_bpm, 1),
                    tick.get("hz", "") if tick.get("found") else "",
                    r["grid"].get("onset_grid_over_tick") or "",
                    r["_band"],
                    "",   # verdict_on_beat: yes / no / subdivision / drifts
                    "",   # verdict_notes
                )
            )
        )

    (args.dist_dir / "calibration.csv").write_text("\n".join(lines) + "\n")
    (args.dist_dir / "README.txt").write_text(
        "Grid calibration set\n"
        "====================\n\n"
        "Each .mid has the extracted music on channels 1-9 and a metronome on\n"
        "channel 10 (General MIDI percussion), accented every 4th click. The\n"
        "filename carries the fit score and the click tempo.\n\n"
        "WHAT THE CLICK IS. The pipeline infers a ROW period, not a beat --\n"
        "a tracker row, the rate at which the driver reads its sequence. Over\n"
        "the corpus that runs 1.2 to 1000 rows per second, median 13.3, and\n"
        "74% of tracks are faster than 8/second. Clicking the raw period is a\n"
        "buzz. So the click is placed on a whole number of rows, chosen to\n"
        "land near 120 BPM, and `rows_per_beat` in the CSV records how many.\n"
        "The phase is the inferred phase, untouched.\n\n"
        "That means a 'subdivision' verdict is informative but NOT a failure\n"
        "of the grid: if the click is twice or three times too fast, the row\n"
        "grid may be right and only `rows_per_beat` wrong. What would damn\n"
        "the grid is 'no' or 'drifts' -- those cannot be fixed by remultiplying.\n\n"
        "Play each one and fill in calibration.csv:\n\n"
        "  verdict_on_beat = yes          the click is on the beat\n"
        "                    subdivision  steady and aligned, but on a\n"
        "                                 subdivision or a triplet, not the beat\n"
        "                    no           unrelated to the metre\n"
        "                    drifts       starts right and loses alignment\n\n"
        "'drifts' is the verdict that matters most and the one no statistic\n"
        "here can produce: a wrong period with a right phase fits the opening\n"
        "bars and slides out, and fit averaged over the whole track still\n"
        "scores it well.\n\n"
        "What this answers:\n\n"
        "  1. Where the threshold belongs. The bands straddle 0.70, not 0.80,\n"
        "     because the driver tick already disagrees with 0.80: on the 366\n"
        "     music tracks that have both a grid and a confident tick, the\n"
        "     grid lands within 5% of a whole number of driver ticks for\n"
        "     27-31% of tracks below fit 0.70 -- against 9% for random ratios,\n"
        "     so barely above chance -- but 56-71% above it. And 0.70-0.80\n"
        "     looks as tick-locked as 0.90+ (56% at a median residual of\n"
        "     0.008, versus 58% at 0.001). That is a hardware witness rather\n"
        "     than a restatement of fit. If tracks at 0.72 click on the beat,\n"
        "     the bar is too high.\n"
        "  2. Whether the subdivision guard picks the beat. 'Dancing Mad'\n"
        "     alternates between 17.0 and 5.7 rows/s, a ratio of 2.98, which\n"
        "     is beats versus triplets. Fit scores both well and cannot\n"
        "     distinguish them.\n"
        "  3. Whether high fit means a right grid at all. Note that fit does\n"
        "     not rise monotonically on the tick test -- 0.80-0.90 beats\n"
        "     0.90-1.01 (71% against 58%) -- which suggests fit saturates and\n"
        "     the top band is partly sparse tracks that are easy to fit.\n\n"
        "Caveats on what you are hearing: pitch is wrong for about 1.8% of\n"
        "notes (a residual octave error), unpitched percussion is absent\n"
        "entirely, no instruments are assigned, and phase inversion is lost.\n"
        "Judge the CLICK against the rhythm, not the arrangement.\n"
    )
    print(f"\nwrote {len(chosen)} files to {args.dist_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
