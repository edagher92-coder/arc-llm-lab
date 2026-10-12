"""Universal auto-registering skill router (v4.0).

Public API:
    Skill, discover_skills, parse_skill_md, score_skill, route, build_index
"""

from .index import build_index
from .router import (
    DEFAULT_SKILLS_DIR,
    Skill,
    discover_skills,
    parse_skill_md,
    route,
    score_skill,
)

__all__ = [
    "DEFAULT_SKILLS_DIR",
    "Skill",
    "discover_skills",
    "parse_skill_md",
    "route",
    "score_skill",
    "build_index",
]

__version__ = "4.0.0"
