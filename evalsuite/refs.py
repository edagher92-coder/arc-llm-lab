# Independent reference solutions: compute answers from the workspace files (not from generator internals).
import os, re, json, csv, io, hashlib, zipfile, subprocess, sys, shutil, glob
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta
from refs_code import CODE
PY = sys.executable
def W(ws, rel, s, mode="w"):
    p = os.path.join(ws, rel); os.makedirs(os.path.dirname(p) or ws, exist_ok=True)
    if isinstance(s, bytes): open(p, "wb").write(s)
    else: open(p, "w", encoding="utf-8", newline="").write(s)
def R(ws, rel): return open(os.path.join(ws, rel), encoding="utf-8").read()
def A(ws, v): W(ws, "answer.txt", str(v) + "\n")
def C(x): return Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)
def rows(ws, rel): return list(csv.DictReader(io.StringIO(R(ws, rel))))
def wcsv(ws, rel, rs): b = io.StringIO(); csv.writer(b, lineterminator="\n").writerows(rs); W(ws, rel, b.getvalue())
S = {}
for k, v in CODE.items(): S["code-" + k] = (lambda src: lambda ws: W(ws, "solution.py", src))(v)

FIX = {
 "pager": ("start = page * size", "start = (page - 1) * size"),
 "tags": ("def add_tag(tag, tags=[]):\n", "def add_tag(tag, tags=None):\n    tags = [] if tags is None else tags\n"),
 "stats": ("//", "/"),
 "audate": ("%m/%d/%Y", "%d/%m/%Y"),
 "versions": ("return sorted(vs)", "return sorted(vs, key=lambda v: [int(x) for x in v.split('.')])"),
 "cleanup": ("for k in d:", "for k in list(d):"),
 "bsearch": ("hi = mid - 1", "hi = mid"),
 "htmlbits": ("(.*)", "(.*?)"),
 "fact": ("if n == 1:", "if n <= 1:"),
 "mults": ("lambda x: x * i", "lambda x, i=i: x * i"),
 "grid": ("return list(grid)", "return [list(r) for r in grid]"),
 "config": ("except Exception:", "except FileNotFoundError:"),
 "weekend": ("d.weekday() == 5 and d.weekday() == 6", "d.weekday() >= 5"),
 "pricing": ("    p = p * Decimal('1.1')\n    p = p - p", "    p = p - p"),
 "words": ("for w in text.split():", "for w in text.lower().translate(str.maketrans('', '', '.,!?;:')).split():"),
 "fibo": ("_cache[n - 1] = r", "_cache[n] = r"),
 "csvout": ("open(path, 'w')", "open(path, 'w', newline='', encoding='utf-8')"),
 "chunks": ("len(lst) - n + 1", "len(lst)"),
 "prefix": ("return s.lstrip(prefix)", "return s[len(prefix):] if s.startswith(prefix) else s"),
 "matches": ("x is target", "x == target"),
}
for k, (a, b) in FIX.items():
    def f(ws, k=k, a=a, b=b):
        s = R(ws, k + ".py"); assert a in s, k; W(ws, k + ".py", s.replace(a, b, 1))
    S["debug-" + k] = f

S["tool-log-errors"] = lambda ws: A(ws, sum(1 for l in R(ws, "logs/app.log").splitlines() if " [ERROR] " in l))
S["tool-sha256"] = lambda ws: A(ws, hashlib.sha256(open(os.path.join(ws, "data/blob.bin"), "rb").read()).hexdigest())
S["tool-count-py"] = lambda ws: A(ws, len(glob.glob(os.path.join(ws, "src/**/*.py"), recursive=True)))
def _pt(ws):
    p = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=ws, capture_output=True, text=True)
    A(ws, re.search(r"(\d+) failed", p.stdout).group(1))
S["tool-pytest-count"] = _pt
S["tool-git-log"] = lambda ws: A(ws, len(subprocess.run(["git", "log", "--format=%H", "--", "config.yaml"], cwd=ws, capture_output=True, text=True).stdout.split()))
def _gb(ws):
    g = lambda *a: subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@x"] + list(a), cwd=ws, check=True, capture_output=True)
    g("checkout", "-q", "-b", "fix/readme-typo"); W(ws, "README.md", R(ws, "README.md").replace("Snowflwo", "FrostLine")); g("commit", "-qam", "Fix README typo"); g("checkout", "-q", "main")
