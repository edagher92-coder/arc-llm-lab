"""Structural tests for workflows/specs/ltx25_upscale.spec.json (the "Upscale x2" video-to-video workflow). Run: python -m pytest -q tests/test_upscale.py

No ComfyUI needed. The spec is built with tools/build_workflow.py against a minimal object_info (only SaveVideo's output_node flag matters, because
every node comes from the spec's "add" block). The built graph is then checked for dangling links, output slots, undeclared/unused placeholders, model
names, a no-local-text-encoder rule, the memory guard in video.resolve_params, and the in-graph frame cap (the ComfyMathExpression strings are
evaluated here with the same function set ComfyUI offers). It cannot prove the nodes accept these inputs on the live ComfyUI: see docs/UPSCALE.md.
"""
import json, math, os, re, sys, types
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, D); sys.path.insert(0, os.path.join(D, "tools"))
import build_workflow as b
import video

SPEC = os.path.join(D, "workflows", "specs", "ltx25_upscale.spec.json")
INFO = {"SaveVideo": {"output_node": True}}
PH = re.compile(r"\{\{(\w+)\}\}")

# Classes this graph uses and where each was confirmed on the PC (read from source / object_info.json on 12 Oct 2026; nothing was run).
CONFIRMED = {
    "LoadVideo": "ComfyUI core comfy_extras/nodes_video.py (object_info)", "GetVideoComponents": "core nodes_video.py (object_info)",
    "CreateVideo": "core nodes_video.py (object_info)", "SaveVideo": "core nodes_video.py (object_info)",
    "GetImageSize": "core nodes_images.py (object_info)", "ImageFromBatch": "core nodes_images.py (object_info)",
    "TrimAudioDuration": "core nodes_audio.py (object_info)", "ComfyMathExpression": "core nodes_math.py (object_info)",
    "PrimitiveFloat": "core nodes_primitive.py (object_info)", "ImageScale": "core nodes.py (object_info)",
    "VAELoader": "core nodes.py (object_info)", "VAEEncode": "core nodes.py (object_info)", "VAEDecodeTiled": "core nodes.py (object_info)",
    "LatentUpscaleModelLoader": "core nodes_hunyuan.py (object_info)", "LTXVLatentUpsampler": "core nodes_lt_upsampler.py (object_info)",
    "LTXVEmptyLatentAudio": "core nodes_lt_audio.py (object_info)", "LTXVConcatAVLatent": "core nodes_lt.py (object_info)",
    "LTXVSeparateAVLatent": "core nodes_lt.py (object_info)", "LTXVDualCFGGuider": "core nodes_lt.py (object_info)",
    "LTXVConditioning": "core nodes_lt.py (object_info)", "RandomNoise": "core nodes_custom_sampler.py (object_info)",
    "KSamplerSelect": "core nodes_custom_sampler.py (object_info)", "ManualSigmas": "core nodes_custom_sampler.py (object_info)",
    "SamplerCustomAdvanced": "core nodes_custom_sampler.py (object_info)",
    "UnetLoaderGGUF": "ComfyUI-GGUF nodes.py line 322 NODE_CLASS_MAPPINGS",
    "ElzLTXAPITextEncode": "elz_nodes/__init__.py line 210 (api_encode.py)",
}
# output slot counts, from object_info.json's `output` lists (GetVideoComponents also has two combo outputs we never use)
OUT_SLOTS = {"LoadVideo": 1, "GetVideoComponents": 5, "GetImageSize": 3, "PrimitiveFloat": 1, "ComfyMathExpression": 3, "ImageFromBatch": 1,
             "TrimAudioDuration": 1, "ImageScale": 1, "VAELoader": 1, "VAEEncode": 1, "LatentUpscaleModelLoader": 1, "LTXVLatentUpsampler": 1,
             "LTXVEmptyLatentAudio": 1, "LTXVConcatAVLatent": 1, "LTXVSeparateAVLatent": 2, "ElzLTXAPITextEncode": 1, "LTXVConditioning": 2,
             "UnetLoaderGGUF": 1, "LTXVDualCFGGuider": 1, "RandomNoise": 1, "KSamplerSelect": 1, "ManualSigmas": 1, "SamplerCustomAdvanced": 2,
             "VAEDecodeTiled": 1, "CreateVideo": 1, "SaveVideo": 0}
