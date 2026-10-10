"""Validate every checker: untouched workspace must FAIL, reference solution must PASS."""
import tempfile, os, sys, shutil, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tasks, refs
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
