"""Explicit, loopback-only generation measurements; never executes model output."""
import argparse
import datetime
import json
import math
import pathlib
import re
import time
import urllib.request
import os
BASE = os.environ.get('QWEN_BASE', 'http://127.0.0.1:10001')


PROMPT = """Write a complete Python 3.11 standard-library-only module implementing
a strict parse_duration(text) function and a unittest test suite with at least
40 individually named test methods. Return only Python source, no markdown.
Accept positive durations composed of integer or decimal amounts followed by
d, h, m, s, or ms, separated by optional spaces. Return integer milliseconds.
Reject non-string inputs, empty input, negative values, repeated units, junk,
missing units, non-finite amounts, and amounts requiring sub-millisecond rounding.
Do not use eval, network, filesystem, subprocesses or third-party packages.
Include varied success cases and boundary/error cases, verifying exceptions and
exact values. Each test should be readable and independent. Add a small final
unittest.main guard. Fully implement both the parser and the tests, not a sketch.
"""


def request(path, body=None):
    raw = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=raw,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=480) as response:
        return json.load(response)


def metric_snapshot():
    """Read native counters only; do not request generation or change state."""
    wanted = {
        "prompt_tokens_total", "tokens_predicted_total",
        "tokens_predicted_seconds_total", "n_decode_total",
        "spec_decode_num_draft_tokens_total",
        "spec_decode_num_accepted_tokens_total", "spec_decode_num_drafts_total",
    }
    with urllib.request.urlopen(BASE + "/metrics", timeout=5) as response:
        source = response.read().decode("utf-8")
    snapshot = {}
    for line in source.splitlines():
        match = re.fullmatch(r"llamacpp:([a-z_]+) ([0-9.eE+\-]+)", line)
        if match and match[1] in wanted:
            value = float(match[2])
            if math.isfinite(value) and value >= 0:
                snapshot[match[1]] = value
    return snapshot


def stream_request(body):
    """Measure first useful content without changing the model workload."""
    body = dict(body, stream=True, stream_options={"include_usage": True})
    started = time.monotonic()
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    first_content_s = None
    finish_reason = None
    usage, timings = {}, {}
    done = False
    with urllib.request.urlopen(req, timeout=480) as response:
        headers_s = time.monotonic() - started
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                done = True
                break
            chunk = json.loads(payload)
            if not isinstance(chunk, dict) or "error" in chunk:
                raise ValueError("stream returned an invalid/error chunk")
            choices = chunk.get("choices", [])
            if not isinstance(choices, list):
                raise ValueError("stream choices must be a list")
            for choice in choices:
                if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                    raise ValueError("unexpected stream choice")
                delta = choice.get("delta", {})
                if not isinstance(delta, dict):
                    raise ValueError("stream delta must be an object")
                content = delta.get("content")
                if content is not None and not isinstance(content, str):
                    raise ValueError("stream content must be text")
                if content and content.strip() and first_content_s is None:
                    first_content_s = time.monotonic() - started
                if choice.get("finish_reason") is not None:
                    finish_reason = choice["finish_reason"]
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            if isinstance(chunk.get("timings"), dict):
                timings = chunk["timings"]
    if not done or first_content_s is None or not finish_reason or not timings:
        raise ValueError("stream ended without complete content/finish/timing evidence")
    result = {"choices": [{"finish_reason": finish_reason}], "usage": usage, "timings": timings}
    return result, {"headers_s": headers_s, "first_content_s": first_content_s}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--runs", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--expected-context", type=int, default=32768,
                        help="Verify the explicitly selected existing runtime context; does not change it")
    args = parser.parse_args()
    target = pathlib.Path(args.output)
    if target.exists() or not target.parent.is_dir():
        parser.error("output must be a fresh file in an existing directory")
    slots = request("/slots")
    if not slots or any(slot.get("is_processing") is not False for slot in slots):
        parser.error("all native slots must be known idle")
    if any(slot.get("n_ctx") != args.expected_context for slot in slots):
        parser.error("native context differs from the explicitly selected existing runtime context")
    # Reserve the evidence path before generating; retain partial evidence on failure.
    with target.open("x", encoding="utf-8") as log:
        for index in range(args.runs):
            before = metric_snapshot()
            started = time.monotonic()
            body = {
                "model": os.environ.get("QWEN_MODEL", "qwen3.8-27b"),
                "messages": [{"role": "user", "content": PROMPT}],
                "max_tokens": 2304,
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 20,
                "seed": 4242 + index,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            latency = {}
            if args.stream:
                result, latency = stream_request(body)
            else:
                result = request("/v1/chat/completions", body)
            wall_s = time.monotonic() - started
            after = metric_snapshot()
            timings = result.get("timings", {})
            choice = result["choices"][0]
            n = timings.get("predicted_n")
            gen_ms = timings.get("predicted_ms")
            tps = timings.get("predicted_per_second")
            long_enough = (isinstance(n, (int, float)) and n >= 1536
                           and isinstance(gen_ms, (int, float)) and gen_ms >= 30000)
            row = {
                "label": args.label, "run": index + 1,
                "context": args.expected_context,
                "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "wall_s": round(wall_s, 3), "timings": timings,
                "streaming": args.stream, "latency": latency,
                "usage": result.get("usage", {}),
                "finish_reason": choice.get("finish_reason"),
                "long_enough": long_enough,
                "speed_floor_met": long_enough and isinstance(tps, (int, float)) and tps >= 40,
                "output_executed": False,
                "quality_acceptance": "not evaluated; capped outputs are not completed code",
                "native_counter_deltas": {
                    key: after[key] - before[key]
                    for key in before.keys() & after.keys()
                },
            }
            line = json.dumps(row, sort_keys=True)
            log.write(line + "\n")
            log.flush()
            print(line, flush=True)


if __name__ == "__main__":
    main()

