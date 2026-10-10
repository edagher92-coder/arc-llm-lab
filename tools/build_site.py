"""Build the GitHub Pages benchmark site from data/*.csv and data/community/*.json.
Also renders the guides in docs/*.md listed in GUIDES to docs/guides/<slug>.html (stdlib-only Markdown subset, see render_md),
with breadcrumbs JSON-LD, a FAQPage on the FAQ, and per-page lastmod in the sitemap (docs/.lastmod.json maps each page's content hash to
the date it last changed, so builds stay deterministic; set SOURCE_DATE_EPOCH to pin the date).
Writes docs/index.html (from tools/site_template.html), docs/sitemap.xml, docs/robots.txt, docs/.nojekyll and
docs/assets/social-preview.png (a copy of assets/social-preview.png so the absolute og:image URL resolves on Pages).
Usage: python tools/build_site.py
Note: search engines only read robots.txt at the root of a host. A GitHub project page is served from a sub-path, so the
robots.txt written here is a convention for the project, not something major crawlers will pick up. Submit docs/sitemap.xml
in Google Search Console if you want it indexed promptly."""
import csv, datetime, hashlib, html, json, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from build_tables import community, depth_label  # noqa: E402  (community results, validated when jsonschema is installed)
from check_links import slug as heading_slug  # noqa: E402  (same heading ids GitHub and check_links use)

SITE_URL = "https://edagher92-coder.github.io/arc-llm-lab/"
REPO_URL = "https://github.com/edagher92-coder/arc-llm-lab"
RAW_URL = "https://raw.githubusercontent.com/edagher92-coder/arc-llm-lab/main"
OG_IMAGE = SITE_URL + "assets/social-preview.png"
AUTHOR = "Elie Dagher"
DESCRIPTION = "Intel Arc Pro B60 24GB benchmarks for llama.cpp on Vulkan: Qwen3.8-27B at 42.3 tok/s eval-suite throughput (per-request decode 47-58), 420 tok/s prompt reading at 32K, agent reliability, community results."
KEYWORDS = ["Intel Arc", "Arc Pro B60", "B580", "B570", "Arc B50", "Arc B70", "A770", "Battlemage", "Xe2", "Vulkan", "llama.cpp",
            "local LLM", "24GB VRAM", "Qwen 27B", "speculative decoding", "flash attention", "benchmarks", "Claude Code", "Codex"]

def rows(n): return list(csv.DictReader(open(os.path.join(ROOT, "data", n), encoding="utf-8")))
esc = html.escape
def safe_url(u): return u if u.startswith(("https://", "http://")) else "#"   # data files are contributor-supplied: never emit javascript: or data: links

def intel_table(gpus):
    """Static table of the Intel cards (readable without JavaScript). Only the B60 is measured; the rest is arithmetic."""
    head = ["Card", "VRAM", "Bandwidth", "AU price (dated)", "27B Q4 + 32K context fits?", "Measured"]
    body = []
    for r in gpus:
        if not r["gpu"].startswith("Intel"): continue
        measured = r["measured_decode_tok_s"] and "<b>%s tok/s</b>, %s with the draft model" % (esc(r["measured_decode_tok_s"]), esc(r["measured_with_drafter_tok_s"]))
        price = ('<a href="%s">A$%s</a> (%s)' % (esc(safe_url(r["price_source"]), quote=True), esc(r["price_aud"]), esc(r["price_date"]))) if r["price_aud"] else "no sourced price"
        fits = r["fits_27b_q4_32k"] + (" (measured)" if measured else " (ESTIMATE)")
        body.append([esc(r["gpu"].replace("Intel ", "")), esc(r["vram_gb"]) + " GB", esc(r["bandwidth_gbs"]) + " GB/s", price, fits, measured or "not measured"])
    return table_html(head, body)

def table_html(head, body):
    return "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
        "".join("<th>%s</th>" % h for h in head), "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in body))

