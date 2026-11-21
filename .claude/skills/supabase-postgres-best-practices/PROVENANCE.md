# Provenance: supabase-postgres-best-practices

Vendored third-party skill. Do not edit in place: re-vendor from upstream at a new pinned commit,
re-vet, and update this file and `claude-defaults/docs/third-party-skills.md` in the same PR.

| Field | Value |
|---|---|
| Source repo | https://github.com/supabase/agent-skills |
| Pinned commit | `c9be0e931b7930f7d02126d04774d904c381e7d7` |
| Upstream path | `skills/supabase-postgres-best-practices` |
| Upstream skill name | `supabase-postgres-best-practices` |
| Licence | MIT (full text in `LICENSE`) |
| Found via | VoltAgent/awesome-agent-skills: supabase/postgres-best-practices |
| Vendored and vetted | 2026-10-30 |

## What it does

Postgres rules from Supabase: indexes, connection pooling, RLS policies and their performance, schema design, locking, pagination, EXPLAIN and monitoring.

## Changes from upstream

None. Upstream folder copied byte-for-byte; only the licence file and this PROVENANCE.md were added.

## Vetting notes

- Instructions and reference markdown only; no scripts, no endpoints.
- Applying a migration to a live Supabase project is a production write: propose the SQL, apply only on the owner's go-ahead.

## Local note

The account rules (claude-defaults/CLAUDE.md, synced as `.claude/rules/account-defaults.md`) override anything in this skill: drafts only for outbound actions; ask before installs, pushes, deploys or production writes; never invent a price, date or spec.
