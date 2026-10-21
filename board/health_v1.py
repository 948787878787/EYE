# Health checks for the pedestrian signal reader (pure logic; CanMV MicroPython and CPython, tests/test_health_v1.py).
# Architecture review A9 / user 2026-10-14 ("tell me when it is broken"): conditions under which the reader cannot see a
# signal even though it is running. Each returns a fault key that guide_v2.SafeAnnouncer speaks instead of a colour.
#   camera_dark     mean brightness of a sparse frame sample below DARK_MEAN for HOLD_MS (night without light, lens cap)
#   camera_blocked  almost no contrast (spread below FLAT_SPREAD) for HOLD_MS (lens covered by a hand, coat or fog)
#   slow            the loop runs slower than the Voter needs: its MIN_FRAMES votes in WINDOW_MS (ped_logic_v1) need at
#                   least ~3.3 frames/s; mean frame period above SLOW_PERIOD_MS over SLOW_WINDOW frames
# A fault clears only after RECOVER_MS of good frames, so a flickering condition does not toggle the speech.
# The frame statistics come from frame_stats() on a strided sample of one channel (cheap on the board).
try:
    from time import ticks_diff
except ImportError:            # CPython (tests)
    def ticks_diff(a, b):
        return a - b

CAMERA_DARK, CAMERA_BLOCKED, SLOW = "camera_dark", "camera_blocked", "slow"
FAULT_ORDER = (CAMERA_BLOCKED, CAMERA_DARK, SLOW)    # most specific first when several hold

DARK_MEAN = 20                 # 0-255: a night street with signals is far brighter than this
FLAT_SPREAD = 10               # p90 - p10 of the sample: a covered lens is nearly uniform
HOLD_MS = 1500                 # a condition must last this long to become a fault
RECOVER_MS = 1000              # good frames needed before a fault clears
SLOW_PERIOD_MS = 300           # mean frame period above this: < 3.3 fps, the Voter cannot reach MIN_FRAMES
SLOW_WINDOW = 10
SAMPLE_STEP = 16               # frame_stats: every 16th pixel in x and y


def frame_stats(values):
    """(mean, spread) of a flat sequence of 0-255 ints; spread = 90th - 10th percentile."""
    vals = sorted(int(v) for v in values)
    n = len(vals)
    if n == 0:
        return 0, 0
    mean = sum(vals) // n
    return mean, vals[(9 * n) // 10 if n > 1 else 0] - vals[n // 10]


class _Hold:
    """A condition that turns on after HOLD_MS of True and off after RECOVER_MS of False."""

    def __init__(self):
        self.on = False
        self.since = None

    def update(self, now, cond):
        if cond == self.on:
            self.since = None
            return self.on
        if self.since is None:
            self.since = now
        if ticks_diff(now, self.since) >= (HOLD_MS if cond else RECOVER_MS):
            self.on, self.since = cond, None
        return self.on


class Health:
    def __init__(self):
        self.holds = {CAMERA_DARK: _Hold(), CAMERA_BLOCKED: _Hold(), SLOW: _Hold()}
        self.periods = []
        self.last_frame = None

    def update(self, now, mean, spread):
        """Call once per frame with frame_stats() of this frame. Returns a fault key or None."""
        if self.last_frame is not None:
            self.periods.append(ticks_diff(now, self.last_frame))
            if len(self.periods) > SLOW_WINDOW:
                self.periods.pop(0)
        self.last_frame = now
        slow = len(self.periods) >= SLOW_WINDOW and sum(self.periods) > SLOW_PERIOD_MS * len(self.periods)
        on = {CAMERA_DARK: self.holds[CAMERA_DARK].update(now, mean < DARK_MEAN),
              CAMERA_BLOCKED: self.holds[CAMERA_BLOCKED].update(now, spread < FLAT_SPREAD and mean >= DARK_MEAN),
              SLOW: self.holds[SLOW].update(now, slow)}
        for key in FAULT_ORDER:
            if on[key]:
                return key
        return None
