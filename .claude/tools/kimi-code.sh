#!/usr/bin/env bash
# kimi-code -- launch Claude Code backed by a Kimi model via Ollama's
# Anthropic-compatible API (Ollama >= 0.14, announced 2026-01-16).
#
#   ./kimi-code.sh                 # best available Kimi (prefers kimi-k3*)
#   ./kimi-code.sh kimi-k2.5:cloud # explicit tag
#   ./kimi-code.sh --list          # show Kimi tags the daemon can see
#
# How it works: Claude Code speaks the Anthropic Messages API; the local
# Ollama daemon serves that API and transparently proxies :cloud tags to
# Ollama Cloud (flat-rate). So a "Kimi Claude Code" session costs zero
# Claude quota.
#
# NUMBERS RULE (non-negotiable): a Kimi-backed session is for heavy
# NON-stakes work only -- bulk coding, refactors, drafts, research. Customer
# prices, quotes, invoices, legal content stay in a real Claude session.
#
# Auto-upgrade: prefers any kimi-k3* tag the daemon lists (expected on
# Ollama Cloud ~2026-07-27), falling back to kimi-k2.7-code:cloud (this
# week's bench clean-sweeper for code). Pass a tag to override.
set -euo pipefail

BASE="${CLAUDE_KIMI_OLLAMA_URL:-http://localhost:11434}"
FALLBACK="kimi-k2.7-code:cloud"

if ! curl -fsS --max-time 5 "$BASE/api/version" >/dev/null 2>&1; then
  echo "error: no Ollama daemon at $BASE -- start Ollama (>= 0.14) first." >&2
  echo "       (cloud tags need the daemon signed in to ollama.com or OLLAMA_API_KEY set)" >&2
  exit 1
fi
command -v claude >/dev/null 2>&1 || { echo "error: 'claude' CLI not on PATH." >&2; exit 1; }

kimi_tags() {
  curl -fsS --max-time 10 "$BASE/api/tags" 2>/dev/null \
    | python3 -c "import json,sys; [print(m['name']) for m in json.load(sys.stdin).get('models',[]) if 'kimi' in m['name'].lower()]" 2>/dev/null || true
}

if [ "${1:-}" = "--list" ]; then
  kimi_tags
  exit 0
fi

MODEL="${1:-}"
if [ -z "$MODEL" ]; then
  # Prefer K3 the moment it exists; otherwise the current code specialist.
  MODEL="$(kimi_tags | grep -i 'kimi-k3' | head -1 || true)"
  MODEL="${MODEL:-$FALLBACK}"
else
  shift || true
fi

echo "[kimi-code] Claude Code -> $MODEL via $BASE (zero Claude quota)"
echo "[kimi-code] NUMBERS RULE: non-stakes work only -- no customer prices/quotes/invoices/legal."

ANTHROPIC_BASE_URL="$BASE" ANTHROPIC_AUTH_TOKEN="ollama" exec claude --model "$MODEL" "$@"
