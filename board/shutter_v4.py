# Standalone photo + video capture for Taiwan intersections (01Studio CanMV K230, firmware v1.8).
# v4 vs v3: stopping from the IDE (or a USB connection by the MCP tools) while recording or saving is no longer
# swallowed as a write error. v3's Recorder.pump / Shutter.save caught every Exception, so the 2026-09-26 key
# test logged "clip_end ... reason=error" when the computer connected; the clip itself was fine. Now the IDE
# interrupt propagates, main() stops normally and the clip is closed with reason=exit.
# KEY (IO21): short press = 1 photo (1920x1080 JPEG q95, as v2).
#             hold >= 1 s = start / stop MP4 recording (H.264 1920x1080, sensor rate 28-30 fps, hardware encoder).
#             A long press also keeps the photo taken when the key went down.
#             A short press while recording still saves a photo (the encoder queue absorbs the pause).
# Blue LED (IO52): idle = short blink every 2 s; solid while saving a photo or while the key is held;
#                  recording = slow 1 Hz blink (0.5 s on / 0.5 s off); fast blink = error or SD almost full.
# Files: /data/captures/sNNN/img_NNNN.jpg and vid_NNNN.mp4, new session folder per boot, log.csv per session.
# Clips are split every ~60 s at a keyframe (no frames lost). A clip that is not closed (power cut,
# watchdog reset) is lost, so the split also bounds the loss. Fragmented MP4 closes in ~5 ms; a plain
# MP4 took 11 s to close a 10 s clip on fw 1.8 (longer than the watchdog timeout).
# v3 vs v2: the key is debounced on release too. v2 treated a single "released" reading during a hold
# (contact chatter) as a new press, restarted the 1 s hold timer and never reached burst mode.
from media.sensor import *
from media.display import *
from media.media import *
from media.vencoder import *
from mpp.mp4_format import *
from mpp.mp4_format_struct import *
from machine import Pin, FPIOA, WDT, RTC
import os, time, gc, uctypes

KEY_PIN = 21
KEY_PRESSED = 0
LED_PIN = 52
PHOTO_SIZE = [1920, 1080]
PREVIEW_SIZE = [640, 360]
JPEG_QUALITY = 95
VIDEO_SIZE = [1920, 1080]
VIDEO_KBPS = 8000
VENC_CHN = VENC_CHN_ID_0
VENC_OUT_BUFS = 30            # ~1 s of encoded frames queued while a photo save blocks the loop
STREAM_PACKS_MAX = 64         # GetStream returns the whole queue at once (header + I + P...)
KEYFRAME_BUF_BYTES = 768 * 1024  # header + IDR; IDRs were ~85 KB at 8 Mbps
CLIP_MAX_MS = 60000
FMP4 = True
CAPTURE_ROOT = "/data/captures"
MIN_FREE_MB = 200
PRESS_DEBOUNCE_MS = 20
RELEASE_DEBOUNCE_MS = 80
LONG_PRESS_MS = 1000
HEARTBEAT_MS = 2000
HEARTBEAT_ON_MS = 80
REC_BLINK_MS = 500
FAST_BLINK_MS = 150
ERROR_SHOW_MS = 2000
WDT_TIMEOUT_S = 10
SPACE_CHECK_MS = 5000
WRITE_RETRIES = 3
RETRY_DELAY_MS = 50

# main.py passes STANDALONE=True; running from the IDE leaves it False (no watchdog)
STANDALONE = globals().get("STANDALONE", False)
IDE_STOP = "IDE interrupt"     # CanMV IDE stop is an Exception with this text: never treat it as an error


def retry(fn, *args):
    """/data occasionally rejects the first open in a fresh directory (EPERM); retry."""
    for attempt in range(WRITE_RETRIES):
        try:
            return fn(*args)
        except OSError:
            if attempt == WRITE_RETRIES - 1:
                raise
            time.sleep_ms(RETRY_DELAY_MS)


def write_file(path, data):
    with open(path, "wb") as f:
        f.write(data)


