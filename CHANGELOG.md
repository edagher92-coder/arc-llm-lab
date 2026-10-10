# Changelog

## 2.1.1 - 2026-10-10
**Presentation and reach**
- README first screen rebuilt: headline results, who it is for (measured vs estimate), one command to try, and how to submit your card's numbers.
- Every guide is now its own page on the GitHub Pages site (`docs/guides/`), with descriptions, canonical URLs, breadcrumbs and FAQ structured data, all listed in the sitemap. The build stays deterministic.
- Easier result submissions: the benchmark scripts print the raw output path and copy the result JSON to the clipboard, warn about a placeholder driver field and suggest smaller depths on 12GB cards. The form's duplicated fields are optional, and `-Mmvq` / `--mmvq` is documented as the setting the maintainer's results use.
- New `SUPPORT.md`, a "Show and tell" discussion form and a Discussions link on the new-issue page.

## 2.1.0 - 2026-10-10
**New**
- `docs/TOOL-CALLING.md`: what tool schemas cost on a local model, a measured tool-bundle cache test (`bench/bundle-cache-test.py`: appending tools reuses the cached prefix, 7.6 s instead of a cold 15.6 s; returning to a known bundle takes 1.5 s), and loading rules for Open WebUI, Claude Code and Codex.
- `bench/regression.ps1` logs per-turn new-prompt and cached tokens to `turns.csv`, so cache misses are visible. A re-run with logging passed at 57.3 s (baseline 54.9 s); two earlier runs at 84-89 s are unexplained, most likely a partial cache miss.

**Fixes from a 10-lane review**
- Eval harness: clean-exit wrong answers from Codex are no longer `api_error`; max-turns is classified before the log scan; checker crashes are `checker_error`; a failed metrics scrape records `None`, not the server's lifetime total; a sustained step that hit the timeout no longer counts as passed; the report applies the BOM re-scores and flags a memory probe with no compaction as not exercised.
- Checkers (suite 1.2): `recover-env-var` re-runs app.py, so a hand-written out.txt cannot pass; `code-postcode` tests the 2235-2599 and ACT boundaries; `files-version-bump` accepts a missing final newline; `recover-missing-module` matches whole numbers.
- `qwen window` falls back to 24576, not 100000, if the governor status file can't be read.
- Voice: cancelling during transcription really cancels; a double tap can't start two recorders; no auto-listen after a cancel; browser-voice errors no longer leave the orb stuck; one meter loop instead of one per sentence; TTS requests time out after 15 s.
- Site: honest description (42.3 tok/s is eval-suite throughput), shorter title, keywords limited to what the repo covers, charts survive a missing data series, contributor links checked client-side too; link checker covers issue forms.
- Wrappers: the published `claude-qwen.cmd` matches the production config (the rejected "v2" settings are removed); `codex-qwen.cmd` documents `MCPOFF`.
- Docs: TOKEN-EFFICIENCY no longer lists rejected settings as active; B70 KV headroom corrected to about 11.5 GiB; small number fixes in RELIABILITY.

## 2.0.1 - 2026-10-10
**Results**
- Claude Code sustained sessions on the fixed spec: **10/10 at 48K**, **9/10 at 64K**. At 64K, steps 1-9 passed and the step-10 memory probe came back `UNKNOWN`: the agent's compaction summary dropped a fact given only in conversation. No server overflow, reload or truncation in either run.
- New rule in RELIABILITY.md: put must-keep facts in a workspace file (`CLAUDE.md`, `AGENTS.md`, `NOTES.md`); long sessions are Supervised for facts held only in conversation.
- Cache-switch test (`bench/cache-switch-test.py`): after a short unrelated chat on the single slot, a 36K-token agent prompt resumed in 6.5 s instead of 87.6 s (19 tokens re-processed, 36,432 restored from the host-RAM prompt cache).

**Fixes from a four-lane code review**
- Governor: the model's own VRAM is no longer counted as "other apps" (it caused a bogus LEAN and an unload); the watchdog restarts the stack only when llama-swap stops answering, not on any API error; prewarm counts as activity; idle prewarm reloads the default variant; one failed GPU counter read no longer triggers an unload; `doctor` engine check runs again (`R` alias clash); emergency-floor re-fit loop prevented; atomic `status.json`.
- Eval suite: clean-exit wrong answers are no longer labelled `api_error`; checkers read UTF-16 and BOM files; Claude compaction counts are no longer doubled (true counts quoted in RELIABILITY.md); a memory probe written to a file now fails; passes that needed a timeout kill are excluded from speed medians; results files are never silently overwritten.
- `bench/regression.ps1`: a crashed test can no longer report PASS.
- Voice: tapping the orb stops speech; one TTS failure no longer disables neural voice for the session; chunked uploads and bad JSON handled in `tts_server.py`.
- Site and tools: contributor URLs need http(s); community table cells escaped; chart labels no longer clipped; accessibility fixes; CI hardening.
- `agents/claude-qwen.cmd` also finds Claude Code installed by the Microsoft Store (MSIX) desktop app.

**Follow-up fixes (second review, same day)**
- `bench/regression.ps1`: a misplaced comment in the 2.0.1 fix had switched off the coding/tools pass checks; restored.
- Voice: three TTS failures in a row (not one) switch to the phone voice; tapping the orb while it speaks also stops the stream; a voice preview un-mutes.
- `recover-encoding` checker reads the output as strict UTF-8 again (the cp1252 fallback let a half-fix pass).
- `sustained.py` refuses to overwrite before it wipes the old workspace; `report.py` halves the double-counted compactions in older Claude records.
- Governor never learns the "other apps" VRAM figure while a model is still starting.

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
