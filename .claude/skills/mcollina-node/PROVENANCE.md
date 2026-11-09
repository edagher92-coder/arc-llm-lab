# Provenance: mcollina-node

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/mcollina/skills |
| Pinned commit | `c75d70dbfbe991d8cec42aeda0b64ff14fbb9ac7` |
| Upstream path | `skills/node` |
| Upstream skill name | `node` |
| Licence | MIT (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: mcollina/skills (community collection) |
| Vendored and vetted | 2026-10-30 |

## What it does

Node.js practice from a Node TSC member: error handling, graceful shutdown, streams, caching, flaky and stuck `node --test` runs, profiling, env config, TypeScript type stripping.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- Instructions and reference markdown; `rules/assets/*.ts` are illustrative examples and are not executed by the skill.
- `rules/profiling.md` shows unpinned `npx @platformatic/flame` and `npx autocannon`; pin a version and ask before running them.
- Recommends Node 22.6+ type stripping; respect each repo's pinned runtime (for example Node 20 in CI).

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
