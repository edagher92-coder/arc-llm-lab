#!/usr/bin/env python3
"""Convert Lightricks' official LTX-2.5 ComfyUI workflows (UI/litegraph format)
into presets for the Arc PC: GGUF transformer, int8 Gemma encoder, our VAE names.

Usage:
    python tools/convert_ltx_presets.py --src <ComfyUI-LTXVideo clone> [--out presets/ltx25]

stdlib only; output is deterministic (sorted file order, sorted keys in index).
Only the loader nodes / model filenames are changed; topology and all other
widget values are kept as the official calibrated defaults.
"""
import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

WF_REL = Path("example_workflows") / "2.5"

# ---- our files (names exactly as on the PC) --------------------------------
OUR_GGUF = "LTX-2.5-Distilled-Q4_K_M.gguf"
OUR_TEXT_ENCODER = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
OUR_VIDEO_VAE = "ltx-2.5-video-vae-bf16.safetensors"
OUR_AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"
OUR_UPSCALER = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
ENHANCER_ENCODER = "gemma4_e2b_it_bf16.safetensors"  # prompt enhancer; not in our confirmed file list

SRC_TRANSFORMER = "ltx-2.5-22b-distilled-transformer-bf16.safetensors"
SRC_TEXT_ENCODER = "gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"

# exact-string replacements applied to every widget value
EXACT_MAP = {
    SRC_TRANSFORMER: OUR_GGUF,
    SRC_TEXT_ENCODER: OUR_TEXT_ENCODER,
    # VAE / upscaler names already identical upstream; mapped for explicitness
    "ltx-2.5-video-vae-bf16.safetensors": OUR_VIDEO_VAE,
    "ltx-2.5-audio-vae-bf16.safetensors": OUR_AUDIO_VAE,
    "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors": OUR_UPSCALER,
}
# upstream model-download entries (properties.models) we must not advertise
DROP_MODEL_NAMES = {SRC_TRANSFORMER, SRC_TEXT_ENCODER}

LOADER_TYPES = {"UNETLoader", "CheckpointLoaderSimple", "CheckpointLoader", "LTXVCheckpointLoader"}

# ---- node-type classification ---------------------------------------------
LTXVIDEO_NODES = {
    "GemmaAPITextEncode", "LTXAddVideoICLoRAGuide", "LTXAddVideoICLoRAGuideAdvanced", "LTXFloatToInt",
    "LTXICLoRALoaderModelOnly", "LTXVAudioOnlyEmptyVideoLatent", "LTXVAudioOnlyModel", "LTXVDilateVideoMask",
    "LTXVDrawTracks", "LTXVGetTilingSizes", "LTXVHDRDecodePostprocess", "LTXVImgToVideoConditionOnly",
    "LTXVInpaintPreprocess", "LTXVLaplacianPyramidBlend", "LTXVLoadConditioning", "LTXVLoadEXRSequence",
    "LTXVSDRToHDRWorkingSpace", "LTXVSaveHLG", "LTXVSetAudioRefTokens", "LTXVSparseTrackEditor",
    "LTXVTiledFusionSampler", "LTXVVAEForceFloat32",
}  # verified present in Lightricks/ComfyUI-LTXVideo source
PACKS = {  # node type -> custom pack (INFERRED for the non-LTXVideo packs)
    **{t: "ComfyUI-LTXVideo" for t in LTXVIDEO_NODES},
    "UnetLoaderGGUF": "ComfyUI-GGUF",
    "DWPreprocessor": "comfyui_controlnet_aux",
    "CannyEdgePreprocessor": "comfyui_controlnet_aux",
    "LoadVideoDepthAnythingModel": "ComfyUI-VideoDepthAnything",
    "VideoDepthAnythingProcess": "ComfyUI-VideoDepthAnything",
    "VideoDepthAnythingOutput": "ComfyUI-VideoDepthAnything",
}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-")
FRONTEND_ONLY = {"Reroute", "Note", "MarkdownNote"}
# flagged for Arc/XPU review (kept in the graph, not removed)
XPU_RISK_TYPES = {
    "DWPreprocessor": "controlnet_aux pose models often use onnxruntime-gpu (CUDA); verify on XPU or run CPU",
    "CannyEdgePreprocessor": "controlnet_aux; CPU-capable, low risk",
    "LoadVideoDepthAnythingModel": "Video-Depth-Anything pack; may assume CUDA/xformers, verify on XPU",
    "VideoDepthAnythingProcess": "Video-Depth-Anything pack; may assume CUDA, verify on XPU",
    "GemmaAPITextEncode": "cloud LTX API path; inert unless the ckpt name contains 'ltxv_'; needs an API key, not used locally",
}
NVIDIA_STR_RE = re.compile(r"cuda|nvfp4|fp8|tensorrt|sageattn|flash_attn", re.I)

