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

The hidden tests are cumulative: each step's check runs every earlier test as well, so one early slip fails every later step. To keep that from hiding later work, each step is also scored on **its own test only** (`new_test_passed` in the record; the report's "This step's own test" column). The cumulative `passed` result stays as the regression check. For steps 1 to 8, when the cumulative check fails, the harness re-runs it with the earlier tests switched off to get the own-step result (own-step results are independent of the earlier steps' tests, provided earlier modules import), and the step 5 prompt states the loader return types explicitly (`load_machines(path) -> list[Machine]`, `load_bookings(path) -> list[Booking]`, plain lists in file order), because an earlier version left them ambiguous and a correct-looking answer could fail the hidden test. Results from runs made before this change have no own-step column.

**Tiers:**

- **Autonomous:** at least 90% pass.
- **Supervised:** 60–89%.
- **Escalate to a stronger model:** under 60%.

These apply per category, and per task across runs.

## Results (2026-10-10, raw records in [evalsuite/results/](../evalsuite/results/))

### 100-task suite at a 32K client window

| Run | Passed | 95% CI (Wilson) | Completed tasks/min | Median time per passing task | Prompt-cache hit | Prompt tokens per pass |
|---|---|---|---|---|---|---|
| **Claude Code 2.1.295** (production config) | **97/100** | 91.5–99.0% | **1.54** | 24 s | 92.2% | 3.4K |
| **Codex CLI 0.153.4** | **95/100**¹ | 88.8–97.8% | 0.62 | 70 s | 83.7% | 18.2K |
| Claude Code, "v2" config (rejected) | 93/100² | 86.3–96.6% | 1.13 | 24 s | 91.4% | 4.0K |

Both are single runs on the same machine: 0 context overflows, 0 failures caused by timeouts or reloads in the production runs, minimum free VRAM 1.19 GiB.
¹ 94 recorded; `files-extract-emails` was correct but the file began with a UTF-8 byte-order mark written by PowerShell. The checker now accepts a BOM (`tasks.rd` reads `utf-8-sig`) and the verdict was re-checked on the kept workspace ([rescore-bom.json](../evalsuite/results/rescore-bom.json)).
² The v2 config added a "definition of done" system-prompt rule and extra Claude Code environment settings. 3 tasks were disturbed by an accidental model swap during the run (91/97 on the clean tasks), and one new failure mode appeared: Claude Code's auto-compaction returned an empty summary (`long-contract-clause`). Lower pass rate and fewer tasks/min, so **v2 was not adopted**; the production config is unchanged. Prompt-only rules did not fix the "answer not saved" failures.

Codex is about 2.5× slower per task here mainly because each Codex request carries a much larger prompt (18K vs 3.4K prompt tokens per passing task), which a local GPU feels directly.

### Failures, by kind

| Kind | Claude Code (production) | Codex |
|---|---|---|
| Found the answer, did not write the required file | 2 (`long-needle-log`, `long-contract-clause`) | 1 (`recover-circular-import`) |
| Wrong result | 0 | 2 (`biz-price-update`, `tool-unique-suburbs`) |
| Timed out | 0 | 2 (`tool-git-branch`, `debug-bsearch`) |
| **Destructive** (overwrote a file with another file's content, reported success) | **1** (`files-tabs-to-spaces`) | 0 |

### Tiers (pooled over both agents; single runs, so provisional)

| Category | Pass rate | Attempts | Tier |
|---|---|---|---|
| Coding | 100% | 40 | Autonomous (provisional) |
| Debugging | 97.5% | 40 | Autonomous (provisional) |
| Business tasks | 95% | 20 | Autonomous (provisional) |
| Error recovery | 95% | 20 | Autonomous (provisional) |
| File operations | 96.7% | 30 | **Supervised** (one destructive failure caps it) |
| Tool calling | 93.3% | 30 | Supervised |
| Long-context retrieval | 90% | 20 | Supervised |

"Autonomous" here means: run unattended **inside a checkpointed workspace** (commit or snapshot first). With 20–40 attempts per category the lower confidence bound is still under 90%, so treat these as working tiers, not guarantees. Nothing scored low enough to need escalation to a stronger model; escalate anyway for multi-repo refactors, anything irreversible, and anything touching money or production.

### Sustained sessions (10 dependent steps, 14K-token spec, rules change at step 9, memory probe at step 10)

| Run | Result |
|---|---|
| **Codex, 48K window** | **10/10**: every step's own test passed, the v2 rules change was applied everywhere, and the step-10 memory probe was correct³ |
| **Codex, 64K window** | **10/10** (same) |
| Claude Code, 48K and 64K (first run) | Steps 1–4 passed; steps 5–10 **invalid**: the step-5 prompt never said "return a list", the model reasonably returned a dict, and cumulative tests then failed every later step on that one test. The prompt now states the return type and each step's own test is scored separately (provided earlier modules import). A re-run on the fixed spec is in progress and will be added here. The 48K run's memory probe at step 10 was correct. |

³ The probe answer was written with a BOM and re-scored after the checker fix, like the 32K task above.

**What this shows:** a single Arc Pro B60 running Qwen3.8-27B can carry a 10-step, 48–64K-token agent session to the end, including a mid-session rules change and recall of a fact given 9 steps earlier, without silent truncation. Claude Code compacted 2–12 times during these sessions; Codex 0–2 times.

## Context safety: how silent truncation is prevented

1. **`--no-context-shift` on the server.** The flag is passed explicitly, and in llama.cpp b11524 context shift is also disabled by default (per its server README). Overflow returns HTTP 400 `exceed_context_size_error` instead of quietly dropping the oldest tokens ([overflow_test.py](../evalsuite/overflow_test.py)).
2. **Client window = server context − 8K.** The agents auto-compact before the server could overflow (`qwen window`).
3. **Session protection in the governor.** It records the largest live prompt in the last 60 minutes. If VRAM pressure forces a reload, `launch.ps1` raises the new context to at least that size + 8K, down to an emergency floor of 1.15 GiB free. If even that can't fit, the client gets an explicit error, never a silently shorter context.
4. **Memory probe.** The sustained-session test checks that compaction kept what mattered. Compaction itself is done by the agent (Claude Code or Codex summarising the conversation), not by the server, so a summary can legitimately lose detail; that is what the probe measures.

## Reproduce

```powershell
cd evalsuite
python selftest.py                                   # validate checkers first
powershell -File ..\evalsuite\run.ps1 -Agent claude -Cap 32768
python sustained.py --agent claude --cap 65536
python report.py                                     # results\report.md + summary.json
```