def community_table(recs):
    if not recs: return "<p class=\"note\">No community results yet. Yours could be the first.</p>"
    head = ["GPU", "Backend / build", "Patches", "Model", "Depths", "pp (tok/s)", "tg (tok/s)", "Driver / OS", "By"]
    body = []
    for d in recs:
        ds = sorted(d["depth_results"], key=int)
        pp = " / ".join("%.0f" % d["depth_results"][k]["pp_tok_s"] for k in ds); tg = " / ".join("%.2f" % d["depth_results"][k]["tg_tok_s"] for k in ds)
        patches = ("%d" % len(d["patches"])) if d["patches"] else "none"
        gpu = esc(d["gpu"]) if ("%g" % d["vram_gb"]) in d["gpu"] else "%s (%g GB)" % (esc(d["gpu"]), d["vram_gb"])
        if d.get("raw_log_url"): gpu += ' <a href="%s">log</a>' % esc(safe_url(d["raw_log_url"]), quote=True)
        body.append([gpu, "%s %s" % (esc(d["backend"]), esc(d["llama_cpp_build"])), patches, "%s (KV %s/%s)" % (esc(d["model"]), esc(d["kv_cache"]["k"]), esc(d["kv_cache"]["v"])),
                     " / ".join(depth_label(k) for k in ds), pp, tg, "%s, %s" % (esc(d["driver"]), esc(d["os"])), esc(d["contributor"])])
    return table_html(head, body)

def json_ld():
    csv_files = ["prompt-speed-vs-depth.csv", "speculative-decoding-sweep.csv", "agent-turns.csv", "vram-budget-64k.csv", "gpu-comparison.csv", "peer-benchmarks.csv"]
    creator = {"@type": "Person", "name": AUTHOR}
    graph = [
        {"@type": "Dataset", "@id": SITE_URL + "#dataset",
         "name": "arc-llm-lab benchmark data: llama.cpp on an Intel Arc Pro B60 24GB",
         "description": "Raw and tabulated measurements of Qwen3.8-27B on a single Intel Arc Pro B60 24GB with llama.cpp on Vulkan: prompt-processing and generation speed by context depth, speculative-decoding sweep, VRAM budget, agent-turn timings, GPU comparison and peer results, with raw logs.",
         "url": SITE_URL, "creator": creator, "license": "https://opensource.org/licenses/MIT", "isAccessibleForFree": True,
         "keywords": KEYWORDS, "datePublished": "2026-10-10",
         "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": "%s/data/%s" % (RAW_URL, f)} for f in csv_files]},
        {"@type": "SoftwareSourceCode", "@id": SITE_URL + "#code",
         "name": "arc-llm-lab", "description": DESCRIPTION, "url": SITE_URL, "codeRepository": REPO_URL, "creator": creator,
         "license": "https://opensource.org/licenses/MIT", "keywords": KEYWORDS, "programmingLanguage": ["PowerShell", "Python"],
         "runtimePlatform": "Windows 11"},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=1, ensure_ascii=False).replace("</", "<\\/")

# ---- guides: docs/*.md -> docs/guides/<slug>.html -------------------------------------------------------------------
# (markdown file, optional description; when None the first paragraph is used)
GUIDES = [("SETUP", "Step-by-step setup of llama.cpp on Windows 11 with an Intel Arc Pro B60 24GB: engine, models, server key, verification, remote access, chat UI and nightly regression."),
          ("INTEL-FA", None), ("TOKEN-EFFICIENCY", None), ("TOOL-CALLING", None), ("GATEWAY", None), ("HARNESS-PLAN", None), ("PLATFORM", None), ("RELIABILITY", None), ("PEERS", None),
          ("FAQ", None)]
GUIDE_SLUGS = {n: n.lower() for n, _ in GUIDES}

