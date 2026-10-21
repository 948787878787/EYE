"""board/hardcase_v2.py: crop-only hard cases (privacy): crop geometry and the no-box path."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import hardcase_v2 as H  # noqa: E402

W, H_ = 1536, 864


def test_crop_is_a_square_of_the_classifier_context():
    x0, y0, x1, y1 = H.crop_rect((700, 300, 30, 57), W, H_)
    assert x1 - x0 == y1 - y0 == int(57 * H.CONTEXT)
    assert x0 <= 700 and x1 >= 730 and y0 <= 300 and y1 >= 357


def test_tiny_box_gets_the_minimum_side_and_stays_inside():
    for box in ((0, 0, 4, 8), (W - 5, H_ - 9, 4, 8), (760, 400, 4, 8)):
        x0, y0, x1, y1 = H.crop_rect(box, W, H_)
        assert x1 - x0 == H.MIN_SIDE and 0 <= x0 and x1 <= W and 0 <= y0 and y1 <= H_


def test_crop_never_exceeds_the_image():
    x0, y0, x1, y1 = H.crop_rect((0, 0, 2000, 2000), W, H_)
    assert (x1 - x0, y1 - y0) == (H_, H_) and x1 <= W


@pytest.mark.parametrize("box", [(700, 300, 30, 57), (0, 0, 10, 20), (1500, 840, 30, 20)])
def test_crop_is_a_small_fraction_of_the_frame(box):
    x0, y0, x1, y1 = H.crop_rect(box, W, H_)
    assert (x1 - x0) * (y1 - y0) < 0.01 * W * H_


class FakeImg:
    def width(self):
        return W

    def height(self):
        return H_


def test_no_box_logs_a_record_without_an_image(tmp_path, monkeypatch):
    w = H.CropHardCaseWriter(root=str(tmp_path))
    monkeypatch.setattr(w, "_ensure_session", lambda: None)
    monkeypatch.setattr(H, "free_mb", lambda root: 10_000)
    written = []
    monkeypatch.setattr(H, "write_retry", lambda path, data: written.append(path))

    class Log(list):
        def write(self, s):
            self.append(s)

        def flush(self):
            pass
    w.log, w.dir = Log(), str(tmp_path)
    assert w.save(FakeImg(), 1000, "stuck", "UNKNOWN", "unk", None, False, None)
    assert written == [] and w.log[0].startswith(",1000,stuck")
