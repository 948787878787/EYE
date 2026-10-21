# Crosswalk shadow mode v1 (pure logic: board and tests/test_crosswalk_shadow_v1.py; no board-only imports).
# Plan docs/plans/2026-10-20_crossing_select_v1.md, amendments 7-8: gate L-B failed (green recall -5.45 points, limit 5),
# so the crosswalk model may run on the board only in SHADOW mode: the midline and what crossing_select_v1.gate WOULD
# have decided are recorded (blackbox_v2), but the reader's label, state and speech never change.
# Model output: YOLO26-pose end-to-end (1, N, 12) = x0 y0 x1 y1 score class, near x y v, far x y v in model-input px;
# the chn2 frame is letterboxed into the input CENTERED like ultralytics (2026-10-21: ONNX on ImVisible valid, usable
# 96.1% centered vs 94.9% top-left), so frame px = (input px - pad) / ratio.
# Ownership uses detector-window px (the reader's boxes): window px = frame px - window origin.
from crossing_select_v1 import gate

ROW = 12                       # 6 box values + 2 keypoints x (x, y, visibility)
CW_CONF = 0.25                 # same threshold as gate L-B (amendment 6) and the kmodel check (amendment 8)


def centered_pad(src_size, dst_size):
    """Centered letterbox (as ultralytics trains / predicts): (top, bottom, left, right, ratio)."""
    ratio = min(dst_size[0] / src_size[0], dst_size[1] / src_size[1])
    pad_w = dst_size[0] - int(ratio * src_size[0])
    pad_h = dst_size[1] - int(ratio * src_size[1])
    return pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, ratio


def midline_from_row(row, ratio, origin, pad=(0, 0)):
    """One output row -> (score, near, far) in window px. origin: (x0, y0) of the detector window in the frame;
    pad: (left, top) of the letterbox in input px."""
    ox, oy = origin
    px, py = pad
    near = ((row[6] - px) / ratio - ox, (row[7] - py) / ratio - oy)
    far = ((row[9] - px) / ratio - ox, (row[10] - py) / ratio - oy)
    return float(row[4]), near, far


def top_row_index(scores):
    """Index of the highest score (first on ties), or None for no rows. scores: any sequence."""
    best, idx = None, None
    for i, s in enumerate(scores):
        if best is None or s > best:
            best, idx = s, i
    return idx


def tracker_input(found, min_conf=CW_CONF):
    """CrosswalkTracker.update midline from one model run: (near, far), or None below min_conf / nothing found."""
    if found is None or found[0] < min_conf:
        return None
    return found[1], found[2]


def shadow(label, sig, boxes, scores, owned, read_fn):
    """What crossing_select_v1.gate would report: (label, note). Never fed back into the reader (shadow mode)."""
    if sig is None:
        return label, ""
    return gate(label, sig, boxes, scores, owned, read_fn)
