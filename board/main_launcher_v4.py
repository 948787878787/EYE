# /sdcard/main.py - boot launcher v4 (architecture review A9; user 2026-10-14): the board starts the READER at boot.
# v3 started shutter_v4 (photo / video collection), so a blind user switching the device on got no signal reading.
#   - default: the newest fail-safe reader (v15 -> v14 -> v13: heartbeat, spoken faults, self-test, stall watchdog);
#     never a reader without those (v12 and older), even as a fallback.
#   - KEY held down while booting (HOLD_MS): data collection instead (shutter_v4 -> v3), as v3 did.
#   - a crash restarts the list (ROUNDS times); after that the launcher stops (the reader already said "error" and a
#     dead board is silent: no heartbeat = do not go). The reader's own WDT reboots a hung board into this launcher.
#   - stopping from the IDE ("IDE interrupt") or Ctrl-C ends the launcher.
# Pure parts (choose_apps, key_held) are tested on the Mac: tests/test_main_launcher_v4.py.
READERS = [
    "/sdcard/ped_light/ped_light_v15_bbox.py",
    "/sdcard/ped_light/ped_light_v14_aim.py",
    "/sdcard/ped_light/ped_light_v13_safe.py",
]
SHUTTERS = [
    "/sdcard/ped_light/shutter_v4.py",
    "/sdcard/ped_light/shutter_v3.py",
]
KEY_PIN, KEY_PRESSED, LED_PIN = 21, 0, 52
HOLD_MS = 1000                 # KEY must read pressed this long at boot to choose data collection
SAMPLE_MS = 20
ROUNDS = 3                     # full passes over the list before giving up


def key_held(readings):
    """readings: KEY pin values sampled every SAMPLE_MS for HOLD_MS. Held = pressed in every sample (a bounce or a
    brief touch does not switch the device away from reading signals)."""
    return bool(readings) and all(r == KEY_PRESSED for r in readings)


def choose_apps(held):
    return list(SHUTTERS) if held else list(READERS)


def _read_key():
    import time
    from machine import Pin, FPIOA
    fpioa = FPIOA()
    fpioa.set_function(KEY_PIN, FPIOA.GPIO0 + KEY_PIN)
    key = Pin(KEY_PIN, Pin.IN, Pin.PULL_UP)
    out = []
    for _ in range(HOLD_MS // SAMPLE_MS):
        out.append(key.value())
        time.sleep_ms(SAMPLE_MS)
    return out


def main():
    import sys
    import time
    try:
        held = key_held(_read_key())
    except Exception as e:
        if str(e) == "IDE interrupt":
            return
        print("KEY read failed, starting the reader:", e)
        held = False
    apps = choose_apps(held)
    print("mode", "data collection" if held else "signal reader")
    for _ in range(ROUNDS):
        for path in apps:
            try:
                print("launch", path)
                exec(open(path).read(), {"__name__": "__main__", "STANDALONE": True})
                return
            except KeyboardInterrupt:
                return
            except Exception as e:
                if str(e) == "IDE interrupt":
                    return
                sys.print_exception(e)
                time.sleep(1)
    print("all apps failed", ROUNDS, "times: launcher stopped")


if __name__ == "__main__":
    main()
