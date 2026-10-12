"""Check (and optionally install) what family-reel needs, then prove it works with a self-test.

  python doctor.py                         report what works on this machine
  python doctor.py --install core          Python packages, Playwright + a browser, fonts   (~300 MB)
  python doctor.py --install depth         + torch/transformers + Depth Anything V2        (~1.5 GB)
  python doctor.py --install ai            + diffusers/insightface + portrait models        (~7 GB)
  python doctor.py --selftest [--keep]     render a 10 s demo reel from generated images

Tiers: core = photos, videos, captions, original score, render (always the goal);
depth = 2.5D parallax camera moves; ai = "growing up / ageing" portraits.
Nothing needs admin rights: Node packages go to ~/.cache/family-reel/node, models to
~/.cache/family-reel/models (override with MODELS_DIR), fonts to ~/.cache/family-reel/fonts.
"""
import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("FAMILY_REEL_CACHE", Path.home() / ".cache" / "family-reel"))
NODE_PREFIX = CACHE / "node"
MODELS = Path(os.environ.get("MODELS_DIR", CACHE / "models"))
FONT_CACHE = CACHE / "fonts"

CORE_PY = {"PIL": "pillow", "numpy": "numpy", "scipy": "scipy", "mido": "mido", "imageio_ffmpeg": "imageio-ffmpeg",
           "cv2": "opencv-python-headless", "pillow_heif": "pillow-heif"}
DEPTH_PY = {"torch": "torch", "transformers": "transformers", "huggingface_hub": "huggingface_hub"}
AI_PY = {"diffusers": "diffusers", "accelerate": "accelerate", "safetensors": "safetensors", "insightface": "insightface",
         "onnxruntime": "onnxruntime", "spandrel": "spandrel"}
