"""Convert a ComfyUI *UI-format* workflow (the .json a template or the editor's Save gives) into the *API-format* graph that POST /prompt takes.

Why: the gateway submits jobs headlessly, and the official templates only ship in UI format (with subgraphs, widget lists and reroutes).
The editor's "Export (API)" does this in the browser; this script does it offline from the template and ComfyUI's own /object_info, so no
browser session on the PC is needed. It understands: subgraphs (flattened, ids become "outer:inner" exactly like the editor), reroutes,
widgets_values in object_info order (including control_after_generate and image-upload extras), dynamic combos ("scale dimensions" style
nodes), autogrow inputs (values.a), muted nodes (dropped) and bypassed nodes (passed through). Only nodes an output node depends on are kept.

Usage: python comfy_ui_to_api.py template.json object_info.json out.json
"""
import json, sys

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
SKIP_TYPES = {"Note", "MarkdownNote", "Reroute"}


class ConvertError(Exception):
    pass


def _links(lst):
    out = {}
    for l in lst or []:
        if isinstance(l, dict):
            out[l["id"]] = (l["origin_id"], l["origin_slot"], l["target_id"], l["target_slot"])
        else:
            out[l[0]] = (l[1], l[2], l[3], l[4])
    return out


def _is_widget(spec):
    t = spec[0] if isinstance(spec, (list, tuple)) and spec else spec
    return isinstance(t, list) or t == "COMFY_DYNAMICCOMBO_V3" or (isinstance(t, str) and all(p in WIDGET_TYPES for p in t.split(",")))


def _extra_after(spec):
    """How many extra widgets_values entries follow this widget in a saved workflow."""
    cfg = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    n = 0
    if cfg.get("control_after_generate"):
        n += 1
    if cfg.get("image_upload") or cfg.get("video_upload") or cfg.get("audio_upload"):
        n += 1
    return n


