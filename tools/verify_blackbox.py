"""Check a black box file (board/blackbox_v1.py) on the PC: every "#chain" digest must follow from the lines before it.
Prints OK with the number of chunks and frames, or the first chunk that does not match (edited, dropped or reordered
lines). Lines after the last chain record (power cut before a flush) are reported as unverified; a last line without
its newline (power cut in the middle of a write, even of a chain record) is reported as cut off, not as tampering.
Usage: python3 tools/verify_blackbox.py /path/to/telemetry.csv
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board"))

import blackbox_v1 as B  # noqa: E402


def verify(text):
    """(ok, chunks, frames, message)."""
    lines = text.splitlines(keepends=True)
    cut = ""
    if lines and not lines[-1].endswith("\n"):        # power lost mid-write: the last line is incomplete
        lines, cut = lines[:-1], " (last line cut off by a power loss)"
    if not lines or not lines[0].startswith("#genesis,"):
        return False, 0, 0, "no genesis line"
    prev = B.digest("", lines[0].strip().split(",", 1)[1])
    body = [x for x in lines[1:] if not x.startswith("t_ms,")]        # header
    chunk, chunks, frames = [], 0, 0
    for x in body:
        if x.startswith("#chain,"):
            _, n, hexd = x.strip().split(",")
            prev = B.digest(prev, "".join(chunk))
            chunks += 1
            if int(n) != chunks or hexd != prev:
                return False, chunks - 1, frames, "chunk %d does not match: edited, dropped or reordered" % chunks
            frames += len(chunk)
            chunk = []
        else:
            chunk.append(x)
    tail = " (%d trailing lines unverified)" % len(chunk) if chunk else ""
    return True, chunks, frames, "OK" + tail + cut


def main(argv=None):
    path = (argv or sys.argv[1:])[0]
    ok, chunks, frames, msg = verify(open(path, encoding="utf-8").read())
    print("%s: %s, %d chunks, %d frames" % (path, msg, chunks, frames))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
