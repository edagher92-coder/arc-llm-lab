"""Plain-assert tests for slotpolicy.py. Run: python3 governor/test_slotpolicy.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slotpolicy as sp

GIB = 1024 ** 3
MP = "C:/AI/models/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf"


def test_filename():
    assert sp.slot_filename("qwen3.8-27b") == "qwen3.8-27b.bin"
    assert sp.slot_filename("qwen3.8-27b-long") == "qwen3.8-27b-long.bin"
    for bad in ("", "..", "../x", "a/b", "a\\b", ".hidden", None, "x" * 80, "a b"):
        assert sp.slot_filename(bad) is None, bad


def test_save_decision():
    assert sp.save_decision({"is_processing": False, "n_tokens": 43000}, 4096) == (True, "n_tokens 43000")
    assert sp.save_decision({"is_processing": False, "n_tokens": 4096}, 4096)[0] is True   # boundary
    ok, why = sp.save_decision({"is_processing": False, "n_tokens": 4095}, 4096)
    assert not ok and "min_tokens" in why
    assert sp.save_decision({"is_processing": True, "n_tokens": 43000}, 4096) == (False, "slot busy")
    assert sp.save_decision({"is_processing": False, "n_past": 9000}, 4096)[0] is True      # fallback key
    assert sp.save_decision({"is_processing": False, "n_tokens": 0}, 4096)[0] is False
    # unknown count: save, validate afterwards with n_saved
    assert sp.save_decision({"is_processing": False}, 4096) == (True, "n_tokens not reported")
    assert sp.save_decision(None, 4096)[0] is False
    assert sp.save_decision({"is_processing": False, "n_tokens": True}, 4096)[1] == "n_tokens not reported"


def test_post_save_ok():
    assert sp.post_save_ok(43000, 4096)[0] is True
    assert sp.post_save_ok(10, 4096)[0] is False
    assert sp.post_save_ok(None, 4096)[0] is False
    assert sp.post_save_ok(True, 4096)[0] is False


MS = (16_900_000_000, 1760000000)       # (size, mtime) of the model file now


def test_restore_decision_kv_type():
    stat = (1000, 2000)
    sc = {"n_tokens": 43000, "model_path": MP, "model_size": 1000, "model_mtime": 2000, "kv": "f16/f16"}
    assert sp.restore_decision(sc, True, MP, 65536, stat, kv_now="f16/f16")[0] is True
    assert sp.restore_decision(sc, True, MP, 65536, stat, kv_now="F16/F16")[0] is True
    ok, why = sp.restore_decision(sc, True, MP, 65536, stat, kv_now="q8_0/q8_0")
    assert not ok and "kv type changed" in why
    # unknown on either side: no veto (older sidecars have no kv field)
    assert sp.restore_decision(sc, True, MP, 65536, stat, kv_now=None)[0] is True
    sc2 = dict(sc); del sc2["kv"]
    assert sp.restore_decision(sc2, True, MP, 65536, stat, kv_now="q8_0/q8_0")[0] is True


def test_restore_decision():
    sc = {"n_tokens": 43000, "ctx": 65536, "saved_at": "2026-10-11T09:00:00", "model_path": MP,
          "model_size": MS[0], "model_mtime": MS[1]}
    assert sp.restore_decision(sc, True, MP, 65536, MS) == (True, "n_tokens 43000")
    assert sp.restore_decision(sc, True, MP, 43000 + 4096, MS)[0] is True                       # exact boundary
    ok, why = sp.restore_decision(sc, True, MP, 43000 + 4095, MS)
    assert not ok and why.startswith("ctx ")
    assert sp.restore_decision(sc, False, MP, 65536, MS) == (False, "no slot file")
    assert sp.restore_decision(None, True, MP, 65536, MS) == (False, "no sidecar")
    assert sp.restore_decision("junk", True, MP, 65536, MS) == (False, "no sidecar")
    # model swapped under the same variant id (different gguf)
    assert sp.restore_decision(sc, True, "C:/AI/models/x/other.gguf", 65536, MS) == (False, "model_path mismatch")
    # Windows spelling and case differences are not a mismatch
    assert sp.restore_decision(sc, True, MP.replace("/", "\\").upper(), 65536, MS)[0] is True
    assert sp.restore_decision(dict(sc, model_path=None), True, MP, 65536, MS)[1] == "model_path mismatch"
    assert sp.restore_decision(dict(sc, n_tokens=0), True, MP, 65536, MS)[1] == "sidecar has no n_tokens"
    assert sp.restore_decision(dict(sc, n_tokens="43000"), True, MP, 65536, MS)[1] == "sidecar has no n_tokens"
    assert sp.restore_decision(sc, True, MP, None, MS) == (False, "new ctx unknown")
    # smaller re-fit context than the saved prompt: skip, never truncate
    assert sp.restore_decision(sc, True, MP, 32768, MS)[0] is False
    # model file replaced under the same path
    assert sp.restore_decision(sc, True, MP, 65536, (MS[0] + 1, MS[1])) == (False, "model file changed (size/mtime differ)")
    assert sp.restore_decision(sc, True, MP, 65536, (MS[0], MS[1] + 1))[1].startswith("model file changed")
    assert sp.restore_decision(sc, True, MP, 65536, None) == (False, "model file stat unavailable")
    # old sidecar without size/mtime is not trusted
    old = {k: v for k, v in sc.items() if k not in ("model_size", "model_mtime")}
    assert sp.restore_decision(old, True, MP, 65536, MS) == (False, "sidecar has no model size/mtime")
    assert sp.restore_decision(dict(sc, model_size=None), True, MP, 65536, MS)[0] is False
    assert sp.restore_decision(dict(sc, model_mtime="1760000000"), True, MP, 65536, MS)[0] is False


def test_unload_gate():
    assert sp.unload_gate({"is_processing": True}) == (False, "slot busy")
    assert sp.unload_gate({"is_processing": False})[0] is True
    assert sp.unload_gate({})[0] is True
    assert sp.unload_gate(None) == (True, "slot state unknown")


def test_restore_target_ok():
    f = sp.restore_target_ok
    assert f({"is_processing": False, "n_tokens": 0}) == (True, "slot empty")
    assert f({"is_processing": False}) == (True, "slot empty")
    assert f(None)[0] is True
    assert f({"is_processing": True, "n_tokens": 0})[0] is False
    ok, why = f({"is_processing": False, "n_tokens": 12})
    assert not ok and "not empty" in why


def _e(name, gib, mtime):
    return {"name": name, "size": int(gib * GIB), "mtime": mtime}


def _unit(stem, gib, mtime):
    return [_e(stem + ".bin", gib, mtime), _e(stem + ".json", 0, mtime)]


def test_prune_by_count():
    ents = _unit("a", 1, 100) + _unit("b", 1, 200) + _unit("c", 1, 300) + _unit("d", 1, 400)
    out = sp.prune_selection(ents, 3, 12)
    assert sorted(out) == ["a.bin", "a.json"], out
    assert sp.prune_selection(ents, 4, 12) == []
    out = sp.prune_selection(ents, 1, 12)
    assert sorted(out) == ["a.bin", "a.json", "b.bin", "b.json", "c.bin", "c.json"]


def test_prune_by_size():
    ents = _unit("a", 5, 100) + _unit("b", 5, 200) + _unit("c", 5, 300)
    out = sp.prune_selection(ents, 3, 12)          # 15 GiB > 12 -> drop oldest (10 GiB left)
    assert sorted(out) == ["a.bin", "a.json"], out
    out = sp.prune_selection(ents, 3, 4)           # even the newest alone is too big: all go
    assert sorted(out) == sorted(["a.bin", "a.json", "b.bin", "b.json", "c.bin", "c.json"])
    assert sp.prune_selection(ents, 3, 15) == []   # exactly at the limit is fine


def test_prune_tmp_and_orphans():
    ents = _unit("a", 3.4, 100) + [_e("b.tmp.bin", 1.2, 500), _e("c.bin", 2, 50), _e("d.json", 0, 60)]
    out = sp.prune_selection(ents, 3, 12)
    assert sorted(out) == ["b.tmp.bin", "c.bin", "d.json"], out


def test_prune_never_touches_strangers():
    ents = _unit("a", 1, 100) + [_e("notes.txt", 1, 1), _e("sub/evil.bin", 1, 1), _e("..\\x.bin", 1, 1),
                                 _e("mine.bin", 1, 5), _e("mine.json", 0, 5), _e("x.tmp.bin", 1, 1)]
    out = sp.prune_selection(ents, 3, 12, managed_ids={"a"})
    assert out == [], out                      # mine.* and x.tmp.bin are not managed ids
    out = sp.prune_selection(ents, 3, 12)      # unmanaged mode still ignores .txt and path-like names
    assert "notes.txt" not in out and "sub/evil.bin" not in out and "..\\x.bin" not in out
    assert "x.tmp.bin" in out
    for n in sp.prune_selection(ents, 0, 12):
        assert "/" not in n and "\\" not in n and n.endswith((".bin", ".json"))


def test_prune_tie_break_is_stable():
    ents = _unit("b", 1, 100) + _unit("a", 1, 100)
    assert sorted(sp.prune_selection(ents, 1, 12)) == ["a.bin", "a.json"]


def test_hygiene():
    f = sp.hygiene_decision
    assert f(400, 15, False, 6, None)[0] is True
    assert f(360, 10.5, False, 6, None)[0] is True                       # boundary: loaded == 6 h
    assert f(359, 15, False, 6, None) == (False, "loaded 359 min < 360 min")
    assert f(400, 10, False, 6, None)[0] is False                        # quiet must be MORE than 10
    assert f(400, 9, False, 6, None)[0] is False
    assert f(400, 15, True, 6, None) == (False, "busy")
    assert f(400, 15, False, 0, None) == (False, "disabled")             # 0 disables
    assert f(400, 15, False, None, None) == (False, "disabled")
    assert f(None, 15, False, 6, None) == (False, "load time unknown")
    assert f(400, 15, False, 6, 5) == (False, "cooldown")
    assert f(400, 15, False, 6, 31)[0] is True
    assert f(100, 15, False, 1.5, None)[0] is True                       # fractional hours
    assert f(100, 15, False, 1.5, None, min_quiet_min=20)[0] is False


def test_empty_reply():
    f = sp.empty_reply_step
    # request finished with zero predicted tokens
    assert f(100, 50, 600, 50, False, 0) == 1
    assert f(600, 50, 1100, 50, False, 1) == 2
    assert f(1100, 50, 1600, 50, False, 2) == 3
    # a healthy reply resets the run
    assert f(1600, 50, 1700, 80, False, 2) == 0
    # nothing happened: unchanged
    assert f(100, 50, 100, 50, False, 2) == 2
    # still processing: cannot judge, unchanged
    assert f(100, 50, 600, 50, True, 2) == 2
    # server restarted (counters went backwards) or first sample: reset
    assert f(5000, 900, 10, 0, False, 2) == 0
    assert f(None, None, 10, 0, False, 2) == 0
    assert f(10, None, 10, 0, False, 2) == 0


# ------------------------------- Control Centre levers (request.json, phases, bands) -------------------------------
NOW = 1760180000


def _req(action="unload", age=5, **kw):
    d = {"action": action, "t": NOW - age, "by": "cc"}
    d.update(kw)
    return d


def test_request_time():
    f = sp.request_time
    assert f(1760180000) == 1760180000.0
    assert f(1760180000.5) == 1760180000.5
    assert f(1760180000000) == 1760180000.0                       # milliseconds
    assert f("2025-10-11T10:13:20Z") == 1760177600.0
    assert f("2025-10-11T20:13:20+10:00") == 1760177600.0
    assert f("2025-10-11T10:13:20") == 1760177600.0              # naive == UTC
    for bad in (None, True, False, 0, -5, "", "yesterday", "1760180000", [], {}, float("nan"), "2025-13-45T99:99"):
        assert f(bad) is None, bad


def test_request_decision_accepts_only_the_four_actions():
    f = sp.request_decision
    assert f(_req("load"), NOW) == (True, "load", None, "ok")
    assert f(_req("unload"), NOW)[:2] == (True, "unload")
    assert f(_req("restore"), NOW)[:2] == (True, "restore")
    assert f(_req("reload"), NOW)[:2] == (True, "restore")        # GUI word mapped to the governor word
    assert f(_req("UNLOAD"), NOW)[:2] == (True, "unload")
    for bad in ("exec", "powershell", "kill", "unload; calc", "", "../load", "load now", 7, ["load"], None):
        r = {"action": bad, "t": NOW - 1, "by": "cc"}
        assert f(r, NOW)[:2] == (False, None), bad
    assert f({"t": NOW}, NOW)[:2] == (False, None)                 # no action key at all
    assert f({"action": "load"}, NOW) == (False, None, None, "no usable timestamp")      # t is mandatory
    assert f("load", NOW)[0] is False and f(None, NOW)[0] is False and f([_req()], NOW)[0] is False


def test_request_decision_ignores_old_and_future_requests():
    f = sp.request_decision
    assert f(_req(age=59), NOW)[0] is True
    assert f(_req(age=60), NOW)[0] is True                        # the limit itself is still fresh
    ok, a, arg, why = f(_req(age=61), NOW)
    assert not ok and why.startswith("stale request")
    assert f(_req(age=3600), NOW)[0] is False
    assert f(_req(age=-3), NOW)[0] is True                        # small clock skew
    assert f(_req(age=-30), NOW) == (False, None, None, "request dated in the future")
    assert f({"action": "load", "t": "2025-10-11T10:13:20Z"}, 1760177600 + 30)[0] is True
    assert f({"action": "load", "t": "2025-10-11T10:13:20Z"}, 1760177600 + 90)[0] is False
    assert f(_req(), NOW, max_age=2)[0] is False                   # configurable


def test_request_decision_mode_needs_a_valid_mode():
    f = sp.request_decision
    assert f(_req("mode", mode="max"), NOW) == (True, "mode", "MAX", "ok")
    assert f(_req("mode", mode="OFF"), NOW)[2] == "OFF"
    for bad in (None, "", "TURBO", "MAX; x", 3, ["MAX"]):
        assert f(_req("mode", mode=bad), NOW) == (False, None, None, "mode not allowed"), bad
    assert f(_req("mode"), NOW)[0] is False
    # arg is only ever set for 'mode'
    assert f(_req("unload", mode="MAX"), NOW)[2] is None


def test_request_plan():
    p = sp.request_plan
    # unload: busy -> postponed, no unload (acceptance test); idle -> unload
    assert p("unload", True, "ready", True, "AUTO") == ("postpone", "a request is running")
    assert p("unload", True, "ready", False, "AUTO")[0] == "unload"
    assert p("unload", False, "stopped", False, "AUTO") == ("noop", "not loaded")
    # load
    assert p("load", False, "stopped", False, "AUTO")[0] == "prewarm"
    assert p("load", True, "ready", False, "AUTO") == ("noop", "already loaded")
    assert p("load", False, "stopped", False, "OFF") == ("noop", "mode OFF")                 # the loop would unload it again
    assert p("load", False, "stopped", False, "AUTO", other_running=True)[0] == "noop"
    assert p("load", False, "starting", False, "AUTO") == ("noop", "model is already loading")
    # restore (reload with the saved context)
    assert p("restore", True, "ready", False, "AUTO")[0] == "unload-then-prewarm"
    assert p("restore", True, "ready", True, "AUTO")[0] == "postpone"
    assert p("restore", False, "stopped", False, "AUTO")[0] == "prewarm"
    assert p("restore", True, "ready", False, "OFF")[0] == "noop"
    # llama-swap down: nothing is attempted
    assert p("unload", False, "swap-down", False, "AUTO") == ("noop", "llama-swap not answering")
    assert p("load", False, "api-error", False, "AUTO")[0] == "noop"
    # mode changes are always allowed, whatever the model is doing
    assert p("mode", True, "ready", True, "OFF")[0] == "set-mode"
    assert p("exec", True, "ready", False, "AUTO")[0] == "noop"


def _walk(samples):
    """Feed phase_decide a list of kwargs dicts; return the phases."""
    return [sp.phase_decide(**k) for k in samples]


def test_phase_unload_busy_is_postponed_then_expires():
    busy = dict(state="ready", loaded=True, processing=True)
    assert sp.phase_decide(**busy, postponed_age=0) == "postponed-busy"
    assert sp.phase_decide(**busy, postponed_age=29) == "postponed-busy"
    assert sp.phase_decide(**busy, postponed_age=30) == "ready"           # hold over
    assert sp.phase_decide(state="ready", loaded=True, processing=False, postponed_age=5) == "postponed-busy"
    # postponed never sticks to a model that is gone
    assert sp.phase_decide(state="stopped", loaded=False, processing=False, postponed_age=5) == "stopped"


def test_phase_unload_walks_unloading_then_stopped():
    seq = _walk([
        dict(state="ready", loaded=True, processing=False),                                         # before
        dict(state="ready", loaded=True, processing=False, unload_age=0.5),                          # the sample that unloaded
        dict(state="stopped", loaded=False, processing=False, unload_age=15.5),                      # next sample
    ])
    assert seq == ["ready", "unloading", "stopped"], seq
    assert sp.phase_decide("stopping", True, False) == "unloading"


def test_phase_load_walks_loading_restoring_warming_ready():
    seq = _walk([
        dict(state="stopped", loaded=False, processing=False, prewarm_age=0.2),                      # load asked, swap not starting yet
        dict(state="starting", loaded=False, processing=False, job_phase="loading", job_age=4),
        dict(state="ready", loaded=True, processing=False, job_phase="restoring", job_age=9),
        dict(state="ready", loaded=True, processing=True, job_phase="warming", job_age=12),          # the 1-token 'hi' when no restore
        dict(state="ready", loaded=True, processing=False, job_phase="ready", job_age=14),
        dict(state="ready", loaded=True, processing=False),
    ])
    assert seq == ["loading", "loading", "restoring", "warming", "ready", "ready"], seq


def test_phase_restore_in_one_sample_is_loading_not_unloading():
    # UnloadThenPrewarm: both timestamps are fresh and `loaded` still holds the pre-unload value
    assert sp.phase_decide("ready", True, False, unload_age=1.0, prewarm_age=0.9) == "loading"
    # a plain unload (no reload) in the same state is 'unloading'
    assert sp.phase_decide("ready", True, False, unload_age=1.0) == "unloading"


def test_phase_dead_job_leftover_is_ignored():
    assert sp.phase_decide("ready", True, False, job_phase="restoring", job_age=600) == "ready"
    assert sp.phase_decide("stopped", False, False, job_phase="loading", job_age=600) == "stopped"
    assert sp.phase_decide("ready", True, False, job_phase="restoring", job_age=None) == "ready"
    assert sp.phase_decide("ready", True, False, job_phase="bogus", job_age=3) == "ready"
    for st, ld in (("swap-down", False), ("api-error", False), ("stopped", False), ("ready", True)):
        assert sp.phase_decide(st, ld, False) in sp.ALL_PHASES


def _bands_sum(b):
    return b["model_gib"] + b["kv_gib"] + b["desktop_gib"] + b["other_gib"] + b["free_gib"]


def test_vram_bands_sum_to_total_with_desktop_band():
    # loaded: 21.4 used of 23.88, llama 18.7 of which KV 65536 x 64.5 KiB = 4.03 GiB, dwm 2.7
    b = sp.vram_bands(23.88, 21.4, 18.7, 2.7, 65536, 64.5)
    assert abs(_bands_sum(b) - 23.88) <= 0.1, b
    assert b["desktop_gib"] == 2.7 and b["kv_estimated"] is True
    assert abs(b["kv_gib"] - 4.03) < 0.01 and abs(b["model_gib"] - (18.7 - 4.03)) < 0.02
    # unloaded: the desktop band is still there, model and KV are zero
    u = sp.vram_bands(23.88, 2.9, 0.0, 2.7, None, 64.5)
    assert u["desktop_gib"] == 2.7 and u["model_gib"] == 0 and u["kv_gib"] == 0
    assert abs(_bands_sum(u) - 23.88) <= 0.1 and abs(u["other_gib"] - 0.2) < 0.01
    # dwm counter bigger than what is left after llama: clamped, never negative
    c = sp.vram_bands(23.88, 21.0, 20.0, 2.7, 32768, 64.5)
    assert c["desktop_gib"] == 1.0 and c["other_gib"] == 0 and c["free_gib"] == 2.88
    assert abs(_bands_sum(c) - 23.88) <= 0.1
    # counters overshoot the heap: scaled down, free is 0, still sums to the total
    o = sp.vram_bands(23.88, 30.0, 26.0, 2.7, 32768, 64.5)
    assert o["free_gib"] == 0 and abs(_bands_sum(o) - 23.88) <= 0.1
    # garbage in: no crash, no negatives
    z = sp.vram_bands(23.88, -1, -2, -3, None, None)
    assert _bands_sum(z) - 23.88 <= 0.1 and all(v >= 0 for k, v in z.items() if k.endswith("_gib"))
    # llama so small KV would exceed it: KV is capped at llama's share
    k = sp.vram_bands(23.88, 3.0, 1.0, 2.0, 262144, 64.5)
    assert k["kv_gib"] == 1.0 and k["model_gib"] == 0


def test_preload_items_match_the_governors_expected_ctx():
    # same arithmetic as governor.ps1 expected_ctx: default variant, BALANCED margin 1.5, others (desktop + browser) 2.9 GiB
    total, margin, others, base, kv = 23.88, 1.5, 2.9, 17.15, 64.5
    ec = int(((total - margin - others - base) * 1048576) / kv / 4096) * 4096
    assert ec == 36864, ec
    p = sp.preload_items(total, others, base, kv, ec, margin)
    assert p["kv_gib"] == 2.27 and p["need_gib"] == 19.42 and p["free_after_gib"] == 1.56 and p["fits"] is True
    assert abs(p["base_gib"] + p["kv_gib"] - p["need_gib"]) <= 0.01
    # ctx_min forces a context the heap cannot hold with that margin: fits is False and free_after is below the margin
    q = sp.preload_items(total, 5.0, base, kv, 32768, margin)
    assert q["fits"] is False and q["free_after_gib"] < margin - 0.05


def test_ps_mirror_of_governor_wiring():
    """v4 governor: the slot is saved before every governor-initiated unload and restored after its relaunch.
    (The repo's Control Centre request.json lever is NOT part of the deployed v4 governor.)"""
    here = os.path.dirname(os.path.abspath(__file__))
    lib = open(os.path.join(here, "slotlib.ps1")).read()
    gov = open(os.path.join(here, "governor.ps1")).read()
    for name in ("SlotSave", "SlotRestorePlan", "SlotWarmFlow", "SlotCfg", "SlotPrune", "SlotDiskFreeGib"):
        assert ("function %s(" % name) in lib, name
    unload = gov[gov.index("function Unload("):gov.index("function WaitServerGone(")]
    assert "InFlight $script:curPort" in unload                      # fresh in-flight check right before the unload
    assert unload.index("SlotSave") < unload.index("/api/models/unload/")   # save first, then unload
    assert "UnloadThenPrewarm" in gov and "WaitServerGone 45" in gov          # relaunch only after the old server is gone
    prewarm = gov[gov.index("function Prewarm("):gov.index("function UnloadThenPrewarm(")]
    assert "SlotRestorePlan" in prewarm and "SlotWarmFlow" in prewarm
    # phase hooks inside SlotWarmFlow: loading at the start, restoring, warming, ready at the end
    flow = lib[lib.index("function SlotWarmFlow("):lib.index("# ---------------- for qwen.ps1")]
    for ph in ("loading", "restoring", "warming", "ready"):
        assert ("SlotSetPhase $p '%s'" % ph) in flow, ph
    assert "SlotRestoreDecision" in flow and "$kvNow" in flow                 # KV type is checked at restore time
    assert "kv = $kvType" in lib                                              # ... and recorded at save time
    # PS 5.1 pitfalls: no $pid variable, no PS7-only operators
    assert "$pid " not in gov.replace("$pids", "") and "$pid=" not in gov and "$pid)" not in gov
    assert "??" not in gov and "?." not in gov
    # status.json always carries the degraded flag and the last error
    for key in ("degraded", "last_error", "loop_errors", "sense_warnings", "decision_reason"):
        assert ("'%s'" % key) in gov, key


def test_ps_decision_constants_match_python():
    lib = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "slotlib.ps1")).read()
    for needle in ("%d" % sp.REQUEST_MAX_AGE_SEC, "%d" % sp.POSTPONE_HOLD_SEC, "%d" % sp.JOB_PHASE_MAX_SEC,
                   "%d" % sp.UNLOAD_SHOW_SEC, "%d" % sp.PREWARM_SHOW_SEC):
        assert needle in lib, needle
    for ph in sp.ALL_PHASES:
        assert ("'%s'" % ph) in lib, ph



def test_ps_mirror_present():
    """Drift guard: every policy function has a PowerShell twin in slotlib.ps1 (cannot run PS here)."""
    ps = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "slotlib.ps1")).read()
    for name in ("SlotFilename", "SlotTokenCount", "SlotSaveDecision", "SlotPostSaveOk", "SlotRestoreDecision",
                 "SlotRestoreTargetOk", "SlotUnloadGate", "SlotPruneSelection", "SlotHygieneDecision", "SlotEmptyReplyStep"):
        assert ("function %s(" % name) in ps, name


def run():
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print("ok  ", name)
    print("%d tests passed" % len(tests))


if __name__ == "__main__":
    run()
