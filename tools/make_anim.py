"""Animated SVGs for the README (CSS keyframes inside SVG; play 3 times then rest on the final frame;
users with prefers-reduced-motion see the final frame immediately). Usage: python tools/make_anim.py"""
import os, html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
T = {
    "dark": dict(bg="#0D1117", panel="#161B22", ink="#E6EDF3", ink2="#9DA7B3", grid="#21262D", stock="#4F7BFF", opt="#E8661E", third="#B26FE0", code="#C9D1D9"),
    "light": dict(bg="#FFFFFF", panel="#F6F8FA", ink="#1F2328", ink2="#59636E", grid="#E6E9EC", stock="#2F5BEA", opt="#D9581A", third="#8E4FC8", code="#24292F"),
}
SANS = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace"
ITER = 3

def esc(s): return html.escape(s, quote=True)

def save(name, theme, svg):
    open(os.path.join(OUT, f"{name}-{theme}.svg"), "w", encoding="utf-8").write(svg)

def motion(rules):
    """Static final frame by default; animate only when the viewer has not asked for reduced motion."""
    return "@media (prefers-reduced-motion: no-preference){" + "".join(rules) + "}"

CODE = [
    "def merge_intervals(intervals):",
    "    out = []",
    "    for s, e in sorted(intervals):",
    "        if out and s <= out[-1][1]:",
    "            out[-1][1] = max(out[-1][1], e)",
    "        else:",
    "            out.append([s, e])",
    "    return out",
]
TOKENS = 85  # approximate token count of CODE

def token_race(theme):
    t = T[theme]; W, H = 1000, 420; cycle = 9.0
    panels = [("No drafter (stock or Intel FA build)", 16.0, t["stock"], 40), ("arc-llm-lab (Intel FA + DFlash2)", 42.3, t["opt"], 520)]
    css = [f"text{{font-family:{SANS}}} .code{{font-family:{MONO};font-size:15px;fill:{t['code']}}}"]
    anim = []; body = []
    total_chars = sum(len(l) for l in CODE)
    for pi, (label, rate, col, x0) in enumerate(panels):
        dur = TOKENS / rate; start = 0.6
        body.append(f'<rect x="{x0}" y="80" width="440" height="270" rx="12" fill="{t["panel"]}" stroke="{t["grid"]}"/>')
        body.append(f'<circle cx="{x0+22}" cy="102" r="5" fill="{col}"/><text x="{x0+36}" y="107" font-size="14" fill="{t["ink"]}" font-weight="600">{esc(label)}</text>')
        acc = 0
        for li, line in enumerate(CODE):
            a = (start + dur * acc / total_chars) / cycle * 100
            acc += len(line)
            b = (start + dur * acc / total_chars) / cycle * 100
            k = f"r{pi}_{li}"
            anim.append(f"@keyframes {k}{{0%,{a:.2f}%{{clip-path:inset(0 100% 0 0)}}{b:.2f}%,100%{{clip-path:inset(0 0 0 0)}}}}"
                       f".{k}{{animation:{k} {cycle}s linear {ITER} forwards}}")
            body.append(f'<text class="code {k}" x="{x0+22}" y="{140+li*24}" xml:space="preserve">{esc(line)}</text>')
        endp = (start + dur) / cycle * 100
        kd = f"d{pi}"
        anim.append(f"@keyframes {kd}{{0%,{endp:.2f}%{{opacity:0}}{min(endp+2,100):.2f}%,100%{{opacity:1}}}}.{kd}{{animation:{kd} {cycle}s linear {ITER} forwards}}")
        body.append(f'<text class="{kd}" x="{x0+418}" y="335" text-anchor="end" font-size="15" font-weight="700" fill="{col}">done in {dur:.1f} s at {rate:g} tok/s</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Same code generated at 16 tokens per second without a draft model (llama-bench) versus 42.3 tokens per second with the DFlash2 draft model (eval-suite throughput) on an Intel Arc Pro B60">'
           f'<style>{"".join(css)}{motion(anim)}</style><rect width="{W}" height="{H}" fill="{t["bg"]}"/>'
           f'<text x="40" y="44" font-size="22" font-weight="700" fill="{t["ink"]}">Same 27B model, same Arc Pro B60: 2.6x faster generation with speculative decoding</text>'
           f'<text x="40" y="68" font-size="14" fill="{t["ink2"]}">Real-time replay at measured speeds, Qwen3.8-27B Q4_K_M, ~{TOKENS} tokens</text>'
           + "".join(body) +
           f'<text x="40" y="395" font-size="12" fill="{t["ink2"]}">Rates: data/speculative-decoding-sweep.csv (no drafter 16.0 = llama-bench tg32, identical on stock and Intel FA builds; DFlash2 n=7 42.3 = eval-suite throughput, wall-clock; per-request decode 47-58, mean 53.3)</text></svg>')
    save("anim-token-race", theme, svg)

