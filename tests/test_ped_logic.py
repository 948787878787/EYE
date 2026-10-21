"""Tests for board/ped_logic_v1.py (shared decision logic of the signal reader)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import ped_logic_v1 as L  # noqa: E402

FRAME_MS = 100  # 10 FPS


def run(labels, start=0):
    """Feed one label per frame; return list of states."""
    voter = L.Voter()
    return [voter.update(start + i * FRAME_MS, lab) for i, lab in enumerate(labels)]


def pattern(on_label, on_ms, off_label, off_ms, total_ms):
    out = []
    t = 0
    while t < total_ms:
        phase = t % (on_ms + off_ms)
        out.append(on_label if phase < on_ms else off_label)
        t += FRAME_MS
    return out


# ---- voting --------------------------------------------------------------

def test_no_detection_stays_unknown():
    assert set(run(["none"] * 30)) == {L.UNKNOWN}


def test_steady_red_becomes_red_after_min_frames():
    states = run(["red"] * 20)
    assert states[L.MIN_FRAMES - 2] == L.UNKNOWN
    assert states[L.MIN_FRAMES - 1] == L.RED
    assert states[-1] == L.RED


def test_steady_green_is_debounced_before_announcing():
    states = run(["green"] * 20)
    first_green = states.index(L.GREEN)
    first_candidate_frame = L.MIN_FRAMES - 1
    assert (first_green - first_candidate_frame) * FRAME_MS >= L.GREEN_HOLD_MS
    assert L.RED not in states


def test_leaving_green_is_immediate_on_red():
    states = run(["green"] * 20 + ["red"])
    assert states[-2] == L.GREEN
    assert states[-1] != L.GREEN


def test_mixed_red_and_green_is_unknown():
    states = run(["red", "green"] * 15)
    assert L.GREEN not in states
    assert L.GREEN_FLASH not in states


def test_mostly_unknown_frames_do_not_give_green():
    states = run(["green", "unk", "unk"] * 10)
    assert L.GREEN not in states


def test_flashing_green_detected():
    states = run(pattern("green", 500, "none", 500, 4000))
    assert L.GREEN_FLASH in states
    assert L.GREEN not in states


def test_single_frame_dropouts_are_not_flashing():
    labels = pattern("green", 900, "none", 100, 4000)
    states = run(labels)
    assert L.GREEN_FLASH not in states
    assert states[-1] == L.GREEN


def test_red_after_flash_goes_through_unknown_not_green():
    labels = pattern("green", 500, "none", 500, 3000) + ["red"] * 20
    states = run(labels)
    after = states[len(labels) - 20:]
    assert L.GREEN not in after
    assert L.GREEN_FLASH not in after[1:]
    assert after[-1] == L.RED


def test_ticks_wraparound_safe_with_large_start():
    states = run(["red"] * 10, start=10 ** 9)
    assert states[-1] == L.RED


# ---- frame labels ----------------------------------------------------------

def test_label_requires_higher_confidence_for_green():
    assert L.label_from_probs({"red": 0.65, "green": 0.3, "other": 0.05}, False) == "red"
    assert L.label_from_probs({"red": 0.1, "green": 0.75, "other": 0.15}, False) == "unk"
    assert L.label_from_probs({"red": 0.05, "green": 0.9, "other": 0.05}, False) == "green"


def test_veto_blocks_green_label():
    assert L.label_from_probs({"red": 0.05, "green": 0.9, "other": 0.05}, True) == "unk"


def test_primary_signal_prefers_largest_confident_box():
    boxes = [(0, 0, 10, 20), (300, 50, 30, 60), (500, 50, 40, 80)]
    scores = [0.9, 0.8, 0.2]
    assert L.primary_signal(boxes, scores, 768)[:4] == (300, 50, 30, 60)


def test_primary_signal_none_when_nothing_confident():
    assert L.primary_signal([(0, 0, 10, 10)], [0.1], 768) is None


# ---- red-evidence veto -------------------------------------------------------

def image(w, h, fill, patch=None, patch_box=None):
    px = [[fill for _ in range(w)] for _ in range(h)]
    if patch:
        x0, y0, x1, y1 = patch_box
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[y][x] = patch
    return lambda x, y: px[y][x]


HOUSING_GREEN = (40, 90, 60)      # painted housing, dull
LIT_RED = (250, 60, 70)
LIT_CYAN_GREEN = (60, 240, 200)   # Taiwan walking figure
ORANGE_DIGITS = (255, 150, 20)


def test_veto_on_lit_red_figure():
    assert L.red_veto(image(20, 40, HOUSING_GREEN, LIT_RED, (6, 10, 14, 30)), 0, 0, 20, 40)


def test_no_veto_on_green_figure_in_green_housing():
    assert not L.red_veto(image(20, 40, HOUSING_GREEN, LIT_CYAN_GREEN, (6, 10, 14, 30)), 0, 0, 20, 40)


def test_orange_countdown_is_not_red():
    get = image(20, 40, HOUSING_GREEN, ORANGE_DIGITS, (4, 2, 16, 14))
    assert not L.red_veto(get, 0, 0, 20, 40)


def test_dark_housing_alone_is_not_red():
    assert not L.red_veto(image(20, 40, (30, 20, 20)), 0, 0, 20, 40)


def test_veto_subsamples_large_boxes():
    get = image(200, 200, HOUSING_GREEN, LIT_RED, (50, 50, 150, 150))
    assert L.red_veto(get, 0, 0, 200, 200)


def test_solid_green_needs_same_red_lookback_as_flash():
    """Regression: after real red frames, a burst of (possibly misclassified) green must not
    reach GREEN before the red look-back window has fully passed."""
    labels = ["red"] * 14 + ["green"] * 40
    states = run(labels)
    last_red_t = 13 * FRAME_MS
    for i, s in enumerate(states):
        if s == L.GREEN:
            assert i * FRAME_MS - last_red_t > L.RED_LOOKBACK_MS
            break
    else:
        raise AssertionError("never reached GREEN")


def test_no_green_after_flash_until_red():
    """After GREEN_FLASHING the phase is ending: steady-looking green must not become GREEN
    ("go") until a RED starts a new cycle."""
    labels = ["green"] * 20 + pattern("green", 500, "none", 500, 3000) + ["green"] * 40
    states = run(labels)
    flash_at = states.index(L.GREEN_FLASH)
    assert L.GREEN not in states[flash_at:]


def test_green_allowed_again_after_red_following_flash():
    labels = pattern("green", 500, "none", 500, 3000) + ["red"] * 30 + ["green"] * 60
    states = run(labels)
    assert L.GREEN_FLASH in states
    assert states[-1] == L.GREEN


def test_flash_memory_resets_after_long_absence():
    labels = pattern("green", 500, "none", 500, 3000) + ["none"] * (L.FLASH_RESET_MS // FRAME_MS + 5) + ["green"] * 30
    states = run(labels)
    assert states[-1] == L.GREEN


def test_small_signals_are_not_read():
    """Color of a signal shorter than MIN_READ_PX (sensor px) is unreliable: never read it."""
    assert not L.readable(L.MIN_READ_PX - 1)
    assert L.readable(L.MIN_READ_PX)
    assert L.readable(80)


def test_classifier_rejects_non_signals():
    """Stage 2 vetoes stage 1: a crop the classifier calls 'other' is not a pedestrian signal."""
    assert L.label_from_probs({"red": 0.1, "green": 0.1, "other": 0.8}, False) == "none"
    assert L.label_from_probs({"red": 0.3, "green": 0.2, "other": 0.5}, False) == "unk"   # undecided
    assert L.label_from_probs({"red": 0.7, "green": 0.0, "other": 0.3}, False) == "red"


def test_handheld_jitter_is_not_flashing():
    """Irregular dropouts (long on-phases) from a shaking camera must not look like a flashing signal."""
    labels = (["green"] * 20 + ["none"] * 4 + ["green"] * 15 + ["none"] * 6 + ["green"] * 25
              + ["none"] * 3 + ["green"] * 18)
    assert L.GREEN_FLASH not in run(labels)


def test_implausible_boxes_are_not_read():
    """Only boxes shaped and sized like a pedestrian signal are read (sensor px)."""
    assert L.plausible(30, 55)                      # typical signal, h/w ~1.8
    assert not L.plausible(10, 15)                  # too small to read
    assert not L.plausible(600, 760)                # whole-screen box, too big and too square
    assert not L.plausible(100, 90)                 # square: not two stacked lamps
    assert not L.plausible(10, 60)                  # thin sliver: side view
    assert L.plausible(L.MAX_READ_PX / 1.8, L.MAX_READ_PX)
    assert not L.plausible((L.MAX_READ_PX + 1) / 1.8, L.MAX_READ_PX + 1)


def test_green_is_kept_through_handheld_dropouts():
    """Hysteresis: once GREEN, a ~50% detection rate (shaky hand-held camera) keeps GREEN."""
    labels = ["green"] * 20 + ["green", "none"] * 20
    states = run(labels)
    assert states[19] == L.GREEN
    assert all(s == L.GREEN for s in states[20:])


def test_green_still_left_immediately_on_red_with_hysteresis():
    labels = ["green"] * 20 + ["green", "none"] * 5 + ["red"]
    states = run(labels)
    assert states[-2] == L.GREEN and states[-1] != L.GREEN


def test_green_left_when_signal_disappears():
    labels = ["green"] * 20 + ["none"] * 15
    states = run(labels)
    first_unknown = states.index(L.UNKNOWN, 20)
    assert (first_unknown - 20) * FRAME_MS <= 1200


def test_irregular_on_off_is_not_flashing():
    """Cycles inside the flash ranges but irregular (shaky camera) are not a hardware-timed flash."""
    labels = (["green"] * 3 + ["none"] * 9 + ["green"] * 10 + ["none"] * 3 + ["green"] * 4
              + ["none"] * 11 + ["green"] * 12 + ["none"] * 3 + ["green"] * 10)
    assert L.GREEN_FLASH not in run(labels)
