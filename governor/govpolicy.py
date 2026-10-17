"""Pure decision logic of the Qwen governor (no I/O). Mirrored one to one by the Gov* functions
in governor.ps1 (and the others/ctx formulas in launch.ps1). Change a rule in both places.

Units: GiB for VRAM, GB for RAM, seconds/minutes as named. All inputs may be None (= "the read
failed"); every function has a defined answer for that, because one failed PDH sample must never
kill the loop or poison the state.
"""

# A loaded 27B Q4_K_M (17.15 GiB base) can never show less than this on the adapter or on its own process.
LOADED_MIN_ADAPTER_GIB = 8.0
LOADED_MIN_LLAMA_GIB = 4.0
# 'others' may not jump by more than this between two samples (15 s) without being confirmed first.
OTHERS_JUMP_GIB = 4.0
OTHERS_CONFIRM_SAMPLES = 4
# Everything that is not llama-server: desktop (dwm ~2.7 GiB on this PC), Chrome, Open WebUI, MCP processes.
OTHERS_PLAUSIBLE_MAX_GIB = 8.0
PROFILES = ("MAX", "BALANCED", "LEAN")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def validate_vram(adapter_gib, llama_gib, total_gib, loaded, llama_alive, last_good, suspect_count, starting=False):
    """Turn the two PDH readings into trusted numbers.

    adapter_gib : max over '\\GPU Adapter Memory(*)\\Dedicated Usage' instances (None = read failed)
    llama_gib   : sum of '\\GPU Process Memory(pid_<llama-server>*)\\Dedicated Usage' (None = failed / no process)
    total_gib   : profiles.json vram.total_gib
    loaded      : llama-swap says the governed model is 'ready'
    llama_alive : a llama-server process exists
    starting    : llama-swap says the model is 'starting' (its counters lag: never learn 'others' now)
    last_good   : previous trusted dict or None
    suspect_count: consecutive samples in which 'others' jumped (confirmation counter)

    Returns (metrics, suspect_count). metrics = {used, free, llama, others, ok, warn}.
    ok=False means "do not act on these numbers this sample" (they are last-good or absent).
    """
    warn = []
    lg = last_good or {}
    adapter_ok = _num(adapter_gib) and 0.0 <= adapter_gib <= total_gib * 1.05
    if not adapter_ok:
        warn.append("adapter counter invalid (%r)" % (adapter_gib,))
    elif loaded and adapter_gib < LOADED_MIN_ADAPTER_GIB:
        adapter_ok = False
        warn.append("adapter counter reads %.2f GiB while the model is loaded (impossible)" % adapter_gib)

    if not adapter_ok:
        # keep the last good picture, flag it, do not act
        if lg:
            m = dict(lg)
            m["ok"] = False
            m["warn"] = warn
            return m, suspect_count
        return {"used": None, "free": None, "llama": None, "others": None, "ok": False, "warn": warn}, suspect_count

    used = adapter_gib
    free = clamp(total_gib - used, 0.0, total_gib)

    llama_ok = _num(llama_gib) and 0.0 <= llama_gib <= used + 0.5
    if llama_ok and loaded and llama_gib < LOADED_MIN_LLAMA_GIB:
        llama_ok = False
        warn.append("process counter reads %.2f GiB for a loaded model (lagging)" % llama_gib)
    if not llama_ok and llama_gib is not None and _num(llama_gib) and not loaded:
        # not loaded: a small/zero per-process value is fine (starting or exiting server)
        llama_ok = True

    if llama_ok:
        llama = clamp(llama_gib, 0.0, used)
    elif loaded and _num(lg.get("others")):
        # trust the last good 'others' and attribute the rest to the model
        llama = clamp(used - lg["others"], 0.0, used)
    elif loaded:
        llama = used  # first sample ever and the process counter is wrong: assume nothing else is there
    else:
        llama = 0.0
    if not llama_alive and not loaded:
        llama = 0.0

    others = clamp(used - llama, 0.0, total_gib)
    ok = True
    if starting:
        warn.append("model starting: keeping last good others")
        others = lg["others"] if _num(lg.get("others")) else None
        if others is not None:
            llama = clamp(used - others, 0.0, used)
        return {"used": round(used, 2), "free": round(free, 2), "llama": round(llama, 2),
                "others": None if others is None else round(others, 2), "ok": False, "warn": warn}, suspect_count
    # jump guard: a sudden change in others while a model is (un)loading is almost always a counter lag
    if _num(lg.get("others")) and abs(others - lg["others"]) > OTHERS_JUMP_GIB:
        suspect_count += 1
        if suspect_count < OTHERS_CONFIRM_SAMPLES:
            warn.append("others jumped %.2f -> %.2f GiB; keeping last good until confirmed (%d/%d)"
                        % (lg["others"], others, suspect_count, OTHERS_CONFIRM_SAMPLES))
            others = lg["others"]
            llama = clamp(used - others, 0.0, used)
            ok = False
        else:
            warn.append("others change confirmed after %d samples" % suspect_count)
            suspect_count = 0
    else:
        suspect_count = 0
    if others > OTHERS_PLAUSIBLE_MAX_GIB and not loaded and llama_alive:
        # a dying/starting llama-server still holds VRAM: that is not 'others'
        warn.append("others %.2f GiB with a llama-server alive but not ready: ignoring" % others)
        others = lg["others"] if _num(lg.get("others")) else None
        ok = False
    return {"used": round(used, 2), "free": round(free, 2), "llama": round(llama, 2),
            "others": None if others is None else round(others, 2), "ok": ok, "warn": warn}, suspect_count


