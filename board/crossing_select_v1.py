# Signal selection v1 (pure logic: board and tests/test_crossing_select_v1.py; no board-only imports).
# User 2026-10-20: at a two-stage crossing (median island) the two pedestrian signals stand in one line and switch at
# different times; the NEARER one (larger in pixels) governs the segment in front of the user. The zebra-crossing
# model (crosswalk_v1.CrosswalkTracker.owned_far) says which signals belong to the user's crossing at all.
# Measured before this version (docs/plans/2026-10-20_crossing_select_v1.md): on the 43 labelled multi-signal frames
# the largest box is the faced signal only 30/43 times, and 13 of the 18 tallest-box misses are near ties (< 1.15x),
# so size decides only (a) among signals on the user's crossing and (b) when the size difference is clear.
# Safety: like crosswalk_v1.gate_label, this runs after the reader and can only turn GREEN into "unk"; red / unk /
# none pass through unchanged. ISLAND_WAIT is a spoken note on a kept GREEN, never a permission.
import math

from crosswalk_v1 import on_crossing

PRIMARY_CONF = 0.35            # same as ped_logic_v4/v5: boxes below it are not signals the user could be facing
GUARD_CONF = 0.25              # same as ped_logic_v4/v5: a box this confident can still BLOCK a green (never give one)
SIZE_MARGIN = 1.4              # nearer signal must be this much larger (linear size) to be told apart by size

NOT_ON_CROSSING = "not-on-crossing"        # the reader's signal is not on the user's crossing
NEARER_NOT_GREEN = "nearer-not-green"      # a larger signal on the crossing reads something other than green
SIZE_TIE = "size-tie"                      # two signals of about the same size disagree
ISLAND_WAIT = "island-wait"                # green for this segment, the farther in-line signal is red


def linear_size(box):
    """sqrt(area) of (x, y, w, h): proportional to 1 / distance for heads of one size; a side-on head is smaller."""
    w, h = box[2], box[3]
    return math.sqrt(w * h) if w > 0 and h > 0 else 0.0


def _same(a, b):
    return tuple(a[:4]) == tuple(b[:4])


def gate(label, sig, boxes, scores, owned, read_fn):
    """Final (label, note) for the reader's primary signal sig (x, y, w, h[, score]) with reader label `label`.
    boxes / scores: all detections of the frame (same pixel frame as owned). owned: CrosswalkTracker.owned_far() ->
    (far, tol_px) or None (no usable crossing: only the size tie is checked). read_fn(box) reads another box exactly
    like the primary; it runs only on GREEN frames, at most twice."""
    if label != "green" or sig is None:
        return label, ""
    # blockers include weaker boxes: a near red at 0.30 must still stop a far green (IMG_4644, 2026-10-20)
    cands = [tuple(b[:4]) for b, s in zip(boxes, scores) if s >= GUARD_CONF]
    if not any(_same(c, sig) for c in cands):
        cands.append(tuple(sig[:4]))
    if owned is not None:
        far, tol = owned
        line = [c for c in cands if on_crossing(c, far, tol)]
        if not line:
            return "unk", NOT_ON_CROSSING
        if not on_crossing(sig, far, tol):
            nearest = max(line, key=linear_size)
            return ("green" if read_fn(nearest) == "green" else "unk"), NOT_ON_CROSSING
        cands = line
    order = sorted(cands, key=linear_size, reverse=True)
    nearest = order[0]
    if not _same(nearest, sig):
        if linear_size(nearest) >= SIZE_MARGIN * linear_size(sig) and read_fn(nearest) != "green":
            return "unk", NEARER_NOT_GREEN
        nearest = tuple(sig[:4])
        order = [nearest] + [c for c in order if not _same(c, sig)]
    if len(order) < 2:
        return "green", ""
    second = order[1]
    if linear_size(nearest) < SIZE_MARGIN * linear_size(second):
        return ("green", "") if read_fn(second) == "green" else ("unk", SIZE_TIE)
    if owned is not None and read_fn(second) == "red":
        return "green", ISLAND_WAIT
    return "green", ""
