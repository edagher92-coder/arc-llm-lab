"""Slot persistence policy for the Qwen governor (pure functions, no I/O).

governor/slotlib.ps1 mirrors every function here one to one (CamelCase names with a
Slot prefix, same argument order, same rules and near-identical reason wording). The
unit tests in test_slotpolicy.py pin the behaviour; if you change a rule, change both.
"""

import re

GIB = 1024 ** 3
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Keys llama-server may use for "tokens currently held in the slot", first hit wins.
TOKEN_KEYS = ("n_tokens", "n_past", "n_cache_tokens")


def slot_filename(variant_id):
    """'<variant-id>.bin', or None when the id could escape the slots dir."""
    if not isinstance(variant_id, str) or not _ID_RE.match(variant_id) or variant_id.startswith("."):
        return None
    return variant_id + ".bin"


def slot_token_count(slot):
    """Tokens held by a /slots entry, or None when the build does not report it."""
    if not isinstance(slot, dict):
        return None
    for k in TOKEN_KEYS:
        v = slot.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            return int(v)
    return None


def save_decision(slot, min_tokens):
    """Decide whether to save before an unload. Returns (save: bool, reason: str).

    Unknown token count -> save anyway; the caller re-checks n_saved afterwards
    (post_save_ok) and discards a too-small result.
    """
    if not isinstance(slot, dict):
        return False, "no slot info"
    if slot.get("is_processing") is True:
        return False, "slot busy"
    n = slot_token_count(slot)
    if n is None:
        return True, "n_tokens not reported"
    if n < min_tokens:
        return False, "n_tokens %d < min_tokens %d" % (n, min_tokens)
    return True, "n_tokens %d" % n


def post_save_ok(n_saved, min_tokens):
    """After the save call: keep the file only when it really holds enough tokens."""
    if not isinstance(n_saved, (int, float)) or isinstance(n_saved, bool):
        return False, "save reply has no n_saved"
    n = int(n_saved)
    if n < min_tokens:
        return False, "n_saved %d < min_tokens %d" % (n, min_tokens)
    return True, "n_saved %d" % n


def _norm_path(p):
    return str(p).replace("\\", "/").strip().lower()


def unload_gate(slot):
    """May the governor unload now? False only when the slot is definitely processing.

    Used before the save (cheap pre-check) and again after it: a request can arrive while
    a multi-second save runs, and unloading then would kill it. Returns (ok, reason).
    """
    if isinstance(slot, dict) and slot.get("is_processing") is True:
        return False, "slot busy"
    return True, "slot idle" if isinstance(slot, dict) else "slot state unknown"


