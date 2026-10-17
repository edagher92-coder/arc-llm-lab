import csv, json, os, sys, unittest, importlib.util
HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location("rr", os.path.join(HERE, "..", "tools", "reasoning_resolver_UNTESTED.py"))
rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)

class Matrix(unittest.TestCase):
    pass

def make(row):
    def t(self):
        body = json.loads(row["request_json"])
        if row["expected_error"]:
            with self.assertRaises(rr.PolicyError):
                rr.resolve(body, row["route"])
            return
        out = rr.resolve(body, row["route"])
        r = out["_resolution"]
        self.assertEqual(r["enable_thinking"], row["expected_enable_thinking"] == "true")
        self.assertEqual(r["effort"] or "", row["expected_effort"])
        self.assertEqual("" if r["budget"] is None else str(r["budget"]), row["expected_budget"])
        self.assertNotIn("reasoning_effort", out)  # nothing top-level that could clobber nested
        self.assertEqual(out["chat_template_kwargs"]["enable_thinking"], r["enable_thinking"])
        self.assertEqual(body, json.loads(row["request_json"]))  # input not mutated
    return t

for row in csv.DictReader(open(os.path.join(HERE, "precedence_matrix.csv"))):
    setattr(Matrix, f"test_{row['id']}", make(row))

class PackRouterRegression(unittest.TestCase):
    """Demonstrates the pack router's defects (#8) against the same matrix shapes."""
    @classmethod
    def setUpClass(cls):
        p = os.path.join(HERE, "..", "inputs", "pack", "agents", "reasoning_effort_router.py")
        if not os.path.exists(p): raise unittest.SkipTest("the rejected pack router is not shipped in arc-llm-lab (see docs/TRIED-AND-REJECTED.md)")
        s = importlib.util.spec_from_file_location("pack_router", p); cls.m = importlib.util.module_from_spec(s); s.loader.exec_module(cls.m)
    def test_first_turn_simple_gets_xhigh(self):
        eff, bud = self.m.classify_turn_effort([{"role": "system", "content": "x"}, {"role": "user", "content": "hello"}])
        self.assertEqual((eff, bud), ("xhigh", 4096))
    def test_nested_effort_clobbered(self):
        out = self.m.apply_dynamic_reasoning_to_payload({"messages": [{"role": "user", "content": "hi"}], "chat_template_kwargs": {"reasoning_effort": "low"}})
        self.assertEqual(out["reasoning_effort"], "xhigh")  # server gives top-level precedence -> caller's 'low' lost
    def test_no_thinking_code_mode_gets_effort_injected(self):
        out = self.m.apply_dynamic_reasoning_to_payload({"messages": [{"role": "user", "content": "fix bug"}], "chat_template_kwargs": {"enable_thinking": False}})
        self.assertIn("reasoning_effort", out)
    def test_canonical_budget_ignored(self):
        out = self.m.apply_dynamic_reasoning_to_payload({"messages": [{"role": "user", "content": "hi"}], "reasoning_budget_tokens": 100})
        self.assertIn("thinking_budget_tokens", out)  # adds alias alongside canonical field
    def test_input_mutated(self):
        p = {"messages": [{"role": "user", "content": "hi"}]}
        self.m.apply_dynamic_reasoning_to_payload(p)
        self.assertIn("reasoning_effort", p)

if __name__ == "__main__":
    unittest.main(verbosity=2)
