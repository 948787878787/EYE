"""Tests for board/hardcase_v1.py (hard-case mining policy and writer of the signal reader)."""
import builtins
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import hardcase_v1 as H  # noqa: E402
import ped_logic_v1 as L  # noqa: E402

FRAME_MS = 100  # 10 FPS
P_RED = {"red": 0.97, "green": 0.01, "other": 0.02}
P_GREEN = {"red": 0.01, "green": 0.97, "other": 0.02}
P_UNSURE = {"red": 0.45, "green": 0.15, "other": 0.40}
PROBS_OF = {"red": P_RED, "green": P_GREEN}


def feed(frames, start=0, policy=None):
    """frames: (state, label, probs, vetoed) per FRAME_MS. Returns [(ms since start, reason)] of saves."""
    policy = policy or H.HardCasePolicy()
    saves = []
    for i, (state, label, probs, vetoed) in enumerate(frames):
        now = (start + i * FRAME_MS) % H.TICKS_PERIOD
        save, reason = policy.update(now, state, label, probs, vetoed)
        if save:
            saves.append((i * FRAME_MS, reason))
    return saves


def run_reader(labels):
    """Real Voter states + confident classifier, as on the board. Returns saves like feed()."""
    voter = L.Voter()
    frames = []
    for i, label in enumerate(labels):
        state = voter.update(i * FRAME_MS, label)
        frames.append((state, label, PROBS_OF.get(label), False))
    return feed(frames)


