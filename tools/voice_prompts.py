"""Single source of truth for spoken prompts (Traditional Chinese, Taiwan Mandarin).

Keys are the speech keys emitted by board/guide_v1.py plus a few system/obstacle prompts.
tools/make_prompts.py renders them to board/audio/<key>.wav; tools/voice_bridge.py plays those
files on the Mac and board/voice_v1.py plays them on the board, so both sound identical.

Wording rules: short (macOS `say` adds ~2.3 s startup, so audio must be pre-rendered anyway),
calm, and never "stop" when a green is lost (the user may already be on the crossing).
"""
VOICE = "Meijia"                 # macOS zh_TW voice
RATE = 220                       # words per minute for `say -r`

PROMPTS = {
    "red": "紅燈，請等待",
    "green": "綠燈，可以通行",
    "green_flash": "綠燈快結束，請勿開始穿越",
    "unknown": "號誌無法確認，請勿開始穿越",
    "unclear": "號誌不清楚，請稍等",
    "turn_left": "號誌在左，請向左轉",
    "turn_right": "號誌在右，請向右轉",
    "scan": "看不到號誌，請原地慢慢轉動",
    "scan_lr": "未偵測到號誌，請慢慢左右轉動",      # v6: after 5 s without a signal in view
    "found": "找到號誌",
    "obstacle_vehicle": "注意，前方有車",
    "obstacle_person": "前方有行人",
    "ready": "系統啟動",
    "error": "系統錯誤",
}
