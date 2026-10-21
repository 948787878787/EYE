# Prompt player v2 (user 2026-10-14, architecture review A9/A10): voice_v1 + three fail-safe additions; v1 unchanged.
#   1. New keys: heartbeat tones tick / tick_fast (guide_v2), faults camera_dark / camera_blocked / slow (health_v1),
#      stalled. Wording: tools/voice_prompts_v2.py; tones: tools/make_tones_v1.py.
#   2. Self-test: every REQUIRED prompt must load and the output must open, else Voice.ok is False and
#      Voice.missing lists what failed; the reader then refuses to start (no "ready" = do not use it).
#   3. Stall watchdog in the writer thread, independent of the detection loop: the loop calls alive() every frame; if
#      it has not for STALL_MS, the writer itself plays "stalled" every STALL_REPEAT_MS (no heartbeat ticks can come
#      from a dead loop, and the user hears why).
# Prompt player for the pedestrian signal reader (CanMV K230 fw v1.8, 01Studio 3.5 mm audio jack).
# Plays /sdcard/ped_light/audio/<key>.wav: 16 kHz mono 16-bit PCM rendered on the Mac by
# tools/make_prompts.py from tools/voice_prompts.py (single source of wording; the Mac bridge
# tools/voice_bridge.py plays the same files). No speech policy here: board/guide_v1.py decides
# what to say and when; this module only plays keys by priority.
# Playback API as in the official example 02-Media/audio.py play_audio(): media.wave reads the WAV,
# PyAudio().open(output=True) + stream.write(chunk) plays it, stop_stream/close/terminate release it.
# stream.write() is paced by the audio hardware (audio.py pushes a whole file with back-to-back
# writes), so playing inside the detection loop blocks it for about the prompt length minus
# LEAD_MS (0.7-2.6 s, durations in the make_prompts.py table).
# Default: one persistent output stream fed by a _thread writer (pattern of 26-xiaozhi/audio_manager.py)
# that keeps at most LEAD_MS + CHUNK_MS queued, so say() returns at once and write() should rarely
# wait (the driver's buffer depth is undocumented: verify on the board). THREADED = False plays
# inside say(). Pure logic (PromptPolicy, Player) runs on CPython (tests/test_voice.py).
# Any audio failure is logged once and turns Voice into a no-op: the detector keeps running.
#
# Board script usage (audio before the camera: the order 26-xiaozhi uses):
#     voice = Voice()
#     voice.say("ready")
#     per frame:   for key in guide.update(now, state, ...): voice.say(key, now)
#     on a crash:  voice.say("error"); voice.close(wait_ms=3000)       finally: voice.close()
try:
    from time import ticks_ms, ticks_diff, ticks_add, sleep_ms
