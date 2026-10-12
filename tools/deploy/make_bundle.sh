#!/usr/bin/env bash
# make_bundle.sh <from_ref> <to_ref> <out.zip>
# Zip of files changed under gateway/ between two refs (tests excluded) plus MANIFEST.json.
# Zip entries use repo paths (gateway/<x>). Prints the zip SHA256 on the last line.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <from_ref> <to_ref> <out.zip>" >&2
  exit 64
fi
FROM_REF=$1
TO_REF=$2
OUT=$3

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 69; }
FROM=$(git rev-parse --verify "$FROM_REF^{commit}")
TO=$(git rev-parse --verify "$TO_REF^{commit}")

case "$OUT" in /*) ;; *) OUT="$(pwd)/$OUT" ;; esac
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/tree"

# Changed (A/M/T) and deleted (D) paths under gateway/, no rename detection, tests and caches excluded.
git diff --name-status --no-renames -z "$FROM" "$TO" -- gateway/ > "$STAGE/diff.bin"
python3 -I - "$STAGE" <<'PY'
import sys, re
stage = sys.argv[1]
parts = open(stage + "/diff.bin", "rb").read().split(b"\0")
parts = [p.decode("utf-8") for p in parts if p]
changed, deleted = [], []
skip = re.compile(r"(^gateway/tests/|/__pycache__/|\.pyc$)")
for i in range(0, len(parts), 2):
    status, path = parts[i], parts[i + 1]
    if skip.search(path):
        continue
    (deleted if status.startswith("D") else changed).append(path)
open(stage + "/changed.txt", "w").write("\n".join(sorted(changed)))
open(stage + "/deleted.txt", "w").write("\n".join(sorted(deleted)))
PY

if [ -s "$STAGE/changed.txt" ]; then
  # Read the committed bytes via git archive (same bytes a manual archive would ship).
  xargs -d '\n' git archive --format=tar "$TO" -- < "$STAGE/changed.txt" | tar -x -C "$STAGE/tree"
fi

python3 -I - "$STAGE" "$FROM" "$TO" "$OUT" <<'PY'
import sys, json, hashlib, zipfile, os
stage, frm, to, out = sys.argv[1:5]
changed = [l for l in open(stage + "/changed.txt").read().split("\n") if l]
deleted = [l for l in open(stage + "/deleted.txt").read().split("\n") if l]
files = []
for p in changed:
    data = open(os.path.join(stage, "tree", p), "rb").read()
    files.append({"path": p, "sha256": hashlib.sha256(data).hexdigest()})
manifest = {"from": frm, "to": to, "files": files, "deleted": deleted}
if os.path.exists(out):
    os.remove(out)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    def add(name, data):
        zi = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))  # fixed time, reproducible zip
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        z.writestr(zi, data)
    add("MANIFEST.json", json.dumps(manifest, indent=2).encode("utf-8"))
    for p in changed:
        add(p, open(os.path.join(stage, "tree", p), "rb").read())
print("files=%d deleted=%d" % (len(files), len(deleted)), file=sys.stderr)
PY

SHA=$(sha256sum "$OUT" | cut -d' ' -f1)
echo "zip:    $OUT" >&2
echo "sha256: $SHA" >&2
echo "$SHA"
