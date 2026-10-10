import json, re, subprocess, sys, tempfile, time, urllib.request, os, html.parser
PORT = sys.argv[1]; LABEL = sys.argv[2]
BASE = f"http://127.0.0.1:{PORT}"
def post(path, body, hdr=None):
    h = {"Content-Type": "application/json"}; h.update(hdr or {})
    t = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=h), timeout=900))
    return r, time.time() - t
def chat(prompt, max_tokens=1600):
    r, dt = post("/v1/chat/completions", {"model": "m", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
                 "temperature": 0.2, "top_p": 0.95, "top_k": 20, "chat_template_kwargs": {"enable_thinking": False}})
    tm = r.get("timings", {})
    return r["choices"][0]["message"]["content"], tm.get("predicted_n", 0), tm.get("predicted_per_second", 0), dt
def code_block(txt, lang):
    m = re.findall(r"```(?:%s)?\s*\n(.*?)```" % lang, txt, re.S)
    return max(m, key=len) if m else txt
PY = [
 ("merge_intervals", "Write a Python function merge_intervals(intervals) that takes a list of [start, end) half-open integer intervals (start < end), merges overlapping AND touching intervals, and returns a new sorted list of [start, end] lists. Raise ValueError for invalid intervals (non-int, start >= end). Do not mutate the input. Return only the code.",
  "a=[[5,7],[1,3],[3,4],[10,12],[11,15]]\nb=[x[:] for x in a]\nassert merge_intervals(a)==[[1,4],[5,7],[10,15]]\nassert a==b\nassert merge_intervals([])==[]\nfor bad in ([[3,3]],[[2,1]],[[1.5,2]]):\n  try:\n    merge_intervals(bad); raise SystemExit('no raise')\n  except ValueError: pass\n"),
 ("lru", "Write a Python class LRUCache(capacity) with get(key) returning -1 if missing and put(key, value), both O(1), evicting the least recently used key when over capacity. Return only the code.",
  "c=LRUCache(2)\nc.put(1,1);c.put(2,2)\nassert c.get(1)==1\nc.put(3,3)\nassert c.get(2)==-1\nc.put(4,4)\nassert c.get(1)==-1 and c.get(3)==3 and c.get(4)==4\nc.put(3,30)\nassert c.get(3)==30\n"),
 ("csv", "Write a Python function parse_csv_line(line) that parses ONE CSV line per RFC 4180 without using the csv module: fields separated by commas, fields may be wrapped in double quotes, quoted fields may contain commas, and a doubled quote \"\" inside quotes is a literal quote. Return a list of strings. Return only the code.",
  "assert parse_csv_line('a,b,c')==['a','b','c']\nassert parse_csv_line('\"a,b\",c')==['a,b','c']\nassert parse_csv_line('\"he said \"\"hi\"\"\",x')==['he said \"hi\"','x']\nassert parse_csv_line('a,,c')==['a','','c']\nassert parse_csv_line('')==['']\n"),
 ("flatten", "Write a Python function flatten_json(obj) that flattens nested dicts and lists into a single dict with dotted keys; list elements use their index, e.g. {'a':{'b':[1,{'c':2}]}} -> {'a.b.0':1,'a.b.1.c':2}. Empty dicts/lists become a key with the empty value. Return only the code.",
  "assert flatten_json({'a':{'b':[1,{'c':2}]}})=={'a.b.0':1,'a.b.1.c':2}\nassert flatten_json({'x':1})=={'x':1}\nassert flatten_json({'e':{},'l':[]})=={'e':{},'l':[]}\n"),
 ("topk", "Write a Python function top_k_frequent(words, k) returning the k most frequent words sorted by frequency descending, ties broken alphabetically ascending. Return only the code.",
  "assert top_k_frequent(['i','love','leetcode','i','love','coding'],2)==['i','love']\nassert top_k_frequent(['the','day','is','sunny','the','the','the','sunny','is','is'],4)==['the','is','sunny','day']\n"),
 ("roman", "Write Python functions int_to_roman(n) for 1..3999 and roman_to_int(s) for valid numerals. Return only the code.",
  "assert int_to_roman(1994)=='MCMXCIV' and int_to_roman(3999)=='MMMCMXCIX' and int_to_roman(4)=='IV'\nassert all(roman_to_int(int_to_roman(i))==i for i in range(1,4000))\n"),
]
JS = [("slugify_debounce", "Write a JavaScript (Node, CommonJS) module that exports slugify(str) (lowercase, strip accents via normalize('NFD'), replace non-alphanumerics with single hyphens, trim hyphens) and debounce(fn, ms) (trailing-edge). Use module.exports = { slugify, debounce }. Return only the code.",
  "const {slugify,debounce}=require(process.argv[2]);const assert=require('assert');\nassert.strictEqual(slugify('  Héllo, Wörld!! Frozen  Hire '),'hello-world-frozen-hire');\nassert.strictEqual(slugify('--a__b--'),'a-b');\nlet n=0;const d=debounce(()=>n++,30);d();d();d();setTimeout(()=>{assert.strictEqual(n,1);console.log('ok')},80);\n")]
