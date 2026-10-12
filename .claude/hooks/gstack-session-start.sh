#!/usr/bin/env bash
#
# gstack-session-start.sh — SessionStart hook that makes gstack available in a
# cloud/web Claude Code session.
#
# Why this exists at all. Local machines get gstack from bootstrap.sh --user,
# which installs it once into ~/.claude/skills/gstack. Cloud and web sessions
# never run bootstrap: they start from a fresh container with only what the
# repository itself carries. The obvious fix — committing gstack into every
# repo — is wrong twice over: it is ~57MB per repo through the sync fan-out,
# and it freezes gstack at whatever was last pasted in, breaking its own
# /gstack-upgrade path.
#
# So the session clones it on start instead. Ephemeral container, ephemeral
# clone, nothing committed.
#
# Design rules:
#   * NEVER fail the session. Every failure path warns on stdout and exits 0 —
#     a missing skill pack is an inconvenience, a broken SessionStart hook is a
#     session that will not start.
#   * Skip instantly when gstack is already present, so a resumed session pays
#     nothing.
#   * Opt out with GSTACK_SKIP=1.
#
# Wire it in .claude/settings.json:
#   {"hooks": {"SessionStart": [{"hooks": [{"type": "command",
#     "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/gstack-session-start.sh\""}]}]}}

set -uo pipefail          # deliberately NOT -e: see "never fail the session"

DEST="${HOME}/.claude/skills/gstack"

[ "${GSTACK_SKIP:-0}" = "1" ] && { echo "gstack: skipped (GSTACK_SKIP=1)"; exit 0; }
[ -f "$DEST/SKILL.md" ] && { echo "gstack: already present"; exit 0; }

command -v git >/dev/null 2>&1 || { echo "gstack: git unavailable — skipping"; exit 0; }

mkdir -p "$(dirname "$DEST")" 2>/dev/null || { echo "gstack: cannot create skills dir — skipping"; exit 0; }

# --depth 1 --single-branch: the history is not wanted and the clone is on the
# session's critical path. --filter=blob:none would be faster still but is not
# supported by every proxy, and a hook is the wrong place to be clever.
if timeout 180 git clone --single-branch --depth 1 \
      https://github.com/garrytan/gstack.git "$DEST" >/dev/null 2>&1; then
  echo "gstack: installed ($(find "$DEST" -maxdepth 2 -name SKILL.md | wc -l | tr -d ' ') skills)"
else
  rm -rf "$DEST" 2>/dev/null      # never leave a half-clone that looks installed
  echo "gstack: clone failed or timed out — continuing without it"
fi

exit 0
