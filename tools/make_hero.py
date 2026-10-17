"""Hero banner, per-task decode chart, GPU-contention chart, project-scale card and social preview.
Usage: python tools/make_hero.py      (needs matplotlib; Inter font optional)
Reads data/decode-per-request.csv, data/gpu-contention-20261017.csv and data/vram-budget-64k.csv.
Same palette and themes as tools/make_charts.py (validated for colour-vision deficiency in light and dark);
every value is printed on the chart, so colour never carries meaning alone."""
import csv, os, subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Circle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, OUT = os.path.join(ROOT, "data"), os.path.join(ROOT, "assets")
FONT = "Inter" if any("Inter" in f.name for f in font_manager.fontManager.ttflist) else "DejaVu Sans"
plt.rcParams.update({"font.family": FONT})

THEMES = {
    "dark": dict(bg="#0D1117", card="#161B22", edge="#30363D", ink="#E6EDF3", ink2="#9DA7B3", grid="#21262D",
                 stock="#4F7BFF", opt="#E8661E", third="#B26FE0", glow="#3D6BFF"),
    "light": dict(bg="#FFFFFF", card="#F6F8FA", edge="#D0D7DE", ink="#1F2328", ink2="#59636E", grid="#E6E9EC",
                  stock="#2F5BEA", opt="#D9581A", third="#8E4FC8", glow="#2F5BEA"),
}

def rows(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))

def canvas(t, w, h):
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=200)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off")
    return fig, ax

def card(ax, t, x, y, w, h, accent=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=14", linewidth=1.2,
                                edgecolor=t["edge"], facecolor=t["card"]))
    if accent:
        ax.add_patch(FancyBboxPatch((x, y + h - 6), w, 6, boxstyle="round,pad=0,rounding_size=3", linewidth=0, facecolor=accent))

def save(fig, name):
    fig.savefig(os.path.join(OUT, name), facecolor=fig.get_facecolor())
    plt.close(fig)

# ---------------------------------------------------------------- data
dec = rows("decode-per-request.csv")
drafted = [float(r["decode_tok_s"]) for r in dec if r["kv_window_tokens"]]
stock = float(next(r["decode_tok_s"] for r in dec if not r["kv_window_tokens"]))
mean = sum(drafted) / len(drafted)
kv_window = int(next(r["kv_window_tokens"] for r in dec if r["kv_window_tokens"]))

# ---------------------------------------------------------------- hero banner
def hero(theme):
    t = THEMES[theme]; W, H = 1600, 620
    fig, ax = canvas(t, W, H)
    for r, a in ((330, .05), (250, .07), (170, .09)):
        ax.add_patch(Circle((1420, 470), r, color=t["glow"], alpha=a, linewidth=0))
    ax.text(70, 548, "arc-llm-lab", color=t["opt"], fontsize=17, fontweight="bold")
    ax.text(70, 488, "Qwen3.8-27B at 50+ tok/s on one Intel Arc GPU", color=t["ink"], fontsize=33, fontweight="bold")
    ax.text(72, 444, "Arc Pro B60 24GB · llama.cpp Vulkan · Intel flash-attention prefill kernel · DFlash2 speculative decoding · 64K context window",
            color=t["ink2"], fontsize=13.5)
    tiles = [
        (f"{mean:.0f} tok/s", f"mean decode, 7 coding tasks\n(peak {max(drafted):.0f}; stock {stock:.0f})", t["opt"]),
        (f"{kv_window // 1024}K", "context window on 24GB\n(f16 KV, drafter loaded)", t["stock"]),
        ("3.6x", "faster prompt reading at 32K\n(118 to 420 tok/s)", t["third"]),
        ("97/100", "hidden-checker agent tasks\n(Claude Code, 32K window)", t["opt"]),
        ("A$999", "24GB card (dated AU price);\nno cloud, no API bill", t["stock"]),
    ]
    tw, gap, x0, y0, th = 276, 20, 70, 120, 250
    for i, (big, small, col) in enumerate(tiles):
        x = x0 + i * (tw + gap)
        card(ax, t, x, y0, tw, th, accent=col)
        ax.text(x + 24, y0 + th - 92, big, color=t["ink"], fontsize=31, fontweight="bold")
        ax.text(x + 24, y0 + th - 130, small, color=t["ink2"], fontsize=12.5, va="top", linespacing=1.5)
    ax.text(70, 62, "Single runs on one workstation, raw logs in data/raw/. Decode is per-request server speed with a 64K KV window allocated and short prompts;"
            " at 30-37K of real context agent turns generate about 42 tok/s.", color=t["ink2"], fontsize=11)
    ax.text(70, 36, "Prices and caveats are dated in the README. Built and measured by Elie Dagher.", color=t["ink2"], fontsize=11)
    save(fig, f"hero-{theme}.png")

