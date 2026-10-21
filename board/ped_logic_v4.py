# Decision logic v4 = v3 + the 2026-10-05 architecture-review fixes (docs/analysis/2026-10-05_architecture_review.md).
# Pure logic: runs on CanMV MicroPython and CPython (tests/test_ped_logic_v4.py). v1 and v3 stay unchanged.
#   A2  three thresholds: the detector outputs boxes from DET_POST_CONF, the primary needs PRIMARY_CONF, a neighbour
#       blocks GREEN from GUARD_CONF. In v3 the detector cut (0.35) also hid weak red lamps from the guard
#       (board photo s021_img_0018: the red lamp above a dark green lamp scored < 0.35, GREEN 0.99 was read).
#   A4  neighbours are read without the shape gate (neighbour_label): a box on the lit red lamp alone (h/w ~1)
#       read "none" in v3 and did not block.
#   A6  GREEN from a box touching the window edge, or without one box height of window above it (where the red
#       lamp of the same head sits), is unk: the evidence against it may be outside the window.
#   A7  a guard block latches like a red vote: no GREEN for RED_LOOKBACK_MS (v3 blocked one frame only).
#   A8  GREEN_FLASHING needs a GREEN established earlier in the same cycle and FLASH_MIN_SHARE green frames.
#   MIN_READ_PX 16 (v1: 20): all gates 0 dangerous at 16 (2026-10-05_oof_cleaning_round.md).
try:
    from time import ticks_diff
except ImportError:            # CPython (tests)
    def ticks_diff(a, b):
        return a - b

from ped_logic_v1 import (UNKNOWN, RED, GREEN, GREEN_FLASH, MAX_READ_PX, MIN_ASPECT, MAX_ASPECT,  # noqa: F401
                          P_RED, P_GREEN, P_OTHER, red_veto, label_from_probs, WINDOW_MS, MIN_FRAMES, RED_RATIO,
                          GREEN_RATIO, GREEN_KEEP_RATIO, GREEN_HOLD_MS, FLASH_WINDOW_MS, FLASH_OFF_MIN_MS,
                          FLASH_OFF_MAX_MS, FLASH_ON_MIN_MS, FLASH_ON_MAX_MS, FLASH_JITTER_MS, FLASH_MIN_OFFS,
                          RED_LOOKBACK_MS, HISTORY_MS, FLASH_RESET_MS)
from ped_logic_v3 import NEAR_FACTOR, near  # noqa: F401

DET_POST_CONF = 0.20           # detector output threshold (reader: conf_thresh of the detector)
PRIMARY_CONF = 0.35            # = v1 DET_CONF: a box must reach this to be the signal that is read
GUARD_CONF = 0.25              # a neighbour this confident can block GREEN
DET_CONF = PRIMARY_CONF        # v1 name, for callers that still use it
MIN_READ_PX = 16
EDGE_PX = 2                    # window px: a box this close to an edge is cut off
TOP_ROOM = 1.0                 # GREEN needs this many box heights of window above the box
BLOCKING = ("red", "unk")
FLASH_MIN_SHARE = 0.3          # share of green frames in the window needed for GREEN_FLASHING


def readable(box_h_px):
    return box_h_px >= MIN_READ_PX


def plausible(box_w_px, box_h_px):
    if box_w_px <= 0 or not (MIN_READ_PX <= box_h_px <= MAX_READ_PX):
        return False
    return MIN_ASPECT <= box_h_px / box_w_px <= MAX_ASPECT


def primary_signal(boxes, scores, frame_width):
    """Largest box with score >= PRIMARY_CONF, ties broken by closeness to center: (x, y, w, h, score) or None."""
    best, best_key = None, None
    for (x, y, w, h), s in zip(boxes, scores):
        if s < PRIMARY_CONF:
            continue
        key = (w * h, -abs(x + w / 2 - frame_width / 2))
        if best_key is None or key > best_key:
            best, best_key = (x, y, w, h, s), key
    return best


def neighbour_label(probs, vetoed):
    """Label of a NEIGHBOUR box for the guard, without the shape gate. probs None = too small to read (blocks)."""
    if probs is None:
        return "unk"
    if vetoed or probs["red"] >= P_RED:
        return "red"
    if probs["other"] >= P_OTHER:
        return "none"
    if probs["green"] >= P_GREEN:
        return "green"
    return "unk"


