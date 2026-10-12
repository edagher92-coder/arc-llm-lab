"""Tests for the ElzSaveConditioning / ElzLoadConditioning ComfyUI nodes (needs torch + safetensors; skipped without them). Run: python tests/test_elz_nodes.py"""
import json, os, sys, tempfile, traceback
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(D, "comfy_nodes"))
try:
    import torch, safetensors                                   # noqa: F401
    import elz_nodes as n
except ImportError as _e:
    n = None; _why = str(_e)

def need():
    if n is None:
        try: import pytest; pytest.skip(_why)
        except ImportError: raise SystemExit("skipped: " + _why)

def fresh():
    d = tempfile.mkdtemp(prefix="elzcond-"); os.environ["ELZ_COND_DIR"] = d; return os.path.realpath(d)

def conds():
    g = torch.Generator().manual_seed(1)
    pos = [[torch.randn(1, 8, 16, generator=g).to(torch.bfloat16), {"attention_mask": torch.ones(1, 8, dtype=torch.int64), "frame_rate": 24.0, "tag": "p", "none": None, "nest": {"a": [1, 2]}}]]
    neg = [[torch.randn(1, 4, 16, generator=g), {}], [torch.randn(1, 2, 16, generator=g), {"k": 3}]]
    return pos, neg

def save(name="cond", prompt="a fox"):
    pos, neg = conds(); n.SaveConditioning().run(pos, neg, prompt, name); return pos, neg

def refuses(fn, word):
    try: fn()
    except n.CondError as e: assert word in str(e), e; return
    raise AssertionError("did not refuse (%s)" % word)

def test_nodes_registered():
    need()
    assert {"ElzSaveConditioning", "ElzLoadConditioning"} <= set(n.NODE_CLASS_MAPPINGS) and n.NODE_CLASS_MAPPINGS["ElzSaveConditioning"].OUTPUT_NODE
    assert n.NODE_CLASS_MAPPINGS["ElzLoadConditioning"].RETURN_TYPES == ("CONDITIONING", "CONDITIONING")

def test_roundtrip_keeps_values_dtypes_shapes_and_sidecar():
    need(); d = fresh(); pos, neg = save()
    assert sorted(os.listdir(d)) == ["cond.json", "cond.safetensors"], os.listdir(d)
    side = json.load(open(os.path.join(d, "cond.json")))
    assert side["schema"] == 1 and side["prompt_sha256"] == n.prompt_hash("a fox") and side["tensors"]["positive.0.cond"] == {"shape": [1, 8, 16], "dtype": "bfloat16"}, side
    p2, n2 = n.LoadConditioning().run("a fox", "cond")
    assert p2[0][0].dtype == torch.bfloat16 and torch.equal(p2[0][0], pos[0][0]) and p2[0][1]["attention_mask"].dtype == torch.int64
    assert p2[0][1]["frame_rate"] == 24.0 and p2[0][1]["tag"] == "p" and p2[0][1]["none"] is None and p2[0][1]["nest"] == {"a": [1, 2]}
    assert len(n2) == 2 and torch.equal(n2[1][0], neg[1][0]) and n2[1][1] == {"k": 3}

