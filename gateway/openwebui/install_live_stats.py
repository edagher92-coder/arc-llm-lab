"""Install the Live stats filter into Open WebUI (global, active). Backs up webui.db first."""
import json, shutil, sqlite3, time
DB = r"C:\AI\openwebui\data\webui.db"; ts = int(time.time())
shutil.copy(DB, DB + ".bak-stats-%d" % ts)
src = open(r"C:\AI\gateway\live_stats_filter.py", encoding="utf-8").read()
c = sqlite3.connect(DB)
cols = [r[1] for r in c.execute("pragma table_info(function)")]
ref = dict(zip(cols, c.execute("select * from function where id='smart_tool_router'").fetchone()))
meta = {"description": "Speed, context use and drafter acceptance under every reply", "manifest": {"title": "Live stats", "version": "0.1.0"}}
row = dict(ref, id="live_stats", name="Live stats", type="filter", content=src, meta=json.dumps(meta), valves=None, is_active=1, is_global=1, created_at=ts, updated_at=ts)
c.execute("delete from function where id='live_stats'")
c.execute("insert into function (%s) values (%s)" % (",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
c.commit(); print("installed:", [r for r in c.execute("select id,type,is_active,is_global from function")])