def new_session_dir():
    try:
        os.stat(CAPTURE_ROOT)
    except OSError:
        os.mkdir(CAPTURE_ROOT)
    last = 0
    for name in os.listdir(CAPTURE_ROOT):
        if name.startswith("s") and name[1:].isdigit():
            last = max(last, int(name[1:]))
    path = "%s/s%03d" % (CAPTURE_ROOT, last + 1)
    os.mkdir(path)
    return path


def free_mb():
    st = os.statvfs(CAPTURE_ROOT)  # (bsize, frsize, blocks, bfree, bavail, ...)
    return st[1] * st[4] // (1024 * 1024)


def init_io():
    fpioa = FPIOA()
    fpioa.set_function(KEY_PIN, FPIOA.GPIO0 + KEY_PIN)
    fpioa.set_function(LED_PIN, FPIOA.GPIO0 + LED_PIN)
    key = Pin(KEY_PIN, Pin.IN, Pin.PULL_UP)
    led = Pin(LED_PIN, Pin.OUT)
    led.value(0)
    return key, led


class Key:
    """KEY with press and release debounce. poll() returns "press", "long" (once per hold) or None."""

    def __init__(self, pin):
        self.pin = pin
        self.down = False
        self.down_at = 0
        self.up_since = None
        self.long_fired = False

    def pressed(self):
        return self.pin.value() == KEY_PRESSED

    def poll(self, now):
        if self.pressed():
            self.up_since = None
            if not self.down:
                time.sleep_ms(PRESS_DEBOUNCE_MS)
                if not self.pressed():
                    return None
                self.down, self.down_at, self.long_fired = True, now, False
                return "press"
            if not self.long_fired and time.ticks_diff(now, self.down_at) >= LONG_PRESS_MS:
                self.long_fired = True
                return "long"
            return None
        if self.down:
            # a hold ends only after the pin reads released for RELEASE_DEBOUNCE_MS
            if self.up_since is None:
                self.up_since = now
            elif time.ticks_diff(now, self.up_since) >= RELEASE_DEBOUNCE_MS:
                self.down = False
        return None

    def held(self):
        return self.down and not self.long_fired


class Log:
    def __init__(self, session_dir):
        self.rtc = RTC()
        self.f = retry(open, session_dir + "/log.csv", "a")
        self.f.write("file,ticks_ms,rtc,kind,info\n")

    def row(self, name, kind, info=""):
        stamp = "-".join(str(v) for v in self.rtc.datetime()[:7])
        self.f.write("%s,%d,%s,%s,%s\n" % (name, time.ticks_ms(), stamp, kind, info))
        self.f.flush()

    def close(self):
        self.f.close()


def new_stream_data():
    """fw 1.8 StreamData has room for 12 packs, but GetStream hands over every queued pack in one
    call (16-19 after a 0.6 s photo save) and then raises IndexError; make room for the whole queue."""
    sd = StreamData()
    for name in ("phy_addr", "data", "stream_type", "data_size", "pts"):
        setattr(sd, name, [0] * STREAM_PACKS_MAX)
    return sd


class Mp4Clip:
    """One MP4 file with one H.264 video track (kd_mp4_* API, as in examples/02-Media/mp4muxer.py)."""

    def __init__(self, path):
        cfg = k_mp4_config_s()
        cfg.config_type = K_MP4_CONFIG_MUXER
        cfg.muxer_config.file_name[:] = bytes(path, "utf-8")
        cfg.muxer_config.fmp4_flag = FMP4
        self.handle = retry(self._create, cfg)
        track = k_mp4_track_info_s()
        track.track_type = K_MP4_STREAM_VIDEO
        track.time_scale = 1000
        track.video_info.width = VIDEO_SIZE[0]
        track.video_info.height = VIDEO_SIZE[1]
        track.video_info.codec_id = K_MP4_CODEC_ID_H264
        track_handle = k_u64_ptr()
        self._check(kd_mp4_create_track(self.handle, track_handle, track), "kd_mp4_create_track")
        self.track = track_handle.value
        self.frame = k_mp4_frame_data_s()
        self.frames = 0
        self.bytes = 0
        self.started = time.ticks_ms()

    @staticmethod
    def _check(ret, what):
        if ret:
            raise OSError("%s failed (%d)" % (what, ret))

    def _create(self, cfg):
        handle = k_u64_ptr()
        self._check(kd_mp4_create(handle, cfg), "kd_mp4_create")
        return handle.value

    def write(self, addr, size, ts):
        self.frame.codec_id = K_MP4_CODEC_ID_H264
        self.frame.data = addr
        self.frame.data_length = size
        self.frame.time_stamp = ts
        self._check(kd_mp4_write_frame(self.handle, self.track, self.frame), "kd_mp4_write_frame")
        self.frames += 1
        self.bytes += size

    def close(self):
        kd_mp4_destroy_tracks(self.handle)
        kd_mp4_destroy(self.handle)


