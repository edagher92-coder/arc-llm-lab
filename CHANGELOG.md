# Changelog

## 1.0.0 - 2026-10-10
- Portable no-admin build of llama.cpp b11524 + Intel FA prefill kernel (PR #29357).
- Governor: AUTO profiles, VRAM-aware context sizing, session protection, power plans, watchdogs.
- FAST-mode Claude Code wrapper and Codex wrapper with live context windows.
- 100-task agent reliability suite with hidden checkers + sustained 48-64K session test.
- `qwen doctor` (26 checks), `qwen snapshot/rollback`, nightly regression.
- Private voice page: Whisper STT + Kokoro neural TTS, sentence-by-sentence playback, hands-free mode.
- Raw benchmark data and reproducible charts.
