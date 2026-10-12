---
name: skill-router
description: |
  [OPS] Rank the available Claude Code skills against a natural-language request
  using the auto-registering skill_router CLI (stdlib-only, zero config), and
  regenerate a skills INDEX.md from the live registry. Works in any project —
  the package is bundled alongside this file.
  Use when the user says "which skill should I use", "route this request",
  "list all skills", or "regenerate the skills index".
---

# Skill router (global / user-level copy)

The router reads every `*/SKILL.md` under a skills directory as its routing
table — no hand-maintained config. Drop a new `SKILL.md` on disk and it
registers automatically. This copy ships the `skill_router/` Python package
in this same directory, so it works in **any** project, including brand-new
ones with nothing vendored.

## How to invoke

1. **Repo has its own copy** (`skill_router/` at the repo root, or
   `src/skill_router/` in the Snow Flow monorepo): prefer it —
   `python -m skill_router "query"` from the repo root
   (prefix `PYTHONPATH=src` for the monorepo).
2. **Anywhere else** (new project, no vendored copy): use the bundled package —

   ```bash
   PYTHONPATH="$HOME/.claude/skills/skill-router" python -m skill_router "query"
   ```

   With no `-d`, it auto-discovers the nearest skills directory by walking up
   from the package (`.claude/skills/` preferred, top-level `skills/` fallback);
   from the user-level install that resolves to `~/.claude/skills/` itself.
   Point it at a project explicitly with `-d path/to/.claude/skills`.

## Commands

| Task | Flag |
|---|---|
| Route a request | `python -m skill_router "audit these drafts"` |
| Top-N as JSON | `--json -n 3` |
| List the registry | `--registry` |
| Regenerate INDEX.md | `--index` |
| Scan another directory | `-d path/to/skills` |

## Behaviour

1. Run the route command with the user's request as the query.
2. Report the top matches with their scores. If the best match is clearly
   right, invoke that skill (or point the user at it).
3. If nothing matches, say so and show the `--registry` output — never guess a
   skill that isn't registered.

> Source of truth: `edagher92-coder/Claude-code-` (`src/skill_router/`).
> Fix bugs there first, then re-copy here and to the vendored repo copies.

## Model escalation (seamless — see /auto-escalate)

After routing, gauge the task against the /auto-escalate rubric on BOTH
dials — model (`haiku`→`sonnet`→`opus`→`fable`) and reasoning effort
(`low`→`medium`→`high`→`xhigh`→`max`) — via the Agent tool's `model` and
`effort` params. Quality-first: when torn between rungs on quality-relevant
work, round UP; go straight to `fable + max` for clearly frontier tasks.
The main session stays on the pinned Opus 5 default — drop-back needs no action.