except ImportError:            # CPython (tests)
    import time as _time

    def ticks_ms():
        return int(_time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

    def ticks_add(a, b):
        return a + b

    def sleep_ms(ms):
        _time.sleep(ms / 1000)

AUDIO_DIR = "/sdcard/ped_light/audio"
RATE = 16000                   # every prompt WAV: 16 kHz, mono, 16-bit
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK_MS = 100                 # audio per stream.write() (02-Media/audio.py: 40 ms, tts_zh.py: 300 ms)
CHUNK_FRAMES = RATE * CHUNK_MS // 1000
CHUNK_BYTES = CHUNK_FRAMES * CHANNELS * SAMPLE_WIDTH
LEAD_MS = 200                  # audio kept queued ahead of the speaker: rides out main-loop stalls
PACE_MS = 20                   # writer sleep while nothing is due
VOLUME = 85                    # 0-100, value of 02-Media/audio.py; raise for street noise
THREADED = True                # False: prompts play inside say() (blocks for about their length)
CLOSE_WAIT_MS = 500
IDE_STOP = "IDE interrupt"     # CanMV IDE stop is an Exception with this text: never swallow it

# Same keys as tools/voice_prompts.PROMPTS (the board cannot import tools/; tests check they match).
PROMPTS = ("red", "green", "green_flash", "unknown", "unclear", "turn_left", "turn_right", "scan",
           "scan_lr", "found", "obstacle_vehicle", "obstacle_person", "ready", "error",
           "tick", "tick_fast", "camera_dark", "camera_blocked", "slow", "stalled", "aligned")
# The reader may not start without these: colours, the withdrawal, heartbeat, every fault, start and error.
REQUIRED = ("red", "green", "green_flash", "unknown", "tick", "tick_fast", "camera_dark", "camera_blocked", "slow",
            "stalled", "ready", "error")
STALL_MS = 2000                # detection loop silent this long -> "stalled" from the writer thread
STALL_REPEAT_MS = 4000
# A prompt >= INTERRUPT_PRIORITY cuts short a playing prompt of lower or equal priority (the newest
# signal information wins, as the PREEMPT keys in tools/voice_bridge.py); the playing key itself is
# never restarted. Any other request while busy is refused: say() returns False, nothing is queued.
PRIORITY = {"error": 4, "stalled": 4,
            "red": 3, "green": 3, "green_flash": 3, "unknown": 3, "obstacle_vehicle": 3,
            "camera_dark": 3, "camera_blocked": 3, "slow": 3,
            "tick": 0, "tick_fast": 0, "aligned": 1,
            "unclear": 1, "turn_left": 1, "turn_right": 1, "scan": 1, "scan_lr": 1, "found": 1,
            "obstacle_person": 1, "ready": 1}
INTERRUPT_PRIORITY = 3
# Event prompts no other module rate-limits; guide_v1 keys follow guide_v1's own cooldowns only.
COOLDOWN_PROMPTS = ("obstacle_vehicle", "obstacle_person", "ready", "error")
COOLDOWN_MS = 4000             # an event prompt is not repeated within this time

# PromptPolicy.decide() results
PLAY, INTERRUPT, BUSY, COOLDOWN, MISSING = "play", "interrupt", "busy", "cooldown", "missing"


def split_chunks(pcm, chunk_bytes):
    """Cut PCM into writes of exactly chunk_bytes, zero-padding the last one
    (an AO write must be exactly one period: 26-xiaozhi/audio_manager.py play_audio_data)."""
    chunks = []
    for i in range(0, len(pcm), chunk_bytes):
        chunk = pcm[i:i + chunk_bytes]
        if len(chunk) < chunk_bytes:
            chunk = chunk + bytes(chunk_bytes - len(chunk))
        chunks.append(chunk)
    return chunks


def load_clip(wave, path):
    """Read one prompt with the media.wave calls of 02-Media/audio.py; returns its chunks."""
    wf = wave.open(path, "rb")
    try:
        fmt = (wf.get_framerate(), wf.get_channels(), wf.get_sampwidth())
        if fmt != (RATE, CHANNELS, SAMPLE_WIDTH):
            raise ValueError("format %s, need %s" % (fmt, (RATE, CHANNELS, SAMPLE_WIDTH)))
        parts = []
        data = wf.read_frames(CHUNK_FRAMES)
        while data:
            parts.append(data)
            data = wf.read_frames(CHUNK_FRAMES)
    finally:
        wf.close()
    chunks = split_chunks(b"".join(parts), CHUNK_BYTES)
    if not chunks:
        raise ValueError("no audio frames")
    return chunks


class PromptPolicy:
    """Priority, interrupt and event cooldown rules; no audio."""

    def __init__(self, available=PROMPTS):
        self.available = set(available)
        self.last_start = {}           # prompt key -> ticks_ms it last started

    def decide(self, name, now, playing):
        """playing: key being played or None."""
        if name not in self.available or name not in PRIORITY:
            return MISSING
        last = self.last_start.get(name)
        if name in COOLDOWN_PROMPTS and last is not None and ticks_diff(now, last) < COOLDOWN_MS:
            return COOLDOWN
        if playing is None:
            return PLAY
        if name != playing and PRIORITY[name] >= INTERRUPT_PRIORITY and PRIORITY[name] >= PRIORITY[playing]:
            return INTERRUPT
        return BUSY

    def started(self, name, now):
        self.last_start[name] = now


class Player:
    """What the audio output plays next: current prompt, chunk position and write pacing.
    request() runs in the detection loop, next_chunk() in the writer; Voice holds a lock around both."""

    def __init__(self, clips):
        self.clips = clips             # prompt key -> list of CHUNK_BYTES pieces
        self.policy = PromptPolicy(clips)
        self.playing = None
        self.pos = 0
        self.queued_until = None       # ticks_ms when the audio written so far runs out

    def request(self, name, now):
        decision = self.policy.decide(name, now, self.playing)
        if decision == PLAY or decision == INTERRUPT:
            self.playing, self.pos = name, 0   # an interrupted prompt stops after its queued chunks
            self.policy.started(name, now)
        return decision

    def next_chunk(self, now):
        """Chunk to write now, or None when idle or LEAD_MS is already queued (a write would block)."""
        if self.playing is None:
            return None
        ahead = 0 if self.queued_until is None else ticks_diff(self.queued_until, now)
        if ahead < 0 or ahead > LEAD_MS + CHUNK_MS:
            ahead = 0                  # output ran dry (or the tick counter wrapped)
        if ahead > LEAD_MS:
            return None
        chunks = self.clips[self.playing]
        chunk = chunks[self.pos]
        self.pos += 1
        if self.pos >= len(chunks):
            self.playing = None
        self.queued_until = ticks_add(now, ahead + CHUNK_MS)
        return chunk


class StallWatch:
    """Writer-thread side of the stall watchdog (pure): due(now) is True when the loop has not called alive() for
    STALL_MS and "stalled" was not played in the last STALL_REPEAT_MS. Nothing fires before the first alive()."""

    def __init__(self):
        self.alive_at = None
        self.said_at = None

    def alive(self, now):
        self.alive_at = now

    def due(self, now):
        if self.alive_at is None or ticks_diff(now, self.alive_at) < STALL_MS:
            return False
        if self.said_at is not None and ticks_diff(now, self.said_at) < STALL_REPEAT_MS:
            return False
        self.said_at = now
        return True


class _NoLock:
    """Stand-in for the _thread lock when prompts play in the caller."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Voice:
    """Board audio output. Audio errors never propagate: logged once, then every call is a no-op."""

    def __init__(self, audio_dir=AUDIO_DIR, threaded=THREADED, volume=VOLUME):
        self.ok = False
        self.failed = False
        self.threaded = False
        self.running = False           # writer thread alive
        self.stopping = False
        self.lock = _NoLock()
        self.player = Player({})
        self.p = self.stream = None
        self.missing = list(REQUIRED)      # self-test result: REQUIRED prompts that did not load
        self.watch = StallWatch()
        try:
            self._open(audio_dir, volume)
        except Exception as e:
            if str(e) == IDE_STOP:
                raise
            self._fail("init", e)
            self._release()
            return
        self.ok = True
        if threaded:
            self._start_writer()

    def self_test_ok(self):
        """True only if the output opened and every REQUIRED prompt loaded (the reader must not start otherwise)."""
        return self.ok and not self.missing

    def alive(self, now=None):
        """Detection loop heartbeat for the writer's stall watchdog; call once per frame."""
        self.watch.alive(ticks_ms() if now is None else now)

    def _open(self, audio_dir, volume):
        import media.media         # noqa: F401  as in 02-Media/audio.py (media buffers)
        from media.pyaudio import PyAudio, paInt16
        import media.wave as wave
        clips = {}
        for name in PROMPTS:
            try:
                clips[name] = load_clip(wave, audio_dir + "/" + name + ".wav")
            except Exception as e:
                if str(e) == IDE_STOP:
                    raise
                print("VOICE prompt %s unusable: %s" % (name, e))
        self.missing = [k for k in REQUIRED if k not in clips]
        if not clips:
            raise OSError("no usable prompts in " + audio_dir)
        self.player = Player(clips)
        self.p = PyAudio()
        self.stream = self.p.open(format=paInt16, channels=CHANNELS, rate=RATE, output=True,
                                  frames_per_buffer=CHUNK_FRAMES)
        self.stream.volume(vol=volume)

    def _start_writer(self):
        try:
            import _thread
            self.lock = _thread.allocate_lock()
            self.running = self.threaded = True
            _thread.start_new_thread(self._writer, ())
        except Exception as e:
            if str(e) == IDE_STOP:
                raise
            self.lock, self.running, self.threaded = _NoLock(), False, False
            print("VOICE no writer thread, prompts will block: %s" % e)

    def _fail(self, where, e):
        if not self.failed:
            print("VOICE disabled (%s): %s" % (where, e))
        self.failed = True
        self.ok = False

    def say(self, name, now=None):
        """Play a prompt key now. False when refused: an equal/higher-priority prompt is playing
        (see PRIORITY), an event prompt is in its cooldown, the WAV is missing, or audio is off."""
        if not self.ok:
            return False
        now = ticks_ms() if now is None else now
        with self.lock:
            decision = self.player.request(name, now)
        if decision == PLAY and not self.threaded:
            self._drain()
        return self.ok and (decision == PLAY or decision == INTERRUPT)

    def _pump(self):
        """One playback step: write the next chunk if it is due, else sleep PACE_MS."""
        with self.lock:
            chunk = self.player.next_chunk(ticks_ms())
        if chunk is None:
            sleep_ms(PACE_MS)
            return
        ret = self.stream.write(chunk)
        if isinstance(ret, int) and ret < 0:
            raise OSError("stream.write returned %d" % ret)

    def _writer(self):
        try:
            while not self.stopping:
                now = ticks_ms()
                if self.watch.due(now):
                    with self.lock:
                        self.player.request("stalled", now)
                    print("VOICE stalled: no frame for %d ms" % ticks_diff(now, self.watch.alive_at))
                self._pump()
        except Exception as e:
            self._fail("playback", e)
        self.running = False

    def _drain(self):
        """Blocking mode: returns once the last chunk is written (prompt length - LEAD_MS)."""
        try:
            while self.player.playing is not None:
                self._pump()
        except Exception as e:
            if str(e) == IDE_STOP:
                raise
            self._fail("playback", e)

    def wait_idle(self, timeout_ms):
        """Wait until the current prompt is fully written; True if it was."""
        t0 = ticks_ms()
        while self.ok and self.player.playing is not None and ticks_diff(ticks_ms(), t0) < timeout_ms:
            sleep_ms(PACE_MS)
        return self.player.playing is None

    def close(self, wait_ms=0):
        """Release the audio device; wait_ms > 0 first lets the current prompt finish (e.g. "error")."""
        if self.ok and wait_ms > 0 and self.wait_idle(wait_ms):
            sleep_ms(LEAD_MS + CHUNK_MS)   # the last chunks are still in the output buffer
        self.ok = False
        self.stopping = True
        t0 = ticks_ms()
        while self.running and ticks_diff(ticks_ms(), t0) < CLOSE_WAIT_MS:
            sleep_ms(PACE_MS)
        self._release()

    def _release(self):
        """Teardown in the order of 02-Media/audio.py play_audio()."""
        for obj, method in ((self.stream, "stop_stream"), (self.stream, "close"), (self.p, "terminate")):
            if obj is None:
                continue
            try:
                getattr(obj, method)()
            except Exception as e:
                print("VOICE %s failed: %s" % (method, e))
        self.stream = self.p = None
