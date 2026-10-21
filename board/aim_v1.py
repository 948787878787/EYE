# Aiming guidance for the chest-worn reader (pure logic; CanMV MicroPython and CPython, tests/test_aim_v1.py).
# User 2026-10-14 (blind-user review item 7): "I cannot tell whether the camera points at the signal".
# Spoken only - no aiming beeps: a tone could be mistaken for guide_v2's GREEN heartbeat "tick" (safety).
# Active only while no colour is GREEN / GREEN_FLASH and no fault: no turning instructions on the crossing.
# The user is asked to TURN in place (never to step sideways: at a curb a side step can leave the sidewalk, guide_v1).
#   turn_left / turn_right   a front-facing signal stays left / right of centre for PRESENCE_MS
#   aligned                  it came to the centre after a turn prompt (said once)
try:
    from time import ticks_diff
except ImportError:            # CPython (tests)
    def ticks_diff(a, b):
        return a - b

from ped_logic_v1 import GREEN, GREEN_FLASH

SAY_LEFT, SAY_RIGHT, SAY_ALIGNED = "turn_left", "turn_right", "aligned"
CENTER = 0.10                  # |cx - 0.5| (frame fraction) at most this: centred
OFF = 0.16                     # at least this: off to one side (hysteresis band between)
FACING_MIN_ASPECT, FACING_MAX_ASPECT = 1.2, 3.2   # h / w of a signal seen from the front (guide_v1)
PRESENCE_MS = 800              # a zone counts once its hits fill most of this window
PRESENCE_MIN_HITS = 3
PRESENCE_MIN_RATIO = 0.6
COOLDOWN_MS = 3000             # the same prompt not sooner
MIN_GAP_MS = 1500              # between any two aiming prompts


def zone(cx, previous):
    off = cx - 0.5
    if abs(off) <= CENTER:
        return "center"
    if abs(off) >= OFF:
        return "left" if off < 0 else "right"
    return previous if previous in ("left", "right") else "center"


class AimGuide:
    def __init__(self):
        self.frames = []           # (t, zone or None)
        self.zone = None
        self.turned = False        # a turn prompt was given and the signal is not centred yet
        self.last_said = {}
        self.last_any = None

    def _ok_to_say(self, now, key):
        last = self.last_said.get(key)
        if last is not None and ticks_diff(now, last) < COOLDOWN_MS:
            return False
        return self.last_any is None or ticks_diff(now, self.last_any) >= MIN_GAP_MS

    def _say(self, now, key, out):
        self.last_said[key], self.last_any = now, now
        out.append(key)

    def _settled(self, now):
        """The zone most recent frames agree on, or None."""
        self.frames = [(t, z) for t, z in self.frames if ticks_diff(now, t) <= PRESENCE_MS]
        n = len(self.frames)
        for z in ("left", "right", "center"):
            hits = sum(1 for _, fz in self.frames if fz == z)
            if hits >= PRESENCE_MIN_HITS and hits >= PRESENCE_MIN_RATIO * n:
                return z
        return None

    def update(self, now, state, fault, signal):
        """signal: (cx as a fraction of the full frame width, w, h) of the primary detection, or None.
        Returns the aiming keys to play now (none while green or during a fault)."""
        if state in (GREEN, GREEN_FLASH) or fault is not None:
            self.frames, self.zone, self.turned = [], None, False
            return []
        z = None
        if signal is not None:
            cx, w, h = signal
            if w > 0 and FACING_MIN_ASPECT <= h / w <= FACING_MAX_ASPECT:
                z = zone(cx, self.zone)
        self.frames.append((now, z))
        settled = self._settled(now)
        out = []
        if settled is None:
            return out
        self.zone = settled
        if settled in ("left", "right"):
            key = SAY_LEFT if settled == "left" else SAY_RIGHT
            if self._ok_to_say(now, key):
                self._say(now, key, out)
                self.turned = True
        elif self.turned and self._ok_to_say(now, SAY_ALIGNED):
            self._say(now, SAY_ALIGNED, out)
            self.turned = False
        return out
