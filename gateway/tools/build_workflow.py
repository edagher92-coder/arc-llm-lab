"""Turn a converted API graph into a gateway workflow file: {"meta": {...parameters...}, "prompt": <graph with {{placeholders}}>}.

Usage: python build_workflow.py spec.json api_graph.json object_info.json out.json
       python build_workflow.py spec.json out.json            (a staged spec, see "stages" below: no graph needed)

spec.json:
  {"meta": {...copied into the workflow's meta block, including "params"...},
   "replace": {"<node>": {"class_type": "...", "inputs": {...}}},          # swap a node for another class (e.g. UNETLoader -> UnetLoaderGGUF); applied first
   "add":  {"<new node id>": {"class_type": "...", "inputs": {...}}},       # extra nodes (e.g. the audio NaN guard); wire them with "set"
   "set":  {"<node>.<input>": value | ["<node>", slot] | "{{param}}"},     # edits applied first (a list [node, slot] is a link)
   "bind": {"<param>": ["<node>.<input>", ...]},                          # these inputs become "{{param}}" placeholders
   "rewire": {"<node>:<slot>": ["<node>", slot]},                          # every input linked to that output is relinked (e.g. to a conditioning loader)
   "keep_outputs": ["<node>", ...],                                       # after the edits, output nodes not listed here are removed (a stage that only saves conditioning)
   "drop": ["<node>", ...]}                                               # nodes removed before pruning
Staged workflow (two-process split, see video.py): {"meta": {...params...}, "stages": ["<stage workflow name>", ...]} builds to
{"meta": {..., "stages": [...]}, "prompt": {}}; each stage is itself an ordinary spec, built into workflows_dir/stages/<name>.json.
Unreferenced nodes are pruned after the edits, so rewiring around an unwanted branch (a prompt enhancer, say) also removes that branch.
"""
import copy, json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfy_ui_to_api import prune_graph, ConvertError


def _at(graph, ref):
    node, _, inp = ref.partition(".")
    if node not in graph:
        raise ConvertError("no node %r in the graph (%s)" % (node, ref))
    return graph[node]["inputs"], inp


STAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
GRAPH_KEYS = ("replace", "add", "set", "bind", "drop", "rewire", "keep_outputs")


def build_staged(spec):
    st = spec["stages"]
    if not isinstance(st, list) or not st or not all(isinstance(x, str) and STAGE_NAME.fullmatch(x) and ".." not in x for x in st):
        raise ConvertError("stages must be a non-empty list of stage names")
    if len(set(st)) != len(st):
        raise ConvertError("a stage name is listed twice")
    bad = [k for k in GRAPH_KEYS if spec.get(k)]
    if bad:
        raise ConvertError("a staged spec holds no graph edits (found: %s); put them in the stage specs" % ", ".join(bad))
    meta = dict(spec.get("meta") or {})
    meta["stages"] = list(st)
    return {"meta": meta, "prompt": {}}


def build(spec, api, info):
    if spec.get("stages") is not None:
        return build_staged(spec)
    g = copy.deepcopy(api)
    for nid, node in (spec.get("replace") or {}).items():
        if nid not in g:
            raise ConvertError("replace: no node %r in the graph" % nid)
        g[nid] = copy.deepcopy(node)
    for nid, node in (spec.get("add") or {}).items():
        if nid in g:
            raise ConvertError("add: node id %r already exists" % nid)
        g[nid] = copy.deepcopy(node)
    for ref, val in (spec.get("set") or {}).items():
        d, k = _at(g, ref)
        d[k] = val
    for key, new in (spec.get("rewire") or {}).items():
        src, _, slot = key.rpartition(":")
        if not src or not slot.isdigit() or src not in g or not (isinstance(new, list) and len(new) == 2 and new[0] in g):
            raise ConvertError("rewire %r -> %r: want '<node>:<slot>' of an existing node and ['<node>', slot]" % (key, new))
        for nid, node in g.items():
            if nid in (spec.get("add") or {}):                              # the nodes the spec added keep the inputs it gave them
                continue
            for inp, v in node["inputs"].items():
                if isinstance(v, list) and len(v) == 2 and v[0] == src and v[1] == int(slot):
                    node["inputs"][inp] = list(new)
    for param, refs in (spec.get("bind") or {}).items():
        if param not in (spec.get("meta", {}).get("params") or {}) and param not in ("seconds",):
            raise ConvertError("bind %r is not declared in meta.params" % param)
        for ref in refs:
            d, k = _at(g, ref)
            d[k] = "{{%s}}" % param
    for nid in spec.get("drop") or []:                                   # e.g. a preview node that would keep a rewired-away branch alive
        g.pop(nid, None)
    if spec.get("keep_outputs") is not None:
        keep = spec["keep_outputs"]
        missing = [k for k in keep if k not in g]
        if missing:
            raise ConvertError("keep_outputs: no node %s in the graph" % ", ".join(map(repr, missing)))
        for k in [k for k, v in g.items() if (info.get(v["class_type"]) or {}).get("output_node") and k not in keep]:
            del g[k]
    g = prune_graph(g, info)
    for g_node in g.values():
        g_node.pop("_meta", None)
    return {"meta": spec.get("meta") or {}, "prompt": g}


if __name__ == "__main__":
    if len(sys.argv) not in (3, 5):
        sys.exit(__doc__)
    spec = json.load(open(sys.argv[1], encoding="utf-8-sig"))
    if len(sys.argv) == 3:
        if spec.get("stages") is None:
            sys.exit("only a staged spec can be built without api_graph.json and object_info.json\n" + __doc__)
        api = info = None
    else:
        api, info = (json.load(open(p, encoding="utf-8-sig")) for p in sys.argv[2:4])
    out = build(spec, api, info)
    json.dump(out, open(sys.argv[-1], "w", encoding="utf-8"), indent=1)
    print("%d nodes, %d parameters -> %s" % (len(out["prompt"]), len((out["meta"].get("params") or {})), sys.argv[-1]))
