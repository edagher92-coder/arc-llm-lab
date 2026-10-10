"""Build the GitHub Pages benchmark site from data/*.csv and data/community/*.json.
Writes docs/index.html (from tools/site_template.html), docs/sitemap.xml, docs/robots.txt, docs/.nojekyll and
docs/assets/social-preview.png (a copy of assets/social-preview.png so the absolute og:image URL resolves on Pages).
Usage: python tools/build_site.py
Note: search engines only read robots.txt at the root of a host. A GitHub project page is served from a sub-path, so the
robots.txt written here is a convention for the project, not something major crawlers will pick up. Submit docs/sitemap.xml
in Google Search Console if you want it indexed promptly."""
import csv, html, json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from build_tables import community, depth_label  # noqa: E402  (community results, validated when jsonschema is installed)

SITE_URL = "https://edagher92-coder.github.io/arc-llm-lab/"
REPO_URL = "https://github.com/edagher92-coder/arc-llm-lab"
RAW_URL = "https://raw.githubusercontent.com/edagher92-coder/arc-llm-lab/main"
OG_IMAGE = SITE_URL + "assets/social-preview.png"
AUTHOR = "Elie Dagher"
DESCRIPTION = "Intel Arc Pro B60 24GB benchmarks for llama.cpp on Vulkan: 42.3 tok/s Qwen3.8-27B generation, 420 tok/s prompt reading at 32K, agent reliability, community results."
KEYWORDS = ["Intel Arc", "Arc Pro B60", "B580", "B570", "Arc B50", "Arc B70", "A770", "Battlemage", "Xe2", "Vulkan", "llama.cpp", "Ollama",
            "LM Studio", "local LLM", "24GB VRAM", "Qwen 27B", "speculative decoding", "flash attention", "benchmarks", "Claude Code", "Codex"]

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
         "runtimePlatform": "Windows 11, Linux"},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=1, ensure_ascii=False).replace("</", "<\\/")

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
    open(os.path.join(docs, "sitemap.xml"), "w", encoding="utf-8", newline="\n").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n  <url>\n    <loc>%s</loc>\n    <changefreq>weekly</changefreq>\n  </url>\n</urlset>\n' % SITE_URL)
    open(os.path.join(docs, "robots.txt"), "w", encoding="utf-8", newline="\n").write("User-agent: *\nAllow: /\n\nSitemap: %ssitemap.xml\n" % SITE_URL)
    shutil.copyfile(os.path.join(ROOT, "assets", "social-preview.png"), os.path.join(docs, "assets", "social-preview.png"))
    print("site -> docs/index.html (%d bytes), docs/sitemap.xml, docs/robots.txt, docs/assets/social-preview.png" % len(page))

if __name__ == "__main__":
    main()
