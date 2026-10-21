# Crosswalk direction logic v1 (pure logic: board and tests/test_crosswalk.py; no board-only imports).
# Input: the zebra-crossing midline (near end, far end) from a crosswalk model that runs every few frames
# (docs/analysis/2026-09-26_crosswalk_direction_design.md), and the signal boxes of the current frame. Midline and
# boxes must be in ONE pixel frame (e.g. the 1280x720 chn2 frame: shift detector-window boxes by the window origin);
# focal / center_x describe that frame (focal_px(width, measured horizontal field of view)).
# Two uses, as in LytNet / ImVisible and the PTL-Crosswalk project:
#   1. Alignment hint: turn in place slightly left / right until the user faces the far end of the crossing.
#      Turn prompts only, never "step sideways" (same rule as guide_v1: at a curb a side step can leave the sidewalk).
#   2. Signal ownership: the signal serving the user's crossing stands above the FAR end of the midline. Two signals
#      of two crossings on one pole (2026-09-26, -2025-11-16-214839) stand at the same place, so position cannot split
#      them: ped_logic_v3.guard_green stays in charge of that case. Ownership rejects signals of crossings farther away.
# Safety: nothing here makes GREEN more likely. gate_label() keeps red / unk / none unchanged and can only turn a
# GREEN into "unk" (caution). Without a fresh, stable, roughly straight-ahead midline everything passes through
# unchanged, i.e. the reader behaves exactly like ped_logic_v3.
import math

from ped_logic_v1 import DET_CONF

DEG = 180.0 / math.pi

# speech keys (wording belongs to tools/voice_prompts.py when a reader uses them)
SAY_CW_LEFT, SAY_CW_RIGHT = "cw_turn_left", "cw_turn_right"   # crossing lies slightly left / right: turn in place
ALIGNED = "cw_aligned"         # facing the far end of the crossing (a state, never a permission to walk)

# midline sanity
MIN_LEN_FRAC = 0.10            # midline shorter than this share of the window width: not a usable crossing
MAX_IMAGE_ANGLE_DEG = 70.0     # midline flatter than this (from vertical) runs across the view: another crossing
                               # (ImVisible labels: 99% within +-73 deg, median |angle| 40 deg)

# alignment (LytNet's app used +-10 deg; hysteresis avoids flip-flopping around the threshold)
ALIGN_ENTER_DEG = 8.0          # |heading| at or below this -> aligned
ALIGN_LEAVE_DEG = 12.0         # once aligned, stay aligned until |heading| exceeds this
GUIDE_MAX_DEG = 35.0           # farther off: probably not the user's crossing -> no hint and no ownership

# ownership
SIGNAL_W_M = 0.30              # approximate width of a Taiwan pedestrian signal head (detector box), metres
MAX_LATERAL_M = 6.0            # half crossing width (1.5-4 m) + pole setback (0.5-2 m)

# tracker (crosswalk model runs every N frames; the crossing moves slowly in the image)
WINDOW_MS = 3000
MIN_OBS = 3                    # valid midlines needed in the window
MIN_FOUND_RATIO = 0.6          # share of model runs in the window that found a valid midline
MAX_SPREAD_DEG = 10.0          # heading spread in the window: larger = user turning or unstable detections
STALE_MS = 1500                # newest valid midline older than this -> no crossing
FAR_TOL_FRAC = 0.03            # base far-end x tolerance (share of window width), plus the observed jitter

try:
    from time import ticks_diff
except ImportError:            # CPython (tests)
    def ticks_diff(a, b):
        return a - b


def focal_px(width_px, hfov_deg):
    """Pinhole focal length in px for an image width_px wide with horizontal field of view hfov_deg."""
    return (width_px / 2.0) / math.tan(hfov_deg / 2.0 / DEG)


def bearing_deg(x_px, center_x, focal):
    """Direction of image column x_px, degrees right (+) or left (-) of the optical axis."""
    return math.atan2(x_px - center_x, focal) * DEG


def image_angle_deg(near, far):
    """Angle of the near->far midline from the image vertical, + = far end to the right."""
    return math.atan2(far[0] - near[0], near[1] - far[1]) * DEG


def valid_midline(near, far, width_px):
    """Far end above the near end, long enough, and not running across the view."""
    if near is None or far is None or far[1] >= near[1]:
        return False
    if math.sqrt((far[0] - near[0]) ** 2 + (far[1] - near[1]) ** 2) < MIN_LEN_FRAC * width_px:
        return False
    return abs(image_angle_deg(near, far)) <= MAX_IMAGE_ANGLE_DEG


def midline_heading(near, far, center_x, focal, horizon_y=None):
    """Heading of the crossing (deg, + = right). Without a horizon row: bearing of the far end (the far end lies close
    to the horizon, and walking toward it also corrects a sideways offset over the crossing). With horizon_y: bearing
    of the midline's vanishing point (the midline extended to the horizon row), which needs a level, calibrated camera."""
    x = far[0]
    dy = far[1] - near[1]
    if horizon_y is not None and abs(dy) >= 1.0:
        x = near[0] + (horizon_y - near[1]) * (far[0] - near[0]) / dy
    return bearing_deg(x, center_x, focal)


