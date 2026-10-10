#!/usr/bin/env bash
# arc-bench.sh - measure your Intel Arc GPU with llama-bench (Linux) and write a community result file.
#
#   bench/arc-bench.sh -m /path/Qwen3.8-27B-UD-Q4_K_M.gguf --vram-gb 24 --contributor "Your Name"
#
# Runs:  llama-bench -ngl 99 -fa 1 -ctk f16 -ctv f16 -p 2048 -n 32 -d 0,16384,32768 -r 1 -o json
# (the flags of bench/compare-f16.ps1; GGML_VK_FORCE_MMVQ=1 is added with --mmvq). Needs bash and python3.
# Writes: <out-dir>/<date>-<gpu>-<backend>-<build>.json following data/community/schema.json, prints a markdown row,
# and tells you how to submit it: https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: arc-bench.sh -m MODEL.gguf --vram-gb N [options]
  -m, --model PATH        GGUF to benchmark (required unless --from-json)
  -b, --bench PATH        llama-bench binary (default: $LLAMA_BENCH or llama-bench on PATH)
  -d, --depths LIST       context depths, default 0,16384,32768
  -o, --out-dir DIR       where to write the result (default ./arc-bench-results)
      --vram-gb N         VRAM of the card in GB (required)
      --gpu NAME          card name (default: what llama-bench reports)
      --contributor NAME  name or handle to credit (default: anonymous; your login name is never used unless you pass it)
      --driver TEXT       driver version (default: auto-detected where possible)
      --os TEXT           operating system (default: auto-detected)
      --patches LIST      comma-separated commit SHAs or names applied on top of the build (default: none)
      --notes TEXT        anything that helped or hurt (flags, free VRAM, power, temperatures)
      --raw-log-url URL   link to the raw output if you posted it somewhere
      --mmvq              set GGML_VK_FORCE_MMVQ=1 (what the maintainer's results use)
      --from-json FILE    skip the run and convert an existing `llama-bench -o json` output
  -h, --help
USAGE
}

MODEL=""; BENCH="${LLAMA_BENCH:-llama-bench}"; DEPTHS="0,16384,32768"; OUT_DIR="./arc-bench-results"
VRAM=""; GPU=""; CONTRIB="anonymous"; DRIVER=""; OSNAME=""; PATCHES=""; NOTES=""; RAWURL=""; MMVQ=0; FROM_JSON=""
while [ $# -gt 0 ]; do
  case "$1" in
    -m|--model) MODEL="$2"; shift 2;;
    -b|--bench) BENCH="$2"; shift 2;;
    -d|--depths) DEPTHS="$2"; shift 2;;
    -o|--out-dir) OUT_DIR="$2"; shift 2;;
    --vram-gb) VRAM="$2"; shift 2;;
    --gpu) GPU="$2"; shift 2;;
    --contributor) CONTRIB="$2"; shift 2;;
    --driver) DRIVER="$2"; shift 2;;
    --os) OSNAME="$2"; shift 2;;
    --patches) PATCHES="$2"; shift 2;;
    --notes) NOTES="$2"; shift 2;;
    --raw-log-url) RAWURL="$2"; shift 2;;
    --mmvq) MMVQ=1; shift;;
    --from-json) FROM_JSON="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2;;
  esac
done
command -v python3 >/dev/null || { echo "python3 is required to write the result file" >&2; exit 2; }
[ -n "$VRAM" ] || { echo "--vram-gb is required (for example --vram-gb 24)" >&2; usage >&2; exit 2; }
awk -v v="$VRAM" 'BEGIN{exit !(v ~ /^[0-9]+(\.[0-9]+)?$/ && v+0 > 0)}' || { echo "--vram-gb must be a positive number, got '$VRAM'" >&2; exit 2; }

mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
if [ -n "$FROM_JSON" ]; then
  RAW="$FROM_JSON"; FLAGS="(converted from an existing llama-bench -o json file)"
