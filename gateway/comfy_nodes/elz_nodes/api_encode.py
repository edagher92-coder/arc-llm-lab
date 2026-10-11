"""ElzLTXAPITextEncode: LTX-2.5 prompt conditioning from Lightricks' hosted text encoder, so the 12B Gemma encoder never loads locally.

Calls POST https://api.ltx.video/v1/prompt-embedding (the endpoint Lightricks' own GemmaAPITextEncode uses; documented as free) and returns
CONDITIONING. Differences from the official node, all deliberate:
- the API key is read from a file on this PC ($ELZ_LTX_KEY_FILE, else C:\\AI\\secrets\\ltx-api-key.txt), never from a node input, so it is
  never stored in the workflow, ComfyUI's history or the output metadata, and never logged;
- redirects are refused, so the Authorization header cannot be carried to another host;
- the pickled response is loaded with an allow-list unpickler (tensor rebuild helpers, dtypes, plain containers only);
- the model selector is a fixed input (LTX 2.5.0 / gemma4-12b-ltx-v1, read once from the int8 transformer's safetensors metadata), because
  our transformer is a GGUF file without that metadata;
- identical requests are answered from a small in-process cache.
"""
import collections, hashlib, io, json, os, pickle, urllib.error, urllib.request

API_URL = "https://api.ltx.video/v1/prompt-embedding"
DEFAULT_KEY_FILE = r"C:\AI\secrets\ltx-api-key.txt"
CACHE_MAX = 16
_cache = collections.OrderedDict()


class LTXAPIError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(req, timeout):
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)


def key_file():
    return os.environ.get("ELZ_LTX_KEY_FILE") or DEFAULT_KEY_FILE


def read_key(path=None):
    p = path or key_file()
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            k = f.read(512).strip()
    except OSError:
        k = ""
    if not k or any(c.isspace() for c in k):
        raise LTXAPIError("LTX API key missing: put the key (one line) in %s, or set ELZ_LTX_KEY_FILE" % p)
    return k


_ALLOWED = {
    ("torch._utils", "_rebuild_tensor_v2"), ("torch._utils", "_rebuild_tensor"), ("torch._utils", "_rebuild_parameter"),
    ("torch._utils", "_rebuild_device_tensor_from_numpy"), ("torch._tensor", "_rebuild_from_type_v2"),
    ("torch.storage", "_load_from_bytes"), ("torch", "Size"), ("torch", "Tensor"), ("torch", "device"),
    ("collections", "OrderedDict"), ("builtins", "set"), ("builtins", "frozenset"), ("builtins", "slice"),
}
_STORAGES = {"FloatStorage", "HalfStorage", "BFloat16Storage", "DoubleStorage", "LongStorage", "IntStorage", "BoolStorage",
             "ByteStorage", "CharStorage", "ShortStorage", "UntypedStorage"}
_DTYPES = {"float32", "float16", "bfloat16", "float64", "int64", "int32", "int16", "int8", "uint8", "bool"}


class SafeUnpickler(pickle.Unpickler):
    """Only what a pickled list of [tensor, {str: tensor|number|...}] needs. Anything else (os, subprocess, eval, getattr...) is refused."""
    def find_class(self, module, name):
        if (module, name) == ("torch.storage", "_load_from_bytes"):
            return _load_storage_cpu                    # the API pickles CUDA storages; map them to the CPU, with torch's safe loader
        if (module, name) in _ALLOWED or (module == "torch" and (name in _STORAGES or name in _DTYPES)):
            return super().find_class(module, name)
        raise pickle.UnpicklingError("refused global %s.%s in the LTX API response" % (module, name))


def _load_storage_cpu(b):
    import torch
    return torch.load(io.BytesIO(b), map_location="cpu", weights_only=True)


def safe_loads(data):
    return SafeUnpickler(io.BytesIO(data)).load()


DISK_CACHE_MAX = 200


def cache_dir():
    """$ELZ_COND_CACHE, else C:\\AI\\video\\cond_cache. Entries are safetensors (tensors only) + a JSON sidecar; no pickle on disk."""
    return os.environ.get("ELZ_COND_CACHE") or r"C:\AI\video\cond_cache"


