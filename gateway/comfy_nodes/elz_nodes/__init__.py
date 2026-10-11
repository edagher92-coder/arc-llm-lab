"""Elz nodes: small guards for the Intel XPU video pipeline. Copy this folder into ComfyUI/custom_nodes/ and whitelist it (--whitelist-custom-nodes elz_nodes)."""
import hashlib, json, os, re, tempfile, time
import torch


class AudioNanGuard:
    """Replace NaN/Inf samples in a decoded audio clip with silence so the AAC muxer never rejects the file; logs how much was bad."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"audio": ("AUDIO",)}}
    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "run"
    CATEGORY = "elz"

    def run(self, audio):
        w = audio["waveform"]
        bad = int((~torch.isfinite(w)).sum().item())
        print("ELZ_AUDIO_GUARD samples=%d nonfinite=%d (%.1f%%) absmax=%.4f" % (w.numel(), bad, 100.0 * bad / max(1, w.numel()), float(torch.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0).abs().max())), flush=True)
        if bad:
            w = torch.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0).clamp(-1.0, 1.0)
        return ({"waveform": w, "sample_rate": audio["sample_rate"]},)


# ---------- two-process split: hand the text conditioning from one ComfyUI process to the next ----------
# Q6_K needs the 12B text encoder's host RAM back before the transformer loads. The gateway runs two stages (workflows with "stages"): stage 1
# encodes and saves the conditioning with ElzSaveConditioning, ComfyUI is killed, stage 2 starts fresh and loads it with ElzLoadConditioning.
# The hand-over is a plain safetensors file plus a JSON sidecar. No pickle anywhere: safetensors holds only tensors, everything else is JSON.
COND_SCHEMA = 1
COND_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
COND_SLOTS = ("positive", "negative")


class CondError(ValueError):
    pass


def cond_dir():
    """The only folder these nodes read or write: $ELZ_COND_DIR (the gateway sets it per job), else <ComfyUI temp>/elz_cond."""
    d = os.environ.get("ELZ_COND_DIR")
    if not d:
        try:
            import folder_paths
            d = os.path.join(folder_paths.get_temp_directory(), "elz_cond")
        except Exception:
            d = os.path.join(tempfile.gettempdir(), "elz_cond")
    os.makedirs(d, exist_ok=True)
    return os.path.realpath(d)


def cond_paths(name):
    """(safetensors path, sidecar path) for a bare name, confined to the cond dir: no separators, no dots, no symlinks."""
    if not isinstance(name, str) or not COND_NAME.fullmatch(name):
        raise CondError("conditioning name must be 1-64 letters, digits, '_' or '-'")
    root = cond_dir()
    out = []
    for ext in (".safetensors", ".json"):
        p = os.path.join(root, name + ext)
        if os.path.dirname(os.path.realpath(p)) != root or os.path.islink(p):
            raise CondError("conditioning path escapes the conditioning folder")
        out.append(p)
    return tuple(out)


def prompt_hash(prompt):
    return hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()


def cond_to_tensors(slot, cond):
    """A ComfyUI CONDITIONING (list of [tensor, dict]) -> ({safetensors key: cpu tensor}, JSON description). Anything that is neither a tensor nor
    plain JSON is refused rather than silently dropped."""
    if not isinstance(cond, (list, tuple)) or not cond:
        raise CondError("%s conditioning is empty or not a list" % slot)
    tensors, entries = {}, []
    for i, item in enumerate(cond):
        if not isinstance(item, (list, tuple)) or len(item) != 2 or not torch.is_tensor(item[0]) or not isinstance(item[1], dict):
            raise CondError("%s[%d] is not a [tensor, dict] pair" % (slot, i))
        key = "%s.%d.cond" % (slot, i)
        tensors[key] = item[0].detach().to("cpu").contiguous()
        entry = {"cond": key, "tensors": {}, "extras": {}}
        for k, v in item[1].items():
            if not isinstance(k, str):
                raise CondError("%s[%d] has a non-string key" % (slot, i))
            if torch.is_tensor(v):
                tk = "%s.%d.x.%s" % (slot, i, k)
                tensors[tk] = v.detach().to("cpu").contiguous()
                entry["tensors"][k] = tk
            else:
                try:
                    json.dumps(v, allow_nan=False)
                except (TypeError, ValueError):
                    raise CondError("%s[%d].%s (%s) cannot be saved: only tensors and plain JSON values are allowed" % (slot, i, k, type(v).__name__))
                entry["extras"][k] = v
        entries.append(entry)
    return tensors, entries


def tensors_to_cond(entries, tensors):
    out = []
    for e in entries:
        d = dict(e["extras"])
        for k, tk in e["tensors"].items():
            d[k] = tensors[tk]
        out.append([tensors[e["cond"]], d])
    return out


class SaveConditioning:
    """Save the positive and negative text conditioning (safetensors + JSON sidecar with shapes, dtypes, prompt hash and schema version)."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"positive": ("CONDITIONING",), "negative": ("CONDITIONING",),
                             "prompt": ("STRING", {"multiline": True, "default": ""}), "name": ("STRING", {"default": "cond"})}}
    RETURN_TYPES = ()
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "elz"

    @classmethod
    def IS_CHANGED(s, **kw):
        return float("nan")

    def run(self, positive, negative, prompt, name="cond"):
        from safetensors.torch import save_file
        st_path, js_path = cond_paths(name)
        tensors, slots = {}, {}
        for slot, cond in zip(COND_SLOTS, (positive, negative)):
            t, slots[slot] = cond_to_tensors(slot, cond)
            tensors.update(t)
        h = prompt_hash(prompt)
        side = {"schema": COND_SCHEMA, "prompt_sha256": h, "created": time.time(), "slots": slots,
                "tensors": {k: {"shape": list(v.shape), "dtype": str(v.dtype).replace("torch.", "")} for k, v in tensors.items()}}
        tmp = st_path + ".tmp"
        save_file(tensors, tmp, metadata={"elz_schema": str(COND_SCHEMA), "prompt_sha256": h})
        os.replace(tmp, st_path)
        with open(js_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(side, f, indent=1, allow_nan=False)
        os.replace(js_path + ".tmp", js_path)                 # the sidecar lands last: a loader that finds it finds a complete tensor file
        print("ELZ_COND_SAVED name=%s tensors=%d bytes=%d prompt_sha256=%s" % (name, len(tensors), os.path.getsize(st_path), h[:12]), flush=True)
        return ()


class LoadConditioning:
    """Load what ElzSaveConditioning wrote. Refuses (raises) on a missing file, a schema or prompt-hash mismatch, or tensors that differ from the sidecar."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"prompt": ("STRING", {"multiline": True, "default": ""}), "name": ("STRING", {"default": "cond"})}}
    RETURN_TYPES = ("CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("positive", "negative")
    FUNCTION = "run"
    CATEGORY = "elz"

    @classmethod
    def IS_CHANGED(s, **kw):
        return float("nan")

    def run(self, prompt, name="cond"):
        from safetensors import safe_open
        st_path, js_path = cond_paths(name)
        if not (os.path.isfile(st_path) and os.path.isfile(js_path)):
            raise CondError("no saved conditioning named %r in the conditioning folder" % name)
        try:
            side = json.load(open(js_path, encoding="utf-8"))
        except (OSError, ValueError) as ex:
            raise CondError("conditioning sidecar is unreadable (%s)" % ex)
        if not isinstance(side, dict) or side.get("schema") != COND_SCHEMA:
            raise CondError("conditioning schema %r is not the supported version %d" % ((side or {}).get("schema") if isinstance(side, dict) else None, COND_SCHEMA))
        if side.get("prompt_sha256") != prompt_hash(prompt):
            raise CondError("the saved conditioning was made from a different prompt; refusing to load it")
        want = side.get("tensors")
        slots = side.get("slots")
        if not isinstance(want, dict) or not isinstance(slots, dict) or any(s not in slots for s in COND_SLOTS):
            raise CondError("conditioning sidecar is incomplete")
        loaded = {}
        with safe_open(st_path, framework="pt", device="cpu") as f:
            meta = f.metadata() or {}
            if meta.get("elz_schema") != str(COND_SCHEMA) or meta.get("prompt_sha256") != side["prompt_sha256"]:
                raise CondError("the tensor file and its sidecar disagree (schema or prompt hash)")
            if set(f.keys()) != set(want):
                raise CondError("the tensor file does not hold the tensors the sidecar lists")
            for k in f.keys():
                t = f.get_tensor(k)
                if list(t.shape) != list(want[k].get("shape", [])) or str(t.dtype).replace("torch.", "") != want[k].get("dtype"):
                    raise CondError("tensor %s differs from the sidecar (shape or dtype)" % k)
                loaded[k] = t
        try:
            out = tuple(tensors_to_cond(slots[s], loaded) for s in COND_SLOTS)
        except (KeyError, TypeError) as ex:
            raise CondError("conditioning sidecar does not match the tensor file (%r)" % (ex,))
        print("ELZ_COND_LOADED name=%s tensors=%d" % (name, len(loaded)), flush=True)
        return out


# Front-end extension (web/elz_studio.js): Studio link, queue/elapsed badge, Release GPU hint, node colours. Serves no HTTP routes of its own.
WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {"ElzAudioNanGuard": AudioNanGuard, "ElzSaveConditioning": SaveConditioning, "ElzLoadConditioning": LoadConditioning}
NODE_DISPLAY_NAME_MAPPINGS = {"ElzAudioNanGuard": "Audio NaN guard (Elz)", "ElzSaveConditioning": "Save conditioning (Elz)", "ElzLoadConditioning": "Load conditioning (Elz)"}

# Auto Production (production.py): prompt builder + optional LLM director, driven by cheatsheets/*.json. Failing to import it must never take the guards above down.
try:
    from .production import NODE_CLASS_MAPPINGS as _P_CLASSES, NODE_DISPLAY_NAME_MAPPINGS as _P_NAMES
    NODE_CLASS_MAPPINGS.update(_P_CLASSES)
    NODE_DISPLAY_NAME_MAPPINGS.update(_P_NAMES)
except Exception as _ex:   # noqa: BLE001
    print("ELZ_PRODUCTION_UNAVAILABLE %s: %s" % (type(_ex).__name__, _ex), flush=True)
