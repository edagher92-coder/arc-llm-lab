#!/usr/bin/env python3
"""claude_status_line — Claude Code statusLine command.

Shows the active Claude tier (from the harness's own stdin payload) plus a
live badge when a local ("offline") or Ollama Cloud model was recently used
for classification (claude-routing-classifier.ps1) or HEAVY offload
(ollama_route.py) — Model Routing Policy v5.0.

Wire it in settings.json:
    "statusLine": { "type": "command", "command": "~/.claude/tools/claude_status_line.py", "refreshInterval": 10 }

On Windows without Git Bash (shebang won't resolve), override the command
in your local settings.json to: "python ~/.claude/tools/claude_status_line.py"

Contract: Claude Code hides the whole status line on a non-zero exit code
or empty stdout, so this NEVER raises — any failure falls back to a minimal
line and always exits 0.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATUS_FILE = Path.home() / ".claude" / ".routing-status.json"
FRESH_SECONDS = 600  # how long a local/cloud badge stays visible after last use

# Router engine badges. 'anthropic' = a router dispatch that went to the Claude
# API (online, uses quota); 'cloud' = Ollama Cloud (online, flat-rate sub);
# 'local' = genuinely on your own hardware (offline). Written by router.py's
# _write_routing_status and the PowerShell classifier/HEAVY hooks.
ENGINE_BADGE = {
    "local": "\U0001f5a5️ offline",
    "cloud": "☁️ online·Ollama Cloud",
    "anthropic": "\U0001f310 online·Claude",
}


def _age_str(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    return f"{int(seconds // 3600)}h ago"


def _read_model_badge(payload: dict) -> str:
    model = payload.get("model") or {}
    name = model.get("display_name") or model.get("id") or "Claude"
    return f"\U0001f916 {name}"


def _read_engine_badge() -> str | None:
    try:
        raw = STATUS_FILE.read_text(encoding="utf-8")
        state = json.loads(raw)
        ts = datetime.fromisoformat(str(state["ts"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age < 0 or age > FRESH_SECONDS:
            return None
        engine = state.get("engine")
        badge = ENGINE_BADGE.get(engine)
        if not badge:
            return None
        model = state.get("model", "?")
        return f"{badge} ({model}, {_age_str(age)})"
    except Exception:
        return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    try:
        parts = [_read_model_badge(payload)]
        engine_badge = _read_engine_badge()
        if engine_badge:
            parts.append(engine_badge)
        print("  ·  ".join(parts))
    except Exception:
        print("\U0001f916 Claude Code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
