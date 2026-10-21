# Pure decision logic for the pedestrian signal reader, shared by the board and Mac tests.
# No board-only imports: runs on CanMV MicroPython and on CPython (tests/test_ped_logic.py).
# Safety: GREEN needs stronger and longer agreement than RED, leaving GREEN is immediate,
# anything unclear is UNKNOWN. Never defaults to GREEN.
try:
    from time import ticks_diff
except ImportError:            # CPython (tests)
    def ticks_diff(a, b):
        return a - b

UNKNOWN, RED, GREEN, GREEN_FLASH = "UNKNOWN", "RED", "GREEN", "GREEN_FLASHING"

# frame classification
DET_CONF = 0.35
MIN_READ_PX = 20               # box height in sensor px below which color is not read (~35-40 m away):
                               # the only wrong-color frame in val+test (246 frames) was 18-24 px
MAX_READ_PX = 450              # taller = signal within ~2 m or a whole-screen false box: not read
MIN_ASPECT = 1.2               # detector boxes on real signals have h/w 1.6-1.9 (val/test)
MAX_ASPECT = 3.2
P_RED = 0.6
P_GREEN = 0.8                  # green needs more confidence than red
P_OTHER = 0.6                  # classifier says "not a pedestrian signal" (vehicle light, screen, lamp):
                               # the detection is dropped, stage 2 vetoes stage 1

# red-evidence veto, identical to tools/color_gate.py
LIT_ABS_MIN = 60
LIT_REL_MAX = 0.4
SAT_MIN = 0.3
RED_OVER_G = 1.8
RED_OVER_B = 1.0
GREEN_OVER_R = 1.1
GB_OVER_R = 2.0
MIN_RED_FRACTION = 0.003
MIN_RED_PX = 3
RED_OVER_GREEN = 4.0
VETO_MAX_PIXELS = 900          # subsample big boxes to bound the pure-Python loop

# time-based voting
WINDOW_MS = 1500
MIN_FRAMES = 5
RED_RATIO = 0.5
GREEN_RATIO = 0.7              # share of green frames needed to ENTER green
GREEN_KEEP_RATIO = 0.4         # hysteresis: share needed to STAY green (shaky hand-held dropouts);
                               # any red vote still leaves green at once
GREEN_HOLD_MS = 600            # GREEN must hold this long before it is announced
FLASH_WINDOW_MS = 3000
FLASH_OFF_MIN_MS = 250         # shorter gaps are detection dropouts, not flashing
FLASH_OFF_MAX_MS = 1200
FLASH_ON_MIN_MS = 250          # a flash cycle also needs a short, regular ON phase: a long steady
FLASH_ON_MAX_MS = 1200         # green with a dropout (shaking camera) is not flashing
FLASH_JITTER_MS = 300          # a real flash is hardware-timed: all ON (and all OFF) phases within this
FLASH_MIN_OFFS = 2
RED_LOOKBACK_MS = 3000         # GREEN and GREEN_FLASH both require no red vote this long
HISTORY_MS = max(FLASH_WINDOW_MS, RED_LOOKBACK_MS)
FLASH_RESET_MS = 10000         # after GREEN_FLASHING, GREEN is blocked until RED or this long without green