S["tool-git-branch"] = _gb
S["tool-largest"] = lambda ws: A(ws, max((f for f in os.listdir(os.path.join(ws, "assets")) if os.path.isfile(os.path.join(ws, "assets", f))), key=lambda f: os.path.getsize(os.path.join(ws, "assets", f))))
def _ip(ws):
    from collections import Counter
    A(ws, Counter(l.split()[0] for l in R(ws, "logs/access.log").splitlines()).most_common(1)[0][0])
S["tool-top-ip"] = _ip
S["tool-unique-suburbs"] = lambda ws: A(ws, len({r["suburb"] for r in rows(ws, "customers.csv")}))
S["tool-find-config"] = lambda ws: A(ws, [f for f in os.listdir(os.path.join(ws, "configs")) if re.search(r"^\s+port: 8443$", R(ws, "configs/" + f), re.M)][0])
S["tool-json-sum"] = lambda ws: A(ws, "%.2f" % sum(Decimal(str(o["amount"])) for o in json.loads(R(ws, "orders.json"))["orders"] if o["status"] == "paid"))
S["tool-run-script"] = lambda ws: A(ws, subprocess.run([PY, "calc.py", "--mode", "fast", "17"], cwd=ws, capture_output=True, text=True).stdout.strip())
S["tool-line-number"] = lambda ws: A(ws, [i for i, l in enumerate(R(ws, "lib.py").splitlines(), 1) if l.startswith("def reconcile(")][0])
S["tool-word-count"] = lambda ws: A(ws, sum(len(R(ws, "docs/" + f).split()) for f in os.listdir(os.path.join(ws, "docs")) if f.endswith(".md")))
def _zip(ws):
    with zipfile.ZipFile(os.path.join(ws, "backup.zip"), "w") as z:
        for f in glob.glob(os.path.join(ws, "notes", "*.txt")): z.write(f, os.path.basename(f))
S["tool-zip"] = _zip

def _ren(ws):
    for f in glob.glob(os.path.join(ws, "images", "*.jpeg")): os.rename(f, f[:-5] + ".jpg")
S["files-rename-ext"] = _ren
def _org(ws):
    d = os.path.join(ws, "downloads")
    for f in os.listdir(d):
        e = f.rsplit(".", 1)[-1].lower(); sub = "pdf" if e == "pdf" else "csv" if e == "csv" else "images" if e in ("jpg", "jpeg", "png") else "other"
        os.makedirs(os.path.join(d, sub), exist_ok=True); shutil.move(os.path.join(d, f), os.path.join(d, sub, f))
S["files-organise"] = _org
def _bump(ws):
    for f, a, b in [("pyproject.toml", 'version = "1.4.2"', 'version = "1.5.0"'), ("package.json", '"version": "1.4.2"', '"version": "1.5.0"'), ("app/__init__.py", '"1.4.2"', '"1.5.0"')]:
        W(ws, f, R(ws, f).replace(a, b))
