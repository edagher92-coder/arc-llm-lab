---
name: hq-skills
description: >
  [OPS] Master-repo skill menu — list every skill synced from the .github
  father repo into this repo (grouped by category) and run the one Elie
  picks manually. Use when the user types /hq-skills or says "show me all
  skills", "list the skill menu", "what skills are available here",
  "pick a skill", or "apply a skill manually". Auto-apply by context stays
  the default; this menu is the manual override.
---

# HQ skill menu

Present the full synced skill registry for THIS repo and run whichever
skill Elie selects. Never invent skills; the menu is exactly what exists
on disk.

## Steps

1. **Build the registry from disk.** Glob `*/SKILL.md` under the repo's
   skills directory (`.claude/skills/` preferred; top-level `skills/` as
   fallback). For each, read the frontmatter `name` + `description`, and
   the `[CATEGORY]` tag if the description carries one. If the vendored
   `skill_router` package is present, prefer
   `python -m skill_router --registry` — same data, already parsed.
2. **Show the menu.** One numbered table grouped by category tag
   (`[CONTENT]`, `[FINANCE]`, `[OPS]`, `[STRATEGY]`, `[REVIEW]`,
   `[DESIGN]`, `[ADS]`, `[EFFICIENCY]`, untagged last), each row:
   `N · /skill-name — one-line summary`. Keep summaries to one line; no
   prose between rows.
3. **Run the pick.** When Elie answers with a number or name, invoke that
   skill via the Skill tool with any arguments he gave. If the choice is
   ambiguous, show the 2-3 closest rows and ask which.
4. **Delegation note.** If the chosen skill's work is then delegated to a
   subagent or worker model, attach that SKILL.md's content to the
   delegate's prompt — workers have no native discovery (see the
   account rule "Skills pass down the model ladder").

## Rules

- Read-only over the registry: never edit, create, or delete skills here —
  skill authoring belongs in the master repo (`edagher92-coder/.github`
  → `claude-defaults/skills/`), which syncs everywhere.
- If a listed skill needs an MCP/connector this repo doesn't have (Xero,
  Canva, Meta token), still list it but mark it `(needs <connector>)`.
- No pagination games: if the registry is long, show it all — one screen
  of rows beats a back-and-forth.
