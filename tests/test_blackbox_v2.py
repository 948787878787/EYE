"""board/blackbox_v2.py: v1 line + crosswalk shadow columns, own genesis, same verifier."""
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "board"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import blackbox_v1 as B1  # noqa: E402
import blackbox_v2 as B  # noqa: E402
import verify_blackbox as V  # noqa: E402

PROBS = {"red": 0.05, "green": 0.91, "other": 0.04}
SIG = (500, 200, 20, 38, 0.87)
ARGS = (1000, 1, "GREEN", "green", PROBS, SIG, False, False, None, ["green"], 8000, 1.5, 55, 90)


def test_line_extends_v1_and_matches_header():
    x = B.line(*ARGS, found=(0.61, (700.4, 570.0), (480.0, 300.6)), owned=((480.0, 300.0), 31.0),
               shadow_label="unk", shadow_note="not-on-crossing")
    v1 = B1.line(*ARGS)
    assert x.startswith(v1[:-1] + ",")
    assert x.count(",") == B.HEADER.count(",")
    assert x.endswith(",0.610,700,570,480,300,480,31,unk,not-on-crossing\n")


def test_line_without_crosswalk_run_has_empty_shadow_columns():
    x = B.line(*ARGS)
    assert x.count(",") == B.HEADER.count(",")
    assert x.endswith(",,,,,,,,,\n")


def test_record_and_verify_chain(tmp_path, monkeypatch):
    bb = B.BlackBox(root=str(tmp_path))
    bb.path = str(tmp_path / "telemetry.csv")
    with open(bb.path, "w") as fh:
        fh.write("#genesis,%s\n" % B.GENESIS + B.HEADER)
    for i in range(3):
        bb.record("RED", 1000 + i, i, "red", PROBS, SIG, False, False, None, [], None, None, 50, 80,
                  found=(0.5, (1, 2), (3, 4)), owned=None, shadow_label="red", shadow_note="")
    bb.flush()
    ok, chunks, frames, msg = V.verify(open(bb.path).read())
    assert ok and chunks == 1 and frames == 3, msg


def test_v2_genesis_differs_from_v1():
    assert B.GENESIS != B1.GENESIS
    assert B.BlackBox(root="/nonexistent").chain.prev == B.digest("", B.GENESIS)