def link_target(t, src):
    """Rewrite a link from docs/<src>.md for the rendered page: sibling guides -> Pages, other repo files -> GitHub, anything missing is an error."""
    if t.startswith(("https://", "http://", "mailto:")) or t.startswith("#"): return t
    base, _, frag = t.partition("#")
    path = os.path.normpath(os.path.join(ROOT, "docs", base))
    name = os.path.basename(base)[:-3] if base.endswith(".md") and os.path.dirname(path) == os.path.join(ROOT, "docs") else None
    if name in GUIDE_SLUGS: return "%sguides/%s.html%s" % (SITE_URL, GUIDE_SLUGS[name], "#" + frag if frag else "")
    if not os.path.exists(path): raise SystemExit("guide %s links to a missing file: %s" % (src, t))
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    return "%s/%s/main/%s%s" % (REPO_URL, "tree" if os.path.isdir(path) else "blob", rel, "#" + frag if frag else "")

def inline_md(text, src):
    """Backtick code, **bold**, *italic* and [text](url); everything else is escaped. Code spans are lifted out first so bold can wrap them."""
    codes = []
    def lift(m): codes.append("<code>%s</code>" % esc(m.group(1), quote=False)); return "\x00%d\x00" % (len(codes) - 1)
    text = esc(re.sub(r"`([^`]+)`", lift, text), quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: '<a href="%s">%s</a>' % (esc(link_target(html.unescape(m.group(2)), src), quote=True), m.group(1)), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)

def plain_md(text):
    text = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", text)
    return re.sub(r"\*\*(.+?)\*\*|`([^`]+)`", lambda m: m.group(1) or m.group(2), text)

def split_row(line):
    cells, cur, tick = [], "", False
    for i, ch in enumerate(line.strip().strip("|") + "|"):
        if ch == "`": tick = not tick
        if ch == "|" and not tick and not cur.endswith("\\"): cells.append(cur.strip()); cur = ""
        else: cur += ch
    return [c.replace("\\|", "|") for c in cells]

def parse_md(md):
    """Blocks: ('h', level, text) ('p', text) ('code', lang, text) ('ul'|'ol', [items]) ('table', head, rows, aligns). Nested lists are not supported."""
    lines, blocks, i = re.sub(r"<!--.*?-->", "", md, flags=re.S).split("\n"), [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip(): i += 1; continue
        if ln.lstrip().startswith("```"):
            lang, body, i = ln.strip()[3:].strip(), [], i + 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"): body.append(lines[i]); i += 1
            blocks.append(("code", lang, "\n".join(body))); i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", ln)
        if m: blocks.append(("h", len(m.group(1)), m.group(2))); i += 1; continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|?\s*$", lines[i + 1]):
            head, aligns, rows, i = split_row(ln), [("right" if c.strip().endswith(":") else "") for c in split_row(lines[i + 1])], [], i + 2
            while i < len(lines) and lines[i].startswith("|"): rows.append(split_row(lines[i])); i += 1
            blocks.append(("table", head, rows, aligns)); continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", ln)
        if m:
            kind, items = ("ol" if m.group(2)[0].isdigit() else "ul"), []
            while i < len(lines):
                m = re.match(r"^([-*]|\d+\.)\s+(.*)", lines[i])
                if m: items.append(m.group(2)); i += 1
                elif lines[i].startswith("  ") and lines[i].strip() and items: items[-1] += " " + lines[i].strip(); i += 1
                else: break
            blocks.append((kind, items)); continue
        para = []
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("```", "|")) and not re.match(r"^(#{1,6}\s|([-*]|\d+\.)\s)", lines[i]): para.append(lines[i].strip()); i += 1
        if not para: raise SystemExit("markdown line not understood: " + ln)
        blocks.append(("p", " ".join(para)) if not re.match(r"^\*\*[^*]+\*\*$", para[0]) else ("qa", para[0][2:-2], " ".join(para[1:])))
    return blocks

