# Pedestrian signal reader v15 "bbox" = v14 + biased exposure + black box + crop-only hard cases (user 2026-10-14).
#   1. exposure_v1 (architecture review A5): after AE_SETTLE_FRAMES the ISP auto exposure is switched off and exposure
#      time / analog gain are steered to half the brightness AE would choose (EV -1), so lit LED signals do not clip
#      to white. UNVALIDATED on the detector: EXPOSURE = False keeps the ISP AE. Any sensor call failing -> AE back on.
#      health_v1 gets the mean scaled back by 2^-EV_BIAS, so a deliberately darker frame is not a "camera_dark" fault.
#   2. blackbox_v1: one CSV line per frame (state, label, probs, box, fault, what was said, exposure, gain, light) in
#      /data/blackbox/sNNN/telemetry.csv with a SHA-256 chain (tools/verify_blackbox.py). Numbers only, no images.
#   3. hardcase_v2: hard cases save only the signal crop, not the whole sensor ROI (passers-by, plates).
# v14 stays as it was. Decision logic unchanged (ped_logic_v4).
# Pedestrian signal reader v14 "aim" = v13 + aiming guidance (user 2026-10-14, blind-user review item 7): aim_v1 says
# "號誌在左/右，請向左/右轉" when a front-facing signal stays off-centre, and "號誌在正前方" once it is centred after a
# turn prompt. Spoken only (an aiming beep could be mistaken for the GREEN heartbeat tick); never while GREEN /
# GREEN_FLASH or during a fault. v13 stays as it was.
# Pedestrian signal reader v13 "safe" = v12 + fail-safe feedback (user 2026-10-14, architecture review A9/A10).
# Decision logic is unchanged (ped_logic_v4: v5 / v6 failed their pre-registered gates). v12 stays as it was.
# v13 changes:
#   1. Silence = do not go (guide_v2.SafeAnnouncer): a tick every second while GREEN, a faster double tick while
#      GREEN_FLASH; a lost green is withdrawn at once ("號誌無法確認，請勿開始穿越"), never "stop".
#   2. Faults are spoken (health_v1): camera too dark, lens blocked, loop too slow for the Voter; while a fault lasts
#      no colour is announced, the LED stays off, and the fault is repeated every 6 s.
#   3. Self-test before "ready" (voice_v2): every required prompt must load and the audio output must open, else the
#      reader refuses to start ("ready" is never said; "error" if any sound works) - no "ready" = do not use it.
#   4. Stall watchdog in the audio thread (voice_v2): no frame for 2 s -> "系統異常…" from the writer itself;
#      hardware WDT in every mode (v12: standalone only), WDT_TIMEOUT_S 3 (v12: 10).
# Pedestrian signal reader v12 "logic4" = v8 + ped_logic_v4 (CanMV K230 fw v1.8). v10 (cues, another worktree) and
# v11 (FULL/ZOOM plan) are taken names; v12 starts from the deployed v8 and carries everything of it forward.
# v12 changes (docs/analysis/2026-10-05_architecture_review.md, fixes A2 A4 A6 A7 A8):
#   1. The detector outputs boxes from DET_POST_CONF 0.20 (v8: 0.35, which also hid weak red lamps from the guard);
#      the primary still needs PRIMARY_CONF 0.35, a neighbour blocks GREEN from GUARD_CONF 0.25. max_boxes 20.
#   2. Neighbours are read without the shape gate (neighbour_read): a box on the lit red lamp alone blocks GREEN.
#   3. Edge guard: GREEN from a box touching the window edge or without room above it for the red lamp is unk.
#   4. A guard block latches in the Voter like a red vote (no GREEN for 3 s); GREEN_FLASHING needs a GREEN
#      established in the same cycle and a 30% green share. MIN_READ_PX 16 (v8: 20).
# v8 "guard" = v7 + neighbour guard + board speaker + timing:
# v8 changes (docs/analysis/2026-09-26_optimization_review.md):
#   1. ped_logic_v3.guard_green: a GREEN primary next to another confident signal that reads red or unclear
#      (two signals of two crossings on one pole) is not announced (trace char C). v7 announced GREEN on the
#      leak-free test frame -2025-11-16-214839 while the signal facing the user was red.
#   2. Speech on the board: voice_v1.Voice plays /sdcard/ped_light/audio/<key>.wav (3.5 mm jack) in addition
#      to the "SAY <key>" lines; any audio failure turns Voice into a no-op (detection keeps running).
#      VOICE=False disables it (e.g. while tools/voice_bridge.py plays on the Mac).
#   3. DEBUG_OSD (default: on from the IDE, off standalone) skips the per-frame overlay drawing that a blind
#      user never sees; GC_EVERY (default 10; v7 collected every frame) spaces out gc.collect(); TIMING prints mean ms per stage
#      every 200 frames to find where the 12-14 FPS go before changing the model input.
# v7 (user request): window 80% x 80% of the frame (x 0.10-0.90, y 0.00-0.80) instead of 60% x 70%,
# v7 (user request): window 80% x 80% of the frame (x 0.10-0.90, y 0.00-0.80) instead of 60% x 70%,
# so the signal leaves the box less easily. Cost: the detector sees signals at 0.625 instead of
# 0.833 of their chn2 size (0.75x), so small far signals are found in fewer frames.
# Reads the pedestrian signal in the walking-direction ROI and speaks state changes
# (red / green / green flashing / green lost). New in v6 (board/scan_v1.py): no signal in view for
# 5 s -> "未偵測到號誌，請慢慢左右轉動" (at most every 10 s), then "找到號誌" when one comes into view.
# Still no side-window search or turn-left/right guidance (v4 has those).
# Extra debug for bench tests: all center detections with detector confidence, classifier
# probabilities of the primary signal on screen, and a once-per-second DBG line on the terminal.
# Stage 1: YOLO26n finds pedestrian signals in the walking-direction ROI (single class).
# Stage 2: a 96x96 classifier reads the color on a crop from the full-resolution ROI,
#          and a rule-based red-evidence veto (tools/color_gate.py) must not object to GREEN.
# Decision logic lives in ped_logic_v1.py / guide_v1.py, unit-tested on the Mac
# (tests/test_ped_logic.py, tests/test_guide.py). Never defaults to GREEN.
# Speech: prints "SAY <key>" and plays it on the board (voice_v1, VOICE=True).
from libs.PipeLine import PipeLine
from libs.YOLO import YOLO26
from libs.AIBase import AIBase
from libs.AI2D import Ai2d
from libs.Utils import *
from media.sensor import *
from media.display import *
from media.media import *
from machine import Pin, FPIOA, WDT
import nncase_runtime as nn
import ulab.numpy as np
import os, gc, time, image, sys

