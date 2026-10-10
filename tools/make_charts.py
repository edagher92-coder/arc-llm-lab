"""Regenerate every README chart from data/*.csv, in GitHub light and dark themes.
Usage: python tools/make_charts.py      (needs matplotlib; Inter font optional)
Palette validated for CVD / contrast on both surfaces (see docs/METHOD.md)."""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, OUT = os.path.join(ROOT, "data"), os.path.join(ROOT, "assets")
FONT = "Inter" if any("Inter" in f.name for f in font_manager.fontManager.ttflist) else "DejaVu Sans"

THEMES = {
    "dark": dict(bg="#0D1117", ink="#E6EDF3", ink2="#9DA7B3", grid="#21262D", stock="#4F7BFF", opt="#E8661E", third="#B26FE0"),
    "light": dict(bg="#FFFFFF", ink="#1F2328", ink2="#59636E", grid="#E6E9EC", stock="#2F5BEA", opt="#D9581A", third="#8E4FC8"),
}

def rows(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))

def frame(t, w=10, h=5.6):
    plt.rcParams.update({"font.family": FONT, "font.size": 12})
    fig, ax = plt.subplots(figsize=(w, h), dpi=160)
    fig.patch.set_facecolor(t["bg"]); ax.set_facecolor(t["bg"])
    for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], length=0, labelsize=11)
    ax.grid(axis="y", color=t["grid"], linewidth=1); ax.set_axisbelow(True)
    return fig, ax

def titles(fig, t, title, sub, source):
    fig.text(0.06, 0.93, title, color=t["ink"], fontsize=17, fontweight="bold", ha="left")
    fig.text(0.06, 0.875, sub, color=t["ink2"], fontsize=11.5, ha="left")
    fig.text(0.06, 0.03, source, color=t["ink2"], fontsize=9.5, ha="left")

def save(fig, name, theme):
    fig.savefig(os.path.join(OUT, f"{name}-{theme}.png"), facecolor=fig.get_facecolor())
    plt.close(fig)

def prompt_depth(theme):
    t = THEMES[theme]; d = rows("prompt-speed-vs-depth.csv")
    fig, ax = frame(t); fig.subplots_adjust(left=0.08, right=0.80, top=0.80, bottom=0.16)
    series = [("intel-fa", "f16", "Intel FA kernel, f16 KV", t["opt"]), ("stock-vulkan", "f16", "Stock Vulkan, f16 KV", t["stock"]),
              ("intel-fa", "q4_0", "Intel FA kernel, q4 KV", t["third"])]
    for cfg, kv, label, col in series:
        pts = [(int(r["depth_tokens"]) / 1024, float(r["pp2048_tok_s"])) for r in d if r["config"] == cfg and r["kv_cache"] == kv]
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color=col, linewidth=2.2, marker="o", markersize=8, markeredgecolor=t["bg"], markeredgewidth=2, zorder=3)
        dy = {"Intel FA kernel, q4 KV": -22}.get(label, 0)
        ax.annotate(f"{label}\n{ys[-1]:.0f} tok/s", (xs[-1], ys[-1]), xytext=(12, dy), textcoords="offset points",
                    color=t["ink"], fontsize=10.5, va="center")
    ax.set_xticks([0, 16, 32]); ax.set_xticklabels(["empty", "16K tokens", "32K tokens"])
    ax.set_xlim(-2, 34); ax.set_ylim(0, 720); ax.set_ylabel("prompt processing, tokens/s", color=t["ink2"])
    titles(fig, t, "Intel's FA kernel reads long prompts 3.6x faster, but only with f16 KV",
           "Arc Pro B60 24GB, llama.cpp Vulkan b11524, Qwen3.8-27B Q4_K_M, llama-bench pp2048 at increasing context depth",
           "Source: data/prompt-speed-vs-depth.csv (raw: data/raw/compare-f16.txt, compare-q4.txt). Stock q4 KV is identical to Intel FA q4 KV.")
    save(fig, "prompt-speed-vs-depth", theme)

def agent_turns(theme):
    t = THEMES[theme]; d = rows("agent-turns.csv")
    fig, ax = frame(t, h=4.8); fig.subplots_adjust(left=0.34, right=0.93, top=0.76, bottom=0.18)
    ax.grid(axis="y", visible=False); ax.grid(axis="x", color=t["grid"], linewidth=1)
    labels = ["Before: stock Vulkan + drafter", "Intel FA kernel, f16 KV", "Final: tuned for 64K context"]
    vals = [201, 54.9, 56.7]; cols = [t["stock"], t["opt"], t["opt"]]
    y = list(range(len(vals)))[::-1]
    for yi, v, c in zip(y, vals, cols):
        ax.add_patch(FancyBboxPatch((0, yi - 0.28), v, 0.56, boxstyle="round,pad=0,rounding_size=0.12", linewidth=0, facecolor=c, mutation_aspect=0.08))
        ax.text(v + 3, yi, f"{v:.0f} s" if v > 100 else f"{v:.1f} s", va="center", color=t["ink"], fontsize=12, fontweight="bold")
    ax.set_yticks(y); ax.set_yticklabels(labels, color=t["ink"], fontsize=11.5); ax.set_xlim(0, 230); ax.set_ylim(-0.6, 2.6)
    ax.set_xlabel("wall-clock seconds for 3 agent turns (lower is better)", color=t["ink2"])
    titles(fig, t, "Three agentic coding turns at 30K+ context: 201 s to 55 s",
           "Each turn reads ~3K new tokens on top of a 30-37K token conversation and writes 400 tokens",
           "Source: data/agent-turns.csv (raw: data/raw/server-test.txt, bench-history.csv). 'Before' measured during the session; raw log not retained.")
    save(fig, "agent-turns", theme)

