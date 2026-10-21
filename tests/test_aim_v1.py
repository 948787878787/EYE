"""board/aim_v1.py AimGuide: spoken turn / aligned prompts, never while green or during a fault, never a tone."""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import aim_v1 as A  # noqa: E402
from ped_logic_v1 import GREEN, GREEN_FLASH, RED, UNKNOWN  # noqa: E402

FACING = (12, 24)              # w, h: h/w 2.0


def run(cxs, state=RED, fault=None, step=70, aim=None):
    aim = aim or A.AimGuide()
    out = []
    for i, cx in enumerate(cxs):
        sig = None if cx is None else (cx, *FACING)
        out.append((i * step, aim.update(i * step, state, fault, sig)))
    return out, aim


def said(out):
    return [(t, k) for t, ks in out for k in ks]


def test_left_signal_asks_to_turn_left_once_settled():
    out, _ = run([0.2] * 20)
    s = said(out)
    assert s[0][1] == "turn_left" and s[0][0] >= (A.PRESENCE_MIN_HITS - 1) * 70
    assert [k for _, k in s] == ["turn_left"]                  # cooldown: not repeated within 3 s (1.4 s run)


def test_turning_to_the_centre_says_aligned_once():
    out, _ = run([0.8] * 15 + [0.5] * 30)
    assert [k for _, k in said(out)] == ["turn_right", "aligned"]


def test_centred_from_the_start_says_nothing():
    out, _ = run([0.5] * 50)
    assert said(out) == []


def test_hysteresis_band_does_not_flip():
    out, _ = run([0.33] * 20 + [0.38] * 20)                   # 0.38 is inside the band: stays "left"
    assert [k for _, k in said(out)] == ["turn_left"]


def test_side_facing_boxes_are_ignored():
    aim = A.AimGuide()
    out = [aim.update(i * 70, RED, None, (0.2, 30, 20)) for i in range(20)]    # h/w 0.67: seen from the side
    assert not any(out)


def test_flicker_is_not_enough():
    out, _ = run([0.2, None, None, None] * 10)
    assert said(out) == []


@pytest.mark.parametrize("state", [GREEN, GREEN_FLASH])
def test_silent_while_green(state):
    out, _ = run([0.2] * 30, state=state)
    assert said(out) == []


def test_silent_during_a_fault_and_forgets_the_zone():
    aim = A.AimGuide()
    run([0.8] * 15, aim=aim)
    out, _ = run([0.5] * 20, fault="camera_dark", aim=aim)
    assert said(out) == [] and not aim.turned


def test_repeats_after_the_cooldown():
    out, _ = run([0.2] * 80)                                  # 5.6 s
    times = [t for t, k in said(out) if k == "turn_left"]
    assert len(times) == 2 and times[1] - times[0] >= A.COOLDOWN_MS


@pytest.mark.parametrize("seed", range(200))
def test_only_spoken_keys_and_never_while_green(seed):
    rnd = random.Random(seed)
    aim, t = A.AimGuide(), 0
    for _ in range(200):
        t += rnd.choice([40, 70, 120])
        state = rnd.choice([RED, UNKNOWN, GREEN, GREEN_FLASH])
        sig = rnd.choice([None, (rnd.random(), 10, rnd.choice([5, 20, 40]))])
        ks = aim.update(t, state, rnd.choice([None] * 6 + ["slow"]), sig)
        assert set(ks) <= {A.SAY_LEFT, A.SAY_RIGHT, A.SAY_ALIGNED}
        if ks:
            assert state not in (GREEN, GREEN_FLASH)