sys.path.append("/sdcard/ped_light")
from ped_logic_v4 import (UNKNOWN, RED, GREEN, GREEN_FLASH, PRIMARY_CONF, DET_POST_CONF, Voter, red_veto,
                          primary_signal, label_from_probs, readable, plausible, neighbour_label, apply_guards)
from hardcase_v2 import HardCasePolicy, CropHardCaseWriter
from exposure_v1 import ExposureControl, EV_BIAS, TARGET
from blackbox_v1 import BlackBox
from guide_v2 import SafeAnnouncer
from health_v1 import Health, frame_stats
from aim_v1 import AimGuide
from scan_v1 import ScanPrompter
from voice_v2 import Voice

DET_KMODEL = "/sdcard/ped_light/models/tw_sig_yolo26n_640_roi_v4.kmodel"
CLS_KMODEL = "/sdcard/ped_light/models/tw_color_yolo11n_cls_96_v4.kmodel"
CLS_LABELS = ["green", "other", "red"]   # Ultralytics classify order = sorted folder names
DET_INPUT = [640, 640]
CLS_INPUT = 96

SENSOR_SIZE = [1920, 1080]
ROI = (0.10, 0.00, 0.90, 0.80)   # v7 wide window; training ROI (tools/build_roi_dataset.py) is 0.20-0.80 x 0.05-0.75
WINDOWS = {"center": (ROI[0], ROI[2])}
FRAME_SIZE = [1280, 720]         # chn2: full frame; detector windows are cropped from it by ai2d
DET_SRC_SIZE = [1024, 576]       # window size = ROI at the chn2 scale (training windows were 768x504)
WIN_Y0 = round(ROI[1] * FRAME_SIZE[1])
CLS_SRC_SIZE = [1536, 864]       # chn1: ROI at full sensor resolution for color crops (1.5 x DET_SRC_SIZE)
DISPLAY_SIZE = [960, 540]