def render_blocks(blocks, src):
    out, seen = [], {}
    for b in blocks:
        if b[0] == "h":
            s = heading_slug(b[2]); n = seen.get(s, 0); seen[s] = n + 1
            out.append('<h%d id="%s">%s</h%d>' % (b[1], s if n == 0 else "%s-%d" % (s, n), inline_md(b[2], src), b[1]))
        elif b[0] == "p": out.append("<p>%s</p>" % inline_md(b[1], src))
        elif b[0] == "qa": out.append('<p class="q"><strong>%s</strong></p>' % inline_md(b[1], src) + ("<p>%s</p>" % inline_md(b[2], src) if b[2] else ""))
        elif b[0] == "code": out.append('<pre><code%s>%s</code></pre>' % (' class="language-%s"' % esc(b[1]) if b[1] else "", esc(b[2], quote=False)))
        elif b[0] in ("ul", "ol"): out.append("<%s>%s</%s>" % (b[0], "".join("<li>%s</li>" % inline_md(x, src) for x in b[1]), b[0]))
        else:
            th = "".join('<th%s>%s</th>' % (' style="text-align:right"' if a else "", inline_md(c, src)) for c, a in zip(b[1], b[3] + [""] * len(b[1])))
            tr = "".join("<tr>%s</tr>" % "".join('<td%s>%s</td>' % (' style="text-align:right"' if a else "", inline_md(c, src)) for c, a in zip(r, b[3] + [""] * len(r))) for r in b[2])
            out.append('<div class="tw"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, tr))
    return "\n".join(out)

def short(text, n=200):
    text = re.sub(r"\s+", " ", plain_md(text)).strip()
    if len(text) <= n: return text
    cut = text[:n]; end = max(cut.rfind(". "), cut.rfind("? "))
    return cut[:end + 1] if end > 60 else cut.rsplit(" ", 1)[0].rstrip(",;:(") + "\u2026"   # whole sentences where possible

GUIDE_CSS = """:root{--bg:#FFFFFF;--panel:#F6F8FA;--ink:#1F2328;--ink2:#59636E;--line:#D0D7DE;--link:#B8470F}
@media (prefers-color-scheme:dark){:root{--bg:#0D1117;--panel:#161B22;--ink:#E6EDF3;--ink2:#9DA7B3;--line:#30363D;--link:#E8661E}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--link)}.wrap{max-width:860px;margin:0 auto;padding:0 20px}
nav.top{padding:18px 0;border-bottom:1px solid var(--line);font-size:15px}nav.top a{margin-right:16px;font-weight:600}
.crumbs{color:var(--ink2);font-size:14px;margin:20px 0 0}h1{font-size:clamp(28px,4.5vw,40px);line-height:1.15;letter-spacing:-.02em;margin:10px 0 18px}
h2{font-size:24px;margin:2em 0 .4em;padding-top:.6em;border-top:1px solid var(--line)}h3{font-size:19px;margin:1.6em 0 .3em}
p.q{margin:1.4em 0 .2em}p.q+p{margin-top:0}code{font:13.5px/1.4 ui-monospace,"JetBrains Mono",Consolas,monospace;background:var(--panel);padding:1px 5px;border-radius:5px}
pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-x:auto}pre code{background:none;padding:0}
.tw{overflow-x:auto;margin:1em 0}table{border-collapse:collapse;font-size:14.5px}th,td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}th{background:var(--panel)}
footer{margin:48px 0 40px;padding-top:18px;border-top:1px solid var(--line);color:var(--ink2);font-size:14px}footer a{margin-right:14px}"""

def guide_pages():
    """Returns {slug: page html}. The head mirrors the home page (canonical, Open Graph, Twitter card, JSON-LD) with an inlined stylesheet and no external requests."""
    icon = re.search(r'<link rel="icon"[^>]*>', open(os.path.join(ROOT, "tools", "site_template.html"), encoding="utf-8").read()).group(0)
    pages = {}
    for name, desc in GUIDES:
        src = os.path.join(ROOT, "docs", name + ".md")
        md = open(src, encoding="utf-8").read()
        blocks = parse_md(md)
        h1 = next(b[2] for b in blocks if b[0] == "h" and b[1] == 1)
        title = plain_md(h1)
        url = "%sguides/%s.html" % (SITE_URL, GUIDE_SLUGS[name])
        if not desc:   # first paragraph; a Q&A page has none, so list its sections
            first = next((b[1] for b in blocks if b[0] == "p"), None)
            desc = short(first) if first else short("%s. Covers %s." % (title, ", ".join(plain_md(b[2]).lower() for b in blocks if b[0] == "h" and b[1] == 2)))
        ld = [{"@type": "TechArticle", "@id": url + "#article", "headline": title[:110], "description": desc, "url": url, "inLanguage": "en",
               "author": {"@type": "Person", "name": AUTHOR}, "isPartOf": {"@id": SITE_URL + "#code"}, "mainEntityOfPage": url,
               "image": OG_IMAGE, "license": "https://opensource.org/licenses/MIT"},
              {"@type": "BreadcrumbList", "itemListElement": [
                  {"@type": "ListItem", "position": 1, "name": "arc-llm-lab", "item": SITE_URL},
                  {"@type": "ListItem", "position": 2, "name": title, "item": url}]}]
        qa = [(plain_md(b[1]), plain_md(b[2])) for b in blocks if b[0] == "qa" and b[2]] if name == "FAQ" else []
        if qa: ld.append({"@type": "FAQPage", "@id": url + "#faq", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa]})
        ldjson = json.dumps({"@context": "https://schema.org", "@graph": ld}, indent=1, ensure_ascii=False).replace("</", "<\\/")
        nav = " ".join('<a href="%sguides/%s.html">%s</a>' % (SITE_URL, GUIDE_SLUGS[n], n.replace("-", " ").title() if n not in ("FAQ", "INTEL-FA") else n.replace("-", " ")) for n, _ in GUIDES if n != name)
        head_title = esc(title if len(title) > 60 else title + " | arc-llm-lab")
        pages[GUIDE_SLUGS[name]] = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(t)s</title>
