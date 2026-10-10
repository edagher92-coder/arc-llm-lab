"""Add the gateway as an Open WebUI tool server and switch off the old direct PC-agent and Browser connections.
Run only while Open WebUI is stopped. Backs up webui.db first. Requested by the owner on 2026-10-10."""
import json, shutil, sqlite3, time
ts = int(time.time())
DB = r"C:\AI\openwebui\data\webui.db"
shutil.copy(DB, DB + ".bak-gw-%d" % ts)
KEY = open(r"C:\AI\mcpo\api-key.txt").read().strip()
c = sqlite3.connect(DB)
row = c.execute("select value from config where key='tool_server.connections'").fetchone()
conns = (json.loads(row[0]) if row and isinstance(row[0], str) else (row[0] if row else [])) or []
for x in conns:
    if (x.get("info") or {}).get("id") in ("pc", "browser"):
        x.setdefault("config", {})["enable"] = False
if not any(str(x.get("url", "")).rstrip("/").endswith("/gw") for x in conns):
    conns.append({"url": "http://127.0.0.1:8100/gw", "path": "openapi.json", "type": "openapi", "auth_type": "bearer", "key": KEY,
                  "config": {"enable": True}, "info": {"id": "gw", "name": "PC tools (smart gateway)",
                  "description": "Search and call PC tools on demand. Actions that change things need approval on the approvals page."}})
c.execute("update config set value=?, updated_at=? where key='tool_server.connections'", (json.dumps(conns), ts))
c.commit()
print([((x.get("info") or {}).get("id"), (x.get("config") or {}).get("enable")) for x in conns])