def test_refuses_wrong_prompt_and_schema_and_tampering():
    need(); d = fresh(); save()
    refuses(lambda: n.LoadConditioning().run("another prompt", "cond"), "different prompt")
    side_p = os.path.join(d, "cond.json"); side = json.load(open(side_p))
    json.dump(dict(side, schema=2), open(side_p, "w")); refuses(lambda: n.LoadConditioning().run("a fox", "cond"), "schema")
    bad = json.loads(json.dumps(side)); bad["tensors"]["positive.0.cond"]["shape"] = [1, 8, 17]; json.dump(bad, open(side_p, "w"))
    refuses(lambda: n.LoadConditioning().run("a fox", "cond"), "differs from the sidecar")
    bad = json.loads(json.dumps(side)); bad["tensors"]["positive.0.cond"]["dtype"] = "float32"; json.dump(bad, open(side_p, "w"))
    refuses(lambda: n.LoadConditioning().run("a fox", "cond"), "differs from the sidecar")
    bad = json.loads(json.dumps(side)); bad["tensors"]["extra.key"] = {"shape": [1], "dtype": "float32"}; json.dump(bad, open(side_p, "w"))
    refuses(lambda: n.LoadConditioning().run("a fox", "cond"), "does not hold")
    json.dump(dict(side, prompt_sha256=n.prompt_hash("other")), open(side_p, "w"))                    # sidecar edited to match another prompt: the tensor file's own metadata disagrees
    refuses(lambda: n.LoadConditioning().run("other", "cond"), "disagree")
    os.remove(side_p); refuses(lambda: n.LoadConditioning().run("a fox", "cond"), "no saved conditioning")

def test_safetensors_only_no_pickle():
    need(); d = fresh(); save(); marker = os.path.join(d, "PWNED")
    class Evil:
        def __reduce__(self): return (open, (marker, "w"))
    import pickle
    open(os.path.join(d, "cond.safetensors"), "wb").write(pickle.dumps(Evil()))                        # a pickle where the tensors should be
    try: n.LoadConditioning().run("a fox", "cond"); raise AssertionError("loaded a pickle")
    except AssertionError: raise
    except Exception: pass
    assert not os.path.exists(marker), "pickle payload ran"

def test_paths_confined_to_cond_dir():
    need(); d = fresh()
    for bad in ("../x", "a/b", "a\\b", "x.y", "", "/etc/passwd", "C:\\x", "a" * 65, None, "..", "x\x00y", "ok\n"):
        refuses(lambda: n.SaveConditioning().run(*conds(), "p", bad), "name")
        refuses(lambda: n.LoadConditioning().run("p", bad), "name")
    assert os.listdir(d) == []
    save("good-name_1"); assert os.path.isfile(os.path.join(d, "good-name_1.safetensors"))
    outside = tempfile.mkdtemp(); open(os.path.join(outside, "t.safetensors"), "wb").write(b"x"); open(os.path.join(outside, "t.json"), "w").write("{}")
    if hasattr(os, "symlink"):
        os.symlink(os.path.join(outside, "t.safetensors"), os.path.join(d, "link.safetensors")); os.symlink(os.path.join(outside, "t.json"), os.path.join(d, "link.json"))
        refuses(lambda: n.LoadConditioning().run("p", "link"), "escapes")
        refuses(lambda: n.SaveConditioning().run(*conds(), "p", "link"), "escapes")
    assert open(os.path.join(outside, "t.safetensors"), "rb").read() == b"x"

def test_save_refuses_what_it_cannot_store():
    need(); fresh(); pos, neg = conds()
    refuses(lambda: n.SaveConditioning().run([[torch.zeros(1), {"o": object()}]], neg, "p"), "cannot be saved")
    refuses(lambda: n.SaveConditioning().run([[torch.zeros(1), {"f": float("nan")}]], neg, "p"), "cannot be saved")
    refuses(lambda: n.SaveConditioning().run([], neg, "p"), "empty")
    refuses(lambda: n.SaveConditioning().run(["not a pair"], neg, "p"), "pair")

def test_overwrite_is_atomic_and_new_save_replaces_old():
    need(); d = fresh(); save(prompt="one"); save(prompt="two")
    assert not [f for f in os.listdir(d) if f.endswith(".tmp")]
    refuses(lambda: n.LoadConditioning().run("one", "cond"), "different prompt"); n.LoadConditioning().run("two", "cond")

if __name__ == "__main__":
    if n is None: raise SystemExit("skipped: " + _why)
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_") and callable(f):
            try: f(); print("ok   ", k)
            except Exception: fails += 1; print("FAIL ", k); traceback.print_exc()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
