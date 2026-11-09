# Provenance: addy-accessibility

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/addyosmani/web-quality-skills |
| Pinned commit | `afa8da942115f2961fdbfa80807ea0b232ff6c00` |
| Upstream path | `skills/accessibility` |
| Upstream skill name | `accessibility` |
| Licence | MIT (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: addyosmani/accessibility |
| Vendored and vetted | 2026-10-30 |

## What it does

WCAG 2.2 accessibility audit and fixes for customer-facing web pages: semantics, forms, focus, contrast, ARIA live regions, keyboard paths.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- Instructions and reference markdown only; HTML comments in references are code-example labels.
- One unpinned `npx lighthouse` example; pin a version and ask before running.
- Links to a sibling `web-quality-audit` skill that was not vendored (overlaps `cf-web-perf`).

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
