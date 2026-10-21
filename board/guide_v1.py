# Aiming guidance and speech policy for the pedestrian signal reader (pure logic).
# Shared by the board and Mac tests (tests/test_guide.py); no board-only imports.
# The user is asked to TURN in place, never to step sideways: at a curb a side step can
# leave the sidewalk. Guidance never announces a color; colors come only from the
# center ROI through ped_logic_v1.Voter.
try:
    from time import ticks_diff
except ImportError:            # CPython (tests)
    def ticks_diff(a, b):
        return a - b

from ped_logic_v1 import UNKNOWN, RED, GREEN, GREEN_FLASH

# speech keys (the voice layer maps them to audio or text)
SAY_RED, SAY_GREEN, SAY_GREEN_FLASH = "red", "green", "green_flash"
SAY_LOST = "unknown"           # a GREEN / GREEN_FLASH was lost: user must stop relying on it
SAY_UNCLEAR = "unclear"        # signal in view but color undecidable
SAY_LEFT, SAY_RIGHT = "turn_left", "turn_right"
SAY_SCAN = "scan"              # nothing found anywhere: turn slowly left and right
SAY_FOUND = "found"

STATE_SPEECH = {RED: SAY_RED, GREEN: SAY_GREEN, GREEN_FLASH: SAY_GREEN_FLASH}

# search windows as full-frame x fractions; same size as the center ROI so the detector
# sees signals at the scale it was trained on
WINDOWS = {"center": (0.20, 0.80), "left": (0.0, 0.60), "right": (0.40, 1.0)}
SEARCH_AFTER_MS = 1500         # no signal in the center this long -> scan side windows
SIDE_HIT_WINDOW_MS = 1500
SIDE_MIN_HITS = 2              # repeated hits on a side before guiding toward it
GUIDE_MAX_OFFSET = 0.33        # |cx - 0.5| limit, about +-30 deg: farther is likely the cross street
TURN_THRESHOLD = 0.15          # |cx - 0.5| below this is "straight ahead", no turn prompt
FACING_MIN_ASPECT = 1.2        # h / w of a signal seen from the front (two stacked lamps)
FACING_MAX_ASPECT = 3.2        # thinner means seen from the side: belongs to another crossing
UNCLEAR_AFTER_MS = 4000        # > normal RED->GREEN gap of the voter (~3.6 s)
SCAN_AFTER_MS = 4000           # searching this long with no side hit -> ask for a slow scan

PRESENCE_WINDOW_MS = 1000      # a signal counts as "in view" only if seen in most recent frames:
PRESENCE_MIN_RATIO = 0.5       # filters flickering false detections (glare) and single-frame dropouts
PRESENCE_MIN_FRAMES = 3

LOST_HOLD_MS = 1500            # StateAnnouncer: UNKNOWN must last this long before "green lost" is said
REPEAT_SAME_MS = 8000          # StateAnnouncer: the same announcement is not repeated sooner

MIN_GAP_MS = 1500              # between any two non-state prompts
COOLDOWN_MS = {SAY_LEFT: 3000, SAY_RIGHT: 3000, SAY_SCAN: 8000, SAY_UNCLEAR: 6000, SAY_FOUND: 3000}


def facing(w_px, h_px):
    return w_px > 0 and FACING_MIN_ASPECT <= h_px / w_px <= FACING_MAX_ASPECT


def guidable(cx):
    return abs(cx - 0.5) <= GUIDE_MAX_OFFSET