class Recorder:
    """Hardware H.264 encoder bound to sensor chn0. It runs from boot and its output is dropped while
    idle: on fw 1.8 a stopped venc channel cannot be started again, and a channel created after
    sensor.run() receives no frames."""

    def __init__(self, session_dir, log):
        self.dir = session_dir
        self.log = log
        self.encoder = Encoder()
        self.stream = new_stream_data()
        self.link = None
        self.created = False
        self.started = False
        self.recording = False
        self.clip = None
        self.clip_name = ""
        self.count = 0
        self.header = b""
        self.pts0 = 0
        self.keybuf = bytearray(KEYFRAME_BUF_BYTES)

    def setup(self, sensor):
        """Call before sensor.run()."""
        w, h = VIDEO_SIZE
        self.encoder.SetOutBufs(VENC_CHN, VENC_OUT_BUFS, w, h)
        self.link = MediaManager.link(sensor.bind_info(chn=CAM_CHN_ID_0)["src"],
                                      (VIDEO_ENCODE_MOD_ID, VENC_DEV_ID, VENC_CHN))
        attr = ChnAttrStr(self.encoder.PAYLOAD_TYPE_H264, self.encoder.H264_PROFILE_MAIN, w, h,
                          bit_rate=VIDEO_KBPS)
        self.encoder.Create(VENC_CHN, attr)
        self.created = True
        self.encoder.Start(VENC_CHN)
        self.started = True

    def start(self):
        """Recording begins at the next keyframe (header + IDR): requested now, else within 1 s (GOP 30)."""
        self.recording = True
        try:
            kd_mpi_venc_request_idr(VENC_CHN)
        except Exception as e:
            print("IDR request failed, waiting for the next GOP:", e)

    def stop(self, reason):
        self.recording = False
        self._end_clip(reason)

    def elapsed_ms(self):
        return time.ticks_diff(time.ticks_ms(), self.clip.started) if self.clip else 0

    def pump(self):
        """Drain every queued encoder packet; returns False if writing failed (recording stopped)."""
        ok = True
        while self.encoder.GetStream(VENC_CHN, self.stream, timeout=0) == 0:
            try:
                if ok:
                    self._handle_packs(self.stream)
            except Exception as e:
                if str(e) == IDE_STOP:
                    raise                            # a stop request, not a write failure
                print("recording failed:", e)
                self.stop("error")
                ok = False
            finally:
                self.encoder.ReleaseStream(VENC_CHN, self.stream)
        return ok

    def _handle_packs(self, sd):
        for i in range(sd.pack_cnt):
            kind, addr, size, pts = sd.stream_type[i], sd.data[i], sd.data_size[i], sd.pts[i]
            if kind == self.encoder.STREAM_TYPE_HEADER:
                self.header = bytes(uctypes.bytearray_at(addr, size))   # SPS/PPS, a few dozen bytes
            elif kind == self.encoder.STREAM_TYPE_I:
                self._on_keyframe(addr, size, pts)
            elif self.clip:
                self.clip.write(addr, size, pts - self.pts0)

    def _on_keyframe(self, addr, size, pts):
        """Every IDR is written as one sample with the SPS/PPS header in front: the first sample of
        a clip must be (mp4muxer.py), and without it decoders lose the PPS after the first GOP."""
        if not self.recording:
            return
        if self.clip and self.elapsed_ms() >= CLIP_MAX_MS:
            self._end_clip("split")
        n = len(self.header)
        if not n or n + size > len(self.keybuf):
            print("oversized keyframe: header", n, "bytes, IDR", size, "bytes")
            if self.clip:                        # keep the GOP; header as its own sample (as mp4muxer.py)
                if n:
                    self.clip.write(uctypes.addressof(self.header), n, pts - self.pts0)
                self.clip.write(addr, size, pts - self.pts0)
            return
        self.keybuf[:n] = self.header
        self.keybuf[n:n + size] = uctypes.bytearray_at(addr, size)
        if self.clip is None:
            self._begin_clip(pts)
        self.clip.write(uctypes.addressof(self.keybuf), n + size, pts - self.pts0)

    def _begin_clip(self, pts):
        self.count += 1
        self.clip_name = "vid_%04d.mp4" % self.count
        self.clip = Mp4Clip(self.dir + "/" + self.clip_name)
        self.pts0 = pts
        self.log.row(self.clip_name, "clip_start")
        print("recording", self.dir + "/" + self.clip_name)

    def _end_clip(self, reason):
        clip, self.clip = self.clip, None
        if clip is None:
            return
        ms = time.ticks_diff(time.ticks_ms(), clip.started)
        try:
            clip.close()
        except Exception as e:
            print("clip close failed:", e)
            reason += "+close_failed"
        info = "frames=%d ms=%d bytes=%d reason=%s" % (clip.frames, ms, clip.bytes, reason)
        self.log.row(self.clip_name, "clip_end", info)
        print("closed", self.clip_name, info)

    def teardown(self):
        """Call after sensor.stop() (order of mp4muxer.py): unlink, drain, stop, destroy."""
        self.stop("exit")
        self.link = None
        if self.started:
            while self.encoder.GetStream(VENC_CHN, self.stream, timeout=0) == 0:
                self.encoder.ReleaseStream(VENC_CHN, self.stream)
            self.encoder.Stop(VENC_CHN)
            self.started = False
        if self.created:
            self.encoder.Destroy(VENC_CHN)
            self.created = False