def agent_race(theme):
    import csv
    t = T[theme]; W, H = 1000, 318; scale = 20.0  # 1 s of animation = 20 s of real time
    turns = list(csv.DictReader(open(os.path.join(ROOT, "data", "agent-turns.csv"), encoding="utf-8")))
    secs_of = lambda prefix: float(next(r["three_turn_wall_s"] for r in turns if r["config"].startswith(prefix)))
    rows = [("Before\u2020: stock Vulkan + drafter", secs_of("stock Vulkan + drafter"), t["stock"]), ("arc-llm-lab: Intel FA, f16 KV, final tuned", secs_of("Intel FA tuned"), t["opt"])]
    cycle = 201 / scale + 3.0; x0, maxw = 330, 560
    css = [f"text{{font-family:{SANS}}}"]; anim = []; body = []
    for i, (lab, secs, col) in enumerate(rows):
        y = 110 + i * 80; w = maxw * secs / 201; endp = (0.5 + secs / scale) / cycle * 100; startp = 0.5 / cycle * 100
        k = f"b{i}"; kl = f"l{i}"
        anim.append(f"@keyframes {k}{{0%,{startp:.2f}%{{transform:scaleX(0)}}{endp:.2f}%,100%{{transform:scaleX(1)}}}}.{k}{{transform-box:fill-box;transform-origin:left center;animation:{k} {cycle:.2f}s linear {ITER} forwards}}")
        anim.append(f"@keyframes {kl}{{0%,{endp:.2f}%{{opacity:0}}{min(endp+3,100):.2f}%,100%{{opacity:1}}}}.{kl}{{animation:{kl} {cycle:.2f}s linear {ITER} forwards}}")
        body.append(f'<text x="{x0-16}" y="{y+27}" text-anchor="end" font-size="16" fill="{t["ink"]}">{esc(lab)}</text>')
        body.append(f'<rect x="{x0}" y="{y}" width="{maxw}" height="40" rx="6" fill="{t["grid"]}" opacity="0.6"/>')
        body.append(f'<rect class="{k}" x="{x0}" y="{y}" width="{w:.1f}" height="40" rx="6" fill="{col}"/>')
        body.append(f'<text class="{kl}" x="{x0+w+12:.1f}" y="{y+27}" font-size="18" font-weight="700" fill="{t["ink"]}">{secs:g} s</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Three agent turns at 30K context: 201 seconds before (observed before logging was in place, no raw log), 56.7 seconds with arc-llm-lab">'
           f'<style>{"".join(css)}{motion(anim)}</style><rect width="{W}" height="{H}" fill="{t["bg"]}"/>'
           f'<text x="40" y="44" font-size="22" font-weight="700" fill="{t["ink"]}">Three agentic coding turns at 30K+ context</text>'
           f'<text x="40" y="68" font-size="14" fill="{t["ink2"]}">Time-lapse, 20x speed. Each turn: ~3K new tokens on a 30-37K conversation, 400 tokens written.</text>'
           + "".join(body) +
           f'<text x="40" y="282" font-size="12" fill="{t["ink2"]}">Source: data/agent-turns.csv (final tuned config shown: 56.7 s; first Intel FA build: 54.9 s)</text>'
           f'<text x="40" y="300" font-size="12" fill="{t["ink2"]}">\u2020 Observed before logging was in place; raw log not retained; re-run planned.</text></svg>')
    save("anim-agent-race", theme, svg)

