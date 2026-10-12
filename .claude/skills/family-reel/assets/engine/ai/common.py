"""Shared paths and helpers for the optional local-AI steps.

Paths (override with environment variables):
  REEL_DIR     project folder (default: the folder above ai/)
  UPLOADS_DIR  the user's photos (default: <project>/uploads)
  MODELS_DIR   downloaded models, shared by every project (default: ~/.cache/family-reel/models)
  THREADS      CPU threads for torch (default: all cores)
"""
import os
from pathlib import Path

from PIL import Image, ImageOps

try:  # iPhone photos arrive as HEIC
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

AI = Path(__file__).resolve().parent
PROJECT = Path(os.environ.get("REEL_DIR", AI.parent))
UPLOADS = Path(os.environ.get("UPLOADS_DIR", PROJECT / "uploads"))
MODELS = Path(os.environ.get("MODELS_DIR", Path.home() / ".cache" / "family-reel" / "models"))
ASSETS = PROJECT / "assets"
THREADS = int(os.environ.get("THREADS", os.cpu_count() or 4))


def resolve_upload(name):
    """Find an upload by exact name, by Claude upload id (<id>-image.jpg), or by prefix."""
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    for c in (UPLOADS / name, PROJECT / name, UPLOADS / f"{name}-image.jpg"):
        if c.exists():
            return c
    hits = sorted(UPLOADS.glob(f"{name}*"))
    if hits:
        return hits[0]
    raise FileNotFoundError(f"missing upload: {name} (looked in {UPLOADS})")


def load_photo(name):
    return ImageOps.exif_transpose(Image.open(resolve_upload(name))).convert("RGB")


def model(sub):
    p = MODELS / sub
    if not p.exists():
        raise SystemExit(f"model not found: {p}\nRun: python <skill>/scripts/doctor.py --install ai   (or set MODELS_DIR)")
    return p
