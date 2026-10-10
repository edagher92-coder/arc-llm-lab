# Changelog

## 2.0.0 - 2026-10-10
**Results**
- Agent eval finished: Claude Code @32K **97/100** (1.54 completed tasks/min, 92% prompt-cache hit); Codex @32K **95/100** (0.62 tasks/min). Raw records in `evalsuite/results/`.
- Sustained 10-step sessions: Codex **10/10 at 48K and 64K**, including a mid-session rules change and a step-10 memory probe.
- Tested a "v2" agent config (definition-of-done prompt rule + extra Claude Code settings): 93/100 and slower, so it was **not adopted**.

**Harness fixes found by the eval**
- Sustained test step 5 now states the return type; each step's own test is scored separately from regressions.
- Checkers accept a UTF-8 BOM (PowerShell writes one); affected verdicts re-checked (`rescore-bom.json`).

**New**
- Intel FA prefill patches vendored in `engine/patches/` with SHA-256 sums (upstream PR #29357 was closed unmerged).
- One-command benchmark scripts (`bench/arc-bench.ps1`, `bench/arc-bench.sh`), community result schema and issue forms.
- Platform guide: Open WebUI hub with MCP tools (incl. Claude Code tools via `claude mcp serve`), phone access over Tailscale, local voice (`docs/PLATFORM.md`).
- Token-efficiency guide (`docs/TOKEN-EFFICIENCY.md`), peer comparison (`docs/PEERS.md`), card-fit guide for B580/B570/B50/A770/B70, concept explainer (`docs/HOW-IT-WORKS.md`).
- SEO: canonical/OG/Twitter meta, JSON-LD, sitemap, robots; CITATION.cff; CI selftest on Ubuntu and Windows.

**Corrections**
- 42.3 tok/s is now defined precisely (eval-suite throughput incl. prompt processing); per-request decode is 47–58 tok/s.
- Provenance footnotes for figures without raw logs; scrubbed private names from task text and history.

## 1.0.0 - 2026-10-10
- Portable no-admin build of llama.cpp b11524 + Intel FA prefill kernel (PR #29357).
- Governor: AUTO profiles, VRAM-aware context sizing, session protection, power plans, watchdogs.
- FAST-mode Claude Code wrapper and Codex wrapper with live context windows.
- 100-task agent reliability suite with hidden checkers + sustained 48-64K session test.
- `qwen doctor` (26 checks), `qwen snapshot/rollback`, nightly regression.
- Private voice page: Whisper STT + Kokoro neural TTS, sentence-by-sentence playback, hands-free mode.
- Raw benchmark data and reproducible charts.