def guard_green(label, sig, boxes, scores, read_fn):
    """v3 guard with GUARD_CONF. read_fn((x, y, w, h, score)) must read like neighbour_label."""
    if label != "green":
        return label
    for box, score in zip(boxes, scores):
        if score < GUARD_CONF or tuple(box[:4]) == tuple(sig[:4]) or not near(sig, box):
            continue
        if read_fn(tuple(box[:4]) + (score,)) in BLOCKING:
            return "unk"
    return label


def edge_guard(label, sig, win_w, win_h):
    """GREEN only from a box clear of the window edges with room for the red lamp above it."""
    if label != "green":
        return label
    x, y, w, h = sig[:4]
    if x <= EDGE_PX or y <= EDGE_PX or x + w >= win_w - EDGE_PX or y + h >= win_h - EDGE_PX:
        return "unk"
    if y < TOP_ROOM * h:
        return "unk"
    return label


def apply_guards(label, sig, boxes, scores, read_fn, win_w, win_h):
    """(label, blocked): blocked = a GREEN was turned into unk by a guard (feed it to Voter.update)."""
    guarded = edge_guard(guard_green(label, sig, boxes, scores, read_fn), sig, win_w, win_h)
    return guarded, label == "green" and guarded != "green"


class Voter:
    def __init__(self):
        self.frames = []           # (t_ms, label), label in red / green / none / unk
        self.green_since = None
        self.state = UNKNOWN
        self.flashed = False
        self.last_green_t = None
        self.block_t = None        # A7: last guard block
        self.green_reached = False  # A8: GREEN announced in this cycle

    def _flash_offs(self, now):
        ons, offs_ms = [], []
        run_start = gap_start = None
        for t, label in self.frames:
            if ticks_diff(now, t) > FLASH_WINDOW_MS:
                continue
            if label == "green":
                if gap_start is not None:
                    on_ms = ticks_diff(gap_start, run_start)
                    off_ms = ticks_diff(t, gap_start)
                    if FLASH_ON_MIN_MS <= on_ms <= FLASH_ON_MAX_MS and FLASH_OFF_MIN_MS <= off_ms <= FLASH_OFF_MAX_MS:
                        ons.append(on_ms)
                        offs_ms.append(off_ms)
                    run_start = t
                elif run_start is None:
                    run_start = t
                gap_start = None
            elif run_start is not None and gap_start is None:
                gap_start = t
        if ons and (max(ons) - min(ons) > FLASH_JITTER_MS or max(offs_ms) - min(offs_ms) > FLASH_JITTER_MS):
            return 0
        return len(ons)

    def update(self, now, label, blocked=False):
        if blocked:
            self.block_t = now
        self.frames.append((now, label))
        if label == "red":
            self.green_reached = False     # any red vote ends the cycle's established GREEN
        if label == "green":
            self.last_green_t = now
        elif self.last_green_t is not None and ticks_diff(now, self.last_green_t) > FLASH_RESET_MS:
            self.flashed = False   # signal gone for long: likely a new crossing
            self.green_reached = False
        while self.frames and ticks_diff(now, self.frames[0][0]) > HISTORY_MS:
            self.frames.pop(0)
        recent = [l for t, l in self.frames if ticks_diff(now, t) <= WINDOW_MS]
        n = len(recent)
        reds = recent.count("red")
        greens = recent.count("green")
        red_recently = any(l == "red" and ticks_diff(now, t) <= RED_LOOKBACK_MS for t, l in self.frames)
        if self.block_t is not None and ticks_diff(now, self.block_t) <= RED_LOOKBACK_MS:
            red_recently = True

        candidate = UNKNOWN
        if n >= MIN_FRAMES:
            if reds >= RED_RATIO * n and greens == 0:
                candidate = RED
            elif (not red_recently and self.green_reached and greens >= FLASH_MIN_SHARE * n
                  and self._flash_offs(now) >= FLASH_MIN_OFFS):
                candidate = GREEN_FLASH
            elif not red_recently and greens >= (GREEN_KEEP_RATIO if self.state == GREEN else GREEN_RATIO) * n:
                candidate = GREEN

        if candidate == RED:
            self.flashed = False
            self.green_reached = False
        elif candidate == GREEN and self.flashed:
            candidate = GREEN_FLASH
        if candidate == GREEN_FLASH:
            self.flashed = True

        if candidate == GREEN:
            if self.green_since is None:
                self.green_since = now
            if self.state != GREEN and ticks_diff(now, self.green_since) < GREEN_HOLD_MS:
                candidate = UNKNOWN
        else:
            self.green_since = None
        if candidate == GREEN:
            self.green_reached = True
        self.state = candidate
        return self.state
