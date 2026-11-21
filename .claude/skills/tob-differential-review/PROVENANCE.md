# Provenance: tob-differential-review

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/trailofbits/skills |
| Pinned commit | `2be6433b39e009cd2b6fd3be1895f6b1faa5af9a` |
| Upstream path | `plugins/differential-review/skills/differential-review` |
| Upstream skill name | `differential-review` |
| Licence | CC-BY-SA-4.0 (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: trailofbits/differential-review |
| Vendored and vetted | 2026-10-30 |

## What it does

Security-focused review of a PR, commit or diff: risk triage, git-blame history, blast radius, test-coverage gaps, written report.

## Changes from upstream

Frontmatter only: `Bash` removed from `allowed-tools`, so shell commands go through the normal permission prompt instead of being pre-approved while the skill is active. Body unchanged. Under CC-BY-SA-4.0 this adapted SKILL.md is shared under the same licence; the change is indicated here as the licence requires.

## Vetting notes

- Instructions and reference markdown only; no scripts, no network endpoints.
- Writes a markdown report file into the working tree; do not commit it unless asked.
- Mentions `differential-review:adversarial-modeler`, `audit-context-building` and `issue-writer`, which are not vendored; do those steps inline.

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
