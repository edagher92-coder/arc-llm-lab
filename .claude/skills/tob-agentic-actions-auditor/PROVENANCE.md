# Provenance: tob-agentic-actions-auditor

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/trailofbits/skills |
| Pinned commit | `2be6433b39e009cd2b6fd3be1895f6b1faa5af9a` |
| Upstream path | `plugins/agentic-actions-auditor/skills/agentic-actions-auditor` |
| Upstream skill name | `agentic-actions-auditor` |
| Licence | CC-BY-SA-4.0 (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: not individually listed; same vendor repo as the listed trailofbits/* skills |
| Vendored and vetted | 2026-10-30 |

## What it does

Audits GitHub Actions workflows that run AI agents (Claude Code Action, Codex, Gemini CLI, AI Inference) for prompt-injection paths, pull_request_target misuse, dangerous sandbox flags and wildcard allowlists.

## Changes from upstream

Frontmatter only: `Bash` removed from `allowed-tools`, so shell commands go through the normal permission prompt instead of being pre-approved while the skill is active. Body unchanged. Under CC-BY-SA-4.0 this adapted SKILL.md is shared under the same licence; the change is indicated here as the licence requires.

## Vetting notes

- Instructions and reference markdown only; report-only, explicitly does not modify workflow files.
- Remote mode uses read-only `gh api` calls and carries its own rule never to pipe fetched YAML to a shell or interpreter.
- No endpoints other than the GitHub API through the owner's authenticated `gh`.

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