# ---------------------------------------------------------------- per-task decode
def decode_chart(theme):
    t = THEMES[theme]
    plt.rcParams.update({"font.size": 12})
    fig, ax = plt.subplots(figsize=(10, 5.8), dpi=160)
    fig.patch.set_facecolor(t["bg"]); ax.set_facecolor(t["bg"])
    fig.subplots_adjust(left=0.30, right=0.95, top=0.76, bottom=0.17)
    for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"]); ax.tick_params(colors=t["ink2"], length=0, labelsize=11)
    ax.grid(axis="x", color=t["grid"], linewidth=1); ax.set_axisbelow(True)
    labels = [r["request"] for r in dec if r["kv_window_tokens"]] + ["Stock llama.cpp, no drafter"]
    vals = drafted + [stock]; cols = [t["opt"]] * len(drafted) + [t["stock"]]
    ys = list(range(len(vals)))[::-1]
    for y, v, c in zip(ys, vals, cols):
        ax.add_patch(FancyBboxPatch((0, y - 0.30), v, 0.60, boxstyle="round,pad=0,rounding_size=0.10", linewidth=0,
                                    facecolor=c, mutation_aspect=0.12))
        ax.text(v - 0.8, y, f"{v:.1f}" if v != stock else f"{v:.2f}", va="center", ha="right", color="#FFFFFF", fontsize=11.5, fontweight="bold")
    ax.axvline(50, color=t["ink2"], linewidth=1.2, linestyle=(0, (4, 3)), zorder=1)
    ax.text(50, len(vals) - 0.35, "50 tok/s ", color=t["ink2"], fontsize=10.5, va="bottom", ha="right")
    ax.axvline(mean, color=t["opt"], linewidth=1.2, linestyle=(0, (1, 2)), zorder=1)
    ax.text(mean, len(vals) - 0.35, f" mean {mean:.1f}", color=t["ink"], fontsize=10.5, va="bottom", ha="left")
    ax.set_yticks(ys); ax.set_yticklabels(labels, color=t["ink"], fontsize=11)
    ax.set_xlim(0, 66); ax.set_ylim(-0.7, len(vals) - 0.2); ax.set_xlabel("generation (decode), tokens/s", color=t["ink2"])
    fig.text(0.04, 0.93, f"Every coding task decodes at 47-58 tok/s; {sum(v >= 50 for v in drafted)} of {len(drafted)} clear 50",
             color=t["ink"], fontsize=16.5, fontweight="bold")
    fig.text(0.04, 0.885, f"Arc Pro B60 24GB, Qwen3.8-27B UD-Q4_K_M + DFlash2 drafter (n=7), {kv_window:,}-token f16 KV window allocated, short prompts, temp 0.2",
             color=t["ink2"], fontsize=10.5, va="top")
    fig.text(0.04, 0.03, "Source: data/decode-per-request.csv (raw: data/raw/tune.txt, row n7 ub256 dkv-q8; stock: data/raw/compare-f16.txt tg32). "
             "\nSingle run per task. Coding 7/7 correct in that run.", color=t["ink2"], fontsize=9)
    fig.savefig(os.path.join(OUT, f"decode-per-task-{theme}.png"), facecolor=fig.get_facecolor()); plt.close(fig)

# ---------------------------------------------------------------- GPU contention
def contention(theme):
    t = THEMES[theme]; d = rows("gpu-contention-20261017.csv")
    plt.rcParams.update({"font.size": 12})
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=160)
    fig.patch.set_facecolor(t["bg"]); ax.set_facecolor(t["bg"])
    fig.subplots_adjust(left=0.42, right=0.94, top=0.74, bottom=0.18)
    for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"]); ax.tick_params(colors=t["ink2"], length=0, labelsize=11)
    ax.grid(axis="x", color=t["grid"], linewidth=1); ax.set_axisbelow(True)
    names = {"second idle Ollama model resident on the GPU": "parse_duration: idle Ollama model resident",
             "after unloading the idle Ollama model": "parse_duration: after unloading it",
             "before recovery (53K window)": "merge_intervals: 53K window, contended",
             "larger sizing reserve (32K window) repeat": "merge_intervals: 32K window, more headroom"}
    ys = [3.2, 2.4, 1.0, 0.2]
    for y, r in zip(ys, d):
        v = float(r["gen_tok_s"]); good = v > 40
        ax.add_patch(FancyBboxPatch((0, y - 0.28), v, 0.56, boxstyle="round,pad=0,rounding_size=0.10", linewidth=0,
                                    facecolor=t["opt"] if good else t["stock"], mutation_aspect=0.12))
        ax.text(v + 0.8, y, f"{v:.1f} tok/s · {float(r['wall_s']):.1f} s", va="center", color=t["ink"], fontsize=11, fontweight="bold")
    ax.set_yticks(ys); ax.set_yticklabels([names[r["condition"]] for r in d], color=t["ink"], fontsize=11)
    ax.set_xlim(0, 75); ax.set_ylim(-0.4, 3.7); ax.set_xlabel("generation (decode), tokens/s", color=t["ink2"])
    fig.text(0.04, 0.92, "The #1 slowdown: something else holding VRAM. Free it and decode more than doubled", color=t["ink"], fontsize=16, fontweight="bold")
    fig.text(0.04, 0.87, "Same B60 and model, 17 Oct 2026. An idle Ollama model left on the GPU cut decode from 52.7 to 22.2 tok/s.",
             color=t["ink2"], fontsize=10.5, va="top")
    fig.text(0.04, 0.03, "Source: data/gpu-contention-20261017.csv, docs/OPERATING-PROFILES-20261017.md. Single observations; output length, cache state\n"
             "and (merge_intervals) context size also differ, so this is not a controlled A/B.", color=t["ink2"], fontsize=9)
    fig.savefig(os.path.join(OUT, f"gpu-contention-{theme}.png"), facecolor=fig.get_facecolor()); plt.close(fig)

