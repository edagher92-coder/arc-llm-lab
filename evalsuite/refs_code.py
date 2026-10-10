# Reference solutions for selftest only (never shown to agents).
CODE = {}
CODE["merge_intervals"] = '''
def merge_intervals(iv):
    out = []
    for a in iv:
        if len(a) != 2 or not all(type(x) is int for x in a) or a[0] >= a[1]: raise ValueError(a)
    for s, e in sorted([list(a) for a in iv]):
        if out and s <= out[-1][1]: out[-1][1] = max(out[-1][1], e)
        else: out.append([s, e])
    return out
'''
CODE["lru"] = '''
from collections import OrderedDict
class LRUCache:
    def __init__(self, c): self.c = c; self.d = OrderedDict()
    def get(self, k):
        if k not in self.d: return -1
        self.d.move_to_end(k); return self.d[k]
    def put(self, k, v):
        self.d[k] = v; self.d.move_to_end(k)
        if len(self.d) > self.c: self.d.popitem(last=False)
'''
CODE["abn"] = '''
def is_valid_abn(a):
    a = a.replace(" ", "")
    if len(a) != 11 or not a.isdigit(): return False
    d = [int(c) for c in a]; d[0] -= 1
    return sum(x * w for x, w in zip(d, [10,1,3,5,7,9,11,13,15,17,19])) % 89 == 0
'''
CODE["gst"] = '''
from decimal import Decimal, ROUND_HALF_UP
def gst_breakdown(t):
    q = Decimal("0.01"); g = (t / 11).quantize(q, ROUND_HALF_UP); return ((t - g).quantize(q), g)
'''
CODE["bizdays"] = '''
import datetime
def business_days(s, e, holidays=()):
    n = 0; h = set(holidays)
    while s <= e:
        if s.weekday() < 5 and s not in h: n += 1
        s += datetime.timedelta(days=1)
    return n
'''
CODE["duration"] = '''
import re
def parse_duration(s):
    t = s.replace(" ", "")
    if not t or not re.fullmatch(r"(\\d+[hms])+", t): raise ValueError(s)
    return sum(int(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in re.findall(r"(\\d+)([hms])", t))
'''
CODE["rle"] = '''
import re, itertools
def rle_encode(s): return "".join("%d%s" % (len(list(g)), k) for k, g in itertools.groupby(s))
def rle_decode(s): return "".join(c * int(n) for n, c in re.findall(r"(\\d+)(\\D)", s))
'''
CODE["semver"] = '''
def compare_semver(a, b):
    def k(v):
        main, _, pre = v.partition("-"); p = [int(x) for x in main.split(".")]; p += [0] * (3 - len(p))
        return (p, 0 if pre else 1, pre)
    x, y = k(a), k(b); return (x > y) - (x < y)
'''
CODE["jsonpath"] = '''
import re
def get_path(o, path, default=None):
    for name, idx in re.findall(r"([^.\\[\\]]+)|\\[(\\d+)\\]", path):
        try: o = o[int(idx)] if idx else o[name]
        except (KeyError, IndexError, TypeError): return default
    return o
'''
CODE["wrap"] = '''
def wrap_text(t, w):
    lines = []; cur = ""
    for word in t.split():
        if not cur: cur = word
        elif len(cur) + 1 + len(word) <= w: cur += " " + word
        else: lines.append(cur); cur = word
    if cur: lines.append(cur)
    return lines
'''
CODE["spiral"] = '''
def spiral(m):
    m = [r[:] for r in m]; out = []
    while m:
        out += m.pop(0); m = [list(r) for r in zip(*m)][::-1]
    return out
'''
CODE["dedupe"] = '''
def dedupe(items, key=None):
    seen = []; out = []
    for x in items:
        k = key(x) if key else x
        if k not in seen: seen.append(k); out.append(x)
    return out
'''
CODE["email"] = '''
import re
def is_valid_email(s):
    if s.count("@") != 1: return False
    l, d = s.split("@")
    if not l or " " in l or "." not in d: return False
    labels = d.split(".")
    if not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", x) for x in labels): return False
    return re.fullmatch(r"[A-Za-z]{2,}", labels[-1]) is not None
'''
CODE["topk"] = '''
from collections import Counter
def top_k_frequent(w, k): c = Counter(w); return sorted(c, key=lambda x: (-c[x], x))[:k]
'''
CODE["roman"] = '''
V = [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
def int_to_roman(n):
    s = ""
    for v, r in V:
        while n >= v: s += r; n -= v
    return s
def roman_to_int(s):
    m = {"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}; t = 0
    for i, c in enumerate(s):
        t += -m[c] if i + 1 < len(s) and m[s[i+1]] > m[c] else m[c]
    return t
'''
CODE["money"] = '''
from decimal import Decimal
def split_amount(total, n):
    if n < 1: raise ValueError(n)
    c = int((total * 100).to_integral_value()); b, r = divmod(c, n)
    return [Decimal(b + (1 if i < r else 0)) / 100 for i in range(n)]
'''
CODE["csvparse"] = '''
def parse_csv_line(line):
    out = []; cur = ""; q = False; i = 0
    while i < len(line):
        ch = line[i]
        if q:
            if ch == '"' and i + 1 < len(line) and line[i+1] == '"': cur += '"'; i += 1
            elif ch == '"': q = False
            else: cur += ch
        elif ch == '"': q = True
        elif ch == ",": out.append(cur); cur = ""
        else: cur += ch
        i += 1
    out.append(cur); return out
'''
CODE["flatten"] = '''
def flatten_json(o, p=""):
    out = {}
    items = o.items() if isinstance(o, dict) else enumerate(o)
    for k, v in items:
        key = "%s.%s" % (p, k) if p else str(k)
        if isinstance(v, (dict, list)) and v: out.update(flatten_json(v, key))
        else: out[key] = v
    return out
'''
CODE["tokenbucket"] = '''
import time
class TokenBucket:
    def __init__(self, cap, rate, clock=time.monotonic): self.cap = cap; self.rate = rate; self.clock = clock; self.t = clock(); self.tok = cap
    def allow(self, cost=1):
        now = self.clock(); self.tok = min(self.cap, self.tok + (now - self.t) * self.rate); self.t = now
        if self.tok >= cost: self.tok -= cost; return True
        return False
'''
CODE["postcode"] = '''
def nsw_region(p):
    try: n = int(str(p).strip())
    except ValueError: return "Other"
    if 2600 <= n <= 2618 or 2900 <= n <= 2920: return "ACT"
    if 2000 <= n <= 2234: return "Sydney Metro"
    if 2235 <= n <= 2999: return "Regional NSW"
    return "Other"
'''
