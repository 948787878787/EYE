# Black box v1: per-frame telemetry of the reader, tamper-evident (pure logic + a lazy writer; CPython tests in
# tests/test_blackbox_v1.py, PC check tools/verify_blackbox.py). User 2026-10-14.
# - No images, only numbers: what the reader saw and said on every frame (no faces, no plates).
# - Lines are kept in RAM and written FLUSH_LINES at a time to /data/blackbox/sNNN/telemetry.csv; never while GREEN /
#   GREEN_FLASH is shown unless the buffer reaches MAX_LINES (a write must not stall the loop during a green).
# - Each written chunk is followed by "#chain,<n>,<sha256(previous digest + chunk)>": editing, dropping or reordering
#   any earlier line breaks every later digest. This shows the file was not edited after the fact; it is a record of
#   what the device did, not proof that it was right (a wrong announcement is recorded just as faithfully).
# - Any write error disables the black box (logged once); the reader never stops for it.
try:
    import hashlib
except ImportError:            # some MicroPython ports
    import uhashlib as hashlib
try:
    from binascii import hexlify
except ImportError:
    from ubinascii import hexlify

ROOT = "/data/blackbox"
FLUSH_LINES = 100              # ~7 s at 14 fps
MAX_LINES = 400                # flush even during a green past this (RAM bound, ~40 KB)
MIN_FREE_MB = 200
GENESIS = "k230-blackbox-v1"
HEADER = ("t_ms,frame,state,label,p_red,p_green,p_other,det,box_x,box_y,box_w,box_h,blocked,vetoed,fault,said,"
          "exp_us,gain,mean,spread\n")
GREENISH = ("GREEN", "GREEN_FLASHING", "GREEN_FLASH")


def digest(prev_hex, chunk):
    h = hashlib.sha256()
    h.update((prev_hex + chunk).encode())
    return hexlify(h.digest()).decode()


def _f(v, fmt="%.3f"):
    return "" if v is None else fmt % v


def line(t, n, state, label, probs, sig, blocked, vetoed, fault, said, exp_us, gain, mean, spread):
    """One CSV line; probs: dict or None; sig: (x, y, w, h, score) window px or None; said: list of keys."""
    p = probs or {}
    box = ("%d,%d,%d,%d" % (sig[0], sig[1], sig[2], sig[3])) if sig else ",,,"
    return "%d,%d,%s,%s,%s,%s,%s,%s,%s,%d,%d,%s,%s,%s,%s,%d,%d\n" % (
        t, n, state, label or "", _f(p.get("red")), _f(p.get("green")), _f(p.get("other")),
        _f(sig[4] if sig else None), box, 1 if blocked else 0, 1 if vetoed else 0, fault or "",
        "+".join(said), _f(exp_us, "%d"), _f(gain, "%.2f"), mean, spread)


class Chain:
    """Pure: buffered lines -> chunks with chain records."""

    def __init__(self):
        self.buf = []
        self.prev = digest("", GENESIS)
        self.chunks = 0

    def add(self, text):
        self.buf.append(text)

    def due(self, state):
        n = len(self.buf)
        return n >= MAX_LINES or (n >= FLUSH_LINES and state not in GREENISH)

    def take(self):
        """The text to write now: the buffered lines + their chain record; empties the buffer."""
        chunk = "".join(self.buf)
        self.buf = []
        self.chunks += 1
        self.prev = digest(self.prev, chunk)
        return chunk + "#chain,%d,%s\n" % (self.chunks, self.prev)


def _sync():
    """os.sync() where the port has it (closing the file already flushed Python's buffer)."""
    try:
        import os
        os.sync()
    except (ImportError, AttributeError):
        pass
    except OSError as e:
        print("blackbox sync failed:", e)


class BlackBox:
    def __init__(self, root=ROOT):
        self.root = root
        self.chain = Chain()
        self.path = None
        self.ok = True

    def record(self, state, *fields):
        """fields as line() after state is put in; writes when due. Never raises (except the IDE stop)."""
        if not self.ok:
            return
        self.chain.add(line(fields[0], fields[1], state, *fields[2:]))
        if self.chain.due(state):
            self.flush()

    def flush(self):
        if not self.ok or not self.chain.buf:
            return
        try:
            self._ensure()
            with open(self.path, "a") as fh:
                fh.write(self.chain.take())
            _sync()                                  # a pulled power bank must not lose the written chunk
        except Exception as e:
            if str(e) == "IDE interrupt":
                raise
            print("blackbox disabled:", e)
            self.ok = False

    def _ensure(self):
        if self.path is not None:
            return
        import os
        from hardcase_v1 import mkdir_if_missing, next_session_name, free_mb
        mkdir_if_missing(self.root)
        if free_mb(self.root) < MIN_FREE_MB:
            raise OSError("card almost full")
        d = self.root + "/" + next_session_name(os.listdir(self.root))
        os.mkdir(d)
        self.path = d + "/telemetry.csv"
        with open(self.path, "w") as fh:
            fh.write("#genesis,%s\n" % GENESIS + HEADER)
        print("blackbox", self.path)
