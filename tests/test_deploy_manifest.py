"""Checks tools/deploy/make_bundle.sh against a throwaway git repo (no network, no PC)."""
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "deploy" / "make_bundle.sh"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git") or not shutil.which("bash"):
        pytest.skip("git/bash not available")
    r = tmp_path / "r"
    (r / "gateway" / "tests").mkdir(parents=True)
    (r / "gateway" / "comfy_nodes" / "elz_nodes").mkdir(parents=True)
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "gateway" / "video.py").write_text("v1\n")
    (r / "gateway" / "old.py").write_text("old\n")
    (r / "gateway" / "tests" / "t.py").write_text("t1\n")
    (r / "README.md").write_text("r1\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "one")
    (r / "gateway" / "video.py").write_text("v2\n")
    (r / "gateway" / "comfy_nodes" / "elz_nodes" / "n.py").write_text("n\n")
    (r / "gateway" / "tests" / "t.py").write_text("t2\n")
    (r / "README.md").write_text("r2\n")
    (r / "gateway" / "old.py").unlink()
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "two")
    return r


def test_bundle_manifest(repo, tmp_path):
    out = tmp_path / "b.zip"
    res = subprocess.run(["bash", str(SCRIPT), "HEAD~1", "HEAD", str(out)], cwd=repo, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == hashlib.sha256(out.read_bytes()).hexdigest()
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert names[0] == "MANIFEST.json"
        m = json.loads(z.read("MANIFEST.json"))
        paths = [f["path"] for f in m["files"]]
        assert paths == ["gateway/comfy_nodes/elz_nodes/n.py", "gateway/video.py"]
        assert sorted(names[1:]) == sorted(paths)  # no tests/, no README
        for f in m["files"]:
            assert hashlib.sha256(z.read(f["path"])).hexdigest() == f["sha256"]
    assert m["deleted"] == ["gateway/old.py"]
    assert m["from"] == git(repo, "rev-parse", "HEAD~1") and m["to"] == git(repo, "rev-parse", "HEAD")


def test_bad_args():
    res = subprocess.run(["bash", str(SCRIPT), "only-one"], capture_output=True, text=True)
    assert res.returncode == 64
