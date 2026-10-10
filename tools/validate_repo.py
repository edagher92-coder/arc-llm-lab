"""Repository checks that need no GPU (run by CI, safe to run locally).
  1. data/community/*.json validate against data/community/schema.json          (needs: pip install jsonschema)
  2. .github/ISSUE_TEMPLATE/*.yml parse and have the keys GitHub requires        (needs: pip install pyyaml)
  3. every data/*.csv parses with a constant number of columns
  4. engine/patches/SHA256SUMS matches the patch files
  5. bench/arc-bench.sh (and .ps1 when pwsh is installed) turn bench/fixtures/llama-bench-sample.json into a result
     that validates against the schema, and the two scripts agree on the numbers
Usage: python tools/validate_repo.py        (exit code 1 if anything fails; missing optional packages are reported and skipped)"""
import csv, glob, hashlib, json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails, skipped = [], []
def ok(msg): print("ok    " + msg)
def fail(msg): fails.append(msg); print("FAIL  " + msg)
def skip(msg): skipped.append(msg); print("skip  " + msg)

def load_schema():
    return json.load(open(os.path.join(ROOT, "data", "community", "schema.json"), encoding="utf-8"))

def check_community():
    try: import jsonschema
    except ImportError: return skip("community JSON: jsonschema is not installed")
    schema = load_schema(); jsonschema.Draft202012Validator.check_schema(schema)
    files = [p for p in sorted(glob.glob(os.path.join(ROOT, "data", "community", "*.json"))) if os.path.basename(p) != "schema.json"]
    for p in files:
        try: jsonschema.validate(json.load(open(p, encoding="utf-8")), schema); ok("schema: " + os.path.basename(p))
        except Exception as e: fail("schema: %s: %s" % (os.path.basename(p), str(e).splitlines()[0]))
    if not files: skip("no community results yet")

def check_templates():
    try: import yaml
    except ImportError: return skip("issue templates: PyYAML is not installed")
    for p in sorted(glob.glob(os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", "*.yml"))):
        n = os.path.basename(p)
        try: d = yaml.safe_load(open(p, encoding="utf-8"))
        except Exception as e: fail("template %s does not parse: %s" % (n, str(e).splitlines()[0])); continue
        if n == "config.yml": ok("template " + n); continue
        missing = [k for k in ("name", "description", "body") if k not in d]
        ids = [b.get("id") for b in d.get("body", []) if b.get("id")]
        if missing: fail("template %s lacks %s" % (n, missing))
        elif len(ids) != len(set(ids)): fail("template %s has duplicate ids" % n)
        else: ok("template " + n)

def check_csv():
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "*.csv"))):
        rows = list(csv.reader(open(p, encoding="utf-8", newline="")))
        bad = [i + 1 for i, r in enumerate(rows) if len(r) != len(rows[0])]
        (fail if bad else ok)("csv %s%s" % (os.path.basename(p), " rows with a different column count: %s" % bad if bad else ""))

def check_patches():
    d = os.path.join(ROOT, "engine", "patches"); lines = [l for l in open(os.path.join(d, "SHA256SUMS"), encoding="utf-8").read().splitlines() if l.strip()]
    for l in lines:
        h, _, name = l.partition("  ")
        got = hashlib.sha256(open(os.path.join(d, name.strip()), "rb").read()).hexdigest()
        (ok if got == h else fail)("sha256 " + name.strip())
    if len(lines) != len(glob.glob(os.path.join(d, "*.patch"))): fail("SHA256SUMS does not list every .patch file")

def run_bench_script(kind, out):
    fx = os.path.join(ROOT, "bench", "fixtures", "llama-bench-sample.json")
    if kind == "sh":
        if not shutil.which("bash") or not shutil.which("python3"): return skip("arc-bench.sh: bash or python3 missing")
        cmd = ["bash", os.path.join(ROOT, "bench", "arc-bench.sh"), "--from-json", fx, "--vram-gb", "24", "--contributor", "CI", "--driver", "ci", "--os", "ci", "--out-dir", out]
    else:
        pw = shutil.which("pwsh") or os.environ.get("PWSH")
        if not pw: return skip("arc-bench.ps1: pwsh is not installed")
        cmd = [pw, "-NoProfile", "-File", os.path.join(ROOT, "bench", "arc-bench.ps1"), "-FromJson", fx, "-VramGb", "24", "-Contributor", "CI", "-Driver", "ci", "-OsName", "ci", "-OutDir", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: return fail("arc-bench.%s exited %d: %s" % (kind, r.returncode, (r.stderr or r.stdout).strip()[-300:]))
    files = glob.glob(os.path.join(out, "*.json"))
    if len(files) != 1: return fail("arc-bench.%s wrote %d result files" % (kind, len(files)))
    return json.load(open(files[0], encoding="utf-8"))

def check_bench():
    res = {}
    for kind in ("sh", "ps1"):
        with tempfile.TemporaryDirectory() as out:
            d = run_bench_script(kind, out)
            if not d: continue
            res[kind] = d
            try:
                import jsonschema; jsonschema.validate(d, load_schema()); ok("arc-bench.%s output validates" % kind)
            except ImportError: skip("arc-bench.%s: schema check needs jsonschema" % kind)
            except Exception as e: fail("arc-bench.%s output: %s" % (kind, str(e).splitlines()[0]))
    if len(res) == 2:
        a, b = ({k: v for k, v in r.items() if k not in ("cpu", "ram_gb")} for r in (res["sh"], res["ps1"]))
        (ok if a == b else fail)("arc-bench.sh and arc-bench.ps1 agree")

if __name__ == "__main__":
    for f in (check_community, check_templates, check_csv, check_patches, check_bench): f()
    print("\n%d failed, %d skipped" % (len(fails), len(skipped)))
    sys.exit(1 if fails else 0)
