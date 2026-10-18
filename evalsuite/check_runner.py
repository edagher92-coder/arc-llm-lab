"""Offline checks for runner.py's Codex turn cap and prune_codex_trust.py (no model calls; runs on Linux and Windows CI).
python check_runner.py          exit 1 on any failure"""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runner, tasks, prune_codex_trust as prune

fails = 0
def ok(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name); fails += 0 if cond else 1

d = tempfile.mkdtemp(); logf = os.path.join(d, "x.log")
lines = [json.dumps({"type": "item.completed", "item": {"type": t}}) for t in ["command_execution"] * 20 + ["file_change"] * 6 + ["agent_message"] * 5]
lines.insert(3, "not json"); lines.append('{"type":"turn.completed","usage":{}}')
open(logf, "w", encoding="utf-8").write("\n".join(lines))
ok("turn counter counts tool + edit items only (26)", runner.codex_turns_so_far(logf) == 26)
ok("turn counter: missing log counts 0", runner.codex_turns_so_far(os.path.join(d, "nope.log")) == 0)
ok("turn counter agrees with parse_codex", runner.parse_codex("\n".join(lines), os.path.join(d, "none.txt"))["turns"] == 26)
ok("capped run is classified max_turns", runner.classify(False, False, {}, "", None, True) == "max_turns")
ok("timeout is still classified timeout", runner.classify(False, True, {}, "", None, False) == "timeout")
ok("a pass is never a failure", runner.classify(True, False, {}, "", None, True) is None)

ids = {t["id"] for t in tasks.TASKS}
acc = [l.strip() for l in open(os.path.join(HERE, "acceptance.txt"), encoding="utf-8") if l.strip() and not l.lstrip().startswith("#")]
ok("acceptance.txt: %d ids, no duplicates" % len(acc), len(acc) == len(set(acc)) and len(acc) >= 19)
missing = [i for i in acc if i not in ids]
ok("acceptance.txt ids exist in tasks.py (%s)" % (",".join(missing) or "all"), not missing)

cfg = ("model = \"q\"\n[projects.'c:\\ai\\bench']\ntrust_level = \"trusted\"\n# keep me\n"
       "[projects.'c:\\ai\\evalsuite\\work\\run1\\t1']\ntrust_level = \"trusted\"\n\n"
       "[projects.\"C:\\\\AI\\\\evalsuite\\\\work\\\\run2\\\\t2\"]\ntrust_level = \"trusted\"\n"
       "[projects.'c:\\ai\\evalsuite\\workbench']\ntrust_level = \"trusted\"\n[tools]\nx = 1\n")
new, removed = prune.prune(cfg)
ok("prune removes evalsuite work tables (single and double quoted)", removed == 2 and "run1" not in new and "run2" not in new)
ok("prune keeps other projects, comments and later tables", "c:\\ai\\bench" in new and "# keep me" in new and "workbench" in new and "[tools]\nx = 1" in new)
ok("prune is idempotent", prune.prune(new) == (new, 0))

print("CHECK_RUNNER", "PASS" if fails == 0 else "FAIL")
sys.exit(1 if fails else 0)
