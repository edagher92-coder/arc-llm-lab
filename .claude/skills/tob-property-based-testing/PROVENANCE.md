# Provenance: tob-property-based-testing

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/trailofbits/skills |
| Pinned commit | `2be6433b39e009cd2b6fd3be1895f6b1faa5af9a` |
| Upstream path | `plugins/property-based-testing/skills/property-based-testing` |
| Upstream skill name | `property-based-testing` |
| Licence | CC-BY-SA-4.0 (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: trailofbits/property-based-testing |
| Vendored and vetted | 2026-10-30 |

## What it does

Writes and reviews property-based tests (Hypothesis, fast-check): roundtrip, idempotence, invariant and oracle properties for parsers, normalisers, Decimal and money maths.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- Instructions and reference markdown only; no scripts.
- Says itself that adding a PBT library is the user's decision (offer once, accept the answer).

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
