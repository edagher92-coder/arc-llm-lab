"""Checks for the Elz ComfyUI front-end extension (WEB_DIRECTORY + web/elz_studio.js). No ComfyUI or torch needed. Run: python -m pytest tests/test_elz_web.py -q"""
import ast, os, re

PACK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "comfy_nodes", "elz_nodes")
INIT = os.path.join(PACK, "__init__.py")
JS = os.path.join(PACK, "web", "elz_studio.js")


def _web_directory():
    tree = ast.parse(open(INIT, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WEB_DIRECTORY" for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def test_web_directory_is_set():
    assert _web_directory() == "./web"


def test_js_file_exists():
    assert os.path.isfile(JS)


def test_js_registers_extension():
    src = open(JS, encoding="utf-8").read()
    assert "registerExtension" in src
    assert 'name: "elz.studio"' in src


def test_js_has_no_external_hosts_or_eval():
    src = open(JS, encoding="utf-8").read()
    assert "http://" not in src
    assert not re.search(r"\beval\s*\(", src)
    assert "fetch(" not in src and "XMLHttpRequest" not in src
