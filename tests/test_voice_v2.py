"""board/voice_v2.py (pure parts) + its prompt sources: required prompts, stall watchdog, wording and audio files."""
import os
import sys
import wave

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "board"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import voice_prompts_v2 as P  # noqa: E402
import voice_v2 as V  # noqa: E402

AUDIO = os.path.join(HERE, "..", "board", "audio")
# The prompt WAVs are generated locally (tools/make_prompts.py, macOS voice) and not published: skip the file checks
# until they exist.
needs_audio = pytest.mark.skipif(not os.path.isdir(AUDIO), reason="board/audio not generated (tools/make_prompts.py)")


def test_keys_match_the_prompt_source_and_v1_is_a_prefix():
    import voice_v1 as V1
    assert list(V.PROMPTS) == list(P.PROMPTS)
    assert V.PROMPTS[:len(V1.PROMPTS)] == V1.PROMPTS
    assert set(V.PRIORITY) == set(V.PROMPTS)


def test_required_covers_every_key_the_safe_reader_speaks():
    import guide_v2 as G
    import health_v1 as H
    spoken = set(G.STATE_SPEECH.values()) | {G.SAY_LOST, G.SAY_TICK, G.SAY_TICK_FAST} | set(H.FAULT_ORDER)
    assert spoken | {"ready", "error", "stalled"} <= set(V.REQUIRED)


def test_wording_never_says_stop_and_faults_forbid_starting():
    for key, text in P.SPEECH.items():
        assert "停" not in text, key
    for key in ("camera_dark", "camera_blocked", "slow", "stalled"):
        assert P.SPEECH[key].endswith("請勿開始穿越"), key


@pytest.mark.parametrize("key", V.PROMPTS)
@needs_audio
def test_every_prompt_file_has_the_board_format(key):
    with wave.open(os.path.join(AUDIO, key + ".wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (V.RATE, V.CHANNELS, V.SAMPLE_WIDTH)
        assert w.getnframes() > 0


@needs_audio
def test_ticks_are_short_and_never_interrupt():
    for key in ("tick", "tick_fast"):
        with wave.open(os.path.join(AUDIO, key + ".wav")) as w:
            assert w.getnframes() / w.getframerate() < 0.25
    player = V.Player({"tick": [b"x"], "green": [b"x", b"x"], "unknown": [b"x"]})
    assert player.request("green", 0) == V.PLAY
    assert player.request("tick", 10) == V.BUSY               # a tick never cuts a sentence
    player.playing = None
    assert player.request("tick", 20) == V.PLAY
    assert player.request("unknown", 30) == V.INTERRUPT       # a withdrawal cuts a tick


def test_stall_watch_fires_only_after_a_silent_loop_and_repeats():
    w = V.StallWatch()
    assert not w.due(10_000)                                  # nothing before the first alive()
    w.alive(0)
    assert not w.due(V.STALL_MS - 1)
    assert w.due(V.STALL_MS)
    assert not w.due(V.STALL_MS + V.STALL_REPEAT_MS - 1)
    assert w.due(V.STALL_MS + V.STALL_REPEAT_MS)
    w.alive(20_000)
    assert not w.due(20_000 + V.STALL_MS - 1)


def test_self_test_fails_without_audio():
    v = V.Voice(audio_dir="/nonexistent")                     # no media module on the Mac: init fails
    assert not v.self_test_ok() and v.missing
    assert v.say("green") is False
