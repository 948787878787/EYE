"""Tests for board/ped_logic_v3.py: no GREEN while a neighbouring signal on the same pole reads red or unclear."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import ped_logic_v1 as V1  # noqa: E402
import ped_logic_v3 as L  # noqa: E402

# the 2026-09-26 case (-2025-11-16-214839): green signal of another crossing at the window edge is the largest
# box by 9 px^2; the red man facing the user sits right next to it
GREEN_EDGE = (756, 334, 10, 24)
RED_FACING = (738, 338, 11, 21)
FAR_LEFT = (31, 351, 9, 19)


def reader(labels):
    calls = []

    def read(box):
        calls.append(box[:4])
        return labels[tuple(box[:4])]
    return read, calls


def test_v3_keeps_every_v1_name():
    assert L.Voter is V1.Voter and L.primary_signal is V1.primary_signal and L.DET_CONF == V1.DET_CONF


def test_green_is_blocked_by_a_red_neighbour_on_the_same_pole():
    sig = L.primary_signal([GREEN_EDGE, RED_FACING], [0.668, 0.555], 768)
    assert sig[:4] == GREEN_EDGE                       # v1 picks the wrong one
    read, _ = reader({RED_FACING: "red"})
    assert L.guard_green("green", sig, [GREEN_EDGE, RED_FACING], [0.668, 0.555], read) == "unk"


def test_an_unclear_neighbour_also_blocks_green():
    read, _ = reader({RED_FACING: "unk"})
    sig = GREEN_EDGE + (0.668,)
    assert L.guard_green("green", sig, [GREEN_EDGE, RED_FACING], [0.668, 0.555], read) == "unk"


def test_green_or_non_signal_neighbours_do_not_block():
    for other in ("green", "none"):
        read, _ = reader({RED_FACING: other})
        sig = GREEN_EDGE + (0.668,)
        assert L.guard_green("green", sig, [GREEN_EDGE, RED_FACING], [0.668, 0.555], read) == "green"


def test_far_or_weak_boxes_are_ignored_and_never_classified():
    read, calls = reader({})
    sig = GREEN_EDGE + (0.668,)
    boxes, scores = [GREEN_EDGE, FAR_LEFT, RED_FACING], [0.668, 0.685, L.DET_CONF - 0.01]
    assert L.guard_green("green", sig, boxes, scores, read) == "green"
    assert calls == []                                 # far box and sub-threshold box cost no classifier run


def test_only_green_is_checked():
    read, calls = reader({RED_FACING: "red"})
    for label in ("red", "unk", "none"):
        sig = GREEN_EDGE + (0.668,)
        assert L.guard_green(label, sig, [GREEN_EDGE, RED_FACING], [0.668, 0.555], read) == label
    assert calls == []


def test_near_means_within_three_long_sides_on_both_axes():
    sig = (100, 100, 10, 20, 0.9)                      # center (105, 110), long side 20 -> 60 px
    assert L.near(sig, (160, 100, 10, 20))             # centers 60 px apart
    assert not L.near(sig, (161, 100, 10, 20))
    assert not L.near(sig, (100, 171, 10, 20))