def _disk_get(ck):
    st, js = os.path.join(cache_dir(), ck + ".safetensors"), os.path.join(cache_dir(), ck + ".json")
    if not (os.path.isfile(st) and os.path.isfile(js)):
        return None
    try:
        from safetensors.torch import load_file
        t = load_file(st, device="cpu"); meta = json.load(open(js, encoding="utf-8"))
        out = []
        for i, e in enumerate(meta["entries"]):
            extras = {k: (t["%d.%s" % (i, k)] if v == "tensor" else v) for k, v in e["extras"].items()}
            out.append([t["%d.cond" % i], extras])
        os.utime(st, None)
        return out
    except Exception:                                   # a damaged entry is ignored and rewritten on the next call
        return None


def _disk_put(ck, cond):
    try:
        from safetensors.torch import save_file
        import torch
        d = cache_dir(); os.makedirs(d, exist_ok=True)
        tensors, entries = {}, []
        for i, (c, extras) in enumerate(cond):
            tensors["%d.cond" % i] = c.contiguous()
            ex = {}
            for k, v in (extras or {}).items():
                if isinstance(v, torch.Tensor):
                    tensors["%d.%s" % (i, k)] = v.contiguous(); ex[k] = "tensor"
                elif v is None or isinstance(v, (bool, int, float, str)):
                    ex[k] = v
                else:
                    return                              # unknown extra type: do not cache rather than cache wrongly
            entries.append({"extras": ex})
        save_file(tensors, os.path.join(d, ck + ".safetensors"))
        json.dump({"entries": entries}, open(os.path.join(d, ck + ".json"), "w", encoding="utf-8"))
        files = sorted((f for f in os.listdir(d) if f.endswith(".safetensors")), key=lambda f: os.path.getmtime(os.path.join(d, f)))
        for f in files[:-DISK_CACHE_MAX]:
            for ext in (".safetensors", ".json"):
                try: os.remove(os.path.join(d, f[:-12] + ext))
                except OSError: pass
    except Exception:
        pass


def encode(prompt, enhance_prompt=False, ltx_version="2.5.0", gemma_version="gemma4-12b-ltx-v1", key=None, opener=None, timeout=60):
    prompt = (prompt or "").strip()
    if not prompt:
        raise LTXAPIError("the prompt is empty")
    body = {"prompt": prompt, "enhance_prompt": bool(enhance_prompt), "model": {"ltx_version": ltx_version, "gemma_version": gemma_version}}
    ck = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    if ck in _cache:
        _cache.move_to_end(ck)
        return _cache[ck], True
    hit = _disk_get(ck)
    if hit is not None:
        _cache[ck] = hit
        return hit, True
    k = key or read_key()
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + k, "Content-Type": "application/json"})
    try:
        with (opener or _open)(req, timeout) as r:
            status, data = r.status, r.read()
    except urllib.error.HTTPError as ex:
        if ex.code == 401:
            raise LTXAPIError("LTX API rejected the key (401): make a new one at https://console.ltx.io/ and update %s" % key_file()) from None
        if 300 <= ex.code < 400:
            raise LTXAPIError("LTX API answered with a redirect (%d); refused" % ex.code) from None
        raise LTXAPIError("LTX API error HTTP %d" % ex.code) from None
    except (urllib.error.URLError, OSError) as ex:
        raise LTXAPIError("LTX API unreachable (%s)" % type(ex).__name__) from None
    if status != 200:
        raise LTXAPIError("LTX API error HTTP %d" % status)
    cond = safe_loads(data)
    if not isinstance(cond, list) or not cond:
        raise LTXAPIError("LTX API returned an unexpected conditioning shape")
    _cache[ck] = cond
    _disk_put(ck, cond)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return cond, False


class ElzLTXAPITextEncode:
    """Text -> CONDITIONING through Lightricks' hosted LTX-2.5 encoder. No local text-encoder model is loaded."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"prompt": ("STRING", {"multiline": True, "default": ""}),
                             "enhance_prompt": ("BOOLEAN", {"default": False}),
                             "ltx_version": ("STRING", {"default": "2.5.0"}),
                             "gemma_version": ("STRING", {"default": "gemma4-12b-ltx-v1"})}}
    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "run"
    CATEGORY = "elz"

    def run(self, prompt, enhance_prompt=False, ltx_version="2.5.0", gemma_version="gemma4-12b-ltx-v1"):
        cond, cached = encode(prompt, enhance_prompt, ltx_version, gemma_version)
        print("ELZ_LTX_API encode chars=%d cached=%s" % (len(prompt or ""), cached), flush=True)
        return (cond,)
