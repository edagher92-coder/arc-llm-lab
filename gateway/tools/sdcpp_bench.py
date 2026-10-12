"""Benchmark harness for stable-diffusion.cpp's sd-cli.exe running LTX video (the C:\\AI\\minimax\\run.cmd style invocation). Standard library only.

It starts sd-cli once per run, samples the host's AVAILABLE memory while it works, kills it if available RAM falls under --min-free-mb
(the LTX Q6_K run froze a 32 GB PC without a guard) and appends one JSON line per run to a results file. It never starts anything else.

  python sdcpp_bench.py --sd-cli C:\\AI\\minimax\\sd-cli.exe --model ltx-2.5-distilled-Q6_K.gguf --llm gemma-4-12b.gguf --vae ltx-vae.safetensors \\
      --audio-vae ltx-audio-vae.safetensors --prompt "a red kettle on a stove" --width 768 --height 416 --frames 73 --steps 8 --runs 2 \\
      --out-dir C:\\AI\\minimax\\out --min-free-mb 400 --results bench-results.jsonl
  python sdcpp_bench.py --selftest

Result keys follow ltx_bench.py (ts, label, variant, flags, workflow, status, params, wall_s, outputs, error, host_ram_peak_mb,
host_ram_delta_mb, host_ram_scope) plus: exit_code, output (first output path), ram_available_min_mb, ram_available_max_mb, ram_samples,
min_free_mb, killed_low_ram, argv. status is "success" (exit 0 and the output file exists), "killed" (below --min-free-mb), "timeout" or "error".

Available RAM comes from psutil when installed, else on Windows from typeperf "\\Memory\\Available MBytes" (the figure to watch: "free" memory
excludes the file cache and gives false alarms), else wmic. Anywhere else no RAM figure exists: the keys are null and nothing is ever killed.

The sd-cli flag names below are the stable-diffusion.cpp ones as I know them (INFERRED, not checked against your build): if your build spells one
differently, change it with --flag-map NAME=--spelling (repeatable), e.g. --flag-map frames=--video-frames, or add anything else with --sd-arg.
"""
import argparse, json, os, re, shlex, subprocess, sys, tempfile, threading, time

SD_FLAGS = {"mode": "-M", "model": "--diffusion-model", "llm": "--llm", "vae": "--vae", "audio_vae": "--audio-vae", "prompt": "-p",
            "width": "-W", "height": "-H", "frames": "--video-frames", "steps": "--steps", "seed": "--seed", "out": "-o"}


class BenchError(Exception):
    pass


# ---------- available RAM ----------
_PS = None


def _psutil():
    global _PS
    if _PS is None:
        try:
            import psutil
            _PS = psutil
        except ImportError:
            _PS = False
    return _PS or None


def available_mb():
    """(available MB, total MB or None) now, or (None, None) when this platform has no way to tell."""
    ps = _psutil()
    if ps:
        try:
            m = ps.virtual_memory()
            return round(m.available / 2 ** 20, 1), round(m.total / 2 ** 20, 1)
        except Exception:
            pass
    if os.name != "nt":
        return None, None
    try:
        o = subprocess.run(["typeperf", r"\Memory\Available MBytes", "-sc", "1"], capture_output=True, text=True, timeout=15).stdout
        for line in o.splitlines():
            m = re.match(r'^"[^"]*","([\d.]+)"', line.strip())
            if m:
                return round(float(m.group(1)), 1), _total_mb_windows()
    except Exception:
        pass
    try:
        o = subprocess.run(["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/value"], capture_output=True, text=True, timeout=15).stdout
        f = re.search(r"FreePhysicalMemory=(\d+)", o)
        t = re.search(r"TotalVisibleMemorySize=(\d+)", o)
        if f:
            return round(int(f.group(1)) / 1024.0, 1), (round(int(t.group(1)) / 1024.0, 1) if t else None)
    except Exception:
        pass
    return None, None


def _total_mb_windows():
    try:
        o = subprocess.run(["wmic", "ComputerSystem", "get", "TotalPhysicalMemory", "/value"], capture_output=True, text=True, timeout=15).stdout
        m = re.search(r"TotalPhysicalMemory=(\d+)", o)
        return round(int(m.group(1)) / 2 ** 20, 1) if m else None
    except Exception:
        return None


