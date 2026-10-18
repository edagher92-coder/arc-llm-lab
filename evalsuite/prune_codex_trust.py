"""Remove per-workdir trust tables that eval runs leave in the lean Codex home's config.toml.
Only [projects.'<path>'] tables whose path is under C:\\AI\\evalsuite\\work are removed; everything else is kept
byte-for-byte. Writes a timestamped backup first (kept: newest 3) and replaces the file atomically.
Usage: python prune_codex_trust.py [--dry-run] [config.toml]"""
import datetime, glob, os, re, sys

DEFAULT = r"C:\AI\codex-local\home\config.toml"
HDR = re.compile(r"""^\[projects\.(['"])(.*?)\1\]\s*$""")
PREFIX = r"c:\ai\evalsuite\work" + "\\"

def prune(text):
    out, removed, skipping = [], 0, False
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s.startswith("["):
            m = HDR.match(s)
            path = m.group(2).replace("\\\\", "\\").lower() if m else ""
            skipping = bool(m) and path.startswith(PREFIX)
            if skipping:
                removed += 1
                continue
        if skipping:
            continue
        out.append(line)
    return "".join(out), removed

def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    path = args[0] if args else DEFAULT
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    new, removed = prune(text)
    kept = len(re.findall(r"(?m)^\[projects\.", new))
    print(f"evalsuite trust tables: {removed} to remove, {kept} project tables kept, {len(raw)} -> {len(new.encode('utf-8'))} bytes")
    if dry or removed == 0:
        return
    bak = path + ".bak-prune-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    open(bak, "wb").write(raw)
    for old in sorted(glob.glob(path + ".bak-prune-*"))[:-3]:
        os.remove(old)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    os.replace(tmp, path)
    print("written; backup:", os.path.basename(bak))

if __name__ == "__main__":
    main()
