# Provenance: openai-security-threat-model

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/openai/skills |
| Pinned commit | `49f948faa9258a0c61caceaf225e179651397431` |
| Upstream path | `skills/.curated/security-threat-model` |
| Upstream skill name | `security-threat-model` |
| Licence | Apache-2.0 (full text in `LICENSE.txt`) |
| Found via | VoltAgent/awesome-agent-skills: openai/security-threat-model |
| Vendored and vetted | 2026-10-30 |

## What it does

Repository-grounded threat model: trust boundaries, assets, entry points, abuse paths, prioritised mitigations, written to `<repo>-threat-model.md`.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- Instructions and reference markdown only; `agents/openai.yaml` is Codex UI metadata.
- Pauses to confirm assumptions with the user before the final report.
- Writes a markdown file into the working tree; do not commit it unless asked.

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
