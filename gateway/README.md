# Tool gateway

A lazy MCP gateway for a local model used from a phone through Open WebUI and mcpo. Seven pinned tools plus `search_tools` / `call_tool` sit in front of about 100 tools, with PIN approvals, `skills`, `share_file` links and a guard.

Read [docs/GATEWAY.md](../docs/GATEWAY.md) for the design, the 10/10 phone eval and the install steps.

| File | Purpose |
|---|---|
| `gateway.py` | Proxy, search, harness descriptions, guard, audit |
| `approvals.py` | PIN approvals page, profile switch, outbox route |
| `skills.py`, `outbox.py` | `skills` and `share_file` tools |
| `prompts/phone-system.md` | Phone system prompt |
| `gateway.example.json` | Config template: copy it to `gateway.json` (git-ignored) and add your tokens there |
| `openwebui/` | Open WebUI filters: live stats and the phone prompt |
| `tests/` | Unit tests (CI) and `phone_eval.py` (needs the PC stack) |
