"""Tests for tools/comfy_ui_to_api.py and tools/build_workflow.py on a small hand-made UI workflow. Run: python tests/test_workflow_tools.py"""
import copy, json, os, sys, traceback
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(D, "tools"))
import comfy_ui_to_api as c, build_workflow as b

INFO = {
 "PrimitiveStringMultiline": {"input": {"required": {"value": ["STRING", {}]}}, "input_order": {"required": ["value"]}},
 "PrimitiveInt": {"input": {"required": {"value": ["INT", {"control_after_generate": "fixed"}]}}, "input_order": {"required": ["value"]}},
 "RandomNoise": {"input": {"required": {"noise_seed": ["INT", {"control_after_generate": True}]}}, "input_order": {"required": ["noise_seed"]}},
 "Enc": {"input": {"required": {"text": ["STRING", {}], "clip": ["CLIP", {}]}}, "input_order": {"required": ["text", "clip"]}},
 "Loader": {"input": {"required": {"name": [["a.safetensors", "b.safetensors"], {}]}}, "input_order": {"required": ["name"]}},
 "Size": {"input": {"required": {"w": ["INT", {}], "rate": ["FLOAT,INT", {}], "batch": ["INT", {}]}}, "input_order": {"required": ["w", "rate", "batch"]}},
 "Resize": {"input": {"required": {"mode": ["COMFY_DYNAMICCOMBO_V3", {"options": [{"key": "dims", "inputs": {"required": {"width": ["INT", {}], "height": ["INT", {}]}}}, {"key": "scale", "inputs": {"required": {"factor": ["FLOAT", {}]}}}]}], "image": ["IMAGE", {}]}},
            "input_order": {"required": ["image", "mode"]}},
 "Save": {"input": {"required": {"video": ["IMAGE", {}], "prefix": ["STRING", {}]}}, "input_order": {"required": ["video", "prefix"]}, "output_node": True},
 "Preview": {"input": {"required": {"source": ["*", {}]}}, "input_order": {"required": ["source"]}, "output_node": True},
}