def red_veto(pixel_at, x, y, w, h):
    """pixel_at(xx, yy) -> (r, g, b). True when the box clearly glows red (GREEN must not be announced)."""
    step = 1
    while (w // step) * (h // step) > VETO_MAX_PIXELS:
        step += 1
    px = []
    brightest = 0
    for yy in range(y, y + h, step):
        for xx in range(x, x + w, step):
            r, g, b = pixel_at(xx, yy)
            mx = max(r, g, b)
            px.append((r, g, b, mx, min(r, g, b)))
            if mx > brightest:
                brightest = mx
    lit_min = max(LIT_ABS_MIN, LIT_REL_MAX * brightest)
    red_px = green_px = 0
    for r, g, b, mx, mn in px:
        if mx < lit_min or (mx - mn) < SAT_MIN * mx:
            continue
        if r >= RED_OVER_G * g and r >= RED_OVER_B * b:
            red_px += 1
        elif g >= GREEN_OVER_R * r and g + b >= GB_OVER_R * r:
            green_px += 1
    return red_px >= max(MIN_RED_PX, MIN_RED_FRACTION * len(px)) and red_px >= RED_OVER_GREEN * green_px


def primary_signal(boxes, scores, frame_width):
    """The signal the user faces: largest confident box, ties broken by closeness to center.
    boxes: list of (x, y, w, h); returns (x, y, w, h, score) or None."""
    best, best_key = None, None
    for (x, y, w, h), s in zip(boxes, scores):
        if s < DET_CONF:
            continue
        key = (w * h, -abs(x + w / 2 - frame_width / 2))
        if best_key is None or key > best_key:
            best, best_key = (x, y, w, h, s), key
    return best


def readable(box_h_px):
    """True when a detected signal is tall enough (sensor px) for a reliable color reading."""
    return box_h_px >= MIN_READ_PX


def plausible(box_w_px, box_h_px):
    """Readable AND shaped/sized like a pedestrian signal seen from the street (sensor px).
    Detector boxes on real signals have h/w 1.6-1.9; a whole-screen box or a thin side view is not one."""
    if box_w_px <= 0 or not (MIN_READ_PX <= box_h_px <= MAX_READ_PX):
        return False
    return MIN_ASPECT <= box_h_px / box_w_px <= MAX_ASPECT


def label_from_probs(probs, vetoed):
    """probs: dict with 'red', 'green', 'other'. vetoed: red_veto() result for this box.
    Returns red / green / unk (a signal, color undecided) / none (not a pedestrian signal)."""
    if probs["other"] >= P_OTHER:
        return "none"
    if probs["red"] >= P_RED:
        return "red"
    if probs["green"] >= P_GREEN and not vetoed:
        return "green"
    return "unk"


class Voter:
    def __init__(self):
        self.frames = []           # (t_ms, label), label in red / green / none / unk
        self.green_since = None
        self.state = UNKNOWN
        self.flashed = False       # GREEN_FLASHING seen in this cycle: the walk phase is ending
        self.last_green_t = None

    def _flash_offs(self, now):
        """Count on/off cycles where both the green ON run and the OFF gap have flash-like length,
        but only if the cycles are regular (a flashing signal is hardware-timed, jitter is not)."""
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

    def update(self, now, label):
        self.frames.append((now, label))
        if label == "green":
            self.last_green_t = now
        elif self.flashed and self.last_green_t is not None and ticks_diff(now, self.last_green_t) > FLASH_RESET_MS:
            self.flashed = False       # signal gone for long: likely a new crossing
        while self.frames and ticks_diff(now, self.frames[0][0]) > HISTORY_MS:
            self.frames.pop(0)
        recent = [l for t, l in self.frames if ticks_diff(now, t) <= WINDOW_MS]
        n = len(recent)
        reds = recent.count("red")
        greens = recent.count("green")
        red_recently = any(l == "red" and ticks_diff(now, t) <= RED_LOOKBACK_MS for t, l in self.frames)

        candidate = UNKNOWN
        if n >= MIN_FRAMES:
            if reds >= RED_RATIO * n and greens == 0:
                candidate = RED
            elif not red_recently and greens > 0 and self._flash_offs(now) >= FLASH_MIN_OFFS:
                candidate = GREEN_FLASH
            elif not red_recently and greens >= (GREEN_KEEP_RATIO if self.state == GREEN else GREEN_RATIO) * n:
                candidate = GREEN

        if candidate == RED:
            self.flashed = False       # a new cycle starts
        elif candidate == GREEN and self.flashed:
            candidate = GREEN_FLASH    # never "go" at the end of a walk phase
        if candidate == GREEN_FLASH:
            self.flashed = True

        if candidate == GREEN:
            if self.green_since is None:
                self.green_since = now
            if self.state != GREEN and ticks_diff(now, self.green_since) < GREEN_HOLD_MS:
                candidate = UNKNOWN    # entering GREEN is debounced; leaving it is immediate
        else:
            self.green_since = None
        self.state = candidate
        return self.state