res = {"label": LABEL, "coding": [], "tools": [], "web": None}
tok = 0; gen_t = 0.0
for name, prompt, test in PY:
    out, n, tps, dt = chat(prompt); tok += n; gen_t += dt
    src = code_block(out, "python") + "\n\n" + test
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f: f.write(src)
    try: p = subprocess.run([sys.executable, "-I", f.name], capture_output=True, text=True, timeout=20); ok = p.returncode == 0; err = p.stderr[-200:]
    except subprocess.TimeoutExpired: ok, err = False, "timeout"
    res["coding"].append({"task": name, "pass": ok, "tps": round(tps, 1), "err": "" if ok else err})
for name, prompt, test in JS:
    out, n, tps, dt = chat(prompt); tok += n; gen_t += dt
    d = tempfile.mkdtemp(); mod = os.path.join(d, "m.js"); tst = os.path.join(d, "t.js")
    open(mod, "w", encoding="utf-8").write(code_block(out, "(?:javascript|js)")); open(tst, "w", encoding="utf-8").write(test)
    try: p = subprocess.run(["node", tst, mod], capture_output=True, text=True, timeout=20); ok = p.returncode == 0 and "ok" in p.stdout; err = p.stderr[-200:]
    except subprocess.TimeoutExpired: ok, err = False, "timeout"
    res["coding"].append({"task": name, "pass": ok, "tps": round(tps, 1), "err": "" if ok else err})
# tool calling (OpenAI chat format)
tools = [{"type": "function", "function": {"name": "get_weather", "description": "Current weather for a city", "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "units": {"type": "string", "enum": ["c", "f"]}}, "required": ["city"]}}},
         {"type": "function", "function": {"name": "write_file", "description": "Write text to a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
         {"type": "function", "function": {"name": "web_search", "description": "Search the web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}}}]
TC = [("weather in Celsius for Riverside NSW", "get_weather", lambda a: "riverside" in a.get("city", "").lower() and a.get("units") == "c"),
      ("Save the text 'hello' into notes/todo.txt", "write_file", lambda a: a.get("path", "").endswith("todo.txt") and "hello" in a.get("content", "")),
      ("Find the latest Intel Arc Pro B60 driver version; get at most 3 results.", "web_search", lambda a: "b60" in a.get("query", "").lower() and a.get("max_results") == 3)]
for q, want, chk in TC:
    r, dt = post("/v1/chat/completions", {"model": "m", "messages": [{"role": "user", "content": q}], "tools": tools, "max_tokens": 600, "temperature": 0.2,
                                          "chat_template_kwargs": {"enable_thinking": False}})
    calls = r["choices"][0]["message"].get("tool_calls") or []
    ok = False
    if calls:
        c = calls[0]["function"]
        try: ok = c["name"] == want and chk(json.loads(c["arguments"]))
        except Exception: ok = False
    res["tools"].append({"want": want, "pass": ok, "got": [c["function"]["name"] for c in calls]})
# web build
out, n, tps, dt = chat("Build a complete single-file responsive HTML5 landing page (inline CSS + a little vanilla JS) for 'FrostLine Hire - party ice-machine hire'. Include: sticky nav with 4 anchor links, hero with CTA button, 3 service cards, an FAQ accordion using <details>, a contact form with name/email/phone/message and client-side validation, and a footer. Use [CONFIRM: price] placeholders instead of prices. Return only the HTML.", 6000)
tok += n; gen_t += dt
h = code_block(out, "html")
class P(html.parser.HTMLParser):
    def __init__(s): super().__init__(); s.tags = {}; s.stack = []; s.bad = 0
    def handle_starttag(s, t, a): s.tags[t] = s.tags.get(t, 0) + 1
P_ = P(); P_.feed(h)
need = {"nav": 1, "form": 1, "details": 3, "footer": 1, "button": 1, "input": 3, "script": 1, "style": 1}
miss = [k for k, v in need.items() if P_.tags.get(k, 0) < v]
res["web"] = {"pass": not miss and "</html>" in h.lower() and "[CONFIRM" in h, "missing": miss, "tokens": n, "tps": round(tps, 1)}
res["coding_pass"] = sum(c["pass"] for c in res["coding"]); res["coding_total"] = len(res["coding"])
res["tools_pass"] = sum(t["pass"] for t in res["tools"]); res["tools_total"] = len(res["tools"])
res["avg_gen_tps_wall"] = round(tok / gen_t, 1) if gen_t else 0
# Full JSON copy goes next to this script (override with EVAL_OUT_DIR). stdout's last line stays the JSON summary for regression.ps1.
out_dir = os.environ.get("EVAL_OUT_DIR") or os.path.dirname(os.path.abspath(__file__))
try:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"eval-{LABEL}.json"), "w", encoding="utf-8") as fh: fh.write(json.dumps(res, indent=1))
except OSError as e:
    print(f"warning: could not write eval-{LABEL}.json to {out_dir}: {e}", file=sys.stderr)
print(json.dumps(res))
