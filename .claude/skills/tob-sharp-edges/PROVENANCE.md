# Provenance: tob-sharp-edges

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/trailofbits/skills |
| Pinned commit | `2be6433b39e009cd2b6fd3be1895f6b1faa5af9a` |
| Upstream path | `plugins/sharp-edges/skills/sharp-edges` |
| Upstream skill name | `sharp-edges` |
| Licence | CC-BY-SA-4.0 (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: trailofbits/sharp-edges |
| Vendored and vetted | 2026-10-30 |

## What it does

Finds error-prone APIs, dangerous defaults and configuration cliffs (JWT alg choice, zero/empty values that disable checks, silent failures). Use on auth, upload, config and crypto-adjacent code.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- Instructions and reference markdown only; no scripts, no network endpoints.
- `allowed-tools: Read Grep Glob` is read-only and was kept.
- Mentions a plugin-level `sharp-edges-analyzer` agent that lives outside the skill folder and is not vendored; run the workflow inline.

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
