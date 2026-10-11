"""ElzLTXAPITextEncode: hosted LTX-2.5 text encoding. No network: the HTTP opener is faked."""
import importlib.util, io, os, pickle, tempfile, urllib.error
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.join(os.path.dirname(HERE), "comfy_nodes", "elz_nodes")
spec = importlib.util.spec_from_file_location("elz_api_encode_under_test", os.path.join(PACK, "api_encode.py"))
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
KEY = "sk-test-SECRET-123"


def cond():
    return [[torch.randn(1, 8, 16, dtype=torch.bfloat16), {"attention_mask": torch.ones(1, 8, dtype=torch.int64), "pooled_output": None}]]


class Resp:
    def __init__(self, data, status=200): self.data, self.status = data, status
    def read(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener_returning(data, seen):
    def op(req, timeout):
        seen.append(req); return Resp(data)
    return op


def setup_function():
    A._cache.clear()
    os.environ["ELZ_COND_CACHE"] = tempfile.mkdtemp(prefix="elz_cond_cache_")


def test_real_tensor_conditioning_round_trips():
    c = cond(); seen = []
    out, cached = A.encode("a fox in snow", key=KEY, opener=opener_returning(pickle.dumps(c), seen))
    assert not cached and torch.equal(out[0][0], c[0][0]) and out[0][0].dtype == torch.bfloat16 and torch.equal(out[0][1]["attention_mask"], c[0][1]["attention_mask"])
    req = seen[0]
    assert req.full_url == A.API_URL and req.get_header("Authorization") == "Bearer " + KEY
    body = __import__("json").loads(req.data)
    assert body == {"prompt": "a fox in snow", "enhance_prompt": False, "model": {"ltx_version": "2.5.0", "gemma_version": "gemma4-12b-ltx-v1"}}


def test_malicious_pickle_is_refused():
    class Evil:
        def __reduce__(self): return (os.system, ("echo pwned",))
    try:
        A.encode("x", key=KEY, opener=opener_returning(pickle.dumps(Evil()), []))
        raise AssertionError("a pickle calling os.system was accepted")
    except pickle.UnpicklingError as e:
        assert "refused global" in str(e)


def test_repeat_prompt_is_cached_no_second_call():
    seen = []; op = opener_returning(pickle.dumps(cond()), seen)
    A.encode("same prompt", key=KEY, opener=op); out, cached = A.encode("same prompt", key=KEY, opener=op)
    assert cached and len(seen) == 1
    A.encode("same prompt", enhance_prompt=True, key=KEY, opener=op); assert len(seen) == 2       # different request -> new call


def test_errors_are_clear_and_never_contain_the_key():
    def raising(code):
        def op(req, timeout): raise urllib.error.HTTPError(A.API_URL, code, "x", {}, io.BytesIO(b""))
        return op
    for code, want in ((401, "rejected the key"), (302, "redirect"), (500, "HTTP 500")):
        try: A.encode("p%d" % code, key=KEY, opener=raising(code)); raise AssertionError("no error for %d" % code)
        except A.LTXAPIError as e: assert want in str(e) and KEY not in str(e), str(e)
    def down(req, timeout): raise urllib.error.URLError("no route")
    try: A.encode("p-down", key=KEY, opener=down); raise AssertionError("no error when unreachable")
    except A.LTXAPIError as e: assert "unreachable" in str(e) and KEY not in str(e)


def test_key_file_missing_and_present():
    d = tempfile.mkdtemp(); p = os.path.join(d, "k.txt")
    try: A.read_key(p); raise AssertionError("missing key accepted")
    except A.LTXAPIError as e: assert p in str(e)
    open(p, "w", encoding="utf-8").write("﻿" + KEY + "\n")
    assert A.read_key(p) == KEY
    os.environ["ELZ_LTX_KEY_FILE"] = p
    try: assert A.key_file() == p and A.read_key() == KEY
    finally: del os.environ["ELZ_LTX_KEY_FILE"]


def test_empty_prompt_and_bad_shape():
    for bad in ("", "   "):
        try: A.encode(bad, key=KEY, opener=opener_returning(b"", [])); raise AssertionError("empty prompt accepted")
        except A.LTXAPIError: pass
    try: A.encode("shape", key=KEY, opener=opener_returning(pickle.dumps({"not": "a list"}), [])); raise AssertionError("bad shape accepted")
    except A.LTXAPIError as e: assert "shape" in str(e)


def test_node_interface():
    t = A.ElzLTXAPITextEncode.INPUT_TYPES()["required"]
    assert set(t) == {"prompt", "enhance_prompt", "ltx_version", "gemma_version"} and "api_key" not in t       # the key is never a graph input
    assert A.ElzLTXAPITextEncode.RETURN_TYPES == ("CONDITIONING",)


def test_disk_cache_survives_a_restart_and_skips_the_network():
    seen = []; c = cond()
    A.encode("disk cached prompt", key=KEY, opener=opener_returning(pickle.dumps(c), seen))
    A._cache.clear()                                                                    # new ComfyUI process: memory cache gone
    out, cached = A.encode("disk cached prompt", key=KEY, opener=opener_returning(b"", seen))
    assert cached and len(seen) == 1, "second call must come from disk"
    assert torch.equal(out[0][0], c[0][0]) and out[0][0].dtype == torch.bfloat16 and out[0][1]["pooled_output"] is None
    assert torch.equal(out[0][1]["attention_mask"], c[0][1]["attention_mask"])
    assert not [f for f in os.listdir(A.cache_dir()) if f.endswith(".pkl")], "no pickle on disk"
