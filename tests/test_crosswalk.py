"""Tests for board/crosswalk_v1.py: crosswalk heading, alignment hint, signal ownership, and the GREEN safety gate."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import crosswalk_v1 as X  # noqa: E402

W = 1024                       # window width px (v7 window at the chn2 scale)
CX = W / 2
F = X.focal_px(W, 70.0)        # focal length for a 70 deg horizontal field of view


def x_at(deg):
    """Window x of a direction deg degrees right of the optical axis."""
    return CX + F * math.tan(math.radians(deg))


# ---------- geometry ----------

def test_focal_and_bearing_round_trip():
    assert abs(X.focal_px(W, 90.0) - W / 2) < 1e-6
    for deg in (-30, -5, 0, 12, 40):
        assert abs(X.bearing_deg(x_at(deg), CX, F) - deg) < 1e-6


def test_heading_uses_the_far_end_without_a_horizon():
    near, far = (CX, 570), (x_at(15), 300)
    assert abs(X.midline_heading(near, far, CX, F) - 15) < 1e-6


def test_heading_extends_the_midline_to_the_horizon_when_given():
    # line through (512, 570) and (612, 370): x = 512 + (570 - y) / 2 ; at y 270 -> 662
    near, far = (512, 570), (612, 370)
    assert abs(X.midline_heading(near, far, CX, F, horizon_y=270) - X.bearing_deg(662, CX, F)) < 1e-6


def test_horizon_is_ignored_for_a_flat_line():
    near, far = (100, 400), (900, 399.5)
    assert X.midline_heading(near, far, CX, F, horizon_y=100) == X.midline_heading(near, far, CX, F)


def test_valid_midline_rejects_swapped_short_and_flat_lines():
    assert X.valid_midline((500, 570), (520, 300), W)
    assert not X.valid_midline((520, 300), (500, 570), W)       # far end below the near end
    assert not X.valid_midline((500, 570), (505, 560), W)       # too short
    assert not X.valid_midline((0, 570), (1000, 500), W)        # runs across the view: another crossing


def test_valid_midline_rejects_none():
    assert not X.valid_midline(None, (1, 2), W)
    assert not X.valid_midline((1, 2), None, W)


# ---------- alignment ----------

def test_alignment_zones():
    assert X.alignment(0.0) == X.ALIGNED
    assert X.alignment(-X.ALIGN_ENTER_DEG) == X.ALIGNED
    assert X.alignment(X.ALIGN_LEAVE_DEG + 1) == X.SAY_CW_RIGHT
    assert X.alignment(-(X.ALIGN_LEAVE_DEG + 1)) == X.SAY_CW_LEFT
    assert X.alignment(X.GUIDE_MAX_DEG + 1) is None             # too far off: likely another crossing, no hint


def test_alignment_hysteresis():
    between = (X.ALIGN_ENTER_DEG + X.ALIGN_LEAVE_DEG) / 2
    assert X.alignment(between, was_aligned=True) == X.ALIGNED
    assert X.alignment(between, was_aligned=False) == X.SAY_CW_RIGHT
    assert X.alignment(-between, was_aligned=False) == X.SAY_CW_LEFT


def test_hint_keys_are_turns_never_steps():
    assert "turn" in X.SAY_CW_LEFT and "turn" in X.SAY_CW_RIGHT
    for key in (X.SAY_CW_LEFT, X.SAY_CW_RIGHT, X.ALIGNED):
        assert "step" not in key and "move" not in key and "green" not in key


# ---------- ownership ----------

FAR = (x_at(0), 330)


def box_at(cx, bottom, w=10, h=20):
    return (cx - w / 2, bottom - h, w, h)


def test_signal_above_the_far_end_belongs_to_the_crossing():
    b = box_at(FAR[0] + 30, 250)                               # 3 box widths = 0.9 m to the side
    assert abs(X.lateral_m(b, FAR) - 3 * X.SIGNAL_W_M) < 1e-6
    assert X.on_crossing(b, FAR)


def test_signal_far_to_the_side_does_not_belong():
    b = box_at(FAR[0] + 300, 250)                              # 30 widths = 9 m: across the other street
    assert not X.on_crossing(b, FAR)


def test_signal_below_the_far_end_does_not_belong():
    assert not X.on_crossing(box_at(FAR[0], 400), FAR)


def test_tolerance_absorbs_midline_error():
    b = box_at(FAR[0] + 230, 250)                              # 23 widths = 6.9 m
    assert not X.on_crossing(b, FAR)
    assert X.on_crossing(b, FAR, tol_px=40)                    # 19 widths = 5.7 m
    assert X.on_crossing(box_at(FAR[0], FAR[1] + 5), FAR, tol_px=10)


def test_lateral_of_an_empty_box_is_infinite():
    assert X.lateral_m((10, 10, 0, 20), FAR) == float("inf")


def test_pick_signal_prefers_the_signal_nearest_the_walking_line():
    own = box_at(FAR[0] + 40, 250)
    other_corner = box_at(FAR[0] - 120, 250, w=14, h=28)       # bigger, but farther from the line
    far_street = box_at(FAR[0] + 500, 240, w=20, h=40)         # largest, 25 widths = 7.5 m: across the other street
    boxes = [far_street, other_corner, own]
    got = X.pick_signal(boxes, [0.9, 0.8, 0.6], FAR)
    assert got[:4] == own and got[4] == 0.6


def test_pick_signal_ignores_weak_boxes_and_returns_none_when_nothing_belongs():
    own = box_at(FAR[0], 250)
    assert X.pick_signal([own], [X.DET_CONF - 0.01], FAR) is None
    assert X.pick_signal([box_at(FAR[0] + 500, 240)], [0.9], FAR) is None
    assert X.pick_signal([], [], FAR) is None


# ---------- safety gate: never more GREEN ----------

LABELS = ("green", "red", "unk", "none")


def test_gate_passes_everything_through_without_a_crossing():
    for lab in LABELS:
        for other in (None,) + LABELS:
            assert X.gate_label(lab, None, other) == lab


def test_gate_never_creates_green():
    for lab in ("red", "unk", "none"):
        for owned in (True, False):
            for other in (None,) + LABELS:
                assert X.gate_label(lab, owned, other) == lab


def test_green_of_another_crossing_becomes_unclear():
    assert X.gate_label("green", False, None) == "unk"
    assert X.gate_label("green", False, "red") == "unk"
    assert X.gate_label("green", False, "unk") == "unk"


def test_green_not_owned_but_confirmed_by_the_crossing_signal():
    assert X.gate_label("green", False, "green") == "green"


def test_owned_green_is_vetoed_by_a_red_or_unclear_crossing_signal():
    assert X.gate_label("green", True, None) == "green"
    assert X.gate_label("green", True, "green") == "green"
    assert X.gate_label("green", True, "red") == "unk"
    assert X.gate_label("green", True, "unk") == "unk"
    assert X.gate_label("green", True, "none") == "green"      # "none" = classifier says not a ped signal


def test_gate_output_is_green_only_if_input_was_green():
    for lab in LABELS:
        for owned in (None, True, False):
            for other in (None,) + LABELS:
                out = X.gate_label(lab, owned, other)
                assert out in LABELS
                if out == "green":
                    assert lab == "green"


# ---------- tracker ----------

def feed(tr, t0, n, heading, dt=400, far_y=300):
    for k in range(n):
        tr.update(t0 + k * dt, ((CX, 570), (x_at(heading), far_y)))
    return t0 + (n - 1) * dt


def test_tracker_needs_several_consistent_observations():
    tr = X.CrosswalkTracker(W, F)
    t = feed(tr, 0, X.MIN_OBS - 1, 5.0)
    assert tr.current(t) is None
    t = feed(tr, t + 400, 1, 5.0)
    cur = tr.current(t)
    assert cur is not None and abs(cur["heading"] - 5.0) < 1e-6
    assert abs(cur["far"][0] - x_at(5.0)) < 1e-6 and cur["near"] == (CX, 570)


def test_tracker_is_stale_after_a_gap():
    tr = X.CrosswalkTracker(W, F)
    t = feed(tr, 0, 5, 5.0)
    assert tr.current(t) is not None
    assert tr.current(t + X.STALE_MS + 1) is None


def test_tracker_rejects_inconsistent_headings():
    tr = X.CrosswalkTracker(W, F)
    t = feed(tr, 0, 3, 0.0)
    t = feed(tr, t + 400, 2, X.MAX_SPREAD_DEG + 5)
    assert tr.current(t) is None                               # user turning or detections jumping


def test_tracker_needs_most_runs_to_find_the_crossing():
    tr = X.CrosswalkTracker(W, F)
    t = feed(tr, 0, 3, 2.0)
    for k in range(4):
        tr.update(t + 400 * (k + 1), None)                     # model ran but found nothing
    t += 1600
    tr.update(t + 400, ((CX, 570), (x_at(2.0), 300)))
    assert tr.current(t + 400) is None


def test_tracker_ignores_invalid_midlines_and_old_observations():
    tr = X.CrosswalkTracker(W, F)
    tr.update(0, ((CX, 300), (CX, 570)))                       # swapped: counted as a miss
    t = feed(tr, 100, 5, 3.0)
    assert tr.current(t) is not None
    t2 = feed(tr, t + X.WINDOW_MS + 500, X.MIN_OBS, -4.0)      # old +3 deg runs have left the window
    assert abs(tr.current(t2)["heading"] + 4.0) < 1e-6


def test_tracker_hint_with_hysteresis():
    tr = X.CrosswalkTracker(W, F)
    assert tr.hint(0) is None                                  # no crossing yet
    t = feed(tr, 0, 5, 20.0)
    assert tr.hint(t) == X.SAY_CW_RIGHT
    t = feed(tr, t + X.WINDOW_MS, 5, 3.0)
    assert tr.hint(t) == X.ALIGNED
    between = (X.ALIGN_ENTER_DEG + X.ALIGN_LEAVE_DEG) / 2
    t = feed(tr, t + X.WINDOW_MS, 5, between)
    assert tr.hint(t) == X.ALIGNED                             # stays aligned inside the hysteresis band
    t = feed(tr, t + X.WINDOW_MS, 5, -(X.ALIGN_LEAVE_DEG + 3))
    assert tr.hint(t) == X.SAY_CW_LEFT


def test_tracker_hint_none_when_the_crossing_is_far_off_axis():
    tr = X.CrosswalkTracker(W, F)
    t = feed(tr, 0, 5, X.GUIDE_MAX_DEG + 5)
    assert tr.current(t) is not None
    assert tr.hint(t) is None


def test_tracker_ownership_is_inactive_for_an_off_axis_crossing():
    tr = X.CrosswalkTracker(W, F)
    t = feed(tr, 0, 5, X.GUIDE_MAX_DEG + 5)
    assert tr.owned_far(t) is None
    t = feed(tr, t + X.WINDOW_MS, 5, 4.0)
    far, tol = tr.owned_far(t)
    assert abs(far[0] - x_at(4.0)) < 1e-6 and abs(tol - X.FAR_TOL_FRAC * W) < 1e-6


def test_tracker_tolerance_grows_with_far_end_jitter():
    tr = X.CrosswalkTracker(W, F)
    for k, dx in enumerate((0, 20, 10, 5)):
        tr.update(k * 400, ((CX, 570), (CX + dx, 300)))
    far, tol = tr.owned_far(1200)
    assert far[0] == CX + 7.5 and abs(tol - (X.FAR_TOL_FRAC * W + 20)) < 1e-6


# ---------- gate_frame: what the reader calls once per frame ----------

def reader(labels):
    calls = []

    def read(box):
        calls.append(tuple(box[:4]))
        return labels[tuple(box[:4])]
    return read, calls


OWN = box_at(FAR[0] + 20, 250)
OTHER = box_at(FAR[0] + 400, 240, w=12, h=24)                  # 33 widths = 10 m: another crossing


def test_gate_frame_without_a_crossing_changes_nothing():
    read, calls = reader({})
    assert X.gate_frame("green", OTHER + (0.9,), [OTHER], [0.9], None, read) == "green"
    assert calls == []


def test_gate_frame_reads_only_for_green():
    read, calls = reader({OWN: "green"})
    assert X.gate_frame("red", OTHER + (0.9,), [OTHER, OWN], [0.9, 0.6], (FAR, 0), read) == "red"
    assert calls == []                                          # the crossing's green never overrides red


def test_gate_frame_vetoes_the_green_of_another_crossing():
    read, calls = reader({OWN: "red"})
    got = X.gate_frame("green", OTHER + (0.9,), [OTHER, OWN], [0.9, 0.6], (FAR, 0), read)
    assert got == "unk" and calls == [OWN]


def test_gate_frame_green_of_another_crossing_without_any_owned_signal():
    read, calls = reader({})
    assert X.gate_frame("green", OTHER + (0.9,), [OTHER], [0.9], (FAR, 0), read) == "unk"
    assert calls == []


def test_gate_frame_keeps_an_owned_green():
    read, calls = reader({})
    assert X.gate_frame("green", OWN + (0.8,), [OWN, OTHER], [0.8, 0.9], (FAR, 0), read) == "green"
    assert calls == []                                          # the chosen signal is the primary itself


def test_gate_frame_owned_green_confirmed_by_a_closer_owned_signal():
    near_line = box_at(FAR[0], 250)
    read, calls = reader({near_line: "green"})
    own_side = box_at(FAR[0] + 60, 250)
    assert X.gate_frame("green", own_side + (0.8,), [own_side, near_line], [0.8, 0.7], (FAR, 0), read) == "green"
    assert calls == [near_line]


def test_median_of_even_and_odd_lists():
    assert X._median([3, 1, 2]) == 2
    assert X._median([4, 1, 3, 2]) == 2.5
