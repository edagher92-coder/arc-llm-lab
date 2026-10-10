# Tool calling with a local model: what it costs and how to load tools

Measured on one Intel Arc Pro B60 with Qwen3.8-27B (llama.cpp b11524, one slot, 2026-10-10). The short version: **tools are part of the prompt prefix, so load few, load them in a fixed order, add rather than swap, and keep the set stable for the whole chat.**

## Why tools are expensive here

Qwen's chat template writes every tool definition at the very start of the prompt, before the system message:

```jinja
{%- if tools and tools is iterable and tools is not mapping %}
    {{- '<|im_start|>system\n' }}
    {{- "# Tools\n\nYou have access to the following functions:\n\n<tools>" }}
    {%- for tool in tools %}{{- "\n" }}{{- tool | tojson }}{%- endfor %}
```

Two consequences:

1. **Every loaded schema is paid for on every request.** It is cheap only while the server can reuse it from cache.
2. **Changing the tool set changes the prefix.** Everything after the first changed byte, which means the whole conversation, has to be read again. At about 500 tok/s on short prompts and 420 tok/s at 32K, a 20K-token chat costs about 40 s to re-read.

## Measurements

**Tool sets in Open WebUI** (FAST profile, prompt tokens of the first message; measured in a parallel session on the same PC):

| Tools loaded | Prompt tokens | First message, prompt time |
|---|---|---|
| Open WebUI built-ins only (cached) | 5,350 | 0.65 s |
| Built-ins + time, files, library docs, fetch | 7,849 | 15.6 s |
| Built-ins + browser + PC agent (Claude Code tools) | 18,457 | 38.9 s |

The PC agent's tools are not equal. Sizes of their OpenAPI definitions as served by mcpo: Bash 10.5 KB, PowerShell 9.0 KB, Monitor 7.4 KB, Read 2.3 KB, WebFetch 2.1 KB, PushNotification 2.0 KB, Skill 2.0 KB, Edit 1.6 KB, Grep 1.4 KB, Write 1.1 KB, Glob 0.9 KB. On Windows one shell (PowerShell) is enough, and Monitor and PushNotification are no use from a phone, so dropping Bash, Monitor and PushNotification removes about half of the PC agent's schema (20 of 40 KB).

**Switching tool bundles** ([bench/bundle-cache-test.py](../bench/bundle-cache-test.py), [result](../bench/results/bundle-cache-result.json)). Bundle A is about 6.8K tokens of tool schemas; bundle B is A with more tools **appended**:

| Step | Prompt tokens | Read from scratch | Restored from cache | Wall time |
|---|---|---|---|---|
| Bundle A, cold | 6,777 | 6,777 | 0 | 15.6 s |
| Switch to B (A + extra tools) | 9,703 | 3,186 | 6,517 | 7.6 s |
| Back to A, new chat | 6,779 | 262 | 6,517 | 1.5 s |
| A, follow-up message | 6,795 | 33 | 6,762 | 1.1 s |

So:

- **Appending tools only costs the new tools**, because the old ones are still a byte-identical prefix. Inserting or re-ordering would have cost everything after the change.
- **Going back to a bundle used before is nearly free.** llama-server's host-RAM prompt cache (`--cache-ram`, default 8192 MiB in b11524) keeps earlier prefixes. The same mechanism let a 36K-token agent prompt resume in 6.5 s instead of 87.6 s after a phone chat ([PLATFORM.md](PLATFORM.md)).

## Rules that follow

1. **Fixed order, core first.** Always emit the core tools first and in the same order; add extra tools at the end.
2. **Sticky per chat.** Decide early, escalate at most once, never remove a tool mid-chat. Removing one rewrites the prefix just like adding one in the middle.
3. **A few fixed bundles, not per-message mixes.** Each bundle the cache has seen is fast to come back to. Free-form combinations are always cold.
4. **Trim schemas you never use.** In mcpo use `disabledTools` (exact names); in Open WebUI turn off built-in tool categories a model doesn't need.
5. **Use native function calling.** Open WebUI's docs say Native mode is the default since v0.10 and passes tools as structured definitions, while Legacy mode injects a prompt that changes every turn and breaks cache reuse ([docs](https://docs.openwebui.com/features/extensibility/plugin/tools/)).
6. **Coding agents:** Claude Code with `--strict-mcp-config` and one MCP server, and Codex with unused MCP servers switched off (`MCPOFF` in [codex-qwen.cmd](../agents/codex-qwen.cmd)). On the eval runs Codex's fixed prefix was about 15.8K tokens per request against about 6.5K for Claude Code, and Codex re-read it at the start of every task.

## Where tool calls actually failed

From the 100-task runs ([RELIABILITY.md](RELIABILITY.md)): 16 failure records across three runs (production Claude Code, Codex, and the rejected "v2" Claude config), one of them later re-scored as a pass:

| Pattern | Count | What would help |
|---|---|---|
| Found the answer, did not write the required file | 5 | A harness or wrapper check that the output file exists before the agent stops. A prompt rule alone did not fix it (the rejected "v2" config). |
| Wrong file content written over another file, reported as verified | 3 | Bulk edits through a script that reads and writes each file in place, with a diff check |
| Looping or a hung foreground command until timeout | 3 | Per-command timeouts and a turn cap |
| Other: rounding, counted rows instead of distinct values, empty compaction summary, a model swap, a BOM (re-scored) | 5 | Case by case |

None of these was a malformed tool call. Picking and formatting tools was not the weak point; finishing the job and not damaging files was.

## Direction: a lazy tool gateway

The pattern that removes the trade-off is a gateway with a constant, tiny tool surface: a few pinned basics plus `search_tools(query)` and `call_tool(name, arguments)`. The prompt prefix never changes, unused tools cost nothing, and a search result lands at the end of the conversation, where it does not break the cache. It is the same idea as [Anthropic's tool search](https://www.anthropic.com/engineering/advanced-tool-use), and FastMCP ships it as `BM25SearchTransform`.

A prototype exists (FastMCP proxy, BM25 ranking with aliases, a guard with deny rules, rate limits, a kill switch and a hash-chained audit log). It is not deployed or published yet: tools that act on the desktop, a logged-in browser or the shell, called automatically from a phone, need an owner decision on how much runs without confirmation.

## How this was worked out

Ten Haiku agents reviewed the stack in parallel, each with a 7 to 10 minute budget and a 25-call cap, and reported in 1.5 to 5 minutes. Sonnet agents did the research and the deeper reviews, and Opus checked each finding before applying it. That check mattered. One "HIGH" finding, that the governor's error handling could never catch a failed API call, was disproved by a one-line test on the PC. Another, that the gateway's deny rules failed open because of letter case, was confirmed and fixed.
