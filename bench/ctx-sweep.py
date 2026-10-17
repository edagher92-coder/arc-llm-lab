# Context sweep for one llama-server launch line (arc-llm-lab, 2026-10-18).
# Starts llama-server on a spare port at each context size, then measures short-prompt speed,
# speed with the context 80% full, and the process's dedicated/shared VRAM (Windows PDH counters).
# Run it with the production model UNLOADED (qwen mode off) so the card is not shared.
# Edit EXE and the paths in BASE_ARGS for your layout. Usage: python ctx-sweep.py 32768 40960 49152 57344
# Writes results.jsonl and server-<ctx>.log next to this file. Results from the B60: data/ctx-sweep-20261018.jsonl

import json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = r"C:\AI\llama.cpp\vulkan-intelfa\llama-server.exe"
PORT = 10011
CTXS = [int(x) for x in (sys.argv[1:] or ["32768", "40960", "49152", "57344", "65536"])]

BASE_ARGS = [
    "-m", "C:/AI/models/thinkingcap/ThinkingCap-Qwen3.8-27B-Q4_K_M.gguf",
    "--mmproj", "C:/AI/models/thinkingcap/mmproj-ThinkingCap-Qwen3.8-27B-f16.gguf",
    "-a", "qwen3.8-27b", "--host", "127.0.0.1", "--port", str(PORT),
    "-ctk", "f16", "-ctv", "f16", "-t", "14", "-tb", "14", "-cram", "2048", "--prio", "0",
    "-ngl", "99", "-fa", "on", "-lm", "dio", "--jinja", "-np", "1", "--cache-reuse", "256", "--metrics",
    "--reasoning-budget", "16384", "--reasoning-budget-message", "Thinking budget reached. Give the final answer now.",
    "--no-mmproj-offload", "-fit", "off", "--chat-template-file", "C:/AI/governor/qwen38-template.jinja",
    "--no-context-shift",
    "-ngld", "99", "-md", "C:/AI/models/qwen3.8-27b/Qwen3.8-27B-DFlash2-Q4_K_M.gguf",
    "--spec-type", "draft-dflash", "--spec-draft-n-max", "7", "-ub", "256",
    "-ctkd", "q8_0", "-ctvd", "q8_0", "--spec-draft-p-min", "0.4",
]

SHORT = "Write a Python class implementing an LRU cache with get and put, type hints and a docstring. Code only."
URL = f"http://127.0.0.1:{PORT}"


def post(path, body, timeout=900):
    r = urllib.request.urlopen(urllib.request.Request(URL + path, data=json.dumps(body).encode(),
                                                      headers={"Content-Type": "application/json"}), timeout=timeout)
    return json.loads(r.read())


def health():
    try:
        return json.loads(urllib.request.urlopen(URL + "/health", timeout=3).read()).get("status") == "ok"
    except Exception:
        return False


def vram(pid):
    ps = ("$s=(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage','\\GPU Process Memory(*)\\Shared Usage').CounterSamples | "
          f"? {{ $_.InstanceName -like 'pid_{pid}_*' }}; $d=($s | ? Path -like '*dedicated*' | measure CookedValue -Sum).Sum; "
          "$h=($s | ? Path -like '*shared*' | measure CookedValue -Sum).Sum; "
          "$a=(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage').CounterSamples | measure CookedValue -Sum; "
          "'{0} {1} {2}' -f $d,$h,$a.Sum")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         creationflags=0x08000000).stdout.split()
    d, h, a = (float(x) / 2**30 for x in out[:3])
    return {"dedicated": round(d, 2), "shared": round(h, 2), "others": round(a - d, 2)}


def chat(content, max_tokens):
    body = {"messages": [{"role": "user", "content": content}], "max_tokens": max_tokens, "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.time(); d = post("/v1/chat/completions", body); dt = time.time() - t0
    tm = d.get("timings", {})
    return {"wall_s": round(dt, 1), "prompt_n": tm.get("prompt_n"), "prompt_tps": round(tm.get("prompt_per_second", 0), 1),
            "gen_n": tm.get("predicted_n"), "gen_tps": round(tm.get("predicted_per_second", 0), 1),
            "draft": tm.get("draft_n"), "acc": tm.get("draft_n_accepted")}


def filler(target_tokens):
    # varied, code-like text so the drafter behaves like a real agent context
    blocks, i = [], 0
    while True:
        i += 1
        blocks.append(f"def handler_{i}(order_id: int, qty: int, region: str = 'nsw') -> dict:\n"
                      f"    \"\"\"Process order {i}: validate quantity, apply region surcharge {i % 7}%, log the result.\"\"\"\n"
                      f"    if qty <= 0:\n        raise ValueError('qty must be positive for order %d' % order_id)\n"
                      f"    total = qty * {10 + i % 13}.{i % 100:02d} * (1 + {i % 7} / 100)\n"
                      f"    return {{'id': order_id, 'qty': qty, 'region': region, 'total': round(total, 2), 'step': {i}}}\n\n")
        if i % 200 == 0:
            text = "".join(blocks)
            n = len(post("/tokenize", {"content": text})["tokens"])
            if n >= target_tokens:
                keep = int(len(blocks) * target_tokens / n)
                return "".join(blocks[:keep])


def main():
    env = dict(os.environ, GGML_VK_FORCE_MMVQ="1")
    out = open(os.path.join(HERE, "results.jsonl"), "a", encoding="utf-8")
    for ctx in CTXS:
        log = open(os.path.join(HERE, f"server-{ctx}.log"), "w", encoding="utf-8", errors="replace")
        p = subprocess.Popen([EXE] + BASE_ARGS + ["-c", str(ctx)], stdout=log, stderr=subprocess.STDOUT, env=env,
                             creationflags=0x08000000)  # CREATE_NO_WINDOW
        rec = {"ctx": ctx, "t": time.strftime("%H:%M:%S")}
        try:
            t0 = time.time()
            while not health():
                if p.poll() is not None:
                    raise RuntimeError(f"server exited rc={p.returncode}")
                if time.time() - t0 > 240:
                    raise RuntimeError("load timeout")
                time.sleep(2)
            rec["load_s"] = round(time.time() - t0, 1)
            chat("hi", 4)  # warm
            rec["vram_after_load"] = vram(p.pid)
            rec["short"] = [chat(SHORT + " " * k, 300) for k in range(3)]
            text = filler(int(ctx * 0.80))
            rec["deep"] = chat(text + "\n\nNow write one new function handler_final that sums the 'total' of a list of the dicts above, with type hints, a docstring and two doctests. Code only.", 300)
            rec["vram_after_deep"] = vram(p.pid)
        except Exception as e:
            rec["error"] = repr(e)
        finally:
            p.kill(); p.wait(); log.close()
            time.sleep(6)
        print(json.dumps(rec), flush=True); out.write(json.dumps(rec) + "\n"); out.flush()
    out.close()


if __name__ == "__main__":
    main()
