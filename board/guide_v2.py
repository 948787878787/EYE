# Speech policy v2 for the pedestrian signal reader (pure logic; CanMV MicroPython and CPython, tests/test_guide_v2.py).
# guide_v1 stays unchanged. v2 = guide_v1.StateAnnouncer + the fail-safe rules of architecture review A9
# (user, 2026-10-14: "silence must mean do not go"; "tell me when it is broken"):
#   H1  heartbeat: while GREEN is announced, a short "tick" every HEARTBEAT_MS; while GREEN_FLASH, "tick_fast" every
#       HEARTBEAT_FAST_MS. Any other state, a fault, or a dead loop -> no ticks: silence = do not start crossing.
#   H2  a lost GREEN / GREEN_FLASH is spoken at once ("unknown" = "號誌無法確認，請勿開始穿越"; v1 waited 1.5 s;
#       the Voter already debounces short dropouts). Never "stop": the user may already be on the crossing.
#   H3  a fault (camera dark / blocked, loop too slow; health_v1) overrides the Voter: no colour is announced, a
#       GREEN in progress is withdrawn at once, and the fault is repeated every FAULT_REPEAT_MS while it lasts.
try:
    from time import ticks_diff, ticks_add
except ImportError:            # CPython (tests)
    def ticks_diff(a, b):
        return a - b

    def ticks_add(a, b):
        return a + b

from ped_logic_v1 import UNKNOWN, RED, GREEN, GREEN_FLASH

SAY_RED, SAY_GREEN, SAY_GREEN_FLASH, SAY_LOST = "red", "green", "green_flash", "unknown"
SAY_TICK, SAY_TICK_FAST = "tick", "tick_fast"
STATE_SPEECH = {RED: SAY_RED, GREEN: SAY_GREEN, GREEN_FLASH: SAY_GREEN_FLASH}
GREENISH = (GREEN, GREEN_FLASH)

HEARTBEAT_MS = 1000            # GREEN: one tick per second
HEARTBEAT_FAST_MS = 500        # GREEN_FLASH: faster, so the two are told apart by ear
FIRST_TICK_MS = 1500           # first tick after the colour sentence (it plays ~1.5 s)
REPEAT_SAME_MS = 8000          # the same colour sentence is not repeated sooner (as v1)
FAULT_REPEAT_MS = 6000         # a lasting fault is repeated this often


class SafeAnnouncer:
    def __init__(self):
        self.spoken_state = None       # state whose sentence was spoken last (None: nothing / fault)
        self.spoken_at = None
        self.tick_at = None            # when the next heartbeat is due
        self.fault = None
        self.fault_at = None

    def _say_state(self, now, state, out):
        out.append(STATE_SPEECH[state])
        self.spoken_state, self.spoken_at = state, now
        self.tick_at = ticks_add(now, FIRST_TICK_MS) if state in GREENISH else None

    def update(self, now, state, fault=None):
        """state: Voter state; fault: a health_v1 fault key or None. Returns the keys to play now."""
        out = []
        if fault is not None:
            if fault != self.fault or ticks_diff(now, self.fault_at) >= FAULT_REPEAT_MS:
                if self.spoken_state in GREENISH and fault != self.fault:
                    out.append(SAY_LOST)           # withdraw a green first
                out.append(fault)
                self.fault, self.fault_at = fault, now
            self.spoken_state, self.tick_at = None, None
            return out
        self.fault = None
        if state in STATE_SPEECH:
            changed = state != self.spoken_state
            if changed or ticks_diff(now, self.spoken_at) >= REPEAT_SAME_MS:
                self._say_state(now, state, out)   # RED after GREEN: "red" itself withdraws the green
                return out
            if state in GREENISH and self.tick_at is not None and ticks_diff(now, self.tick_at) >= 0:
                out.append(SAY_TICK if state == GREEN else SAY_TICK_FAST)
                self.tick_at = ticks_add(now, HEARTBEAT_MS if state == GREEN else HEARTBEAT_FAST_MS)
            return out
        if self.spoken_state in GREENISH:           # UNKNOWN after a green: withdraw it now
            out.append(SAY_LOST)
            self.spoken_state, self.spoken_at, self.tick_at = UNKNOWN, now, None
        return out