CONTEXT = 1.6                    # classifier crop side = box long side x CONTEXT (as in training)
MIN_CROP_PX = 16

LED_PIN = 52
WDT_TIMEOUT_S = 3                # v13: every mode (v12: 10 s, standalone only); a hung loop reboots the board
STATS_EVERY = 3                  # v13: frame brightness / contrast sample every N frames (health_v1)
STATS_STEP = 32                  # every 32nd pixel of the chn2 green plane: 23 x 40 = 920 values
STANDALONE = globals().get("STANDALONE", False)
HARDCASES = globals().get("HARDCASES", True)
EXPOSURE = globals().get("EXPOSURE", True)       # v15: biased exposure (exposure_v1); False = ISP auto exposure
BLACKBOX = globals().get("BLACKBOX", True)       # v15: per-frame telemetry with a hash chain (blackbox_v1)
AE_SETTLE_FRAMES = 30            # let the ISP AE settle (~2 s) before taking over from its values
VOICE = globals().get("VOICE", True)             # speak on the board (voice_v1); False while the Mac bridge speaks
DEBUG_OSD = globals().get("DEBUG_OSD", not STANDALONE)   # overlay only for bench debugging: a blind user never sees it
GC_EVERY = globals().get("GC_EVERY", 10)         # gc.collect() every N frames (v7: every frame, 6.0 ms; every 10: 0.3 ms)
TIMING = globals().get("TIMING", False)          # print mean ms per stage every 200 frames   # data flywheel: save hard frames to /data/hardcases/sNNN/
TRACE = globals().get("TRACE", False)   # bench: "TR <one char per frame> <state>" every TRACE_LEN frames
TRACE_LEN = 20
TRACE_CHAR = {"green": "G", "red": "R", "unk": "U", "none": "N"}   # C = green blocked by the neighbour guard   # V = green vetoed, - = no detection

STATE_COLORS = {UNKNOWN: (255, 255, 255), RED: (255, 0, 0), GREEN: (0, 255, 0), GREEN_FLASH: (255, 255, 0)}


class WindowDetector(YOLO26):
    """YOLO26 on fixed windows of one full frame. Each window has its own prebuilt Ai2d
    (crop + letterbox pad + resize, verified on the board: build 56 ms once, run 5 ms),
    and AIBase.preprocess uses self.ai2d, so switching windows costs nothing per frame."""

    def __init__(self):
        super().__init__(task_type="detect", mode="video", kmodel_path=DET_KMODEL, labels=["ped_signal"],
                         rgb888p_size=DET_SRC_SIZE, model_input_size=DET_INPUT, display_size=DET_SRC_SIZE,
                         conf_thresh=DET_POST_CONF, max_boxes_num=20, debug_mode=0)
        top, bottom, left, right, _ = letterbox_pad_param(DET_SRC_SIZE, DET_INPUT)
        self.window_ai2d = {}
        self.window_x0 = {}
        for name, (fx0, _) in WINDOWS.items():
            x0 = round(fx0 * FRAME_SIZE[0])
            a = Ai2d(0)
            a.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)
            a.crop(x0, WIN_Y0, DET_SRC_SIZE[0], DET_SRC_SIZE[1])
            a.pad([0, 0, 0, 0, top, bottom, left, right], 0, [128, 128, 128])
            a.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            a.build([1, 3, FRAME_SIZE[1], FRAME_SIZE[0]], [1, 3, DET_INPUT[1], DET_INPUT[0]])
            self.window_ai2d[name] = a
            self.window_x0[name] = x0
        self.ai2d = self.window_ai2d["center"]

    def detect(self, frame_np, window):
        self.ai2d = self.window_ai2d[window]
        return self.run(frame_np)

    def side_detections(self, frame_np, window):
        """(cx_fraction_of_full_frame, w_px, h_px) of confident boxes in a side window."""
        res = self.detect(frame_np, window)
        if not res:
            return []
        out = []
        for (x, y, w, h), s in zip(res[0], res[2]):
            if s >= PRIMARY_CONF:
                out.append(((self.window_x0[window] + x + w / 2) / FRAME_SIZE[0], w, h))
        return out

    def deinit(self):
        self.window_ai2d.clear()
        super().deinit()