OPTIONAL = {"pillow_heif"}
# (folder, file that proves it is there, how to fetch it)
DEPTH_MODELS = [("depth-base", "config.json", ("snapshot", "depth-anything/Depth-Anything-V2-Base-hf", None))]
AI_MODELS = [
    ("pixar-lcm", "model_index.json", ("snapshot", "iamanaiart/LCM-disneyPixarCartoon_v10",
                                       ["model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "unet/*", "vae/*", "feature_extractor/*"])),
    ("faceid", "ip-adapter-faceid_sd15.bin", ("file", "h94/IP-Adapter-FaceID", ["ip-adapter-faceid_sd15.bin"])),
    ("buffalo_l", "detection/model.onnx", ("file", "immich-app/buffalo_l", ["detection/model.onnx", "recognition/model.onnx"])),
    ("esrgan", "RealESRGAN_x4plus.safetensors", ("file", "Comfy-Org/Real-ESRGAN_repackaged", ["RealESRGAN_x4plus.safetensors"])),
    ("esrgan_x2", "diffusion_pytorch_model.safetensors", ("file", "hlky/RealESRGAN_x2plus", ["diffusion_pytorch_model.safetensors"])),
]
FONT_CSS = ("https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;1,500"
            "&family=Great+Vibes&family=Montserrat:wght@500&display=swap")
FONT_FILES = {("Cormorant Garamond", "normal"): "CormorantGaramond-Medium.ttf",
              ("Cormorant Garamond", "italic"): "CormorantGaramond-MediumItalic.ttf",
              ("Great Vibes", "normal"): "GreatVibes-Regular.ttf", ("Montserrat", "normal"): "Montserrat-Medium.ttf"}

OK, NO, OPT = "ok ", "-- ", " ~ "


def have(mod):
    return importlib.util.find_spec(mod) is not None


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def pip_install(pkgs, extra=()):
    if not pkgs:
        return True
    print("  pip install", " ".join(pkgs))
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *extra, *pkgs]
    r = run(cmd)
    if r.returncode and "externally-managed" in (r.stdout + r.stderr):  # Debian/Homebrew Pythons (PEP 668)
        r = run(cmd[:4] + ["--user", "--break-system-packages"] + cmd[4:])
    if r.returncode:
        print("  pip failed:\n" + (r.stderr or r.stdout)[-1500:])
    return r.returncode == 0


# ---------- node / playwright / browser ----------
def node_env():
    env = dict(os.environ)
    paths = [str(NODE_PREFIX / "node_modules")]
    npm = shutil.which("npm")
    if npm:
        r = run([npm, "root", "-g"])
        if r.returncode == 0:
            paths.append(r.stdout.strip())
    env["NODE_PATH"] = os.pathsep.join(paths + ([env["NODE_PATH"]] if env.get("NODE_PATH") else []))
    return env


BROWSER_PROBE = r"""
const pw = (() => { for (const m of ['playwright', 'playwright-core']) { try { return require(m); } catch (e) {} } return null; })();
if (!pw) { console.log(JSON.stringify({playwright: false})); process.exit(0); }
(async () => {
  const fs = require('fs');
  const tries = [['bundled Chromium', {}], ['Google Chrome', {channel: 'chrome'}], ['Microsoft Edge', {channel: 'msedge'}]];
  const envPath = process.env.CHROME_PATH || process.env.BROWSER_PATH; if (envPath) tries.unshift(['$CHROME_PATH', {executablePath: envPath}]);
  for (const p of ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome']) if (fs.existsSync(p)) tries.push([p, {executablePath: p}]);
  for (const [name, o] of tries) { try { const b = await pw.chromium.launch(o); await b.close(); console.log(JSON.stringify({playwright: true, browser: name})); return; } catch (e) {} }
  console.log(JSON.stringify({playwright: true, browser: null}));
})();
"""


def probe_browser():
    node = shutil.which("node")
    if not node:
        return {"node": None}
    ver = run([node, "--version"]).stdout.strip()
    f = Path(tempfile.gettempdir()) / "family_reel_probe.cjs"
    f.write_text(BROWSER_PROBE)
    r = run([node, str(f)], env=node_env(), timeout=120)
    try:
        info = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        info = {"playwright": False}
    info["node"] = ver
    return info


def install_node_bits(info):
    npm = shutil.which("npm")
    if not info.get("node") or not npm:
        print("  Node.js is missing: install it from https://nodejs.org (or: brew install node / winget install OpenJS.NodeJS), then rerun.")
        return
    if not info.get("playwright"):
        NODE_PREFIX.mkdir(parents=True, exist_ok=True)
        print(f"  npm install playwright -> {NODE_PREFIX}")
        r = run([npm, "install", "--prefix", str(NODE_PREFIX), "--no-audit", "--no-fund", "playwright"])
        if r.returncode:
            print("  npm failed:\n" + r.stderr[-1500:])
            return
        info.update(probe_browser())
    if not info.get("browser"):
        cli = NODE_PREFIX / "node_modules" / "playwright" / "cli.js"
        print("  installing Playwright's Chromium (~150 MB)")
        cmd = [shutil.which("node"), str(cli), "install", "chromium"] if cli.exists() else [shutil.which("npx") or "npx", "playwright", "install", "chromium"]
        r = run(cmd, env=node_env())
        if r.returncode:
            print("  browser download failed (" + (r.stderr or r.stdout)[-300:].strip() + ")\n"
                  "  Install Google Chrome or Microsoft Edge instead, or set CHROME_PATH to any Chromium-based browser.")


# ---------- fonts ----------
def ensure_fonts(dst=None, download=True):
    """Copy the four reel fonts into dst (a project's fonts/), downloading them once into the cache."""
    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    missing = [f for f in FONT_FILES.values() if not (FONT_CACHE / f).exists()]
    if missing and download:
        try:
            css = urllib.request.urlopen(urllib.request.Request(FONT_CSS, headers={"User-Agent": "Mozilla/4.0"}), timeout=15).read().decode()
            for block in re.findall(r"@font-face\s*{([^}]*)}", css):
                fam = re.search(r"font-family:\s*'([^']+)'", block).group(1)
                style = re.search(r"font-style:\s*(\w+)", block).group(1)
                url = re.search(r"url\((https://[^)]+)\)", block).group(1)
                name = FONT_FILES.get((fam, style))
                if name and not (FONT_CACHE / name).exists():
                    (FONT_CACHE / name).write_bytes(urllib.request.urlopen(url, timeout=30).read())
        except Exception as e:
            print(f"  fonts not downloaded ({e.__class__.__name__}); system fonts will stand in")
    ok = all((FONT_CACHE / f).exists() for f in FONT_FILES.values())
    if ok and dst:
        Path(dst).mkdir(parents=True, exist_ok=True)
        for f in FONT_FILES.values():
            shutil.copy2(FONT_CACHE / f, Path(dst) / f)
    return ok


# ---------- music ----------
def find_soundfont():
    import glob
    cands = [os.environ.get("SOUNDFONT", ""), "/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2",
             "/usr/share/soundfonts/default.sf2"] + glob.glob(str(CACHE / "*.sf2"))
    cands += glob.glob("/opt/homebrew/share/soundfonts/*.sf2") + glob.glob("/usr/local/share/soundfonts/*.sf2")
    return next((c for c in cands if c and os.path.exists(c)), None)


# ---------- models ----------
def models_present(spec):
    return [(d, (MODELS / d / proof).exists()) for d, proof, _ in spec]


def download_models(spec):
    from huggingface_hub import hf_hub_download, snapshot_download
    for d, proof, (kind, repo, files) in spec:
        if (MODELS / d / proof).exists():
            continue
        print(f"  downloading {repo} -> {MODELS / d}")
        if kind == "snapshot":
            snapshot_download(repo, local_dir=str(MODELS / d), allow_patterns=files)
        else:
            for f in files:
                hf_hub_download(repo, f, local_dir=str(MODELS / d))


# ---------- report ----------
def report(project=None):
    print(f"family-reel doctor  |  {platform.system()} {platform.machine()}  |  Python {platform.python_version()}  |  {os.cpu_count()} CPUs")
    free = shutil.disk_usage(Path.home()).free / 1e9
    print(f"free disk: {free:.1f} GB   cache: {CACHE}")
    tiers = {}
    miss_core = [p for m, p in CORE_PY.items() if m not in OPTIONAL and not have(m)]
    print("\nCORE (photos, video clips, captions, original score, render)")
    for m, p in CORE_PY.items():
        print(f"  [{OK if have(m) else (OPT if m in OPTIONAL else NO)}] {p}" + ("  (optional: iPhone HEIC photos)" if m in OPTIONAL else ""))
    b = probe_browser()
    print(f"  [{OK if b.get('node') else NO}] Node.js {b.get('node') or 'missing'}")
    print(f"  [{OK if b.get('playwright') else NO}] Playwright")
    print(f"  [{OK if b.get('browser') else NO}] browser: {b.get('browser') or 'none can start'}")
    sf2, fs = find_soundfont(), shutil.which("fluidsynth")
    print(f"  [{OK if fs and sf2 else OPT}] FluidSynth + soundfont" + ("" if fs and sf2 else "  (optional: the built-in synth is used instead)"))
    fonts = all((FONT_CACHE / f).exists() for f in FONT_FILES.values()) or (project and all((Path(project) / 'fonts' / f).exists() for f in FONT_FILES.values()))
    print(f"  [{OK if fonts else OPT}] reel fonts" + ("" if fonts else "  (optional: system fonts stand in)"))
    tiers["core"] = not miss_core and b.get("browser")
    print("\nDEPTH (2.5D parallax camera moves)")
    for m, p in DEPTH_PY.items():
        print(f"  [{OK if have(m) else NO}] {p}")
    dm = models_present(DEPTH_MODELS)
    for d, ok in dm:
        print(f"  [{OK if ok else NO}] model {d}")
    tiers["depth"] = tiers["core"] and all(have(m) for m in DEPTH_PY) and all(ok for _, ok in dm)
    print("\nAI PORTRAITS (growing up / ageing together)")
    for m, p in AI_PY.items():
        print(f"  [{OK if have(m) else NO}] {p}")
    am = models_present(AI_MODELS)
    for d, ok in am:
        print(f"  [{OK if ok else NO}] model {d}")
    tiers["ai"] = tiers["depth"] and all(have(m) for m in AI_PY) and all(ok for _, ok in am)
    print("\nREADY:", ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in tiers.items()))
    if not tiers["core"]:
        print("next: python doctor.py --install core")
    return tiers, b


def install(tier, project=None):
    order = ["core", "depth", "ai"]
    for t in order[: order.index(tier) + 1]:
        print(f"\n== installing {t} ==")
        if t == "core":
            pip_install([p for m, p in CORE_PY.items() if not have(m)])
            install_node_bits(probe_browser())
            ensure_fonts(Path(project) / "fonts" if project else None)
        if t in ("depth", "ai"):
            if not have("torch"):
                extra = ("--index-url", "https://download.pytorch.org/whl/cpu") if platform.system() == "Linux" else ()
                pip_install(["torch"], extra)  # CPU build: no multi-GB CUDA download
            pip_install([p for m, p in DEPTH_PY.items() if m != "torch" and not have(m)])
            download_models(DEPTH_MODELS)
        if t == "ai":
            if platform.system() == "Windows" and not have("insightface"):
                print("  note: insightface compiles a small C++ extension on Windows (needs Visual Studio Build Tools);"
                      " if it fails, run the AI tier under WSL.")
            pip_install([p for m, p in AI_PY.items() if not have(m)])
            download_models(AI_MODELS)
        importlib.invalidate_caches()


# ---------- self-test ----------
def selftest(keep=False):
    import numpy as np
    from PIL import Image, ImageDraw
    import imageio_ffmpeg
    sys.path.insert(0, str(Path(__file__).parent))
    from new_reel import copy_engine
    t_start = time.time()
    proj = Path(tempfile.mkdtemp(prefix="family-reel-selftest-"))
    copy_engine(proj)
    up = proj / "uploads"
    up.mkdir()
    ensure_fonts(proj / "fonts")
    rng = np.random.default_rng(3)
    for i, (w, h) in enumerate([(1200, 1600), (1200, 1600), (1600, 1000), (1200, 1600)]):
        yy, xx = np.mgrid[0:h, 0:w]
        c0, c1 = rng.integers(40, 220, 3), rng.integers(40, 220, 3)
        a = (yy / h)[..., None]
        img = Image.fromarray((c0 * (1 - a) + c1 * a).astype(np.uint8))
        d = ImageDraw.Draw(img)
        for _ in range(12):
            x, y, r = rng.integers(0, w), rng.integers(0, h), rng.integers(30, 160)
            d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
        img.save(up / f"photo{i + 1}.jpg", quality=90)
    # a sprite clip (dark ball bouncing on a light plain background) and a short video clip
    def clip(path, w, h, n, draw):
        gen = imageio_ffmpeg.write_frames(str(path), (w, h), fps=24, macro_block_size=8)
        gen.send(None)
        for k in range(n):
            gen.send(draw(k))
        gen.close()

    def ball(k):
        f = np.full((320, 320, 3), (239, 243, 247), np.uint8)
        yy, xx = np.mgrid[0:320, 0:320]
        cy = 200 - 60 * abs(np.sin(k / 6))
        f[(xx - 160) ** 2 + (yy - cy) ** 2 < 70 ** 2] = (60, 70, 90)
        return f

    def bars(k):
        f = np.zeros((360, 640, 3), np.uint8)
        for j in range(8):
            f[:, j * 80:(j + 1) * 80] = ((j * 40 + k * 5) % 255, (j * 90) % 255, 200 - j * 20)
        return f
    clip(up / "pet.mp4", 320, 320, 36, ball)
    clip(up / "clip.mp4", 640, 360, 96, bars)
    scenes = {
        "name": "family-reel self-test", "width": 1080, "height": 1920, "fps": 30, "duration": 10, "output": "out/selftest.mp4",
        "intro": {"t1": 2.2},
        "photos": {"p1": {"file": "photo1.jpg", "blur": [[0.1, 0.1, 0.4, 0.3]]}, "p2": {"file": "photo3.jpg"}},
        "videos": {"v1": {"src": "clip.mp4", "ss": 0.5, "speed": 0.85}},
        "cards": {"a": {"file": "photo2.jpg", "box": [0.2, 0.2, 0.8, 0.65]}, "b": {"file": "photo4.jpg", "box": [0.2, 0.2, 0.8, 0.65], "whiten": True}},
        "sprites": {"pet": {"src": "pet.mp4", "fps": 12}},
        "shots": [{"photo": "p1", "t0": 2.2, "t1": 5.0, "fade": 0.7, "from": [0.5, 0.5, 1.0], "to": [0.5, 0.45, 0.8]},
                  {"video": "v1", "t0": 4.5, "t1": 6.8, "fade": 0.6},
                  {"photo": "p2", "t0": 6.3, "t1": 8.3, "fade": 0.6, "fit": True}],
        "captions": [{"t0": 0.3, "t1": 2.2, "y": 900, "theme": "intro", "lines": ["*Self-test*", "FAMILY REEL"]},
                     {"t0": 2.8, "t1": 4.8, "y": 1300, "lines": ["THE ENGINE WORKS —", "*on this machine.*"]}],
        "blooms": [{"t": 4.9, "y": 820, "size": 1}], "lightLeaks": [5.2], "petalsFrom": 8,
        "endcard": {"t0": 7.8, "faces": [{"card": "a", "slot": [360, 560, 150], "label": "One", "at": 8.0},
                                         {"card": "b", "slot": [720, 560, 150], "label": "Two", "at": 8.2}],
                    "sprite": {"name": "pet", "x": 540, "y": 980, "h": 220, "at": 8.3, "fps": 12, "label": "Pet"},
                    "lines": [{"t": 8.5, "y": 1250, "text": "~Self-test~", "scale": 0.62}], "divider": {"t": 8.8, "y": 1360}},
        "score": {"strings_at": 2.5},
    }
    (proj / "scenes.json").write_text(json.dumps(scenes, indent=1))
    env = node_env()
    steps = [("prep", [sys.executable, "prep.py", str(up)]), ("score", [sys.executable, "compose.py"]),
             ("render", [shutil.which("node") or "node", "render.cjs"])]
    ok = True
    for name, cmd in steps:
        t = time.time()
        r = run(cmd, cwd=proj, env=env)
        print(f"  {name:7s} {'ok ' if r.returncode == 0 else 'FAILED'}  {time.time() - t:5.1f}s")
        if r.returncode:
            print((r.stdout + r.stderr)[-2000:])
            ok = False
            break
    if ok:
        sys.path.insert(0, str(Path(__file__).parent))
        from finish import probe
        info = probe(proj / "out" / "selftest.mp4")
        ok = info["frames"] == 300 and info["audio"]
        print(f"  verify  {'ok ' if ok else 'FAILED'}  {info['frames']} frames, {info['duration']:.2f} s, audio: {info['audio']}")
    print(("SELF-TEST PASSED" if ok else "SELF-TEST FAILED") + f" in {time.time() - t_start:.0f}s")
    if keep or not ok:
        print("project kept at", proj)
    else:
        shutil.rmtree(proj, ignore_errors=True)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install", choices=["core", "depth", "ai"])
    ap.add_argument("--project", help="a reel project folder (fonts are copied into it)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the self-test project")
    a = ap.parse_args()
    if a.install:
        install(a.install, a.project)
        print()
    tiers, _ = report(a.project)
    if a.selftest:
        print("\n== self-test ==")
        sys.exit(0 if selftest(a.keep) else 1)


if __name__ == "__main__":
    main()
