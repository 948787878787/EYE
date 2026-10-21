# Hard-case mining for the pedestrian signal reader (data flywheel).
# While the reader runs on the street, HardCasePolicy picks the frames most worth labeling
# (red-evidence veto, unsure classifier, undecidable voting, implausibly fast RED<->GREEN flips)
# and HardCaseWriter saves them with a CSV record to /data/hardcases/sNNN/ for retraining.
# The policy is pure Python: runs on CanMV MicroPython and on CPython (tests/test_hardcase.py).
# The writer imports board modules lazily, inside its functions, so this file imports anywhere.
TICKS_PERIOD = 1 << 30         # MicroPython ticks_ms period on 32-bit small ints (used by the fallback)

try:
    from time import ticks_diff
except ImportError:            # CPython (tests): same wrapping arithmetic as MicroPython ticks
    def ticks_diff(a, b):
        return (a - b + TICKS_PERIOD // 2) % TICKS_PERIOD - TICKS_PERIOD // 2

from ped_logic_v1 import UNKNOWN, RED, GREEN, GREEN_FLASH, WINDOW_MS, GREEN_HOLD_MS, RED_LOOKBACK_MS

# reason tags, in priority order: the first triggered reason that is not rate-limited is saved
VETO, FLIP, STUCK, UNSURE = "veto", "flip", "stuck", "unsure"
REASONS = (VETO, FLIP, STUCK, UNSURE)
COLOR_OF = {RED: "red", GREEN: "green", GREEN_FLASH: "green"}   # UNKNOWN has no color

# what counts as a hard case
UNSURE_TOP1 = 0.6              # top-1 prob below this: classifier commits to no class (= P_RED, lowest threshold)
UNSURE_MARGIN = 0.4            # top-1 minus top-2 below this: two classes compete (red vs other on tail lights,
                               # green vs other on blurry night lights); with 3 classes it adds top-1 up to 0.7
NORMAL_CHANGE_MS = max(WINDOW_MS, RED_LOOKBACK_MS) + GREEN_HOLD_MS   # a normal RED->GREEN change is
                               # UNKNOWN this long (3.6 s): derived so it follows the Voter's tuning
STUCK_UNKNOWN_MS = NORMAL_CHANGE_MS + 1500   # UNKNOWN this long with a signal in view: voting cannot
                               # decide; the 1.5 s margin covers frame jitter and a few lost votes
SIGNAL_GAP_MS = 1000           # detector dropouts shorter than this keep the UNKNOWN timer running
FLIP_MIN_MS = 8000             # two RED<->GREEN changes closer than this are implausible: Taiwan walk and red
                               # phases last >= ~10 s, and the Voter alone needs 1.5-3.6 s of UNKNOWN per change

# rate limits, so a stuck scene cannot fill the card
MIN_GAP_MS = 2000              # at most one save per 2 s overall; every save stalls the loop (see HardCaseWriter)
REASON_COOLDOWN_MS = 10000     # the same reason at most once per 10 s: a lasting situation gives a few frames
MAX_PER_REASON = 100           # per session: one noisy reason cannot use up the whole budget
MAX_PER_SESSION = 300          # per boot: ~300 x 250 KB = 75 MB, about one evening of labeling
SKIP_WHILE_GREEN = True        # no saves while GREEN is announced: a save stall must never delay leaving GREEN


def is_unsure(probs):
    """Least-confidence / margin test on the color classifier's probabilities (dict of class -> prob)."""
    p = sorted(probs.values(), reverse=True)
    second = p[1] if len(p) > 1 else 0.0
    return p[0] < UNSURE_TOP1 or p[0] - second < UNSURE_MARGIN


class HardCasePolicy:
    """Fed once per frame; decides whether the frame is worth saving for retraining."""

    def __init__(self):
        self.last_color = None         # "red" / "green" of the last decided state
        self.last_change = None        # ticks of the last RED<->GREEN change
        self.last_signal = None        # ticks of the last frame with a detected signal
        self.unknown_since = None      # ticks when UNKNOWN began with a signal in view
        self.last_save = None
        self.last_by_reason = {}       # reason -> ticks of its last save
        self.count_by_reason = {}      # reason -> saves this session
        self.saved = 0

    def update(self, now, state, label, probs, vetoed):
        """now: ticks_ms, state: Voter state, label: red/green/unk/none, probs: dict or None.
        Returns (save, reason). Call on every frame: the flip and stuck trackers need every state.
        A returned save counts even if the write later fails, so a failing card is not hammered."""
        triggered = self._triggered(now, state, label, probs, vetoed)
        if not triggered or not self._may_save(now, state):
            return False, None
        for reason in triggered:
            if self._reason_allowed(now, reason):
                self._record(now, reason)
                return True, reason
        return False, None

    def _triggered(self, now, state, label, probs, vetoed):
        """All reasons this frame qualifies for, in REASONS priority order."""
        hits = {
            FLIP: self._track_flip(now, state),
            STUCK: self._track_stuck(now, state, label),
            VETO: bool(vetoed),
            UNSURE: probs is not None and is_unsure(probs),
        }
        return [r for r in REASONS if hits[r]]

    def _track_flip(self, now, state):
        """True on a RED<->GREEN change that follows the previous change too quickly."""
        color = COLOR_OF.get(state)
        if color is None or color == self.last_color:
            return False
        first_color = self.last_color is None
        self.last_color = color
        if first_color:
            return False               # the first decided color of the session is not a change
        quick = self.last_change is not None and ticks_diff(now, self.last_change) < FLIP_MIN_MS
        self.last_change = now
        return quick

    def _track_stuck(self, now, state, label):
        """True while UNKNOWN has lasted longer than STUCK_UNKNOWN_MS with a signal in view."""
        if label != "none":
            self.last_signal = now
        in_view = self.last_signal is not None and ticks_diff(now, self.last_signal) <= SIGNAL_GAP_MS
        if state != UNKNOWN or not in_view:
            self.unknown_since = None
            return False
        if self.unknown_since is None:
            self.unknown_since = now
        return ticks_diff(now, self.unknown_since) > STUCK_UNKNOWN_MS

    def _may_save(self, now, state):
        """Limits shared by all reasons."""
        if self.saved >= MAX_PER_SESSION:
            return False
        if SKIP_WHILE_GREEN and state in (GREEN, GREEN_FLASH):
            return False
        return self.last_save is None or ticks_diff(now, self.last_save) >= MIN_GAP_MS

    def _reason_allowed(self, now, reason):
        if self.count_by_reason.get(reason, 0) >= MAX_PER_REASON:
            return False
        last = self.last_by_reason.get(reason)
        return last is None or ticks_diff(now, last) >= REASON_COOLDOWN_MS

    def _record(self, now, reason):
        self.saved += 1
        self.last_save = now
        self.last_by_reason[reason] = now
        self.count_by_reason[reason] = self.count_by_reason.get(reason, 0) + 1


# ---- board side: saving (board modules imported lazily) --------------------------------

HARDCASE_ROOT = "/data/hardcases"   # /sdcard is only a 500 MB partition; /data holds 13.9 GB
JPEG_QUALITY = 90              # labeling needs sharp small signals; ~150-300 KB per 1152x756 frame
MIN_FREE_MB = 200              # stop saving before the card is full (same margin as shutter_v2.py)
WRITE_RETRIES = 3              # /data may reject the first open in a fresh directory (EPERM)
RETRY_DELAY_MS = 50
PROB_KEYS = ("red", "green", "other")
CSV_HEADER = "file,ticks_ms,reason,state,label,p_red,p_green,p_other,vetoed,box_x,box_y,box_w,box_h\n"


def next_session_name(names):
    """'sNNN' one above the highest existing session folder, so a number is never reused."""
    last = 0
    for name in names:
        if name.startswith("s") and name[1:].isdigit():
            last = max(last, int(name[1:]))
    return "s%03d" % (last + 1)


def csv_line(name, now, reason, state, label, probs, vetoed, box=None):
    """One CSV record. probs None (no signal) and box None leave their columns empty.
    box: (x, y, w, h) of the primary signal in saved-image pixels, a pre-label for annotation."""
    p = ["%.3f" % probs[k] for k in PROB_KEYS] if probs else ["", "", ""]
    b = [str(int(v)) for v in box] if box else ["", "", "", ""]
    return ",".join([name, str(now), reason, state, label] + p + [str(int(bool(vetoed)))] + b) + "\n"


def _sleep_ms(ms):
    import time
    time.sleep_ms(ms)


def open_retry(path, mode):
    """Same as shutter_v2.py (not importable: it runs main() on import)."""
    for attempt in range(WRITE_RETRIES):
        try:
            return open(path, mode)
        except OSError:
            if attempt == WRITE_RETRIES - 1:
                raise
            _sleep_ms(RETRY_DELAY_MS)


def write_retry(path, data):
    for attempt in range(WRITE_RETRIES):
        try:
            with open_retry(path, "wb") as f:
                f.write(data)
            return
        except OSError:
            if attempt == WRITE_RETRIES - 1:
                raise
            _sleep_ms(RETRY_DELAY_MS)


def mkdir_if_missing(path):
    import os
    try:
        os.stat(path)
    except OSError:
        os.mkdir(path)


def free_mb(path):
    import os
    st = os.statvfs(path)          # (bsize, frsize, blocks, bfree, bavail, ...)
    return st[1] * st[4] // (1024 * 1024)


def roi_jpeg(img, quality=JPEG_QUALITY):
    """RGBP888 (planar) snapshot -> JPEG bytes.
    to_jpeg() is only proven on packed RGB888 frames (shutter_v2.py, examples/16-AI-Cube/
    DataCollectionCamera.py), so repack CHW -> HWC with the SDK helper libs.Utils.chw2hwc
    (used on RGBP888 frames in libs/PlatTasks.py) and wrap it without a copy, as the
    examples/23-CV_Lite scripts do. Costs one ~2.6 MB heap copy for 1152x756."""
    import image
    from libs.Utils import chw2hwc
    hwc = chw2hwc(img.to_numpy_ref())
    rgb = image.Image(hwc.shape[1], hwc.shape[0], image.RGB888, alloc=image.ALLOC_REF, data=hwc)
    return rgb.to_jpeg(quality=quality).bytearray()


class HardCaseWriter:
    """Saves hard-case frames as hc_NNNN_<reason>.jpg + log.csv in /data/hardcases/sNNN/.
    Save the 1152x756 ROI frame (chn1, the classifier's crop source): it is full sensor resolution
    where signals appear and holds 42% of the pixels of 1080p, so the stall is shorter.
    Stall per save (estimate, not measured): 1080p JPEG takes ~0.5 s on this board, so expect
    ~0.2 s encode + the CHW->HWC repack + the SD write, roughly 0.3-0.5 s with no new frames.
    The Voter is time-based, so a stall only thins its window; MIN_GAP_MS bounds the duty cycle,
    and SKIP_WHILE_GREEN keeps stalls out of announced GREEN. Call save() after the state has been
    shown (LED, display) so the stall never delays an announcement already computed."""

    def __init__(self, root=HARDCASE_ROOT):
        self.root = root
        self.dir = None                # created on the first save: rmdir is unsupported on /data,
        self.log = None                # so boots without hard cases leave no empty folder
        self.count = 0

    def _ensure_session(self):
        """Folder first, then the log; a failed log open is retried in the same folder next time."""
        import os
        if self.dir is None:
            mkdir_if_missing(self.root)
            path = self.root + "/" + next_session_name(os.listdir(self.root))
            os.mkdir(path)
            self.dir = path
            print("hardcase session", path)
        if self.log is None:
            self.log = open_retry(self.dir + "/log.csv", "a")
            self.log.write(CSV_HEADER)
            self.log.flush()

    def save(self, img, now, reason, state, label, probs, vetoed, box=None):
        """True when the JPEG and its CSV record are on the card. Never raises (except IDE stop):
        the signal reader must keep running when the card misbehaves."""
        import gc
        try:
            self._ensure_session()
            if free_mb(self.root) < MIN_FREE_MB:
                print("hardcase: card almost full, not saving")
                return False
            self.count += 1            # never reused, even after a failed write: no overwrites
            name = "hc_%04d_%s.jpg" % (self.count, reason)
            write_retry(self.dir + "/" + name, roi_jpeg(img))
            self.log.write(csv_line(name, now, reason, state, label, probs, vetoed, box))
            self.log.flush()
            return True
        except Exception as e:
            if str(e) == "IDE interrupt":
                raise
            print("hardcase save failed:", e)
            return False
        finally:
            gc.collect()

    def close(self):
        if self.log:
            self.log.close()
            self.log = None