# ---- IC-LoRA mapping (graph-embedded name -> our expected 2.5 filename) -----
LORA_NAME_FMT = "ltx-2.5-22b-ic-lora-{}-0.9.safetensors"
LORA_MAP = {  # short name -> (filename, status)
    "alpha-gen": (LORA_NAME_FMT.format("alpha-gen"), "VERIFIED"),
}
for _n in ("restore", "refine-details", "deblur", "decompression", "colorization", "sdr-to-hdr",
           "day-to-night", "clean-plate", "water-simulation", "layout-to-render", "ingredients",
           "pixel-spatial-upscaler"):
    LORA_MAP[_n] = (LORA_NAME_FMT.format(_n), "INFERRED")


def lora_short(name):
    """Best-effort short name for a LoRA file embedded in an official graph."""
    low = name.lower()
    for key in ("sdr-to-hdr", "day-to-night", "refine-details", "general_refine", "in-outpainting",
                "motion-track", "union-control", "ingredients", "deblur"):
        if key in low:
            return {"general_refine": "refine-details", "in-outpainting": "in-outpainting",
                    "motion-track": "motion-track", "union-control": "union-control"}.get(key, key)
    return low


# ---- helpers ----------------------------------------------------------------
def git_sha(src):
    out = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else "UNKNOWN"


def purposes_from_readme(readme):
    """basename -> 'What it does' text from the README tables (first occurrence wins)."""
    res = {}
    for line in readme.splitlines():
        m = re.match(r"\|\s*\[([^\]]+\.json)\]\([^)]*\)\s*\|\s*(.+?)\s*\|\s*$", line)
        if m and m.group(1) not in res and not m.group(2).startswith("-"):
            res[m.group(1)] = re.sub(r"\*\*", "", m.group(2))
    return res


def iter_scopes(doc):
    """Yield (scope_name, node_list, link_list) for the top level and every subgraph."""
    yield "top", doc.get("nodes", []), doc.get("links", [])
    for sg in doc.get("definitions", {}).get("subgraphs", []):
        yield "subgraph:" + sg.get("name", sg.get("id", "?")), sg.get("nodes", []), sg.get("links", [])


def map_value(v):
    if isinstance(v, str):
        if v in EXACT_MAP:
            return EXACT_MAP[v]
        if SRC_TRANSFORMER in v or SRC_TEXT_ENCODER in v:  # note text / urls
            v = re.sub(r"https?://\S*" + re.escape(SRC_TRANSFORMER), "(local GGUF, see presets/ltx25/README.md)", v)
            v = re.sub(r"https?://\S*" + re.escape(SRC_TEXT_ENCODER), "(local int8 encoder, see presets/ltx25/README.md)", v)
            v = v.replace(SRC_TRANSFORMER, OUR_GGUF).replace(SRC_TEXT_ENCODER, OUR_TEXT_ENCODER)
        return v
    if isinstance(v, list):
        return [map_value(x) for x in v]
    if isinstance(v, dict):
        return {k: map_value(x) for k, x in v.items()}
    return v


def scrub_models(obj):
    """Recursively drop upstream download entries for files we replace."""
    if isinstance(obj, dict):
        if isinstance(obj.get("models"), list):
            obj["models"] = [m for m in obj["models"]
                             if not (isinstance(m, dict) and m.get("name") in DROP_MODEL_NAMES)]
            if not obj["models"]:
                del obj["models"]
        for v in obj.values():
            scrub_models(v)
    elif isinstance(obj, list):
        for v in obj:
            scrub_models(v)


def convert_node(n, changes):
    t = n.get("type")
    wv = n.get("widgets_values")
    if t in LOADER_TYPES and isinstance(wv, list) and wv and isinstance(wv[0], str) \
            and "ltx-2.5-22b-distilled" in wv[0]:
        for i in n.get("inputs", []):
            if i.get("name") == "weight_dtype" and i.get("link") is not None:
                raise ValueError("weight_dtype is linked on node %s" % n.get("id"))
        n["type"] = "UnetLoaderGGUF"
        n["widgets_values"] = [OUR_GGUF]
        n["inputs"] = [i for i in n.get("inputs", []) if i.get("name") not in ("weight_dtype", "ckpt_name")]
        for i in n["inputs"]:
            if i.get("name") == "ckpt_name":
                i["name"] = "unet_name"
        n["properties"] = {"Node name for S&R": "UnetLoaderGGUF", "cnr_id": "ComfyUI-GGUF"}
        # outputs: MODEL on slot 0 for both node types; checkpoint loaders had extra CLIP/VAE slots
        outs = n.get("outputs", [])
        if t != "UNETLoader":
            if any(o.get("links") for o in outs[1:]):
                raise ValueError("loader %s has extra linked outputs; manual conversion needed" % n.get("id"))
            n["outputs"] = outs[:1]
        changes.append("loader %s %s -> UnetLoaderGGUF" % (n.get("id"), t))
        return
    # everything else is handled by the document-wide pass in convert_doc


