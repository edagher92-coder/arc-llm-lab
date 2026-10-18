# Codex on the local Qwen: the locked-in harness (18 Oct 2026)

Codex CLI (`codex-qwen`) is the one everyday harness for Qwen3.8-27B on the B60. Claude Code on Qwen (`claude-qwen`)
and the `ask_local` MCP tool stay available; a repo batch runner is used only on demand. Other harnesses (a DeepSeek
harness trial) are parked: on the one task tried it scored lower than the existing runner and added moving parts.

## What `codex-qwen` does

| Piece | File | Why |
|---|---|---|
| Lean Codex home | [agents/codex-lean-home/config.toml](../agents/codex-lean-home/config.toml) (deploy to `C:\AI\codex-local\home`) | No plugins, MCP servers, global AGENTS.md or skills tree: about 3K base prompt tokens instead of about 16K |
| Compact instructions | [instructions-compact.md](../agents/codex-lean-home/instructions-compact.md) | 1.6 KB system prompt with the Windows/PowerShell rules learned below |
| Preflight | [preflight.ps1](../agents/codex-lean-home/preflight.ps1) | Takes the engine lock, waits while the slot is busy, prints the live window (server ctx - 8K) |
| Engine lock | [agents/locks/qwen-lock.ps1](../agents/locks/qwen-lock.ps1) | One Qwen job at a time: `C:\AI\locks\qwen-engine.lock`, shared by codex-qwen, claude-qwen and the repo runner (`QWEN_LOCK_SCRIPT`). Dead or orphaned holders are taken over automatically |
| Launcher | [agents/codex-qwen.cmd](../agents/codex-qwen.cmd) | Window and compaction (90%) from the live server; git identity label; for unattended `exec` only, the repo's own `.git` is writable |

The single llama-server slot is shared: two jobs interleave requests and each runs at about half speed, which is why
the lock exists. Interactive Codex keeps Codex's `.git` protection (it asks before git writes); unattended `exec` runs
cannot ask, so `codex-qwen` adds the current repo's `.git` as a writable root (`QWEN_GIT_WRITE=0` turns that off).

## Measured (evalsuite, same 19 tasks, hidden checkers)

| Setup | Passed | Wall, tasks both passed | Server prompt tokens |
|---|---|---|---|
| Old Codex home + MCP (10 Oct, ctx 65K) | 13/19 | 930 s (12 tasks) | 367,460 |
| Lean home, first run (18 Oct, ctx 40-49K) | 15/19 | 477 s (same 12 tasks, -49%) | 53,455 (-85%) |
| Lean home + all fixes, acceptance run (18 Oct 11:31) | **18/19** (all 19 in 711 s) | | 26,537 (-93%) |
| Then the money rule tightened: `biz-price-update` + `biz-gst-invoice` x3 | **6/6** | | |
| New engine (kq2) + governor spill fix, ctx 32K, first run (18 Oct 13:46) | 17/19 (all 19 in 540 s) | | 27,238 |
| Plus two rules: unindented patch example, 5-cent step rounding | 18/19 (all 19 in 500 s) | | 23,439 |
| Plus two rules: edge cases beyond the given tests, stray-space check in every patched file; the three flaky tasks x3 first | **9/9**, then **19/19 (all 19 in 521 s)** | | 20,765 |

On the kq2 engine the server's generation time for the whole set fell from 394 s (acceptance run) to 194-216 s.
The two first-run failures on the new engine were the stray-space patch (`+ version = ...` in `pyproject.toml`,
which TOML still parses) and a 5-cent rounding answer of 3.23 instead of 3.25; the one after that was a binary-search
fix that passed the given test but crashed on a value larger than all. Each got one generic rule in
[instructions-compact.md](../agents/codex-lean-home/instructions-compact.md).

The one acceptance failure was `biz-price-update` (3.225 rounded to 3.20 with floats although `Decimal` was imported);
it passed 3 of 3 after the rule "build Decimals from the text, never float()/round() money, hand-check one row".
Run-to-run variance is real at thinking-off: `debug-bsearch` and `biz-price-update` each failed once and passed on
other runs, so quote the acceptance run, not the best run.

Raw rows: [data/codex-eval-20261018/](../data/codex-eval-20261018/).

## Failures found and fixed (each traced in the Codex event log)

1. `tool-sha256`: correct hash, empty answer. PowerShell 5.1 `>` writes UTF-16 (bytes FF FE ...). Rule: write text with `Set-Content -Encoding ascii/utf8`.
2. `files-version-bump`: a stray leading space in a patched line. The compact prompt's own apply_patch example taught `+ line`. Example corrected, plus an explicit rule.
3. `tool-git-branch` (timed out in every earlier run, 98 commands): Codex's Windows sandbox keeps `.git` read-only. A root-level `-c sandbox_workspace_write.writable_roots=[...]` is ignored when `exec` gets `-s`; placed after `exec` it applies. Now 35 s.
4. `biz-price-update` (timed out, then wrong): the model re-ran a failing check 40 times, and later rounded money with floats (3.225 -> 3.20). Rules: never repeat a failing command unchanged; fix the output, not the check; money in cents or `Decimal` with ROUND_HALF_UP.
5. `tool-unique-suburbs`: split CSV by position and counted the wrong column. Rule: `Import-Csv` by header, sanity-check answers.
