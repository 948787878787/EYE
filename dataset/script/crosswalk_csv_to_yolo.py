"""Turn dataset/crosswalk_tw/crosswalk_tw_v1.csv into a YOLO-pose dataset (1 class, 2 keypoints: near end, far end of
the crossing midline) on the photos downloaded by download_roboflow.py.
  ahead  -> one label line; box = midline extent + 10% of its length (at least 5% of the image), as ImVisible
  none   -> empty label file (negative: no crossing the user would walk on)
  unsure -> skipped
Images are linked (not copied). Splits follow the CSV's split column (EYE's leak-free split, not Roboflow's).
Usage: python dataset/script/crosswalk_csv_to_yolo.py --images data/roboflow_v1 --out data/crosswalk_tw_pose
"""
import argparse
import csv
import glob
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "crosswalk_tw", "crosswalk_tw_v1.csv")
MARGIN, MIN_BOX = 0.10, 0.05


def _span(lo, hi, pad, min_len):
    lo, hi = lo - pad, hi + pad
    if hi - lo < min_len:
        mid = (lo + hi) / 2.0
        lo, hi = mid - min_len / 2.0, mid + min_len / 2.0
    lo, hi = max(0.0, lo), min(1.0, hi)
    return (lo + hi) / 2.0, hi - lo


def label_line(near, far):
    """YOLO-pose line in normalised units; both keypoints visible (2)."""
    pad = MARGIN * math.dist(near, far)
    cx, bw = _span(min(near[0], far[0]), max(near[0], far[0]), pad, MIN_BOX)
    cy, bh = _span(min(near[1], far[1]), max(near[1], far[1]), pad, MIN_BOX)
    c = lambda v: min(1.0, max(0.0, v))  # noqa: E731
    vals = [cx, cy, bw, bh, c(near[0]), c(near[1]), None, c(far[0]), c(far[1]), None]
    return " ".join(["0"] + ["2" if v is None else "%.6f" % v for v in vals])


def find_image(images_root, stem):
    hits = glob.glob(os.path.join(images_root, "*", "images", stem + ".*"))
    return hits[0] if hits else None


def convert(images_root, out, csv_path=CSV):
    counts, missing = {}, 0
    for r in csv.DictReader(open(csv_path)):
        if r["class"] == "unsure":
            continue
        img = find_image(images_root, r["image_stem"])
        if img is None:
            missing += 1
            continue
        split = r["split"]
        for sub in ("images", "labels"):
            os.makedirs(os.path.join(out, split, sub), exist_ok=True)
        dst = os.path.join(out, split, "images", os.path.basename(img))
        if not os.path.exists(dst):
            os.symlink(os.path.abspath(img), dst)
        with open(os.path.join(out, split, "labels", r["image_stem"] + ".txt"), "w") as f:
            if r["class"] == "ahead":
                near = (float(r["near_x"]), float(r["near_y"]))
                far = (float(r["far_x"]), float(r["far_y"]))
                f.write(label_line(near, far) + "\n")
        counts[(split, r["class"])] = counts.get((split, r["class"]), 0) + 1
    with open(os.path.join(out, "data.yaml"), "w") as f:
        f.write(f"path: {os.path.abspath(out)}\ntrain: train/images\nval: valid/images\n"
                "kpt_shape: [2, 3]  # 0 = near end, 1 = far end\nflip_idx: [0, 1]\nnc: 1\nnames: ['crosswalk']\n")
    return counts, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--images", required=True, help="folder from download_roboflow.py")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    counts, missing = convert(a.images, a.out)
    for k, v in sorted(counts.items()):
        print(k, v)
    if missing:
        print(f"{missing} labelled images not found (wrong Roboflow version?)", file=sys.stderr)


if __name__ == "__main__":
    main()
