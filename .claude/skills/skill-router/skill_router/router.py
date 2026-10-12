"""Universal, auto-registering skill router (v4.0).

The router reads the *skills themselves* as its routing table. Every skill in
this repo ships a ``SKILL.md`` whose frontmatter encodes a ``[CATEGORY]`` tag,
a human summary, and quoted "Use when the user says ..." trigger phrases. That
structured metadata is all a router needs, so there is **no hand-maintained
config**: drop a new ``SKILL.md`` on disk and it registers automatically, in any
domain — Snowflow, Profit Minute, or something you invent next week.

Design contract
---------------
- **Auto-registering**: :func:`discover_skills` globs ``*/SKILL.md`` and parses
  each one. The registry is rebuilt from disk on every call — nothing is cached,
  so it can never drift from what is actually on disk.
- **Any domain**: zero brand-specific logic lives here. Skills are grouped by
  whatever ``[CATEGORY]`` tags they declare; routing works off whatever trigger
  phrases they declare.
- **Routing**: :func:`route` ranks every skill against a free-text query and
  returns the matches, best first.

Zero third-party dependencies — standard library only, matching the rest of
this repo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

def _find_repo_root() -> Path:
    """Walk up from this package to the first directory that looks like a repo
    root — one containing ``.git``, ``.claude``, or a top-level ``skills/``.

    The package is vendored across several repos at different depths
    (``src/skill_router/`` here, ``skill_router/`` at the root elsewhere), so
    the root cannot be a fixed number of ``parents[...]`` hops.
    """
    package_dir = Path(__file__).resolve().parent
    for candidate in (package_dir.parent, *package_dir.parent.parents):
        if (
            (candidate / ".git").exists()
            or (candidate / ".claude").is_dir()
            or (candidate / "skills").is_dir()
        ):
            return candidate
    return package_dir.parent


def _default_skills_dir(root: Path) -> Path:
    """Prefer ``.claude/skills`` (Claude Code's discovery path); fall back to a
    top-level ``skills/`` directory (the convention in repos that keep skills
    outside ``.claude``). When neither exists yet, point at the preferred path
    so ``discover_skills`` degrades to an empty registry rather than raising.
    """
    preferred = root / ".claude" / "skills"
    if preferred.is_dir():
        return preferred
    fallback = root / "skills"
    if fallback.is_dir():
        return fallback
    return preferred


_REPO_ROOT = _find_repo_root()
DEFAULT_SKILLS_DIR = _default_skills_dir(_REPO_ROOT)

# --- Tunable ranking weights -------------------------------------------------
# These four constants are the router's "knobs". A trigger-phrase hit is the
# strongest signal (the skill author wrote those phrases to be matched); name
# and summary overlap are softer corroboration; category is a faint tiebreaker.
# Tuning these changes routing behaviour without touching the algorithm.
TRIGGER_WEIGHT = 1.0
NAME_WEIGHT = 0.6
SUMMARY_WEIGHT = 0.3
CATEGORY_WEIGHT = 0.1

# Words too common to carry routing signal. Deliberately small — domain terms
# like "post", "week", "canva", "meta" must survive so they can do the routing.
_STOPWORDS = frozenset(
    "a an the of for to this that these those and or in on at with your my our "
    "i it is are be as by from into".split()
)

_CATEGORY_RE = re.compile(r"\[([^\]]+)\]")
_QUOTED_RE = re.compile(r'"([^"]+)"')
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Skill:
    """One registered skill, parsed from its ``SKILL.md`` frontmatter."""

    name: str
    category: str
    summary: str
    triggers: tuple[str, ...] = field(default_factory=tuple)
    path: Path | None = None

    def as_dict(self) -> dict:
        """JSON-serialisable view (used by the registry dump)."""
        return {
            "name": self.name,
            "category": self.category,
            "summary": self.summary,
            "triggers": list(self.triggers),
            "path": str(self.path) if self.path else None,
        }


def _tokens(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stopwords and 1-char noise removed."""
    return [
        t
        for t in _TOKEN_RE.findall(text.lower())
        if len(t) > 1 and t not in _STOPWORDS
    ]


def _split_frontmatter(text: str) -> str:
    """Return the YAML frontmatter block (between the first two ``---`` fences).

    Returns an empty string when the document has no frontmatter, so callers
    degrade gracefully rather than raising on a malformed skill file.
    """
    if not text.lstrip().startswith("---"):
        return ""
    body = text.split("---", 2)
    return body[1] if len(body) >= 3 else ""


def parse_skill_md(text: str, path: Path | None = None) -> Skill | None:
    """Parse one ``SKILL.md`` document into a :class:`Skill`.

    The frontmatter uses a YAML block scalar (``description: |``). Rather than
    pull in a YAML dependency, we extract the two fields we need by hand:
    ``name`` (a scalar) and ``description`` (an indented multi-line block).
    Returns ``None`` when there is no usable ``name``.
    """
    front = _split_frontmatter(text)
    if not front:
        return None

    name = ""
    description_lines: list[str] = []
    in_description = False
    for raw in front.splitlines():
        stripped = raw.strip()
        if not in_description:
            if stripped.startswith("name:"):
                name = stripped[len("name:") :].strip()
            elif stripped.startswith("description:"):
                inline = stripped[len("description:") :].strip()
                # "description: |" opens a block; "description: foo" is inline.
                if inline and inline != "|":
                    description_lines.append(inline)
                in_description = True
        else:
            # The block ends at the next top-level (unindented) YAML key.
            if raw and not raw[0].isspace() and stripped.endswith(":"):
                in_description = False
            elif raw and not raw[0].isspace() and ":" in stripped:
                in_description = False
            else:
                description_lines.append(stripped)

    if not name:
        return None

    description = " ".join(line for line in description_lines if line).strip()
    category_match = _CATEGORY_RE.search(description)
    category = category_match.group(1).strip() if category_match else "UNCATEGORIZED"

    # Summary = description minus the [CATEGORY] tag, trimmed before the
    # "Use when ..." trigger sentence so the registry stays scannable.
    summary = _CATEGORY_RE.sub("", description, count=1).strip()
    cut = re.search(r"\buse when(?:ever)?\b", summary, flags=re.IGNORECASE)
    if cut:
        summary = summary[: cut.start()].strip()
    summary = summary.rstrip(". ").strip()

    triggers = tuple(dict.fromkeys(_QUOTED_RE.findall(description)))

    return Skill(
        name=name,
        category=category,
        summary=summary,
        triggers=triggers,
        path=path,
    )


def discover_skills(skills_dir: Path | str = DEFAULT_SKILLS_DIR) -> list[Skill]:
    """Scan ``skills_dir`` for ``*/SKILL.md`` and return registered skills.

    This is the "auto-registering" step: it reads the live filesystem every
    call, so the registry always reflects exactly what is on disk. Results are
    sorted by name for stable output.
    """
    root = Path(skills_dir)
    skills: list[Skill] = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        skill = parse_skill_md(skill_md.read_text(encoding="utf-8"), path=skill_md)
        if skill is not None:
            skills.append(skill)
    return skills


def score_skill(query: str, skill: Skill) -> float:
    """Rank how well ``skill`` answers ``query`` (higher is better, 0 = no match).

    Baseline algorithm — a weighted blend of four overlap signals:

    1. **Trigger phrases** (strongest): the best token-overlap ratio across the
       skill's declared "Use when ..." phrases. These were authored to be
       matched, so a hit here is the most trustworthy signal.
    2. **Name**: overlap with the skill's own (de-hyphenated) name.
    3. **Summary**: overlap with the description prose.
    4. **Category**: a faint bonus when the query names the category.

    The weights live in the module-level ``*_WEIGHT`` constants so behaviour can
    be tuned without rewriting the algorithm.
    """
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return 0.0

    score = 0.0

    best_trigger = 0.0
    for phrase in skill.triggers:
        phrase_tokens = set(_tokens(phrase))
        if not phrase_tokens:
            continue
        overlap = len(query_tokens & phrase_tokens) / len(phrase_tokens)
        best_trigger = max(best_trigger, overlap)
    score += TRIGGER_WEIGHT * best_trigger

    name_tokens = set(_tokens(skill.name.replace("-", " ")))
    if name_tokens:
        score += NAME_WEIGHT * (len(query_tokens & name_tokens) / len(name_tokens))

    summary_tokens = set(_tokens(skill.summary))
    if summary_tokens:
        score += SUMMARY_WEIGHT * (
            len(query_tokens & summary_tokens) / len(summary_tokens)
        )

    category_tokens = set(_tokens(skill.category))
    if category_tokens & query_tokens:
        score += CATEGORY_WEIGHT

    return score


def route(
    query: str,
    skills: Iterable[Skill] | None = None,
    *,
    top: int | None = None,
    skills_dir: Path | str = DEFAULT_SKILLS_DIR,
) -> list[tuple[Skill, float]]:
    """Return ``(skill, score)`` pairs for ``query``, best match first.

    When ``skills`` is omitted the registry is auto-discovered from
    ``skills_dir`` (so a bare ``route("...")`` call "just works"). Only positive
    scores are returned; ``top`` optionally caps the list length.
    """
    registry = list(skills) if skills is not None else discover_skills(skills_dir)
    ranked = [
        (skill, score_skill(query, skill)) for skill in registry
    ]
    ranked = [pair for pair in ranked if pair[1] > 0]
    ranked.sort(key=lambda pair: (-pair[1], pair[0].name))
    return ranked[:top] if top is not None else ranked
