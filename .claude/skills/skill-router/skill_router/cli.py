"""Command-line front end for the skill router.

    python -m skill_router "audit these drafts for compliance"   # route a query
    python -m skill_router --registry                            # dump the registry
    python -m skill_router --index                               # regen INDEX.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .index import write_index
from .router import DEFAULT_SKILLS_DIR, discover_skills, route


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill_router",
        description="Route a natural-language request to the best-matching skill.",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="The request to route (omit when using --registry or --index).",
    )
    parser.add_argument(
        "-d",
        "--skills-dir",
        default=str(DEFAULT_SKILLS_DIR),
        help=(
            "Directory to scan for */SKILL.md (default: auto-detected — this "
            "repo's .claude/skills, falling back to a top-level skills/)."
        ),
    )
    parser.add_argument(
        "-n",
        "--top",
        type=int,
        default=5,
        help="Show at most N matches (default: 5).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a table.",
    )
    parser.add_argument(
        "--registry",
        action="store_true",
        help="List every registered skill (the auto-discovered routing table).",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Regenerate INDEX.md from the live registry and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    skills_dir = Path(args.skills_dir)

    if args.index:
        out = write_index(skills_dir)
        print(f"Wrote {out}")
        return 0

    if args.registry:
        skills = discover_skills(skills_dir)
        if args.json:
            print(json.dumps([s.as_dict() for s in skills], indent=2))
        else:
            for skill in skills:
                print(f"/{skill.name:24} [{skill.category}]  {skill.summary}")
        return 0

    query = " ".join(args.query).strip()
    if not query:
        _build_parser().print_help()
        return 2

    matches = route(query, top=args.top, skills_dir=skills_dir)

    if args.json:
        print(
            json.dumps(
                [{"skill": s.name, "score": round(score, 4)} for s, score in matches],
                indent=2,
            )
        )
        return 0

    if not matches:
        print(f"No skill matched: {query!r}", file=sys.stderr)
        return 1

    print(f"Best matches for {query!r}:")
    for rank, (skill, score) in enumerate(matches, start=1):
        print(f"  {rank}. /{skill.name:24} {score:5.2f}  [{skill.category}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
