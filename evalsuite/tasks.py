"""arc-llm-lab evaluation suite: 100 reproducible agent tasks with hidden automatic checkers.
Each task: id, cat, prompt, files ({relpath: str|bytes} or callable(ws)), check(ws) -> (ok: bool, reason: str).
Categories: coding 20, debugging 20, tool 15, fileops 15, longctx 10, business 10, recovery 10.
Checkers run only AFTER the agent finishes; hidden tests are never visible to the agent."""
import json, os, re, subprocess, sys, random, hashlib, csv, io, zipfile, shutil
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta

PY = sys.executable
TASKS = []
SUITE_VERSION = "1.2"  # bump whenever a checker, prompt or generator changes; results/*.jsonl carry it

def T(id, cat, prompt, files, check, timeout=420):
    TASKS.append(dict(id=id, cat=cat, prompt=prompt, files=files, check=check, timeout=timeout))

def materialize(task, ws):
    os.makedirs(ws, exist_ok=True)
    f = task["files"]
    if callable(f):
        f(ws)
        return
    for rel, content in f.items():
        p = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(p) or ws, exist_ok=True)
        if isinstance(content, bytes):
            open(p, "wb").write(content)
        else:
            open(p, "w", encoding="utf-8", newline="").write(content)

def rd(ws, p):
    """Text of ws/p with BOM stripped and newlines normalised; None only if the file is missing/unreadable.
    Accepts UTF-8 (+/- BOM), UTF-16 (Windows PowerShell 5.1 '>' / Out-File default) and falls back to cp1252."""
    try:
        b = open(os.path.join(ws, p), "rb").read()
    except Exception:
        return None
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        s = b.decode("utf-16", errors="replace")
    else:
        try: s = b.decode("utf-8-sig")
        except UnicodeDecodeError: s = b.decode("cp1252", errors="replace")
    return s.replace("\r\n", "\n").replace("\r", "\n")

def rdb(ws, p):
    try:
        return open(os.path.join(ws, p), "rb").read()
    except Exception:
        return None

def ans(ws):
    a = rd(ws, "answer.txt")
    return (a or "").strip()

def norm(s):
    return (s or "").strip().strip("`'\" .").strip().lower()

def answer_is(expected):
    def chk(ws):
        a = ans(ws)
        ok = norm(a) == norm(str(expected))
        return ok, "" if ok else f"answer.txt={a[:80]!r} expected={expected!r}"
    return chk

def num(s):
    try:
        return Decimal(str(s).strip().strip("`'\" ").replace("$", "").replace(",", ""))
    except Exception:
        return None

def answer_num(expected):
    def chk(ws):
        a = ans(ws)
        ok = num(a) is not None and num(a) == Decimal(str(expected))
        return ok, "" if ok else f"answer.txt={a[:80]!r} expected={expected}"
    return chk

def all_of(*checks):
    def chk(ws):
        for c in checks:
            ok, why = c(ws)
            if not ok:
                return False, why
        return True, ""
    return chk

def unchanged(rel, content):
    def chk(ws):
        ok = rd(ws, rel) == content
        return ok, "" if ok else f"{rel} was modified but must not be"
    return chk

def purge_pycache(ws):
    """Stale bytecode can mask same-size edits made within one second; always check fresh source."""
    for root, dirs, _ in os.walk(ws):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True); dirs.remove(d)

def run_py(ws, args, timeout=60, env=None):
    purge_pycache(ws)
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1"); e.update(env or {})
    return subprocess.run([PY] + args, cwd=ws, capture_output=True, text=True, timeout=timeout, env=e)