def ui():
    sg = {"id": "sg-1", "name": "Pipe", "inputs": [{"name": "text", "type": "STRING"}, {"name": "w", "type": "INT"}, {"name": "img", "type": "IMAGE"}, {"name": "mdl", "type": "COMBO"}],
          "outputs": [{"name": "OUT", "type": "IMAGE"}, {"name": "ENC", "type": "STRING"}, {"name": "SZ", "type": "INT"}],
          "nodes": [
              {"id": 1, "type": "Enc", "mode": 0, "widgets_values": ["ignored"], "inputs": [{"name": "text", "link": 10, "widget": {"name": "text"}}, {"name": "clip", "link": 13}]},
              {"id": 2, "type": "Size", "mode": 0, "widgets_values": [64, 24, 1], "inputs": [{"name": "w", "link": 11, "widget": {"name": "w"}}]},
              {"id": 3, "type": "Loader", "mode": 0, "widgets_values": ["a.safetensors"], "inputs": [{"name": "name", "link": 12, "widget": {"name": "name"}}]},
              {"id": 4, "type": "Reroute", "mode": 0, "inputs": [{"name": "", "link": 14}], "outputs": [{"name": "", "type": "IMAGE"}]},
              {"id": 5, "type": "Resize", "mode": 0, "widgets_values": ["dims", 320, 240], "inputs": [{"name": "image", "link": 15}]},
              {"id": 6, "type": "Note", "mode": 0},
          ],
          "links": [{"id": 10, "origin_id": -10, "origin_slot": 0, "target_id": 1, "target_slot": 0}, {"id": 11, "origin_id": -10, "origin_slot": 1, "target_id": 2, "target_slot": 0},
                    {"id": 12, "origin_id": -10, "origin_slot": 3, "target_id": 3, "target_slot": 0}, {"id": 13, "origin_id": 3, "origin_slot": 0, "target_id": 1, "target_slot": 1},
                    {"id": 14, "origin_id": -10, "origin_slot": 2, "target_id": 4, "target_slot": 0}, {"id": 15, "origin_id": 4, "origin_slot": 0, "target_id": 5, "target_slot": 0},
                    {"id": 16, "origin_id": 5, "origin_slot": 0, "target_id": -20, "target_slot": 0},
                    {"id": 17, "origin_id": 1, "origin_slot": 0, "target_id": -20, "target_slot": 1}, {"id": 18, "origin_id": 2, "origin_slot": 0, "target_id": -20, "target_slot": 2}]}
    return {"nodes": [
        {"id": 100, "type": "PrimitiveStringMultiline", "mode": 0, "widgets_values": ["a fox"], "inputs": []},
        {"id": 101, "type": "PrimitiveInt", "mode": 0, "widgets_values": [1280, "fixed"], "inputs": []},
        {"id": 102, "type": "RandomNoise", "mode": 0, "widgets_values": [7, "randomize"], "inputs": []},
        # the subgraph instance: prompt wired from node 100, w is a promoted widget (wired AND still occupying a slot), image wired from 103
        {"id": 200, "type": "sg-1", "mode": 0, "widgets_values": ["text-in-widget", 999, "b.safetensors"],
         "inputs": [{"name": "text", "link": 1}, {"name": "w", "link": 2}, {"name": "img", "link": 3}, {"name": "mdl"}]},
        {"id": 103, "type": "Loader", "mode": 0, "widgets_values": ["b.safetensors"], "inputs": []},
        {"id": 300, "type": "Save", "mode": 0, "widgets_values": ["video/x"], "inputs": [{"name": "video", "link": 4}]},
        {"id": 301, "type": "Preview", "mode": 0, "inputs": [{"name": "source", "link": 5}]},
        {"id": 304, "type": "Preview", "mode": 0, "inputs": [{"name": "source", "link": 6}]},
        {"id": 302, "type": "MarkdownNote", "mode": 0},
        {"id": 303, "type": "Loader", "mode": 0, "widgets_values": ["a.safetensors"], "inputs": []},   # unused: pruned
    ], "links": [[1, 100, 0, 200, 0, "STRING"], [2, 101, 0, 200, 1, "INT"], [3, 103, 0, 200, 2, "IMAGE"], [4, 200, 0, 300, 0, "IMAGE"], [5, 200, 1, 301, 0, "STRING"], [6, 200, 2, 304, 0, "INT"]],
        "definitions": {"subgraphs": [sg]}}

def test_convert():
    api = c.convert(ui(), INFO)
    assert set(api) == {"200:1", "200:2", "200:3", "200:5", "100", "101", "103", "300", "301", "304"}, sorted(api)       # Note/MarkdownNote/Reroute/unused dropped
    assert api["200:1"]["inputs"]["text"] == ["100", 0]                    # a subgraph input wired from outside resolves to that node
    assert api["200:2"]["inputs"] == {"w": ["101", 0], "rate": 24, "batch": 1}, api["200:2"]   # FLOAT,INT is a widget; wired widgets still own a value slot
    assert api["200:3"]["inputs"]["name"] == "b.safetensors"               # promoted widget: 3rd widget-typed input, value slot index 3-1=2 ("b.safetensors")
    assert api["200:5"]["inputs"] == {"image": ["103", 0], "mode": "dims", "mode.width": 320, "mode.height": 240}   # reroute followed; dynamic combo flattened
    assert api["100"]["inputs"] == {"value": "a fox"} and api["101"]["inputs"] == {"value": 1280}   # control_after_generate extras skipped
    assert api["300"]["inputs"] == {"video": ["200:5", 0], "prefix": "video/x"}

def test_missing_node_type():
    u = ui(); u["nodes"].append({"id": 999, "type": "NotInstalled", "mode": 0, "inputs": []})
    try: c.convert(u, INFO); raise AssertionError("accepted an uninstalled node")
    except c.ConvertError as e: assert "NotInstalled" in str(e)

def test_muted_and_bypassed():
    u = ui(); u["nodes"][1]["mode"] = 2                                      # muted: dropped; whatever it fed loses that input
    api = c.convert(u, INFO); assert "101" not in api and "w" not in api["200:2"]["inputs"], api["200:2"]
    u = ui(); sg = u["definitions"]["subgraphs"][0]; sg["nodes"][4]["mode"] = 4  # bypassed Resize: IMAGE in -> IMAGE out passes straight through
    sg["nodes"][4]["outputs"] = [{"type": "IMAGE"}]; sg["nodes"][4]["inputs"][0]["type"] = "IMAGE"
    api = c.convert(u, INFO); assert api["300"]["inputs"]["video"] == ["103", 0]