class ColorClassifier(AIBase):
    """Crops a square around a detection from the full-res ROI frame and classifies its color."""

    def __init__(self):
        super().__init__(CLS_KMODEL, [CLS_INPUT, CLS_INPUT], CLS_SRC_SIZE, 0)
        self.ai2d = Ai2d(0)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)

    def classify(self, frame_np, x, y, side):
        self.ai2d.crop(x, y, side, side)
        self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
        self.ai2d.build([1, 3, CLS_SRC_SIZE[1], CLS_SRC_SIZE[0]], [1, 3, CLS_INPUT, CLS_INPUT])
        return self.run(frame_np)

    def postprocess(self, results):
        probs = results[0][0]
        return {CLS_LABELS[i]: float(probs[i]) for i in range(len(CLS_LABELS))}


def roi_pixels():
    x0, y0, x1, y1 = ROI
    # round, not int: board floats are single precision (0.8 * 1920 -> 1535.99 -> 1535 fails the sensor check)
    return (round(x0 * SENSOR_SIZE[0]), round(y0 * SENSOR_SIZE[1]),
            round((x1 - x0) * SENSOR_SIZE[0]), round((y1 - y0) * SENSOR_SIZE[1]))


def create_camera():
    sensor = Sensor(fps=30)
    sensor.reset()
    Display.init(Display.VIRT, width=DISPLAY_SIZE[0], height=DISPLAY_SIZE[1], osd_num=1, to_ide=True)
    sensor.set_framesize(w=DISPLAY_SIZE[0], h=DISPLAY_SIZE[1], chn=CAM_CHN_ID_0)
    sensor.set_pixformat(Sensor.YUV420SP, chn=CAM_CHN_ID_0)
    sensor.set_framesize(w=CLS_SRC_SIZE[0], h=CLS_SRC_SIZE[1], chn=CAM_CHN_ID_1, crop=roi_pixels())
    sensor.set_pixformat(Sensor.RGBP888, chn=CAM_CHN_ID_1)
    sensor.set_framesize(w=FRAME_SIZE[0], h=FRAME_SIZE[1], chn=CAM_CHN_ID_2)
    sensor.set_pixformat(Sensor.RGBP888, chn=CAM_CHN_ID_2)
    Display.bind_layer(**sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0), layer=Display.LAYER_VIDEO1)
    sensor.run()
    return sensor


def to_display(x, y, w, h):
    """chn2 ROI pixel box -> display pixel box."""
    rx0, ry0, rx1, ry1 = ROI
    sx = (rx1 - rx0) * DISPLAY_SIZE[0] / DET_SRC_SIZE[0]
    sy = (ry1 - ry0) * DISPLAY_SIZE[1] / DET_SRC_SIZE[1]
    return int(rx0 * DISPLAY_SIZE[0] + x * sx), int(ry0 * DISPLAY_SIZE[1] + y * sy), int(w * sx), int(h * sy)


def classify_box(sig, cls_np, classifier):
    """Crop a CONTEXT square around a window-px box from chn1 and classify it: probs."""
    x, y, w, h = sig[:4]
    k = CLS_SRC_SIZE[0] / DET_SRC_SIZE[0]
    cx, cy = (x + w / 2) * k, (y + h / 2) * k
    side = int(max(MIN_CROP_PX, max(w, h) * k * CONTEXT))
    side = min(side, CLS_SRC_SIZE[0], CLS_SRC_SIZE[1])
    x0 = int(min(max(0, cx - side / 2), CLS_SRC_SIZE[0] - side))
    y0 = int(min(max(0, cy - side / 2), CLS_SRC_SIZE[1] - side))
    return classifier.classify(cls_np, x0, y0, side)


