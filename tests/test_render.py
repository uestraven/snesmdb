"""The listening renderer's two load-bearing properties.

Sound quality is not one of them. The renderer exists to isolate ONE
variable -- which sample a note uses -- so the only things that must hold
are that it is deterministic and that it never invents audio for an event
whose identity is not established.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snesmdb import render as r  # noqa: E402


def _sample(value: int = 1000, n: int = 64, loop=None) -> r.Sample:
    return r.Sample(pcm=tuple([value] * n), loop_offset=loop)


def _event(sid="a", onset=0.0, dur=0.1, pitch=r.PITCH_UNITY) -> r.Event:
    return r.Event(onset_sec=onset, duration_sec=dur, voice=0,
                   pitch_register=pitch, attack_level=15,
                   sustain_level=15, sample_id=sid)


# ---------------------------------------------------------------------------
# No substitution -- the safeguard
# ---------------------------------------------------------------------------

def test_an_unresolved_identity_is_skipped_not_filled():
    """`sample_id: null` means the identity was never established. Rendering
    a convenient sample there would manufacture agreement between the two
    candidates on exactly the events where we know least."""
    out = r.render([_event(sid=None)], {"a": _sample()}, 1.0)
    assert out.rendered == 0
    assert out.skipped_unresolved_identity == 1
    assert set(out.pcm) == {0}, "silence, not a substituted instrument"


def test_an_identity_absent_from_the_bank_is_skipped_and_named():
    """Distinct from an unresolved identity: here the data claims an
    identity but the private bank has no audio for it, which is a gap in the
    experiment's inputs and must not be silently equated with silence."""
    out = r.render([_event(sid="missing")], {"a": _sample()}, 1.0)
    assert out.skipped_identity_not_in_bank == 1
    assert out.skipped_unresolved_identity == 0
    assert out.skipped_ids == ["missing"]


def test_the_two_skip_reasons_are_counted_separately():
    out = r.render([_event(sid=None), _event(sid="nope")],
                   {"a": _sample()}, 1.0)
    assert (out.skipped_unresolved_identity,
            out.skipped_identity_not_in_bank) == (1, 1)
    assert out.skipped == 2


def test_an_empty_sample_is_not_rendered():
    out = r.render([_event()], {"a": r.Sample(pcm=(), loop_offset=None)}, 1.0)
    assert out.rendered == 0 and out.skipped_unusable_event == 1


# ---------------------------------------------------------------------------
# Determinism -- so a difference between renders means a difference in input
# ---------------------------------------------------------------------------

def test_the_same_inputs_render_byte_identical_audio():
    bank = {"a": _sample(1000), "b": _sample(-1000)}
    events = [_event("a", 0.0), _event("b", 0.05), _event("a", 0.2)]
    first = r.wav_bytes(r.render(events, bank, 0.5).pcm)
    second = r.wav_bytes(r.render(events, bank, 0.5).pcm)
    assert first == second


def test_wav_bytes_carry_no_metadata_that_could_differ_between_runs():
    """Hand-built header: a library writer could embed a timestamp, and the
    blind comparison relies on file bytes differing ONLY by audio."""
    a = r.wav_bytes([0, 1, -1])
    assert a[:4] == b"RIFF" and a[8:12] == b"WAVE"
    assert a == r.wav_bytes([0, 1, -1])


def test_changing_only_the_sample_identity_changes_the_audio():
    """The experiment's premise: if swapping the identity did NOT change the
    render, an A/B listening test could not detect anything."""
    events = [_event("a")]
    one = r.render(events, {"a": _sample(1000)}, 0.3).pcm
    other = r.render(events, {"a": _sample(-1000)}, 0.3).pcm
    assert one != other


def test_identical_audio_under_two_identities_renders_identically():
    """The converse, and the reason the null-control strata work: two
    identities whose audio is the same are audibly indistinguishable, so a
    listener reporting a difference there is reporting about themselves."""
    events_a = [_event("a")]
    events_b = [_event("b")]
    bank = {"a": _sample(1000), "b": _sample(1000)}
    assert r.render(events_a, bank, 0.3).pcm == r.render(
        events_b, bank, 0.3).pcm


# ---------------------------------------------------------------------------
# The parts that are faithful rather than approximate
# ---------------------------------------------------------------------------

def test_pitch_register_is_treated_as_a_resample_ratio():
    """$1000 is 1.0x. This is what the hardware does, so no assumption about
    a sample's natural base pitch is needed."""
    bank = {"a": r.Sample(pcm=tuple(range(100)), loop_offset=None)}
    slow = r.render([_event(pitch=r.PITCH_UNITY // 2)], bank, 0.3).pcm
    fast = r.render([_event(pitch=r.PITCH_UNITY * 2)], bank, 0.3).pcm
    assert slow != fast


def test_a_one_shot_stops_rather_than_looping():
    """A sample with no loop point must not be made to repeat; that would
    invent sustain the hardware would not produce."""
    bank = {"a": _sample(1000, n=16, loop=None)}
    out = r.render([_event(dur=0.5)], bank, 1.0)
    tail = out.pcm[int(0.4 * r.SAMPLE_RATE):]
    assert set(tail) == {0}


def test_a_looping_sample_sustains_through_the_note():
    bank = {"a": _sample(1000, n=16, loop=0)}
    out = r.render([_event(dur=0.3)], bank, 1.0)
    mid = out.pcm[int(0.15 * r.SAMPLE_RATE)]
    assert mid != 0


def test_events_past_the_excerpt_window_are_dropped_not_wrapped():
    out = r.render([_event(onset=5.0)], {"a": _sample()}, 1.0)
    assert set(out.pcm) == {0}


def test_output_is_clamped_to_signed_16_bit():
    bank = {"a": _sample(32767, n=64, loop=0)}
    events = [_event(f"a", onset=0.0) for _ in range(64)]
    out = r.render(events, bank, 0.3)
    assert all(-32768 <= v <= 32767 for v in out.pcm)
