"""ARC-PC Phase-3 sustained-session test (48K-64K).
One continuous agent session builds a small hire/invoicing package over 10 dependent steps, re-reading a large
requirements doc, so the conversation grows past the client window and must compact.
Measures per step: pass (cumulative hidden tests = regression check), wall time, PEAK live prompt tokens (llama-server /slots),
server n_ctx, model reloads, compaction events, explicit overflow errors. Step 10 is a memory probe: a code given only
in conversation at step 1 must be recalled after compaction -> detects silent context loss.
Usage: python sustained.py --agent claude|codex --cap 49152|65536 [--run NAME]"""
import argparse, json, os, re, glob, random, shutil, subprocess, sys, threading, time, urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runner as RN
import tasks as SUITE

PROBE = "SF-7731-KESTREL"
D = Decimal
def cents(x): return D(x).quantize(D("0.01"), ROUND_HALF_UP)

# ---------------- data ----------------
HOLIDAYS = [date(2026, 10, 5), date(2026, 12, 25), date(2026, 12, 28), date(2027, 1, 1), date(2027, 1, 26)]
def gen_data():
    r = random.Random(900)
    machines = [("DBL-1", "double", "120.00"), ("DBL-2", "double", "120.00"), ("TRP-1", "triple", "165.00"), ("SGL-1", "single", "85.00"),
                ("SGL-2", "single", "85.00"), ("SOFT-1", "softserve", "210.00")]
    bookings = []
    for i in range(200):
        m = r.choice(machines)[0]; s = date(2026, 10, 1) + timedelta(days=r.randrange(110)); e = s + timedelta(days=r.choice([0, 0, 1, 1, 2, 3, 6]))
        cust = r.choice(["Bondi Public School", "Parra Events", "Smith, J & K", "Gosford Show Society", "Manly \"Surf\" Club", "Riverside Fete"])
        bookings.append(("BK%03d" % (i + 1), m, cust, s, e))
    return machines, bookings
MACH, BOOK = gen_data()

def csv_files():
    import csv, io
    b = io.StringIO(); w = csv.writer(b, lineterminator="\n"); w.writerow(["id", "kind", "daily_rate"]); w.writerows(MACH)
    c = io.StringIO(); w = csv.writer(c, lineterminator="\n"); w.writerow(["id", "machine_id", "customer", "start", "end"])
    for i, m, cu, s, e in BOOK: w.writerow([i, m, cu, s.strftime("%d/%m/%Y"), e.strftime("%d/%m/%Y")])
    return b.getvalue(), c.getvalue()

def requirements_md():
    r = random.Random(901)
    filler_words = ("machine hire customers must receive clear written terms before delivery and the driver confirms power access cleaning "
                    "syrup ratios ice levels safety tags insurance certificates are kept on file for every school event and council permit").split()
    def para(n): return " ".join(r.choice(filler_words) for _ in range(n)).capitalize() + "."
    S = ["# SnowHire platform requirements (v3)", "", "Owner: the owner. Status: approved. This document is long; the rules that matter for code are in sections 2, 3, 4, 5 and 7.", ""]
    S += ["## 1. Background", ""] + [para(r.randrange(60, 120)) for _ in range(8)] + [""]
    S += ["## 2. Data model", "", "- Machine: id (str), kind (str), daily_rate (Decimal, AUD ex GST).",
          "- Booking: id (str), machine_id (str), customer (str), start (date), end (date). Dates are INCLUSIVE: a booking from 3 Nov to 3 Nov is one day.",
          "- CSV files use dd/mm/yyyy dates (Australian format) and may contain quoted fields with commas and doubled quotes.", ""]
    S += ["## 3. Pricing (rules version 1)", "", "- A booking is charged per day: daily_rate for each day from start to end inclusive.",
          "- Saturday and Sunday days are charged daily_rate * 1.10 (10% weekend surcharge).",
          "- Round the booking total to the cent, half-up, only at the end (never per day).", ""]
    S += ["## 4. Conflicts", "", "- Two bookings conflict if they use the same machine and their inclusive date ranges share at least one day.", ""]
    S += ["## 5. Invoicing (GST)", "", "- One invoice line per booking: amount = the booking price.",
          "- GST is 10% of each line amount, rounded half-up to the cent PER LINE; invoice gst = sum of line GST.",
          "- subtotal = sum of line amounts; total = subtotal + gst.", ""]
    S += ["## 6. Operations notes", ""] + [para(r.randrange(80, 140)) for _ in range(40)] + [""]
    S += ["## 7. Public holidays (used from rules version 2 only)", "", "NSW public holidays in the booking period: " + ", ".join(h.isoformat() for h in HOLIDAYS) + ".",
          "Under rules version 2 a public holiday is charged like a weekend day (the surcharge applies once, never twice).", ""]
    S += ["## 8. Appendix: customer FAQ", ""] + [para(r.randrange(80, 140)) for _ in range(30)] + [""]
    return "\n".join(S) + "\n"

