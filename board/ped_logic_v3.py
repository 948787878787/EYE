# Decision logic v3 = ped_logic_v1 + a neighbour guard for GREEN (pure logic: board and tests/test_ped_logic_v3.py).
# Found on the leak-free test (2026-09-26, -2025-11-16-214839): two pedestrian signals side by side on one pole
# serve two crossings. primary_signal() takes the largest box, which was the green signal of the OTHER crossing
# at the window edge (240 vs 231 px^2), so GREEN was reported while the signal facing the user was red.
# Rule: a GREEN frame becomes "unk" when another confident box within NEAR_FACTOR long sides of the primary reads
# red or unclear. Measured (docs/analysis/2026-09-26_optimization_review.md): dangerous frames 1 -> 0, green frames
# 77 -> 76 of 100 (valid+test); board photos unchanged (the guard never fired).
# Everything else (thresholds, veto, Voter, primary_signal) is ped_logic_v1, unchanged.
from ped_logic_v1 import *  # noqa: F401,F403  same public names as v1
from ped_logic_v1 import DET_CONF

NEAR_FACTOR = 3.0              # neighbour = center within 3 long sides of the primary box, on both axes
BLOCKING = ("red", "unk")      # neighbour labels that forbid GREEN ("none" = not a pedestrian signal)


def near(sig, box):
    """True when box (x, y, w, h) lies within NEAR_FACTOR long sides of sig (x, y, w, h[, score])."""
    x, y, w, h = sig[:4]
    reach = NEAR_FACTOR * max(w, h)
    bx, by, bw, bh = box[:4]
    return abs(bx + bw / 2 - x - w / 2) <= reach and abs(by + bh / 2 - y - h / 2) <= reach


def guard_green(label, sig, boxes, scores, read_fn):
    """label of the primary signal after the neighbour guard. read_fn((x, y, w, h, score)) -> red / green / unk /
    none reads one other box exactly like the primary; it runs only for confident near boxes of a GREEN frame."""
    if label != "green":
        return label
    for box, score in zip(boxes, scores):
        if score < DET_CONF or tuple(box[:4]) == tuple(sig[:4]) or not near(sig, box):
            continue
        if read_fn(tuple(box[:4]) + (score,)) in BLOCKING:
            return "unk"
    return label
