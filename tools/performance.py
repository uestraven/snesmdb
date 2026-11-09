#!/usr/bin/env python3
"""What real SNES music does with its eight voices, envelopes and echo.

    performance.py <out-dir> <report.json> [--echo-sample 8]

Not a pipeline stage. This is the analysis `docs/design.md` §7 argues is the
actual payoff of the corpus, and it is deliberately about PERFORMANCE rather
than composition:

    "Composition-rule changes derived from measurement are 0 for 4 with this
    listener... The one axis that has ever landed is how material is *played*
    -- per-song duty and position-shaped velocity were accepted immediately.
    So if this is built for analysis, extract performance conventions (voice
    counts over time, velocity shaping, ADSR, echo usage, note-length
    distributions) before progressions and form lengths."

Those five axes, in that order.

Every claim is reported with its spread ACROSS GAMES, because the useful
distinction is between a convention (every driver and composer does it) and a
house style (one studio does it). A corpus-wide mean hides exactly that, and a
mean over 22 games weighted by track count would mostly describe Earthbound.
So per-game figures are computed first and the corpus figure is the median over
games, not over tracks.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TICKS = 1_024_000

#: DSP registers this reads. Echo lives outside the per-voice block, so it
#: cannot be recovered from the note list and needs the write log.
REG_FLG = 0x6C
REG_EON = 0x4D
REG_EVOL_L = 0x2C
REG_EVOL_R = 0x3C
REG_EFB = 0x0D
REG_MVOL_L = 0x0C
REG_MVOL_R = 0x1C
REG_PMON = 0x2D
REG_NON = 0x3D


def _signed8(value: int) -> int:
    return value - 256 if value >= 128 else value


def _percentiles(values: list[float], points=(5, 25, 50, 75, 95)) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    out = {}
    for p in points:
        index = min(len(ordered) - 1, max(0, int(round(p / 100 * (len(ordered) - 1)))))
        out[f"p{p}"] = round(ordered[index], 4)
    return out


def _spread(per_game: dict[str, float]) -> dict[str, Any]:
    """Median over games plus the spread, so a convention is distinguishable
    from one studio's habit."""
    values = [v for v in per_game.values() if v is not None]
    if not values:
        return {}
    return {
        "median_over_games": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "iqr": round(
            (_percentiles(values, (75,))["p75"] - _percentiles(values, (25,))["p25"]), 4
        )
        if len(values) >= 4
        else None,
        "n_games": len(values),
    }


# --------------------------------------------------------------- the measures


