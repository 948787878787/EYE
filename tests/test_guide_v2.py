"""board/guide_v2.py SafeAnnouncer: heartbeat only while GREEN / GREEN_FLASH, lost green withdrawn at once, faults
override colours (architecture review A9; user 2026-10-14 "silence must mean do not go")."""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "board"))

import guide_v2 as G  # noqa: E402
from ped_logic_v1 import GREEN, GREEN_FLASH, RED, UNKNOWN  # noqa: E402

TICKS = (G.SAY_TICK, G.SAY_TICK_FAST)


def run(seq, step=100, fault_at=None):
    """seq: list of states, one per `step` ms (fault_at: {index: fault}). Returns [(t, keys)]."""
    a, out = G.SafeAnnouncer(), []
    for i, s in enumerate(seq):
        out.append((i * step, a.update(i * step, s, (fault_at or {}).get(i))))
    return out


def keys(out):
    return [k for _, ks in out for k in ks]


def test_green_is_announced_then_ticks_every_second():
    out = run([GREEN] * 50)                                  # 5 s
    assert out[0][1] == ["green"]
    ticks = [t for t, ks in out if G.SAY_TICK in ks]
    assert ticks[0] == G.FIRST_TICK_MS
    assert all(b - a == G.HEARTBEAT_MS for a, b in zip(ticks, ticks[1:]))
    assert len(ticks) == 4


def test_flashing_ticks_twice_as_fast_and_differently():
    out = run([GREEN] * 20 + [GREEN_FLASH] * 30)
    assert "green_flash" in keys(out)
    fast = [t for t, ks in out if G.SAY_TICK_FAST in ks]
    assert len(fast) >= 2 and all(b - a == G.HEARTBEAT_FAST_MS for a, b in zip(fast, fast[1:]))
    assert all(t >= 2000 for t, ks in out if G.SAY_TICK_FAST in ks)


def test_lost_green_is_withdrawn_in_the_same_frame_and_ticks_stop():
    out = run([GREEN] * 30 + [UNKNOWN] * 30)
    assert out[30][1] == ["unknown"]                          # v1 waited LOST_HOLD_MS 1500
    assert not any(k in TICKS for _, ks in out[30:] for k in ks)


def test_red_after_green_says_red_and_stops_ticking():
    out = run([GREEN] * 30 + [RED] * 30)
    assert out[30][1] == ["red"]
    assert not any(k in TICKS for _, ks in out[30:] for k in ks)


def test_unknown_without_a_previous_green_is_silent():
    assert keys(run([UNKNOWN] * 50)) == []
    assert keys(run([RED] * 5 + [UNKNOWN] * 50)) == ["red"]


def test_fault_withdraws_green_then_repeats_and_blocks_colours():
    seq = [GREEN] * 200                                      # 20 s; the fault from 3 s on
    out = run(seq, fault_at={i: "camera_blocked" for i in range(30, 200)})
    assert out[30][1] == ["unknown", "camera_blocked"]
    later = [t for t, ks in out[31:] if ks]
    assert later == [30 * 100 + G.FAULT_REPEAT_MS, 30 * 100 + 2 * G.FAULT_REPEAT_MS]
    assert not any(k in TICKS + ("green",) for _, ks in out[30:] for k in ks if k != "camera_blocked")


def test_after_a_fault_the_colour_is_announced_again():
    out = run([GREEN] * 20 + [GREEN] * 20 + [GREEN] * 20, fault_at={i: "camera_dark" for i in range(20, 40)})
    assert out[40][1] == ["green"]


def test_repeat_of_the_same_colour_after_8_s_restarts_the_heartbeat():
    out = run([GREEN] * 100)
    assert [t for t, ks in out if "green" in ks] == [0, G.REPEAT_SAME_MS]


@pytest.mark.parametrize("seed", range(500))
def test_ticks_only_while_green_and_no_fault(seed):
    rnd = random.Random(seed)
    a = G.SafeAnnouncer()
    t = 0
    for _ in range(300):
        t += rnd.choice([30, 70, 100, 140, 400])
        state = rnd.choice([GREEN, GREEN, GREEN_FLASH, RED, UNKNOWN])
        fault = rnd.choice([None] * 8 + ["camera_dark", "slow"])
        ks = a.update(t, state, fault)
        if any(k in TICKS for k in ks):
            assert fault is None and state in (GREEN, GREEN_FLASH)
            assert (G.SAY_TICK in ks) == (state == GREEN)
        if fault is not None:
            assert not set(ks) & {"green", "green_flash", "red"}


def test_ticks_survive_the_tick_counter_wrapping(monkeypatch):
    period = 1 << 30
    monkeypatch.setattr(G, "ticks_add", lambda a, b: (a + b) % period)
    monkeypatch.setattr(G, "ticks_diff", lambda a, b: ((a - b + period // 2) % period) - period // 2)
    a = G.SafeAnnouncer()
    t0 = period - 1200
    out = [a.update((t0 + i * 100) % period, GREEN) for i in range(40)]
    assert sum(1 for ks in out if G.SAY_TICK in ks) == 3
