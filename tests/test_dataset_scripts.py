"""dataset/script: crosswalk CSV -> YOLO-pose conversion."""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dataset", "script"))
import crosswalk_csv_to_yolo as C  # noqa: E402

CSV = os.path.join(os.path.dirname(__file__), "..", "dataset", "crosswalk_tw", "crosswalk_tw_v1.csv")


def test_label_line_box_and_keypoints():
    parts = C.label_line((0.5, 1.0), (0.5, 0.5)).split()
    assert parts[0] == "0" and len(parts) == 11
    assert parts[5:7] == ["0.500000", "1.000000"] and parts[8:10] == ["0.500000", "0.500000"]
    assert parts[7] == "2" and parts[10] == "2"


def test_csv_is_consistent():
    rows = list(csv.DictReader(open(CSV)))
    assert {r["split"] for r in rows} == {"train", "valid"}
    assert {r["class"] for r in rows} == {"ahead", "none", "unsure"}
    for r in rows:
        coords = [r[k] for k in ("near_x", "near_y", "far_x", "far_y")]
        if r["class"] == "ahead":
            assert all(0.0 <= float(v) <= 1.0 for v in coords), r
        else:
            assert coords == ["", "", "", ""], r
    assert len({r["image_stem"] for r in rows}) == len(rows)


def test_convert_writes_labels_and_negatives(tmp_path):
    img_root = tmp_path / "rf"
    (img_root / "train" / "images").mkdir(parents=True)
    for stem in ("a", "b", "c"):
        (img_root / "train" / "images" / f"{stem}.jpg").write_bytes(b"x")
    table = tmp_path / "t.csv"
    table.write_text("split,image_stem,class,near_x,near_y,far_x,far_y\n"
                     "train,a,ahead,0.5,1.0,0.5,0.5\ntrain,b,none,,,,\ntrain,c,unsure,,,,\nvalid,zz,none,,,,\n")
    counts, missing = C.convert(str(img_root), str(tmp_path / "out"), str(table))
    assert counts == {("train", "ahead"): 1, ("train", "none"): 1} and missing == 1
    assert (tmp_path / "out" / "train" / "labels" / "a.txt").read_text().startswith("0 ")
    assert (tmp_path / "out" / "train" / "labels" / "b.txt").read_text() == ""
