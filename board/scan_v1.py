# Scan prompt for reader v6 (pure logic, shared by the board and tests/test_scan.py).
# No pedestrian signal in view for SCAN_AFTER_MS -> "未偵測到號誌，請慢慢左右轉動", at most once per
# SCAN_REPEAT_MS. After such a prompt, the first signal back in view gets "找到號誌".
# "In view" uses the guide_v1 presence filter, so glare flickers and detector dropouts neither start
# nor reset the count. A state announcement in the same frame always wins (busy=True).
# Never announces a color: colors come only from ped_logic_v1.Voter via guide_v1.StateAnnouncer.
try:
    from time import ticks_diff
except ImportError:            # CPython (tests)
    def ticks_diff(a, b):
        return a - b

from guide_v1 import PRESENCE_WINDOW_MS, PRESENCE_MIN_RATIO, PRESENCE_MIN_FRAMES

SAY_SCAN_LR = "scan_lr"
SAY_FOUND = "found"
SCAN_AFTER_MS = 5000           # user request: 5 s without a signal
SCAN_REPEAT_MS = 10000         # do not nag: at most one scan prompt per 10 s


class ScanPrompter:
    def __init__(self, start_ms):
        self.presence = []             # (t_ms, detected) within PRESENCE_WINDOW_MS
        self.missing_since = start_ms  # nothing is in view at start
        self.last_scan = None
        self.prompted = False          # a scan prompt was given since a signal was last in view

    def _in_view(self, now, detected):
        self.presence.append((now, detected))
        self.presence = [(t, d) for t, d in self.presence if ticks_diff(now, t) <= PRESENCE_WINDOW_MS]
        hits = sum(1 for _, d in self.presence if d)
        return hits >= PRESENCE_MIN_FRAMES and hits >= PRESENCE_MIN_RATIO * len(self.presence)

    def update(self, now, detected, busy):
        """detected: a pedestrian signal was found this frame. busy: a state announcement was made
        this frame. Returns the speech keys to say (0 or 1)."""
        if self._in_view(now, detected):
            self.missing_since = None
            found = self.prompted and not busy
            self.prompted = False
            return [SAY_FOUND] if found else []
        if self.missing_since is None:
            self.missing_since = now
        if busy or ticks_diff(now, self.missing_since) < SCAN_AFTER_MS:
            return []
        if self.last_scan is not None and ticks_diff(now, self.last_scan) < SCAN_REPEAT_MS:
            return []
        self.last_scan = now
        self.prompted = True
        return [SAY_SCAN_LR]