def validate_ram(ram_gb, last_good_gb):
    """Available RAM in GB. 0 or an absurd value is a failed PDH sample, not an empty machine."""
    if _num(ram_gb) and 0.05 <= ram_gb <= 2048.0:
        return ram_gb, True
    return last_good_gb, False


def pressure_step(count, free_gib, ram_gb, vram_ok, ram_ok, free_threshold, ram_critical,
                  others_gib=None, baseline_others=None, growth_min=0.5, hard_floor=0.25):
    """Consecutive-sample counter of REAL pressure. Invalid samples never add to it (they reset it:
    a reading we cannot trust is no evidence of pressure).

    A re-fit must mean OTHER apps grew: low free VRAM alone is the model's own steady state after a tight fit
    (2026-10-16: ctx 40960 left 0.65 GiB free and v4.0 re-fitted onto the same footprint). So free < threshold
    counts only when others has grown >= growth_min since the post-launch baseline; without a baseline it does
    not count at all. free < hard_floor (0.25) always counts, as does RAM < ram_critical."""
    now = False
    if vram_ok and _num(free_gib):
        if free_gib < hard_floor:
            now = True
        elif free_gib < free_threshold and _num(others_gib) and _num(baseline_others) \
                and (others_gib - baseline_others) >= growth_min:
            now = True
    if ram_ok and _num(ram_gb) and ram_gb < ram_critical:
        now = True
    return count + 1 if now else 0


def pressure_reason(free_gib, ram_gb, free_threshold, ram_critical, others_gib=None, baseline_others=None, hard_floor=0.25):
    parts = []
    if _num(free_gib) and free_gib < hard_floor:
        parts.append("free VRAM %.2f GiB < hard floor %.2f" % (free_gib, hard_floor))
    elif _num(free_gib) and free_gib < free_threshold:
        if _num(others_gib) and _num(baseline_others):
            parts.append("free VRAM %.2f GiB < %.2f with others %+.2f GiB since baseline %.2f"
                         % (free_gib, free_threshold, others_gib - baseline_others, baseline_others))
        else:
            parts.append("free VRAM %.2f GiB < %.2f" % (free_gib, free_threshold))
    if _num(ram_gb) and ram_gb < ram_critical:
        parts.append("RAM %.2f GB < %.2f" % (ram_gb, ram_critical))
    return ", ".join(parts) or "no pressure"


def baseline_ready(loaded, vram_ok, llama_measured, n_ctx, stable_count, need=2):
    """After a launch the counters settle for a few samples. Take the baseline on the `need`-th consecutive
    sample that is loaded, has valid VRAM numbers, a directly measured llama share and a known n_ctx.
    Returns (new_stable_count, take_now)."""
    if loaded and vram_ok and llama_measured and _num(n_ctx) and n_ctx > 0:
        stable_count += 1
        return stable_count, stable_count >= need
    return 0, False