def frames_of(state, label, ms, probs=None, vetoed=False):
    return [(state, label, probs, vetoed)] * (ms // FRAME_MS)


# ---- quiet when nothing is hard ------------------------------------------

def test_no_signal_never_saves():
    assert feed(frames_of(L.UNKNOWN, "none", 60000)) == []


def test_steady_red_with_confident_classifier_never_saves():
    assert run_reader(["red"] * 600) == []


def test_steady_green_with_confident_classifier_never_saves(monkeypatch):
    monkeypatch.setattr(H, "SKIP_WHILE_GREEN", False)   # prove it is the rules, not the green pause
    assert run_reader(["green"] * 600) == []


def test_full_signal_cycle_never_saves(monkeypatch):
    monkeypatch.setattr(H, "SKIP_WHILE_GREEN", False)
    flashing = (["green"] * 5 + ["none"] * 5) * 10          # 500 ms on / 500 ms off for 10 s
    labels = ["red"] * 400 + ["green"] * 150 + flashing + ["red"] * 400
    assert run_reader(labels) == []


def test_stuck_threshold_outlasts_a_normal_red_to_green_change():
    assert H.STUCK_UNKNOWN_MS > max(L.WINDOW_MS, L.RED_LOOKBACK_MS) + L.GREEN_HOLD_MS


# ---- each reason triggers -------------------------------------------------

def test_veto_saves_immediately():
    assert feed([(L.UNKNOWN, "unk", P_GREEN, True)]) == [(0, H.VETO)]


@pytest.mark.parametrize("probs", [
    {"red": 0.50, "green": 0.30, "other": 0.20},   # low top-1
    {"red": 0.65, "green": 0.02, "other": 0.33},   # top-1 ok, but red and other compete
])
def test_unsure_classifier_saves(probs):
    assert H.is_unsure(probs)
    assert feed([(L.RED, "red", probs, False)]) == [(0, H.UNSURE)]


@pytest.mark.parametrize("probs", [P_RED, P_GREEN, {"red": 0.65, "green": 0.20, "other": 0.15}])
def test_confident_or_diffuse_second_is_not_unsure(probs):
    assert not H.is_unsure(probs)


def test_stuck_unknown_saves_after_threshold():
    saves = feed(frames_of(L.UNKNOWN, "unk", H.STUCK_UNKNOWN_MS + 2000))
    assert saves == [(H.STUCK_UNKNOWN_MS + FRAME_MS, H.STUCK)]


def test_stuck_timer_survives_short_detector_dropouts():
    n = (H.STUCK_UNKNOWN_MS + 2000) // FRAME_MS
    frames = [(L.UNKNOWN, "unk" if i % 4 == 0 else "none", None, False) for i in range(n)]
    assert feed(frames) == [(H.STUCK_UNKNOWN_MS + FRAME_MS, H.STUCK)]


def test_stuck_timer_resets_when_signal_is_lost():
    first = H.STUCK_UNKNOWN_MS - H.SIGNAL_GAP_MS - 500     # + the gap tolerance: still below the threshold
    frames = frames_of(L.UNKNOWN, "unk", first) + frames_of(L.UNKNOWN, "none", H.SIGNAL_GAP_MS + 1000) \
        + frames_of(L.UNKNOWN, "unk", H.STUCK_UNKNOWN_MS - 500)
    assert feed(frames) == []


def test_stuck_timer_resets_when_state_is_decided():
    almost = H.STUCK_UNKNOWN_MS - 500
    frames = frames_of(L.UNKNOWN, "unk", almost) + frames_of(L.RED, "red", 200) \
        + frames_of(L.UNKNOWN, "unk", almost)
    assert feed(frames) == []


def test_quick_flip_back_saves_at_second_change():
    frames = frames_of(L.RED, "red", 5000) + frames_of(L.UNKNOWN, "unk", 1500) \
        + frames_of(L.GREEN, "green", 1000) + frames_of(L.UNKNOWN, "unk", 1500) \
        + frames_of(L.RED, "red", 3000)
    assert feed(frames) == [(9000, H.FLIP)]


def test_slow_changes_are_not_flips():
    frames = frames_of(L.RED, "red", 30000) + frames_of(L.GREEN, "green", 10000) \
        + frames_of(L.GREEN_FLASH, "green", 8000) + frames_of(L.RED, "red", 30000)
    policy = H.HardCasePolicy()
    assert feed(frames, policy=policy) == []
    assert policy.last_color == "red"


def test_first_color_change_after_start_is_not_a_flip():
    frames = frames_of(L.RED, "red", 1000) + frames_of(L.GREEN, "green", 1000) \
        + frames_of(L.GREEN, "green", 10000)
    assert feed(frames) == []


def test_green_to_green_flash_is_not_a_color_change():
    frames = (frames_of(L.GREEN, "green", 500) + frames_of(L.GREEN_FLASH, "green", 500)) * 10
    policy = H.HardCasePolicy()
    assert feed(frames, policy=policy) == []
    assert policy.last_change is None


# ---- rate limits ----------------------------------------------------------

def test_global_gap_between_saves(monkeypatch):
    monkeypatch.setattr(H, "REASON_COOLDOWN_MS", 0)
    saves = feed(frames_of(L.UNKNOWN, "unk", 10000, P_GREEN, True))
    assert [t for t, _ in saves] == [0, 2000, 4000, 6000, 8000]


def test_same_reason_cooldown():
    saves = feed(frames_of(L.UNKNOWN, "unk", 30000, P_GREEN, True))
    vetoes = [t for t, r in saves if r == H.VETO]
    assert vetoes == [0, 10000, 20000]


def test_falls_through_to_next_reason_while_first_cools_down():
    frames = [(L.RED, "red", P_RED, True)] + frames_of(L.RED, "red", 2500, P_RED) \
        + [(L.RED, "red", P_UNSURE, True)]
    assert feed(frames) == [(0, H.VETO), (2600, H.UNSURE)]


def test_stuck_scene_is_bounded():
    """A signal that stays undecidable (veto + unsure every frame) for 10 minutes."""
    saves = feed(frames_of(L.UNKNOWN, "unk", 600000, P_UNSURE, True))
    per_minute = len(saves) / 10
    assert per_minute <= 3 * 60000 / H.REASON_COOLDOWN_MS    # veto, stuck, unsure each once per cooldown
    assert all(b - a >= H.MIN_GAP_MS for (a, _), (b, _) in zip(saves, saves[1:]))


def test_per_reason_cap(monkeypatch):
    monkeypatch.setattr(H, "MAX_PER_REASON", 3)
    policy = H.HardCasePolicy()
    vetoes = feed(frames_of(L.RED, "red", 60000, P_RED, True), policy=policy)
    assert len(vetoes) == 3
    assert feed([(L.RED, "red", P_UNSURE, False)], start=70000, policy=policy) == [(0, H.UNSURE)]


def test_per_session_cap(monkeypatch):
    monkeypatch.setattr(H, "MAX_PER_SESSION", 5)
    monkeypatch.setattr(H, "REASON_COOLDOWN_MS", 0)
    policy = H.HardCasePolicy()
    assert len(feed(frames_of(L.UNKNOWN, "unk", 60000, P_UNSURE, True), policy=policy)) == 5
    assert policy.saved == 5


def test_no_saves_while_green_is_announced(monkeypatch):
    frame = [(L.GREEN, "green", P_GREEN, True)]
    assert feed(frame) == []
    monkeypatch.setattr(H, "SKIP_WHILE_GREEN", False)
    assert feed(frame) == [(0, H.VETO)]


def test_trackers_keep_running_while_saves_are_paused():
    policy = H.HardCasePolicy()
    feed(frames_of(L.GREEN, "green", 1000), policy=policy)
    assert policy.last_color == "green"


# ---- ticks wraparound -----------------------------------------------------

def test_ticks_diff_fallback_wraps_like_micropython():
    assert H.ticks_diff(5, H.TICKS_PERIOD - 5) == 10
    assert H.ticks_diff(H.TICKS_PERIOD - 5, 5) == -10


def scenario():
    """Every reason at least once, plus cooldown repeats."""
    return (frames_of(L.UNKNOWN, "unk", H.STUCK_UNKNOWN_MS + 1000)
            + frames_of(L.RED, "red", 5000, P_RED)
            + frames_of(L.RED, "red", 3000, P_GREEN, True)
            + frames_of(L.GREEN, "green", 1000, P_GREEN)
            + frames_of(L.RED, "red", 3000, P_UNSURE)
            + frames_of(L.UNKNOWN, "unk", 20000, P_UNSURE, True))


@pytest.mark.parametrize("start", [H.TICKS_PERIOD - 1234, H.TICKS_PERIOD - 7000, H.TICKS_PERIOD - 30000])
def test_decisions_identical_across_ticks_wraparound(start):
    reference = feed(scenario(), start=0)
    assert {r for _, r in reference} == set(H.REASONS)
    assert feed(scenario(), start=start) == reference


# ---- pure writer helpers --------------------------------------------------

def test_next_session_name():
    assert H.next_session_name([]) == "s001"
    assert H.next_session_name(["s001", "s007", "sx", "s01a", "log.csv"]) == "s008"


def test_csv_line_matches_header():
    ncols = H.CSV_HEADER.count(",") + 1
    full = H.csv_line("hc_0001_veto.jpg", 1234, H.VETO, L.UNKNOWN, "unk", P_GREEN, True, (10, 20, 30, 40.7))
    empty = H.csv_line("hc_0002_stuck.jpg", 99, H.STUCK, L.UNKNOWN, "none", None, False)
    assert full == "hc_0001_veto.jpg,1234,veto,UNKNOWN,unk,0.010,0.970,0.020,1,10,20,30,40\n"
    assert empty == "hc_0002_stuck.jpg,99,stuck,UNKNOWN,none,,,,0,,,,\n"
    assert full.count(",") + 1 == ncols == empty.count(",") + 1


# ---- writer on CPython (JPEG encoder stubbed) -------------------------------

@pytest.fixture
def fake_jpeg(monkeypatch):
    monkeypatch.setattr(H, "roi_jpeg", lambda img: b"\xff\xd8" + img + b"\xff\xd9")


def save(writer, reason=H.VETO, img=b"frame"):
    return writer.save(img, 1000, reason, L.UNKNOWN, "unk", P_GREEN, True, (1, 2, 3, 4))


def test_writer_creates_session_on_first_save(tmp_path, fake_jpeg):
    root = str(tmp_path / "hardcases")
    writer = H.HardCaseWriter(root)
    assert not os.path.exists(root)
    assert save(writer, H.VETO) and save(writer, H.FLIP)
    writer.close()
    session = os.path.join(root, "s001")
    assert sorted(os.listdir(session)) == ["hc_0001_veto.jpg", "hc_0002_flip.jpg", "log.csv"]
    with open(os.path.join(session, "log.csv")) as f:
        lines = f.read().splitlines()
    assert lines[0] + "\n" == H.CSV_HEADER
    assert [line.split(",")[0] for line in lines[1:]] == ["hc_0001_veto.jpg", "hc_0002_flip.jpg"]


def test_writer_new_boot_never_reuses_a_session(tmp_path, fake_jpeg):
    root = tmp_path / "hardcases"
    (root / "s001").mkdir(parents=True)
    (root / "s007").mkdir()
    (root / "s007" / "hc_0001_veto.jpg").write_bytes(b"old")
    writer = H.HardCaseWriter(str(root))
    assert save(writer)
    writer.close()
    assert (root / "s008" / "hc_0001_veto.jpg").exists()
    assert (root / "s007" / "hc_0001_veto.jpg").read_bytes() == b"old"


def test_writer_failure_returns_false_and_never_reuses_a_name(tmp_path, monkeypatch):
    def broken(img):
        raise RuntimeError("encoder out of memory")
    monkeypatch.setattr(H, "roi_jpeg", broken)
    writer = H.HardCaseWriter(str(tmp_path))
    assert save(writer) is False
    monkeypatch.setattr(H, "roi_jpeg", lambda img: b"jpg")
    assert save(writer) is True
    writer.close()
    assert "hc_0002_veto.jpg" in os.listdir(str(tmp_path / "s001"))


def test_writer_passes_ide_interrupt_through(tmp_path, monkeypatch):
    def stop(img):
        raise Exception("IDE interrupt")
    monkeypatch.setattr(H, "roi_jpeg", stop)
    with pytest.raises(Exception, match="IDE interrupt"):
        save(H.HardCaseWriter(str(tmp_path)))


def test_writer_skips_when_card_is_almost_full(tmp_path, fake_jpeg, monkeypatch):
    monkeypatch.setattr(H, "free_mb", lambda path: H.MIN_FREE_MB - 1)
    writer = H.HardCaseWriter(str(tmp_path))
    assert save(writer) is False
    writer.close()
    assert not any(n.endswith(".jpg") for n in os.listdir(str(tmp_path / "s001")))


def test_free_mb_reads_statvfs(tmp_path):
    assert H.free_mb(str(tmp_path)) > 0


def flaky_open(monkeypatch, tmp_path, failures):
    """First `failures` opens under tmp_path raise EPERM, as /data does in a fresh directory."""
    real_open = builtins.open
    calls = []

    def fake(path, *args, **kwargs):
        if str(path).startswith(str(tmp_path)):
            calls.append(path)
            if len(calls) <= failures:
                raise OSError(1, "EPERM")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", fake)
    monkeypatch.setattr(H, "_sleep_ms", lambda ms: None)
    return calls


def test_write_retry_survives_first_eperm(tmp_path, monkeypatch):
    calls = flaky_open(monkeypatch, tmp_path, failures=1)
    H.write_retry(str(tmp_path / "a.jpg"), b"x")
    assert len(calls) == 2
    assert (tmp_path / "a.jpg").read_bytes() == b"x"


def test_write_retry_gives_up_eventually(tmp_path, monkeypatch):
    flaky_open(monkeypatch, tmp_path, failures=10 ** 6)
    with pytest.raises(OSError):
        H.write_retry(str(tmp_path / "a.jpg"), b"x")
