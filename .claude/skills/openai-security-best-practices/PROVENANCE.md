# Provenance: openai-security-best-practices

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/openai/skills |
| Pinned commit | `49f948faa9258a0c61caceaf225e179651397431` |
| Upstream path | `skills/.curated/security-best-practices` |
| Upstream skill name | `security-best-practices` |
| Licence | Apache-2.0 (full text in `LICENSE.txt`) |
| Found via | VoltAgent/awesome-agent-skills: openai/security-best-practices |
| Vendored and vetted | 2026-10-30 |

## What it does

Framework-specific secure-coding references (Express, Next.js, React, Vue, FastAPI, Flask, Django, Go) for secure-by-default code and on-request security reports.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- Reference markdown only; links point to OWASP, MDN and framework docs (no data-receiving endpoints).
- Its `Overrides` section says to respect documented project exceptions. The account rules still take precedence over anything in this skill.
- Complements the in-house `security-audit`; use this for the per-framework rule text.

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