S["files-version-bump"] = _bump
S["files-csv-to-json"] = lambda ws: W(ws, "products.json", json.dumps([{"sku": r["sku"], "name": r["name"], "price": float(r["price"]), "qty": int(r["qty"])} for r in rows(ws, "products.csv")]))
S["files-json-to-csv"] = lambda ws: wcsv(ws, "inventory.csv", [["sku", "name", "qty"]] + [[i["sku"], i["name"], i["qty"]] for i in sorted(json.loads(R(ws, "inventory.json"))["items"], key=lambda i: i["sku"])])
def _merge(ws):
    def m(a, b):
        for k, v in b.items(): a[k] = m(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
        return a
    W(ws, "merged.json", json.dumps(m(json.loads(R(ws, "base.json")), json.loads(R(ws, "override.json")))))
S["files-config-merge"] = _merge
def _rf(ws):
    for f in glob.glob(os.path.join(ws, "**", "*.py"), recursive=True):
        s = open(f, encoding="utf-8").read(); open(f, "w", encoding="utf-8").write(re.sub(r"\bcalc_total\b", "calculate_total", s))
S["files-refactor-rename"] = _rf
def _dd(ws):
    rs = list(csv.reader(io.StringIO(R(ws, "contacts.csv")))); seen = set(); out = [rs[0]]
    for r in rs[1:]:
        if r and r[1].lower() not in seen: seen.add(r[1].lower()); out.append(r)
    wcsv(ws, "contacts_clean.csv", out)
S["files-dedupe-csv"] = _dd
def _lic(ws):
    H = "# Copyright (c) 2026 FrostLine Hire"
    for f in glob.glob(os.path.join(ws, "src", "**", "*.py"), recursive=True):
        s = open(f, encoding="utf-8").read()
        if not s.startswith(H): open(f, "w", encoding="utf-8", newline="").write(H + "\n" + s)
S["files-license-header"] = _lic
def _em(ws):
    found = set()
    for f in glob.glob(os.path.join(ws, "inbox", "*.txt")):
        for e in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", open(f, encoding="utf-8").read()): found.add(e.lower().rstrip("."))
    W(ws, "emails.txt", "\n".join(sorted(found)) + "\n")
S["files-extract-emails"] = _em
S["files-env-example"] = lambda ws: W(ws, ".env.example", "".join((l.split("=", 1)[0] + "=\n") if "=" in l and not l.startswith("#") else l + "\n" for l in R(ws, ".env").split("\n")[:-1]))
def _split(ws):
    ls = R(ws, "big.csv").splitlines(); h, d = ls[0], ls[1:]
    for k in range(0, len(d), 100): W(ws, "parts/part_%d.csv" % (k // 100 + 1), "\n".join([h] + d[k:k + 100]) + "\n")
S["files-split-csv"] = _split
def _tabs(ws):
    for f in glob.glob(os.path.join(ws, "**", "*.py"), recursive=True):
        if os.sep + "vendor" + os.sep in f: continue
        s = open(f, encoding="utf-8").read(); open(f, "w", encoding="utf-8", newline="").write(s.replace("\t", "    "))
S["files-tabs-to-spaces"] = _tabs
S["files-sort-names"] = lambda ws: W(ws, "names.txt", "\n".join(sorted([l for l in R(ws, "names.txt").splitlines() if l.strip()], key=str.lower)) + "\n")
def _crlf(ws):
    for f in glob.glob(os.path.join(ws, "scripts", "*.sh")):
        b = open(f, "rb").read(); open(f, "wb").write(b.replace(b"\r\n", b"\n"))
S["files-line-endings"] = _crlf

S["long-needle-log"] = lambda ws: A(ws, [l.split()[2] for l in R(ws, "logs/server.log").splitlines() if l.split()[1] == "FATAL"][0])
S["long-aggregate-sku"] = lambda ws: A(ws, sum(int(r["qty"]) for r in rows(ws, "orders.csv") if r["sku"] == "SLUSH-BLUE-5L"))
S["long-distinct-march"] = lambda ws: A(ws, len({r["customer"] for r in rows(ws, "orders.csv") if r["date"].startswith("2026-03")}))
S["long-config-path"] = lambda ws: A(ws, json.loads(R(ws, "config_dump.json"))["services"]["billing"]["retry"]["max_attempts"])
S["long-find-caller"] = lambda ws: A(ws, [f for f in os.listdir(os.path.join(ws, "src")) if re.search(r"^\s+return legacy_charge\(", R(ws, "src/" + f), re.M)][0])
def _ctr(ws):
    t = R(ws, "contracts.txt"); blk = t.split("Seaport Ice Pty Ltd (ABN")[1].split("Schedule")[0]
    A(ws, re.search(r"giving (\d+) days", blk).group(1))
S["long-contract-clause"] = _ctr
def _gl(ws):
    for f in glob.glob(os.path.join(ws, "docs", "*.md")):
        m = re.search(r"deadline for Project Glacier is (\d{4}-\d\d-\d\d)", open(f, encoding="utf-8").read())
        if m: A(ws, m.group(1))
S["long-multi-file"] = _gl
S["long-action-items"] = lambda ws: A(ws, len(re.findall(r"^- \[[ x]\] ACTION \(Owner: Jon\)", R(ws, "meeting_notes.md"), re.M)))
S["long-count-decorated"] = lambda ws: A(ws, len(re.findall(r"^@deprecated$", R(ws, "utils.py"), re.M)))
def _reb(ws):
    p = subprocess.run([PY, "-c", "import rebates; print(rebates.compute_rebate_v37(10))"], cwd=ws, capture_output=True, text=True); A(ws, p.stdout.strip())
S["long-code-trace"] = _reb

def _inv(ws):
    o = json.loads(R(ws, "order.json")); sub = Decimal(0); g = Decimal(0)
    for i in o["items"]:
        lt = Decimal(i["unit_price_ex"]) * i["qty"]; sub += lt
        if not i["gst_free"]: g += C(lt / 10)
    W(ws, "invoice.json", json.dumps({"subtotal_ex": str(C(sub)), "gst": str(g), "total": str(C(sub) + g)}))
S["biz-gst-invoice"] = _inv
def _bk(ws):
    rs = rows(ws, "bookings.csv"); out = []
    for a in rs:
        for b in rs:
            if a["id"] < b["id"] and a["machine"] == b["machine"] and a["start"] < b["end"] and b["start"] < a["end"]: out.append(a["id"] + "," + b["id"])
    W(ws, "conflicts.txt", "\n".join(sorted(out)) + "\n")
S["biz-booking-conflicts"] = _bk
S["biz-reorder"] = lambda ws: wcsv(ws, "reorder.csv", [["supplier", "sku", "qty"]] + sorted([[r["supplier"], r["sku"], max(int(r["reorder_qty"]), 2 * int(r["reorder_point"]) - int(r["on_hand"]))] for r in rows(ws, "stock.csv") if int(r["on_hand"]) <= int(r["reorder_point"])]))
def _tier(ws):
    pr = {r["sku"]: Decimal(r["unit_price"]) for r in rows(ws, "price_list.csv")}; t = {}
    for r in rows(ws, "orders.csv"):
        q = int(r["qty"]); d = Decimal("0.85") if q >= 50 else Decimal("0.9") if q >= 10 else 1
        t[r["customer"]] = t.get(r["customer"], 0) + C(pr[r["sku"]] * q * d)
    wcsv(ws, "totals.csv", [["customer", "total"]] + [[c, "%.2f" % t[c]] for c in sorted(t)])
S["biz-discount-tiers"] = _tier
def _rec(ws):
    b = rows(ws, "bank.csv"); l = rows(ws, "ledger.csv"); used = set(); um = []
    for x in sorted(b, key=lambda x: x["id"]):
        cands = [y for y in l if y["id"] not in used and y["amount"] == x["amount"] and abs((date.fromisoformat(y["date"]) - date.fromisoformat(x["date"])).days) <= 3]
        if cands:
            y = min(cands, key=lambda y: abs((date.fromisoformat(y["date"]) - date.fromisoformat(x["date"])).days)); used.add(y["id"])
        else: um.append(["bank", x["id"]])
    um += [["ledger", y["id"]] for y in l if y["id"] not in used]
    wcsv(ws, "unmatched.csv", [["source", "id"]] + sorted(um))
S["biz-bank-rec"] = _rec
def _pay(ws):
    rate = {r["employee"]: Decimal(r["hourly_rate"]) for r in rows(ws, "rates.csv")}; h = {e: Decimal(0) for e in rate}
    for r in rows(ws, "timesheets.csv"): h[r["employee"]] += Decimal(r["hours"])
    out = [["employee", "ordinary_hours", "overtime_hours", "gross"]]
    for e in sorted(rate):
        o = min(h[e], 38); ot = max(h[e] - 38, 0); out.append([e, o, ot, "%.2f" % C(o * rate[e] + ot * rate[e] * Decimal("1.5"))])
    wcsv(ws, "pay.csv", out)
S["biz-payroll-ot"] = _pay
def _age(ws):
    b = {k: Decimal(0) for k in ["current", "1-30", "31-60", "61-90", "90+"]}
    for r in rows(ws, "invoices.csv"):
        if r["paid"] != "no": continue
        d = (date(2026, 10, 9) - date.fromisoformat(r["due_date"])).days
        b["current" if d <= 0 else "1-30" if d <= 30 else "31-60" if d <= 60 else "61-90" if d <= 90 else "90+"] += Decimal(r["amount"])
    W(ws, "aging.json", json.dumps({k: "%.2f" % v for k, v in b.items()}))
S["biz-aged-receivables"] = _age
def _pu(ws):
    rs = list(csv.reader(io.StringIO(R(ws, "prices.csv")))); out = [rs[0]]
    for s, c, p in rs[1:]:
        if c == "syrup": p = "%.2f" % ((Decimal(p) * Decimal("1.075") * 20).quantize(Decimal(1), ROUND_HALF_UP) / 20)
        out.append([s, c, p])
    wcsv(ws, "prices_new.csv", out)
S["biz-price-update"] = _pu
def _q(ws):
    rt = json.loads(R(ws, "rates.json")); rq = json.loads(R(ws, "request.json"))
    day = sum(Decimal(rt["machines"][m["type"]]) * m["qty"] for m in rq["machines"])
    hire = C(sum(day * (1 + Decimal(rt["weekend_surcharge_pct"]) / 100 if date.fromisoformat(d).weekday() >= 5 else 1) for d in rq["dates"]))
    dl = Decimal(rt["delivery"][rq["zone"]]); g = C((hire + dl) / 10)
    W(ws, "quote.json", json.dumps({"hire_ex": "%.2f" % hire, "delivery_ex": "%.2f" % dl, "gst": "%.2f" % g, "total": "%.2f" % (hire + dl + g)}))
S["biz-hire-quote"] = _q
def _ms(ws):
    t = {}
    for r in rows(ws, "sales.csv"):
        k = (r["date"][:7], r["product"]); t[k] = t.get(k, 0) + int(r["qty"]) * Decimal(r["unit_price"])
    wcsv(ws, "summary.csv", [["month", "product", "revenue"]] + [[m, p, "%.2f" % t[(m, p)]] for m, p in sorted(t)])
S["biz-monthly-sales"] = _ms

def _rmm(ws):
    s = R(ws, "report.py").replace("from snowutils.fmt import money_table\n", "def money_table(items):\n    return ''.join('%-15s %10.2f\\n' % kv for kv in items)\n")
    W(ws, "report.py", s); subprocess.run([PY, "report.py"], cwd=ws)
S["recover-missing-module"] = _rmm
S["recover-wrong-path"] = lambda ws: A(ws, "%.2f" % sum(Decimal(r["amount"]) for r in rows(ws, "data/2026/sales.csv")))
S["recover-typo-command"] = lambda ws: A(ws, subprocess.run([PY, "stats.py", "numbers.txt"], cwd=ws, capture_output=True, text=True).stdout.strip())
def _bj(ws):
    s = re.sub(r"//.*", "", R(ws, "settings.json")); s = re.sub(r",(\s*[}\]])", r"\1", s); W(ws, "settings.json", s); A(ws, json.loads(s)["threshold"])
S["recover-bad-json"] = _bj
S["recover-two-bugs"] = lambda ws: W(ws, "orderline.py", R(ws, "orderline.py").replace("split()[1]", "split()[0]").replace("int(float(price) * 100)", "round(float(price) * 100)"))
def _ev(ws):
    subprocess.run([PY, "app.py"], cwd=ws, env=dict(os.environ, APP_MODE="offline"))
S["recover-env-var"] = _ev
def _enc(ws):
    W(ws, "menu.py", R(ws, "menu.py").replace("open('menu.txt')", "open('menu.txt', encoding='utf-8')").replace("open('menu_out.txt', 'w')", "open('menu_out.txt', 'w', encoding='utf-8')"))
S["recover-encoding"] = _enc
S["recover-missing-dir"] = lambda ws: W(ws, "export.py", "import os\nos.makedirs('out', exist_ok=True)\n" + R(ws, "export.py"))
S["recover-infinite-loop"] = lambda ws: W(ws, "process.py", R(ws, "process.py").replace("        continue\n", "        i += 1\n        continue\n"))
def _ci(ws):
    W(ws, "b.py", "def fmt(n):\n    from a import helper\n    return 'TOTAL %d (helper check %d)' % (n, helper(1))\n")
    A(ws, subprocess.run([PY, "main.py"], cwd=ws, capture_output=True, text=True).stdout.strip())
S["recover-circular-import"] = _ci
