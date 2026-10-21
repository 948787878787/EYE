# Hard-case mining v2 (user 2026-10-14, privacy): hardcase_v1's policy unchanged, but the writer saves only the
# signal crop - the square the classifier sees (box long side x CONTEXT, at least MIN_SIDE px) - instead of the whole
# 1536x864 sensor ROI, which held passers-by and number plates. A hard case without a box (e.g. "stuck" with no
# detection this frame) is logged in the CSV with an empty file name and no image. A crop around a large, near box can
# still show part of a person standing right under the signal: privacy-reduced, not privacy-free.
# The crop is also cheaper: a ~100x100 JPEG instead of a 1536x864 one, so the save stall is much shorter.
from hardcase_v1 import (HardCasePolicy, HardCaseWriter, MIN_FREE_MB, JPEG_QUALITY, csv_line, free_mb,  # noqa: F401
                         write_retry)

CONTEXT = 1.6                  # as the classifier crop (ped_light_v12_logic4.CONTEXT)
MIN_SIDE = 32


def crop_rect(box, img_w, img_h, context=CONTEXT, min_side=MIN_SIDE):
    """(x0, y0, x1, y1): a square around box (x, y, w, h) of side max(min_side, long side x context), shifted to stay
    inside the image (as the board's classifier crop), never larger than the image."""
    x, y, w, h = box[0], box[1], box[2], box[3]
    side = int(max(min_side, max(w, h) * context))
    side = min(side, img_w, img_h)
    cx, cy = x + w / 2, y + h / 2
    x0 = int(min(max(0, cx - side / 2), img_w - side))
    y0 = int(min(max(0, cy - side / 2), img_h - side))
    return x0, y0, x0 + side, y0 + side


def crop_jpeg(img, rect, quality=JPEG_QUALITY):
    """RGBP888 (planar) snapshot -> JPEG of rect only (copied out first: chw2hwc reshapes, which needs a contiguous
    array)."""
    import image
    from libs.Utils import chw2hwc
    x0, y0, x1, y1 = rect
    part = img.to_numpy_ref()[:, y0:y1, x0:x1].copy()
    hwc = chw2hwc(part)
    rgb = image.Image(hwc.shape[1], hwc.shape[0], image.RGB888, alloc=image.ALLOC_REF, data=hwc)
    return rgb.to_jpeg(quality=quality).bytearray()


class CropHardCaseWriter(HardCaseWriter):
    def save(self, img, now, reason, state, label, probs, vetoed, box=None):
        """As HardCaseWriter.save, but only the signal crop; no box -> CSV record only. Never raises (but IDE stop)."""
        import gc
        try:
            self._ensure_session()
            if free_mb(self.root) < MIN_FREE_MB:
                print("hardcase: card almost full, not saving")
                return False
            self.count += 1
            name = ""
            if box:
                name = "hc_%04d_%s.jpg" % (self.count, reason)
                rect = crop_rect(box, img.width(), img.height())
                write_retry(self.dir + "/" + name, crop_jpeg(img, rect))
            self.log.write(csv_line(name, now, reason, state, label, probs, vetoed, box))
            self.log.flush()
            return True
        except Exception as e:
            if str(e) == "IDE interrupt":
                raise
            print("hardcase save failed:", e)
            return False
        finally:
            gc.collect()