class Shutter:
    def __init__(self, session_dir, led, log):
        self.dir = session_dir
        self.led = led
        self.log = log
        self.count = 0

    def save(self, img):
        if free_mb() < MIN_FREE_MB:
            print("SD almost full, not saving")
            return False
        t0 = time.ticks_ms()
        self.led.value(1)
        self.count += 1
        name = "img_%04d.jpg" % self.count
        try:
            retry(write_file, self.dir + "/" + name, img.to_jpeg(quality=JPEG_QUALITY).bytearray())
            self.log.row(name, "photo")
            print("saved", self.dir + "/" + name, time.ticks_diff(time.ticks_ms(), t0), "ms")
            return True
        except Exception as e:
            self.count -= 1
            if str(e) == IDE_STOP:
                raise                                # a stop request, not a failed save
            print("save failed:", e)
            return False
        finally:
            self.led.value(0)
            gc.collect()


def create_sensor():
    """chn0 feeds the video encoder (4 KB aligned buffers, alignment=12 as in mp4muxer.py),
    chn1 is the photo frame (as v2 chn0), chn2 the IDE preview."""
    sensor = Sensor(fps=30)
    sensor.reset()
    sensor.set_framesize(w=VIDEO_SIZE[0], h=VIDEO_SIZE[1], chn=CAM_CHN_ID_0, alignment=12)
    sensor.set_pixformat(Sensor.YUV420SP, chn=CAM_CHN_ID_0)
    sensor.set_framesize(w=PHOTO_SIZE[0], h=PHOTO_SIZE[1], chn=CAM_CHN_ID_1)
    sensor.set_pixformat(Sensor.RGB888, chn=CAM_CHN_ID_1)
    sensor.set_framesize(w=PREVIEW_SIZE[0], h=PREVIEW_SIZE[1], chn=CAM_CHN_ID_2)
    sensor.set_pixformat(Sensor.RGB888, chn=CAM_CHN_ID_2)
    return sensor


def start_camera(sensor, recorder):
    recorder.setup(sensor)                       # the encoder must exist before sensor.run()
    Display.init(Display.VIRT, width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1], to_ide=True)
    sensor.run()


