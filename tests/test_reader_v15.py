"""board/ped_light_v15_bbox.py = v14 + exposure_v1 + blackbox_v1 + hardcase_v2 (board-only): static wiring checks."""
import ast
import os

SRC = open(os.path.join(os.path.dirname(__file__), "..", "board", "ped_light_v15_bbox.py"), encoding="utf-8").read()
LOOP = SRC[SRC.index("while True:"):SRC.index("except KeyboardInterrupt")]


def test_keeps_the_v13_v14_safety_and_aim_lines():
    for line in ("voice.self_test_ok()", "wdt = WDT(1, WDT_TIMEOUT_S)\n", "voice.alive(now)",
                 "announcer.update(now, state, fault)", "aim.update(now, state, fault, aim_sig)",
                 "led.value(0 if fault else"):
        assert line in SRC


def test_hard_cases_are_crop_only():
    assert "from hardcase_v2 import HardCasePolicy, CropHardCaseWriter" in SRC and "hardcase_v1" not in SRC
    assert "CropHardCaseWriter() if HARDCASES" in SRC


def test_exposure_takes_over_after_settling_and_falls_back_to_ae():
    assert LOOP.index("take_over_exposure(sensor)") < LOOP.index("expo.update(stats[0])")
    assert "expo = None                          # sensor refused" in LOOP
    take = SRC[SRC.index("def take_over_exposure"):SRC.index("def apply_exposure")]
    assert take.index("ExposureControl(") < take.index("sensor.auto_exposure(False)")   # AE off only if reads worked
    assert "sensor.auto_exposure(True)" in SRC[SRC.index("def apply_exposure"):]


def test_health_sees_the_unbiased_light():
    assert "light = int(stats[0] * 2 ** -EV_BIAS) if expo is not None else stats[0]" in LOOP
    assert LOOP.index("light = ") < LOOP.index("health.update(now, light, stats[1])")


def test_black_box_records_every_frame_after_the_speech_and_flushes_at_exit():
    assert LOOP.index("aim.update(") < LOOP.index("bb.record(state, now, n,")
    assert "bb.flush()" in SRC[SRC.index("finally:"):]


def test_board_safe_syntax():
    for node in ast.walk(ast.parse(SRC)):
        assert not isinstance(node, (ast.JoinedStr, ast.NamedExpr))