def convert_doc(doc, source_file, sha):
    doc = copy.deepcopy(doc)
    changes = []
    for _, nodes, _ in iter_scopes(doc):
        for n in nodes:
            convert_node(n, changes)
    doc = map_value(doc)  # filenames in widgets, subgraph instances, notes, extra
    scrub_models(doc)
    doc.setdefault("extra", {})["arc_preset"] = {
        "source_file": source_file, "source_sha": sha,
        "gguf": OUR_GGUF, "text_encoder": OUR_TEXT_ENCODER,
        "converter": "tools/convert_ltx_presets.py",
    }
    return doc, changes


def analyse(doc):
    types, loras, models, flags = set(), [], set(), []
    for scope, nodes, _ in iter_scopes(doc):
        for n in nodes:
            t = n.get("type", "")
            if UUID_RE.match(t):
                continue
            types.add(t)
            wv = n.get("widgets_values")
            vals = wv if isinstance(wv, list) else []
            if t in XPU_RISK_TYPES:
                flags.append({"node_type": t, "reason": XPU_RISK_TYPES[t]})
            if t == "LTXICLoRALoaderModelOnly" and vals and isinstance(vals[0], str):
                loras.append(vals[0])
            if t in ("UnetLoaderGGUF", "CLIPLoader", "VAELoader", "LatentUpscaleModelLoader") and vals \
                    and isinstance(vals[0], str):
                models.add(vals[0])
            if t != "MarkdownNote" and t != "Note":
                for v in vals:
                    if isinstance(v, str) and NVIDIA_STR_RE.search(v):
                        flags.append({"node_type": t, "reason": "widget value mentions NVIDIA-specific path: %s" % v})
    uniq_flags = [dict(t) for t in sorted({tuple(sorted(f.items())) for f in flags})]
    return sorted(types), sorted(set(loras)), sorted(models), uniq_flags


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="path to a ComfyUI-LTXVideo clone")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "presets" / "ltx25"))
    a = ap.parse_args(argv)
    src, out = Path(a.src), Path(a.out)
    wf_dir = src / WF_REL
    sha = git_sha(src)
    purposes = purposes_from_readme((wf_dir / "README.md").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(wf_dir.rglob("*.json"), key=lambda p: p.relative_to(wf_dir).as_posix())
    entries, all_types = [], {}
    for f in files:
        rel = f.relative_to(wf_dir).as_posix()
        name = f.stem
        doc = json.loads(f.read_text(encoding="utf-8"))
        new, changes = convert_doc(doc, "example_workflows/2.5/" + rel, sha)
        (out / (name + ".json")).write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        types, loras, models, flags = analyse(new)
        for t in types:
            all_types.setdefault(t, []).append(name)
        lora_entries = []
        for l in loras:
            short = lora_short(l)
            ours = LORA_MAP.get(short)
            lora_entries.append({
                "graph_embedded_name": l, "short": short,
                "our_expected_name": ours[0] if ours else None,
                "name_status": ours[1] if ours else "INFERRED (no mapping; use the embedded name)",
            })
        required = sorted(set(models) | {OUR_GGUF})
        entries.append({
            "name": name,
            "file": name + ".json",
            "source_file": "example_workflows/2.5/" + rel,
            "source_sha": sha,
            "purpose": purposes.get(f.name, "(not described in the 2.5 README)"),
            "required_node_types": sorted(t for t in types if t in PACKS),
            "required_packs": sorted({PACKS[t] for t in types if t in PACKS}),
            "all_node_types": types,
            "required_models": required,
            "unconfirmed_models": sorted(m for m in required if m == ENHANCER_ENCODER),
            "ic_loras": lora_entries,
            "runnable_now": not lora_entries,
            "needs_ic_lora_download": bool(lora_entries),
            "arc_review_flags": flags,
            "converted": changes,
        })
    index = {
        "source_repo": "https://github.com/Lightricks/ComfyUI-LTXVideo",
        "source_path": "example_workflows/2.5",
        "source_sha": sha,
        "our_models": {"transformer_gguf": OUR_GGUF, "text_encoder": OUR_TEXT_ENCODER,
                       "video_vae": OUR_VIDEO_VAE, "audio_vae": OUR_AUDIO_VAE, "spatial_upscaler": OUR_UPSCALER},
        "ic_lora_name_map": {k: {"file": v[0], "status": v[1]} for k, v in sorted(LORA_MAP.items())},
        "node_types_by_pack": {p: sorted(t for t in all_types if PACKS.get(t) == p) for p in sorted(set(PACKS.values()))},
        "node_types_used": {t: sorted(v) for t, v in sorted(all_types.items())},
        "presets": entries,
    }
    (out / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %d presets + index.json to %s (source %s)" % (len(entries), out, sha))
    return 0


if __name__ == "__main__":
    sys.exit(main())
