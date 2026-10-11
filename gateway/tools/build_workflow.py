"""Turn a converted API graph into a gateway workflow file: {"meta": {...parameters...}, "prompt": <graph with {{placeholders}}>}.

Usage: python build_workflow.py spec.json api_graph.json object_info.json out.json

spec.json:
  {"meta": {...copied into the workflow's meta block, including "params"...},
   "replace": {"<node>": {"class_type": "...", "inputs": {...}}},          # swap a node for another class (e.g. UNETLoader -> UnetLoaderGGUF); applied first
   "add":  {"<new node id>": {"class_type": "...", "inputs": {...}}},       # extra nodes (e.g. the audio NaN guard); wire them with "set"
   "set":  {"<node>.<input>": value | ["<node>", slot] | "{{param}}"},     # edits applied first (a list [node, slot] is a link)
   "bind": {"<param>": ["<node>.<input>", ...]},                          # these inputs become "{{param}}" placeholders
   "drop": ["<node>", ...]}                                               # nodes removed before pruning
Unreferenced nodes are pruned after the edits, so rewiring around an unwanted branch (a prompt enhancer, say) also removes that branch.
"""
import copy, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfy_ui_to_api import prune_graph, ConvertError


def _at(graph, ref):
    node, _, inp = ref.partition(".")
    if node not in graph:
        raise ConvertError("no node %r in the graph (%s)" % (node, ref))
    return graph[node]["inputs"], inp


def build(spec, api, info):
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
    for param, refs in (spec.get("bind") or {}).items():
        if param not in (spec.get("meta", {}).get("params") or {}) and param not in ("seconds",):
            raise ConvertError("bind %r is not declared in meta.params" % param)
        for ref in refs:
            d, k = _at(g, ref)
            d[k] = "{{%s}}" % param
    for nid in spec.get("drop") or []:                                   # e.g. a preview node that would keep a rewired-away branch alive
        g.pop(nid, None)
    g = prune_graph(g, info)
    for g_node in g.values():
        g_node.pop("_meta", None)
    return {"meta": spec.get("meta") or {}, "prompt": g}


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    spec, api, info = (json.load(open(p, encoding="utf-8-sig")) for p in sys.argv[1:4])
    out = build(spec, api, info)
    json.dump(out, open(sys.argv[4], "w", encoding="utf-8"), indent=1)
    print("%d nodes, %d parameters -> %s" % (len(out["prompt"]), len((out["meta"].get("params") or {})), sys.argv[4]))