# the on-disk model files named in the brief
MODEL_FILES = {"LTX-2.5-Distilled-Q4_K_M.gguf", "ltx-2.5-video-vae-bf16.safetensors", "ltx-2.5-audio-vae-bf16.safetensors",
               "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"}


def spec():
    return json.load(open(SPEC, encoding="utf-8-sig"))


def built():
    wf = b.build(spec(), {}, INFO)
    return wf, wf["prompt"]


def walk(x):
    if isinstance(x, dict):
        for v in x.values(): yield from walk(v)
    elif isinstance(x, list):
        for v in x: yield from walk(v)
    elif isinstance(x, str):
        yield x


def links(g):
    for nid, n in g.items():
        for k, v in n["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                yield nid, k, v[0], v[1]


def test_builds_and_all_nodes_kept():
    s = spec()
    wf, g = built()
    assert set(g) == set(s["add"]), "pruning removed or added nodes"        # every added node feeds the single SaveVideo
    assert sum(1 for n in g.values() if n["class_type"] == "SaveVideo") == 1


def test_every_link_target_exists_and_slot_in_range():
    _, g = built()
    n = 0
    for nid, k, src, slot in links(g):
        n += 1
        assert src in g, "%s.%s links to missing node %s" % (nid, k, src)
        assert src != nid
        cls = g[src]["class_type"]
        assert isinstance(slot, int) and 0 <= slot < OUT_SLOTS[cls], "%s.%s uses slot %s of %s (%s)" % (nid, k, slot, src, cls)
    assert n > 30


def test_graph_is_acyclic():
    _, g = built()
    state = {}
    def visit(k):
        assert state.get(k) != 1, "cycle at %s" % k
        if state.get(k) == 2: return
        state[k] = 1
        for _, _, src, _ in (l for l in links(g) if l[0] == k): visit(src)
        state[k] = 2
    for k in g: visit(k)


def test_every_class_is_confirmed_on_the_pc():
    _, g = built()
    used = {n["class_type"] for n in g.values()}
    assert used == set(CONFIRMED), (used ^ set(CONFIRMED))
    assert used == set(OUT_SLOTS)


def test_cloud_encoder_and_no_local_text_encoder():
    _, g = built()
    classes = [n["class_type"] for n in g.values()]
    assert classes.count("ElzLTXAPITextEncode") == 2
    for bad in ("CLIPLoader", "DualCLIPLoader", "CLIPTextEncode", "LTXAVTextEncoderLoader", "GemmaAPITextEncode", "TextGenerateLTX2Prompt"):
        assert bad not in classes, bad
    assert not any(".safetensors" in s and "gemma" in s.lower() for s in walk(g))
    for n in g.values():
        if n["class_type"] == "ElzLTXAPITextEncode":
            assert n["inputs"]["enhance_prompt"] is False and n["inputs"]["ltx_version"] == "2.5.0" and n["inputs"]["gemma_version"] == "gemma4-12b-ltx-v1"
    pos = [n for n in g.values() if n["class_type"] == "ElzLTXAPITextEncode"]
    assert {n["inputs"]["prompt"] for n in pos} == {"{{prompt}}", "{{negative}}"}


def test_models_are_the_ones_on_disk_and_no_lora():
    _, g = built()
    names = {v for n in g.values() for k, v in n["inputs"].items() if k in ("unet_name", "vae_name", "model_name")}
    assert names == MODEL_FILES, names
    assert "LoraLoader" not in {n["class_type"] for n in g.values()} and not any("lora" in s.lower() for s in walk(g))


def test_pipeline_shape_v2v_x2():
    _, g = built()
    by = {}
    for k, n in g.items(): by.setdefault(n["class_type"], []).append(k)
    # source clip -> VAEEncode -> latent x2 -> AV concat -> sampler -> separate -> tiled decode -> video with the original audio
    enc, up, cat, smp, sep, dec, vid = (g[by[c][0]] for c in ("VAEEncode", "LTXVLatentUpsampler", "LTXVConcatAVLatent", "SamplerCustomAdvanced", "LTXVSeparateAVLatent", "VAEDecodeTiled", "CreateVideo"))
    assert g[enc["inputs"]["pixels"][0]]["class_type"] == "ImageScale"
    assert up["inputs"]["samples"][0] == by["VAEEncode"][0]
    assert cat["inputs"]["video_latent"][0] == by["LTXVLatentUpsampler"][0]
    assert smp["inputs"]["latent_image"][0] == by["LTXVConcatAVLatent"][0]
    assert sep["inputs"]["av_latent"] == [by["SamplerCustomAdvanced"][0], 0]
    assert dec["inputs"]["samples"] == [by["LTXVSeparateAVLatent"][0], 0]
    assert vid["inputs"]["images"][0] == by["VAEDecodeTiled"][0]
    assert g[vid["inputs"]["audio"][0]]["class_type"] == "TrimAudioDuration"
    assert g[g[vid["inputs"]["audio"][0]]["inputs"]["audio"][0]]["class_type"] == "GetVideoComponents"
    sig = g[smp["inputs"]["sigmas"][0]]["inputs"]["sigmas"]
    vals = [float(x) for x in sig.split(",")]
    assert vals == sorted(vals, reverse=True) and vals[-1] == 0.0
    assert g[by["SaveVideo"][0]]["inputs"]["filename_prefix"].startswith("video/gw_")


def test_placeholders_match_declared_params():
    s = spec()
    _, g = built()
    used = {m for t in walk(g) for m in PH.findall(t)}
    declared = set(s["meta"]["params"])
    assert used <= declared, used - declared
    assert used == {"video", "seconds", "prompt", "negative", "seed"}
    assert declared - used == {"width", "height"}                       # guard-only params: not bound into the graph on purpose


def test_meta_shape():
    m = spec()["meta"]
    for k in ("title", "description", "kind", "est_minutes", "params", "fps", "max_px_frames"):
        assert k in m, k
    assert m["kind"] == "upscale" and m["input"] == "video"
    assert isinstance(m["est_minutes"], (int, float)) and not isinstance(m["est_minutes"], bool) and m["est_minutes"] > 0
    assert "unmeasured" in m["est_minutes_note"].lower()
    assert m["params"]["video"] == {**m["params"]["video"], "type": "video", "required": True}
    for k, p in m["params"].items():
        assert p["type"] in ("str", "int", "float", "image", "video"), k
        if "default" in p and p["type"] in ("int", "float"):
            assert p.get("min", p["default"]) <= p["default"] <= p.get("max", p["default"]), k
    assert m["max_px_frames"] * 4 == 60000000                          # source px-frames x 4 = the 60 M output guard
    for pr in m["presets"]:
        assert set(pr["params"]) <= set(m["params"])
    assert video.est_minutes({"meta": m}) == 6


def _wf():
    return {"meta": spec()["meta"], "prompt": built()[1]}


def test_guard_refuses_over_60m_output_and_suggests_trimming():
    cfg = types.SimpleNamespace(max_px_frames=60000000)
    ok, _ = video.resolve_params(_wf(), {"video": "C:/x/a.mp4", "width": 768, "height": 416, "seconds": 1.7}, cfg)    # 768x416 x 41 frames
    assert ok["seconds"] == 1.6667 and round(ok["seconds"] * 24) + 1 == 41 and 768 * 416 * 41 * 4 <= 60000000
    try:
        video.resolve_params(_wf(), {"video": "C:/x/a.mp4", "width": 768, "height": 416, "seconds": 2}, cfg)         # 49 frames: 62.6 M at the output
        raise AssertionError("2 s of 768x416 should be refused")
    except video.VideoError as e:
        assert "over this workflow's limit" in str(e) and "Try at most" in str(e) and "41 frames" in str(e), str(e)
    for w, h in ((960, 544), (1280, 704)):                               # a bigger source does not fit even at the shortest length offered here
        try:
            video.resolve_params(_wf(), {"video": "C:/x/a.mp4", "width": w, "height": h, "seconds": 1.7}, cfg)
            raise AssertionError("%dx%d accepted" % (w, h))
        except video.VideoError:
            pass


def test_missing_source_size_is_an_error_not_a_bypass():
    try:
        video.resolve_params(_wf(), {"video": "C:/x/a.mp4", "seconds": 1.7}, None)
        raise AssertionError("width/height are required so the guard cannot be skipped")
    except video.VideoError as e:
        assert "required" in str(e)


def test_fill_graph_leaves_no_placeholder():
    cfg = types.SimpleNamespace(max_px_frames=60000000)
    vals, _ = video.resolve_params(_wf(), {"video": "gw_abc.mp4", "width": 768, "height": 416, "seconds": 1.7, "seed": 7}, cfg)
    vals["video"] = "gw_abc.mp4"                                         # what the worker does after staging the clip into ComfyUI's input folder
    g = video.fill_graph(_wf()["prompt"], vals)
    assert not any(PH.search(t) for t in walk(g))
    lv = [n for n in g.values() if n["class_type"] == "LoadVideo"][0]
    assert lv["inputs"]["file"] == "gw_abc.mp4"
    assert [n for n in g.values() if n["class_type"] == "RandomNoise"][0]["inputs"]["noise_seed"] == 7


MATH = {"min": min, "max": max, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil}


def _expr(g, nid, **v):
    n = g[nid]["inputs"]
    r = eval(n["expression"], {"__builtins__": {}}, {**MATH, **v})      # the same function set as comfy_extras/nodes_math.py MATH_FUNCTIONS
    return r


def test_in_graph_frame_cap_matches_the_guard():
    _, g = built()
    ids = {n["inputs"]["expression"]: k for k, n in g.items() if n["class_type"] == "ComfyMathExpression"}
    cap = [k for k, n in g.items() if n["class_type"] == "ComfyMathExpression" and "60000000" in n["inputs"]["expression"]][0]
    def frames(src_frames, want, w, h): return int(_expr(g, cap, a=src_frames, b=want, c=w, d=h))
    assert frames(97, 41, 768, 416) == 41                               # trim to the request
    assert frames(33, 41, 768, 416) == 33                               # shorter source: keep it (8n+1 from the gateway)
    assert frames(97, 97, 768, 416) == 41                               # asked for more than fits: capped at the guard, 41 frames
    assert frames(97, 97, 1536, 832) == 9                               # a 1536x832 source (3072x1664 out) is cut to 9 frames, still within the cap
    for src in (97, 193):
        for w, h in ((768, 416), (640, 352), (512, 288)):
            n = frames(src, 1000, w, h)
            assert (n - 1) % 8 == 0 and w * h * n * 4 <= 60000000, (w, h, n)
    fps = _expr(g, [k for k, n in g.items() if n["class_type"] == "ComfyMathExpression" and n["inputs"]["expression"] == "a"][0], a=24.0)
    assert fps == 24.0 and ids["round(a*b)+1"]
    assert _expr(g, ids["round(a*b)+1"], a=1.6667, b=24.0) == 41
    assert _expr(g, ids["floor(a/32)*32"], a=770) == 768


def test_links_to_spec_params_ranges():
    p = spec()["meta"]["params"]
    assert p["seconds"]["max"] <= 4 and p["width"]["multiple_of"] == 32 and p["height"]["multiple_of"] == 32
    assert p["prompt"]["max_len"] <= 1500 and "default" in p["prompt"], "an empty prompt would be sent to the API, so a default is required"


if __name__ == "__main__":
    import traceback
    bad = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_") and callable(f):
            try: f(); print("ok  ", k)
            except Exception: bad += 1; print("FAIL", k); traceback.print_exc()
    sys.exit(1 if bad else 0)