def kill_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    ps = _psutil()
    if os.name == "nt":
        subprocess.run(["taskkill", "/f", "/t", "/pid", str(proc.pid)], capture_output=True)
    elif ps:
        try:
            kids = ps.Process(proc.pid).children(recursive=True)
        except Exception:
            kids = []
        for k in kids:
            try:
                k.kill()
            except Exception:
                pass
        proc.kill()
    else:
        proc.kill()
    try:
        proc.wait(30)
    except Exception:
        pass


# ---------- one run ----------
def build_argv(a, out_path, seed, flags=None):
    f = dict(SD_FLAGS, **(flags or {}))
    argv = [a.sd_cli, f["mode"], "vid_gen", f["model"], a.model, f["llm"], a.llm, f["vae"], a.vae]
    if a.audio_vae:
        argv += [f["audio_vae"], a.audio_vae]
    argv += [f["prompt"], a.prompt, f["width"], str(a.width), f["height"], str(a.height), f["frames"], str(a.frames), f["steps"], str(a.steps),
             f["seed"], str(seed), f["out"], out_path]
    for x in a.sd_arg or []:
        argv += shlex.split(x, posix=(os.name != "nt"))
    return argv


class Sampler(threading.Thread):
    """Polls available RAM; if it falls under min_free_mb calls on_low() once (the caller kills sd-cli)."""
    def __init__(self, min_free_mb, on_low, every=0.5, probe=None):
        super().__init__(daemon=True)
        self.min_free, self.on_low, self.every, self.probe = float(min_free_mb), on_low, every, probe or available_mb
        self.stop_ev, self.lo, self.hi, self.first, self.total, self.n, self.tripped = threading.Event(), None, None, None, None, 0, None

    def sample(self):
        av, tot = self.probe()
        if av is None:
            return
        self.n += 1
        self.total = tot if tot is not None else self.total
        self.first = av if self.first is None else self.first
        self.lo = av if self.lo is None else min(self.lo, av)
        self.hi = av if self.hi is None else max(self.hi, av)
        if self.min_free > 0 and av < self.min_free and self.tripped is None:
            self.tripped = av
            try:
                self.on_low(av)
            except Exception:
                pass

    def run(self):
        while not self.stop_ev.is_set():
            self.sample()
            if self.stop_ev.wait(self.every):
                break

    def result(self):
        self.stop_ev.set()
        self.join(5)
        if self.n == 0:
            return {"ram_available_min_mb": None, "ram_available_max_mb": None, "ram_samples": 0, "host_ram_peak_mb": None, "host_ram_delta_mb": None, "host_ram_scope": None}
        d = {"ram_available_min_mb": self.lo, "ram_available_max_mb": self.hi, "ram_samples": self.n, "host_ram_scope": "system-used"}
        if self.total is not None:                           # same meaning as ltx_bench: peak system memory in use, and its rise over the start
            d["host_ram_peak_mb"] = round(self.total - self.lo, 1)
            d["host_ram_delta_mb"] = round(self.first - self.lo, 1)
        else:
            d["host_ram_peak_mb"] = d["host_ram_delta_mb"] = None
        return d


def run_one(a, i, flags=None, probe=None):
    seed = (a.seed + i) if a.seed >= 0 else int(time.time()) % 2 ** 31 + i
    os.makedirs(a.out_dir, exist_ok=True)
    now = time.time()
    out = os.path.join(a.out_dir, "sdcpp_%s%03d_run%d.%s" % (time.strftime("%Y%m%d-%H%M%S", time.localtime(now)), int(now * 1000) % 1000, i + 1, a.ext))
    if os.path.exists(out):                                  # a stale file must never make a failed run look like it produced something
        os.remove(out)
    argv = build_argv(a, out, seed, flags)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "label": a.label, "variant": a.variant, "flags": " ".join(argv[1:]) if a.record_flags else "",
           "workflow": os.path.basename(a.model), "status": "error", "run": i + 1, "argv": [os.path.basename(argv[0])] + argv[1:] if a.record_flags else None,
           "params": {"prompt": a.prompt if len(a.prompt) <= 80 else a.prompt[:77] + "...", "width": a.width, "height": a.height, "frames": a.frames, "steps": a.steps, "seed": seed},
           "min_free_mb": a.min_free_mb, "killed_low_ram": False, "exit_code": None, "output": None, "outputs": []}
    lg = open(os.path.join(a.out_dir, "sdcpp_run%d.log" % (i + 1)), "ab") if a.log else subprocess.DEVNULL
    t0 = time.time()
    try:
        proc = subprocess.Popen(argv, stdout=lg, stderr=subprocess.STDOUT, cwd=a.cwd or None)
    except OSError as ex:
        rec["error"] = "could not start sd-cli: %s" % ex
        rec["wall_s"] = round(time.time() - t0, 2)
        return rec
    killed = threading.Event()
    sam = Sampler(a.min_free_mb, lambda av: (killed.set(), kill_tree(proc)), a.poll, probe)
    sam.start()
    timed_out = False
    try:
        proc.wait(a.timeout if a.timeout > 0 else None)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
    finally:
        rec.update(sam.result())
        if lg is not subprocess.DEVNULL:
            lg.close()
    rec["wall_s"] = round(time.time() - t0, 2)
    rec["exit_code"] = proc.returncode
    exists = os.path.isfile(out) and os.path.getsize(out) > 0
    if exists:
        rec["output"], rec["outputs"] = out, [os.path.basename(out)]
    if killed.is_set():
        rec["status"], rec["killed_low_ram"] = "killed", True
        rec["error"] = "available RAM fell to %.0f MB, under --min-free-mb %g; sd-cli was killed" % (sam.tripped, a.min_free_mb)
    elif timed_out:
        rec["status"], rec["error"] = "timeout", "no exit within %g s; sd-cli was killed" % a.timeout
    elif proc.returncode == 0 and exists:
        rec["status"] = "success"
    else:
        rec["error"] = "exit code %s%s" % (proc.returncode, "" if exists else ", no output file")
    return rec


