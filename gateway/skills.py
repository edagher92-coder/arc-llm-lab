"""`skills` tool for the lazy gateway: search and load your playbooks (SKILL.md files) without loading them all.

Index: every <root>/*/SKILL.md under the configured roots. Frontmatter `name` and `description` are used when present
and well formed; otherwise the folder name and the first paragraph. The index is rebuilt when a root or a SKILL.md changes.
Only skills that appear in the index can be loaded, by name, so a path or "../" in the query can never read another file.
"""
import json, os, re
from typing import Literal

from fastmcp.exceptions import ToolError
import fastmcp.server.transforms.search.bm25 as _bm25

FRONT = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def expand(p):
    """Expand %VAR% (also on Linux, for tests), $VAR and ~ in a configured path."""
    p = re.sub(r"%([^%\\/]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), p)
    return os.path.expanduser(os.path.expandvars(p))


def trim(text, limit):
    """Keep head and tail of an over-long text (same shape as the gateway's result trim: 3/4 head, 5/24 tail)."""
    if not limit or len(text) <= limit:
        return text
    head, tail = limit * 3 // 4, limit * 5 // 24
    cut = len(text) - head - tail
    return (text[:head] + "\n[...]\n" + text[-tail:] +
            "\n[gateway: trimmed %d chars; narrow with line ranges, Select-String or an offset]" % cut)


def parse_frontmatter(text):
    """Return (meta dict, body). Tolerates missing, unterminated or garbled frontmatter (then meta is empty)."""
    m = FRONT.match(text)
    if not m:
        return {}, text
    meta, key = {}, None
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if kv and not line.startswith((" ", "\t")):
            key, val = kv.group(1).lower(), kv.group(2).strip()
            meta[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
        elif key and line.strip() and line[:1] in (" ", "\t"):   # folded / literal block continuation
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, text[m.end():]


def first_paragraph(body):
    for para in re.split(r"\n\s*\n", body.strip()):
        lines = [l.strip() for l in para.splitlines() if l.strip() and not l.strip().startswith("#") and l.strip() != "---"]
        if lines:
            return " ".join(lines)
    return ""


class SkillIndex:
    def __init__(self, roots):
        self.roots = [expand(r) for r in roots or []]
        self.sig = None
        self.skills = {}      # lower-case name -> {name, description, path, dir}
        self._bm = None
        self._order = []

    def _signature(self):
        sig = []
        for r in self.roots:
            try:
                sig.append((r, os.stat(r).st_mtime_ns, tuple(sorted(
                    (d, os.stat(os.path.join(r, d, "SKILL.md")).st_mtime_ns)
                    for d in os.listdir(r) if os.path.isfile(os.path.join(r, d, "SKILL.md"))))))
            except OSError:
                sig.append((r, None, ()))       # missing or unreadable root: tolerated
        return tuple(sig)

    def refresh(self):
        sig = self._signature()
        if sig == self.sig:
            return
        self.sig, skills = sig, {}
        for root, mtime, _ in sig:
            if mtime is None:
                continue
            real_root = os.path.realpath(root)
            for d in sorted(os.listdir(root)):
                f = os.path.join(root, d, "SKILL.md")
                real = os.path.realpath(f)
                if not os.path.isfile(f) or os.path.commonpath([real_root, real]) != real_root:
                    continue        # not a skill, or a symlink pointing outside the root
                try:
                    text = open(f, encoding="utf-8-sig", errors="replace").read()
                except OSError:
                    continue
                meta, body = parse_frontmatter(text)
                name = (meta.get("name") or d).strip() or d
                desc = (meta.get("description") or first_paragraph(body)).strip()
                skills.setdefault(name.lower(), {"name": name, "description": desc, "path": f, "dir": os.path.dirname(f)})
        self.skills = skills
        self._order = list(skills.values())
        self._bm = _bm25._BM25Index()
        self._bm.build(["%s %s %s" % (s["name"].replace("-", " ").replace("_", " "), s["name"], s["description"]) for s in self._order])

    def search(self, query, k=6):
        self.refresh()
        hits = [self._order[i] for i in self._bm.query(query, k)] if query.strip() else self._order[:k]
        return [{"name": s["name"], "description": s["description"][:140], "path": s["path"]} for s in hits]

    def load(self, name, limit=0):
        self.refresh()
        name = (name or "").strip()
        if not name or any(c in name for c in "/\\") or ".." in name or name.lower() not in self.skills:
            raise ToolError("Unknown skill %r. Use skills(action=\"search\", query=...) and load a name from the result." % name[:80])
        s = self.skills[name.lower()]
        _, body = parse_frontmatter(open(s["path"], encoding="utf-8-sig", errors="replace").read())
        tail = "\n\nReference files are under %s ; pc_Read them when the skill says to." % s["dir"]
        # leave room for the trim note so the gateway's own result trim never fires a second time
        return trim(body.strip(), max(200, limit - len(tail) - 300) if limit else 0) + tail


def register(server, cfg, max_chars=0):
    """Mount the `skills` tool on the gateway. max_chars: trim limit for `load` (the gateway's max_result_chars)."""
    index = SkillIndex((cfg.get("skills") or {}).get("roots", []))

    @server.tool(name="skills", description="Search and load your playbooks. search first, then load one and follow it.")
    def skills(action: Literal["search", "load"], query: str = "") -> str:
        if action == "search":
            hits = index.search(query)
            return json.dumps(hits, ensure_ascii=False, separators=(",", ":")) if hits else \
                "[] no skill matched; try other words, or search with an empty query to list a few."
        if action == "load":
            return index.load(query, max_chars)
        raise ToolError('action must be "search" or "load"')

    return index