# ---------------- reference rules ----------------
def ref_price(s, e, rate, ver):
    sur = D("0.10") if ver == 1 else D("0.125"); tot = D(0); d = s
    while d <= e:
        special = d.weekday() >= 5 or (ver == 2 and d in HOLIDAYS)
        tot += D(rate) * (1 + sur if special else 1); d += timedelta(days=1)
    return cents(tot)

def ref_month(month, ver):
    rate = {m[0]: D(m[2]) for m in MACH}; sur = D("0.10") if ver == 1 else D("0.125"); tot = D(0)
    for _, m, _, s, e in BOOK:
        d = s
        while d <= e:
            if d.strftime("%Y-%m") == month:
                special = d.weekday() >= 5 or (ver == 2 and d in HOLIDAYS)
                tot += rate[m] * (1 + sur if special else 1)
            d += timedelta(days=1)
    return cents(tot)

# ---------------- cumulative hidden tests ----------------
def tests_upto(step, ver):
    T = ["import datetime as dt, subprocess, sys\nfrom decimal import Decimal as D\n"]
    T.append("from snowhire.models import Machine, Booking\n"
             "M = Machine(id='DBL-1', kind='double', daily_rate=D('120.00'))\n"
             "def B(i, s, e, m='DBL-1'): return Booking(id=i, machine_id=m, customer='X', start=s, end=e)\n"
             "def test_models():\n    b = B('B1', dt.date(2026,11,2), dt.date(2026,11,3)); assert b.machine_id == 'DBL-1' and M.daily_rate == D('120.00')\n")
    if step >= 2:
        cases = [(date(2026, 11, 2), date(2026, 11, 2)), (date(2026, 11, 6), date(2026, 11, 9)), (date(2026, 12, 24), date(2026, 12, 28)), (date(2026, 10, 3), date(2026, 10, 5))]
        T.append("from snowhire.pricing import booking_price\ndef test_price():\n" + "".join(
            "    assert booking_price(B('P', dt.date(%d,%d,%d), dt.date(%d,%d,%d)), M) == D('%s')\n" % (s.year, s.month, s.day, e.year, e.month, e.day, ref_price(s, e, "120.00", ver)) for s, e in cases))
    if step >= 3:
        T.append("from snowhire.conflicts import find_conflicts\ndef test_conflicts():\n"
                 "    bs = [B('A', dt.date(2026,11,1), dt.date(2026,11,3)), B('B', dt.date(2026,11,3), dt.date(2026,11,4)), B('C', dt.date(2026,11,5), dt.date(2026,11,5)), B('D', dt.date(2026,11,1), dt.date(2026,11,9), m='SGL-1')]\n"
                 "    assert [tuple(x) for x in find_conflicts(bs)] == [('A', 'B')]\n")
    if step >= 4:
        a = ref_price(date(2026, 11, 6), date(2026, 11, 9), "120.00", ver); b = ref_price(date(2026, 11, 2), date(2026, 11, 2), "120.00", ver)
        g = cents(a * D("0.1")) + cents(b * D("0.1"))
        T.append("from snowhire.invoice import make_invoice\ndef test_invoice():\n"
                 "    inv = make_invoice([B('I1', dt.date(2026,11,6), dt.date(2026,11,9)), B('I2', dt.date(2026,11,2), dt.date(2026,11,2))], {'DBL-1': M})\n"
                 "    assert D(str(inv['subtotal'])) == D('%s') and D(str(inv['gst'])) == D('%s') and D(str(inv['total'])) == D('%s') and len(inv['lines']) == 2\n" % (a + b, g, a + b + g))
    if step >= 5:
        i, m, cu, s, e = BOOK[17]
        T.append("from snowhire.io import load_bookings, load_machines\ndef test_io():\n"
                 "    bs = load_bookings('data/bookings.csv'); ms = load_machines('data/machines.csv')\n"
                 "    assert len(bs) == 200 and len(ms) == 6\n"
                 "    b = [x for x in bs if x.id == '%s'][0]\n    assert b.customer == %r and b.start == dt.date(%d,%d,%d) and b.end == dt.date(%d,%d,%d) and b.machine_id == '%s'\n"
                 "    assert [x for x in ms if x.id == 'TRP-1'][0].daily_rate == D('165.00')\n" % (i, cu, s.year, s.month, s.day, e.year, e.month, e.day, m))
    if step >= 6:
        busy = {m for _, m, _, s, e in BOOK if s <= date(2026, 12, 20) and e >= date(2026, 12, 18)}
        free = sorted(x[0] for x in MACH if x[0] not in busy)
        T.append("from snowhire.availability import available_machines\ndef test_avail():\n"
                 "    assert list(available_machines(load_machines('data/machines.csv'), load_bookings('data/bookings.csv'), dt.date(2026,12,18), dt.date(2026,12,20))) == %r\n" % free)
    if step >= 7:
        T.append("from snowhire.reports import monthly_revenue\ndef test_monthly():\n"
                 "    r = monthly_revenue(load_bookings('data/bookings.csv'), load_machines('data/machines.csv'))\n"
                 "    assert D(str(r['2026-11'])) == D('%s') and D(str(r['2026-12'])) == D('%s')\n" % (ref_month("2026-11", ver), ref_month("2026-12", ver)))
    if step >= 8:
        T.append("def test_cli():\n    p = subprocess.run([sys.executable, '-m', 'snowhire', 'report', '--month', '2026-11', '--data', 'data/bookings.csv', '--machines', 'data/machines.csv'], capture_output=True, text=True, timeout=60)\n"
                 "    assert p.returncode == 0 and '2026-11 revenue: $%s' in p.stdout.replace(',', ''), p.stdout + p.stderr\n" % ref_month("2026-11", ver))
    return "".join(T)

