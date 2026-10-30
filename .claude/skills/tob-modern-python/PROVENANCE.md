# Provenance: tob-modern-python

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/trailofbits/skills |
| Pinned commit | `2be6433b39e009cd2b6fd3be1895f6b1faa5af9a` |
| Upstream path | `plugins/modern-python/skills/modern-python` |
| Upstream skill name | `modern-python` |
| Licence | CC-BY-SA-4.0 (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: trailofbits/modern-python |
| Vendored and vetted | 2026-10-30 |

## What it does

Modern Python project tooling: uv, ruff, ty, pytest, PEP 723 scripts, pre-commit (prek), detect-secrets, zizmor, pip-audit, Dependabot.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- FLAGGED for the owner: `references/uv-commands.md` and `references/security-setup.md` reproduce the vendors' official installer one-liners (`curl ... | sh` and PowerShell `irm ... | iex`). They are documentation, not steps the skill runs, but they are pipe-to-shell installs.
- Also documents `uv publish` and `uvx cookiecutter gh:trailofbits/cookiecutter-python` (fetches a remote template).
- Migration section deletes requirements.txt and venvs, but only when the user asks for a migration.
- The plugin's `hooks/` and shims (which wrap pip/python) live outside the skill folder and were NOT vendored.

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
