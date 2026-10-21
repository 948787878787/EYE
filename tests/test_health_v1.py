"""board/health_v1.py: camera dark / blocked and slow-loop faults, with hold and recovery times."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import health_v1 as H  # noqa: E402

GOOD = (120, 90)               # mean, spread of a normal street frame


def feed(h, frames, start=0, step=70):
    """frames: list of (mean, spread); returns the fault after each frame."""
    return [h.update(start + i * step, m, s) for i, (m, s) in enumerate(frames)]


def test_frame_stats():
    assert H.frame_stats([]) == (0, 0)
    assert H.frame_stats([100] * 50) == (100, 0)
    mean, spread = H.frame_stats(list(range(256)))
    assert mean == 127 and spread == 230 - 25


def test_normal_frames_have_no_fault():
    assert set(feed(H.Health(), [GOOD] * 100)) == {None}


def test_dark_becomes_a_fault_only_after_the_hold():
    out = feed(H.Health(), [(8, 3)] * 40)
    first = out.index(H.CAMERA_DARK)
    assert first * 70 >= H.HOLD_MS and (first - 1) * 70 < H.HOLD_MS


def test_covered_lens_is_blocked_not_dark():
    out = feed(H.Health(), [(60, 4)] * 40)
    assert out[-1] == H.CAMERA_BLOCKED and H.CAMERA_DARK not in out


def test_a_short_flicker_does_not_toggle():
    out = feed(H.Health(), [GOOD] * 10 + [(5, 2)] * 5 + [GOOD] * 10)
    assert set(out) == {None}


def test_fault_clears_after_recovery_time():
    h = H.Health()
    out = feed(h, [(5, 2)] * 40 + [GOOD] * 30)
    clear = next(i for i in range(40, 70) if out[i] is None)
    assert (clear - 40) * 70 >= H.RECOVER_MS


def test_slow_loop_is_a_fault():
    h = H.Health()
    out = [h.update(i * 400, *GOOD) for i in range(20)]       # 2.5 fps
    assert out[-1] == H.SLOW
    h2 = H.Health()
    assert set(h2.update(i * 200, *GOOD) for i in range(40)) == {None}     # 5 fps is fine


def test_blocked_wins_over_slow():
    h = H.Health()
    out = [h.update(i * 400, 60, 3) for i in range(20)]
    assert out[-1] == H.CAMERA_BLOCKED