S_SUFFIX = " Work inside the current folder only. Run your code to verify it before you finish."
STEPS = [
 ("Read docs/requirements.md (all of it, it is long) and data/. We are building a Python package snowhire/ step by step over this session. "
  "Step 1: create snowhire/__init__.py and snowhire/models.py with dataclasses Machine(id, kind, daily_rate) and Booking(id, machine_id, customer, start, end) as per section 2 (daily_rate a Decimal, start/end datetime.date). "
  "Also, remember this for later in our session: the client reference code is " + PROBE + ". Do NOT write that code into any file." + S_SUFFIX, 1),
 ("Step 2: create snowhire/pricing.py with booking_price(booking, machine) -> Decimal implementing pricing rules version 1 from section 3 of docs/requirements.md." + S_SUFFIX, 1),
 ("Step 3: create snowhire/conflicts.py with find_conflicts(bookings) returning a sorted list of (id1, id2) tuples (id1 < id2) per section 4." + S_SUFFIX, 1),
 ("Step 4: create snowhire/invoice.py with make_invoice(bookings, machines_by_id, gst_rate=Decimal('0.10')) returning a dict with keys lines (list of dicts with booking, amount, gst), subtotal, gst, total (Decimals) per section 5. "
  "Use pricing.booking_price." + S_SUFFIX, 1),
 ("Step 5: create snowhire/io.py with load_machines(path) and load_bookings(path) that read data/machines.csv and data/bookings.csv into the dataclasses (see section 2 for the date format and quoting). "
  "Check that all 200 bookings load." + S_SUFFIX, 1),
 ("Step 6: create snowhire/availability.py with available_machines(machines, bookings, start, end) returning the sorted list of machine ids that have no booking overlapping any day of the inclusive range." + S_SUFFIX, 1),
 ("Step 7: create snowhire/reports.py with monthly_revenue(bookings, machines) returning a dict 'YYYY-MM' -> Decimal: every booked day's charge (daily_rate, with the weekend surcharge on weekend days) is attributed to the month of that day; "
  "sum per month and round each month's total to the cent half-up at the end." + S_SUFFIX, 1),
 ("Step 8: add a command line interface so that `python -m snowhire report --month 2026-11 --data data/bookings.csv --machines data/machines.csv` prints exactly one line like `2026-11 revenue: $12345.67` "
  "(no thousands separator) using monthly_revenue." + S_SUFFIX, 1),
 ("Step 9: the pricing rules changed to rules version 2: the weekend surcharge is now 12.5% instead of 10%, and public holidays listed in section 7 of docs/requirements.md are charged like weekend days (surcharge applies once). "
  "Update every part of the package that depends on the surcharge (pricing, invoice, monthly revenue, CLI) so they all use version 2, keeping one source of truth for the rule. Re-verify everything." + S_SUFFIX, 2),
 ("Step 10: write to answer.txt the client reference code I gave you at the very start of this session (it is not in any file). If you no longer have it, write UNKNOWN. Then reply with a one-paragraph summary of the package.", 2),
]

