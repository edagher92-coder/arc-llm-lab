"""Make gateway.agent.json from your gateway.json for Claude Code, Claude Desktop or Codex.

An agent already has its own shell and file tools, so the `pc` server (a nested Claude Code) is dropped and the pc_* pins with
it. Browser, your Chrome, desktop, MarkItDown, library docs, fetch, time, skills and share_file stay behind the same search.
Tokens stay in your local files. Run:  .venv\\Scripts\\python.exe make_agent_config.py [drop more servers...]"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(HERE, "gateway.json"); dst = os.path.join(HERE, "gateway.agent.json")
drop = {"pc", *sys.argv[1:]}
c = json.load(open(src, encoding="utf-8-sig"))
c["servers"] = {k: v for k, v in c["servers"].items() if k not in drop}
pref = tuple(d + "_" for d in drop)
c["pin"] = [p for p in c.get("pin", []) if not p.startswith(pref)]
c["descriptions"] = {k: v for k, v in (c.get("descriptions") or {}).items() if not k.startswith(pref)}
c["name"] = c.get("name", "gateway") + "-agent"
json.dump(c, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("wrote %s: servers %s, pinned %s" % (dst, ", ".join(c["servers"]), ", ".join(c["pin"])))