def cleanup(what, fn, *args):
    """Run one teardown step; report a failure and continue with the next step."""
    try:
        fn(*args)
    except Exception as e:
        print("cleanup", what, "failed:", e)


def led_level(now, alert, recording, held, last_beat):
    """LED level for this loop; saving a photo drives the LED directly (solid on)."""
    if alert:
        return (now // FAST_BLINK_MS) % 2
    if held:
        return 1
    if recording:
        return 1 if (now // REC_BLINK_MS) % 2 == 0 else 0
    return 1 if time.ticks_diff(now, last_beat) < HEARTBEAT_ON_MS else 0


def overlay(img, session, shutter, recorder):
    text = "%s  #%d" % (session.split("/")[-1], shutter.count)
    if recorder.recording:
        text += "  REC %s %ds" % (recorder.clip_name, recorder.elapsed_ms() // 1000)
    img.draw_string_advanced(8, 8, 28, text, color=(255, 0, 0) if recorder.recording else (255, 255, 0))


def toggle_recording(recorder):
    """Returns False when recording cannot start (SD almost full)."""
    if recorder.recording:
        recorder.stop("key")
        return True
    if free_mb() < MIN_FREE_MB:
        print("SD almost full, not recording")
        return False
    recorder.start()
    return True


def run_loop(sensor, key, led, session, shutter, recorder, wdt):
    last_beat = error_until = last_space_check = time.ticks_ms()
    low_space = free_mb() < MIN_FREE_MB
    while True:
        os.exitpoint()
        if wdt:
            wdt.feed()
        img_photo = sensor.snapshot(chn=CAM_CHN_ID_1)
        img_view = sensor.snapshot(chn=CAM_CHN_ID_2)
        ok = recorder.pump()
        now = time.ticks_ms()
        event = key.poll(now)
        if event == "press":
            recorder.pump()                      # empty the encoder queue before the ~0.5 s save
            ok = shutter.save(img_photo) and ok
        elif event == "long":
            ok = toggle_recording(recorder) and ok
        if not ok:
            error_until = time.ticks_add(now, ERROR_SHOW_MS)
        if time.ticks_diff(now, last_space_check) >= SPACE_CHECK_MS:
            last_space_check = now
            low_space = free_mb() < MIN_FREE_MB
            if low_space and recorder.recording:
                recorder.stop("low_space")
        if time.ticks_diff(now, last_beat) >= HEARTBEAT_MS:
            last_beat = now
        alert = time.ticks_diff(error_until, now) > 0 or low_space
        led.value(led_level(now, alert, recorder.recording, key.held(), last_beat))
        overlay(img_view, session, shutter, recorder)
        Display.show_image(img_view)


def main():
    if os.uname()[-1] != "k230_canmv_01studio":
        print("warning: KEY/LED pins are for 01Studio; board is", os.uname()[-1])
    key_pin, led = init_io()
    session = new_session_dir()
    print("session", session, "free MB", free_mb(), "standalone", STANDALONE)
    log = Log(session)
    recorder = Recorder(session, log)
    shutter = Shutter(session, led, log)
    sensor = create_sensor()
    wdt = None
    try:
        start_camera(sensor, recorder)
        wdt = WDT(1, WDT_TIMEOUT_S) if STANDALONE else None
        run_loop(sensor, Key(key_pin), led, session, shutter, recorder, wdt)
    except KeyboardInterrupt:
        print("stopped")
    except Exception as e:
        if str(e) != IDE_STOP:
            raise
        print("stopped by IDE")
    finally:
        led.value(0)
        cleanup("clip", recorder.stop, "exit")   # finalize the MP4 before anything else
        cleanup("log", log.close)
        if wdt:
            cleanup("wdt", wdt.close)
        os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
        cleanup("sensor", sensor.stop)
        cleanup("encoder", recorder.teardown)
        time.sleep_ms(50)
        cleanup("display", Display.deinit)
        cleanup("media", MediaManager.deinit)
        print("photos this session:", shutter.count, "clips:", recorder.count)


if __name__ == "__main__":
    main()