class Guide:
    def __init__(self):
        self.last_state = UNKNOWN
        self.center_seen_at = None     # last time the center window had a signal
        self.unknown_since = None      # UNKNOWN with a signal in the center, since
        self.search_since = None
        self.side_hits = []            # (t, cx) of guidable, front-facing side detections
        self.last_said = {}            # key -> t
        self.last_prompt_at = None
        self.guided = False            # a turn/scan prompt was given since the center lost the signal
        self.scan_toggle = False
        self.presence = []             # (t, center detection this frame)

    def windows_to_scan(self):
        """Side windows to run this frame in addition to the center (alternate left/right)."""
        if self.search_since is None:
            return []
        self.scan_toggle = not self.scan_toggle
        return ["left"] if self.scan_toggle else ["right"]

    def _can_say(self, now, key):
        cool = COOLDOWN_MS.get(key, 0)
        last = self.last_said.get(key)
        if last is not None and ticks_diff(now, last) < cool:
            return False
        return self.last_prompt_at is None or ticks_diff(now, self.last_prompt_at) >= MIN_GAP_MS

    def _say(self, now, key, out):
        self.last_said[key] = now
        self.last_prompt_at = now
        out.append(key)

    def _side_direction(self, now):
        self.side_hits = [(t, cx) for t, cx in self.side_hits if ticks_diff(now, t) <= SIDE_HIT_WINDOW_MS]
        left = [cx for _, cx in self.side_hits if cx < 0.5 - TURN_THRESHOLD]
        right = [cx for _, cx in self.side_hits if cx > 0.5 + TURN_THRESHOLD]
        if len(left) >= SIDE_MIN_HITS and len(left) >= len(right):
            return SAY_LEFT
        if len(right) >= SIDE_MIN_HITS:
            return SAY_RIGHT
        return None

    def _in_view(self, now, detected):
        self.presence.append((now, detected))
        self.presence = [(t, d) for t, d in self.presence if ticks_diff(now, t) <= PRESENCE_WINDOW_MS]
        hits = sum(1 for _, d in self.presence if d)
        return hits >= PRESENCE_MIN_FRAMES and hits >= PRESENCE_MIN_RATIO * len(self.presence)

    def update(self, now, state, center_has_signal, side_detections=()):
        """state: Voter state. center_has_signal: a readable detection in the center this frame.
        side_detections: (cx_fraction, w_px, h_px) found this frame in side windows.
        Returns the list of speech keys to play now (state changes first)."""
        out = []
        center_has_signal = self._in_view(now, center_has_signal)
        # 1. state changes are always spoken, immediately
        if state != self.last_state:
            if state in STATE_SPEECH:
                out.append(STATE_SPEECH[state])
                self.last_said[STATE_SPEECH[state]] = now
                self.guided = False            # a color announcement supersedes "found"
            elif self.last_state in (GREEN, GREEN_FLASH):
                out.append(SAY_LOST)
                self.last_said[SAY_LOST] = now
            self.last_state = state

        for cx, w_px, h_px in side_detections:
            if guidable(cx) and facing(w_px, h_px):
                self.side_hits.append((now, cx))

        # 2. center has a signal: stop searching; complain only if it stays undecidable
        if center_has_signal:
            self.center_seen_at = now
            self.search_since = None
            if self.guided:
                if out:                        # a color announcement supersedes "found"
                    self.guided = False
                elif self._can_say(now, SAY_FOUND):
                    self._say(now, SAY_FOUND, out)
                    self.guided = False
            if state == UNKNOWN:
                if self.unknown_since is None:
                    self.unknown_since = now
                if ticks_diff(now, self.unknown_since) >= UNCLEAR_AFTER_MS and self._can_say(now, SAY_UNCLEAR):
                    self._say(now, SAY_UNCLEAR, out)
            else:
                self.unknown_since = None
            return out

        # 3. no signal in the center
        self.unknown_since = None
        lost_for = None if self.center_seen_at is None else ticks_diff(now, self.center_seen_at)
        if self.search_since is None and (lost_for is None or lost_for >= SEARCH_AFTER_MS):
            self.search_since = now
        if self.search_since is None or state != UNKNOWN:
            return out
        direction = self._side_direction(now)
        if direction and self._can_say(now, direction):
            self._say(now, direction, out)
            self.guided = True
        elif direction is None and ticks_diff(now, self.search_since) >= SCAN_AFTER_MS and self._can_say(now, SAY_SCAN):
            self._say(now, SAY_SCAN, out)
            self.guided = True
        return out


class StateAnnouncer:
    """Speech for the signal-first reader (no guidance): announce color states, and a lost
    green, without chattering. Colors are spoken as soon as the voter reports them (the voter
    already debounces GREEN); a lost green only after UNKNOWN has lasted LOST_HOLD_MS, so a
    short dropout is silent; the same sentence is not repeated within REPEAT_SAME_MS."""

    def __init__(self):
        self.state = None
        self.state_since = None
        self.spoken = None             # last spoken key
        self.spoken_at = None
        self.spoken_state = None       # state that key announced

    def update(self, now, state):
        if state != self.state:
            self.state, self.state_since = state, now
        if state in STATE_SPEECH:
            key, hold = STATE_SPEECH[state], 0
        elif state == UNKNOWN and self.spoken_state in (GREEN, GREEN_FLASH):
            key, hold = SAY_LOST, LOST_HOLD_MS
        else:
            return []
        if ticks_diff(now, self.state_since) < hold:
            return []
        if key == self.spoken and ticks_diff(now, self.spoken_at) < REPEAT_SAME_MS:
            return []
        self.spoken, self.spoken_at, self.spoken_state = key, now, state
        return [key]