def drafter(theme):
    t = THEMES[theme]; d = [r for r in rows("speculative-decoding-sweep.csv") if r["code_avg_tok_s"]]
    fig, ax = frame(t); fig.subplots_adjust(left=0.08, right=0.97, top=0.80, bottom=0.22)
    names = [r["setting"].replace("DFlash2 ", "").replace(" (chosen)", ", chosen") for r in d]
    vals = [float(r["code_avg_tok_s"]) for r in d]
    for i, (r, v) in enumerate(zip(d, vals)):
        col = t["stock"] if r["draft_n_max"] == "0" else (t["opt"] if "chosen" in r["setting"] else t["third"])
        ax.add_patch(FancyBboxPatch((i - 0.32, 0), 0.64, v, boxstyle="round,pad=0,rounding_size=0.06", linewidth=0, facecolor=col, mutation_aspect=20))
        ax.text(i, v + 1.2, f"{v:.1f}", ha="center", color=t["ink"], fontsize=12, fontweight="bold")
        fv = r["free_vram_gib"]
        ax.text(i, -7.5, (f"{fv} GiB free" if fv else "no draft model"), ha="center", color=t["ink2"], fontsize=10)
    ax.set_xticks(range(len(d))); ax.set_xticklabels(names, color=t["ink"], fontsize=11)
    ax.set_xlim(-0.6, len(d) - 0.4); ax.set_ylim(0, 50); ax.set_ylabel("generation, tokens/s (coding average)", color=t["ink2"])
    titles(fig, t, "Speculative decoding: 16 to 42 tok/s, until VRAM runs out",
           "DFlash2 draft model, draft length n. Under ~1.1 GiB free VRAM, generation collapses. Every setting: 7/7 coding, 3/3 tools.",
           "Source: data/speculative-decoding-sweep.csv (raw: data/raw/tune.txt). 'no drafter' = llama-bench tg32; others = 7-task coding average.")
    save(fig, "speculative-decoding", theme)

def vram(theme):
    t = THEMES[theme]; d = rows("vram-budget-64k.csv")
    fig, ax = frame(t, h=3.4); fig.subplots_adjust(left=0.06, right=0.94, top=0.72, bottom=0.14)
    ax.grid(False); ax.spines["bottom"].set_visible(False); ax.set_yticks([]); ax.set_xticks([])
    cols = [t["stock"], t["opt"], t["third"], None]
    names = ["Model + DFlash2 drafter", "KV cache, 64K tokens (f16)", "Other apps (desktop)", "Free headroom"]
    x = 0
    for r, c in zip(d, cols):
        g = float(r["gib"])
        if c: ax.barh(0.55, g - 0.06, left=x, height=0.55, color=c, linewidth=0)
        else: ax.barh(0.55, g - 0.06, left=x, height=0.55, color=t["bg"], edgecolor=t["ink2"], hatch="///", linewidth=1)
        x += g
    for i, (r, c, nm) in enumerate(zip(d, cols, names)):
        kx = i * 6.0
        if c: ax.add_patch(plt.Rectangle((kx, -0.42), 0.45, 0.32, color=c, linewidth=0))
        else: ax.add_patch(plt.Rectangle((kx, -0.42), 0.45, 0.32, facecolor=t["bg"], edgecolor=t["ink2"], hatch="///", linewidth=1))
        ax.text(kx + 0.7, -0.26, f"{float(r['gib']):.2f} GiB", ha="left", va="center", color=t["ink"], fontsize=11, fontweight="bold")
        ax.text(kx + 0.7, -0.62, nm, ha="left", va="center", color=t["ink2"], fontsize=10)
    ax.set_xlim(0, 23.88); ax.set_ylim(-0.9, 1.0)
    titles(fig, t, "Where 24GB goes at 64K context",
           "23.88 GiB usable on the Arc Pro B60. The governor always keeps at least 1.35-1.5 GiB free.", "Source: data/vram-budget-64k.csv")
    save(fig, "vram-budget", theme)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for th in THEMES:
        prompt_depth(th); agent_turns(th); drafter(th); vram(th)
    print("charts ->", OUT)