def depth_draw(theme):
    import csv
    t = T[theme]; W, H = 1000, 460
    rows = list(csv.DictReader(open(os.path.join(ROOT, "data", "prompt-speed-vs-depth.csv"), encoding="utf-8")))
    X = lambda d: 120 + d / 32768 * 640; Y = lambda v: 390 - v / 700 * 300
    series = [("intel-fa", "f16", "Intel FA kernel, f16 KV", t["opt"]), ("stock-vulkan", "f16", "Stock Vulkan, f16 KV", t["stock"]), ("intel-fa", "q4_0", "Intel FA kernel, q4 KV", t["third"])]
    css = [f"text{{font-family:{SANS}}}"]; anim = []; body = []
    for v in range(0, 701, 100):
        body.append(f'<line x1="120" x2="780" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{t["grid"]}"/><text x="108" y="{Y(v)+5:.1f}" text-anchor="end" font-size="13" fill="{t["ink2"]}">{v}</text>')
    for d, lab in ((0, "empty"), (16384, "16K tokens"), (32768, "32K tokens")):
        body.append(f'<text x="{X(d):.1f}" y="416" text-anchor="middle" font-size="14" fill="{t["ink2"]}">{lab}</text>')
    for si, (cfg, kv, lab, col) in enumerate(series):
        pts = [(X(int(r["depth_tokens"])), Y(float(r["pp2048_tok_s"])), float(r["pp2048_tok_s"])) for r in rows if r["config"] == cfg and r["kv_cache"] == kv]
        path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)
        k = f"s{si}"; delay = 0.4 + si * 0.5
        anim.append(f"@keyframes {k}{{from{{stroke-dashoffset:1000}}to{{stroke-dashoffset:0}}}}.{k}{{stroke-dasharray:1000;stroke-dashoffset:1000;animation:{k} 1.8s ease-out {delay}s forwards}}"
                   f"@keyframes f{k}{{from{{opacity:0}}to{{opacity:1}}}}.f{k}{{opacity:0;animation:f{k} .4s ease-out {delay+1.6}s forwards}}")
        body.append(f'<path class="{k}" d="{path}" fill="none" stroke="{col}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        for x, y, _ in pts:
            body.append(f'<circle class="f{k}" cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{col}" stroke="{t["bg"]}" stroke-width="2"/>')
        x, y, v = pts[-1]; dy = {2: 22}.get(si, 0)
        body.append(f'<text class="f{k}" x="{x+14:.1f}" y="{y+5+dy:.1f}" font-size="14" fill="{t["ink"]}">{esc(lab)}: <tspan font-weight="700">{v:.0f} tok/s</tspan></text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Prompt processing speed versus context depth on Arc Pro B60: Intel FA with f16 KV 420 tokens per second at 32K, stock 118, q4 KV 101">'
           f'<style>{"".join(css)}{motion(anim)}</style><rect width="{W}" height="{H}" fill="{t["bg"]}"/>'
           f'<text x="40" y="40" font-size="22" font-weight="700" fill="{t["ink"]}">Reading long prompts: 3.6x faster at 32K, only with f16 KV</text>'
           f'<text x="40" y="64" font-size="14" fill="{t["ink2"]}">Prompt processing, tokens/s (llama-bench pp2048) as the conversation grows</text>'
           + "".join(body) +
           f'<text x="40" y="446" font-size="12" fill="{t["ink2"]}">Source: data/prompt-speed-vs-depth.csv (raw: data/raw/compare-f16.txt, compare-q4.txt)</text></svg>')
    save("anim-prompt-depth", theme, svg)

if __name__ == "__main__":
    for th in T:
        token_race(th); agent_race(th); depth_draw(th)
    print("animations ->", OUT)
