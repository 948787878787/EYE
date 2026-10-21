"""Tests for board/crossing_select_v1.py: pick the signal of THIS crossing (crosswalk direction), then the nearest one
(largest) among signals in line; a near tie or a non-green nearer signal turns GREEN into unk."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import crossing_select_v1 as S  # noqa: E402

FAR = (500.0, 400.0)           # far end of the crossing's midline (window px)
OWNED = (FAR, 10.0)            # CrosswalkTracker.owned_far(): (far, tol_px)


def reader(labels):
    calls = []

    def read(box):
        calls.append(tuple(box[:4]))
        return labels[tuple(box[:4])]
    return read, calls


def test_not_green_passes_through_and_reads_nothing():
    read, calls = reader({})
    for label in ("red", "unk", "none"):
        assert S.gate(label, (480, 200, 30, 54), [(480, 200, 30, 54)], [0.9], OWNED, read) == (label, "")
    assert calls == []


def test_without_a_crosswalk_a_single_signal_passes():
    read, _ = reader({})
    assert S.gate("green", (480, 200, 30, 54), [(480, 200, 30, 54)], [0.9], None, read) == ("green", "")


def test_two_stage_near_green_far_red_keeps_green_and_says_wait_at_the_island():
    near, far = (485, 200, 30, 54), (492, 300, 14, 25)        # same line; far one clearly smaller (2.1x)
    read, _ = reader({near: "green", far: "red"})
    assert S.gate("green", near, [near, far], [0.9, 0.8], OWNED, read) == ("green", S.ISLAND_WAIT)


def test_two_stage_needs_the_crosswalk_to_tell_it_is_in_line():
    near, far = (485, 200, 30, 54), (492, 300, 14, 25)
    read, _ = reader({near: "green", far: "red"})
    assert S.gate("green", near, [near, far], [0.9, 0.8], None, read) == ("green", "")


def test_near_tie_between_green_and_red_is_unk():
    a, b = (470, 200, 30, 54), (520, 205, 28, 50)            # 1.06x: size cannot say which is nearer
    read, _ = reader({a: "green", b: "red"})
    assert S.gate("green", a, [a, b], [0.9, 0.9], OWNED, read) == ("unk", S.SIZE_TIE)


def test_near_tie_both_green_stays_green():
    a, b = (470, 200, 30, 54), (520, 205, 28, 50)
    read, _ = reader({a: "green", b: "green"})
    assert S.gate("green", a, [a, b], [0.9, 0.9], OWNED, read) == ("green", "")


def test_primary_off_the_crossing_uses_the_crossing_signal():
    side = (20, 150, 16, 72)                                   # larger signal far to the left: another crossing
    mine = (488, 240, 20, 36)
    read, _ = reader({side: "green", mine: "red"})
    assert S.gate("green", side, [side, mine], [0.9, 0.8], OWNED, read) == ("unk", S.NOT_ON_CROSSING)
    read, _ = reader({side: "green", mine: "green"})
    assert S.gate("green", side, [side, mine], [0.9, 0.8], OWNED, read) == ("green", S.NOT_ON_CROSSING)


def test_no_signal_on_the_crossing_is_unk():
    side = (20, 150, 16, 72)
    read, _ = reader({side: "green"})
    assert S.gate("green", side, [side], [0.9], OWNED, read) == ("unk", S.NOT_ON_CROSSING)


def test_a_larger_signal_on_the_crossing_that_is_not_green_wins():
    small, big = (495, 300, 14, 25), (480, 200, 30, 54)       # the reader picked the smaller one
    read, _ = reader({small: "green", big: "unk"})
    assert S.gate("green", small, [small, big], [0.9, 0.9], OWNED, read) == ("unk", S.NEARER_NOT_GREEN)


def test_low_score_boxes_are_ignored():
    near, ghost = (485, 200, 30, 54), (480, 190, 31, 56)
    read, calls = reader({near: "green", ghost: "red"})
    assert S.gate("green", near, [near, ghost], [0.9, 0.1], OWNED, read) == ("green", "")
    assert calls == []


def test_size_is_linear_size_of_the_area():
    assert abs(S.linear_size((0, 0, 4, 9)) - 6.0) < 1e-9
    assert S.linear_size((0, 0, 0, 9)) == 0.0


def test_a_weakly_detected_larger_red_still_blocks_a_far_green():
    # IMG_4644 pattern (2026-10-20): near red 51x110 at score 0.47 and far green 21x39 at 0.54; if the near red
    # drops below PRIMARY_CONF the reader picks the far green, but a larger box >= GUARD_CONF that is red blocks it
    near_red, far_green = (494, 542, 51, 110), (1039, 685, 21, 39)
    read, _ = reader({near_red: "red", far_green: "green"})
    assert S.gate("green", far_green, [far_green, near_red], [0.54, 0.30], None, read) == ("unk", S.NEARER_NOT_GREEN)
    read, calls = reader({near_red: "red", far_green: "green"})
    assert S.gate("green", far_green, [far_green, near_red], [0.54, 0.20], None, read) == ("green", "")
