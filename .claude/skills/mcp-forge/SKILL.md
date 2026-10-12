---
name: mcp-forge
description: >
  Build, extend, or debug an MCP server to the house standard (FastMCP
  pattern, typed single-purpose tools, forced-tool-choice structured outputs).
  Use when creating the hq-orchestrator server, wrapping a CLI/API as MCP
  tools, or fixing tool-schema validation errors. Not for consuming existing
  MCP servers — that's native tool use.
---

# mcp-forge — MCP server construction

Distilled from `modelcontextprotocol/servers`, `modelcontextprotocol/python-sdk`,
`anthropics/anthropic-sdk-python` (all MIT).

## House standard (the extracted logic)

1. **Small, typed, single-purpose tools.** One tool = one verb on one noun
   (`delegate_task`, `read_artifact`) — never a `do_things(action=...)`
   multiplexer. Schemas from typed signatures, every param described, enums
   over free strings.
2. **FastMCP skeleton** (the entire boilerplate you need):
   ```python
   from mcp.server.fastmcp import FastMCP
   mcp = FastMCP("hq-orchestrator")

   @mcp.tool()
   def delegate_task(run_id: str, task_envelope: dict, timeout_seconds: int = 600) -> dict:
       """Dispatch a task envelope to a worker model; returns the result envelope."""
       ...
   if __name__ == "__main__":
       mcp.run()  # stdio transport
   ```
3. **Resources vs tools split**: read-only browsable state (run logs,
   STATE.json) = resources; anything with side effects = tools.
4. **Guaranteed-parse worker outputs**: when a tool itself calls a model,
   force tool choice on a submit-tool whose schema is the result envelope —
   never parse free text.
5. **Fail loud and typed**: validate inputs against the JSON Schema before
   doing work; return JSON-RPC `-32602` on bad envelopes. Path args are
   resolved and prefix-checked (no traversal).
6. **Secrets via env only**; the server never logs them.

## Procedure

1. Define the tool table first (name, one-line purpose, schema) — get it
   audited before writing code.
2. Generate the FastMCP server; one module per tool group.
3. Write the smoke test: spawn over stdio, `tools/list`, one happy call, one
   schema-reject call.
4. Register in `.mcp.json`; verify discovery from a fresh session.

## Verification

- `tools/list` shows exactly the designed table; smoke tests pass; a
  deliberately malformed call returns `-32602`, not a stack trace.