else
  [ -n "$MODEL" ] && [ -f "$MODEL" ] || { echo "model file not found: ${MODEL:-<none>}" >&2; usage >&2; exit 2; }
  command -v "$BENCH" >/dev/null || [ -x "$BENCH" ] || { echo "llama-bench not found: $BENCH (use --bench PATH)" >&2; exit 2; }
  RAW="$OUT_DIR/llama-bench-$STAMP.json"
  FLAGS="llama-bench -ngl 99 -fa 1 -ctk f16 -ctv f16 -p 2048 -n 32 -d $DEPTHS -r 1"
  if [ "$MMVQ" = 1 ]; then export GGML_VK_FORCE_MMVQ=1; FLAGS="GGML_VK_FORCE_MMVQ=1 $FLAGS"; fi
  echo "Running: $FLAGS   (about 5-15 minutes for a 27B model)" >&2
  "$BENCH" -m "$MODEL" -ngl 99 -fa 1 -ctk f16 -ctv f16 -p 2048 -n 32 -d "$DEPTHS" -r 1 -o json >"$RAW" 2>"$RAW.stderr" \
    || { echo "llama-bench failed; see $RAW.stderr" >&2; exit 1; }
fi

if [ -z "$OSNAME" ]; then
  if [ -r /etc/os-release ]; then OSNAME="$(. /etc/os-release; echo "${PRETTY_NAME:-Linux}") (kernel $(uname -r))"; else OSNAME="$(uname -sr)"; fi
fi
if [ -z "$DRIVER" ]; then
  DRIVER="$( (vulkaninfo --summary 2>/dev/null | grep -m1 -iE 'driverInfo' | sed 's/^[^=]*= *//') || true)"
  [ -n "$DRIVER" ] || DRIVER="unknown (please edit this field)"
fi
CPU="$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | sed 's/.*: *//' || true)"
RAMGB="$(awk '/MemTotal/ {printf "%d", $2/1048576+0.5}' /proc/meminfo 2>/dev/null || true)"

ARC_RAW="$RAW" ARC_OUT_DIR="$OUT_DIR" ARC_VRAM="$VRAM" ARC_GPU="$GPU" ARC_CONTRIB="$CONTRIB" ARC_DRIVER="$DRIVER" ARC_OS="$OSNAME" \
ARC_PATCHES="$PATCHES" ARC_NOTES="$NOTES" ARC_RAWURL="$RAWURL" ARC_FLAGS="$FLAGS" ARC_CPU="$CPU" ARC_RAMGB="$RAMGB" ARC_DATE="$(date +%F)" \
ARC_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" python3 - <<'PY'
import json, os, re, sys
E = os.environ
rows = json.load(open(E["ARC_RAW"], encoding="utf-8"))
if isinstance(rows, dict): rows = [rows]
if not rows: sys.exit("llama-bench output contained no results")
first = rows[0]
backend = str(first.get("backends", "")).strip() or "unknown"
if backend.upper() in ("CPU", "BLAS", "CPU,BLAS"):
    sys.exit("llama-bench ran on the CPU only (backends: %s). Check that your build has Vulkan or SYCL and that the GPU is visible." % backend)
backend = ",".join(b for b in backend.split(",") if b.upper() not in ("CPU", "BLAS", "RPC")) or backend
depth = {}
for r in rows:
    d = str(int(r.get("n_depth", 0))); npr = int(r.get("n_prompt", 0)); ngen = int(r.get("n_gen", 0))
    cell = depth.setdefault(d, {})
    if npr > 0 and ngen == 0 and npr >= cell.get("pp_tokens", 0):
        cell.update(pp_tok_s=round(float(r["avg_ts"]), 2), pp_tokens=npr, pp_stddev=round(float(r.get("stddev_ts", 0)), 2))
    elif ngen > 0 and npr == 0 and ngen >= cell.get("tg_tokens", 0):
        cell.update(tg_tok_s=round(float(r["avg_ts"]), 2), tg_tokens=ngen, tg_stddev=round(float(r.get("stddev_ts", 0)), 2))