def box_veto(sig, cls_np):
    """Red-evidence veto inside a window-px box on chn1."""
    x, y, w, h = sig[:4]
    k = CLS_SRC_SIZE[0] / DET_SRC_SIZE[0]
    bx = int(min(max(0, x * k), CLS_SRC_SIZE[0] - 1))
    by = int(min(max(0, y * k), CLS_SRC_SIZE[1] - 1))
    bw = int(max(1, min(w * k, CLS_SRC_SIZE[0] - bx)))
    bh = int(max(1, min(h * k, CLS_SRC_SIZE[1] - by)))
    pixel_at = lambda xx, yy: (int(cls_np[0, yy, xx]), int(cls_np[1, yy, xx]), int(cls_np[2, yy, xx]))
    return red_veto(pixel_at, bx, by, bw, bh)


def frame_label(sig, cls_np, classifier):
    """Classify the primary signal; returns (label, probs, vetoed)."""
    if sig is None:
        return "none", None, False
    x, y, w, h, _ = sig
    k = CLS_SRC_SIZE[0] / DET_SRC_SIZE[0]
    if not readable(h * k):              # chn1 is full sensor resolution: h * k is in sensor px
        return "unk", None, False        # too far for a reliable color reading
    if not plausible(w * k, h * k):      # whole-screen box, square blob or side view
        return "none", None, False
    probs = classify_box(sig, cls_np, classifier)
    vetoed = False
    if label_from_probs(probs, False) == "green":   # veto check only when it could matter
        vetoed = box_veto(sig, cls_np)
    return label_from_probs(probs, vetoed), probs, vetoed


def neighbour_read(box, cls_np, classifier):
    """Guard reading of a neighbour (ped_logic_v4.neighbour_label): no shape gate, the veto always runs."""
    k = CLS_SRC_SIZE[0] / DET_SRC_SIZE[0]
    if not readable(box[3] * k):
        return neighbour_label(None, False)
    return neighbour_label(classify_box(box, cls_np, classifier), box_veto(box, cls_np))


def draw_overlay(osd, res, sig, label, probs, vetoed, state):
    """Bench-debug overlay (DEBUG_OSD): window, every center detection, the primary signal and the state."""
    osd.clear()
    rx, ry, rw, rh = to_display(0, 0, DET_SRC_SIZE[0], DET_SRC_SIZE[1])
    osd.draw_rectangle(rx, ry, rw, rh, color=(255, 255, 255), thickness=1)
    if res:                          # every center detection, thin, with detector confidence
        for (x, y, w, h), s in zip(res[0], res[2]):
            dx, dy, dw, dh = to_display(x, y, w, h)
            osd.draw_rectangle(dx, dy, dw, dh, color=(128, 128, 128), thickness=1)
            osd.draw_string_advanced(dx, dy + dh + 2, 18, "%.2f" % s, color=(200, 200, 200))
    if sig:
        bx, by, bw, bh = to_display(*sig[:4])
        color = {"red": (255, 0, 0), "green": (0, 255, 0), "none": (128, 128, 128)}.get(label, (255, 255, 0))
        osd.draw_rectangle(bx, by, bw, bh, color=color, thickness=3)
        tag = label + (" veto" if vetoed else "")
        if probs:
            tag += " g%.2f o%.2f r%.2f" % (probs["green"], probs["other"], probs["red"])
        osd.draw_string_advanced(bx, max(0, by - 28), 22, tag, color=color)
    osd.draw_string_advanced(10, 10, 40, state, color=STATE_COLORS[state])
    Display.show_image(osd, 0, 0, Display.LAYER_OSD3)


def take_over_exposure(sensor):
    """Read what the ISP AE settled on, switch AE off and return the controller; None (AE stays on) if any call
    fails - fw 1.8 may lack these Sensor methods (stubs are newer)."""
    try:
        ctl = ExposureControl(sensor.get_exposure_time_range(), sensor.get_again_range(), sensor.exposure(),
                              sensor.again())
        sensor.auto_exposure(False)
        print("EXPOSURE takeover: exp %d us gain %.2f, target mean %d" % (ctl.exp, ctl.gain, int(TARGET)))
        return ctl
    except Exception as e:
        if str(e) == "IDE interrupt":
            raise
        print("EXPOSURE takeover failed, ISP AE kept:", e)
        return None