def alignment(heading, was_aligned=False):
    """ALIGNED, SAY_CW_LEFT, SAY_CW_RIGHT, or None when the crossing is too far off-axis to guide toward."""
    a = abs(heading)
    if a > GUIDE_MAX_DEG:
        return None
    if a <= (ALIGN_LEAVE_DEG if was_aligned else ALIGN_ENTER_DEG):
        return ALIGNED
    return SAY_CW_RIGHT if heading > 0 else SAY_CW_LEFT


def lateral_m(box, far, tol_px=0.0):
    """Sideways distance (metres, approx.) of a signal box (x, y, w, h) from the line toward the far end, measured in
    signal widths so it holds at any distance. tol_px absorbs the uncertainty of the far end."""
    x, _, w, _ = box[:4]
    if w <= 0:
        return float("inf")
    dx = max(0.0, abs(x + w / 2.0 - far[0]) - tol_px)
    return dx / w * SIGNAL_W_M


def on_crossing(box, far, tol_px=0.0):
    """True when a signal box stands above the far end of the crossing and close to the walking line."""
    y, h = box[1], box[3]
    if y + h > far[1] + tol_px:        # a signal is mounted high: its box ends above the far end of the ground line
        return False
    return lateral_m(box, far, tol_px) <= MAX_LATERAL_M


def pick_signal(boxes, scores, far, tol_px=0.0):
    """The confident box that belongs to the crossing and is nearest the walking line: (x, y, w, h, score) or None."""
    best, best_key = None, None
    for box, s in zip(boxes, scores):
        if s < DET_CONF or not on_crossing(box, far, tol_px):
            continue
        key = (lateral_m(box, far, tol_px), -box[2] * box[3])
        if best_key is None or key < best_key:
            best, best_key = tuple(box[:4]) + (s,), key
    return best


def gate_label(label, primary_owned, crossing_label):
    """Final label of the primary signal. primary_owned: None = no usable crossing (pass through), else whether the
    primary signal belongs to the crossing. crossing_label: reading of pick_signal()'s box when it is another box.
    Only a GREEN can change, and only to "unk"."""
    if primary_owned is None or label != "green":
        return label
    if not primary_owned:
        return "green" if crossing_label == "green" else "unk"
    return "unk" if crossing_label in ("red", "unk") else "green"


def gate_frame(label, sig, boxes, scores, owned, read_fn):
    """Per-frame helper for a reader. label: ped_logic_v3 label of the primary signal sig (x, y, w, h[, score]).
    owned: CrosswalkTracker.owned_far() -> (far, tol_px) or None. read_fn((x, y, w, h, score)) reads another box
    exactly like the primary; it runs only on GREEN frames, for the crossing's own signal."""
    if owned is None or label != "green" or sig is None:
        return label
    far, tol = owned
    primary_owned = on_crossing(sig, far, tol)
    chosen = pick_signal(boxes, scores, far, tol)
    crossing_label = None
    if chosen is not None and tuple(chosen[:4]) != tuple(sig[:4]):
        crossing_label = read_fn(chosen)
    return gate_label(label, primary_owned, crossing_label)


def _median(values):
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


class CrosswalkTracker:
    """Keeps the crosswalk model's recent midlines and reports a crossing only when it is fresh and consistent."""

    def __init__(self, width_px, focal, center_x=None, horizon_y=None):
        self.width = width_px
        self.focal = focal
        self.center_x = width_px / 2.0 if center_x is None else center_x
        self.horizon_y = horizon_y
        self.runs = []                 # (t, near, far, heading) per model run; near/far/heading None = nothing found
        self.aligned = False

    def update(self, now, midline):
        """midline: (near, far) in window px from one crosswalk model run, or None when it found nothing."""
        entry = (now, None, None, None)
        if midline is not None and valid_midline(midline[0], midline[1], self.width):
            near, far = midline
            entry = (now, near, far, midline_heading(near, far, self.center_x, self.focal, self.horizon_y))
        self.runs.append(entry)
        self.runs = [r for r in self.runs if ticks_diff(now, r[0]) <= WINDOW_MS]

    def current(self, now):
        """dict(near, far, heading, tol) of a fresh, consistent crossing (medians over the window), else None."""
        runs = [r for r in self.runs if ticks_diff(now, r[0]) <= WINDOW_MS]
        found = [r for r in runs if r[1] is not None]
        if len(found) < MIN_OBS or len(found) < MIN_FOUND_RATIO * len(runs):
            return None
        if ticks_diff(now, found[-1][0]) > STALE_MS:
            return None
        headings = [r[3] for r in found]
        if max(headings) - min(headings) > MAX_SPREAD_DEG:
            return None
        far_x = [r[2][0] for r in found]
        return {
            "near": (_median([r[1][0] for r in found]), _median([r[1][1] for r in found])),
            "far": (_median(far_x), _median([r[2][1] for r in found])),
            "heading": _median(headings),
            "tol": FAR_TOL_FRAC * self.width + max(far_x) - min(far_x),
        }

    def hint(self, now):
        """Alignment key for the current crossing (with hysteresis) or None. The reader decides when to speak it."""
        cur = self.current(now)
        key = None if cur is None else alignment(cur["heading"], self.aligned)
        self.aligned = key == ALIGNED
        return key

    def owned_far(self, now):
        """(far, tol_px) for signal ownership, or None when there is no roughly straight-ahead crossing."""
        cur = self.current(now)
        if cur is None or abs(cur["heading"]) > GUIDE_MAX_DEG:
            return None
        return cur["far"], cur["tol"]
