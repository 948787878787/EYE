# Exposure control with a negative bias (pure logic; CanMV MicroPython and CPython, tests/test_exposure_v1.py).
# Architecture review A5: the reader never set the exposure, so the ISP auto exposure brightens night scenes until a
# lit LED signal clips to a white blob and the colour classifier / red veto lose it. CanMV fw 1.8 has no exposure
# compensation, so the board turns auto exposure off and this controller steers exposure time and analog gain toward
# AE_TARGET x 2^EV_BIAS (EV_BIAS -1: half the brightness the ISP would choose).
# Exposure first (capped at EXP_CAP_US: a walking user blurs longer exposures), then gain. Multiplicative steps of at
# most MAX_STEP every UPDATE_EVERY frames, no change inside DEADBAND: no oscillation, no flicker of the scene.
# UNVALIDATED: the detector was trained on auto-exposed photos; a darker scene may cost recall. Compare on the board
# (blackbox_v1 logs exp_us / gain / mean) before relying on it; ENABLED = False on the board keeps the ISP AE.
EV_BIAS = -1.0
AE_TARGET = 110                # 0-255 mean the ISP AE settles near on a street scene (assumed; logged to check)
TARGET = AE_TARGET * 2 ** EV_BIAS
DEADBAND = 0.15                # |mean / target - 1| below this: no change
MAX_STEP = 1.25                # at most x1.25 or /1.25 per update
UPDATE_EVERY = 6               # frames between updates (~0.4 s at 14 fps): the sensor applies a change late
EXP_CAP_US = 10000             # motion blur limit for a chest-worn camera while walking
MIN_MEAN = 1                   # a black frame: treat as mean 1 (no division by zero)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class ExposureControl:
    def __init__(self, exp_range, gain_range, exp_us, gain):
        """exp_range / gain_range: (min, max) from the sensor; exp_us / gain: the values AE left (the start)."""
        self.exp_min, self.exp_max = exp_range[0], min(exp_range[1], EXP_CAP_US)
        self.gain_min, self.gain_max = gain_range
        self.exp = _clamp(exp_us, self.exp_min, self.exp_max)
        self.gain = _clamp(gain, self.gain_min, self.gain_max)
        self.frames = 0

    def saturated(self):
        """Exposure and gain both at their maximum: the scene is too dark for the controller."""
        return self.exp >= self.exp_max and self.gain >= self.gain_max

    def update(self, mean):
        """Call every frame with the frame mean (0-255). Returns (exp_us, gain) when they change, else None."""
        self.frames += 1
        if self.frames % UPDATE_EVERY:
            return None
        ratio = TARGET / max(mean, MIN_MEAN)
        if abs(ratio - 1) < DEADBAND:
            return None
        ratio = _clamp(ratio, 1 / MAX_STEP, MAX_STEP)
        want = self.exp * self.gain * ratio                  # total "brightness" to reach
        exp = _clamp(want / self.gain_min, self.exp_min, self.exp_max)   # exposure first, at the lowest gain
        gain = _clamp(want / exp, self.gain_min, self.gain_max)
        if abs(exp - self.exp) < 1 and abs(gain - self.gain) < 0.01:
            return None
        self.exp, self.gain = exp, gain
        return int(exp), gain