def test_build_workflow():
    api = c.convert(ui(), INFO)
    spec = {"meta": {"params": {"prompt": {"type": "str", "required": True}, "width": {"type": "int"}, "seed": {"type": "int"}}},
            "set": {"200:1.text": ["100", 0], "300.prefix": "video/gw"}, "drop": ["301"],
            "bind": {"prompt": ["300.prefix"], "width": ["101.value", "200:2.w"], "seed": ["200:2.batch"]}}
    w = b.build(spec, api, INFO)
    g = w["prompt"]; assert "301" not in g and "103" in g and "303" not in g
    assert g["300"]["inputs"]["prefix"] == "{{prompt}}" and g["200:2"]["inputs"]["w"] == "{{width}}" and "101" not in g   # the placeholder replaced the link, so its source node is pruned
    assert all("_meta" not in n for n in g.values())
    import video                                                            # the produced file is what the queue loads and fills
    vals, files = video.resolve_params(w, {"prompt": "hi", "width": 640}, None); filled = video.fill_graph(g, vals)
    assert filled["300"]["inputs"]["prefix"] == "hi" and filled["200:2"]["inputs"]["w"] == 640 and isinstance(filled["200:2"]["inputs"]["w"], int)
    try: b.build({"bind": {"nope": ["100.value"]}, "meta": {"params": {}}}, api, INFO); raise AssertionError("bound an undeclared parameter")
    except c.ConvertError as e: assert "not declared" in str(e)

# ---- the two-process (stages) specs, built from the real spec files against a graph shaped like the LTX-2.5 one ----
SPECS = os.path.join(D, "workflows", "specs")
Q6_INFO = {"SaveVideo": {"output_node": True}, "Preview": {"output_node": True}, "ElzSaveConditioning": {"output_node": True}}      # as /object_info reports OUTPUT_NODE

def q6_graph():
    n = lambda c, **i: {"class_type": c, "inputs": i, "_meta": {"title": c}}
    return {"405:350": n("LTXAVTextEncoderLoader", text_encoder="gemma.safetensors"), "405:376": n("PrimitiveStringMultiline", value="p"),
            "405:364": n("CLIPTextEncode", text="enhanced", clip=["405:350", 0]), "405:373": n("CLIPTextEncode", text="neg", clip=["405:350", 0]),
            "405:381": n("Preview", source=["405:376", 0]), "405:366": n("LTXVConditioning", positive=["405:364", 0], negative=["405:373", 0], frame_rate=24),
            "405:372": n("PrimitiveInt", value=768), "405:360": n("PrimitiveInt", value=512), "405:362": n("PrimitiveInt", value=4),
            "405:338": n("RandomNoise", noise_seed=1), "405:339": n("RandomNoise", noise_seed=2), "405:384": n("UNETLoader", unet_name="x.safetensors"),
            "405:340": n("Sampler", model=["405:384", 0], pos=["405:366", 0], neg=["405:366", 1], n1=["405:338", 0], n2=["405:339", 0], w=["405:372", 0], h=["405:360", 0], s=["405:362", 0]),
            "405:358": n("AudioDecode", samples=["405:340", 0]), "405:370": n("CreateVideo", images=["405:340", 1], audio=["405:358", 0]),
            "75": n("SaveVideo", video=["405:370", 0], filename_prefix="video/x")}

def spec_file(name): return json.load(open(os.path.join(SPECS, name + ".spec.json"), encoding="utf-8"))
def classes(g): return sorted(v["class_type"] for v in g.values())