def append_result(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def parse_flag_map(items):
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep or k.strip() not in SD_FLAGS or not v.strip():
            raise BenchError("--flag-map wants NAME=--spelling with NAME one of: %s (got %r)" % (", ".join(sorted(SD_FLAGS)), it))
        out[k.strip()] = v.strip()
    return out


def parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sd-cli", help="path to sd-cli.exe (or any command that takes the same flags)")
    ap.add_argument("--model", help="the video diffusion model (GGUF)")
    ap.add_argument("--llm", help="the text encoder / LLM file")
    ap.add_argument("--vae", help="the video VAE")
    ap.add_argument("--audio-vae", default="", help="the audio VAE (omit for silent video)")
    ap.add_argument("--prompt")
    ap.add_argument("--width", type=int, default=768)
    ap.add_argument("--height", type=int, default=416)
    ap.add_argument("--frames", type=int, default=73, help="8n+1")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out-dir", default="sdcpp-out", help="where the clips (and per-run logs) go")
    ap.add_argument("--min-free-mb", type=float, default=400, help="kill sd-cli when available RAM falls under this; 0 turns the guard off")
    ap.add_argument("--results", default="bench-results.jsonl", help="JSON-lines file to append to")
    ap.add_argument("--label", default="")
    ap.add_argument("--variant", default="")
    ap.add_argument("--seed", type=int, default=1, help="seed of run 1 (run n uses seed+n-1); -1 = time based")
    ap.add_argument("--ext", default="mp4", help="output file extension")
    ap.add_argument("--timeout", type=float, default=3600, help="seconds per run; 0 = none")
    ap.add_argument("--poll", type=float, default=0.5, help="seconds between RAM samples")
    ap.add_argument("--cwd", default="", help="working directory for sd-cli")
    ap.add_argument("--sd-arg", action="append", default=[], metavar="'--flag value'", help="extra sd-cli arguments, passed through (repeatable)")
    ap.add_argument("--flag-map", action="append", default=[], metavar="NAME=--flag", help="change the spelling of one sd-cli flag (repeatable)")
    ap.add_argument("--no-record-flags", dest="record_flags", action="store_false", help="do not store the command line (it holds the prompt and file paths)")
    ap.add_argument("--no-log", dest="log", action="store_false", help="discard sd-cli's console output instead of keeping it in out-dir")
    ap.add_argument("--selftest", action="store_true")
    return ap


def main(argv=None):
    ap = parser()
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    for k in ("sd_cli", "model", "llm", "vae", "prompt"):
        if not getattr(a, k):
            ap.error("--%s is required" % k.replace("_", "-"))
    try:
        flags = parse_flag_map(a.flag_map)
    except BenchError as ex:
        print("error: %s" % ex, file=sys.stderr)
        return 2
    if available_mb()[0] is None and a.min_free_mb > 0:
        print("note: no way to read available RAM on this platform; the --min-free-mb guard is inactive", file=sys.stderr)
    bad = 0
    for i in range(max(1, a.runs)):
        rec = run_one(a, i, flags)
        append_result(a.results, rec)
        print(json.dumps({k: rec.get(k) for k in ("run", "status", "wall_s", "exit_code", "ram_available_min_mb", "output", "error")}))
        bad += rec["status"] != "success"
        if rec["status"] == "killed":
            break                                              # the next run would only freeze the PC again
    return 1 if bad else 0


# ---------- self test ----------
FAKE = '''import sys, time
a = sys.argv[1:]
out = a[a.index("-o") + 1]
mode = a[a.index("-p") + 1]
if mode == "fail": sys.exit(3)
if mode == "slow": time.sleep(30)
open(out, "wb").write(b"FAKEMP4")
print("ok", flush=True)
'''


def selftest():
    ok = []

    def check(name, cond):
        ok.append(bool(cond))
        print(("PASS " if cond else "FAIL ") + name)

    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "fake_sd.py")
        open(script, "w").write(FAKE)
        exe = os.path.join(d, "fake-sd-cli.cmd" if os.name == "nt" else "fake-sd-cli")
        if os.name == "nt":
            open(exe, "w").write('@"%s" "%s" %%*\r\n' % (sys.executable, script))
        else:
            open(exe, "w").write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, script))
            os.chmod(exe, 0o755)
        res = os.path.join(d, "r.jsonl")
        base = ["--sd-cli", exe, "--model", "m.gguf", "--llm", "l.gguf", "--vae", "v.safetensors", "--audio-vae", "av.safetensors", "--width", "256", "--height", "192",
                "--frames", "9", "--steps", "2", "--out-dir", os.path.join(d, "out"), "--results", res, "--poll", "0.05"]
        a = parser().parse_args(base + ["--prompt", "hello"])
        argv = build_argv(a, "o.mp4", 7)
        check("argv has every flag", all(x in argv for x in ("--diffusion-model", "--llm", "--vae", "--audio-vae", "-W", "256", "-H", "192", "--video-frames", "9", "--steps", "2", "o.mp4")))
        rec = run_one(a, 0, probe=lambda: (2000.0, 8000.0))
        check("success + output + exit 0", rec["status"] == "success" and rec["exit_code"] == 0 and os.path.isfile(rec["output"]) and rec["outputs"])
        check("ram keys", rec["ram_available_min_mb"] == 2000.0 and rec["host_ram_peak_mb"] == 6000.0 and rec["ram_samples"] >= 1 and rec["wall_s"] > 0)
        rec = run_one(parser().parse_args(base + ["--prompt", "fail"]), 0, probe=lambda: (2000.0, 8000.0))
        check("non-zero exit is an error", rec["status"] == "error" and rec["exit_code"] == 3 and rec["output"] is None)
        t0 = time.time()
        rec = run_one(parser().parse_args(base + ["--prompt", "slow", "--min-free-mb", "400"]), 0, probe=lambda: (100.0, 8000.0))
        check("killed when available RAM is under the floor", rec["status"] == "killed" and rec["killed_low_ram"] and time.time() - t0 < 20 and "400" in rec["error"])
        rec = run_one(parser().parse_args(base + ["--prompt", "slow", "--timeout", "0.5"]), 0, probe=lambda: (2000.0, 8000.0))
        check("timeout kills", rec["status"] == "timeout")
        rec = run_one(parser().parse_args(base + ["--prompt", "hello"]), 0, probe=lambda: (None, None))
        check("no RAM source: runs, nulls, never kills", rec["status"] == "success" and rec["ram_available_min_mb"] is None and rec["ram_samples"] == 0)
        rec = run_one(parser().parse_args(base[:1] + [os.path.join(d, "missing.exe")] + base[2:] + ["--prompt", "hello"]), 0)
        check("missing exe reported", rec["status"] == "error" and "could not start" in rec["error"])
        fm = build_argv(a, "o.mp4", 1, parse_flag_map(["frames=--frames"]))
        check("flag map", "--frames" in fm and "--video-frames" not in fm)
        rc = main(base + ["--prompt", "hello", "--runs", "2"])
        lines = [json.loads(x) for x in open(res).read().splitlines()]
        check("main: one JSON line per run, appended", rc == 0 and len(lines) == 2 and [x["run"] for x in lines] == [1, 2])
        ltx_keys = {"ts", "label", "variant", "flags", "workflow", "status", "params", "wall_s", "outputs", "host_ram_peak_mb", "host_ram_delta_mb", "host_ram_scope"}
        check("same keys as ltx_bench", ltx_keys <= set(lines[0]))
    n = len(ok) - sum(ok)
    print("%d checks, %d failed" % (len(ok), n))
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
