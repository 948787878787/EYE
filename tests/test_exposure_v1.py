"""board/exposure_v1.py: biased exposure control converges, prefers exposure over gain, never oscillates."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import exposure_v1 as E  # noqa: E402

EXP, GAIN = (100, 33000), (1.0, 16.0)


def scene(light):
    """Mean of a frame for a scene of brightness `light` (mean per exposure-us x gain), clipped at 255."""
    return lambda exp, gain: min(255, light * exp * gain)


def simulate(c, render, frames=600):
    means = []
    for _ in range(frames):
        m = render(c.exp, c.gain)
        means.append(m)
        c.update(m)
    return means


@pytest.mark.parametrize("light", [0.005, 0.02, 0.1])
def test_converges_to_the_biased_target(light):
    c = E.ExposureControl(EXP, GAIN, 5000, 1.0)
    means = simulate(c, scene(light))
    assert abs(E.TARGET / means[-1] - 1) < E.DEADBAND         # the deadband is on target / mean
    assert E.TARGET == pytest.approx(E.AE_TARGET / 2)


def test_bright_scene_lowers_exposure_and_keeps_minimum_gain():
    c = E.ExposureControl(EXP, GAIN, 8000, 2.0)
    simulate(c, scene(0.1))
    assert c.gain == GAIN[0] and c.exp < 8000


def test_exposure_is_capped_for_motion_blur_then_gain_rises():
    c = E.ExposureControl(EXP, GAIN, 5000, 1.0)
    simulate(c, scene(0.0005))                                # dim street
    assert c.exp == E.EXP_CAP_US and c.gain > 1.0


def test_too_dark_saturates():
    c = E.ExposureControl(EXP, GAIN, 5000, 1.0)
    simulate(c, scene(0.000001))
    assert c.saturated()


def test_no_oscillation_once_settled():
    c = E.ExposureControl(EXP, GAIN, 5000, 1.0)
    simulate(c, scene(0.02), 600)
    changes = [c.update(scene(0.02)(c.exp, c.gain)) for _ in range(300)]
    assert all(x is None for x in changes)


def test_steps_are_bounded_and_spaced():
    c = E.ExposureControl(EXP, GAIN, 5000, 1.0)
    out = [c.update(255) for _ in range(E.UPDATE_EVERY * 3)]
    changed = [i for i, x in enumerate(out) if x is not None]
    assert changed == [E.UPDATE_EVERY - 1, 2 * E.UPDATE_EVERY - 1, 3 * E.UPDATE_EVERY - 1]
    assert out[E.UPDATE_EVERY - 1][0] == pytest.approx(5000 / E.MAX_STEP, abs=1)


def test_black_frame_does_not_divide_by_zero():
    c = E.ExposureControl(EXP, GAIN, 5000, 1.0)
    out = [c.update(0) for _ in range(30)]
    assert all(x is None or x[0] >= 5000 for x in out)        # a black frame only ever brightens
