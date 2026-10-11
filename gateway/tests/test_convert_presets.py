"""Tests for tools/convert_ltx_presets.py and the generated presets/ltx25 files."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import convert_ltx_presets as C  # noqa: E402

PRESETS = ROOT / "presets" / "ltx25"
FILES = sorted(p for p in PRESETS.glob("*.json") if p.name != "index.json")


def link_ids(links):
    return {(l[0] if isinstance(l, list) else l["id"]) for l in links}


def link_target_ids(links):
    return {(l[0] if isinstance(l, list) else l["id"]): (l[3] if isinstance(l, list) else l["target_id"]) for l in links}


def scope_refs(doc):
    """(scope, link ids in links[], link ids referenced by nodes / subgraph IO)."""
    out = []
    subs = doc.get("definitions", {}).get("subgraphs", [])
    scopes = [("top", doc["nodes"], doc["links"], None)] + [(s["name"], s["nodes"], s["links"], s) for s in subs]
    for name, nodes, links, sg in scopes:
        refs = set()
        for n in nodes:
            for i in n.get("inputs", []) or []:
                if i.get("link") is not None:
                    refs.add(i["link"])
            for o in n.get("outputs", []) or []:
                refs.update(o.get("links") or [])
        if sg:
            for io in (sg.get("inputs", []) or []) + (sg.get("outputs", []) or []):
                refs.update(io.get("linkIds") or [])
        out.append((name, link_ids(links), refs))
    return out


# Dangling node-side link refs that already exist in the official source (preserved, not introduced).
KNOWN_UPSTREAM_DANGLING = {
    ("LTX-2.5_A2V_Two_Stage_Distilled.json", "top"): {13640, 13735},
    ("LTX-2.5_V2V_TiledFusion_HDR_to_HDR.json", "Preprocess"): {29, 30},
    ("LTX-2.5_V2V_TiledFusion_HDR_to_HDR.json", "Preprocess - stage 2"): {29, 30},
}


class ConvertTests(unittest.TestCase):
    def test_presets_exist(self):
        self.assertGreaterEqual(len(FILES), 10, "run tools/convert_ltx_presets.py first")
        self.assertTrue((PRESETS / "index.json").exists())

    def test_loader_replaced_everywhere(self):
        for p in FILES:
            raw = p.read_text(encoding="utf-8")
            self.assertNotIn("ltx-2.5-22b-distilled-transformer", raw, p.name)
            self.assertNotIn("gemma4-12b-with-proj-ltx-2.5-bf16", raw, p.name)
            doc = json.loads(raw)
            n_gguf = 0
            for _, nodes, _ in C.iter_scopes(doc):
                for n in nodes:
                    self.assertNotIn(n["type"], C.LOADER_TYPES - {"CLIPLoader"}, p.name)
                    if n["type"] == "UnetLoaderGGUF":
                        n_gguf += 1
                        self.assertEqual(n["widgets_values"], [C.OUR_GGUF])
                        self.assertEqual([o["type"] for o in n["outputs"]], ["MODEL"])
                    if n["type"] == "CLIPLoader" and n["widgets_values"][0].startswith("gemma4-12b"):
                        self.assertEqual(n["widgets_values"][0], C.OUR_TEXT_ENCODER)
            self.assertGreaterEqual(n_gguf, 1, p.name)

    def test_link_integrity(self):
        for p in FILES:
            doc = json.loads(p.read_text(encoding="utf-8"))
            for name, ids, refs in scope_refs(doc):
                self.assertEqual(refs - ids, KNOWN_UPSTREAM_DANGLING.get((p.name, name), set()),
                                 "%s/%s dangling refs" % (p.name, name))
                self.assertFalse(ids - refs, "%s/%s unreferenced links %s" % (p.name, name, sorted(ids - refs)[:5]))

    def test_links_identical_to_source(self):
        src = self._source()
        if src is None:
            self.skipTest("no source clone available (set LTX_SRC)")
        for f in sorted((src / C.WF_REL).rglob("*.json")):
            a = json.loads(f.read_text(encoding="utf-8"))
            b = json.loads((PRESETS / (f.stem + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(a["links"], b["links"], f.name)
            for sa, sb in zip(a["definitions"]["subgraphs"], b["definitions"]["subgraphs"]):
                self.assertEqual(sa["links"], sb["links"], f.name)
            self.assertEqual([n["id"] for n in a["nodes"]], [n["id"] for n in b["nodes"]], f.name)

    def test_topology_unchanged_synthetic(self):
        index = json.loads((PRESETS / "index.json").read_text(encoding="utf-8"))
        # compare link tables with the in-memory conversion of a synthetic doc (no network needed)
        doc = {"nodes": [{"id": 1, "type": "UNETLoader", "inputs": [], "outputs": [{"name": "MODEL", "type": "MODEL", "links": [5]}],
                          "widgets_values": [C.SRC_TRANSFORMER, "default"], "properties": {"models": [{"name": C.SRC_TRANSFORMER, "url": "https://x/" + C.SRC_TRANSFORMER}]}},
                         {"id": 2, "type": "Sink", "inputs": [{"name": "m", "type": "MODEL", "link": 5}], "outputs": []}],
               "links": [[5, 1, 0, 2, 0, "MODEL"]], "definitions": {"subgraphs": []}}
        before = copy.deepcopy(doc["links"])
        new, changes = C.convert_doc(doc, "x.json", "sha")
        self.assertEqual(new["links"], before)
        self.assertEqual(new["nodes"][0]["type"], "UnetLoaderGGUF")
        self.assertEqual(new["nodes"][0]["outputs"][0]["links"], [5])
        self.assertNotIn("models", new["nodes"][0]["properties"])
        self.assertEqual(len(changes), 1)
        self.assertTrue(index["presets"])

    def test_index_consistent(self):
        index = json.loads((PRESETS / "index.json").read_text(encoding="utf-8"))
        names = {e["file"] for e in index["presets"]}
        self.assertEqual(names, {p.name for p in FILES})
        for e in index["presets"]:
            self.assertEqual(e["runnable_now"], not e["ic_loras"])
            self.assertEqual(e["source_sha"], index["source_sha"])
            self.assertIn(C.OUR_GGUF, e["required_models"])
        self.assertEqual(index["ic_lora_name_map"]["alpha-gen"]["status"], "VERIFIED")
        self.assertEqual(index["ic_lora_name_map"]["restore"]["status"], "INFERRED")

    def test_deterministic(self):
        src = self._source()
        if src is None:
            self.skipTest("no source clone available (set LTX_SRC)")
        import tempfile
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            C.main(["--src", str(src), "--out", a])
            C.main(["--src", str(src), "--out", b])
            fa = sorted(Path(a).iterdir())
            self.assertEqual([x.name for x in fa], sorted(x.name for x in Path(b).iterdir()))
            for x in fa:
                self.assertEqual(x.read_bytes(), (Path(b) / x.name).read_bytes(), x.name)
                if x.name != "index.json":  # also matches the committed preset
                    self.assertEqual(x.read_bytes(), (PRESETS / x.name).read_bytes(), x.name)

    @staticmethod
    def _source():
        import os
        cands = [os.environ.get("LTX_SRC", ""),
                 "/tmp/claude-0/-home-claude-arc-llm-lab/1ea5e2e2-4d1d-5c40-8593-167d024647a1/scratchpad/ltxsrc"]
        for c in cands:
            if c and (Path(c) / C.WF_REL).is_dir():
                return Path(c)
        return None


if __name__ == "__main__":
    unittest.main()
