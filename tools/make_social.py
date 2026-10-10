"""Social preview card (1280x640) for GitHub Settings > Social preview."""
import os, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib import font_manager
FONT = "Inter" if any("Inter" in f.name for f in font_manager.fontManager.ttflist) else "DejaVu Sans"
plt.rcParams["font.family"] = FONT
fig = plt.figure(figsize=(12.8, 6.4), dpi=100); fig.patch.set_facecolor("#070D1F")
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1280); ax.set_ylim(0, 640); ax.axis("off")
for r, a in ((260, .05), (200, .07), (140, .10)):
    ax.add_patch(Circle((1090, 330), r, color="#3D6BFF", alpha=a, linewidth=0))
ax.add_patch(Circle((1090, 330), 92, color="#12245C", linewidth=0)); ax.add_patch(Circle((1090, 330), 40, color="#E8661E", alpha=.85, linewidth=0))
ax.add_patch(Circle((1062, 362), 14, color="#FFFFFF", alpha=.55, linewidth=0))
ax.text(70, 520, "arc-llm-lab", color="#E6EEFF", fontsize=58, fontweight="bold")
ax.text(72, 462, "A 27B coding agent on one Intel Arc Pro B60 24GB", color="#8E9BC4", fontsize=24)
stats = [("42 tok/s", "generation, 2.6x"), ("420 tok/s", "reading at 32K, 3.6x"), ("201s → 55s", "3 agent turns"), ("64K", "context, 1.6 GiB spare")]
for i, (big, small) in enumerate(stats):
    x = 72 + (i % 2) * 380; y = 330 - (i // 2) * 120
    ax.text(x, y, big, color="#FF7A2F" if i == 2 else "#E6EEFF", fontsize=34, fontweight="bold")
    ax.text(x, y - 38, small, color="#8E9BC4", fontsize=16)
ax.text(72, 60, "llama.cpp Vulkan, Intel FA kernel, speculative decoding, Claude Code and Codex local, raw data", color="#8E9BC4", fontsize=16)
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "social-preview.png")
fig.savefig(out, facecolor=fig.get_facecolor()); print(out)
