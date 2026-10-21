"""Render every prompt in tools/voice_prompts.py to board/audio/<key>.wav.

The board (board/voice_v1.py) and the Mac bridge (tools/voice_bridge.py, afplay) play these files.
Per key: macOS `say -v VOICE -r RATE` -> afconvert to 16-bit PCM mono at the board rate
-> trim silence (keep LEAD_MS before / TAIL_MS after the speech), FADE_MS fades, peak ~-1 dBFS
-> rewrite with Python's wave module: clean 44-byte header (afconvert pads the header to 4 KB,
which the board's media.wave parser was never tested with).
Every key is rendered into a temp dir first; board/audio/ is only written when all succeeded.
Re-running regenerates everything. Any failure exits non-zero; nothing is skipped.

Usage: python3 tools/make_prompts.py              render every key (stdlib only; needs macOS say + afconvert)
       python3 tools/make_prompts.py --v2 KEY...  the same for tools/voice_prompts_v2.py (board/voice_v2.py)
       python3 tools/make_prompts.py scan_lr      render only the named keys; other WAVs stay untouched
"""
import array
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.normpath(os.path.join(HERE, "..", "board", "audio"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "board"))
import voice_prompts as VP  # noqa: E402  wording, voice, speaking rate
import voice_v1 as V  # noqa: E402  sample format the board player expects

VOICED_MIN = 300               # |sample| above this counts as speech (~-40 dBFS)
LEAD_MS = 20                   # silence kept before the first voiced sample
TAIL_MS = 150                  # kept after the last one; also separates back-to-back prompts
FADE_MS = 5
PEAK = 29000                   # ~-1 dBFS
HEADER_BYTES = 44
KEY_RE = re.compile(r"[a-z0-9_]+")


def shape(samples, rate):
    """Trim silence, fade both ends and normalize the peak. samples: array('h'); returns a new array."""
    voiced = [i for i, v in enumerate(samples) if abs(v) > VOICED_MIN]
    if not voiced:
        raise ValueError("no speech above the silence threshold")
    start = max(0, voiced[0] - LEAD_MS * rate // 1000)
    end = min(len(samples), voiced[-1] + 1 + TAIL_MS * rate // 1000)
    seg = samples[start:end]
    gain = PEAK / max(abs(v) for v in seg)
    fade = max(1, FADE_MS * rate // 1000)
    last = len(seg) - 1
    out = array.array("h")
    for i, v in enumerate(seg):
        k = min(1.0, i / fade, (last - i) / fade)
        out.append(max(-32768, min(32767, round(v * gain * k))))
    return out


def render(key, text, work_dir):
    """say -> afconvert -> shape -> clean WAV in work_dir. Returns (path, seconds, bytes)."""
    aiff = os.path.join(work_dir, key + ".aiff")
    raw = os.path.join(work_dir, key + "_raw.wav")
    path = os.path.join(work_dir, key + ".wav")
    subprocess.run(["say", "-v", VP.VOICE, "-r", str(VP.RATE), "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@%d" % V.RATE, "-c", str(V.CHANNELS),
                    aiff, raw], check=True)
    with wave.open(raw) as w:
        fmt = (w.getframerate(), w.getnchannels(), w.getsampwidth())
        if fmt != (V.RATE, V.CHANNELS, V.SAMPLE_WIDTH):
            raise RuntimeError("%s: afconvert gave %s" % (key, fmt))
        samples = array.array("h", w.readframes(w.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()             # WAV data is little-endian
    out = shape(samples, V.RATE)
    if sys.byteorder != "little":
        out.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(V.CHANNELS)
        w.setsampwidth(V.SAMPLE_WIDTH)
        w.setframerate(V.RATE)
        w.writeframes(out.tobytes())
    size = os.path.getsize(path)
    if size != HEADER_BYTES + len(out) * V.SAMPLE_WIDTH:
        raise RuntimeError("%s: unexpected WAV layout (%d bytes)" % (key, size))
    return path, len(out) / V.RATE, size


def main(keys=None):
    if V.SAMPLE_WIDTH != array.array("h").itemsize:
        raise RuntimeError("board sample width %d is not 16-bit" % V.SAMPLE_WIDTH)
    bad = [k for k in VP.PROMPTS if not KEY_RE.fullmatch(k)]
    if bad:
        raise RuntimeError("keys must be ASCII file names: %s" % bad)
    unknown = [k for k in keys or [] if k not in VP.PROMPTS]
    if unknown:
        raise RuntimeError("not in voice_prompts.PROMPTS: %s" % unknown)
    selected = {k: VP.PROMPTS[k] for k in keys} if keys else VP.PROMPTS
    rows = []
    with tempfile.TemporaryDirectory() as work_dir:
        for key, text in selected.items():
            rows.append((key, text) + render(key, text, work_dir))
        os.makedirs(AUDIO_DIR, exist_ok=True)
        for key, _, path, _, _ in rows:
            shutil.copyfile(path, os.path.join(AUDIO_DIR, key + ".wav"))

    print("voice %s, rate %d, %d Hz mono 16-bit -> %s" % (VP.VOICE, VP.RATE, V.RATE, AUDIO_DIR))
    print("%-18s %8s %8s  %s" % ("key", "seconds", "bytes", "text"))
    for key, text, _, seconds, size in rows:
        print("%-18s %8.3f %8d  %s" % (key, seconds, size, text))
    print("%-18s %8.3f %8d" % ("total (%d)" % len(rows), sum(r[3] for r in rows), sum(r[4] for r in rows)))
    extra = sorted(f for f in os.listdir(AUDIO_DIR) if f.endswith(".wav") and f[:-4] not in VP.PROMPTS)
    if extra:
        print("WARNING: not in voice_prompts.PROMPTS (left untouched): %s" % ", ".join(extra))


def use_v2():
    """--v2: render the speech keys of tools/voice_prompts_v2.py (board/voice_v2.py); its tones come from
    tools/make_tones_v1.py."""
    global VP
    import types
    import voice_prompts_v2 as VP2
    VP = types.SimpleNamespace(PROMPTS=VP2.SPEECH, VOICE=VP2.VOICE, RATE=VP2.RATE)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--v2" in args:
        args.remove("--v2")
        use_v2()
    main(args)
