"""Studio Phase 2 M2 front end: static page-markup checks (GPU series, history panel, ETA hint, preview, dev mode, login gate). No server needed.
Run: python tests/test_studio_m2_ui.py   (or pytest)"""
import os, re, shutil, subprocess, sys, tempfile, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(os.path.dirname(HERE), "studio", "index.html")


def html():
    return open(PAGE, encoding="utf-8").read()


def script():
    m = re.search(r"<script>\n(.*)</script>", html(), re.S)
    assert m
    return m.group(1)


def test_gpu_series_in_strip_and_charts():
    h = html()
    assert '{k: "gpu"' in h and 'f: "gpu_util"' in h and "min: 0, max: 100" in h          # a METRICS entry: the strip and the 15-minute charts both build from METRICS
    assert 'f: "gpu_mem_gb"' in h and "get: vramOf" in h                                  # GPU memory is the VRAM series, one number
    assert "const vramOf = p =>" in h and "num(p.gpu_mem_gb) ? p.gpu_mem_gb : p.vram_used_gb" in h   # gpu_mem_gb preferred, vram_used_gb is the fallback
    assert "S.hold[m.k]" in h and "hold: true" in h                                       # nulls hold the last value
    assert 'data-t="gpu"' in h or '.mc[data-t="gpu"]' in h
    assert "repeat(5,minmax(0,1fr))" in h                                                 # the strip has room for five series
    assert h.count("mget(m, p)") >= 3                                                    # strip, charts and mean all read through the same accessor


def test_history_panel():
    h = html()
    assert 'id="hist"' in h and 'id="histBody"' in h and "Render history" in h
    assert 'quietGet("history?limit=50")' in h and "function histJobEnded()" in h and "function paintHist()" in h
    assert "slice(0, 20)" in h and "median_phase_s" in h and 'class: "pbar"' in h          # last 20 renders, stacked median-phase bar
    assert "const PHASE_COL" in h and "stage1" in h
    assert 'addEventListener("toggle", histSync)' in h                                    # refreshed when opened
    assert "histJobEnded()" in h and '["done", "failed", "cancelled"]' in h               # and when a job reaches a terminal state
    assert "HIST.hidden = true" in h                                                      # 404 / 401 / 403: the panel disappears
    s = script()
    assert not re.search(r"setInterval\([^)]*loadHist", s) and "setInterval(loadHist" not in s   # no polling


def test_eta_source_hint():
    h = html()
    assert "function etaSource(" in h and "≈ from past renders" in h and '"estimate"' in h and "eta_source" in h
    assert 'class: "src"' in h


def test_live_preview():
    h = html()
    assert 'class: "pv"' in h and "function previewFeed(" in h and "preview_t" in h
    assert "/preview?t=" in h and "Date.now() - st.at >= 2000" in h                       # at most every 2 s
    assert "URL.revokeObjectURL" in h and "r.status === 204" in h and "img.hidden = true" in h
    assert "!document.hidden" in h[h.index("function previewFeed("):h.index("function leftIn(")]


def test_dev_mode():
    h = html()
    assert 'id="devToggle"' in h and 'id="devPanel"' in h and "dev/info" in h
    assert "Dev mode needs a fresh PIN login" in h and "x.status || 0" in h and "st === 401 || st === 403" in h
    assert 'studio.devmode.v1' in h and "function copyBtn(" in h and "navigator.clipboard.writeText" in h
    assert "log_tail" in h and "class: \"envt\"" in h and "co.env" in h
    # storage is guarded
    i = h.index("const store = {")
    assert h[i:i + 400].count("try {") >= 2
    assert 'if (r.status === 401 && o.quiet)' in h                                          # an optional panel never locks the whole page on 401


def test_login_gate_remember_checkbox():
    h = html()
    assert re.search(r'<label class="rem"><input id="rem" type="checkbox" checked>', h) and "Remember this device for 90 days" in h
    assert "remember: !!($(\"#rem\") && $(\"#rem\").checked)" in h and "JSON.stringify({pin: $(\"#pin\").value, remember:" in h
    assert not re.search(r'id="rem"[^>]*style=', h)                                        # styled by the stylesheet, not inline


def test_no_innerhtml_with_server_fields():
    s = script()
    assert not re.search(r"\.(innerHTML|outerHTML)\s*\+?=", s), "server text must go through textContent / createTextNode"
    assert "insertAdjacentHTML" not in s and "document.write" not in s
    assert "eval(" not in s and "new Function" not in s
    # every new panel builds nodes with h() (text children) or textContent
    for fn in ("function histRow(", "function histSummary(", "function devBlock(", "function paintDev2("):
        assert fn in s, fn


def test_motion_focus_and_width_rules():
    h = html()
    assert "prefers-reduced-motion:reduce" in h and ":focus-visible{outline:2px solid" in h
    assert not re.search(r"<script[^>]+src=", h, re.I) and "@import" not in h
    assert ".pv{" in h and "max-height:200px" in h and ".logbox{" in h and "overflow-wrap:anywhere" in h


def test_inline_script_parses():
    node = shutil.which("node")
    if not node:
        print("skip: node not installed"); return
    f = os.path.join(tempfile.mkdtemp(), "studio_m2_inline.js")
    open(f, "w", encoding="utf-8").write(script())
    out = subprocess.run([node, "--check", f], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
