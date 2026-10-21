# Black box v2 = v1 + crosswalk shadow columns (reader v16, plan docs/plans/2026-10-20_crossing_select_v1.md amendment 8).
# Same flush policy, chain and verifier (tools/verify_blackbox.py reads the genesis name from the file); v1 unchanged.
# Extra columns, all empty when the crosswalk model did not run on that frame or found nothing:
#   cw_score, cw_near_x, cw_near_y, cw_far_x, cw_far_y   raw midline of this frame's model run, detector-window px
#                                                          (kept raw so it can be re-evaluated once the board camera's
#                                                          field of view is measured)
#   own_far_x, own_tol                                    CrosswalkTracker.owned_far() used by the shadow gate
#   shadow_label, shadow_note                             what crossing_select_v1.gate would have reported
import blackbox_v1 as V1
from blackbox_v1 import digest

GENESIS = "k230-blackbox-v2"
HEADER = V1.HEADER[:-1] + (",cw_score,cw_near_x,cw_near_y,cw_far_x,cw_far_y,own_far_x,own_tol,"
                           "shadow_label,shadow_note\n")


def shadow_fields(found, owned, shadow_label, shadow_note):
    """found: (score, near, far) or None; owned: (far, tol) or None."""
    f = V1._f
    if found:
        score, near, far = found
        cw = "%s,%s,%s,%s,%s" % (f(score), f(near[0], "%d"), f(near[1], "%d"), f(far[0], "%d"), f(far[1], "%d"))
    else:
        cw = ",,,,"
    own = ("%s,%s" % (f(owned[0][0], "%d"), f(owned[1], "%d"))) if owned else ","
    return "%s,%s,%s,%s" % (cw, own, shadow_label or "", shadow_note or "")


def line(t, n, state, label, probs, sig, blocked, vetoed, fault, said, exp_us, gain, mean, spread,
         found=None, owned=None, shadow_label=None, shadow_note=None):
    base = V1.line(t, n, state, label, probs, sig, blocked, vetoed, fault, said, exp_us, gain, mean, spread)
    return base[:-1] + "," + shadow_fields(found, owned, shadow_label, shadow_note) + "\n"


class BlackBox(V1.BlackBox):
    """v1 writer with v2 lines and header."""

    def __init__(self, root=V1.ROOT):
        super().__init__(root)
        self.chain.prev = digest("", GENESIS)

    def record(self, state, *fields, **shadow):
        if not self.ok:
            return
        self.chain.add(line(fields[0], fields[1], state, *fields[2:], **shadow))
        if self.chain.due(state):
            self.flush()

    def _ensure(self):
        if self.path is not None:
            return
        import os
        from hardcase_v1 import mkdir_if_missing, next_session_name, free_mb
        mkdir_if_missing(self.root)
        if free_mb(self.root) < V1.MIN_FREE_MB:
            raise OSError("card almost full")
        d = self.root + "/" + next_session_name(os.listdir(self.root))
        os.mkdir(d)
        self.path = d + "/telemetry.csv"
        with open(self.path, "w") as fh:
            fh.write("#genesis,%s\n" % GENESIS + HEADER)
        print("blackbox", self.path)