<meta name="description" content="%(d)s">
<meta name="author" content="%(a)s">
<meta name="robots" content="index, follow">
<link rel="canonical" href="%(u)s">
<meta property="og:type" content="article">
<meta property="og:site_name" content="arc-llm-lab">
<meta property="og:url" content="%(u)s">
<meta property="og:title" content="%(h)s">
<meta property="og:description" content="%(d)s">
<meta property="og:image" content="%(i)s">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%(h)s">
<meta name="twitter:description" content="%(d)s">
<meta name="twitter:image" content="%(i)s">
%(icon)s
<script type="application/ld+json">%(ld)s</script>
<style>%(css)s</style>
</head>
<body>
<div class="wrap">
<nav class="top"><a href="%(home)s">arc-llm-lab benchmarks</a><a href="%(repo)s">GitHub</a></nav>
<p class="crumbs"><a href="%(home)s">Home</a> / %(h)s</p>
<main>
%(body)s
</main>
<footer>
<p>More guides: %(nav)s</p>
<p><a href="%(home)s">Back to the benchmark site</a><a href="%(repo)s/blob/main/docs/%(n)s.md">View or edit this page on GitHub</a></p>
<p>Written and measured by %(a)s. MIT licensed. Rendered from docs/%(n)s.md by tools/build_site.py.</p>
</footer>
</div>
</body>
</html>
""" % {"t": head_title, "d": esc(desc, quote=True), "a": AUTHOR, "u": url, "h": esc(title, quote=True), "i": OG_IMAGE, "icon": icon, "ld": ldjson, "css": GUIDE_CSS,
       "home": SITE_URL, "repo": REPO_URL, "body": render_blocks(blocks, name), "nav": nav, "n": name}
    return pages

def write_lastmod(docs, pages):
    """Date each page last changed, tracked by content hash in docs/.lastmod.json so rebuilding unchanged content never changes docs/."""
    path = os.path.join(docs, ".lastmod.json")
    try: old = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError): old = {}
    today = datetime.datetime.fromtimestamp(int(os.environ.get("SOURCE_DATE_EPOCH", datetime.datetime.now(datetime.timezone.utc).timestamp())), datetime.timezone.utc).strftime("%Y-%m-%d")
    new = {}
    for k, text in sorted(pages.items()):
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        new[k] = old[k] if old.get(k, {}).get("sha256") == h else {"sha256": h, "date": today}
    open(path, "w", encoding="utf-8", newline="\n").write(json.dumps(new, indent=1, sort_keys=True) + "\n")
    return {k: v["date"] for k, v in new.items()}

def main():
    gpus = rows("gpu-comparison.csv")
    data = {
        "depth": rows("prompt-speed-vs-depth.csv"),
        "sweep": [r for r in rows("speculative-decoding-sweep.csv") if r["eval_tok_s"]],
        "gpus": gpus,
        "vram": rows("vram-budget-64k.csv"),
        "turns": rows("agent-turns.csv"),
    }
    rel_path = os.path.join(ROOT, "data", "reliability-summary.json")
    data["reliability"] = json.load(open(rel_path, encoding="utf-8")) if os.path.exists(rel_path) else None

    page = open(os.path.join(ROOT, "tools", "site_template.html"), encoding="utf-8").read()
    for k, v in {"__DESCRIPTION__": esc(DESCRIPTION, quote=True), "__SITE_URL__": SITE_URL, "__OG_IMAGE__": OG_IMAGE,
                 "__KEYWORDS__": esc(", ".join(KEYWORDS), quote=True), "__JSONLD__": json_ld(), "__INTEL_TABLE__": intel_table(gpus), "__COMMUNITY_TABLE__": community_table(community())}.items():
        if k not in page: raise SystemExit("template placeholder missing: " + k)
        page = page.replace(k, v)
    # the data blob goes in last, and "</" is escaped so no CSV field can close the script element
    page = page.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))

    docs = os.path.join(ROOT, "docs"); os.makedirs(os.path.join(docs, "assets"), exist_ok=True)
    open(os.path.join(docs, "index.html"), "w", encoding="utf-8", newline="\n").write(page)
    open(os.path.join(docs, ".nojekyll"), "w").write("")
    guides = guide_pages(); os.makedirs(os.path.join(docs, "guides"), exist_ok=True)
    for f in os.listdir(os.path.join(docs, "guides")):
        if f.endswith(".html") and f[:-5] not in guides: os.remove(os.path.join(docs, "guides", f))   # a guide dropped from GUIDES must not linger
    for k, text in guides.items(): open(os.path.join(docs, "guides", k + ".html"), "w", encoding="utf-8", newline="\n").write(text)
    lm = write_lastmod(docs, dict(guides, index=page))
    urls = [(SITE_URL, lm["index"], "weekly")] + [("%sguides/%s.html" % (SITE_URL, GUIDE_SLUGS[n]), lm[GUIDE_SLUGS[n]], "monthly") for n, _ in GUIDES]
    open(os.path.join(docs, "sitemap.xml"), "w", encoding="utf-8", newline="\n").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % "".join(
            "  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>\n    <changefreq>%s</changefreq>\n  </url>\n" % u for u in urls))
    open(os.path.join(docs, "robots.txt"), "w", encoding="utf-8", newline="\n").write("User-agent: *\nAllow: /\n\nSitemap: %ssitemap.xml\n" % SITE_URL)
    shutil.copyfile(os.path.join(ROOT, "assets", "social-preview.png"), os.path.join(docs, "assets", "social-preview.png"))
    print("site -> docs/index.html (%d bytes), %d guide pages in docs/guides/, docs/sitemap.xml, docs/robots.txt, docs/assets/social-preview.png" % (len(page), len(guides)))

if __name__ == "__main__":
    main()
