# Provenance: tob-variant-analysis

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/trailofbits/skills |
| Pinned commit | `2be6433b39e009cd2b6fd3be1895f6b1faa5af9a` |
| Upstream path | `plugins/variant-analysis/skills/variant-analysis` |
| Upstream skill name | `variant-analysis` |
| Licence | CC-BY-SA-4.0 (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: trailofbits/variant-analysis |
| Vendored and vetted | 2026-10-30 |

## What it does

After one bug is found, hunts the other instances of the same root cause across the codebase, optionally as CodeQL or Semgrep queries.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- Instructions, references and query templates (`resources/codeql/*.ql`, `resources/semgrep/*.yaml`); templates are data, nothing is executed by the skill.
- CodeQL/Semgrep are only used if already installed; installing them is a separate decision for the owner.

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
