"""Check links in the Markdown files and docs/index.html. Standard library only.
  - relative links and images must point at a file or folder that exists, and a #fragment must match a heading in the target
  - links to this repo's own GitHub pages (blob/tree/main/..., issues/new?template=...) must match a local file or issue template
  - other http(s) links are not fetched (CI should not depend on the network); they are counted
Usage: python tools/check_links.py            (exit code 1 if anything is broken)"""
import glob, os, re, sys
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWN = "https://github.com/edagher92-coder/arc-llm-lab"
SITE = "https://edagher92-coder.github.io/arc-llm-lab/"

def md_files():
    out = set(glob.glob(os.path.join(ROOT, "*.md")))
    for pat in ("docs/*.md", "engine/**/*.md", "data/**/*.md", "bench/**/*.md", "evalsuite/**/*.md", "voice/**/*.md", "agents/**/*.md", "governor/**/*.md", "tools/**/*.md", "llama-swap/**/*.md"):
        out |= set(glob.glob(os.path.join(ROOT, pat), recursive=True))
    return sorted(out)

def slug(heading):
    h = re.sub(r"`", "", heading.strip())
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)             # [text](url) -> text
    h = re.sub(r"<[^>]+>", "", h).lower()
    h = re.sub(r"[^\w\- ]", "", h, flags=re.UNICODE)
    return h.replace(" ", "-")

_anchor_cache = {}
def anchors(path):
    if path in _anchor_cache: return _anchor_cache[path]
    seen, out, fence = {}, set(), False
    for line in open(path, encoding="utf-8"):
        if line.lstrip().startswith("```"): fence = not fence; continue
        if fence: continue
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            s = slug(m.group(1)); n = seen.get(s, 0); seen[s] = n + 1
            out.add(s if n == 0 else "%s-%d" % (s, n))
        for a in re.findall(r'<a\s+(?:name|id)="([^"]+)"', line): out.add(a)
    _anchor_cache[path] = out
    return out

def html_anchors(path):
    return set(re.findall(r'\sid="([^"]+)"', open(path, encoding="utf-8").read()))

def links_in_markdown(path):
    text, fence, res = open(path, encoding="utf-8").read().split("\n"), False, []
    for i, line in enumerate(text, 1):
        if line.lstrip().startswith("```"): fence = not fence; continue
        if fence: continue
        clean = re.sub(r"`[^`]*`", "", line)
        for m in re.finditer(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)", clean): res.append((i, m.group(1)))
        for m in re.finditer(r'(?:src|href)="([^"]+)"', clean): res.append((i, m.group(1)))
        for m in re.finditer(r'srcset="([^"]+)"', clean):
            for part in m.group(1).split(","): res.append((i, part.strip().split(" ")[0]))
    return res

def links_in_html(path):
    res = []
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        for m in re.finditer(r'(?:src|href)="([^"]+)"', line): res.append((i, m.group(1)))
    return res

def check_target(src, target, line, errors, stats):
    if not target or target.startswith(("mailto:", "data:", "javascript:")) or "${" in target: return
    if target.startswith(("http://", "https://")):
        u = urlparse(target)
        if target.startswith(SITE):
            rel = unquote(target[len(SITE):].split("#")[0].split("?")[0]) or "index.html"
            if not os.path.exists(os.path.join(ROOT, "docs", rel)): errors.append("%s:%d site link has no file in docs/: %s" % (rel_(src), line, target))
            stats["site"] += 1
        elif target.startswith(OWN):
            sub = target[len(OWN):]
            m = re.match(r"^/(?:blob|tree)/main/([^#?]*)", sub)
            if m:
                p = unquote(m.group(1)).rstrip("/")
                if p and not os.path.exists(os.path.join(ROOT, p)): errors.append("%s:%d repo link has no local file: %s" % (rel_(src), line, target))
            elif sub.startswith("/issues/new"):
                t = re.search(r"template=([\w.\-]+)", u.query)
                if t and not os.path.exists(os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", t.group(1))): errors.append("%s:%d no such issue template: %s" % (rel_(src), line, target))
            stats["own"] += 1
        else:
            stats["external"] += 1
        return
    if target.startswith("#"): path, frag = src, target[1:]
    else:
        base, _, frag = target.partition("#")
        base = unquote(base.split("?")[0])
        path = os.path.normpath(os.path.join(os.path.dirname(src), base)) if not base.startswith("/") else os.path.normpath(os.path.join(ROOT, base.lstrip("/")))
        if not os.path.exists(path): errors.append("%s:%d missing target: %s" % (rel_(src), line, target)); return
    stats["relative"] += 1
    if frag:
        frag = unquote(frag)
        if os.path.isdir(path): errors.append("%s:%d fragment on a folder: %s" % (rel_(src), line, target))
        elif path.endswith(".md"):
            if frag not in anchors(path): errors.append("%s:%d no heading '#%s' in %s" % (rel_(src), line, frag, rel_(path)))
        elif path.endswith(".html"):
            if frag not in html_anchors(path): errors.append("%s:%d no id '%s' in %s" % (rel_(src), line, frag, rel_(path)))

def rel_(p): return os.path.relpath(p, ROOT).replace(os.sep, "/")

def main():
    errors, stats, files = [], {"relative": 0, "own": 0, "site": 0, "external": 0}, 0
    for p in md_files():
        files += 1
        for line, t in links_in_markdown(p): check_target(p, t, line, errors, stats)
    idx = os.path.join(ROOT, "docs", "index.html")
    if os.path.exists(idx):
        files += 1
        for line, t in links_in_html(idx): check_target(idx, t, line, errors, stats)
    for e in errors: print("BROKEN", e)
    print("checked %d files: %d relative, %d own-repo, %d own-site, %d external (not fetched); %d broken" % (files, stats["relative"], stats["own"], stats["site"], stats["external"], len(errors)))
    sys.exit(1 if errors else 0)

if __name__ == "__main__":
    main()
