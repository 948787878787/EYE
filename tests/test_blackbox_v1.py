"""board/blackbox_v1.py + tools/verify_blackbox.py: telemetry lines, flush policy, tamper-evident chain."""
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "board"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import blackbox_v1 as B  # noqa: E402
import verify_blackbox as V  # noqa: E402

PROBS = {"red": 0.91, "green": 0.05, "other": 0.04}
SIG = (500, 200, 20, 38, 0.87)


def a_line(t=1000, n=1, state="RED", said=("red",)):
    return B.line(t, n, state, "red", PROBS, SIG, False, False, None, list(said), 8000, 1.5, 55, 90)


def test_line_has_every_header_field_and_no_image_data():
    x = a_line()
    assert x.count(",") == B.HEADER.count(",")
    assert x.startswith("1000,1,RED,red,0.910,0.050,0.040,0.870,500,200,20,38,0,0,,red,8000,1.50,55,90")


def test_line_without_detection_or_probs():
    x = B.line(5, 2, "UNKNOWN", None, None, None, False, False, "camera_dark", [], None, None, 3, 1)
    assert x == "5,2,UNKNOWN,,,,,,,,,,0,0,camera_dark,,,,3,1\n"


def test_flush_waits_while_green_until_the_ram_bound():
    c = B.Chain()
    for i in range(B.FLUSH_LINES):
        c.add(a_line(n=i))
    assert c.due("RED") and not c.due("GREEN") and not c.due("GREEN_FLASHING")
    for i in range(B.MAX_LINES - B.FLUSH_LINES):
        c.add(a_line(n=i))
    assert c.due("GREEN")


def file_text(chunks=3, per=5):
    c = B.Chain()
    out = "#genesis,%s\n" % B.GENESIS + B.HEADER
    for k in range(chunks):
        for i in range(per):
            c.add(a_line(t=k * 100 + i, n=k * per + i))
        out += c.take()
    return out


def test_verify_accepts_an_untouched_file():
    ok, chunks, frames, msg = V.verify(file_text())
    assert ok and chunks == 3 and frames == 15 and msg == "OK"


def test_verify_reports_an_unflushed_tail():
    ok, _, _, msg = V.verify(file_text() + a_line(t=9999))
    assert ok and "1 trailing lines unverified" in msg


def test_editing_one_value_breaks_the_chain():
    text = file_text().replace(",red,0.910", ",green,0.910", 1)      # one label rewritten
    ok, chunks, _, msg = V.verify(text)
    assert not ok and chunks == 0 and "chunk 1" in msg


def test_dropping_a_line_or_a_chunk_breaks_the_chain():
    lines = file_text().splitlines(keepends=True)
    assert not V.verify("".join(lines[:5] + lines[6:]))[0]                # one telemetry line gone
    chain_rows = [i for i, x in enumerate(lines) if x.startswith("#chain,")]
    first_end = chain_rows[0] + 1
    assert not V.verify("".join(lines[:2] + lines[first_end:]))[0]        # the whole first chunk gone


def test_a_write_error_disables_without_raising(tmp_path):
    bb = B.BlackBox(root=str(tmp_path / "missing" / "deeper"))
    bb.path = str(tmp_path / "missing" / "deeper" / "telemetry.csv")     # parent does not exist: open fails
    for i in range(B.FLUSH_LINES):
        bb.record("RED", i, i, "red", PROBS, SIG, False, False, None, [], 1, 1.0, 50, 50)
    assert bb.ok is False


def test_power_loss_in_the_middle_of_a_line_is_not_tampering():
    text = file_text()
    for cut in (text[:-20], text + "123,4,RE"):                          # inside a chain record / a telemetry line
        ok, _, _, msg = V.verify(cut)
        assert ok and "cut off by a power loss" in msg
    ok, chunks, _, _ = V.verify(text[:-20])
    assert chunks == 2                                                   # the cut chunk is unverified, not counted