def predicted_llama_gib(base_gib, ctx, kv_kib_per_token, overhead_gib=0.0):
    return base_gib + overhead_gib + ctx * kv_kib_per_token / 1048576.0


def calibrate(prev_overhead, llama_actual_gib, base_gib, ctx, kv_kib_per_token, alpha=0.5, max_overhead=1.5, min_overhead=-0.5):
    """Learn the footprint launch.ps1's model misses (drafter KV, mmproj, compute buffers). Returns
    (overhead_gib, predicted_gib, delta_gib). overhead is an EMA of the measured delta, clamped."""
    predicted = base_gib + ctx * kv_kib_per_token / 1048576.0
    delta = clamp(llama_actual_gib - predicted, min_overhead, max_overhead)
    if _num(prev_overhead):
        new = prev_overhead + alpha * (delta - prev_overhead)
    else:
        new = delta
    return round(new, 2), round(predicted, 2), round(llama_actual_gib - predicted, 2)


def launch_overhead(calib_entry, enabled=True, max_overhead=1.5):
    """What launch.ps1 adds to base_gib: the learned overhead, never negative (an under-estimate shrinks ctx,
    an over-estimate would spill into shared memory)."""
    if not enabled or not isinstance(calib_entry, dict):
        return 0.0
    v = calib_entry.get("overhead_gib")
    if not _num(v):
        return 0.0
    return round(clamp(v, 0.0, max_overhead), 2)


def refit_repeat_blocked(prev_ctx, new_ctx, others_now, others_at_refit, growth_min=0.5, step=4096):
    """After a re-fit that landed on the same ctx (+- one step) as before, block further re-fits until
    others has changed by >= growth_min since that re-fit."""
    if not (_num(prev_ctx) and _num(new_ctx)) or abs(new_ctx - prev_ctx) > step:
        return False
    if _num(others_now) and _num(others_at_refit) and abs(others_now - others_at_refit) >= growth_min:
        return False
    return True


def profile_choice(mode, idle_sec, ram_gb, ram_ok, others_gib, others_ok, cpu_high_count, a):
    """Which profile AUTO wants this sample. a = profiles.json 'auto'. Invalid readings never push LEAN."""
    if mode not in ("AUTO", "OFF"):
        return mode
    pressure = (ram_ok and _num(ram_gb) and ram_gb < a["ram_floor_gb"]) or \
               (others_ok and _num(others_gib) and others_gib > a["others_vram_lean_gib"]) or \
               (cpu_high_count >= 8)
    if pressure:
        return "LEAN"
    if idle_sec >= a["idle_for_max_sec"] and ram_ok and _num(ram_gb) and ram_gb >= a["ram_for_max_gb"] \
            and others_ok and _num(others_gib) and others_gib < a["others_vram_max_gib"]:
        return "MAX"
    return "BALANCED"


