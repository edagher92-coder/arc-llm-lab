"""Create (or refresh) a family-reel project folder from the skill's engine.

  python new_reel.py <project_dir>            new project: engine + scenes.json + ai/ configs + folders
  python new_reel.py <project_dir> --update   refresh engine files only (never touches scenes.json or media)

The project keeps everything in one place:
  uploads/   the user's photos and videos (or point UPLOADS_DIR / prep.py at their folder)
  assets/    prepared media (generated)       out/  renders and previews (generated)
  fonts/     Google Fonts (OFL), copied from the cache or downloaded here if missing
"""
import argparse
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ENGINE = SKILL / "assets" / "engine"
TEMPLATES = SKILL / "assets" / "templates"
GITIGNORE = """# personal media and generated files stay out of git
uploads/
assets/
out/
fonts/
node_modules/
*.wav
*.mid
*.mp4
*.mov
*.MOV
# AI working files: face embeddings are biometric data; generated images show family members
ai/out/
ai/chain/
ai/beam/
ai/*.npy
ai/*.jpg
ai/*.png
"""


def copy_engine(dst):
    for f in ENGINE.iterdir():
        if f.is_file() and f.suffix in (".js", ".cjs", ".html", ".py", ".json") and f.name != "__pycache__":
            shutil.copy2(f, dst / f.name)
    (dst / "ai").mkdir(exist_ok=True)
    for f in (ENGINE / "ai").glob("*.py"):
        shutil.copy2(f, dst / "ai" / f.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--update", action="store_true", help="refresh engine files only")
    a = ap.parse_args()
    dst = Path(a.project).expanduser().resolve()
    if dst.exists() and (dst / "scenes.json").exists() and not a.update:
        sys.exit(f"{dst} already has a scenes.json. Use --update to refresh the engine files only.")
    dst.mkdir(parents=True, exist_ok=True)
    copy_engine(dst)
    if a.update:
        print(f"engine refreshed in {dst}")
        return
    shutil.copy2(TEMPLATES / "scenes.example.json", dst / "scenes.json")
    shutil.copy2(TEMPLATES / "people.example.json", dst / "ai" / "people.json")
    shutil.copy2(TEMPLATES / "chain.example.json", dst / "ai" / "chain.json")
    for d in ("uploads", "assets", "out", "fonts"):
        (dst / d).mkdir(exist_ok=True)
    (dst / ".gitignore").write_text(GITIGNORE)
    sys.path.insert(0, str(Path(__file__).parent))
    from doctor import ensure_fonts
    got = ensure_fonts(dst / "fonts")
    print(f"project ready: {dst}")
    print("fonts:", "ok" if got else "not downloaded (system fonts will stand in; run doctor.py --install core when online)")
    print("next: put photos/videos in uploads/, edit scenes.json, then: python prep.py && python compose.py && node render.cjs --stills 5,20")


if __name__ == "__main__":
    main()
