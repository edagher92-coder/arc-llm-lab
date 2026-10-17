"""pytest tests for govpolicy.py. Every scenario is taken from a real line of C:\\AI\\governor\\governor.log
(2026-10-10 .. 2026-10-15). Run: python3 -m pytest test_govpolicy.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import govpolicy as g

TOTAL = 23.88
AUTO = {"idle_for_max_sec": 600, "ram_floor_gb": 3.5, "ram_for_max_gb": 8.0,
        "others_vram_lean_gib": 3.5, "others_vram_max_gib": 3.0}


def base_state(**kw):
    s = dict(mode="AUTO", loaded=True, state="ready", in_flight=False, quiet_sec=200, pressure_count=0,
             sample_sec=15, persist_sec=60, committed="MAX", loaded_profile="MAX", idle_unload_min=0,
             since_refit_min=60, refit_interval_min=15, since_prewarm_min=60, prewarm_cooldown_min=10,
             cur_id="qwen3.8-27b", emergency=False, agent_active=False, other_running=None,
             free_gib=1.35, ram_gb=12.0, free_threshold=1.1, ram_critical=1.5,
             quiet_before_reload_sec=120, max_upgrade_quiet_min=20)
    s.update(kw)
    return s


# ---------------- VRAM validation (root cause 2 and 3) ----------------
def test_log_2026_10_10T22_38_26_adapter_zero_while_loaded_is_rejected():
    # "UNLOAD (free VRAM 23.88 GiB < 1.1 -> re-fit context (MAX))": adapter read 0 B with a 21 GiB model loaded
    last = {"used": 22.5, "free": 1.38, "llama": 21.0, "others": 1.5, "ok": True}
    m, sc = g.validate_vram(0.0, 21.0, TOTAL, loaded=True, llama_alive=True, last_good=last, suspect_count=0)
    assert m["ok"] is False
    assert m["free"] == 1.38            # last good kept, not 23.88
    assert any("impossible" in w for w in m["warn"])
    # and it must not count as pressure
    assert g.pressure_step(0, m["free"], 12.0, m["ok"], True, 1.1, 1.5) == 0


def test_log_2026_10_10T22_38_26_all_counters_zero_no_pressure():
    # the same sample set also zeroed 'Available MBytes' (ram 0 < floor 3.5 is what really fired $acute)
    ram, ok = g.validate_ram(0.0, 16.9)
    assert ok is False and ram == 16.9
    assert g.pressure_step(3, 23.88, ram, False, ok, 1.1, 1.5) == 0


def test_log_2026_10_11T08_34_33_others_21_33_while_starting():
    # "profile MAX -> LEAN (othersVRAM=21.33GiB)" two seconds before "launch:" - the old server's VRAM was booked as others
    last = {"used": 21.6, "free": 2.28, "llama": 21.2, "others": 0.44, "ok": True}
    m, sc = g.validate_vram(21.33, 0.0, TOTAL, loaded=False, llama_alive=True, last_good=last, suspect_count=0, starting=True)
    assert m["others"] == 0.44 and m["ok"] is False
    assert g.profile_choice("AUTO", 37527, 18.69, True, m["others"], m["ok"], 0, AUTO) != "LEAN"


def test_log_2026_10_11T08_58_55_process_counter_lag_on_loaded_model():
    # "profile MAX -> LEAN (ram=11.51GB othersVRAM=14.99GiB)": adapter 21.5, llama process counter 6.5 (lagging)
    last = {"used": 21.5, "free": 2.38, "llama": 21.2, "others": 0.3, "ok": True}
    m, sc = g.validate_vram(21.5, 6.5, TOTAL, loaded=True, llama_alive=True, last_good=last, suspect_count=0)
    assert m["ok"] is False and m["others"] == 0.3 and sc == 1
    # a REAL change (someone opened a 5 GiB app) is accepted after 4 consecutive samples
    for i in range(1, 4):
        m, sc = g.validate_vram(21.5, 16.0, TOTAL, True, True, last, sc)
    assert m["ok"] is True and m["others"] == 5.5 and sc == 0


def test_log_2026_10_11T09_17_48_negative_others_clamped():
    # "profile LEAN -> MAX (othersVRAM=-1.16GiB)"
    m, sc = g.validate_vram(20.0, 21.16, TOTAL, loaded=True, llama_alive=True, last_good=None, suspect_count=0)
    assert m["others"] >= 0.0 and m["llama"] <= m["used"]


def test_process_counter_zero_first_sample_loaded_assumes_model():
    m, sc = g.validate_vram(21.2, 0.0, TOTAL, loaded=True, llama_alive=True, last_good=None, suspect_count=0)
    assert m["llama"] == 21.2 and m["others"] == 0.0 and m["ok"] is True


def test_not_loaded_no_process_all_is_others():
    # 2026-10-15T23:17:21 launch others=2.87GiB: the desktop alone
    m, sc = g.validate_vram(2.87, None, TOTAL, loaded=False, llama_alive=False, last_good=None, suspect_count=0)
    assert m["others"] == 2.87 and m["llama"] == 0.0 and m["ok"] is True


def test_adapter_none_no_last_good_is_degraded_not_zero():
    m, sc = g.validate_vram(None, None, TOTAL, loaded=False, llama_alive=False, last_good=None, suspect_count=0)
    assert m["ok"] is False and m["free"] is None
    assert g.pressure_step(2, m["free"], None, m["ok"], False, 1.1, 1.5) == 0


# ---------------- hysteresis and rate limit ----------------
def P(count, free, others=None, base=None, ram=9.0):
    return g.pressure_step(count, free, ram, True, True, 1.1, 1.5, others, base, 0.5, 0.25)


def test_log_2026_10_16_own_footprint_is_not_pressure():
    # v4.0 live: v3-launched ctx 40960 f16, others 2.62 -> adapter 23.23/23.88, free 0.65 for ever -> re-fit every 15 min
    c = 0
    for _ in range(10):
        c = P(c, 0.65, others=2.62, base=2.62)
    assert c == 0
    assert g.decide(base_state(free_gib=0.65, pressure_count=c, others_gib=2.62, baseline_others=2.62)) == ("none", "steady")
    # no baseline yet (just launched): low free alone never counts
    assert P(3, 0.65, others=2.62, base=None) == 0
    # other apps grew by 0.6 GiB: that IS pressure, confirmed after 60 s
    c = 0
    for _ in range(4):
        c = P(c, 0.65, others=3.22, base=2.62)
    assert c == 4
    act, why = g.decide(base_state(free_gib=0.65, pressure_count=c, others_gib=3.22, baseline_others=2.62))
    assert act == "refit" and "+0.60 GiB since baseline 2.62" in why
    # hard floor always counts
    assert P(0, 0.20, others=2.62, base=2.62) == 1
    assert "hard floor" in g.pressure_reason(0.20, 9.0, 1.1, 1.5, 2.62, 2.62)
    # growth of 0.3 is below growth_min
    assert P(0, 0.65, others=2.92, base=2.62) == 0


def test_log_2026_10_12T15_01_40_single_low_sample_does_not_refit():
    # "UNLOAD (free VRAM 0.63 GiB < 1.1 ...)" fired on ONE sample in the live code
    c = P(0, 0.63, others=3.3, base=2.5)
    assert c == 1
    assert g.decide(base_state(free_gib=0.63, pressure_count=c)) == ("none", "steady")


def test_pressure_for_60s_then_refit_once_per_15min():
    c = 0
    for _ in range(4):
        c = P(c, 0.63, others=3.3, base=2.5)
    assert c == 4
    act, why = g.decide(base_state(free_gib=0.63, pressure_count=c, since_refit_min=60, others_gib=3.3, baseline_others=2.5))
    assert act == "refit" and "free VRAM 0.63" in why and "60s" in why
    # 2026-10-12T15:04:41 / 15:07:43 / 15:10:45: the live code re-fit every 3 min. Now: rate-limited.
    act, why = g.decide(base_state(free_gib=0.63, pressure_count=c, since_refit_min=3))
    assert act == "none" and "rate-limited" in why
    act, _ = g.decide(base_state(free_gib=0.63, pressure_count=c, since_refit_min=15))
    assert act == "refit"
    # a re-fit that would repeat the same ctx is blocked
    act, why = g.decide(base_state(free_gib=0.63, pressure_count=c, since_refit_min=15, refit_blocked=True))
    assert act == "none" and "repeat the same ctx" in why


def test_refit_repeat_guard():
    assert g.refit_repeat_blocked(40960, 40960, 2.62, 2.62) is True
    assert g.refit_repeat_blocked(40960, 36864, 2.62, 2.62) is True       # one step counts as the same
    assert g.refit_repeat_blocked(40960, 24576, 2.62, 2.62) is False
    assert g.refit_repeat_blocked(40960, 40960, 3.3, 2.62) is False        # others changed: allowed again
    assert g.refit_repeat_blocked(None, 40960, 2.62, 2.62) is False


def test_baseline_ready_needs_two_stable_samples():
    n, take = g.baseline_ready(True, True, True, 40960, 0)
    assert (n, take) == (1, False)
    n, take = g.baseline_ready(True, True, True, 40960, n)
    assert (n, take) == (2, True)
    assert g.baseline_ready(True, False, True, 40960, 5) == (0, False)    # invalid sample resets
    assert g.baseline_ready(True, True, False, 40960, 5) == (0, False)    # llama share inferred, not measured
    assert g.baseline_ready(False, True, True, 40960, 5) == (0, False)


def test_calibration_with_today_numbers():
    # 2026-10-16: launch ctx 40960 f16 others 2.62 -> predicted llama 17.15 + 2.52 = 19.67; adapter 23.23 -> llama 20.61
    over, pred, delta = g.calibrate(None, 23.23 - 2.62, 17.15, 40960, 64.5)
    assert pred == 19.67 and delta == 0.94 and over == 0.94
    # EMA on a second, smaller measurement
    over2, _, _ = g.calibrate(over, 20.21, 17.15, 40960, 64.5)
    assert over2 == 0.74
    # clamps
    assert g.calibrate(None, 30.0, 17.15, 40960, 64.5)[0] == 1.5
    assert g.calibrate(None, 10.0, 17.15, 40960, 64.5)[0] == -0.5
    # launch.ps1 applies the learned overhead (never negative) and the next fit lands with free >= margin
    oh = g.launch_overhead({"overhead_gib": over})
    assert oh == 0.94
    assert g.launch_overhead({"overhead_gib": -0.3}) == 0.0
    assert g.launch_overhead({"overhead_gib": 0.94}, enabled=False) == 0.0
    assert g.launch_overhead(None) == 0.0
    ctx = g.fit_ctx(TOTAL, 1.5, 2.62, 17.15, 64.5, 32768, 65536, overhead_gib=oh)
    assert ctx == 32768                                  # 1.67 GiB of KV = 24576, lifted to ctx_min
    free_after = TOTAL - 2.62 - g.predicted_llama_gib(17.15, ctx, 64.5, oh)
    assert 1.1 <= round(free_after, 2) <= 1.3, free_after   # 1.15: where the margin wanted it
    # without calibration the same inputs reproduce the 40960 that left 0.65 GiB free
    assert g.fit_ctx(TOTAL, 1.5, 2.62, 17.15, 64.5, 32768, 65536) == 40960
    # idle PC (others 0.14): still the full 65536
    assert g.fit_ctx(TOTAL, 1.35, 0.14, 17.15, 64.5, 32768, 65536, overhead_gib=oh) == 65536
    assert g.fit_ctx(TOTAL, 1.35, 1.0, 17.15, 64.5, 32768, 65536, overhead_gib=oh) == 53248


def test_pressure_resets_on_a_good_sample():
    c = 3
    c = g.pressure_step(c, 1.4, 9.0, True, True, 1.1, 1.5)
    assert c == 0


def test_never_unload_in_flight():
    s = base_state(free_gib=0.3, pressure_count=8, in_flight=True)
    assert g.decide(s)[0] == "none"
    s = base_state(mode="OFF", in_flight=True)
    assert g.decide(s)[0] == "none"
    s = base_state(free_gib=0.3, pressure_count=8, in_flight=None)
    assert g.decide(s) == ("none", "slot state unknown")


def test_pressure_reason_names_the_real_trigger():
    # the live log always said "free VRAM X < 1.1" even when RAM was the trigger
    assert g.pressure_reason(23.88, 1.2, 1.1, 1.5) == "RAM 1.20 GB < 1.50"
    assert g.pressure_reason(0.7, 12.0, 1.1, 1.5) == "free VRAM 0.70 GiB < 1.10"


def test_protected_variants_never_refit():
    s = base_state(free_gib=0.5, pressure_count=8, cur_id="qwen3.8-27b-long")
    assert g.decide(s)[0] == "none"
    s = base_state(free_gib=0.5, pressure_count=8, emergency=True)
    assert g.decide(s)[0] == "none"
    s = base_state(free_gib=0.5, pressure_count=8, committed="LEAN", loaded_profile="LEAN")
    assert g.decide(s)[0] == "unload"


# ---------------- agent clients ----------------
def test_agent_active_blocks_idle_unload_and_prewarms():
    s = base_state(committed="LEAN", loaded_profile="LEAN", idle_unload_min=5, quiet_sec=400, agent_active=True)
    assert g.decide(s)[0] == "none"
    s["agent_active"] = False
    assert g.decide(s)[0] == "idle-unload"
    s = base_state(loaded=False, state="stopped", committed="BALANCED", agent_active=True)
    assert g.decide(s) == ("prewarm", "agent client active - keep model warm")
    s["agent_active"] = False
    assert g.decide(s)[0] == "none"
    s = base_state(loaded=False, state="stopped", committed="LEAN", agent_active=True)
    assert g.decide(s)[0] == "none"          # never pull 21 GiB back in under LEAN pressure
    s = base_state(loaded=False, state="stopped", committed="MAX")
    assert g.decide(s)[0] == "prewarm"
    s["since_prewarm_min"] = 2
    assert g.decide(s)[0] == "none"
    s = base_state(loaded=False, state="stopped", committed="MAX", other_running="qwen3.6-35b-a3b")
    assert g.decide(s)[0] == "none"


def test_upgrades_are_rate_limited_too():
    s = base_state(loaded_profile="BALANCED", committed="MAX", quiet_sec=1300, since_refit_min=10)
    assert g.decide(s)[0] == "none"
    s["since_refit_min"] = 15
    assert g.decide(s) == ("upgrade", "upgrade BALANCED -> MAX")
    s = base_state(loaded_profile="LEAN", committed="BALANCED", quiet_sec=130, since_refit_min=20)
    assert g.decide(s) == ("upgrade", "upgrade LEAN -> BALANCED")


def test_mode_off():
    assert g.decide(base_state(mode="OFF", quiet_sec=31)) == ("unload", "mode OFF")
    assert g.decide(base_state(mode="OFF", quiet_sec=10))[0] == "none"


# ---------------- profile choice never acts on invalid readings ----------------
def test_profile_choice_invalid_readings():
    assert g.profile_choice("AUTO", 40000, 0.0, False, 21.3, False, 0, AUTO) == "BALANCED"
    assert g.profile_choice("AUTO", 40000, 20.0, True, 0.4, True, 0, AUTO) == "MAX"
    assert g.profile_choice("AUTO", 5, 20.0, True, 0.4, True, 0, AUTO) == "BALANCED"
    assert g.profile_choice("AUTO", 40000, 2.4, True, 1.1, True, 0, AUTO) == "LEAN"   # 2026-10-10T08:14:02 ram=2.43GB
    assert g.profile_choice("LEAN", 0, 20.0, True, 0.4, True, 0, AUTO) == "LEAN"


# ---------------- launch.ps1 formulas, checked against real "launch:" lines ----------------
def test_fit_ctx_matches_logged_launches():
    base, kv = 17.15, 64.5
    # 2026-10-11T21:22:19 launch: profile=BALANCED ctx=57344 others=1.53GiB
    assert g.fit_ctx(TOTAL, 1.5, 1.53, base, kv, 32768, 65536) == 57344
    # 2026-10-15T23:17:21 launch: profile=BALANCED ctx=36864 others=2.87GiB
    assert g.fit_ctx(TOTAL, 1.5, 2.87, base, kv, 32768, 65536) == 36864
    # 2026-10-15T10:31:53 launch: profile=MAX ctx=32768 others=3.32GiB
    assert g.fit_ctx(TOTAL, 1.35, 3.32, base, kv, 32768, 65536) == 32768
    # 2026-10-11T12:56:33 launch: profile=MAX ctx=65536 others=0.14GiB
    assert g.fit_ctx(TOTAL, 1.35, 0.14, base, kv, 32768, 65536) == 65536
    # 2026-10-12T14:09:09 launch: profile=BALANCED ctx=49152 others=2.07GiB
    assert g.fit_ctx(TOTAL, 1.5, 2.07, base, kv, 32768, 65536) == 49152
    # the f16 ceiling: 61440 needs others <= ~1.6 GiB in MAX
    assert g.fit_ctx(TOTAL, 1.35, 1.6, base, kv, 32768, 65536) == 61440
    assert g.fit_ctx(TOTAL, 1.35, 1.9, base, kv, 32768, 65536) == 53248


def test_log_2026_10_11T08_04_36_launch_others_21_24_rejected():
    # "launch: ... ctx=32768 others=21.24GiB": the previous server was still alive after the 15 s wait
    o, note = g.launch_others([21.24, 21.2, 21.1], llama_alive=True, status_others=0.43, status_age_sec=20)
    assert o == 0.43 and "still alive" in note
    o, note = g.launch_others([21.24], llama_alive=True, status_others=None, status_age_sec=None)
    assert o == 2.2
    # old server gone, VRAM still draining: the smallest sample wins
    o, note = g.launch_others([5.0, 2.9, 2.87], llama_alive=False, status_others=2.69, status_age_sec=30)
    assert o == 2.87 and note == "measured"
    # implausible without a live server, fresh governor value available
    o, note = g.launch_others([12.0, 11.9, 11.9], llama_alive=False, status_others=2.69, status_age_sec=30)
    assert o == 2.69
    # stale status (> 120 s) is not used
    o, note = g.launch_others([12.0], llama_alive=False, status_others=2.69, status_age_sec=900)
    assert o == 12.0
    # counter failed entirely
    assert g.launch_others([], False, 2.69, 10)[0] == 2.69
    assert g.launch_others(None, False, None, None)[0] == 2.2