# ---------------------------------------------------------------- project scale
def code_lines():
    files = subprocess.check_output(["git", "ls-files"], cwd=ROOT).decode().split("\n")
    n = 0
    for f in files:
        if os.path.splitext(f)[1].lower() in (".py", ".ps1", ".js", ".cjs", ".html", ".sh", ".cmd", ".bat"):
            with open(os.path.join(ROOT, f), "rb") as fh: n += fh.read().count(b"\n")
    return n

def project_scale(theme, stats):
    t = THEMES[theme]; W, H = 1600, 620
    fig, ax = canvas(t, W, H)
    ax.text(70, 552, "The project, by the numbers", color=t["ink"], fontsize=27, fontweight="bold")
    ax.text(72, 512, "Not a config gist: an engine build, a governor, agents, a phone studio, local video and an evaluation harness, all measured.",
            color=t["ink2"], fontsize=13.5)
    cols = [t["opt"], t["stock"], t["third"]]
    tw, th, gx, gy = 278, 180, 20, 22
    for i, (big, small) in enumerate(stats):
        x = 70 + (i % 5) * (tw + gx); y = 250 - (i // 5) * (th + gy)
        card(ax, t, x, y, tw, th, accent=cols[i % 3])
        ax.text(x + 22, y + th - 72, big, color=t["ink"], fontsize=27, fontweight="bold")
        ax.text(x + 22, y + th - 108, small, color=t["ink2"], fontsize=12, va="top", linespacing=1.4)
    save(fig, f"project-scale-{theme}.png")

# ---------------------------------------------------------------- social preview (1280x640)
def social():
    t = THEMES["dark"]; t = dict(t, bg="#070D1F", card="#0F1A38", edge="#22325F")
    fig = plt.figure(figsize=(12.8, 6.4), dpi=100); fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1280); ax.set_ylim(0, 640); ax.axis("off")
    for r, a in ((300, .05), (220, .07), (150, .10)):
        ax.add_patch(Circle((1120, 520), r, color="#3D6BFF", alpha=a, linewidth=0))
    ax.text(64, 548, "arc-llm-lab", color="#FF7A2F", fontsize=26, fontweight="bold")
    ax.text(64, 470, "Qwen3.8-27B at 50+ tok/s", color="#E6EEFF", fontsize=48, fontweight="bold")
    ax.text(66, 420, "on one Intel Arc Pro B60 24GB, with a 64K context window", color="#9DB0E0", fontsize=24)
    stats = [(f"{mean:.0f} tok/s", "mean decode"), ("420 tok/s", "prefill at 32K, 3.6x"), ("97/100", "agent tasks"), ("64K", "context on 24GB")]
    for i, (big, small) in enumerate(stats):
        x = 64 + i * 292
        card(ax, t, x, 150, 272, 170, accent="#FF7A2F" if i % 2 == 0 else "#4F7BFF")
        ax.text(x + 22, 238, big, color="#E6EEFF", fontsize=32, fontweight="bold")
        ax.text(x + 22, 190, small, color="#9DB0E0", fontsize=17)
    ax.text(64, 70, "llama.cpp Vulkan · Intel FA kernel · DFlash2 speculative decoding · raw logs published", color="#9DB0E0", fontsize=17)
    ax.text(64, 34, "Single runs, one workstation; decode is per-request with short prompts. Details and caveats in the README.", color="#6F7BA3", fontsize=12)
    fig.savefig(os.path.join(OUT, "social-preview.png"), facecolor=fig.get_facecolor()); plt.close(fig)

if __name__ == "__main__":
    loc = code_lines()
    stats = [
        ("443", "automated tests\n(gateway, studio, video, agents)"),
        ("100", "agent tasks with hidden\ncheckers, CI-verified"),
        ("23", "logged tuning experiments,\neach with a before/after"),
        (f"{loc / 1000:.0f}K", "lines of Python, PowerShell,\nJS and HTML"),
        ("89", "Markdown guides\nand reference docs"),
        ("15", "raw logs and benchmark\nfiles you can re-check"),
        ("~100", "PC, browser and desktop\ntools behind the phone gateway"),
        ("26", "health checks in\nqwen doctor"),
        ("2", "vendored Intel FA kernel\npatches, checksummed"),
        ("3", "AI workloads on one GPU:\ncode, vision, video"),
    ]
    for th in ("dark", "light"):
        hero(th); decode_chart(th); contention(th); project_scale(th, stats)
    social()
    print("ok", loc)
