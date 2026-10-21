"""Tests for board/ped_logic_v4.py: the 2026-10-05 architecture-review fixes A2 A4 A6 A7 A8
(docs/analysis/2026-10-05_architecture_review.md) on top of v3's neighbour guard."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import ped_logic_v4 as L  # noqa: E402

FRAME_MS = 100
WIN_W, WIN_H = 640, 360

GREEN_BOX = (300, 150, 10, 20)      # primary, well inside the window
RED_ABOVE = (300, 128, 10, 20)      # the red lamp of the same head, right above


def run(labels, blocked=None, start=0):
    voter = L.Voter()
    blocked = blocked or [False] * len(labels)
    return [voter.update(start + i * FRAME_MS, lab, b) for i, (lab, b) in enumerate(zip(labels, blocked))]


def pattern(on_label, on_ms, off_label, off_ms, total_ms):
    out, t = [], 0
    while t < total_ms:
        out.append(on_label if t % (on_ms + off_ms) < on_ms else off_label)
        t += FRAME_MS
    return out


def reader(labels):
    def read(box):
        return labels[tuple(box[:4])]
    return read


# ---- A2: three thresholds ---------------------------------------------------

def test_thresholds_are_split():
    assert L.DET_POST_CONF < L.GUARD_CONF < L.PRIMARY_CONF


def test_primary_ignores_boxes_below_primary_conf():
    assert L.primary_signal([GREEN_BOX], [L.PRIMARY_CONF - 0.01], WIN_W) is None
    assert L.primary_signal([GREEN_BOX], [L.PRIMARY_CONF], WIN_W)[:4] == GREEN_BOX


def test_weak_red_neighbour_above_guard_conf_blocks_green():
    """s021_img_0018: the red lamp above scored below 0.35 and v3 never looked at it."""
    sig = GREEN_BOX + (0.45,)
    read = reader({RED_ABOVE: "red"})
    assert L.guard_green("green", sig, [GREEN_BOX, RED_ABOVE], [0.45, 0.30], read) == "unk"


def test_neighbour_below_guard_conf_is_ignored():
    sig = GREEN_BOX + (0.45,)
    read = reader({RED_ABOVE: "red"})
    assert L.guard_green("green", sig, [GREEN_BOX, RED_ABOVE], [0.45, L.GUARD_CONF - 0.01], read) == "green"


# ---- A4: neighbours are read without the shape gate -------------------------

def test_neighbour_label_vetoed_is_red():
    probs = {"green": 0.9, "other": 0.05, "red": 0.05}
    assert L.neighbour_label(probs, True) == "red"


def test_neighbour_label_other_does_not_block():
    assert L.neighbour_label({"green": 0.1, "other": 0.8, "red": 0.1}, False) == "none"


def test_neighbour_label_unclear_is_unk():
    assert L.neighbour_label({"green": 0.5, "other": 0.2, "red": 0.3}, False) == "unk"


def test_unreadably_small_neighbour_blocks():
    assert L.neighbour_label(None, False) == "unk"


# ---- MIN_READ_PX 16 ---------------------------------------------------------

def test_read_cut_is_16_px_and_plausible_uses_it():
    assert L.readable(16) and not L.readable(15.9)
    assert L.plausible(10, 17) and not L.plausible(10, 15)


# ---- A6: window edges -------------------------------------------------------

def test_green_touching_the_window_edge_is_unk():
    assert L.edge_guard("green", (0, 150, 10, 20, 0.5), WIN_W, WIN_H) == "unk"
    assert L.edge_guard("green", (WIN_W - 10, 150, 10, 20, 0.5), WIN_W, WIN_H) == "unk"
    assert L.edge_guard("green", (300, WIN_H - 20, 10, 20, 0.5), WIN_W, WIN_H) == "unk"


def test_green_without_room_above_for_the_red_lamp_is_unk():
    assert L.edge_guard("green", (300, 10, 10, 20, 0.5), WIN_W, WIN_H) == "unk"


def test_green_inside_the_window_passes_and_red_is_untouched():
    assert L.edge_guard("green", GREEN_BOX + (0.5,), WIN_W, WIN_H) == "green"
    assert L.edge_guard("red", (0, 0, 10, 20, 0.5), WIN_W, WIN_H) == "red"


def test_apply_guards_reports_a_block():
    read = reader({RED_ABOVE: "red"})
    label, blocked = L.apply_guards("green", GREEN_BOX + (0.45,), [GREEN_BOX, RED_ABOVE], [0.45, 0.30], read,
                                    WIN_W, WIN_H)
    assert (label, blocked) == ("unk", True)
    label, blocked = L.apply_guards("red", GREEN_BOX + (0.45,), [GREEN_BOX], [0.45], read, WIN_W, WIN_H)
    assert (label, blocked) == ("red", False)


# ---- Voter: steady behaviour unchanged ---------------------------------------

def test_steady_green_still_announced_after_hold():
    states = run(["green"] * 30)
    assert states[-1] == L.GREEN


def test_red_leaves_green_at_once_and_then_becomes_red():
    states = run(["green"] * 30 + ["red"] * 16)
    assert states[30] != L.GREEN
    assert states[-1] == L.RED


# ---- A7: a guard block latches like a red vote ------------------------------

def test_one_guard_block_keeps_green_off_for_the_red_lookback():
    labels = ["unk"] + ["green"] * 40                        # 4 s
    blocked = [True] + [False] * 40
    states = run(labels, blocked)
    t_first_green = states.index(L.GREEN) * FRAME_MS
    assert t_first_green > L.RED_LOOKBACK_MS


def test_block_in_the_middle_of_green_drops_it():
    labels = ["green"] * 30 + ["unk"] + ["green"] * 10
    blocked = [False] * 30 + [True] + [False] * 10
    states = run(labels, blocked)
    assert states[29] == L.GREEN
    assert L.GREEN not in states[30:]


# ---- A8: flashing needs an established GREEN and a green share --------------

def test_flash_pattern_without_a_prior_green_is_not_announced():
    states = run(pattern("green", 500, "none", 500, 4000))
    assert L.GREEN_FLASH not in states


def test_flash_after_green_is_announced():
    states = run(["green"] * 20 + pattern("green", 500, "none", 500, 4000))
    assert L.GREEN in states and L.GREEN_FLASH in states


def test_sparse_regular_greens_do_not_make_a_flash():
    """Regular greens of 3 frames every 1.5 s (v1 calls this flashing) after GREEN: ~20% < the flash green share."""
    states = run(["green"] * 20 + pattern("green", 300, "none", 1200, 6000))
    assert L.GREEN_FLASH not in states[25:]


def test_v1_would_flash_on_the_sparse_pattern():
    """Guard for the test above: the pattern must be one v1 accepts as flashing."""
    import ped_logic_v1 as V1
    voter = V1.Voter()
    labels = ["green"] * 20 + pattern("green", 300, "none", 1200, 6000)
    assert V1.GREEN_FLASH in [voter.update(i * FRAME_MS, l) for i, l in enumerate(labels)]


def test_red_resets_the_established_green():
    states = run(["green"] * 20 + ["red"] * 10 + pattern("green", 500, "none", 500, 4000))
    assert L.GREEN_FLASH not in states[30:]
