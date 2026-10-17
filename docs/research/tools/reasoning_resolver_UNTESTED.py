#!/usr/bin/env python3
"""UNTESTED-IN-PRODUCTION reference resolver for the gateway (unit-tested on the box only).
Goal: emit ONE canonical, explicit request to llama-server so server-side precedence
(tools/server/server-common.cpp ~L1399-1465 at the reconstructed revision) can never surprise us:
  * top-level reasoning_effort OVERWRITES chat_template_kwargs.reasoning_effort (server)
  * reasoning_effort=="none" forces enable_thinking=false (server)
  * budget = reasoning_budget_tokens, else thinking_budget_tokens, else CLI default when -1 (server)
Policy (caller wins, then route default, then global default; never escalate silently):"""
from __future__ import annotations
import copy

VALID_EFFORT = {"none", "low", "medium", "high", "xhigh"}
TEMPLATE_EFFORT = {"low": "low", "medium": "medium", "high": "xhigh", "xhigh": "xhigh"}  # per user: template maps high->xhigh (UNVERIFIED locally)
ROUTE_DEFAULTS = {  # effort used only when the caller is silent
    "code":    {"enable_thinking": False, "effort": None, "budget": 0},
    "general": {"enable_thinking": True,  "effort": "medium", "budget": 1536},
    "plan":    {"enable_thinking": True,  "effort": "medium", "budget": 2048},
    "vision":  {"enable_thinking": True,  "effort": "low", "budget": 1024},
}

class PolicyError(ValueError):
    pass

def _bool(v, name):
    if isinstance(v, bool):
        return v
    raise PolicyError(f"{name} must be boolean, got {type(v).__name__}")

def resolve(body: dict, route: str = "general", conflict_policy: str = "reject") -> dict:
    """Returns a new body with canonical fields + '_resolution' audit dict (strip before sending if desired)."""
    if route not in ROUTE_DEFAULTS:
        raise PolicyError(f"unknown route {route}")
    b = copy.deepcopy(body)
    ctk = dict(b.get("chat_template_kwargs") or {})
    rd = ROUTE_DEFAULTS[route]
    src = {}

    # ---- effort: top-level vs nested ----
    top = b.get("reasoning_effort")
    nested = ctk.get("reasoning_effort")
    if b.get("reasoning") and isinstance(b["reasoning"], dict) and "effort" in b["reasoning"] and top is None:
        top = b["reasoning"]["effort"]  # Responses API shape
    for v, n in ((top, "reasoning_effort"), (nested, "chat_template_kwargs.reasoning_effort")):
        if v is not None and v not in VALID_EFFORT:
            raise PolicyError(f"invalid {n}={v!r}")
    if top is not None and nested is not None and top != nested:
        if conflict_policy == "reject":
            raise PolicyError(f"conflicting effort: top-level {top!r} vs nested {nested!r}")
        effort, src["effort"] = top, "caller_top_level(server_semantics)"
    elif top is not None:
        effort, src["effort"] = top, "caller_top_level"
    elif nested is not None:
        effort, src["effort"] = nested, "caller_nested"
    else:
        effort, src["effort"] = None, "unset"

    # ---- enable_thinking ----
    et_top = b.get("enable_thinking")
    et_nested = ctk.get("enable_thinking")
    if et_top is not None and et_nested is not None and _bool(et_top, "enable_thinking") != _bool(et_nested, "chat_template_kwargs.enable_thinking"):
        raise PolicyError("conflicting enable_thinking (top-level vs nested)")
    if et_nested is not None:
        thinking, src["thinking"] = _bool(et_nested, "chat_template_kwargs.enable_thinking"), "caller_nested"
    elif et_top is not None:
        thinking, src["thinking"] = _bool(et_top, "enable_thinking"), "caller_top_level"
    elif effort == "none":
        thinking, src["thinking"] = False, "effort_none"
    elif isinstance(b.get("thinking"), dict) and b["thinking"].get("type") in ("enabled", "disabled"):
        thinking, src["thinking"] = b["thinking"]["type"] == "enabled", "caller_anthropic"
    else:
        thinking, src["thinking"] = rd["enable_thinking"], f"route_default:{route}"
    if effort == "none" and thinking:
        raise PolicyError("reasoning_effort='none' contradicts enable_thinking=true")
    if effort is None and thinking:
        effort, src["effort"] = rd["effort"] or "medium", f"route_default:{route}"

    # ---- budget ----
    rbt, tbt = b.get("reasoning_budget_tokens"), b.get("thinking_budget_tokens")
    ab = b["thinking"].get("budget_tokens") if isinstance(b.get("thinking"), dict) else None
    for v, n in ((rbt, "reasoning_budget_tokens"), (tbt, "thinking_budget_tokens"), (ab, "thinking.budget_tokens")):
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < -1):
            raise PolicyError(f"invalid {n}={v!r}")
    if rbt is not None and tbt is not None and rbt != tbt and conflict_policy == "reject":
        raise PolicyError("conflicting reasoning_budget_tokens vs thinking_budget_tokens")
    if rbt is not None and rbt != -1:
        budget, src["budget"] = rbt, "caller_reasoning_budget_tokens"
    elif tbt is not None and tbt != -1:
        budget, src["budget"] = tbt, "caller_thinking_budget_tokens"
    elif ab is not None and ab != -1:
        budget, src["budget"] = ab, "caller_anthropic_budget"
    elif rbt == -1 or tbt == -1:
        budget, src["budget"] = -1, "caller_explicit_unlimited"
    else:
        budget, src["budget"] = rd["budget"], f"route_default:{route}"

    # ---- emit canonical: nested only (no top-level effort, so nothing can clobber), explicit numbers ----
    b.pop("reasoning_effort", None); b.pop("enable_thinking", None); b.pop("thinking_budget_tokens", None); b.pop("reasoning", None)
    ctk["enable_thinking"] = thinking
    if thinking:
        ctk["reasoning_effort"] = TEMPLATE_EFFORT[effort]
    else:
        ctk.pop("reasoning_effort", None)
    b["chat_template_kwargs"] = ctk
    if thinking:
        b["reasoning_budget_tokens"] = budget
    else:
        b.pop("reasoning_budget_tokens", None)
    b["_resolution"] = {"enable_thinking": thinking, "effort": TEMPLATE_EFFORT.get(effort) if thinking else None,
                        "budget": budget if thinking else None, "source": src, "route": route}
    return b