def _int_or_none(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


def restore_decision(sidecar, bin_exists, model_path, ctx, model_stat, headroom=4096, kv_now=None):
    """Decide whether to restore after a governor-initiated load.

    sidecar: dict read from <id>.json or None; ctx: the new server's n_ctx (int or None).
    model_stat: (size_bytes, mtime_epoch_seconds) of the model file NOW, or None when it
    cannot be read. Same path but a replaced file (re-download, re-quantise) must not be
    restored into: size and mtime must both equal what the sidecar recorded.
    Returns (restore: bool, reason: str). On True the reason is the token count.
    """
    if not bin_exists:
        return False, "no slot file"
    if not isinstance(sidecar, dict):
        return False, "no sidecar"
    n = sidecar.get("n_tokens")
    if not isinstance(n, (int, float)) or isinstance(n, bool) or n <= 0:
        return False, "sidecar has no n_tokens"
    n = int(n)
    saved_model = sidecar.get("model_path")
    if not saved_model or not model_path or _norm_path(saved_model) != _norm_path(model_path):
        return False, "model_path mismatch"
    if not model_stat:
        return False, "model file stat unavailable"
    s_size, s_mtime = _int_or_none(sidecar.get("model_size")), _int_or_none(sidecar.get("model_mtime"))
    if s_size is None or s_mtime is None:
        return False, "sidecar has no model size/mtime"
    if s_size != _int_or_none(model_stat[0]) or s_mtime != _int_or_none(model_stat[1]):
        return False, "model file changed (size/mtime differ)"
    # a slot saved with one KV type (f16) cannot be restored into another (q8_0): refuse when both sides are known and differ
    skv = sidecar.get("kv")
    if isinstance(skv, str) and isinstance(kv_now, str) and skv.lower() != kv_now.lower():
        return False, "kv type changed (%s -> %s)" % (skv, kv_now)
    if not isinstance(ctx, (int, float)) or isinstance(ctx, bool) or ctx <= 0:
        return False, "new ctx unknown"
    ctx = int(ctx)
    if ctx < n + headroom:
        return False, "ctx %d < n_tokens %d + %d" % (ctx, n, headroom)
    return True, "n_tokens %d" % n


def restore_target_ok(slot):
    """Right after the load: is the fresh slot still ours to restore into?

    A user request that queued behind the load may already hold the slot or have filled it;
    restoring (or sending the 1-token warm-up) would clobber it. Returns (ok, reason).
    Unknown slot state -> ok (a server that just became healthy is empty in practice).
    """
    if not isinstance(slot, dict):
        return True, "slot state unknown"
    if slot.get("is_processing") is True:
        return False, "slot busy (a request is already running)"
    n = slot_token_count(slot)
    if n is not None and n > 0:
        return False, "slot not empty (%d tokens)" % n
    return True, "slot empty"


def prune_selection(entries, max_files, max_gib, managed_ids=None):
    """Names to delete so the slots dir holds at most max_files and max_gib.

    entries: iterable of dicts {name, size (bytes), mtime (epoch seconds)}.
    A 'unit' is <id>.bin plus <id>.json (the sidecar); max_files counts units.
    Deleted, in this order of certainty:
      1. *.tmp.bin (an interrupted save) and orphans (bin without sidecar, sidecar without bin)
      2. oldest complete units until count <= max_files and total size <= max_gib
    Only *.bin / *.json files whose stem is in managed_ids (when given) are ever
    considered; everything else is ignored, so the caller can never delete a stranger.
    """
    max_bytes = float(max_gib) * GIB
    delete = []
    units = {}
    for e in entries:
        name = e.get("name", "")
        if "/" in name or "\\" in name or not name:
            continue  # leaf names only
        if name.endswith(".tmp.bin"):
            stem, kind = name[: -len(".tmp.bin")], "tmp"
        elif name.endswith(".bin"):
            stem, kind = name[: -len(".bin")], "bin"
        elif name.endswith(".json"):
            stem, kind = name[: -len(".json")], "json"
        else:
            continue
        if managed_ids is not None and stem not in managed_ids:
            continue
        if kind == "tmp":
            delete.append(name)
            continue
        u = units.setdefault(stem, {})
        u[kind] = e

    complete = []
    for stem, u in units.items():
        if "bin" in u and "json" in u:
            size = float(u["bin"].get("size", 0)) + float(u["json"].get("size", 0))
            mtime = max(float(u["bin"].get("mtime", 0)), float(u["json"].get("mtime", 0)))
            complete.append((mtime, stem, size))
        else:
            for e in u.values():
                delete.append(e["name"])

    complete.sort(key=lambda t: (t[0], t[1]))  # oldest first
    count = len(complete)
    total = sum(t[2] for t in complete)
    i = 0
    while i < len(complete) and (count > max_files or total > max_bytes):
        mtime, stem, size = complete[i]
        delete.extend([stem + ".bin", stem + ".json"])
        count -= 1
        total -= size
        i += 1
    return delete


def hygiene_decision(loaded_min, quiet_min, processing, interval_hours, since_last_min,
                     min_quiet_min=10, cooldown_min=30):
    """Scheduled restart: loaded longer than interval_hours AND quiet longer than min_quiet_min.

    interval_hours <= 0 disables. Returns (due: bool, reason: str).
    cooldown_min stops a failed unload from retriggering every sample.
    """
    if not interval_hours or interval_hours <= 0:
        return False, "disabled"
    if processing:
        return False, "busy"
    if loaded_min is None:
        return False, "load time unknown"
    if loaded_min < interval_hours * 60:
        return False, "loaded %.0f min < %.0f min" % (loaded_min, interval_hours * 60)
    if quiet_min <= min_quiet_min:
        return False, "quiet %.1f min <= %d min" % (quiet_min, min_quiet_min)
    if since_last_min is not None and since_last_min < cooldown_min:
        return False, "cooldown"
    return True, "loaded %.1f h, quiet %.1f min" % (loaded_min / 60.0, quiet_min)


def empty_reply_step(prev_prompt, prev_pred, prompt, pred, processing, count):
    """Cheap empty-reply detector over llama-server /metrics counters.

    /metrics has no per-request completion counter, so this is a heuristic over one
    sampling interval: prompt_tokens_total grew while tokens_predicted_total did not and
    nothing is processing now -> a request finished (or was aborted) with zero predicted
    tokens. Any interval that predicted tokens resets the run. Returns the new count.
    A counter that went backwards means the server restarted: reset.
    The caller advances its baseline (prev_*) only on samples where nothing is processing,
    so a request spanning several samples is judged once, when it has finished.
    """
    if None in (prev_prompt, prev_pred, prompt, pred):
        return 0
    if prompt < prev_prompt or pred < prev_pred:
        return 0
    if processing:
        return count
    d_pred = pred - prev_pred
    d_prompt = prompt - prev_prompt
    if d_pred > 0:
        return 0
    if d_prompt > 0:
        return count + 1
    return count


# ---------------------------------------------------------------------------------------------
# Control Centre levers (docs/REMOTE-GUI-SPEC.md section 6.4): request.json, phases, VRAM bands.
# slotlib.ps1 mirrors these as SlotRequestTime / SlotRequestDecision / SlotRequestPlan /
# SlotPhaseDecide / SlotVramBands. Change a rule in both places.
# ---------------------------------------------------------------------------------------------
import datetime as _dt

REQUEST_ACTIONS = ("load", "unload", "restore", "mode")
REQUEST_ALIASES = {"reload": "restore"}          # 6.4 names the GUI button "reload"; the governor's word is "restore"
REQUEST_MODES = ("AUTO", "MAX", "BALANCED", "LEAN", "OFF")
REQUEST_MAX_AGE_SEC = 60
REQUEST_FUTURE_SKEW_SEC = 5
REQUEST_MAX_BYTES = 4096

ACTIVE_PHASES = ("loading", "restoring", "warming")
ALL_PHASES = ("loading", "restoring", "warming", "ready", "unloading", "postponed-busy", "stopped")
POSTPONE_HOLD_SEC = 30      # how long 'postponed-busy' stays visible after a refused unload
JOB_PHASE_MAX_SEC = 180     # a warm-up job phase older than this is a dead job's leftover
UNLOAD_SHOW_SEC = 10        # 'unloading' is shown for the sample in which the unload happened
PREWARM_SHOW_SEC = 30       # curl-style warm-up (no restore job): 'warming' while its request runs


def request_time(t):
    """Epoch seconds (float) of a request's `t`, or None. Accepts epoch seconds (or ms), or an ISO 8601
    string (naive strings count as UTC). Bools and everything else are rejected."""
    if isinstance(t, bool):
        return None
    if isinstance(t, (int, float)):
        if t != t or t <= 0:
            return None
        return float(t) / 1000.0 if t >= 1e11 else float(t)
    if isinstance(t, str):
        s = t.strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", s):
            return None
        try:
            d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.timestamp()
    return None


def request_decision(req, now, max_age=REQUEST_MAX_AGE_SEC):
    """Validate a parsed request.json. Returns (ok, action, arg, reason).

    action is one of REQUEST_ACTIONS ('reload' is mapped to 'restore'); arg is the mode name for
    action 'mode', else None. Anything else is refused: the file is never a way to run code.
    A request older than max_age seconds (or dated in the future beyond a small skew) is stale.
    """
    if not isinstance(req, dict):
        return False, None, None, "not a JSON object"
    a = req.get("action")
    if not isinstance(a, str):
        return False, None, None, "no action"
    a = REQUEST_ALIASES.get(a.strip().lower(), a.strip().lower())
    if a not in REQUEST_ACTIONS:
        return False, None, None, "action not allowed"
    t = request_time(req.get("t"))
    if t is None:
        return False, None, None, "no usable timestamp"
    age = now - t
    if age > max_age:
        return False, None, None, "stale request (%d s old, limit %d s)" % (age, max_age)
    if age < -REQUEST_FUTURE_SKEW_SEC:
        return False, None, None, "request dated in the future"
    arg = None
    if a == "mode":
        m = req.get("mode")
        m = m.strip().upper() if isinstance(m, str) else None
        if m not in REQUEST_MODES:
            return False, None, None, "mode not allowed"
        arg = m
    return True, a, arg, "ok"


def request_plan(action, loaded, state, processing, mode, other_running=False):
    """What the governor does with a valid request. Returns (plan, reason); plan is one of
    'set-mode' | 'prewarm' | 'unload' | 'unload-then-prewarm' | 'postpone' | 'noop'.

    'postpone' = refused because a request is running ("never while busy"): phase 'postponed-busy'.
    A load or restore never runs while mode is OFF (the loop would unload it again), nor over a
    different model, nor while llama-swap is down or already starting the model.
    """
    if action == "mode":
        return "set-mode", "ok"
    if state in ("swap-down", "api-error"):
        return "noop", "llama-swap not answering"
    if state == "starting":
        return "noop", "model is already loading"
    if action == "load":
        if loaded:
            return "noop", "already loaded"
        if mode == "OFF":
            return "noop", "mode OFF"
        if other_running:
            return "noop", "another model is running"
        return "prewarm", "load"
    if action == "restore":
        if mode == "OFF":
            return "noop", "mode OFF"
        if not loaded:
            return ("noop", "another model is running") if other_running else ("prewarm", "load with restore")
        if processing:
            return "postpone", "a request is running"
        return "unload-then-prewarm", "save, unload, reload with restore"
    if action == "unload":
        if not loaded:
            return "noop", "not loaded"
        if processing:
            return "postpone", "a request is running"
        return "unload", "unload"
    return "noop", "action not allowed"


def phase_decide(state, loaded, processing, job_phase=None, job_age=None, unload_age=None,
                 postponed_age=None, prewarm_age=None):
    """The `phase` string for status.json. Ages are seconds since the event, or None if it never happened.

    job_phase/job_age: what the restore warm-up job last wrote to phase.json (loading|restoring|warming|ready).
    unload_age: since the governor's last successful unload call; postponed_age: since it refused one because
    a request was running; prewarm_age: since it last started a (re)load.
    """
    if loaded and postponed_age is not None and postponed_age < POSTPONE_HOLD_SEC:
        return "postponed-busy"
    if job_phase in ACTIVE_PHASES and job_age is not None and job_age < JOB_PHASE_MAX_SEC:
        return job_phase
    if state == "starting":
        return "loading"
    if state == "stopping":
        return "unloading"
    if (prewarm_age is not None and prewarm_age < PREWARM_SHOW_SEC and
            (unload_age is None or prewarm_age <= unload_age)):
        if unload_age is not None and unload_age < UNLOAD_SHOW_SEC:
            return "loading"        # unload then reload in one sample: `loaded` is still the pre-unload value
        if not loaded and state == "stopped":
            return "loading"        # the load was asked for; llama-swap has not reported 'starting' yet
        if loaded and processing:
            return "warming"        # the 1-token warm-up request
    if loaded and unload_age is not None and unload_age < UNLOAD_SHOW_SEC:
        return "unloading"          # the sample in which we unloaded still carries the pre-unload state
    return "ready" if loaded else "stopped"


def vram_bands(total_gib, used_gib, llama_gib, desktop_gib, n_ctx=None, kv_kib_per_token=None):
    """Split the adapter's dedicated VRAM into bands that always sum to total_gib (within rounding).

    total/used: adapter totals; llama: the llama-server processes; desktop: dwm.exe (2.7 GB on the B60 box).
    KV is an estimate (n_ctx * kv_kib_per_token) carved out of llama's share; model gets the rest.
    Everything else on the adapter is 'other'. If counters overshoot the heap the bands are scaled down.
    Returns a dict of GiB values rounded to 2 places plus kv_estimated.
    """
    total = max(0.0, float(total_gib))
    used = max(0.0, float(used_gib))
    llama = min(max(0.0, float(llama_gib)), used)
    desktop = min(max(0.0, float(desktop_gib)), used - llama)
    other = max(0.0, used - llama - desktop)
    kv = 0.0
    if llama > 0 and n_ctx and kv_kib_per_token:
        kv = min(llama, float(n_ctx) * float(kv_kib_per_token) / 1048576.0)
    model = llama - kv
    free = max(0.0, total - used)
    parts = {"model_gib": model, "kv_gib": kv, "desktop_gib": desktop, "other_gib": other}
    s = sum(parts.values())
    if total and s > total:
        f = total / s
        parts = {k: v * f for k, v in parts.items()}
        free = 0.0
    out = {k: round(v, 2) for k, v in parts.items()}
    out["free_gib"] = round(free, 2)
    out["total_gib"] = round(total, 2)
    out["kv_estimated"] = True
    return out


def preload_items(total_gib, others_gib, base_gib, kv_kib_per_token, ctx, margin_gib):
    """Itemised cost of the next load (SlotPreload in slotlib.ps1): base + KV at ctx, and what is left afterwards.

    base_gib is profiles.json `base_gib` (weights, drafter and compute buffers together: the config does not split them).
    fits is True when the free VRAM after loading still honours the profile's margin (0.05 GiB tolerance).
    """
    kv = float(ctx) * float(kv_kib_per_token) / 1048576.0
    need = float(base_gib) + kv
    after = float(total_gib) - float(others_gib) - need
    return {"base_gib": round(base_gib, 2), "kv_gib": round(kv, 2), "ctx": int(ctx), "need_gib": round(need, 2),
            "others_gib": round(others_gib, 2), "free_after_gib": round(after, 2), "margin_gib": round(margin_gib, 2),
            "fits": after >= float(margin_gib) - 0.05}