class Converter:
    def __init__(self, ui, info, warn=None):
        self.info, self.warn = info, warn or (lambda m: None)
        self.sgs = {s["id"]: s for s in (ui.get("definitions") or {}).get("subgraphs", [])}
        self.out = {}
        self.pending = []
        self.root = {"nodes": {n["id"]: n for n in ui["nodes"]}, "links": _links(ui.get("links")), "prefix": "", "parent": None, "inst": None, "sg": None}

    # ---- link resolution: returns ("node", id, slot) or ("value", v)
    def resolve(self, scope, node_id, slot):
        if scope["sg"] is not None and node_id == -10:                       # the subgraph's input pseudo-node
            return self.sg_input(scope, slot)
        node = scope["nodes"].get(node_id)
        if node is None:
            raise ConvertError("dangling link to node %r" % (node_id,))
        t = node["type"]
        if t == "Reroute":
            ins = node.get("inputs") or []
            if not ins or ins[0].get("link") is None:
                raise ConvertError("reroute %s has no input" % node_id)
            o, s, _, _ = scope["links"][ins[0]["link"]]
            return self.resolve(scope, o, s)
        if t in self.sgs:                                                     # a subgraph instance: look inside at what feeds output `slot`
            inner = self.enter(scope, node)
            for lid, (o, s, tgt, ts) in inner["links"].items():
                if tgt == -20 and ts == slot:
                    return self.resolve(inner, o, s)
            raise ConvertError("subgraph %s has nothing on output %d" % (node_id, slot))
        if node.get("mode") == 2:                                             # muted: it produces nothing, so the input it fed is left unconnected
            return ("none", None)
        if node.get("mode") == 4:                                             # bypassed: the first input of matching type passes through
            return self.bypass(scope, node, slot)
        return ("node", scope["prefix"] + str(node_id), slot)

    def bypass(self, scope, node, slot):
        outs = node.get("outputs") or []
        want = outs[slot]["type"] if slot < len(outs) else None
        for i in node.get("inputs") or []:
            if i.get("link") is not None and i.get("type") == want:
                o, s, _, _ = scope["links"][i["link"]]
                return self.resolve(scope, o, s)
        return ("none", None)                                                 # nothing to pass through: the editor leaves the input unconnected

    def enter(self, scope, inst):
        key = ("scope", id(scope), inst["id"])
        if key not in self.__dict__.setdefault("_scopes", {}):
            sg = self.sgs[inst["type"]]
            self._scopes[key] = {"nodes": {n["id"]: n for n in sg["nodes"]}, "links": _links(sg.get("links")), "prefix": scope["prefix"] + str(inst["id"]) + ":",
                                 "parent": scope, "inst": inst, "sg": sg}
        return self._scopes[key]

    def sg_input(self, scope, slot):
        sg, inst, parent = scope["sg"], scope["inst"], scope["parent"]
        name = sg["inputs"][slot]["name"]
        for i in inst.get("inputs") or []:                                    # wired from outside?
            if i.get("name") == name and i.get("link") is not None:
                o, s, _, _ = parent["links"][i["link"]]
                return self.resolve(parent, o, s)
        wv, idx = inst.get("widgets_values") or [], 0                         # otherwise a promoted widget. Every widget-typed input owns a slot in
        for k, inp in enumerate(sg["inputs"]):                                # widgets_values, even one that is currently wired from outside.
            if all(p in WIDGET_TYPES for p in inp["type"].split(",")):
                if k == slot:
                    if idx >= len(wv):
                        raise ConvertError("subgraph input %s has no value" % name)
                    return ("value", wv[idx])
                idx += 1
        raise ConvertError("subgraph input %s is not connected" % name)

    # ---- node conversion
    def convert_scope(self, scope):
        for nid, n in scope["nodes"].items():
            t = n["type"]
            if t in SKIP_TYPES or n.get("mode") in (2, 4):
                continue
            if t in self.sgs:
                self.convert_scope(self.enter(scope, n))
                continue
            if t not in self.info:
                raise ConvertError("node type %r is not installed in this ComfyUI" % t)
            self.out[scope["prefix"] + str(nid)] = self.node(scope, n)

    def node(self, scope, n):
        info = self.info[n["type"]]
        inputs, linked = {}, {}
        for i in n.get("inputs") or []:
            if i.get("link") is not None:
                o, s, _, _ = scope["links"][i["link"]]
                linked[i["name"]] = self.resolve(scope, o, s)
        order = [(k, info["input"]["required"][k]) for k in info["input_order"].get("required", [])] + \
                [(k, info["input"]["optional"][k]) for k in info["input_order"].get("optional", [])] if "optional" in info["input"] else \
                [(k, info["input"]["required"][k]) for k in info["input_order"].get("required", [])]
        wv, pos = list(n.get("widgets_values") or []), 0

        def take(name, spec, prefix=""):
            nonlocal pos
            full = prefix + name
            if spec[0] == "COMFY_DYNAMICCOMBO_V3":
                key = wv[pos] if pos < len(wv) else None
                pos += 1
                if full not in linked and key is not None:
                    inputs[full] = key
                opt = next((o for o in spec[1]["options"] if o["key"] == key), None)
                if opt:
                    for grp in ("required", "optional"):
                        for k, sp in (opt["inputs"].get(grp) or {}).items():
                            if _is_widget(sp):
                                take(k, sp, full + ".")
                return
            if _is_widget(spec):
                val = wv[pos] if pos < len(wv) else None
                pos += 1 + _extra_after(spec)
                if full not in linked and val is not None:
                    inputs[full] = val

        for name, spec in order:
            take(name, spec)
        for name, r in linked.items():
            if r[0] == "node":
                inputs[name] = [r[1], r[2]]
            elif r[0] == "value":
                inputs[name] = r[1]
        return {"class_type": n["type"], "inputs": inputs, "_meta": {"title": n.get("title") or n["type"]}}

    def prune(self):
        self.out = prune_graph(self.out, self.info)

    def run(self):
        self.convert_scope(self.root)
        self.prune()
        return self.out


def prune_graph(api, info):
    """Keep only the output nodes and what they depend on (ComfyUI would not run the rest, but a smaller graph is easier to read and edit)."""
    outs = [k for k, v in api.items() if (info.get(v["class_type"]) or {}).get("output_node")]
    if not outs:
        raise ConvertError("no output node (SaveVideo etc.) in this workflow")
    keep, stack = set(), list(outs)
    while stack:
        k = stack.pop()
        if k in keep:
            continue
        keep.add(k)
        for v in api[k]["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in api:
                stack.append(v[0])
    return {k: api[k] for k in api if k in keep}


def convert(ui, info, warn=None):
    return Converter(ui, info, warn).run()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    api = convert(json.load(open(sys.argv[1], encoding="utf-8-sig")), json.load(open(sys.argv[2], encoding="utf-8-sig")))
    json.dump(api, open(sys.argv[3], "w", encoding="utf-8"), indent=1)
    print("%d nodes written to %s" % (len(api), sys.argv[3]))
