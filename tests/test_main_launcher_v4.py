"""board/main_launcher_v4.py: the reader starts at boot; data collection only with KEY held the whole time."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import main_launcher_v4 as M  # noqa: E402

N = M.HOLD_MS // M.SAMPLE_MS
UP = 1 - M.KEY_PRESSED


def test_default_boot_starts_the_newest_safe_reader():
    apps = M.choose_apps(M.key_held([UP] * N))
    assert apps[0].endswith("ped_light_v15_bbox.py")
    assert all("ped_light_v1" in a for a in apps)


def test_fallbacks_never_include_a_reader_without_the_safety_feedback():
    for path in M.READERS:
        name = os.path.basename(path)
        version = int(name.split("_v")[1].split("_")[0])
        assert version >= 13, name                                # v13 = heartbeat, faults, self-test, stall watch
        assert os.path.exists(os.path.join(os.path.dirname(__file__), "..", "board", name))


def test_key_held_the_whole_time_switches_to_data_collection():
    assert M.choose_apps(M.key_held([M.KEY_PRESSED] * N)) == M.SHUTTERS


def test_a_bounce_or_a_short_touch_keeps_the_reader():
    assert not M.key_held([M.KEY_PRESSED] * (N - 1) + [UP])
    assert not M.key_held([UP] + [M.KEY_PRESSED] * (N - 1))
    assert not M.key_held([])


def test_launcher_sources_exist_and_are_board_safe():
    import ast
    src = open(os.path.join(os.path.dirname(__file__), "..", "board", "main_launcher_v4.py")).read()
    for node in ast.walk(ast.parse(src)):
        assert not isinstance(node, (ast.JoinedStr, ast.NamedExpr))
    for path in M.SHUTTERS:
        assert os.path.exists(os.path.join(os.path.dirname(__file__), "..", "board", os.path.basename(path)))