def decide(s):
    """One sample's action. s is a dict with:
    mode, loaded, state ('ready'|'starting'|'stopped'|'stopping'|'swap-down'|'api-error'),
    in_flight (True|False|None=unknown), quiet_sec, pressure_count, sample_sec, persist_sec,
    committed, loaded_profile, idle_unload_min, since_refit_min, refit_interval_min,
    since_prewarm_min, prewarm_cooldown_min, cur_id, emergency, agent_active, other_running,
    free_gib, ram_gb, free_threshold, ram_critical, quiet_before_reload_sec, max_upgrade_quiet_min
    Returns (action, reason). action in: none, unload, refit, upgrade, idle-unload, prewarm.
    """
    if s["mode"] == "OFF":
        if s["loaded"] and s["in_flight"] is False and s["quiet_sec"] >= 30:
            return "unload", "mode OFF"
        return "none", "mode OFF"
    if s["loaded"]:
        if s["in_flight"] is not False:
            return "none", "request in flight" if s["in_flight"] else "slot state unknown"
        persistent = s["pressure_count"] * s["sample_sec"] >= s["persist_sec"] and s["pressure_count"] > 0
        if persistent and s["quiet_sec"] >= 30:
            why = pressure_reason(s["free_gib"], s["ram_gb"], s["free_threshold"], s["ram_critical"],
                                  s.get("others_gib"), s.get("baseline_others"), s.get("hard_floor", 0.25))
            if s["committed"] == "LEAN":
                return "unload", "pressure, LEAN (%s)" % why
            if s["cur_id"] == "qwen3.8-27b-long" or s["emergency"]:
                return "none", "pressure but protected (%s)" % why
            if s.get("refit_blocked"):
                return "none", "pressure but a re-fit would repeat the same ctx; waiting for others to change (%s)" % why
            if s["since_refit_min"] >= s["refit_interval_min"]:
                return "refit", "%s for %ds -> re-fit context (%s)" % (why, s["pressure_count"] * s["sample_sec"], s["committed"])
            return "none", "pressure persists but re-fit rate-limited (%.0f/%d min)" % (s["since_refit_min"], s["refit_interval_min"])
        if s["idle_unload_min"] > 0 and s["quiet_sec"] >= s["idle_unload_min"] * 60:
            if s["agent_active"]:
                return "none", "idle but an agent client is active: stay warm"
            return "idle-unload", "idle %d min in %s" % (round(s["quiet_sec"] / 60), s["committed"])
        if s["loaded_profile"] == "LEAN" and s["committed"] != "LEAN" \
                and s["quiet_sec"] >= s["quiet_before_reload_sec"] and s["since_refit_min"] >= s["refit_interval_min"]:
            return "upgrade", "upgrade LEAN -> %s" % s["committed"]
        if s["loaded_profile"] == "BALANCED" and s["committed"] == "MAX" \
                and s["quiet_sec"] >= s["max_upgrade_quiet_min"] * 60 and s["since_refit_min"] >= s["refit_interval_min"]:
            return "upgrade", "upgrade BALANCED -> MAX"
        return "none", "steady"
    # not loaded
    if s["state"] == "stopped" and not s["other_running"] and s["since_prewarm_min"] >= s["prewarm_cooldown_min"]:
        if s["committed"] == "MAX":
            return "prewarm", "PC idle - keep model warm in MAX"
        if s["agent_active"] and s["committed"] != "LEAN":
            return "prewarm", "agent client active - keep model warm"
    return "none", "not loaded (%s)" % s["state"]


# ---------------- launch.ps1 formulas ----------------
def fit_ctx(total_gib, margin_gib, others_gib, base_gib, kv_kib_per_token, ctx_min, ctx_max, overhead_gib=0.0):
    """Context that fits: (total - margin - others - base - learned overhead) GiB of KV, rounded down to 4096, clamped."""
    kib = (total_gib - margin_gib - others_gib - base_gib - overhead_gib) * 1048576.0
    ctx = int(kib / kv_kib_per_token / 4096) * 4096 if kib > 0 else 0
    return max(int(ctx_min), min(int(ctx_max), ctx))


def launch_others(samples, llama_alive, status_others, status_age_sec, default_gib=2.2):
    """What launch.ps1 should book as 'others' before sizing the context.
    samples: adapter 'Dedicated Usage' readings in GiB taken ~1 s apart after the old server exited.
    Returns (others_gib, note)."""
    vals = [v for v in (samples or []) if _num(v) and 0.0 <= v <= 64.0]
    fresh = _num(status_others) and _num(status_age_sec) and status_age_sec <= 120 and 0.0 <= status_others <= OTHERS_PLAUSIBLE_MAX_GIB
    if not vals:
        if fresh:
            return round(status_others, 2), "adapter counter failed; using governor's others"
        return default_gib, "adapter counter failed; default"
    meas = min(vals)   # VRAM is still being released; the smallest sample is the closest to the truth
    if llama_alive:
        # the previous server did not exit in time: its VRAM is in the measurement
        if fresh:
            return round(status_others, 2), "old llama-server still alive (measured %.2f); using governor's others" % meas
        return default_gib, "old llama-server still alive (measured %.2f); default" % meas
    if meas > OTHERS_PLAUSIBLE_MAX_GIB:
        if fresh:
            return round(status_others, 2), "measured %.2f GiB implausible; using governor's others" % meas
        return round(meas, 2), "measured %.2f GiB implausible but no better source" % meas
    return round(meas, 2), "measured"