depth = {d: c for d, c in depth.items() if "pp_tok_s" in c and "tg_tok_s" in c}
if not depth: sys.exit("no complete pp/tg pairs found in the llama-bench output")
fname = os.path.basename(str(first.get("model_filename", "")).replace("\\", "/")) or str(first.get("model_type", "unknown"))
m = re.search(r"(?<![A-Za-z])((?:UD-)?(?:IQ\d(?:_[A-Z0-9]+)*|Q\d(?:_[A-Z0-9]+)*|MXFP4|BF16|F16|F32))", fname, re.I)
gpu = E["ARC_GPU"] or str(first.get("gpu_info", "")).strip() or "unknown GPU"
build = "b%s (%s)" % (first.get("build_number", "?"), first.get("build_commit", "?"))
res = {
    "schema_version": 1, "contributor": E["ARC_CONTRIB"], "date": E["ARC_DATE"], "gpu": gpu, "vram_gb": float(E["ARC_VRAM"]) if "." in E["ARC_VRAM"] else int(E["ARC_VRAM"]),
    "driver": E["ARC_DRIVER"], "os": E["ARC_OS"], "backend": backend, "llama_cpp_build": build,
    "patches": [p.strip() for p in E["ARC_PATCHES"].split(",") if p.strip()],
    "model": fname, "quant": m.group(1) if m else "unknown",
    "kv_cache": {"k": str(first.get("type_k", "f16")), "v": str(first.get("type_v", "f16"))},
    "flash_attn": str(first.get("flash_attn", 1)).strip().lower() not in ("0", "false", "off", "disabled", "no"), "flags": E["ARC_FLAGS"],
    "depth_results": dict(sorted(depth.items(), key=lambda kv: int(kv[0]))), "repeats": 1,
}
if E["ARC_CPU"]: res["cpu"] = E["ARC_CPU"]
if E["ARC_RAMGB"].isdigit() and int(E["ARC_RAMGB"]) > 0: res["ram_gb"] = int(E["ARC_RAMGB"])
if E["ARC_RAWURL"]: res["raw_log_url"] = E["ARC_RAWURL"]
if E["ARC_NOTES"]: res["notes"] = E["ARC_NOTES"]
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]
path = os.path.join(E["ARC_OUT_DIR"], "%s-%s-%s-%s-%s.json" % (E["ARC_DATE"], slug(gpu), slug(backend), slug(build), slug(res["quant"])))
json.dump(res, open(path, "w", encoding="utf-8"), indent=2); open(path, "a").write("\n")
try:
    import jsonschema
    schema = json.load(open(os.path.join(E["ARC_SCRIPT_DIR"], "..", "data", "community", "schema.json"), encoding="utf-8"))
    jsonschema.validate(res, schema); print("schema: valid", file=sys.stderr)
except ImportError: pass
except FileNotFoundError: pass
print("\nWrote %s\n" % path)
ds = sorted(depth, key=int)
fmt = lambda k: " / ".join("%.1f" % depth[d][k] for d in ds)
print("| GPU | VRAM | Backend / build | Model | pp%d at depth %s (tok/s) | tg%d at depth %s (tok/s) | By |" % (depth[ds[0]].get("pp_tokens", 2048), "/".join(ds), depth[ds[0]].get("tg_tokens", 32), "/".join(ds)))
print("|---|---|---|---|---|---|---|")
print("| %s | %s GB | %s %s%s | %s %s | %s | %s | %s |" % (gpu, E["ARC_VRAM"], backend, build, " + %d patch(es)" % len(res["patches"]) if res["patches"] else "", fname, res["quant"], fmt("pp_tok_s"), fmt("tg_tok_s"), E["ARC_CONTRIB"]))
print("\nShare it: open https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml and paste the JSON file,")
print("or add it to data/community/ in a pull request. Please also attach the raw llama-bench output.")
PY
