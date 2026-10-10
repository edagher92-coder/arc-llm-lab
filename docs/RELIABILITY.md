# Can a local 27B on one Arc B60 be a dependable daily agent?

Tokens per second are easy to measure and easy to over-value. The question that matters is how many real tasks the agent completes correctly per minute, without a human stepping in, and which kinds of task are safe to leave unattended.

## Method

**Suite:** [evalsuite/tasks.py](../evalsuite/tasks.py), 100 tasks generated deterministically from fixed seeds.

| Category | Tasks | Examples |
|---|---|---|
| Coding | 20 | merge intervals, LRU cache, ABN checksum, GST breakdown, business days, RFC-4180 CSV parser, token bucket |
| Debugging | 20 | off-by-one pagination, mutable default argument, dd/mm vs mm/dd, late-binding closures, CSV newlines on Windows, `is` vs `==` |
| Tool use | 15 | count log levels, SHA-256, pytest failure count, git history question, create a branch and commit, zip archive |
| File operations | 15 | rename/organise, version bump (not the dependency pins), CSV↔JSON, deep-merge config, project-wide rename, CRLF→LF |
| Long-context | 10 | needle in a 20,000-line log with decoys, aggregates over 10,000 CSV rows, nested config path, which module really calls X |
| Business maths | 10 | per-line GST rounding, booking conflicts, reorder quantities, tiered discounts, bank reconciliation, payroll overtime, aged receivables |
| Error recovery | 10 | missing internal package (stdlib only), wrong path, typo'd command, malformed JSON, two stacked bugs, env var, Windows encoding, infinite loop, circular import |

**Hidden checkers.** Each task's checker runs after the agent exits and is never visible to it. Tests are written fresh, scripts are re-run from a clean state, and outputs are compared byte for byte or numerically. [selftest.py](../evalsuite/selftest.py) proves every checker **fails an untouched workspace** and **passes an independent reference solution**. Current status: 100/100 references pass; 98/100 untouched workspaces fail. The 2 that pass untouched on Linux test Windows-only bugs, and they fail as expected on Windows.

**Runner.** [runner.py](../evalsuite/runner.py) gives each task a fresh workspace and a hard timeout, and records:

- pass/fail and the failure reason (`timeout`, `context_overflow`, `max_turns`, `api_error`, `agent_error`, `asked_user`, `answer_not_saved`, `wrong_result`);
- wall time and turns;
- client and server token counts;
- the minimum free VRAM seen;
- the loaded context size;
- whether the model reloaded mid-task.

**Agents:** Claude Code (`claude-qwen`, FAST mode) and Codex (`codex-qwen`), each at a 32K client window, run one after the other on the same server.

**Sustained sessions:** [sustained.py](../evalsuite/sustained.py) runs one continuous conversation of 10 dependent steps, building a small package against a 14K-token requirements document. At step 9 the pricing rules change. At step 10 the agent must recall a code it was given only in conversation at step 1, which detects silent context loss after compaction. It runs at 48K and 64K windows and records peak live prompt size (from llama-server `/slots`), compactions, overflow errors and reloads.

**Tiers:**

- **Autonomous:** at least 90% pass.
- **Supervised:** 60–89%.
- **Escalate to a stronger model:** under 60%.

These apply per category, and per task across runs.

## Results

> Run in progress (Claude Code 32K, 68 of 100 done: **66 passed**, 1.72 completed tasks/min, minimum free VRAM 1.19 GiB, 0 model reloads, 0 context overflows). Final tables for both agents and the sustained sessions are added when the queue finishes.

Early pattern: both failures so far are `answer_not_saved`. The agent found the correct answer and stated it, but never wrote the requested file. That's an instruction-following gap, not a reasoning one, and it is exactly what a "definition of done" rule in the system prompt targets (see [agents/claude-local/LOCAL-SYSTEM.md](../agents/claude-local/LOCAL-SYSTEM.md)).

## Context safety: how silent truncation is prevented

1. **`--no-context-shift` on the server.** Overflow returns HTTP 400 `exceed_context_size_error` instead of quietly dropping the oldest tokens ([overflow_test.py](../evalsuite/overflow_test.py)).
2. **Client window = server context − 8K.** The agents auto-compact before the server could overflow (`qwen window`).
3. **Session protection in the governor.** It records the largest live prompt in the last 60 minutes. If VRAM pressure forces a reload, `launch.ps1` raises the new context to at least that size + 8K, down to an emergency floor of 1.15 GiB free. If even that can't fit, the client gets an explicit error, never a silently shorter context.
4. **Memory probe.** The sustained-session test checks that compaction kept what mattered.

## Reproduce

```powershell
cd evalsuite
python selftest.py                                   # validate checkers first
powershell -File ..\evalsuite\run.ps1 -Agent claude -Cap 32768
python sustained.py --agent claude --cap 65536
python report.py                                     # results\report.md + summary.json
```
