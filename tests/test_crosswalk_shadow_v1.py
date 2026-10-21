"""board/crosswalk_shadow_v1.py: pose output -> window-px midline; shadow gate never changes non-green labels."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))
import crosswalk_shadow_v1 as S  # noqa: E402


def test_midline_from_row_undoes_letterbox_and_window_origin():
    row = [0, 0, 10, 10, 0.7, 0, 160, 170, 1, 150, 80, 1]
    score, near, far = S.midline_from_row(row, 0.25, (128, 0))
    assert score == 0.7
    assert near == (640 - 128, 680) and far == (600 - 128, 320)


def test_top_row_index():
    assert S.top_row_index([0.1, 0.8, 0.8, 0.3]) == 1
    assert S.top_row_index([]) is None


def test_tracker_input_threshold():
    assert S.tracker_input(None) is None
    assert S.tracker_input((0.2, (1, 2), (3, 4))) is None
    assert S.tracker_input((0.25, (1, 2), (3, 4))) == ((1, 2), (3, 4))


def test_shadow_passes_non_green_and_no_signal():
    read = lambda b: "green"  # noqa: E731
    assert S.shadow("red", (0, 0, 10, 20, 0.9), [(0, 0, 10, 20)], [0.9], None, read) == ("red", "")
    assert S.shadow("none", None, [], [], None, read) == ("none", "")


def test_shadow_blocks_green_off_the_crossing():
    sig = (100, 50, 10, 20, 0.9)
    owned = ((500.0, 80.0), 30.0)          # crossing's far end far to the right of the signal
    label, note = S.shadow("green", sig, [sig[:4]], [0.9], owned, lambda b: "green")
    assert label == "unk" and note == "not-on-crossing"


def test_centered_pad_for_the_chn2_frame():
    assert S.centered_pad((1280, 720), (320, 320)) == (70, 70, 0, 0, 0.25)


def test_midline_from_row_removes_the_centered_pad():
    row = [0, 0, 10, 10, 0.7, 0, 160, 240, 1, 150, 150, 1]
    _, near, far = S.midline_from_row(row, 0.25, (128, 0), pad=(0, 70))
    assert near == (640 - 128, 680) and far == (600 - 128, 320)