def test_q6_stage_specs_build():
    enc = b.build(spec_file("ltx25g_q6_enc"), q6_graph(), Q6_INFO)["prompt"]
    assert classes(enc) == ["CLIPTextEncode", "CLIPTextEncode", "ElzSaveConditioning", "LTXAVTextEncoderLoader", "PrimitiveStringMultiline"], classes(enc)    # encoder only: no UNet, sampler or SaveVideo
    assert enc["405:902"]["inputs"] == {"positive": ["405:364", 0], "negative": ["405:373", 0], "prompt": "{{prompt}}", "name": "cond"}, enc["405:902"]
    assert enc["405:373"]["inputs"]["text"] == "{{negative}}" and enc["405:376"]["inputs"]["value"] == "{{prompt}}" and enc["405:364"]["inputs"]["text"] == ["405:376", 0]
    smp = b.build(spec_file("ltx25g_q6_smp"), q6_graph(), Q6_INFO)["prompt"]
    assert "405:364" not in smp and "405:373" not in smp and "405:350" not in smp and "405:381" not in smp, sorted(smp)         # no text encoder in stage 2
    assert smp["405:366"]["inputs"]["positive"] == ["405:901", 0] and smp["405:366"]["inputs"]["negative"] == ["405:901", 1], smp["405:366"]
    assert smp["405:901"]["class_type"] == "ElzLoadConditioning" and smp["405:901"]["inputs"] == {"prompt": "{{prompt}}", "name": "cond"}
    assert smp["405:384"] == {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "LTX-2.5-Distilled-Q6_K.gguf"}}
    assert smp["405:370"]["inputs"]["audio"] == ["405:900", 0] and smp["405:900"]["class_type"] == "ElzAudioNanGuard" and smp["75"]["inputs"]["filename_prefix"] == "video/gw_ltx25q6_t2v"
    assert {"405:372", "405:360", "405:362", "405:338", "405:339"} <= set(smp) and smp["405:372"]["inputs"]["value"] == "{{width}}"
    assert all("_meta" not in v for g in (enc, smp) for v in g.values())

def test_q6_parent_spec_and_end_to_end():
    import tempfile, video
    parent = b.build(spec_file("ltx25q6_t2v"), None, None)
    assert parent["prompt"] == {} and parent["meta"]["stages"] == ["ltx25g_q6_enc", "ltx25g_q6_smp"] and parent["meta"]["params"]["prompt"]["required"]
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "stages"))
    json.dump(parent, open(os.path.join(d, "ltx25q6_t2v.json"), "w"))
    for name in parent["meta"]["stages"]:
        json.dump(b.build(spec_file(name), q6_graph(), Q6_INFO), open(os.path.join(d, "stages", name + ".json"), "w"))
    wfs = video.load_workflows(d); assert list(wfs) == ["ltx25q6_t2v"], list(wfs)               # stages are not listed as workflows
    assert video.stage_names(wfs["ltx25q6_t2v"]) == ["ltx25g_q6_enc", "ltx25g_q6_smp"]
    vals, files = video.resolve_params(wfs["ltx25q6_t2v"], {"prompt": "a fox", "seconds": 3, "width": 960, "height": 544}, None)
    for name in parent["meta"]["stages"]:
        g = video.fill_graph(video.load_stage(d, name)["prompt"], vals)
        assert "{{" not in json.dumps(g), name
    smp = video.fill_graph(video.load_stage(d, "ltx25g_q6_smp")["prompt"], vals)
    assert smp["405:901"]["inputs"]["prompt"] == "a fox" and smp["405:372"]["inputs"]["value"] == 960 and isinstance(smp["405:372"]["inputs"]["value"], int)
    for name in parent["meta"]["stages"]:                                                       # every placeholder a stage uses is a parameter of the parent
        used = video.PH.findall(json.dumps(video.load_stage(d, name)["prompt"])); assert set(used) <= set(parent["meta"]["params"]), (name, used)

def test_staged_spec_rules():
    for spec in ({"stages": []}, {"stages": "a"}, {"stages": ["a", "a"]}, {"stages": ["../x"]}, {"stages": ["a"], "set": {"1.x": 1}}):
        try: b.build(dict(spec, meta={}), None, None); raise AssertionError("accepted %r" % spec)
        except c.ConvertError: pass
    api = q6_graph()
    for bad in ({"rewire": {"405:364:0": ["nope", 0]}}, {"rewire": {"nope:0": ["405:376", 0]}}, {"keep_outputs": ["nope"]}):
        try: b.build(dict(bad, meta={}), api, Q6_INFO); raise AssertionError("accepted %r" % bad)
        except c.ConvertError: pass

if __name__ == "__main__":
    sys.path.insert(0, D)
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