def voice_usage(notes: list[dict], render_ticks: int, step: int = TICKS // 50) -> dict[str, Any]:
    """How many voices sound at once, sampled on a fixed 20 ms grid.

    Sampled rather than event-based so a track that re-keys constantly is not
    weighted more heavily than one that holds notes: the question is how much
    of the TIME is spent at each voice count.
    """
    if not notes or render_ticks <= 0:
        return {}
    # Per-voice intervals, with an unterminated note ending where its voice
    # next speaks -- a voice sounds one note at a time.
    by_voice: dict[int, list[tuple[int, int]]] = defaultdict(list)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for note in notes:
        grouped[int(note["voice"])].append(note)
    for voice, items in grouped.items():
        items.sort(key=lambda n: int(n["start"]))
        for i, note in enumerate(items):
            start = int(note["start"])
            following = int(items[i + 1]["start"]) if i + 1 < len(items) else render_ticks
            end = int(note["end"]) if note.get("end") is not None else following
            by_voice[voice].append((start, max(start, min(end, following))))

    # THE CONFOUND, MEASURED AND PUBLISHED RATHER THAN WARNED ABOUT.
    #
    # `mean_voices_when_sounding` counts GATED voices. A driver that never
    # releases a voice saturates it for a reason that is not musical: Breath
    # of Fire 2 and Mega Man X hold a median 1.1-1.2 ms between a key-off and
    # the next key-on on the same voice, against 27-64 ms elsewhere -- a 50x
    # spread -- so they top any such ranking while sounding no denser. An
    # evaluator caught this and nearly published a density comparison on it.
    #
    # A prose caveat only reaches a reader who is already suspicious. These
    # two numbers sit beside the statistic they undermine, so a researcher
    # comparing games sees the confound in the same table.
    gaps: list[int] = []
    for intervals in by_voice.values():
        ordered = sorted(intervals)
        for (_, end), (next_start, _) in zip(ordered, ordered[1:]):
            if next_start >= end:
                gaps.append(next_start - end)
    gated = sum(b - a for intervals in by_voice.values() for a, b in intervals)

    counts = Counter()
    samples = 0
    for t in range(0, render_ticks, step):
        active = sum(
            1
            for intervals in by_voice.values()
            if any(a <= t < b for a, b in intervals)
        )
        counts[active] += 1
        samples += 1
    if not samples:
        return {}
    silent = counts.get(0, 0) / samples
    weighted = sum(k * v for k, v in counts.items()) / samples
    sounding = [k for k in counts for _ in range(counts[k]) if k > 0]
    return {
        # Median silence between a key-off and the next key-on on the same
        # voice. Near zero means the driver holds voices gated, so the gated
        # count overstates audible density.
        "median_release_gap_ms": (
            round(statistics.median(gaps) / TICKS * 1000.0, 3) if gaps else None
        ),
        # Share of available voice-time spent gated. Approaching 1.0 means a
        # gated-voice measure is saturated and cannot discriminate.
        "gated_duty_cycle": (
            round(gated / (render_ticks * max(len(by_voice), 1)), 4)
            if render_ticks else None
        ),
        "mean_voices": round(weighted, 3),
        "mean_voices_when_sounding": round(
            statistics.fmean(sounding), 3
        ) if sounding else 0.0,
        "max_voices": max(counts),
        "silent_fraction": round(silent, 4),
        "distribution": {str(k): round(v / samples, 4) for k, v in sorted(counts.items())},
    }


def note_lengths(notes: list[dict]) -> dict[str, Any]:
    lengths = [
        (int(n["end"]) - int(n["start"])) / TICKS
        for n in notes
        if n.get("end") is not None and int(n["end"]) > int(n["start"])
    ]
    if not lengths:
        return {}
    return {
        "n": len(lengths),
        "median_sec": round(statistics.median(lengths), 4),
        "percentiles_sec": _percentiles(lengths),
        # Staccato share: how much of the music is short enough to read as
        # articulation rather than sustain.
        "under_100ms": round(sum(1 for v in lengths if v < 0.1) / len(lengths), 4),
        "over_1s": round(sum(1 for v in lengths if v > 1.0) / len(lengths), 4),
    }


def velocity_shaping(notes: list[dict]) -> dict[str, Any]:
    """Volume, panning, and whether volume is SHAPED by anything measurable.

    The NES result worth testing against was "position-shaped velocity": notes
    louder or softer by where they sit, not by what they are. Three candidate
    shapers are tested here, each as a correlation against a null of 0: the
    note's position through the track, its register, and its voice index.
    """
    usable = [
        n for n in notes
        if n.get("volume_left") is not None and n.get("volume_right") is not None
    ]
    if len(usable) < 20:
        return {}
    loud = [abs(int(n["volume_left"])) + abs(int(n["volume_right"])) for n in usable]
    pan = []
    for n in usable:
        left = abs(int(n["volume_left"]))
        right = abs(int(n["volume_right"]))
        total = left + right
        if total:
            pan.append((right - left) / total)
    inverted = sum(
        1 for n in usable
        if (int(n["volume_left"]) < 0) != (int(n["volume_right"]) < 0)
    )

    def correlation(xs: list[float], ys: list[float]) -> float | None:
        if len(xs) < 20:
            return None
        mx = statistics.fmean(xs)
        my = statistics.fmean(ys)
        num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
        dy = math.sqrt(sum((b - my) ** 2 for b in ys))
        return round(num / (dx * dy), 4) if dx > 0 and dy > 0 else None

    span = max(int(n["start"]) for n in usable) or 1
    position = [int(n["start"]) / span for n in usable]
    register = [
        float(n["midi_note"]) for n in usable if n.get("midi_note") is not None
    ]
    loud_pitched = [
        abs(int(n["volume_left"])) + abs(int(n["volume_right"]))
        for n in usable
        if n.get("midi_note") is not None
    ]
    return {
        "n": len(usable),
        "median_volume": round(statistics.median(loud), 2),
        "volume_percentiles": _percentiles([float(v) for v in loud]),
        "median_abs_pan": round(statistics.median([abs(p) for p in pan]), 4) if pan else None,
        "hard_panned_fraction": round(
            sum(1 for p in pan if abs(p) > 0.6) / len(pan), 4
        ) if pan else None,
        # A negative volume inverts that side's phase: a real stereo technique,
        # and worth knowing how much it is used.
        "phase_inverted_fraction": round(inverted / len(usable), 4),
        "corr_volume_vs_position": correlation(position, [float(v) for v in loud]),
        "corr_volume_vs_register": correlation(register, [float(v) for v in loud_pitched]),
        "corr_volume_vs_voice": correlation(
            [float(n["voice"]) for n in usable], [float(v) for v in loud]
        ),
    }


def envelopes(notes: list[dict]) -> dict[str, Any]:
    """ADSR versus direct GAIN, and which envelope settings get used."""
    if not notes:
        return {}
    adsr_on = 0
    words = Counter()
    attacks = Counter()
    decays = Counter()
    sustain_levels = Counter()
    sustain_rates = Counter()
    gains = Counter()
    for note in notes:
        a1 = int(note.get("adsr1") or 0)
        a2 = int(note.get("adsr2") or 0)
        if a1 & 0x80:
            adsr_on += 1
            words[(a1, a2)] += 1
            attacks[a1 & 0x0F] += 1
            decays[(a1 >> 4) & 0x07] += 1
            sustain_levels[(a2 >> 5) & 0x07] += 1
            sustain_rates[a2 & 0x1F] += 1
        else:
            gains[int(note.get("gain") or 0)] += 1
    return {
        "n": len(notes),
        "adsr_fraction": round(adsr_on / len(notes), 4),
        "distinct_adsr_words": len(words),
        "top_adsr_words": [
            {"adsr1": a1, "adsr2": a2, "share": round(c / max(adsr_on, 1), 4)}
            for (a1, a2), c in words.most_common(3)
        ],
        "attack_rate_median": statistics.median(list(attacks.elements())) if attacks else None,
        "decay_rate_median": statistics.median(list(decays.elements())) if decays else None,
        "sustain_level_median": statistics.median(list(sustain_levels.elements())) if sustain_levels else None,
        "sustain_rate_median": statistics.median(list(sustain_rates.elements())) if sustain_rates else None,
        "distinct_gain_values": len(gains),
    }


def echo_and_modulation(log_path: Path) -> dict[str, Any]:
    """Echo, noise and pitch-modulation settings, from the write log.

    These live outside the per-voice register block, so the note list cannot
    carry them: they have to come from the raw DSP writes.
    """
    last: dict[int, int] = {}
    # Drivers set NON and PMON for a note and clear them afterwards, so the
    # LAST value is usually zero and reading it reports that nobody uses
    # noise -- which the extractor's own per-note noise flag contradicts. What
    # matters is whether a voice was EVER switched into noise or modulation
    # mode, so the union of every value written is kept.
    ever: dict[int, int] = {}
    seen_any = False
    try:
        with gzip.open(log_path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                write = json.loads(line)
                # The raw log is not only register writes. `spc_dump` also
                # emits `kind:"dir"` directory snapshots, which carry no
                # `addr` -- 436 of them in the first Evermore track alone.
                # Assuming every record is a write raised KeyError and took
                # the whole performance step down.
                if "addr" not in write:
                    continue
                address = int(write["addr"]) & 0xFF
                if address in (
                    REG_FLG, REG_EON, REG_EVOL_L, REG_EVOL_R, REG_EFB,
                    REG_MVOL_L, REG_MVOL_R, REG_PMON, REG_NON,
                ):
                    value = int(write["data"]) & 0xFF
                    last[address] = value
                    ever[address] = ever.get(address, 0) | value
                    seen_any = True
    except (OSError, ValueError):
        return {}
    if not seen_any:
        return {}
    eon = ever.get(REG_EON, 0)
    eon_voices = bin(eon).count("1")
    evol_l = _signed8(last.get(REG_EVOL_L, 0))
    evol_r = _signed8(last.get(REG_EVOL_R, 0))
    flg = last.get(REG_FLG, 0)
    return {
        "echo_enabled_voices": eon_voices,
        "echo_on": eon_voices > 0 and not (flg & 0x20),
        # FLG bit 5 is ECEN inverted: set means echo WRITES are disabled.
        "echo_writes_disabled": bool(flg & 0x20),
        "echo_volume_l": evol_l,
        "echo_volume_r": evol_r,
        "echo_feedback": _signed8(last.get(REG_EFB, 0)),
        "main_volume_l": _signed8(last.get(REG_MVOL_L, 0)),
        "main_volume_r": _signed8(last.get(REG_MVOL_R, 0)),
        # Voices ever switched into noise or pitch-modulation mode, not those
        # left in it when the window closed.
        "noise_voices": bin(ever.get(REG_NON, 0)).count("1"),
        "pitch_mod_voices": bin(ever.get(REG_PMON, 0)).count("1"),
    }


# --------------------------------------------------------------------- driver


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--echo-sample", type=int, default=8,
        help="tracks per game to read raw logs for; echo needs the full log",
    )
    parser.add_argument(
        "--track-class", default="",
        help="restrict to one track_class, e.g. music. Empty uses every "
             "track, so a run can be compared against itself to see how much "
             "the jingles and effects were moving the figures.",
    )
    args = parser.parse_args()

    rows = []
    skipped = 0
    for line in (args.out_dir / "manifest.jsonl").open():
        row = json.loads(line)
        if not (row.get("ok") and row.get("record_path")):
            continue
        if args.track_class and row.get("track_class") != args.track_class:
            skipped += 1
            continue
        rows.append(row)
    if args.track_class:
        print(f"restricted to track_class={args.track_class}; "
              f"skipped {skipped} other tracks", file=sys.stderr)
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_game[row["tag"]["game"] or "?"].append(row)
    print(f"{len(rows)} tracks, {len(by_game)} games", file=sys.stderr)

    per_game: dict[str, dict[str, Any]] = {}
    for game, tracks in sorted(by_game.items()):
        voice_means, voice_sounding, silent, maxv = [], [], [], []
        lengths_median, short, long_ = [], [], []
        release_gaps, duty = [], []
        volumes, pans, hard, inverted = [], [], [], []
        corr_pos, corr_reg, corr_voice = [], [], []
        adsr_frac, adsr_words, attack, sustain = [], [], [], []
        echo_rows = []

        for index, row in enumerate(tracks):
            record = json.loads((args.out_dir / row["record_path"]).read_text())
            notes = record["notes"]
            render_ticks = int(row["render_seconds"] * TICKS)

            v = voice_usage(notes, render_ticks)
            if v:
                voice_means.append(v["mean_voices"])
                voice_sounding.append(v["mean_voices_when_sounding"])
                silent.append(v["silent_fraction"])
                if v.get("median_release_gap_ms") is not None:
                    release_gaps.append(v["median_release_gap_ms"])
                if v.get("gated_duty_cycle") is not None:
                    duty.append(v["gated_duty_cycle"])
                maxv.append(v["max_voices"])
            n = note_lengths(notes)
            if n:
                lengths_median.append(n["median_sec"])
                short.append(n["under_100ms"])
                long_.append(n["over_1s"])
            s = velocity_shaping(notes)
            if s:
                volumes.append(s["median_volume"])
                if s["median_abs_pan"] is not None:
                    pans.append(s["median_abs_pan"])
                if s["hard_panned_fraction"] is not None:
                    hard.append(s["hard_panned_fraction"])
                inverted.append(s["phase_inverted_fraction"])
                for key, bucket in (
                    ("corr_volume_vs_position", corr_pos),
                    ("corr_volume_vs_register", corr_reg),
                    ("corr_volume_vs_voice", corr_voice),
                ):
                    if s[key] is not None:
                        bucket.append(s[key])
            e = envelopes(notes)
            if e:
                adsr_frac.append(e["adsr_fraction"])
                adsr_words.append(e["distinct_adsr_words"])
                if e["attack_rate_median"] is not None:
                    attack.append(e["attack_rate_median"])
                if e["sustain_level_median"] is not None:
                    sustain.append(e["sustain_level_median"])
            if index < args.echo_sample and row.get("raw_path"):
                got = echo_and_modulation(args.out_dir / row["raw_path"])
                if got:
                    echo_rows.append(got)

        med = lambda xs: round(statistics.median(xs), 4) if xs else None  # noqa: E731
        per_game[game] = {
            "n_tracks": len(tracks),
            "voices": {
                "mean": med(voice_means),
                "mean_when_sounding": med(voice_sounding),
                "silent_fraction": med(silent),
                "max": max(maxv) if maxv else None,
                # Read these two BEFORE comparing mean_when_sounding across
                # games. A near-zero release gap with a duty cycle close to
                # 1.0 means the driver holds voices gated and the mean is
                # saturated by engine policy rather than by musical density.
                "median_release_gap_ms": med(release_gaps),
                "gated_duty_cycle": med(duty),
            },
            "note_lengths": {
                "median_sec": med(lengths_median),
                "under_100ms": med(short),
                "over_1s": med(long_),
            },
            "velocity": {
                "median_volume": med(volumes),
                "median_abs_pan": med(pans),
                "hard_panned_fraction": med(hard),
                "phase_inverted_fraction": med(inverted),
                "corr_volume_vs_position": med(corr_pos),
                "corr_volume_vs_register": med(corr_reg),
                "corr_volume_vs_voice": med(corr_voice),
            },
            "envelopes": {
                "adsr_fraction": med(adsr_frac),
                "distinct_adsr_words": med(adsr_words),
                "attack_rate_median": med(attack),
                "sustain_level_median": med(sustain),
            },
            "echo": {
                "n_sampled": len(echo_rows),
                "echo_on_fraction": round(
                    sum(1 for e in echo_rows if e["echo_on"]) / len(echo_rows), 4
                ) if echo_rows else None,
                "median_echo_voices": med([e["echo_enabled_voices"] for e in echo_rows]),
                "median_echo_volume": med(
                    [(abs(e["echo_volume_l"]) + abs(e["echo_volume_r"])) / 2 for e in echo_rows]
                ),
                "median_feedback": med([e["echo_feedback"] for e in echo_rows]),
                "median_noise_voices": med([e["noise_voices"] for e in echo_rows]),
                "median_pitch_mod_voices": med([e["pitch_mod_voices"] for e in echo_rows]),
            },
        }
        print(f"  {game[:28]:28s} done", file=sys.stderr)

    def across(path: tuple[str, ...]) -> dict[str, Any]:
        collected = {}
        for game, data in per_game.items():
            node: Any = data
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
            if node is not None:
                collected[game] = float(node)
        return _spread(collected)

    corpus = {
        "voices_mean": across(("voices", "mean")),
        "voices_mean_when_sounding": across(("voices", "mean_when_sounding")),
        "silent_fraction": across(("voices", "silent_fraction")),
        "note_median_sec": across(("note_lengths", "median_sec")),
        "note_under_100ms": across(("note_lengths", "under_100ms")),
        "note_over_1s": across(("note_lengths", "over_1s")),
        "median_volume": across(("velocity", "median_volume")),
        "median_abs_pan": across(("velocity", "median_abs_pan")),
        "hard_panned_fraction": across(("velocity", "hard_panned_fraction")),
        "phase_inverted_fraction": across(("velocity", "phase_inverted_fraction")),
        "corr_volume_vs_position": across(("velocity", "corr_volume_vs_position")),
        "corr_volume_vs_register": across(("velocity", "corr_volume_vs_register")),
        "corr_volume_vs_voice": across(("velocity", "corr_volume_vs_voice")),
        "adsr_fraction": across(("envelopes", "adsr_fraction")),
        "distinct_adsr_words": across(("envelopes", "distinct_adsr_words")),
        "attack_rate_median": across(("envelopes", "attack_rate_median")),
        "sustain_level_median": across(("envelopes", "sustain_level_median")),
        "echo_on_fraction": across(("echo", "echo_on_fraction")),
        "median_echo_voices": across(("echo", "median_echo_voices")),
        "median_feedback": across(("echo", "median_feedback")),
        "median_noise_voices": across(("echo", "median_noise_voices")),
        "median_pitch_mod_voices": across(("echo", "median_pitch_mod_voices")),
    }

    args.report.write_text(json.dumps(
        {"track_class": args.track_class or "all", "n_tracks": len(rows),
         "corpus": corpus, "per_game": per_game}, indent=1))

    print("\n=== performance conventions: median over games, and the spread ===")
    print(f"{'measure':28s} {'median':>9s} {'min':>9s} {'max':>9s} {'games':>6s}")
    for name, value in corpus.items():
        if not value:
            continue
        print(f"  {name:26s} {value['median_over_games']:9.3f} "
              f"{value['min']:9.3f} {value['max']:9.3f} {value['n_games']:6d}")
    print(f"\nwrote {args.report}")


if __name__ == "__main__":
    main()
