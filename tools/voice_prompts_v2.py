"""Prompts for board/voice_v2.py = tools/voice_prompts.py (v1, unchanged) + the fail-safe keys of 2026-10-14.

Speech keys are rendered by tools/make_prompts.py --v2; tick / tick_fast are tones (tools/make_tones_v1.py), not speech.
Wording rule kept from v1: never "stop" (the user may already be on the crossing); every fault ends with
"請勿開始穿越" so a fault is never mistaken for permission.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import voice_prompts as V1  # noqa: E402

VOICE, RATE = V1.VOICE, V1.RATE
TONES = ("tick", "tick_fast")
PROMPTS = dict(V1.PROMPTS)
PROMPTS.update({
    "tick": "(tone) green heartbeat",
    "tick_fast": "(tone) green-flashing heartbeat",
    "camera_dark": "太暗，看不到號誌，請勿開始穿越",
    "camera_blocked": "鏡頭被擋住，請勿開始穿越",
    "slow": "系統反應變慢，請勿開始穿越",
    "stalled": "系統異常，請勿依賴，請勿開始穿越",
    "aligned": "號誌在正前方",             # aim_v1 (reader v14): the signal came to the centre after a turn prompt
})
SPEECH = {k: v for k, v in PROMPTS.items() if k not in TONES}
