"""board/scan_v1.py: "no signal for 5 s -> turn slowly left and right" prompt of reader v6."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))
import scan_v1 as S  # noqa: E402

STEP_MS = 100                      # ~10 fps, as on the board


def run(prompter, start, end, detected=False, busy=False):
    """Feed frames in [start, end); returns [(t, key)] of every prompt."""
    out = []
    for t in range(start, end, STEP_MS):
        for key in prompter.update(t, detected, busy):
            out.append((t, key))
    return out


def test_no_prompt_before_five_seconds_without_a_signal():
    p = S.ScanPrompter(0)
    assert run(p, 0, S.SCAN_AFTER_MS) == []


def test_prompts_after_five_seconds_without_a_signal():
    p = S.ScanPrompter(0)
    assert run(p, 0, S.SCAN_AFTER_MS + STEP_MS) == [(S.SCAN_AFTER_MS, S.SAY_SCAN_LR)]


def test_repeats_only_every_ten_seconds():
    p = S.ScanPrompter(0)
    said = run(p, 0, S.SCAN_AFTER_MS + 2 * S.SCAN_REPEAT_MS + STEP_MS)
    assert [t for t, _ in said] == [S.SCAN_AFTER_MS, S.SCAN_AFTER_MS + S.SCAN_REPEAT_MS,
                                   S.SCAN_AFTER_MS + 2 * S.SCAN_REPEAT_MS]


def test_single_frame_flicker_does_not_reset_the_timer():
    p = S.ScanPrompter(0)
    said = run(p, 0, 3000)
    said += run(p, 3000, 3100, detected=True)          # one glare frame is not a signal in view
    said += run(p, 3100, S.SCAN_AFTER_MS + STEP_MS)
    assert said == [(S.SCAN_AFTER_MS, S.SAY_SCAN_LR)]


def test_signal_in_view_restarts_the_count_from_when_it_was_lost():
    p = S.ScanPrompter(0)
    assert run(p, 0, 4000) == []
    assert run(p, 4000, 8000, detected=True) == []
    said = run(p, 8000, 20000)
    # presence needs about one window to decay, then 5 s must pass again
    assert len(said) == 1 and said[0][1] == S.SAY_SCAN_LR
    assert 8000 + S.SCAN_AFTER_MS <= said[0][0] <= 8000 + S.PRESENCE_WINDOW_MS + S.SCAN_AFTER_MS


def test_no_prompt_while_the_signal_stays_in_view():
    p = S.ScanPrompter(0)
    run(p, 0, 1000)
    assert run(p, 1000, 30000, detected=True) == []


def test_detector_dropouts_keep_the_signal_in_view():
    p = S.ScanPrompter(0)
    said = []
    for t in range(0, 30000, STEP_MS):                  # every third frame missed, as in the bench test
        said += p.update(t, (t // STEP_MS) % 3 != 0, False)
    assert said == []


def test_found_is_said_once_when_a_signal_appears_after_a_scan_prompt():
    p = S.ScanPrompter(0)
    run(p, 0, S.SCAN_AFTER_MS + STEP_MS)
    said = run(p, 6000, 9000, detected=True)
    assert [k for _, k in said] == [S.SAY_FOUND]


def test_no_found_without_an_earlier_scan_prompt():
    p = S.ScanPrompter(0)
    run(p, 0, 2000)
    assert run(p, 2000, 5000, detected=True) == []


def test_state_announcement_takes_priority_and_the_scan_follows():
    p = S.ScanPrompter(0)
    assert run(p, 0, S.SCAN_AFTER_MS + STEP_MS, busy=True) == []
    assert run(p, S.SCAN_AFTER_MS + STEP_MS, S.SCAN_AFTER_MS + 2 * STEP_MS) == \
        [(S.SCAN_AFTER_MS + STEP_MS, S.SAY_SCAN_LR)]


def test_found_is_dropped_when_a_state_announcement_says_it_already():
    p = S.ScanPrompter(0)
    run(p, 0, S.SCAN_AFTER_MS + STEP_MS)
    assert run(p, 6000, 7000, detected=True, busy=True) == []
    assert run(p, 7000, 9000, detected=True) == []      # no late "found" afterwards


def test_ticks_wraparound_safe_via_ticks_diff():
    assert S.ticks_diff(5000, 0) == 5000
