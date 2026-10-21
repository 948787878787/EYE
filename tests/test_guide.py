"""Tests for board/guide_v1.py (aiming guidance and speech policy)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import guide_v1 as G  # noqa: E402
from ped_logic_v1 import UNKNOWN, RED, GREEN, GREEN_FLASH  # noqa: E402

FRAME_MS = 100
FRONT = (20, 40)          # w_px, h_px of a front-facing signal (aspect 2.0)
SIDE_VIEW = (8, 40)       # aspect 5.0: seen from the side


def feed(guide, frames, start=0):
    """frames: list of (state, center_has_signal, side_detections). Returns [(t, keys)] with speech."""
    said = []
    for i, (state, center, sides) in enumerate(frames):
        t = start + i * FRAME_MS
        keys = guide.update(t, state, center, sides)
        if keys:
            said.append((t, keys))
    return said


def all_keys(said):
    return [k for _, keys in said for k in keys]


def test_state_changes_are_spoken_immediately():
    said = feed(G.Guide(), [(UNKNOWN, True, ())] * 3 + [(RED, True, ())] + [(GREEN, True, ())])
    assert said == [(300, ["red"]), (400, ["green"])]


def test_losing_green_is_spoken():
    said = feed(G.Guide(), [(GREEN, True, ())] * 5 + [(UNKNOWN, True, ())])
    assert all_keys(said) == ["green", "unknown"]


def test_losing_red_is_silent():
    said = feed(G.Guide(), [(RED, True, ())] * 5 + [(UNKNOWN, True, ())] * 5)
    assert all_keys(said) == ["red"]


def test_no_signal_anywhere_asks_for_slow_scan_with_cooldown():
    said = feed(G.Guide(), [(UNKNOWN, False, ())] * 130)
    times = [t for t, keys in said if "scan" in keys]
    assert times[0] >= G.SCAN_AFTER_MS
    assert all(b - a >= G.COOLDOWN_MS["scan"] for a, b in zip(times, times[1:]))
    assert set(all_keys(said)) == {"scan"}


def test_search_windows_alternate_only_while_searching():
    guide = G.Guide()
    feed(guide, [(UNKNOWN, True, ())] * 5)             # a steady signal in the center
    assert guide.windows_to_scan() == []
    guide.update(500, UNKNOWN, False, ())
    assert guide.windows_to_scan() == []           # lost only briefly: no search yet
    for t in range(600, 600 + G.SEARCH_AFTER_MS + 1000, 100):
        guide.update(t, UNKNOWN, False, ())
    seq = [guide.windows_to_scan()[0] for _ in range(4)]
    assert seq == ["left", "right", "left", "right"]


def test_front_facing_signal_on_left_gives_turn_left():
    frames = [(UNKNOWN, False, ((0.3,) + FRONT,))] * 5
    assert "turn_left" in all_keys(feed(G.Guide(), frames))


def test_front_facing_signal_on_right_gives_turn_right():
    frames = [(UNKNOWN, False, ((0.72,) + FRONT,))] * 5
    assert "turn_right" in all_keys(feed(G.Guide(), frames))


def test_single_side_hit_is_not_enough():
    frames = [(UNKNOWN, False, ((0.3,) + FRONT,))] + [(UNKNOWN, False, ())] * 20
    assert "turn_left" not in all_keys(feed(G.Guide(), frames))


def test_far_side_signal_is_ignored_it_may_be_the_cross_street():
    frames = [(UNKNOWN, False, ((0.1,) + FRONT,))] * 60
    keys = all_keys(feed(G.Guide(), frames))
    assert "turn_left" not in keys and "scan" in keys


def test_side_view_signal_is_ignored():
    frames = [(UNKNOWN, False, ((0.3,) + SIDE_VIEW,))] * 60
    keys = all_keys(feed(G.Guide(), frames))
    assert "turn_left" not in keys


def test_found_after_guidance():
    frames = [(UNKNOWN, False, ((0.3,) + FRONT,))] * 5 + [(UNKNOWN, True, ())] * 20
    keys = all_keys(feed(G.Guide(), frames))
    assert keys.index("turn_left") < keys.index("found")


def test_no_found_without_prior_guidance():
    keys = all_keys(feed(G.Guide(), [(UNKNOWN, True, ())] * 20))
    assert "found" not in keys


def test_unclear_only_after_threshold_and_with_cooldown():
    said = feed(G.Guide(), [(UNKNOWN, True, ())] * 130)
    times = [t for t, keys in said if "unclear" in keys]
    assert times[0] >= G.UNCLEAR_AFTER_MS
    assert all(b - a >= G.COOLDOWN_MS["unclear"] for a, b in zip(times, times[1:]))


def test_no_guidance_while_a_color_is_announced():
    frames = [(RED, True, ())] * 5 + [(RED, False, ((0.3,) + FRONT,))] * 40
    keys = all_keys(feed(G.Guide(), frames))
    assert keys == ["red"]


def test_min_gap_between_prompts():
    guide = G.Guide()
    said = feed(guide, [(UNKNOWN, False, ((0.3,) + FRONT,))] * 5)
    t_left = said[0][0]
    keys = guide.update(t_left + 100, UNKNOWN, True, ())   # found right after: too soon
    assert "found" not in keys


def test_state_speech_ignores_min_gap():
    guide = G.Guide()
    feed(guide, [(UNKNOWN, False, ((0.3,) + FRONT,))] * 5)
    assert guide.update(600, RED, True, ()) == ["red"]


def test_facing_and_guidable_helpers():
    assert G.facing(20, 40) and not G.facing(8, 40) and not G.facing(40, 20) and not G.facing(0, 10)
    assert G.guidable(0.5) and G.guidable(0.2) and not G.guidable(0.1)


def test_color_announcement_supersedes_found():
    guide = G.Guide()
    feed(guide, [(UNKNOWN, False, ((0.3,) + FRONT,))] * 5)
    assert guide.update(2000, RED, True, ()) == ["red"]
    keys = all_keys(feed(guide, [(RED, True, ())] * 30, start=2100))
    assert "found" not in keys


def test_flickering_spurious_detection_is_not_a_signal_in_view():
    """A detection present in only a few frames (glare, clutter) must not trigger 'unclear' or stop searching."""
    frames = [(UNKNOWN, i % 4 == 0, ()) for i in range(130)]     # present 25% of frames
    keys = all_keys(feed(G.Guide(), frames))
    assert "unclear" not in keys and "scan" in keys


def test_steady_signal_in_view_still_reports_unclear():
    frames = [(UNKNOWN, i % 10 != 0, ()) for i in range(130)]    # present 90% of frames
    assert "unclear" in all_keys(feed(G.Guide(), frames))


# ---- state announcements (v5 signal-first speech) -----------------------------

def announce(states, frame_ms=100):
    a = G.StateAnnouncer()
    out = []
    for i, s in enumerate(states):
        for key in a.update(i * frame_ms, s):
            out.append((i * frame_ms, key))
    return out


def test_announcer_speaks_red_immediately():
    assert announce([UNKNOWN] * 3 + [RED] * 3)[0] == (300, "red")


def test_announcer_ignores_short_dips_to_unknown():
    states = [GREEN_FLASH] * 10 + [UNKNOWN] * 3 + [GREEN_FLASH] * 10 + [UNKNOWN] * 4 + [GREEN_FLASH] * 10
    keys = [k for _, k in announce(states)]
    assert keys == ["green_flash"]


def test_announcer_reports_lost_green_after_hold():
    states = [GREEN] * 10 + [UNKNOWN] * 30
    out = announce(states)
    assert [k for _, k in out] == ["green", "unknown"]
    assert out[1][0] - 1000 >= G.LOST_HOLD_MS


def test_announcer_does_not_repeat_same_state_quickly():
    states = [RED] * 10 + [UNKNOWN] * 20 + [RED] * 10
    assert [k for _, k in announce(states)] == ["red"]


def test_announcer_repeats_after_long_gap():
    states = [RED] * 10 + [UNKNOWN] * 100 + [RED] * 5
    assert [k for _, k in announce(states)] == ["red", "red"]
