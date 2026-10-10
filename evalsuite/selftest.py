"""Validate every checker: an untouched workspace must FAIL, a reference solution must PASS.
python selftest.py          report
python selftest.py --ci     exit 1 on any problem (used by GitHub Actions)"""
import tempfile, os, sys, shutil, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tasks, refs
# These two tasks test Windows-only bugs (text-mode newlines, cp1252 default encoding); on Linux the bug cannot show.
WINDOWS_ONLY = {"debug-csvout", "recover-encoding"}
neg, pos = [], []
t0 = time.time()
for t in tasks.TASKS:
    ws = tempfile.mkdtemp(prefix="st_")
    try:
        tasks.materialize(t, ws)
        ok, why = t["check"](ws)
        if ok: neg.append(t["id"])
        refs.S[t["id"]](ws)
        ok, why = t["check"](ws)
        if not ok: pos.append((t["id"], why))
    except Exception as e:
        pos.append((t["id"], "EXC %r" % e))
    finally:
        shutil.rmtree(ws, ignore_errors=True)
print("tasks:", len(tasks.TASKS), "time %.0fs" % (time.time() - t0))
print("untouched-but-passing:", neg)
print("reference-failing:", len(pos))
for i, w in pos: print("  ", i, "->", str(w)[:300])
if "--ci" in sys.argv:
    allowed = WINDOWS_ONLY if os.name != "nt" else set()
    bad_neg = [i for i in neg if i not in allowed]
    if pos or bad_neg or len(tasks.TASKS) != 100:
        print("SELFTEST FAILED", {"reference_failing": [p[0] for p in pos], "untouched_passing": bad_neg}); sys.exit(1)
    print("SELFTEST OK: 100 checkers validated")