def run_hidden(ws, test_src, name="_hidden_test.py"):
    """Write a hidden test file after the agent has finished and run it with pytest."""
    purge_pycache(ws)
    path = os.path.join(ws, name)
    open(path, "w", encoding="utf-8").write(test_src)
    try:
        p = subprocess.run([PY, "-B", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", name], cwd=ws, capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        ok = p.returncode == 0
        return ok, "" if ok else (p.stdout[-400:] + p.stderr[-200:]).strip()
    except subprocess.TimeoutExpired:
        return False, "hidden tests timed out"
    finally:
        try: os.remove(path)
        except Exception: pass

def hidden(test_src):
    return lambda ws: run_hidden(ws, test_src)

def cents(x):
    return Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)

def read_csv(ws, rel):
    t = rd(ws, rel)
    if t is None:
        return None
    return list(csv.reader(io.StringIO(t.lstrip("﻿"))))

SUFFIX = " Work only inside the current folder. Verify your work by running it before you finish."
ANS = " Write only the answer (no extra words) to answer.txt in the current folder."

# ---------------- A. CODING (20): implement in solution.py, hidden pytest ----------------
CODING = [
 ("merge_intervals", "merge_intervals(intervals): list of [start, end) integer pairs (start < end); merge overlapping AND touching intervals; return a new sorted list of [start, end] lists; raise ValueError for invalid intervals (non-int or start >= end); do not mutate the input.",
  "from solution import merge_intervals\nimport pytest\ndef test_a():\n  a=[[5,7],[1,3],[3,4],[10,12],[11,15]]; b=[x[:] for x in a]\n  assert merge_intervals(a)==[[1,4],[5,7],[10,15]] and a==b\n  assert merge_intervals([])==[]\ndef test_bad():\n  for bad in ([[3,3]],[[2,1]],[[1.5,2]]):\n    with pytest.raises(ValueError): merge_intervals(bad)\n"),
 ("lru", "class LRUCache(capacity) with get(key) -> value or -1 and put(key, value), both O(1), evicting the least recently used key when over capacity.",
  "from solution import LRUCache\ndef test_lru():\n  c=LRUCache(2); c.put(1,1); c.put(2,2); assert c.get(1)==1\n  c.put(3,3); assert c.get(2)==-1\n  c.put(4,4); assert c.get(1)==-1 and c.get(3)==3 and c.get(4)==4\n  c.put(3,30); assert c.get(3)==30\n"),
 ("abn", "is_valid_abn(abn: str) -> bool: Australian Business Number check. Ignore spaces; must be 11 digits; subtract 1 from the first digit; weights 10,1,3,5,7,9,11,13,15,17,19; valid if weighted sum % 89 == 0.",
  "from solution import is_valid_abn\ndef test_abn():\n  assert is_valid_abn('51 824 753 556') and is_valid_abn('53004085616')\n  assert not is_valid_abn('51 824 753 557') and not is_valid_abn('123') and not is_valid_abn('5182475355a')\n"),
 ("gst", "gst_breakdown(total_inc_gst) taking a Decimal amount that INCLUDES 10% Australian GST; return a tuple (ex_gst, gst) of Decimals rounded to cents with ROUND_HALF_UP where gst = total/11 rounded and ex_gst = total - gst.",
  "from decimal import Decimal as D\nfrom solution import gst_breakdown\ndef test_gst():\n  assert gst_breakdown(D('110.00'))==(D('100.00'),D('10.00'))\n  assert gst_breakdown(D('99.99'))==(D('90.90'),D('9.09'))\n  assert gst_breakdown(D('0'))==(D('0.00'),D('0.00'))\n"),
 ("bizdays", "business_days(start, end, holidays=()) counting weekdays (Mon-Fri) from start to end inclusive, excluding any dates in holidays; start/end are datetime.date; return 0 if end < start.",
  "import datetime as d\nfrom solution import business_days\ndef test_bd():\n  D=d.date\n  assert business_days(D(2026,10,5),D(2026,10,11))==5\n  assert business_days(D(2026,10,5),D(2026,10,5))==1\n  assert business_days(D(2026,10,10),D(2026,10,11))==0\n  assert business_days(D(2026,10,5),D(2026,10,9),[D(2026,10,6)])==4\n  assert business_days(D(2026,10,9),D(2026,10,5))==0\n"),
 ("duration", "parse_duration(s) -> int seconds for strings like '1h30m', '45s', '2h', '1h2m3s', '90m'; whitespace allowed between parts; raise ValueError on empty or invalid input like '1x' or 'h'.",
  "import pytest\nfrom solution import parse_duration\ndef test_d():\n  assert parse_duration('1h30m')==5400 and parse_duration('45s')==45 and parse_duration('1h 2m 3s')==3723 and parse_duration('90m')==5400\n  for b in ('','1x','h','1h30'):\n    with pytest.raises(ValueError): parse_duration(b)\n"),
 ("rle", "rle_encode(s) and rle_decode(s): run-length encoding where 'aaabcc' -> '3a1b2c'; decode reverses it (counts may be multi-digit).",
  "from solution import rle_encode, rle_decode\ndef test_rle():\n  assert rle_encode('aaabcc')=='3a1b2c' and rle_encode('')==''\n  s='x'*12+'yz'; assert rle_decode(rle_encode(s))==s and rle_decode('12x1y')=='x'*12+'y'\n"),
 ("semver", "compare_semver(a, b) returning -1, 0 or 1 for versions like '1.2.10' vs '1.2.9'; missing parts count as 0 ('1.2' == '1.2.0'); a pre-release suffix like '1.0.0-beta' is lower than '1.0.0'.",
  "from solution import compare_semver as c\ndef test_s():\n  assert c('1.2.10','1.2.9')==1 and c('1.2','1.2.0')==0 and c('1.0.0-beta','1.0.0')==-1 and c('2.0.0','10.0.0')==-1\n"),
 ("jsonpath", "get_path(obj, path, default=None) reading nested dict/list values using paths like 'a.b[0].c' or 'items[2]'; return default if any part is missing or index is out of range.",
  "from solution import get_path\ndef test_g():\n  o={'a':{'b':[{'c':5}]},'items':[1,2,3]}\n  assert get_path(o,'a.b[0].c')==5 and get_path(o,'items[2]')==3 and get_path(o,'items[9]','x')=='x' and get_path(o,'a.z.q') is None\n"),
 ("wrap", "wrap_text(text, width) -> list of lines, greedy word wrap, no line longer than width unless a single word is longer than width (then it sits alone on its line); collapse runs of whitespace.",
  "from solution import wrap_text\ndef test_w():\n  assert wrap_text('the quick brown fox jumps', 10)==['the quick','brown fox','jumps']\n  assert wrap_text('a  verylongwordhere b', 5)==['a','verylongwordhere','b']\n  assert wrap_text('', 5)==[]\n"),
 ("spiral", "spiral(matrix) returning the elements of a rectangular list-of-lists in clockwise spiral order starting top-left; empty matrix -> [].",
  "from solution import spiral\ndef test_s():\n  assert spiral([[1,2,3],[4,5,6],[7,8,9]])==[1,2,3,6,9,8,7,4,5]\n  assert spiral([[1,2,3,4],[5,6,7,8]])==[1,2,3,4,8,7,6,5] and spiral([])==[]\n"),
 ("dedupe", "dedupe(items, key=None) returning a new list with duplicates removed preserving first-seen order; optional key function decides identity; must work for unhashable items like dicts when a key is given.",
  "from solution import dedupe\ndef test_d():\n  assert dedupe([3,1,3,2,1])==[3,1,2]\n  r=dedupe([{'id':1},{'id':2},{'id':1,'x':9}],key=lambda d:d['id']); assert r==[{'id':1},{'id':2}]\n"),
 ("email", "is_valid_email(s): simple validation - exactly one '@', non-empty local part without spaces, domain has at least one dot, labels of letters/digits/hyphens not starting or ending with a hyphen, TLD of 2+ letters.",
  "from solution import is_valid_email as v\ndef test_e():\n  assert v('jon@frostline.com.au') and v('a.b+c@x-y.io')\n  for b in ('a@b','a@@b.com','a b@c.com','@c.com','a@-c.com','a@c.c'): assert not v(b)\n"),
 ("topk", "top_k_frequent(words, k) returning the k most frequent words sorted by frequency descending, ties broken alphabetically ascending.",
  "from solution import top_k_frequent as t\ndef test_t():\n  assert t(['i','love','leetcode','i','love','coding'],2)==['i','love']\n  assert t(['the','day','is','sunny','the','the','the','sunny','is','is'],4)==['the','is','sunny','day']\n"),
 ("roman", "int_to_roman(n) for 1..3999 and roman_to_int(s) for valid numerals.",
  "from solution import int_to_roman as a, roman_to_int as b\ndef test_r():\n  assert a(1994)=='MCMXCIV' and a(3999)=='MMMCMXCIX' and all(b(a(i))==i for i in range(1,4000))\n"),
 ("money", "split_amount(total, n) splitting a Decimal dollar amount into n Decimal parts (cents) that sum exactly to total, as equal as possible, larger parts first; raise ValueError if n < 1.",
  "from decimal import Decimal as D\nimport pytest\nfrom solution import split_amount\ndef test_m():\n  assert split_amount(D('100.00'),3)==[D('33.34'),D('33.33'),D('33.33')]\n  assert split_amount(D('0.05'),2)==[D('0.03'),D('0.02')] and sum(split_amount(D('10.01'),7))==D('10.01')\n  with pytest.raises(ValueError): split_amount(D('1'),0)\n"),
 ("csvparse", "parse_csv_line(line) parsing one RFC-4180 CSV line without the csv module: commas separate fields, fields may be double-quoted, quoted fields may contain commas, and \"\" inside quotes is a literal quote; return a list of strings.",
  "from solution import parse_csv_line as p\ndef test_c():\n  assert p('a,b,c')==['a','b','c'] and p('\"a,b\",c')==['a,b','c'] and p('\"he said \"\"hi\"\"\",x')==['he said \"hi\"','x'] and p('a,,c')==['a','','c'] and p('')==['']\n"),
 ("flatten", "flatten_json(obj) flattening nested dicts and lists into one dict with dotted keys, list items by index: {'a':{'b':[1,{'c':2}]}} -> {'a.b.0':1,'a.b.1.c':2}; empty dicts/lists become a key with the empty value.",
  "from solution import flatten_json as f\ndef test_f():\n  assert f({'a':{'b':[1,{'c':2}]}})=={'a.b.0':1,'a.b.1.c':2} and f({'e':{},'l':[]})=={'e':{},'l':[]}\n"),
 ("tokenbucket", "class TokenBucket(capacity, refill_per_sec, clock=time.monotonic) with allow(cost=1) -> bool; starts full; refills continuously up to capacity based on clock(); the clock argument must be used so tests can inject a fake clock.",
  "from solution import TokenBucket\ndef test_tb():\n  t=[0.0]; b=TokenBucket(2,1.0,clock=lambda:t[0])\n  assert b.allow() and b.allow() and not b.allow()\n  t[0]=1.0; assert b.allow() and not b.allow()\n  t[0]=10; assert b.allow(2) and not b.allow()\n"),
 ("postcode", "nsw_region(postcode) returning 'Sydney Metro' for NSW postcodes 2000-2234, 'Regional NSW' for 2235-2999 (and 2620-2899 excluding ACT range 2600-2618), 'ACT' for 2600-2618 and 2900-2920, else 'Other'. Accept int or str with whitespace; invalid -> 'Other'. ACT ranges take priority.",
  "from solution import nsw_region as r\ndef test_p():\n  assert r(2212)=='Sydney Metro' and r(' 2000 ')=='Sydney Metro' and r(2600)=='ACT' and r(2905)=='ACT' and r(2650)=='Regional NSW' and r(3000)=='Other' and r('abc')=='Other'\n  assert r(2234)=='Sydney Metro' and r(2235)=='Regional NSW' and r(2300)=='Regional NSW' and r(2599)=='Regional NSW' and r(2618)=='ACT' and r(2900)=='ACT'\n"),
]
for name, spec, test in CODING:
    T("code-" + name, "coding", "Create solution.py implementing: " + spec + SUFFIX, {}, hidden(test))

# ---------------- B. DEBUGGING (20): fix the bug, visible failing test + hidden extra tests ----------------
DEBUG = [
 ("pager", "def paginate(items, page, size):\n    \"\"\"Return the items on 1-indexed page `page` of size `size`.\"\"\"\n    start = page * size\n    return items[start:start + size]\n",
  "from pager import paginate\ndef test_first():\n    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]\ndef test_last():\n    assert paginate(list(range(10)), 4, 3) == [9]\n",
  "def test_more():\n    assert paginate(list(range(10)), 2, 3) == [3, 4, 5] and paginate(list(range(10)), 5, 3) == []\n"),
 ("tags", "def add_tag(tag, tags=[]):\n    \"\"\"Append tag to tags (a new list if none given) and return the list.\"\"\"\n    tags.append(tag)\n    return tags\n",
  "from tags import add_tag\ndef test_fresh():\n    assert add_tag('a') == ['a']\n    assert add_tag('b') == ['b']\n",
  "def test_given():\n    t = ['x']; r = add_tag('y', t); assert r == ['x', 'y']\n    assert add_tag('z') == ['z']\n"),
 ("stats", "def average(nums):\n    \"\"\"Arithmetic mean; 0 for an empty list.\"\"\"\n    if not nums:\n        return 0\n    return sum(nums) // len(nums)\n",
  "from stats import average\ndef test_avg():\n    assert average([1, 2]) == 1.5\n",
  "def test_more():\n    assert average([]) == 0 and average([2, 4]) == 3 and abs(average([0.1, 0.2]) - 0.15) < 1e-9\n"),
 ("audate", "from datetime import datetime\n\ndef parse_au_date(s):\n    \"\"\"Parse an Australian dd/mm/yyyy date string into a datetime.date.\"\"\"\n    return datetime.strptime(s.strip(), \"%m/%d/%Y\").date()\n",
  "from datetime import date\nfrom audate import parse_au_date\ndef test_au():\n    assert parse_au_date('03/04/2026') == date(2026, 4, 3)\n    assert parse_au_date('25/12/2026') == date(2026, 12, 25)\n",
  "def test_more():\n    assert parse_au_date(' 01/02/2027 ') == date(2027, 2, 1)\n"),
 ("versions", "def sort_versions(vs):\n    \"\"\"Sort dotted numeric version strings in ascending version order.\"\"\"\n    return sorted(vs)\n",
  "from versions import sort_versions\ndef test_sort():\n    assert sort_versions(['1.10.0', '1.2.0', '1.9.3']) == ['1.2.0', '1.9.3', '1.10.0']\n",
  "def test_more():\n    assert sort_versions(['10.0', '9.1', '9.0.1']) == ['9.0.1', '9.1', '10.0']\n"),
 ("cleanup", "def remove_zero(d):\n    \"\"\"Remove keys whose value is 0, in place, and return the dict.\"\"\"\n    for k in d:\n        if d[k] == 0:\n            del d[k]\n    return d\n",
  "from cleanup import remove_zero\ndef test_rz():\n    assert remove_zero({'a': 0, 'b': 1, 'c': 0}) == {'b': 1}\n",
  "def test_inplace():\n    d = {'x': 0, 'y': 2}; r = remove_zero(d); assert d == {'y': 2} and r is d\n"),
 ("bsearch", "def find(sorted_list, target):\n    \"\"\"Return the index of target in sorted_list, or -1.\"\"\"\n    lo, hi = 0, len(sorted_list) - 1\n    while lo < hi:\n        mid = (lo + hi) // 2\n        if sorted_list[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return lo if sorted_list and sorted_list[lo] == target else -1\n",
  "from bsearch import find\ndef test_find():\n    assert find([1, 3, 5, 7], 3) == 1\n    assert find([], 1) == -1\n",
  "def test_all():\n    for n in range(1, 30):\n        xs = list(range(0, 2 * n, 2))\n        for i, x in enumerate(xs):\n            assert find(xs, x) == i\n        assert find(xs, 1) == -1 and find(xs, -2) == -1 and find(xs, 2 * n) == -1\n"),
 ("htmlbits", "import re\n\ndef extract_bold(html):\n    \"\"\"Return the text inside every <b>...</b> pair, in order.\"\"\"\n    return re.findall(r\"<b>(.*)</b>\", html)\n",
  "from htmlbits import extract_bold\ndef test_bold():\n    assert extract_bold('<b>x</b> and <b>y</b>') == ['x', 'y']\n",
  "def test_more():\n    assert extract_bold('none') == [] and extract_bold('<b>a b</b>') == ['a b']\n"),
 ("fact", "def factorial(n):\n    if n == 1:\n        return 1\n    return n * factorial(n - 1)\n",
  "from fact import factorial\ndef test_f():\n    assert factorial(0) == 1\n    assert factorial(5) == 120\n",
  "def test_more():\n    assert factorial(1) == 1 and factorial(10) == 3628800\n"),
 ("mults", "def make_multipliers(n):\n    \"\"\"Return n functions; the i-th multiplies its argument by i.\"\"\"\n    return [lambda x: x * i for i in range(n)]\n",
  "from mults import make_multipliers\ndef test_m():\n    assert [f(2) for f in make_multipliers(3)] == [0, 2, 4]\n",
  "def test_more():\n    assert [f(5) for f in make_multipliers(4)] == [0, 5, 10, 15]\n"),
 ("grid", "def clone_grid(grid):\n    \"\"\"Return an independent copy of a 2-D list.\"\"\"\n    return list(grid)\n",
  "from grid import clone_grid\ndef test_clone():\n    g = [[1, 2], [3, 4]]\n    c = clone_grid(g)\n    c[0][0] = 9\n    assert g[0][0] == 1 and c == [[9, 2], [3, 4]]\n",
  "def test_more():\n    g = [[1], [2]]; c = clone_grid(g); c[1].append(5); assert g == [[1], [2]]\n"),
 ("config", "import json\n\ndef load_config(path):\n    \"\"\"Return the parsed JSON config; {} if the file does not exist. Invalid JSON must raise ValueError.\"\"\"\n    try:\n        with open(path, encoding='utf-8') as f:\n            return json.load(f)\n    except Exception:\n        return {}\n",
  "import pytest\nfrom config import load_config\ndef test_missing(tmp_path):\n    assert load_config(str(tmp_path / 'nope.json')) == {}\ndef test_invalid(tmp_path):\n    p = tmp_path / 'bad.json'; p.write_text('{oops', encoding='utf-8')\n    with pytest.raises(ValueError):\n        load_config(str(p))\n",
  "def test_ok(tmp_path):\n    p = tmp_path / 'ok.json'; p.write_text('{\"a\": 1}', encoding='utf-8'); assert load_config(str(p)) == {'a': 1}\n"),
 ("weekend", "def is_weekend(d):\n    \"\"\"True if the datetime.date falls on Saturday or Sunday.\"\"\"\n    return d.weekday() == 5 and d.weekday() == 6\n",
  "from datetime import date\nfrom weekend import is_weekend\ndef test_w():\n    assert is_weekend(date(2026, 10, 10)) and is_weekend(date(2026, 10, 11))\n    assert not is_weekend(date(2026, 10, 9))\n",
  "def test_more():\n    assert [is_weekend(date(2026, 10, d)) for d in range(5, 12)] == [False]*5 + [True, True]\n"),
 ("pricing", "from decimal import Decimal, ROUND_HALF_UP\n\ndef final_price(price, discount_pct):\n    \"\"\"Apply a percentage discount to an ex-GST price, then add 10% GST; round to cents half-up.\"\"\"\n    p = Decimal(str(price))\n    p = p * Decimal('1.1')\n    p = p - p * Decimal(str(discount_pct)) / 100\n    p = p * Decimal('1.1')\n    return p.quantize(Decimal('0.01'), ROUND_HALF_UP)\n",
  "from decimal import Decimal\nfrom pricing import final_price\ndef test_fp():\n    assert final_price('100', 10) == Decimal('99.00')\n",
  "def test_more():\n    assert final_price('19.95', 0) == Decimal('21.95') and final_price('50', 25) == Decimal('41.25')\n"),
 ("words", "def word_count(text):\n    \"\"\"Count words case-insensitively, ignoring the punctuation characters . , ! ? ; :\"\"\"\n    counts = {}\n    for w in text.split():\n        counts[w] = counts.get(w, 0) + 1\n    return counts\n",
  "from words import word_count\ndef test_wc():\n    assert word_count('Ice, ice baby! Ice.') == {'ice': 3, 'baby': 1}\n",
  "def test_more():\n    assert word_count('') == {} and word_count('A: a; B?') == {'a': 2, 'b': 1}\n"),
 ("fibo", "_cache = {}\n\ndef fib(n):\n    if n in _cache:\n        return _cache[n]\n    if n < 2:\n        return n\n    r = fib(n - 1) + fib(n - 2)\n    _cache[n - 1] = r\n    return r\n",
  "from fibo import fib\ndef test_fib():\n    assert [fib(i) for i in range(10)] == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]\n",
  "def test_big():\n    assert fib(80) == 23416728348467685\n"),
 ("csvout", "import csv\n\ndef write_rows(path, rows):\n    \"\"\"Write rows (lists of strings) to a UTF-8 CSV file that opens cleanly in Excel and csv.reader.\"\"\"\n    with open(path, 'w') as f:\n        w = csv.writer(f)\n        for r in rows:\n            w.writerow(r)\n",
  "import csv\nfrom csvout import write_rows\ndef test_csv(tmp_path):\n    p = str(tmp_path / 'o.csv')\n    rows = [['item', 'price'], ['Caf\u00e9 frapp\u00e9', '6.50'], ['Shaved ice \u2603', '5.00']]\n    write_rows(p, rows)\n    raw = open(p, 'rb').read()\n    assert b'\\r\\r\\n' not in raw\n    with open(p, encoding='utf-8', newline='') as f:\n        assert list(csv.reader(f)) == rows\n",
  "def test_empty(tmp_path):\n    p = str(tmp_path / 'e.csv'); write_rows(p, []); assert open(p, 'rb').read() == b''\n"),
 ("chunks", "def chunk(lst, n):\n    \"\"\"Split lst into consecutive chunks of size n; the last chunk may be shorter.\"\"\"\n    return [lst[i:i + n] for i in range(0, len(lst) - n + 1, n)]\n",
  "from chunks import chunk\ndef test_c():\n    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]\n",
  "def test_more():\n    assert chunk([], 3) == [] and chunk([1, 2], 5) == [[1, 2]] and chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]\n"),
 ("prefix", "def strip_prefix(s, prefix):\n    \"\"\"Remove prefix from the start of s if present.\"\"\"\n    return s.lstrip(prefix)\n",
  "from prefix import strip_prefix\ndef test_p():\n    assert strip_prefix('invoice_inv001', 'invoice_') == 'inv001'\n",
  "def test_more():\n    assert strip_prefix('abc', 'x') == 'abc' and strip_prefix('aab', 'a') == 'ab'\n"),
 ("matches", "def count_matches(items, target):\n    \"\"\"Count items equal to target.\"\"\"\n    return sum(1 for x in items if x is target)\n",
  "from matches import count_matches\ndef test_cm():\n    assert count_matches(['ab', ''.join(['a', 'b']), 'x'], 'ab') == 2\n",
  "def test_more():\n    assert count_matches([[1], [1], [2]], [1]) == 2\n"),
]
for name, src, vis, extra in DEBUG:
    tf = "test_%s.py" % name
    T("debug-" + name, "debugging",
      "The tests in %s fail. Find and fix the bug in %s.py without editing the test file." % (tf, name) + SUFFIX,
      {name + ".py": src, tf: vis},
      all_of(unchanged(tf, vis), hidden(vis + "\n" + extra)))

# ---------------- C. TOOL CALLING (15): shell/git/hash/test-runner work, answers to answer.txt ----------------
def _gen_applog():
    r = random.Random(301)
    levels = ["INFO"] * 14 + ["DEBUG"] * 5 + ["WARN"] * 3 + ["ERROR"] * 2
    msgs = ["cache refreshed", "user login ok", "payment queued", "slow query 812ms", "retrying upstream", "job finished", "webhook received"]
    lines, n = [], 0
    for i in range(3000):
        lv = r.choice(levels)
        n += lv == "ERROR"
        lines.append("2026-10-%02d %02d:%02d:%02d [%s] %s id=%d" % (1 + i // 400, r.randrange(24), r.randrange(60), r.randrange(60), lv, r.choice(msgs), i))
    return "\n".join(lines) + "\n", n
_applog, _applog_n = _gen_applog()
T("tool-log-errors", "tool", "How many lines in logs/app.log have the level ERROR?" + ANS, {"logs/app.log": _applog}, answer_num(_applog_n))

_blob = bytes(random.Random(302).randrange(256) for _ in range(50000))
T("tool-sha256", "tool", "Compute the SHA-256 hash of data/blob.bin and write the lowercase hex digest." + ANS,
  {"data/blob.bin": _blob}, answer_is(hashlib.sha256(_blob).hexdigest()))

def _pyfiles():
    r = random.Random(303); f = {}; n = 0
    for d in ["src", "src/core", "src/core/util", "src/api", "src/api/v2", "src/legacy"]:
        for i in range(r.randrange(2, 6)):
            f["%s/m%d.py" % (d, i)] = "X = %d\n" % i; n += 1
        f["%s/notes%d.txt" % (d, r.randrange(9))] = "x\n"
        if r.random() < 0.6:
            f["%s/types.pyi" % d] = "X: int\n"
    f["src/core/old.py.bak"] = "X=1\n"; f["src/README.md"] = "# src\n"
    return f, n
_pyf, _pyn = _pyfiles()
T("tool-count-py", "tool", "Count the .py files (Python source files only, recursively) under src/." + ANS, _pyf, answer_num(_pyn))

_mix = "import pytest\n" + "".join("def test_ok_%d():\n    assert %d == %d\n" % (i, i, i) for i in range(7)) + \
       "def test_bad_a():\n    assert 1 + 1 == 3\ndef test_bad_b():\n    assert 'ice'.upper() == 'Ice'\n" + \
       "@pytest.mark.parametrize('x', [1, 2, 3])\ndef test_param(x):\n    assert x != 2\n"
T("tool-pytest-count", "tool", "Run the test suite in tests/ and report how many tests FAIL. Do not modify any files." + ANS,
  {"tests/test_mix.py": _mix}, all_of(answer_num(3), unchanged("tests/test_mix.py", _mix)))

def _git(ws, *a):
    e = dict(os.environ, GIT_AUTHOR_NAME="Eval", GIT_AUTHOR_EMAIL="eval@example.com", GIT_COMMITTER_NAME="Eval", GIT_COMMITTER_EMAIL="eval@example.com")
    return subprocess.run(["git"] + list(a), cwd=ws, capture_output=True, text=True, env=e)

def _repo_cfg(ws):
    os.makedirs(ws, exist_ok=True)
    _git(ws, "init", "-q", "-b", "main")
    plan = [("config.yaml", "port: 80\n"), ("app.py", "print(1)\n"), ("config.yaml", "port: 8080\n"), ("README.md", "# app\n"),
            ("app.py", "print(2)\n"), ("config.yaml", "port: 8080\ndebug: false\n"), ("docs/config.yaml.md", "about config\n"), ("app.py", "print(3)\n")]
    for i, (p, c) in enumerate(plan):
        fp = os.path.join(ws, p); os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8", newline="").write(c)
        _git(ws, "add", "-A"); _git(ws, "commit", "-q", "-m", "change %d: %s" % (i, p))
T("tool-git-log", "tool", "This folder is a git repository. How many commits changed the file config.yaml (in the repository root)?" + ANS, _repo_cfg, answer_num(3))

_readme_typo = "# Frostlnie Hire\n\nParty ice-machine hire across Sydney.\n"
def _repo_typo(ws):
    os.makedirs(ws, exist_ok=True)
    _git(ws, "init", "-q", "-b", "main")
    open(os.path.join(ws, "README.md"), "w", encoding="utf-8", newline="").write(_readme_typo)
    open(os.path.join(ws, "app.py"), "w", encoding="utf-8", newline="").write("print('ok')\n")
    _git(ws, "add", "-A"); _git(ws, "commit", "-q", "-m", "initial")
def _chk_branch(ws):
    b = _git(ws, "show", "fix/readme-typo:README.md")
    if b.returncode != 0: return False, "branch fix/readme-typo missing or README absent"
    if "Frostlnie" in b.stdout or "FrostLine Hire" not in b.stdout: return False, "README on branch not fixed"
    m = _git(ws, "log", "-1", "--format=%s", "fix/readme-typo").stdout.strip()
    if m != "Fix README typo": return False, "commit message is %r" % m
    if _git(ws, "show", "main:README.md").stdout != _readme_typo: return False, "main branch was changed"
    return True, ""
T("tool-git-branch", "tool", "This folder is a git repository. Create a branch named fix/readme-typo, fix the spelling 'Frostlnie' -> 'FrostLine' in README.md and commit it on that branch with the message 'Fix README typo'. Leave the main branch unchanged." + SUFFIX, _repo_typo, _chk_branch)

def _assets():
    r = random.Random(307); f = {}; sizes = {}
    for nm in ["logo.png", "hero.jpg", "menu.pdf", "promo.mp4", "icon.svg", "banner.webp", "brochure.pdf", "bg.jpg"]:
        s = r.randrange(1000, 90000)
        while s in sizes.values(): s += 1
        sizes[nm] = s; f["assets/" + nm] = bytes(r.randrange(256) for _ in range(s))
    f["assets/archive/old_promo.mp4"] = bytes(200000)
    return f, max(sizes, key=sizes.get)
_asf, _asbig = _assets()
T("tool-largest", "tool", "Which file directly inside assets/ (ignore subfolders) is the largest? Give just the file name." + ANS, _asf, answer_is(_asbig))

def _access():
    r = random.Random(308); ips = ["10.0.0.%d" % i for i in range(2, 30)] + ["203.0.113.%d" % i for i in range(1, 9)]
    w = [r.randrange(1, 40) for _ in ips]; w[ips.index("203.0.113.7")] += 25
    lines, cnt, n5 = [], {}, 0
    for i in range(4000):
        ip = r.choices(ips, w)[0]; cnt[ip] = cnt.get(ip, 0) + 1
        st = r.choice([200] * 20 + [301, 404, 404, 500, 502, 503])
        n5 += st >= 500
        lines.append('%s - - [09/Oct/2026:%02d:%02d:%02d +1100] "GET /p/%d HTTP/1.1" %d %d' % (ip, r.randrange(24), r.randrange(60), r.randrange(60), r.randrange(500), st, r.randrange(100, 9000)))
    top = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))
    assert top[0][1] > top[1][1]
    return "\n".join(lines) + "\n", top[0][0], n5
_acc, _acctop, _acc5 = _access()
T("tool-top-ip", "tool", "In logs/access.log, which client IP address made the most requests?" + ANS, {"logs/access.log": _acc}, answer_is(_acctop))

def _customers():
    r = random.Random(309); subs = ["Parramatta", "Penrith", "Bondi", "Manly", "Newtown", "Liverpool", "Chatswood", "Hornsby", "Cronulla", "Blacktown", "Ryde", "Wollongong", "Gosford"]
    rows = ["id,name,suburb,postcode"]; used = set()
    for i in range(400):
        s = r.choice(subs[:11]); used.add(s)
        rows.append("C%04d,Customer %d,%s,2%03d" % (i, i, s, r.randrange(1000)))
    return "\n".join(rows) + "\n", len(used)
_cust, _custn = _customers()
T("tool-unique-suburbs", "tool", "How many distinct suburbs appear in the suburb column of customers.csv?" + ANS, {"customers.csv": _cust}, answer_num(_custn))

def _configs():
    r = random.Random(310); f = {}; ports = [8080, 8081, 9000, 443, 8000, 3000, 5000, 8088, 9443, 8444, 18443]
    names = ["edge-%02d.yaml" % i for i in range(1, 13)]; target = names[6]
    for nm in names:
        p = 8443 if nm == target else r.choice(ports)
        f["configs/" + nm] = "name: %s\nlisten:\n  host: 0.0.0.0\n  port: %d\n# old port: 8443 (removed)\nlimits:\n  rps: %d\n" % (nm[:-5], p, r.randrange(50, 500)) if nm != names[2] else \
            "name: %s\nlisten:\n  host: 0.0.0.0\n  port: %d\nlimits:\n  rps: 18443\n" % (nm[:-5], p)
    return f, target
_cf, _cft = _configs()
def _chk_cfg(ws):
    a = os.path.basename(norm(ans(ws)).replace("\\", "/"))
    return a == _cft, "" if a == _cft else "answer=%r expected %s" % (ans(ws)[:60], _cft)
T("tool-find-config", "tool", "Which file in configs/ actually configures the service to listen on port 8443 (not just mentions it in a comment)? Give the file name." + ANS, _cf, _chk_cfg)

def _orders_json():
    r = random.Random(311); o = []; tot = Decimal("0")
    for i in range(120):
        st = r.choice(["paid", "paid", "paid", "pending", "refunded", "PAID"])
        amt = Decimal(r.randrange(500, 90000)) / 100
        o.append({"id": "O%04d" % i, "status": st, "amount": float(amt), "customer": "C%03d" % r.randrange(60)})
        if st == "paid": tot += amt
    return json.dumps({"orders": o}, indent=1), tot
_oj, _ojt = _orders_json()
T("tool-json-sum", "tool", "orders.json lists orders. What is the total of the amount field for orders whose status is exactly \"paid\" (lowercase)? Give the number with 2 decimals." + ANS, {"orders.json": _oj}, answer_num(_ojt))

_calc = "import argparse, hashlib\np = argparse.ArgumentParser()\np.add_argument('--mode', choices=['fast', 'slow'], required=True)\np.add_argument('n', type=int)\na = p.parse_args()\nh = int(hashlib.md5(('%s-%d' % (a.mode, a.n)).encode()).hexdigest()[:8], 16) % 100000\nprint(h)\n"
_calc_out = int(hashlib.md5(b"fast-17").hexdigest()[:8], 16) % 100000
T("tool-run-script", "tool", "Run calc.py with the arguments --mode fast 17 and report exactly what it prints." + ANS, {"calc.py": _calc}, answer_num(_calc_out))

def _lib():
    r = random.Random(313); lines = ['"""Ledger helpers."""', "import math", ""]
    names = ["f_%03d" % i for i in range(160)]; pos = r.randrange(60, 140); names[pos] = "reconcile"
    ln = None
    for nm in names:
        lines.append("")
        if nm == "reconcile": ln = len(lines) + 1
        lines.append("def %s(x, y=%d):" % (nm, r.randrange(9)))
        lines.append('    """%s helper; see reconcile_all for batch use."""' % nm)
        for k in range(r.randrange(2, 9)):
            lines.append("    x = x * %d + y  # step %d" % (r.randrange(2, 9), k))
        lines.append("    return x")
    lines += ["", "def reconcile_all(rows):", "    return [reconcile(r) for r in rows]", ""]
    return "\n".join(lines) + "\n", ln
_libsrc, _libln = _lib()
T("tool-line-number", "tool", "On which line number of lib.py is the function reconcile defined (the 'def reconcile' line; line 1 is the first line)?" + ANS, {"lib.py": _libsrc}, answer_num(_libln))

def _docs():
    r = random.Random(314); vocab = "ice-machine machine hire event sydney ice syrup flavour delivery booking invoice quote party school fete".split()
    f = {}; tot = 0
    for i in range(9):
        paras = []
        for _ in range(r.randrange(3, 8)):
            ws_ = [r.choice(vocab) for _ in range(r.randrange(20, 90))]; tot += len(ws_); paras.append(" ".join(ws_))
        f["docs/page%d.md" % i] = "\n\n".join(paras) + "\n"
    f["docs/extra/ignore.txt"] = "not markdown words here\n"
    return f, tot
_dcf, _dcn = _docs()
T("tool-word-count", "tool", "What is the total number of words across all .md files directly in docs/ (words = whitespace-separated tokens, as wc -w counts them)?" + ANS, _dcf, answer_num(_dcn))

def _notes():
    r = random.Random(315); f = {}
    for i in range(6):
        f["notes/note_%d.txt" % i] = "note %d %s\n" % (i, r.random())
    f["notes/draft.md"] = "# not a txt\n"; f["notes/sub/inner.txt"] = "subfolder file\n"
    return f
_nf = _notes()
def _chk_zip(ws):
    p = os.path.join(ws, "backup.zip")
    if not os.path.exists(p): return False, "backup.zip missing"
    try:
        z = zipfile.ZipFile(p)
        names = {n for n in z.namelist() if not n.endswith("/")}
        want = {k.split("/")[1] for k in _nf if k.endswith(".txt") and k.count("/") == 1}
        if names != want: return False, "zip has %s" % sorted(names)
        for n in want:
            if z.read(n).decode() != _nf["notes/" + n]: return False, "content mismatch " + n
        return True, ""
    except Exception as e:
        return False, "bad zip: %s" % e
T("tool-zip", "tool", "Create backup.zip in the current folder containing every .txt file directly inside notes/ (not subfolders), stored at the root of the archive (no folder paths inside the zip)." + SUFFIX, _nf, _chk_zip)

# ---------------- D. FILE OPERATIONS (15) ----------------
def _exists(ws, rel): return os.path.exists(os.path.join(ws, rel))

_imgs = {"images/beach_%d.jpeg" % i: ("JPEGDATA-%d\n" % i) for i in range(5)}
_imgs["images/logo.png"] = "PNGDATA\n"; _imgs["images/keep.jpg"] = "ALREADYJPG\n"
def _chk_rename(ws):
    for i in range(5):
        if _exists(ws, "images/beach_%d.jpeg" % i): return False, "beach_%d.jpeg still present" % i
        if rd(ws, "images/beach_%d.jpg" % i) != "JPEGDATA-%d\n" % i: return False, "beach_%d.jpg missing/changed" % i
    if rd(ws, "images/logo.png") != "PNGDATA\n" or rd(ws, "images/keep.jpg") != "ALREADYJPG\n": return False, "other files changed"
    if len(os.listdir(os.path.join(ws, "images"))) != 7: return False, "unexpected files in images/"
    return True, ""
T("files-rename-ext", "fileops", "Rename every .jpeg file in images/ to the same name with a .jpg extension. Leave other files alone." + SUFFIX, _imgs, _chk_rename)

_dl_map = {"report.pdf": "pdf", "Invoice-77.PDF": "pdf", "sales.csv": "csv", "stock.csv": "csv", "photo.jpg": "images", "shot.PNG": "images",
           "setup.exe": "other", "notes.txt": "other", "archive.zip": "other"}
def _chk_organise(ws):
    for fn, d in _dl_map.items():
        if rd(ws, "downloads/%s/%s" % (d, fn)) != "data:" + fn + "\n": return False, "%s not in downloads/%s/" % (fn, d)
        if _exists(ws, "downloads/" + fn): return False, fn + " left in downloads/"
    return True, ""
T("files-organise", "fileops", "Organise downloads/ into subfolders by file type: pdf/ for .pdf, csv/ for .csv, images/ for .jpg/.jpeg/.png, other/ for everything else. Extensions are case-insensitive. Move (do not copy) the files and keep their names." + SUFFIX,
  {"downloads/" + k: "data:" + k + "\n" for k in _dl_map}, _chk_organise)

_pyproj = '[project]\nname = "snowapp"\nversion = "1.4.2"\ndependencies = [\n  "snowlib==1.4.2",\n  "requests>=2.31",\n]\n'
_pkgjson = '{\n  "name": "snowapp-ui",\n  "version": "1.4.2",\n  "dependencies": {\n    "left-pad": "1.4.2"\n  }\n}\n'
_init = '"""Snow app."""\n__version__ = "1.4.2"\n'
_chlog = "# Changelog\n\n## 1.4.2\n- fixed syrup ratios\n\n## 1.4.1\n- first release\n"
def _chk_bump(ws):
    want = {"pyproject.toml": _pyproj.replace('version = "1.4.2"', 'version = "1.5.0"'),
            "package.json": _pkgjson.replace('"version": "1.4.2"', '"version": "1.5.0"'),
            "app/__init__.py": _init.replace("1.4.2", "1.5.0"), "CHANGELOG.md": _chlog}
    for k, v in want.items():
        got = (rd(ws, k) or "").replace("\r\n", "\n")
        if got.rstrip("\n") != v.rstrip("\n"): return False, "%s not as expected" % k  # a missing final newline is not a wrong bump
    return True, ""
T("files-version-bump", "fileops", "Bump this project's own version from 1.4.2 to 1.5.0 everywhere it is declared (pyproject.toml, package.json, app/__init__.py). Do not change dependency versions or CHANGELOG.md." + SUFFIX,
  {"pyproject.toml": _pyproj, "package.json": _pkgjson, "app/__init__.py": _init, "CHANGELOG.md": _chlog}, _chk_bump)

def _products():
    r = random.Random(404); rows = []
    for i in range(25):
        rows.append({"sku": "SKU-%03d" % i, "name": r.choice(["Blue Raspberry", "Cola", "Mango, Passionfruit", "Lime \"Zing\"", "Cherry"]) + " %d" % i,
                     "price": round(r.randrange(100, 5000) / 100, 2), "qty": r.randrange(0, 300)})
    buf = io.StringIO(); w = csv.writer(buf, lineterminator="\n"); w.writerow(["sku", "name", "price", "qty"])
    for x in rows: w.writerow([x["sku"], x["name"], "%.2f" % x["price"], x["qty"]])
    return buf.getvalue(), rows
_prodcsv, _prodrows = _products()
def _chk_prodjson(ws):
    try: got = json.loads(rd(ws, "products.json"))
    except Exception as e: return False, "products.json unreadable: %s" % e
    if not isinstance(got, list) or len(got) != len(_prodrows): return False, "wrong length/shape"
    for g, w in zip(got, _prodrows):
        if set(g) != {"sku", "name", "price", "qty"}: return False, "keys %s" % sorted(g)
        if g["sku"] != w["sku"] or g["name"] != w["name"] or not isinstance(g["qty"], int) or g["qty"] != w["qty"] \
           or isinstance(g["price"], str) or abs(g["price"] - w["price"]) > 1e-9: return False, "row mismatch %s" % g
    return True, ""
T("files-csv-to-json", "fileops", "Convert products.csv to products.json: a JSON array of objects with keys sku, name, price (a number) and qty (an integer), in the same order as the CSV." + SUFFIX, {"products.csv": _prodcsv}, _chk_prodjson)

def _inventory():
    r = random.Random(405); items = [{"sku": "INV-%03d" % r.randrange(1000), "name": r.choice(["Cup 12oz", "Cup, 16oz", "Lid", "Straw \"jumbo\""]), "qty": r.randrange(500), "bin": "A%d" % r.randrange(9)} for _ in range(30)]
    seen = set(); items = [x for x in items if not (x["sku"] in seen or seen.add(x["sku"]))]
    return json.dumps({"items": items}, indent=2), sorted(items, key=lambda x: x["sku"])
_invjson, _invsorted = _inventory()
def _chk_invcsv(ws):
    rows = read_csv(ws, "inventory.csv")
    if not rows: return False, "inventory.csv missing"
    want = [["sku", "name", "qty"]] + [[x["sku"], x["name"], str(x["qty"])] for x in _invsorted]
    rows = [r for r in rows if r]
    return rows == want, "" if rows == want else "csv content mismatch (first diff near %s)" % next((a for a, b in zip(rows, want) if a != b), rows[-1:])
T("files-json-to-csv", "fileops", "Convert inventory.json to inventory.csv with header sku,name,qty (drop other fields), rows sorted by sku, properly quoted CSV." + SUFFIX, {"inventory.json": _invjson}, _chk_invcsv)

_base = {"app": {"name": "snow", "debug": False, "db": {"host": "localhost", "port": 5432, "pool": 5}}, "features": ["a", "b"], "log": {"level": "info"}}
_over = {"app": {"debug": True, "db": {"host": "db.internal", "pool": 20}}, "features": ["c"], "log": {"file": "app.log"}, "new": 1}
def _deep(a, b):
    o = json.loads(json.dumps(a))
    for k, v in b.items():
        o[k] = _deep(o[k], v) if isinstance(v, dict) and isinstance(o.get(k), dict) else v
    return o
def _chk_merge(ws):
    try: got = json.loads(rd(ws, "merged.json"))
    except Exception as e: return False, "merged.json unreadable: %s" % e
    w = _deep(_base, _over)
    return got == w, "" if got == w else "merged.json = %s" % json.dumps(got)[:200]
T("files-config-merge", "fileops", "Deep-merge override.json onto base.json and write the result to merged.json: nested objects merge recursively, any other value (including lists) from override.json replaces the base value. Do not modify the inputs." + SUFFIX,
  {"base.json": json.dumps(_base, indent=2), "override.json": json.dumps(_over, indent=2)}, _chk_merge)

_billing = "recalc_total_flag = True\n\ndef calc_total(items):\n    \"\"\"Sum qty * price.\"\"\"\n    return round(sum(q * p for q, p in items), 2)\n"
_report = "from pkg.billing import calc_total\n\ndef summary(items):\n    return 'Total: %.2f' % calc_total(items)\n"
_pinit = "from pkg.billing import calc_total\n__all__ = ['calc_total']\n"
_ptest = "from pkg import calc_total\nfrom pkg.report import summary\n\ndef test_total():\n    assert calc_total([(2, 1.5), (1, 3)]) == 6.0\n    assert summary([(1, 2)]) == 'Total: 2.00'\n"
def _chk_refactor(ws):
    for root, _, fs in os.walk(ws):
        for fn in fs:
            if fn.endswith(".py"):
                t = open(os.path.join(root, fn), encoding="utf-8").read()
                if re.search(r"\bcalc_total\b", t): return False, "calc_total still in " + fn
    if "recalc_total_flag = True" not in (rd(ws, "pkg/billing.py") or ""): return False, "unrelated name recalc_total_flag was changed"
    return run_hidden(ws, "from pkg import calculate_total\nfrom pkg.billing import calculate_total as c2\nfrom pkg.report import summary\ndef test_h():\n    assert calculate_total([(3, 2.5)]) == 7.5 and c2 is calculate_total and summary([(2, 2)]) == 'Total: 4.00'\n")
T("files-refactor-rename", "fileops", "Rename the function calc_total to calculate_total across the whole project (definition, imports, __all__, call sites and tests). Do not rename anything else. Make sure the tests still pass." + SUFFIX,
  {"pkg/__init__.py": _pinit, "pkg/billing.py": _billing, "pkg/report.py": _report, "tests/test_billing.py": _ptest}, _chk_refactor)

def _contacts():
    r = random.Random(408); rows = [["name", "email", "phone"]]; seen = set(); want = [rows[0]]
    for i in range(80):
        e = "user%d@%s" % (r.randrange(50), r.choice(["gmail.com", "frostline.com.au", "outlook.com"]))
        e = e.upper() if r.random() < 0.2 else e
        row = ["Person %d" % i, e, "04%08d" % r.randrange(10 ** 8)]; rows.append(row)
        if e.lower() not in seen: seen.add(e.lower()); want.append(row)
    buf = io.StringIO(); csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue(), want
_ccsv, _cwant = _contacts()
def _chk_dedupe(ws):
    rows = [r for r in (read_csv(ws, "contacts_clean.csv") or []) if r]
    return rows == _cwant, "" if rows == _cwant else "contacts_clean.csv has %d rows, expected %d" % (len(rows), len(_cwant))
T("files-dedupe-csv", "fileops", "Remove duplicate contacts from contacts.csv by email address (case-insensitive), keeping the first occurrence and the original row order and values. Write the result to contacts_clean.csv with the same header. Leave contacts.csv unchanged." + SUFFIX,
  {"contacts.csv": _ccsv}, all_of(unchanged("contacts.csv", _ccsv), _chk_dedupe))

_HDR = "# Copyright (c) 2026 FrostLine Hire"
_srcf = {"src/a.py": "import os\nprint(os.name)\n", "src/b.py": _HDR + "\nX = 1\n", "src/sub/c.py": "\n\ndef f():\n    return 1\n", "src/sub/d.txt": "not python\n", "src/e.py": ""}
def _chk_header(ws):
    for k, v in _srcf.items():
        got = (rd(ws, k) or "").replace("\r\n", "\n")
        if k.endswith(".py"):
            want = v if v.startswith(_HDR) else _HDR + "\n" + v
            if got.rstrip("\n") != want.rstrip("\n"): return False, "%s wrong: %r" % (k, got[:80])
        elif got != v: return False, k + " changed"
    return True, ""
T("files-license-header", "fileops", "Add the line '%s' as the very first line of every .py file under src/ (recursively) that does not already start with it. Do not duplicate it and do not change anything else." % _HDR + SUFFIX, _srcf, _chk_header)

def _inbox():
    r = random.Random(410); emails = ["jon@frostline.com.au", "accounts@chillco.com", "bob.smith@mailbox.example", "events@school.nsw.edu.au", "j-li@outlook.com", "orders+hire@frostline.com.au", "Ana.Rossi@Example.org"]
    f = {}
    tpl = ["Hi team, please contact {e} about the booking.", "From: {e}\nSubject: quote", "Reply to <{e}> asap.", "My email is {e}.", "cc: {e}, thanks"]
    for i in range(6):
        body = [r.choice(tpl).format(e=r.choice(emails)) for _ in range(4)] + ["Call 0412 345 678 or visit frostline.com.au", "price @ $5 each"]
        f["inbox/mail_%d.txt" % i] = "\n".join(body) + "\n"
    used = set()
    for v in f.values():
        for e in emails:
            if e in v: used.add(e.lower())
    return f, sorted(used)
_inf, _inwant = _inbox()
def _chk_emails(ws):
    got = [l.strip() for l in (rd(ws, "emails.txt") or "").splitlines() if l.strip()]
    return got == _inwant, "" if got == _inwant else "emails.txt=%s expected %s" % (got, _inwant)
T("files-extract-emails", "fileops", "Extract every email address from the .txt files in inbox/ into emails.txt: one per line, lowercase, unique, sorted alphabetically." + SUFFIX, _inf, _chk_emails)

_env = "# FrostLine app settings\nAPP_ENV=production\nDB_URL=postgres://snow:pa55@db:5432/app\n\n# Payments\nSTRIPE_KEY=sk_test_fake_123\nFEATURE_X=true  \nEMPTY=\n"
def _chk_envex(ws):
    want = "# FrostLine app settings\nAPP_ENV=\nDB_URL=\n\n# Payments\nSTRIPE_KEY=\nFEATURE_X=\nEMPTY=\n"
    got = (rd(ws, ".env.example") or "").replace("\r\n", "\n")
    ok = got.rstrip("\n") == want.rstrip("\n")
    return ok, "" if ok else ".env.example=%r" % got[:200]
T("files-env-example", "fileops", "Create .env.example from .env: keep every comment line, blank line and key in the same order, but remove all values (so each setting becomes KEY=). Do not modify .env." + SUFFIX,
  {".env": _env}, all_of(unchanged(".env", _env), _chk_envex))

def _big():
    r = random.Random(412); rows = ["order_id,customer,total"] + ["%d,C%03d,%.2f" % (1000 + i, r.randrange(300), r.randrange(500, 50000) / 100) for i in range(450)]
    return "\n".join(rows) + "\n", rows
_bigcsv, _bigrows = _big()
def _chk_split(ws):
    for k in range(5):
        want = [_bigrows[0]] + _bigrows[1 + k * 100: 1 + (k + 1) * 100]
        got = [l for l in (rd(ws, "parts/part_%d.csv" % (k + 1)) or "").replace("\r\n", "\n").split("\n") if l]
        if got != want: return False, "parts/part_%d.csv wrong (%d lines)" % (k + 1, len(got))
    if _exists(ws, "parts/part_6.csv"): return False, "extra part_6.csv"
    return True, ""
T("files-split-csv", "fileops", "Split big.csv into files of at most 100 data rows each: parts/part_1.csv, parts/part_2.csv, ... in order, each starting with the original header row." + SUFFIX, {"big.csv": _bigcsv}, _chk_split)

_tabf = {"app/main.py": "def main():\n\tfor i in range(3):\n\t\tprint(i)\n\nmain()\n", "app/util.py": "class U:\n\tdef f(self):\n\t\treturn '\\t'\n",
         "vendor/lib.py": "def v():\n\treturn 1\n", "app/readme.txt": "a\tb\n"}
def _chk_tabs(ws):
    for k, v in _tabf.items():
        got = (rd(ws, k) or "").replace("\r\n", "\n")
        want = v.replace("\t", "    ") if k.startswith("app/") and k.endswith(".py") else v
        if got != want: return False, k + " not as expected"
    return True, ""
T("files-tabs-to-spaces", "fileops", "Replace every tab character with 4 spaces in all .py files of this project except anything under vendor/. Do not touch non-.py files." + SUFFIX, _tabf, _chk_tabs)

_names = "\n".join(["zoe", "Adam", "", "bella", "Charlie", "  ", "aaron", "Zack", "dave", ""]) + "\n"
def _chk_names(ws):
    got = [l for l in (rd(ws, "names.txt") or "").replace("\r\n", "\n").split("\n")]
    while got and got[-1] == "": got.pop()
    want = sorted([n for n in _names.split("\n") if n.strip()], key=str.lower)
    return got == want, "" if got == want else "names.txt=%s" % got
T("files-sort-names", "fileops", "Sort the lines of names.txt alphabetically ignoring case, remove blank (empty or whitespace-only) lines, and save the result back to names.txt." + SUFFIX, {"names.txt": _names}, _chk_names)

_sh = {"scripts/deploy.sh": "#!/bin/sh\r\necho deploy\r\nexit 0\r\n", "scripts/backup.sh": "#!/bin/sh\r\ntar czf b.tgz data\r\n", "scripts/run.bat": "@echo off\r\necho hi\r\n", "scripts/ok.sh": "#!/bin/sh\necho ok\n"}
def _chk_crlf(ws):
    for k, v in _sh.items():
        got = rdb(ws, k)
        want = (v.replace("\r\n", "\n") if k.endswith(".sh") else v).encode()
        if got != want: return False, k + " bytes not as expected"
    return True, ""
T("files-line-endings", "fileops", "Convert the .sh files in scripts/ from Windows (CRLF) to Unix (LF) line endings. Leave the .bat file with CRLF endings." + SUFFIX, _sh, _chk_crlf)

# ---------------- E. LONG-CONTEXT RETRIEVAL (10): large inputs, needle + aggregate questions ----------------
def _serverlog():
    r = random.Random(501); lines = []; pos = r.randrange(9000, 17000); rid = None
    for i in range(20000):
        lv = "FATAL" if i == pos else r.choice(["INFO"] * 9 + ["WARN", "ERROR"])
        q = "req-%08x" % r.getrandbits(32)
        if i == pos: rid = q
        msg = "worker crashed: out of memory" if i == pos else r.choice(["handled", "cache miss", "fatal-ish timeout retried", "slow upstream", "user FATALITY score saved"])
        lines.append("2026-10-08T%02d:%02d:%02d %s %s %s" % (i // 900 % 24, i // 15 % 60, i % 60, lv, q, msg))
    return "\n".join(lines) + "\n", rid
_slog, _srid = _serverlog()
T("long-needle-log", "longctx", "logs/server.log is very large. Find the single log entry with level FATAL and report its request id (the req-... token)." + ANS, {"logs/server.log": _slog}, answer_is(_srid), timeout=480)

def _orders_big():
    r = random.Random(502); skus = ["SLUSH-BLUE-5L", "SLUSH-RED-5L", "SLUSH-BLUE-1L", "CUP-12", "CUP-16", "LID-STD", "SLUSH-BLUE-5L-PROMO", "SYRUP-MANGO-5L"]
    rows = ["order_id,date,customer,sku,qty"]; qty = 0; march = set()
    for i in range(10000):
        d = date(2026, 1, 1) + timedelta(days=r.randrange(280)); s = r.choice(skus); q = r.randrange(1, 40); c = "C%04d" % r.randrange(2500)
        rows.append("%d,%s,%s,%s,%d" % (50000 + i, d.isoformat(), c, s, q))
        if s == "SLUSH-BLUE-5L": qty += q
        if d.month == 3: march.add(c)
    return "\n".join(rows) + "\n", qty, len(march)
_obig, _obq, _obm = _orders_big()
T("long-aggregate-sku", "longctx", "orders.csv has 10,000 rows. What is the total qty ordered for the SKU exactly equal to SLUSH-BLUE-5L?" + ANS, {"orders.csv": _obig}, answer_num(_obq), timeout=480)
T("long-distinct-march", "longctx", "orders.csv has 10,000 rows. How many distinct customers placed at least one order in March 2026?" + ANS, {"orders.csv": _obig}, answer_num(_obm), timeout=480)

def _cfgdump():
    r = random.Random(504); svc = {}
    for i in range(400):
        svc["svc_%03d" % i] = {"retry": {"max_attempts": r.randrange(1, 9), "backoff_ms": r.randrange(100, 900)}, "timeout_s": r.randrange(5, 60), "owner": "team-%d" % r.randrange(20)}
    svc["billing_v1"] = {"retry": {"max_attempts": 2}}
    svc["billing"] = {"retry_old": {"max_attempts": 9}, "timeout_s": 30, "retry": {"backoff_ms": 250, "max_attempts": 7}}
    svc["notifications"] = {"billing": {"retry": {"max_attempts": 4}}}
    keys = list(svc); r.shuffle(keys)
    return json.dumps({"version": 3, "services": {k: svc[k] for k in keys}}, indent=2), 7
_cdump, _cdv = _cfgdump()
T("long-config-path", "longctx", "config_dump.json is large. What is the value at the exact path services -> billing -> retry -> max_attempts?" + ANS, {"config_dump.json": _cdump}, answer_num(_cdv))

def _repo40():
    r = random.Random(505); f = {}; target = "mod_%02d.py" % r.randrange(40)
    f["billing/legacy.py"] = "def legacy_charge(amount):\n    \"\"\"Deprecated: do not use.\"\"\"\n    return amount\n"
    for i in range(40):
        nm = "mod_%02d.py" % i; body = ["import math", ""]
        for k in range(r.randrange(8, 20)):
            body += ["def f%d_%d(x):" % (i, k), "    return math.floor(x * %d)" % r.randrange(2, 9), ""]
        if nm == target:
            body += ["from billing.legacy import legacy_charge", "", "def settle(order):", "    return legacy_charge(order['total'])", ""]
        elif i % 9 == 1:
            body += ["# NOTE: never call legacy_charge(amount) here; use charge_v2() instead", ""]
        elif i % 9 == 4:
            body += ["def explain():", "    return 'legacy_charge( was removed in v3'", ""]
        f["src/" + nm] = "\n".join(body) + "\n"
    return f, target
_r40, _r40t = _repo40()
def _chk_caller(ws):
    a = os.path.basename(norm(ans(ws)).replace("\\", "/"))
    return a == _r40t, "" if a == _r40t else "answer=%r expected %s" % (ans(ws)[:60], _r40t)
T("long-find-caller", "longctx", "Exactly one module in src/ actually calls the function legacy_charge (others only mention it in comments or strings). Which file is it? Give the file name." + ANS, _r40, _chk_caller)

def _contracts():
    r = random.Random(506)
    cos = ["%s %s Pty Ltd" % (a, b) for a in ["Seaport", "Coastal", "Westside", "Northern", "Summit", "Bayview", "Redgum", "Blue Gum", "Kingsford", "Sunset"]
           for b in ["Ice", "Freight", "Syrups", "Cups", "Logistics", "Dairy"]]
    r.shuffle(cos); cos = cos[:45]
    if "Seaport Ice Pty Ltd" not in cos: cos[7] = "Seaport Ice Pty Ltd"
    cos.append("Seaport Ice Supplies Pty Ltd"); r.shuffle(cos)
    parts = ["MASTER SUPPLY AGREEMENTS - FROSTLINE NSW\n"]; ans_ = None
    for n, c in enumerate(cos, 1):
        days = r.choice([14, 21, 30, 45, 60, 90])
        while c == "Seaport Ice Pty Ltd" and days in (30,): days = r.choice([21, 45, 60])
        if c == "Seaport Ice Pty Ltd": ans_ = days
        filler = " ".join(r.choice(["The Supplier", "warrants", "that all goods", "comply with", "applicable Australian Standards", "and food safety law,", "including", "labelling,", "storage", "and transport requirements."]) for _ in range(60))
        parts.append("Schedule %d. %s (ABN %011d)\n%d.1 Term. This agreement runs for %d months.\n%d.2 Quality. %s\n%d.3 Termination. Either party may terminate this agreement by giving %d days' written notice. "
                     "Standard notice under clause 2 of the master terms is 30 days unless varied here.\n%d.4 Payment. Net %d days from invoice.\n"
                     % (n, c, r.randrange(10 ** 10, 10 ** 11), n, r.choice([12, 24, 36]), n, filler, n, days, n, r.choice([7, 14, 30])))
    return "\n".join(parts), ans_
_ctr, _ctra = _contracts()
T("long-contract-clause", "longctx", "Read contracts.txt. What notice period, in days, is required to terminate the agreement with Seaport Ice Pty Ltd specifically?" + ANS, {"contracts.txt": _ctr}, answer_num(_ctra), timeout=480)

def _glacier():
    r = random.Random(507); f = {}; projects = ["Project Aurora", "Project Glacier Bay", "Project Tundra", "Project Frost", "Project Glacier", "Project Avalanche"]
    dl = {p: (date(2026, 10, 15) + timedelta(days=r.randrange(10, 120))).isoformat() for p in projects}
    for i in range(50):
        lines = ["# Weekly update %d" % i, ""]
        for _ in range(r.randrange(6, 14)):
            p = r.choice(projects)
            lines.append(r.choice(["%s is on track." % p, "Discussed %s scope with the team." % p, "%s budget review next week." % p, "Risks for %s: supplier delay." % p]))
        f["docs/update_%02d.md" % i] = "\n".join(lines) + "\n"
    k = r.randrange(50); f["docs/update_%02d.md" % k] += "\nDecision: the delivery deadline for Project Glacier is %s (confirmed by Jon).\n" % dl["Project Glacier"]
    k2 = (k + 17) % 50; f["docs/update_%02d.md" % k2] += "\nDecision: the delivery deadline for Project Glacier Bay is %s.\n" % dl["Project Glacier Bay"]
    return f, dl["Project Glacier"]
_glf, _gla = _glacier()
T("long-multi-file", "longctx", "Across the 50 files in docs/, find the confirmed delivery deadline for Project Glacier (not Project Glacier Bay). Give the date as YYYY-MM-DD." + ANS, _glf, answer_is(_gla))

def _meeting():
    r = random.Random(508); owners = ["Jon", "Jo", "Joan", "Sam", "Priya", "Tom", "Jon", "Mia"]
    lines = ["# FrostLine ops meetings - 2026", ""]; n = 0
    for m in range(1, 13):
        lines += ["", "## Meeting %d (2026-%02d-02)" % (m, min(m, 9)), "", "Attendees: Jon, Sam, Priya, Tom, Mia, Jo (contractor), Joan (casual)", ""]
        for _ in range(r.randrange(8, 16)):
            lines.append(r.choice(["- Discussed winter demand for ice-machine hire and how school fetes book.", "- Reviewed supplier pricing for cups and lids; no change.",
                                   "- Jon noted the van service is overdue (informational, no action).", "- Sam presented the booking funnel numbers for the month."]))
        for _ in range(r.randrange(2, 6)):
            o = r.choice(owners); done = r.random() < 0.3
            n += o == "Jon"
            lines.append("- [%s] ACTION (Owner: %s): %s" % ("x" if done else " ", o, r.choice(["call the syrup supplier", "update the price list", "fix the website form", "book the van service", "send school quotes"])))
    return "\n".join(lines) + "\n", n
_mtg, _mtgn = _meeting()
T("long-action-items", "longctx", "meeting_notes.md contains a year of meeting notes. How many action items (lines starting '- [ ] ACTION' or '- [x] ACTION') have Owner exactly Jon (not Jo or Joan), done or not?" + ANS, {"meeting_notes.md": _mtg}, answer_num(_mtgn), timeout=480)

def _utils200():
    r = random.Random(509); lines = ["import functools, warnings", "", "def deprecated(fn):", "    @functools.wraps(fn)", "    def w(*a, **k):", "        warnings.warn(fn.__name__, DeprecationWarning)", "        return fn(*a, **k)", "    return w", "",
                                     "def deprecated_alias(name):", "    return lambda fn: fn", ""]; n = 0
    for i in range(200):
        k = r.random()
        if k < 0.12: lines.append("@deprecated"); n += 1
        elif k < 0.18: lines.append("# @deprecated (kept for reference)")
        elif k < 0.24: lines.append("@deprecated_alias('old_u%d')" % i)
        elif k < 0.28: lines += ["@functools.lru_cache(maxsize=None)", "@deprecated"]; n += 1
        lines += ["def u%d(x):" % i, "    return x + %d" % i, ""]
    return "\n".join(lines) + "\n", n
_u200, _u200n = _utils200()
T("long-count-decorated", "longctx", "How many functions in utils.py are decorated with exactly @deprecated (not @deprecated_alias, and not commented out)?" + ANS, {"utils.py": _u200}, answer_num(_u200n))

def _rebates():
    r = random.Random(510); lines = ['"""Rebate rules by contract version."""', ""]; tiers = {}
    for v in range(1, 61):
        tiers[v] = (r.randrange(2, 9), r.randrange(1, 50))
    order = list(range(1, 61)); r.shuffle(order)
    for v in order:
        lines += ["def compute_rebate_v%d(units):" % v, "    base = units * %d" % r.randrange(2, 20), "    return _tier_%d(base)" % v, ""]
    lines += ["", "# ---- tier helpers ----", ""]
    r.shuffle(order)
    for v in order:
        a, b = tiers[v]; lines += ["def _tier_%d(x):" % v, "    if x > 100:", "        return x * %d - %d" % (a, b), "    return x + %d" % b, ""]
    src = "\n".join(lines) + "\n"
    ns = {}; exec(src, ns)
    return src, ns["compute_rebate_v37"](10)
_reb, _rebv = _rebates()
T("long-code-trace", "longctx", "In rebates.py, what does compute_rebate_v37(10) return?" + ANS, {"rebates.py": _reb}, answer_num(_rebv))

# ---------------- F. BUSINESS MULTI-STEP (10): exact AUD money rules, checker recomputes from inputs ----------------
D2 = Decimal("0.01")
def _dec_eq(a, b):
    try: return Decimal(str(a).replace("$", "").replace(",", "")) == Decimal(str(b)).quantize(D2) and re.fullmatch(r"-?\$?[\d,]*\.\d{2}", str(a).strip()) is not None  # prompts demand exactly 2 decimals; do not round the agent's value for it
    except Exception: return False

def _gst_order():
    r = random.Random(601)
    items = [{"sku": "HIRE-DBL", "desc": "Double ice-machine hire", "qty": 3, "unit_price_ex": "4.15", "gst_free": False}]
    for i in range(9):
        items.append({"sku": "SKU%02d" % i, "desc": "item %d" % i, "qty": r.randrange(1, 13), "unit_price_ex": "%.2f" % (r.randrange(105, 9999) / 100), "gst_free": r.random() < 0.25})
    items += [{"sku": "FEE-A", "desc": "fee a", "qty": 1, "unit_price_ex": "0.15", "gst_free": False}, {"sku": "FEE-B", "desc": "fee b", "qty": 1, "unit_price_ex": "0.15", "gst_free": False}]  # per-line (0.02+0.02) != on-total (0.03)
    sub = sum(Decimal(x["unit_price_ex"]) * x["qty"] for x in items)
    gst = sum(cents(Decimal(x["unit_price_ex"]) * x["qty"] * Decimal("0.1")) for x in items if not x["gst_free"])
    return {"invoice": "INV-2026-0042", "items": items}, cents(sub), gst, cents(sub) + gst
_go, _gsub, _ggst, _gtot = _gst_order()
def _chk_invoice(ws):
    try: g = json.loads(rd(ws, "invoice.json"))
    except Exception as e: return False, "invoice.json unreadable: %s" % e
    for k, v in (("subtotal_ex", _gsub), ("gst", _ggst), ("total", _gtot)):
        if k not in g or not _dec_eq(g[k], v): return False, "%s=%r expected %s" % (k, g.get(k), v)
    return True, ""
T("biz-gst-invoice", "business",
  "Read order.json and write invoice.json with keys subtotal_ex, gst and total (each a string with exactly 2 decimals). Rules (Australian GST): each line total = qty * unit_price_ex; "
  "GST is 10% of each line total for lines where gst_free is false, rounded to the cent half-up PER LINE, then summed; subtotal_ex = sum of all line totals; total = subtotal_ex + gst." + SUFFIX,
  {"order.json": json.dumps(_go, indent=2)}, _chk_invoice)

def _bookings():
    r = random.Random(602); rows = []; base = datetime(2026, 11, 2, 8, 0)
    for i in range(40):
        st = base + timedelta(hours=r.randrange(0, 24 * 10, 2)); en = st + timedelta(hours=r.choice([2, 4, 6, 8]))
        rows.append(("B%03d" % (i + 1), r.choice(["DBL-1", "DBL-2", "TRP-1"]), st, en))
    rows.append(("B041", rows[0][1], rows[0][3], rows[0][3] + timedelta(hours=3)))
    conf = set()
    for a in rows:
        for b in rows:
            if a[0] < b[0] and a[1] == b[1] and a[2] < b[3] and b[2] < a[3]: conf.add("%s,%s" % (a[0], b[0]))
    txt = "id,machine,start,end\n" + "".join("%s,%s,%s,%s\n" % (i, m, s.isoformat(timespec="minutes"), e.isoformat(timespec="minutes")) for i, m, s, e in rows)
    return txt, sorted(conf)
_bk, _bkc = _bookings()
def _chk_conf(ws):
    got = [l.strip().replace(" ", "") for l in (rd(ws, "conflicts.txt") or "").splitlines() if l.strip()]
    return got == _bkc, "" if got == _bkc else "conflicts.txt has %d lines, expected %d (%s...)" % (len(got), len(_bkc), _bkc[:3])
T("biz-booking-conflicts", "business",
  "bookings.csv lists ice-machine hire bookings. Two bookings conflict if they are for the same machine and their time ranges overlap (a booking ending exactly when another starts is NOT a conflict). "
  "Write conflicts.txt with one line per conflicting pair as 'B003,B007' (lower id first), lines sorted, no header." + SUFFIX, {"bookings.csv": _bk}, _chk_conf)

def _stock():
    r = random.Random(603); rows = [["sku", "on_hand", "reorder_point", "reorder_qty", "supplier"]]; want = []
    for i in range(35):
        rp = r.randrange(5, 60); oh = r.randrange(0, 90); rq = r.randrange(10, 100); sup = r.choice(["Coastal Cups", "Blue Gum Syrups", "Redgum Freight"])
        if i == 3: oh = rp
        rows.append(["ST-%03d" % i, str(oh), str(rp), str(rq), sup])
        if oh <= rp: want.append([sup, "ST-%03d" % i, str(max(rq, 2 * rp - oh))])
    buf = io.StringIO(); csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue(), [["supplier", "sku", "qty"]] + sorted(want, key=lambda x: (x[0], x[1]))
_stk, _stkw = _stock()
def _chk_reorder(ws):
    got = [x for x in (read_csv(ws, "reorder.csv") or []) if x]
    return got == _stkw, "" if got == _stkw else "reorder.csv mismatch: %d rows vs %d" % (len(got), len(_stkw))
T("biz-reorder", "business",
  "From stock.csv, find every SKU where on_hand <= reorder_point. Order quantity = max(reorder_qty, 2 * reorder_point - on_hand). Write reorder.csv with header supplier,sku,qty sorted by supplier then sku." + SUFFIX,
  {"stock.csv": _stk}, _chk_reorder)

def _tiers():
    r = random.Random(604); prices = {"SLUSH-5L": "42.50", "CUP-12": "0.18", "SYRUP-1L": "11.95", "MACHINE-DAY": "120.00", "LID": "0.07"}
    rows = ["customer,sku,qty"]; tot = {}
    for i in range(30):
        c = r.choice(["Bondi Public School", "Manly Fete Committee", "Parra Events", "Snow Events Co"]); s = r.choice(list(prices)); q = r.choice([1, 3, 9, 10, 25, 49, 50, 120, 7])
        rows.append('"%s",%s,%d' % (c, s, q))
        disc = Decimal("0.15") if q >= 50 else Decimal("0.10") if q >= 10 else Decimal(0)
        tot[c] = tot.get(c, Decimal(0)) + cents(Decimal(prices[s]) * q * (1 - disc))
    pl = "sku,unit_price\n" + "".join("%s,%s\n" % kv for kv in prices.items())
    return "\n".join(rows) + "\n", pl, [["customer", "total"]] + [[c, "%.2f" % tot[c]] for c in sorted(tot)]
_tord, _tpl, _tw = _tiers()
def _chk_tiers(ws):
    got = [x for x in (read_csv(ws, "totals.csv") or []) if x]
    if len(got) != len(_tw) or got[0] != _tw[0]: return False, "totals.csv shape/header wrong: %s" % got[:2]
    for g, w in zip(got[1:], _tw[1:]):
        if g[0] != w[0] or not _dec_eq(g[1], w[1]): return False, "row %s expected %s" % (g, w)
    return True, ""
T("biz-discount-tiers", "business",
  "Price each line of orders.csv using price_list.csv with volume discounts on that line's qty: 1-9 no discount, 10-49 10% off, 50 or more 15% off. Round each line total to the cent (half-up). "
  "Write totals.csv with header customer,total (sum of that customer's line totals, 2 decimals), sorted by customer name." + SUFFIX,
  {"orders.csv": _tord, "price_list.csv": _tpl}, _chk_tiers)

def _bankrec():
    r = random.Random(605); bank = []; ledger = []; d0 = date(2026, 9, 1); um = set(); n = 0
    for i in range(30):
        amt = "%.2f" % (r.randrange(1000, 300000) / 100); d = d0 + timedelta(days=r.randrange(28)); n += 1
        bank.append(("BK%03d" % n, d, amt)); ledger.append(("LG%03d" % n, d + timedelta(days=r.randrange(-3, 4)), amt))
    bank.append(("BK901", date(2026, 9, 3), "250.00")); ledger.append(("LG901", date(2026, 9, 4), "250.00"))
    bank.append(("BK902", date(2026, 9, 20), "250.00")); ledger.append(("LG902", date(2026, 9, 21), "250.00"))
    bank.append(("BK950", date(2026, 9, 10), "88.80")); ledger.append(("LG950", date(2026, 9, 16), "88.80")); um |= {("bank", "BK950"), ("ledger", "LG950")}
    bank.append(("BK960", date(2026, 9, 12), "1234.56")); um.add(("bank", "BK960"))
    ledger.append(("LG970", date(2026, 9, 14), "77.00")); um.add(("ledger", "LG970"))
    ledger.append(("LG971", date(2026, 9, 15), "1234.65")); um.add(("ledger", "LG971"))
    amts = [b[2] for b in bank]; assert len(set(amts)) == len(amts) - 1
    r.shuffle(bank); r.shuffle(ledger)
    bt = "id,date,amount,description\n" + "".join("%s,%s,%s,EFT %s\n" % (i, d.isoformat(), a, i[-3:]) for i, d, a in bank)
    lt = "id,date,amount,reference\n" + "".join("%s,%s,%s,REF-%s\n" % (i, d.isoformat(), a, i[-3:]) for i, d, a in ledger)
    return bt, lt, [["source", "id"]] + sorted([list(x) for x in um])
_bt, _lt, _bw = _bankrec()
def _chk_rec(ws):
    got = [x for x in (read_csv(ws, "unmatched.csv") or []) if x]
    return got == _bw, "" if got == _bw else "unmatched.csv=%s expected %s" % (got[:8], _bw)
T("biz-bank-rec", "business",
  "Reconcile bank.csv against ledger.csv. A bank row matches a ledger row when the amounts are exactly equal and the dates are at most 3 days apart; each row can match at most once (prefer the closest date). "
  "Write unmatched.csv with header source,id listing every unmatched row (source is 'bank' or 'ledger'), sorted by source then id." + SUFFIX,
  {"bank.csv": _bt, "ledger.csv": _lt}, _chk_rec)

def _payroll():
    r = random.Random(606); emps = {"Ava": "31.50", "Ben": "28.75", "Chloe": "35.00", "Dev": "27.10", "Eve": "42.25"}
    rows = ["employee,date,hours"]; hrs = {e: Decimal(0) for e in emps}
    for e in emps:
        for d in range(5, 12):
            if r.random() < 0.8:
                h = Decimal(r.choice(["4", "6.5", "7.6", "8", "9.5", "10", "11.25"])); hrs[e] += h
                rows.append("%s,2026-10-%02d,%s" % (e, d, h))
    hrs["Dev"] = sum(Decimal(x.split(",")[2]) for x in rows[1:] if x.startswith("Dev,"))
    want = [["employee", "ordinary_hours", "overtime_hours", "gross"]]
    for e in sorted(emps):
        o = min(hrs[e], Decimal(38)); ot = max(hrs[e] - 38, Decimal(0)); g = cents(o * Decimal(emps[e]) + ot * Decimal(emps[e]) * Decimal("1.5"))
        want.append([e, o, ot, g])
    return "\n".join(rows) + "\n", "employee,hourly_rate\n" + "".join("%s,%s\n" % kv for kv in emps.items()), want
_ts, _rates, _payw = _payroll()
def _chk_pay(ws):
    got = [x for x in (read_csv(ws, "pay.csv") or []) if x]
    if len(got) != len(_payw) or [c.strip() for c in got[0]] != _payw[0]: return False, "pay.csv header/shape wrong: %s" % got[:1]
    for g, w in zip(got[1:], _payw[1:]):
        try:
            ok = g[0] == w[0] and Decimal(g[1]) == w[1] and Decimal(g[2]) == w[2] and _dec_eq(g[3], w[3])
        except Exception: ok = False
        if not ok: return False, "row %s expected %s" % (g, [str(x) for x in w])
    return True, ""
T("biz-payroll-ot", "business",
  "Using timesheets.csv (one week) and rates.csv, compute weekly pay: the first 38 hours of the week are ordinary time at the hourly rate, every hour above 38 is overtime at 1.5x the rate. "
  "Write pay.csv with header employee,ordinary_hours,overtime_hours,gross sorted by employee; gross rounded to the cent (half-up) with 2 decimals." + SUFFIX,
  {"timesheets.csv": _ts, "rates.csv": _rates}, _chk_pay)

def _aging():
    r = random.Random(607); asof = date(2026, 10, 9); rows = ["invoice,customer,due_date,amount,paid"]; b = {k: Decimal(0) for k in ["current", "1-30", "31-60", "61-90", "90+"]}
    fixed = [0, 1, 30, 31, 60, 61, 90, 91, -5]
    for i in range(45):
        od = fixed[i] if i < len(fixed) else r.randrange(-30, 150); due = asof - timedelta(days=od); amt = Decimal(r.randrange(5000, 400000)) / 100; paid = r.random() < 0.3 and i >= len(fixed)
        rows.append("INV%04d,C%02d,%s,%.2f,%s" % (i, r.randrange(20), due.isoformat(), amt, "yes" if paid else "no"))
        if not paid:
            k = "current" if od <= 0 else "1-30" if od <= 30 else "31-60" if od <= 60 else "61-90" if od <= 90 else "90+"; b[k] += amt
    return "\n".join(rows) + "\n", b
_ag, _agw = _aging()
def _chk_aging(ws):
    try: g = json.loads(rd(ws, "aging.json"))
    except Exception as e: return False, "aging.json unreadable: %s" % e
    for k, v in _agw.items():
        if k not in g or not _dec_eq(g[k], v): return False, "%s=%r expected %s" % (k, g.get(k), v)
    return True, ""
T("biz-aged-receivables", "business",
  "From invoices.csv, build an aged receivables summary as of 2026-10-09 for UNPAID invoices only. days_overdue = 2026-10-09 minus due_date. Buckets: 'current' (days_overdue <= 0), '1-30', '31-60', '61-90', '90+' (more than 90). "
  "Write aging.json mapping each of those five bucket names to the total amount as a string with 2 decimals (include empty buckets as \"0.00\")." + SUFFIX, {"invoices.csv": _ag}, _chk_aging)

def _prices():
    r = random.Random(608); rows = [["sku", "category", "price"]]; want = {}
    fixed = ["3.00", "10.00", "7.10", "12.30"]
    for i in range(24):
        cat = "syrup" if i < 4 or r.random() < 0.4 else r.choice(["cups", "machines", "lids"]); p = fixed[i] if i < 4 else "%.2f" % (r.randrange(50, 30000) / 100)
        rows.append(["P%03d" % i, cat, p])
        if cat == "syrup":
            x = Decimal(p) * Decimal("1.075"); want["P%03d" % i] = ((x / Decimal("0.05")).quantize(Decimal(1), ROUND_HALF_UP) * Decimal("0.05")).quantize(D2)
        else: want["P%03d" % i] = Decimal(p)
    buf = io.StringIO(); csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue(), rows, want
_pc, _prow, _pw = _prices()
def _chk_prices(ws):
    got = [x for x in (read_csv(ws, "prices_new.csv") or []) if x]
    if len(got) != len(_prow) or got[0] != _prow[0]: return False, "prices_new.csv shape/header wrong"
    for g, o in zip(got[1:], _prow[1:]):
        if g[0] != o[0] or g[1] != o[1] or not _dec_eq(g[2], _pw[o[0]]): return False, "row %s expected price %s" % (g, _pw[o[0]])
    return True, ""
T("biz-price-update", "business",
  "Create prices_new.csv from prices.csv: increase the price of every 'syrup' category item by 7.5% and round to the nearest 5 cents (exact halves round up); other categories keep their price. "
  "Same columns and row order, prices with 2 decimals. Do not modify prices.csv." + SUFFIX, {"prices.csv": _pc}, all_of(unchanged("prices.csv", _pc), _chk_prices))

_rates_q = {"machines": {"double": "120.00", "triple": "165.00", "single": "85.00"}, "delivery": {"metro": "60.00", "regional": "150.00"}, "weekend_surcharge_pct": 10, "gst_pct": 10}
_req_q = {"customer": "Gosford Show Society", "machines": [{"type": "double", "qty": 2}, {"type": "triple", "qty": 1}, {"type": "single", "qty": 3}],
          "dates": ["2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"], "zone": "regional"}
def _quote():
    day = sum(Decimal(_rates_q["machines"][m["type"]]) * m["qty"] for m in _req_q["machines"]); hire = Decimal(0)
    for d in _req_q["dates"]:
        hire += day * (Decimal("1.10") if date.fromisoformat(d).weekday() >= 5 else 1)
    hire = cents(hire); dl = Decimal(_rates_q["delivery"][_req_q["zone"]]); gst = cents((hire + dl) * Decimal("0.10"))
    return {"hire_ex": hire, "delivery_ex": dl, "gst": gst, "total": hire + dl + gst}
_qw = _quote()
def _chk_quote(ws):
    try: g = json.loads(rd(ws, "quote.json"))
    except Exception as e: return False, "quote.json unreadable: %s" % e
    for k, v in _qw.items():
        if k not in g or not _dec_eq(g[k], v): return False, "%s=%r expected %s" % (k, g.get(k), v)
    return True, ""
T("biz-hire-quote", "business",
  "Build a hire quote from rates.json and request.json. Daily hire = sum of qty * machine daily rate; each hire date that falls on a Saturday or Sunday costs the daily hire plus the weekend surcharge percentage. "
  "hire_ex = total over all dates (rounded to cents); delivery_ex = the zone's delivery fee, charged once; gst = 10% of (hire_ex + delivery_ex) rounded half-up; total = hire_ex + delivery_ex + gst. "
  "Write quote.json with keys hire_ex, delivery_ex, gst, total as strings with 2 decimals." + SUFFIX,
  {"rates.json": json.dumps(_rates_q, indent=2), "request.json": json.dumps(_req_q, indent=2)}, _chk_quote)

def _sales():
    r = random.Random(610); rows = ["date,product,qty,unit_price"]; agg = {}
    for i in range(300):
        d = date(2026, 1, 1) + timedelta(days=r.randrange(270)); p = r.choice(["Blue Raspberry", "Cola", "Mango", "Cherry"]); q = r.randrange(1, 30); u = r.choice(["4.50", "5.00", "5.50", "3.95"])
        rows.append("%s,%s,%d,%s" % (d.isoformat(), p, q, u)); k = (d.strftime("%Y-%m"), p); agg[k] = agg.get(k, Decimal(0)) + Decimal(u) * q
    return "\n".join(rows) + "\n", [["month", "product", "revenue"]] + [[m, p, "%.2f" % agg[(m, p)]] for m, p in sorted(agg)]
_sl, _slw = _sales()
def _chk_sales(ws):
    got = [x for x in (read_csv(ws, "summary.csv") or []) if x]
    if len(got) != len(_slw) or got[0] != _slw[0]: return False, "summary.csv shape/header wrong (%d rows vs %d)" % (len(got), len(_slw))
    for g, w in zip(got[1:], _slw[1:]):
        if g[:2] != w[:2] or not _dec_eq(g[2], w[2]): return False, "row %s expected %s" % (g, w)
    return True, ""
T("biz-monthly-sales", "business",
  "From sales.csv compute revenue (qty * unit_price) per month and product. Write summary.csv with header month,product,revenue where month is YYYY-MM, sorted by month then product, revenue with 2 decimals." + SUFFIX,
  {"sales.csv": _sl}, _chk_sales)

# ---------------- G. ERROR RECOVERY (10): broken environment / wrong instructions the agent must recover from ----------------
_regions = {"Sydney": ["120.50", "99.95", "310.00"], "Central Coast": ["45.00", "60.25"], "Illawarra": ["220.10", "12.90", "8.00"]}
_salesdata = "region,amount\n" + "".join("%s,%s\n" % (k, a) for k, v in _regions.items() for a in v)
_report_py = ("import csv\nfrom snowutils.fmt import money_table\n\ntotals = {}\nwith open('sales.csv', encoding='utf-8') as f:\n    for row in csv.DictReader(f):\n"
              "        totals[row['region']] = totals.get(row['region'], 0) + float(row['amount'])\n\nwith open('report.txt', 'w', encoding='utf-8') as out:\n"
              "    out.write(money_table(sorted(totals.items())))\n")
def _chk_report(ws):
    src = rd(ws, "report.py") or ""
    if re.search(r"^\s*(from|import)\s+snowutils", src, re.M): return False, "report.py still imports snowutils"
    try: os.remove(os.path.join(ws, "report.txt"))
    except Exception: pass
    try: p = run_py(ws, ["report.py"], timeout=60)
    except subprocess.TimeoutExpired: return False, "report.py timed out"
    out = rd(ws, "report.txt")
    if p.returncode != 0 or not out: return False, "report.py failed on re-run: " + p.stderr[-200:]
    for k, v in _regions.items():
        t = "%.2f" % sum(Decimal(x) for x in v)
        if not re.search(re.escape(k) + r"\D*?(?<![\d.])" + re.escape(t) + r"(?![\d])", out.replace(",", "")): return False, "report.txt missing %s %s" % (k, t)
    return True, ""
T("recover-missing-module", "recovery", "Run report.py to produce report.txt. The internal snowutils package is NOT available on this machine and must not be installed; make report.py work using only the Python standard library. "
  "report.txt should list each region with its total formatted with 2 decimals." + SUFFIX, {"report.py": _report_py, "sales.csv": _salesdata}, _chk_report)

_s26 = "date,amount\n" + "".join("2026-%02d-%02d,%.2f\n" % (1 + i % 9, 1 + i % 28, 10 + i * 3.17) for i in range(40))
_s26tot = sum(Decimal("%.2f" % (10 + i * 3.17)) for i in range(40))
T("recover-wrong-path", "recovery", "Total the amount column of data/sales_2026.csv." + ANS, {"data/2026/sales.csv": _s26, "data/README.txt": "Sales exports are organised by year.\n"}, answer_num(_s26tot))

_nums = "\n".join(str(x) for x in [12, 7.5, 33, 41, 2.25, 19, 8, 27.5]) + "\n"
_stats_py = "import sys, statistics\nvals = [float(l) for l in open(sys.argv[1]) if l.strip()]\nprint('%.3f' % statistics.mean(vals))\n"
T("recover-typo-command", "recovery", "Run `python stat.py numbers.txt` and report the number it prints." + ANS, {"stats.py": _stats_py, "numbers.txt": _nums},
  answer_num("%.3f" % (sum([12, 7.5, 33, 41, 2.25, 19, 8, 27.5]) / 8)))

_settings_bad = '{\n  // pricing settings\n  "threshold": 37.5,\n  "currency": "AUD",\n  "tiers": [10, 50, 100,],\n  "gst": true,\n}\n'
_settings_want = {"threshold": 37.5, "currency": "AUD", "tiers": [10, 50, 100], "gst": True}
def _chk_settings(ws):
    try: g = json.loads(rd(ws, "settings.json"))
    except Exception as e: return False, "settings.json still invalid: %s" % e
    return g == _settings_want, "" if g == _settings_want else "settings.json content changed: %s" % g
T("recover-bad-json", "recovery", "settings.json fails to load with Python's json module. Fix it so it is valid JSON without losing any setting, then write the value of threshold to answer.txt (just the number)." + SUFFIX,
  {"settings.json": _settings_bad}, all_of(_chk_settings, answer_num("37.5")))

_twobug = ("def parse_qty(s):\n    \"\"\"'12 x' -> 12 ; '  7' -> 7\"\"\"\n    return int(s.strip().split()[1])\n\n"
           "def line_total(qty, price):\n    \"\"\"Total in cents (int) for qty items at price dollars (str like '2.35').\"\"\"\n    return qty * int(float(price) * 100)\n")
_twotest = "from orderline import parse_qty, line_total\n\ndef test_parse():\n    assert parse_qty('12 x') == 12 and parse_qty('  7') == 7\n\ndef test_total():\n    assert line_total(3, '2.35') == 705\n    assert line_total(1, '4.10') == 410\n"
T("recover-two-bugs", "recovery", "test_orderline.py fails. Fix orderline.py (not the tests) until all tests pass." + SUFFIX, {"orderline.py": _twobug, "test_orderline.py": _twotest},
  all_of(unchanged("test_orderline.py", _twotest), hidden(_twotest + "\ndef test_more():\n    assert line_total(7, '0.29') == 203 and line_total(2, '19.99') == 3998 and parse_qty('3') == 3\n")))

_app_py = ("import os, sys\nmode = os.environ.get('APP_MODE')\nif mode not in ('offline', 'live'):\n    sys.exit(\"error: set the APP_MODE environment variable to 'offline' or 'live'\")\n"
           "items = 42 if mode == 'offline' else 0\nopen('out.txt', 'w', encoding='utf-8').write('mode=%s items=%d\\n' % (mode, items))\nprint('wrote out.txt')\n")
def _chk_env(ws):
    o = (rd(ws, "out.txt") or "").strip()
    if o != "mode=offline items=42": return False, "out.txt=%r" % o
    try: os.remove(os.path.join(ws, "out.txt"))  # prove app.py itself produces it (a hand-written out.txt must not pass)
    except Exception: pass
    p = run_py(ws, ["app.py"], env={"APP_MODE": "offline"})
    o2 = (rd(ws, "out.txt") or "").strip()
    return o2 == "mode=offline items=42", "" if o2 == "mode=offline items=42" else "app.py re-run gave out.txt=%r rc=%s" % (o2, p.returncode)
T("recover-env-var", "recovery", "Run app.py to generate out.txt for offline use. Do not modify app.py." + SUFFIX, {"app.py": _app_py}, all_of(unchanged("app.py", _app_py), _chk_env))

_menu = "Crème brûlée sundae;12.50\nMango ☀ splash;9.00\nCafé frappé;10.50\nKids cola;4.00\nPiña colada (NA);11.00\n"
_menu_py = ("rows = [l.strip().split(';') for l in open('menu.txt') if l.strip()]\nwith open('menu_out.txt', 'w') as f:\n    for name, price in rows:\n"
            "        if float(price) > 10:\n            f.write(name.upper() + '\\n')\nprint('done')\n")
_menu_want = "CRÈME BRÛLÉE SUNDAE\nCAFÉ FRAPPÉ\nPIÑA COLADA (NA)\n"
def _chk_menu(ws):
    try: os.remove(os.path.join(ws, "menu_out.txt"))
    except Exception: pass
    try: p = run_py(ws, ["menu.py"], timeout=60, env={"PYTHONUTF8": "0", "PYTHONIOENCODING": ""})
    except subprocess.TimeoutExpired: return False, "menu.py timed out"
    got = (rdb(ws, "menu_out.txt") or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")  # strict UTF-8 on purpose: output left in cp1252 is the bug this task tests
    return got == _menu_want, "" if got == _menu_want else "menu_out.txt (re-run) = %r rc=%s %s" % (got[:120], p.returncode, p.stderr[-150:])
T("recover-encoding", "recovery", "menu.py should write the names of items priced over $10 in UPPERCASE to menu_out.txt, but the output comes out garbled on this Windows PC. Fix menu.py so it works correctly "
  "regardless of the system's default encoding, then run it." + SUFFIX, {"menu.txt": _menu, "menu.py": _menu_py}, _chk_menu)

_export_py = ("import csv\nrows = [['sku', 'qty'], ['A1', '5'], ['B2', '0'], ['C3', '12']]\nwith open('out/report.csv', 'w', newline='', encoding='utf-8') as f:\n"
              "    csv.writer(f).writerows(rows)\nprint('exported')\n")
def _chk_export(ws):
    shutil.rmtree(os.path.join(ws, "out"), ignore_errors=True)
    try: p = run_py(ws, ["export.py"], timeout=60)
    except subprocess.TimeoutExpired: return False, "export.py timed out"
    rows = [x for x in (read_csv(ws, "out/report.csv") or []) if x]
    ok = p.returncode == 0 and rows == [["sku", "qty"], ["A1", "5"], ["B2", "0"], ["C3", "12"]]
    return ok, "" if ok else "fresh run failed rc=%s rows=%s %s" % (p.returncode, rows, p.stderr[-150:])
T("recover-missing-dir", "recovery", "export.py crashes. Fix it so it also works on a fresh checkout where the out/ folder does not exist yet, then run it." + SUFFIX, {"export.py": _export_py}, _chk_export)

_inp = "apple 3\n\nbanana 5\n# comment\ncherry 2\n\n\nmango 10\n"
_proc_py = ("lines = open('input.txt', encoding='utf-8').read().split('\\n')\ntotal = 0\ni = 0\nwhile i < len(lines):\n    line = lines[i].strip()\n"
            "    if not line or line.startswith('#'):\n        continue\n    name, qty = line.split()\n    total += int(qty)\n    i += 1\n"
            "open('result.txt', 'w', encoding='utf-8').write('total=%d\\n' % total)\n")
def _chk_proc(ws):
    try: os.remove(os.path.join(ws, "result.txt"))
    except Exception: pass
    try: run_py(ws, ["process.py"], timeout=20)
    except subprocess.TimeoutExpired: return False, "process.py still hangs"
    got = (rd(ws, "result.txt") or "").strip()
    return got == "total=20", "" if got == "total=20" else "result.txt=%r" % got
T("recover-infinite-loop", "recovery", "process.py never finishes on input.txt. Fix it and produce result.txt." + SUFFIX, {"process.py": _proc_py, "input.txt": _inp}, _chk_proc, timeout=480)

_a_py = "from b import fmt\n\ndef helper(x):\n    return x * 2\n\ndef run(vals):\n    return fmt(sum(helper(v) for v in vals))\n"
_b_py = "from a import helper\n\ndef fmt(n):\n    return 'TOTAL %d (helper check %d)' % (n, helper(1))\n"
_main_py = "import a\nprint(a.run([1, 2, 3, 4]))\n"
def _chk_circ(ws):
    try: p = run_py(ws, ["main.py"], timeout=30)
    except subprocess.TimeoutExpired: return False, "main.py timed out"
    want = "TOTAL 20 (helper check 2)"
    if p.stdout.strip() != want: return False, "main.py prints %r rc=%s %s" % (p.stdout.strip()[:80], p.returncode, p.stderr[-150:])
    return answer_is(want)(ws)
T("recover-circular-import", "recovery", "python main.py fails with an import error. Fix the code so main.py runs, then write the exact line it prints to answer.txt." + SUFFIX,
  {"a.py": _a_py, "b.py": _b_py, "main.py": _main_py}, _chk_circ)

assert len(TASKS) == 100, len(TASKS)
assert len({t["id"] for t in TASKS}) == 100
CATS = ["coding", "debugging", "tool", "fileops", "longctx", "business", "recovery"]