class SlotPoll(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True); self.port = port; self.stop = False; self.peak = 0; self.nctx = set(); self.errors = 0
    def run(self):
        while not self.stop:
            try:
                s = json.loads(urllib.request.urlopen("http://127.0.0.1:%s/slots" % self.port, timeout=3).read())
                for x in s:
                    self.peak = max(self.peak, int(x.get("n_prompt_tokens") or 0)); self.nctx.add(x.get("n_ctx"))
            except Exception:
                self.errors += 1
            time.sleep(2)

def compactions(agent, ws, log):
    if agent == "claude":
        slug = re.sub(r"[^A-Za-z0-9]", "-", ws)
        n = 0
        for f in glob.glob(os.path.join(r"C:\AI\claude-local\projects", slug, "*.jsonl")):
            t = open(f, encoding="utf-8", errors="replace").read()
            n += t.count('"compact_boundary"') + t.count('"isCompactSummary":true')
        return n
    return len(re.findall(r"compact", log, re.I))

def codex_cmd(ws, last, thread):
    base = '"%s\\codex-qwen.cmd" exec --skip-git-repo-check -s workspace-write -c approval_policy="never" --json -C "%s" -o "%s"' % (RN.BIN, ws, last)
    return base + (" resume %s -" % thread if thread else " -")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--agent", required=True, choices=["claude", "codex"]); ap.add_argument("--cap", type=int, default=65536); ap.add_argument("--run")
    ap.add_argument("--steps", type=int, default=len(STEPS))
    a = ap.parse_args()
    run = a.run or "sustained-%s-%dk" % (a.agent, a.cap // 1024)
    ws = os.path.join(HERE, "work", run, "project"); shutil.rmtree(os.path.dirname(ws), ignore_errors=True); os.makedirs(ws)
    mcsv, bcsv = csv_files()
    for rel, c in {"docs/requirements.md": requirements_md(), "data/machines.csv": mcsv, "data/bookings.csv": bcsv}.items():
        p = os.path.join(ws, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w", encoding="utf-8", newline="").write(c)
    meta = os.path.join(HERE, "work", run, "_meta"); os.makedirs(meta)
    out = os.path.join(HERE, "results", run + ".jsonl"); open(out, "w").close()
    env = dict(os.environ, QWEN_CLIENT_CAP=str(a.cap)); thread = None
    for k, (prompt, ver) in enumerate(STEPS[:a.steps], 1):
        pf = os.path.join(meta, "step%02d.prompt.txt" % k); open(pf, "w", encoding="utf-8").write(prompt)
        logf = os.path.join(meta, "step%02d.log" % k); last = os.path.join(meta, "step%02d.last.txt" % k)
        if a.agent == "claude":
            cmd = '"%s\\claude-qwen.cmd" -p --output-format json --max-turns 60 --permission-mode acceptEdits --allowedTools "Bash Read Edit Write Glob Grep"%s' % (RN.BIN, "" if k == 1 else " --continue")
        else:
            cmd = codex_cmd(ws, last, thread)
        r0 = RN.running(); port = r0.get("port", 10001); m0 = RN.metrics(port); poll = SlotPoll(port); poll.start(); smp = RN.Sampler(); smp.start()
        t0 = time.time(); timed_out = False
        with open(pf, "rb") as fin, open(logf, "wb") as fo:
            p = subprocess.Popen(cmd, cwd=ws, stdin=fin, stdout=fo, stderr=subprocess.STDOUT, shell=True, env=env, creationflags=RN.NOWIN)
            try: rc = p.wait(timeout=1200)
            except subprocess.TimeoutExpired: timed_out = True; RN.kill_tree(p.pid); time.sleep(2); rc = None
        wall = round(time.time() - t0, 1); poll.stop = True; smp.stop = True
        log = open(logf, encoding="utf-8", errors="replace").read()
        info = RN.parse_claude(log) if a.agent == "claude" else RN.parse_codex(log, last)
        if a.agent == "codex" and not thread:
            m = re.search(r'"thread_id":"([^"]+)"', log); thread = m.group(1) if m else None
        r1 = RN.running(); m1 = RN.metrics(r1.get("port", port))
        if k < 10:
            ok, why = SUITE.run_hidden(ws, tests_upto(k if k < 9 else 8, ver))
        else:
            got = SUITE.ans(ws); ok = SUITE.norm(got) == SUITE.norm(PROBE); why = "" if ok else "answer.txt=%r" % got[:60]
            leaked = [f for f in glob.glob(os.path.join(ws, "**", "*"), recursive=True) if os.path.isfile(f) and not f.endswith("answer.txt")
                      and PROBE in open(f, encoding="utf-8", errors="ignore").read()]
            if leaked: why += " PROBE WRITTEN TO FILES (retention not provable): %s" % [os.path.relpath(x, ws) for x in leaked][:3]
        d = lambda key: (m1.get(key, 0) - m0.get(key, 0)) if m1.get(key, 0) >= m0.get(key, 0) else m1.get(key, 0)
        rec = dict(run=run, agent=a.agent, cap=a.cap, step=k, rules=ver, passed=bool(ok), reason=(why or "")[:500], wall_s=wall, timed_out=timed_out, rc=rc,
                   failure=RN.classify(ok, timed_out, info, log, rc), turns=info.get("turns"), peak_prompt_tok=poll.peak, srv_n_ctx=sorted(x for x in poll.nctx if x),
                   compactions_total=compactions(a.agent, ws, log), overflow_error=bool(re.search(r"exceed_context_size|exceeds the available context", log)),
                   srv_prompt_tok=d("prompt_tokens_total"), srv_cached_tok=d("prompt_tokens_cached_total"), srv_gen_tok=d("tokens_predicted_total"),
                   srv_gen_s=round(d("tokens_predicted_seconds_total"), 1), srv_prompt_s=round(d("prompt_seconds_total"), 1),
                   vram_min_free_gib=smp.min_free, model_reloaded=len(smp.starts | {r0.get("started"), r1.get("started")} - {None}) > 1,
                   final=(info.get("final") or "")[-300:], ended=datetime.now().isoformat(timespec="seconds"))
        open(out, "a", encoding="utf-8").write(json.dumps(rec) + "\n")
        print("step %2d %s %6.1fs peak_prompt=%6d ctx=%s compactions=%d %s" % (k, "PASS" if ok else "FAIL", wall, poll.peak, rec["srv_n_ctx"], rec["compactions_total"], rec["failure"] or ""), flush=True)

if __name__ == "__main__":
    main()