def apply_exposure(sensor, change):
    try:
        sensor.exposure(change[0])
        sensor.again(change[1])
        return True
    except Exception as e:
        if str(e) == "IDE interrupt":
            raise
        print("EXPOSURE set failed, back to ISP AE:", e)
        try:
            sensor.auto_exposure(True)
        except Exception as e2:
            if str(e2) == "IDE interrupt":
                raise
            print("EXPOSURE could not re-enable ISP AE:", e2)
        return False


def main():
    voice = Voice() if VOICE else None           # audio before the camera (order of 26-xiaozhi, voice_v1 notes)
    if voice and not voice.self_test_ok():       # v13: no "ready" without every safety prompt and a working output
        print("SELF-TEST FAILED, missing prompts:", voice.missing)
        voice.say("error")
        voice.close(wait_ms=3000)
        raise RuntimeError("self-test failed: reader not started")
    if not voice:
        print("WARNING VOICE=False: no heartbeat, faults or stall alarm on the board (Mac bridge only)")
    fpioa = FPIOA()
    fpioa.set_function(LED_PIN, FPIOA.GPIO0 + LED_PIN)
    led = Pin(LED_PIN, Pin.OUT)
    sensor = create_camera()
    osd = image.Image(DISPLAY_SIZE[0], DISPLAY_SIZE[1], image.ARGB8888)
    detector = WindowDetector()
    classifier = ColorClassifier()
    voter = Voter()
    announcer = SafeAnnouncer()
    health = Health()
    aim = AimGuide()
    stats = (128, 255)                           # until the first sample: no fault
    policy = HardCasePolicy() if HARDCASES else None
    writer = CropHardCaseWriter() if HARDCASES else None
    bb = BlackBox() if BLACKBOX else None
    expo = None                                  # ExposureControl once AE has settled (EXPOSURE)
    wdt = WDT(1, WDT_TIMEOUT_S)
    last_state = None
    n = 0
    t0 = time.ticks_ms()
    scanner = ScanPrompter(t0)
    trace = []
    spent = {"snap": 0, "det": 0, "cls": 0, "osd": 0, "gc": 0}   # us per stage, TIMING

    def speak(key, now):
        if not key.startswith("tick"):
            print("SAY", key)
        if voice:
            voice.say(key, now)

    if voice:
        voice.say("ready")
    try:
        while True:
            os.exitpoint()
            if wdt:
                wdt.feed()
            ta = time.ticks_us()
            frame = sensor.snapshot(chn=CAM_CHN_ID_2)
            cls_img = sensor.snapshot(chn=CAM_CHN_ID_1)
            frame_np = frame.to_numpy_ref()
            cls_np = cls_img.to_numpy_ref()
            tb = time.ticks_us()
            res = detector.detect(frame_np, "center")
            sig = primary_signal(res[0], res[2], DET_SRC_SIZE[0]) if res else None
            tc = time.ticks_us()
            label, probs, vetoed = frame_label(sig, cls_np, classifier)
            blocked = False
            if sig:
                label, blocked = apply_guards(label, sig, res[0], res[2],
                                              lambda box: neighbour_read(box, cls_np, classifier),
                                              DET_SRC_SIZE[0], DET_SRC_SIZE[1])
            td = time.ticks_us()
            now = time.ticks_ms()
            state = voter.update(now, label, blocked)      # a block keeps GREEN off for RED_LOOKBACK_MS
            if TRACE:
                trace.append("-" if sig is None else ("C" if blocked else "V" if vetoed else TRACE_CHAR.get(label, "?")))
                if len(trace) >= TRACE_LEN:
                    print("TR", "".join(trace), state)
                    trace = []
            if voice:
                voice.alive(now)                         # stall watchdog in the audio thread
            if n % STATS_EVERY == 0:
                stats = frame_stats(frame_np[1, ::STATS_STEP, ::STATS_STEP].flatten().tolist())
            if EXPOSURE and expo is None and n == AE_SETTLE_FRAMES:
                expo = take_over_exposure(sensor)
            if expo is not None:
                change = expo.update(stats[0])
                if change and not apply_exposure(sensor, change):
                    expo = None                          # sensor refused: AE is back on
            light = int(stats[0] * 2 ** -EV_BIAS) if expo is not None else stats[0]
            fault = health.update(now, light, stats[1])
            spoken = announcer.update(now, state, fault)   # heartbeat, immediate withdrawal, faults (guide_v2)
            for key in spoken:
                speak(key, now)
            if fault is None:
                for key in scanner.update(now, sig is not None and label != "none", bool(spoken)):
                    speak(key, now)
                    spoken = spoken + [key]
            aim_sig = None
            if sig:                                      # primary box: window px -> fraction of the full frame width
                aim_sig = (ROI[0] + (sig[0] + sig[2] / 2) / DET_SRC_SIZE[0] * (ROI[2] - ROI[0]), sig[2], sig[3])
            for key in aim.update(now, state, fault, aim_sig):
                if not spoken:                           # a colour / fault / scan prompt this frame goes first
                    speak(key, now)
                    spoken = spoken + [key]
            if bb:
                bb.record(state, now, n, label, probs, sig, blocked, vetoed, fault, spoken,
                          expo.exp if expo else None, expo.gain if expo else None, stats[0], stats[1])

            te = time.ticks_us()
            if DEBUG_OSD:
                draw_overlay(osd, res, sig, label, probs, vetoed, state)
            tf = time.ticks_us()

            led.value(0 if fault else 1 if state == GREEN else ((now // 150) % 2 if state == GREEN_FLASH else 0))
            if state != last_state:
                print("STATE", state, "fault", fault, "t_ms", time.ticks_diff(now, t0))
                last_state = state
            if policy:                  # after the state is shown: a save stalls the loop ~0.3 s
                save, reason = policy.update(now, state, label, probs, vetoed)
                if save:
                    k = CLS_SRC_SIZE[0] / DET_SRC_SIZE[0]
                    box = [v * k for v in sig[:4]] if sig else None
                    writer.save(cls_img, now, reason, state, label, probs, vetoed, box)
            n += 1
            if n % 10 == 0:                  # ~1 line per second for bench debugging
                if sig:
                    h_px = int(sig[3] * CLS_SRC_SIZE[0] / DET_SRC_SIZE[0])
                    p = " g%.2f o%.2f r%.2f" % (probs["green"], probs["other"], probs["red"]) if probs else ""
                    print("DBG det %.2f h %dpx label %s%s%s state %s" % (sig[4], h_px, label, p,
                                                                        " guard" if blocked else "", state))
                else:
                    print("DBG no detection state", state, "light %d spread %d fault %s" % (stats[0], stats[1], fault))
            tg = time.ticks_us()
            if n % GC_EVERY == 0:
                gc.collect()
            th = time.ticks_us()
            if TIMING:
                for key, (a, b) in (("snap", (ta, tb)), ("det", (tb, tc)), ("cls", (tc, td)), ("osd", (te, tf)),
                                    ("gc", (tg, th))):
                    spent[key] += time.ticks_diff(b, a)
            if n % 200 == 0:
                print("fps", round(n * 1000 / time.ticks_diff(now, t0), 1))
                if TIMING:
                    print("TIMING ms/frame " + " ".join("%s %.1f" % (k, v / 200000) for k, v in spent.items()))
                    spent = {k: 0 for k in spent}
    except KeyboardInterrupt:
        print("stopped")
    except Exception as e:
        if str(e) != "IDE interrupt":
            if voice:
                voice.say("error")
                voice.close(wait_ms=3000)
            raise
        print("stopped by IDE")
    finally:
        led.value(0)
        if voice:
            voice.close()
        if writer:
            writer.close()
        if bb:
            bb.flush()
        if wdt:
            wdt.close()
        detector.deinit()
        classifier.deinit()
        os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
        sensor.stop()
        time.sleep_ms(50)
        Display.deinit()

main()
