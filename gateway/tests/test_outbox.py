"""Tests for share_file / outbox. Run from gateway/: python -m unittest tests/test_outbox.py -v"""
import asyncio, http.client, json, os, shutil, socket, sys, tempfile, time, unittest, zipfile
from http.server import ThreadingHTTPServer
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "voice"))


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


APPR_PORT = _free_port()
os.environ["GW_APPROVAL_PORT"] = str(APPR_PORT)
import outbox, approvals, tts_server  # noqa: E402
from fastmcp import FastMCP, Client  # noqa: E402

CSP = "sandbox allow-scripts allow-forms allow-popups allow-downloads"
BASE = "https://pc.ts.net:8445/tts/outbox"


def get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse(); body = r.read(); h = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, h, body


def token_and_rel(url):
    rest = url.split("/tts/outbox/", 1)[1]
    tok, rel = rest.split("/", 1)
    return tok, rel


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="obx-")
        cls.shared = os.path.join(cls.tmp, "shared"); cls.out = os.path.join(cls.tmp, "outbox")
        cls.gw = os.path.join(cls.tmp, "shared", "gateway")      # a gateway dir that even sits inside a root
        cls.other = os.path.join(cls.tmp, "elsewhere")
        for d in (cls.shared, cls.out, cls.gw, cls.other): os.makedirs(d, exist_ok=True)
        open(os.path.join(cls.gw, "approval-pin.json"), "w").write("{}")
        open(os.path.join(cls.gw, "gateway.json"), "w").write("{}")
        open(os.path.join(cls.other, "secret.txt"), "w").write("nope")
        cls.cfg = {"outbox": {"dir": cls.out, "roots": [cls.shared], "public_base": BASE, "ttl_hours": 24, "max_mb": 1},
                   "gateway_dir": cls.gw}
        outbox._DIR = cls.out
        approvals.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        outbox._now = time.time

    def tearDown(self):
        outbox._now = time.time

    def mkfile(self, rel, data=b"hello"):
        p = os.path.join(self.shared, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(data); return p

    def share(self, path, z=False, cfg=None):
        return outbox.share(path, z, cfg or self.cfg)


class TestSafety(Base):
    def test_outside_roots_rejected(self):
        with self.assertRaises(outbox.ShareError): self.share(os.path.join(self.other, "secret.txt"))

    def test_dotdot_traversal_rejected(self):
        p = os.path.join(self.shared, "..", "elsewhere", "secret.txt")
        with self.assertRaises(outbox.ShareError): self.share(p)

    def test_symlink_escape_file_rejected(self):
        l = os.path.join(self.shared, "lnk.txt")
        if os.path.lexists(l): os.unlink(l)
        os.symlink(os.path.join(self.other, "secret.txt"), l)
        with self.assertRaises(outbox.ShareError): self.share(l)

    def test_symlink_inside_tree_rejected(self):
        self.mkfile("evil/index.html", b"<html></html>")
        l = os.path.join(self.shared, "evil", "leak")
        if os.path.lexists(l): os.unlink(l)
        os.symlink(self.other, l)
        with self.assertRaises(outbox.ShareError): self.share(os.path.join(self.shared, "evil"))
        with self.assertRaises(outbox.ShareError): self.share(os.path.join(self.shared, "evil"), True)

    def test_gateway_dir_and_secret_files_rejected(self):
        for p in (self.gw, os.path.join(self.gw, "gateway.json"), os.path.join(self.gw, "approval-pin.json")):
            with self.assertRaises(outbox.ShareError, msg=p): self.share(p)

    def test_dir_containing_gateway_rejected(self):
        # the root itself contains the gateway dir (with secrets): sharing it must be refused
        with self.assertRaises(outbox.ShareError): self.share(self.shared)

    def test_outbox_dir_rejected(self):
        cfg = {"outbox": dict(self.cfg["outbox"], roots=[self.tmp])}
        with self.assertRaises(outbox.ShareError): self.share(self.out, cfg=cfg)

    def test_missing_rejected(self):
        with self.assertRaises(outbox.ShareError): self.share(os.path.join(self.shared, "nope.txt"))

    def test_size_cap_file_and_dir_and_zip(self):
        big = self.mkfile("big/big.bin", os.urandom(1024 * 1024 + 10))
        with self.assertRaises(outbox.ShareError): self.share(big)
        with self.assertRaises(outbox.ShareError): self.share(os.path.join(self.shared, "big"), True)   # incompressible zip > cap
        self.mkfile("bigsite/index.html", b"x" * 10)
        self.mkfile("bigsite/a.bin", os.urandom(1024 * 1024 + 10))
        with self.assertRaises(outbox.ShareError): self.share(os.path.join(self.shared, "bigsite"))
        left = [n for n in os.listdir(self.out) if n.startswith(".tmp-")]
        self.assertEqual(left, [])

    def test_tool_returns_error_text(self):
        srv = FastMCP("t"); outbox.register(srv, self.cfg)
        async def go():
            async with Client(srv) as c:
                r = await c.call_tool("share_file", {"path": os.path.join(self.other, "secret.txt")})
                return r.content[0].text
        self.assertTrue(asyncio.run(go()).startswith("Not shared:"))


class TestPublish(Base):
    def test_file_copy_and_url(self):
        p = self.mkfile("doc/report.pdf", b"%PDF-1.4 fake")
        r = self.share(p)
        self.assertEqual(r["kind"], "file")
        tok, rel = token_and_rel(r["url"])
        self.assertRegex(tok, r"^[A-Za-z0-9_-]{20,24}$")
        self.assertEqual(rel, "report.pdf")
        self.assertTrue(r["url"].startswith(BASE + "/"))
        self.assertEqual(open(os.path.join(self.out, tok, "report.pdf"), "rb").read(), b"%PDF-1.4 fake")
        idx = json.load(open(os.path.join(self.out, "index.json")))
        self.assertEqual(idx[tok]["name"], "report.pdf"); self.assertIn("expires", idx[tok]); self.assertEqual(idx[tok]["bytes"], 13)

    def test_non_website_dir_zipped_deterministic(self):
        self.mkfile("notes/b.txt", b"bb"); self.mkfile("notes/a.txt", b"aa"); self.mkfile("notes/sub/c.txt", b"cc")
        r1 = self.share(os.path.join(self.shared, "notes")); r2 = self.share(os.path.join(self.shared, "notes"))
        self.assertEqual(r1["kind"], "zip"); self.assertTrue(r1["url"].endswith("/notes.zip"))
        z1 = open(os.path.join(self.out, r1["token"], "notes.zip"), "rb").read()
        z2 = open(os.path.join(self.out, r2["token"], "notes.zip"), "rb").read()
        self.assertEqual(z1, z2)   # deterministic
        names = zipfile.ZipFile(os.path.join(self.out, r1["token"], "notes.zip")).namelist()
        self.assertEqual(names, ["notes/a.txt", "notes/b.txt", "notes/sub/c.txt"])

    def test_zip_flag_on_file(self):
        p = self.mkfile("z/one.txt", b"1")
        r = self.share(p, True)
        self.assertEqual(r["kind"], "zip"); self.assertTrue(r["url"].endswith("/one.zip"))

    def test_website_dir_published_unzipped(self):
        self.mkfile("site/index.html", b'<link rel="stylesheet" href="css/app.css"><script src="js/app.js"></script>')
        self.mkfile("site/css/app.css", b"body{color:red}"); self.mkfile("site/js/app.js", b"console.log(1)")
        r = self.share(os.path.join(self.shared, "site"))
        self.assertEqual(r["kind"], "site"); self.assertTrue(r["url"].endswith("/site/index.html"))
        tok, rel = token_and_rel(r["url"])
        self.assertTrue(os.path.isfile(os.path.join(self.out, tok, "site", "css", "app.css")))

    def test_site_with_zip_true_is_zipped(self):
        self.mkfile("site2/index.html", b"x")
        self.assertEqual(self.share(os.path.join(self.shared, "site2"), True)["kind"], "zip")

    def test_tool_message(self):
        srv = FastMCP("t"); outbox.register(srv, self.cfg)
        p = self.mkfile("msg/hello.txt", b"x" * 2048)
        async def go():
            async with Client(srv) as c:
                names = [t.name for t in await c.list_tools()]
                r = await c.call_tool("share_file", {"path": p})
                return names, r.content[0].text
        names, text = asyncio.run(go())
        self.assertIn("share_file", names)
        self.assertRegex(text, r"^Shared: https://pc\.ts\.net:8445/tts/outbox/[\w-]{22}/hello\.txt \(2 KB, link works for 24 h on your tailnet devices\)$")

    def test_purge_on_register_and_call(self):
        r = self.share(self.mkfile("p/old.txt"))
        outbox._now = lambda: time.time() + 25 * 3600
        outbox.register(FastMCP("t"), self.cfg)           # purge at register
        self.assertFalse(os.path.exists(os.path.join(self.out, r["token"])))
        self.assertNotIn(r["token"], json.load(open(os.path.join(self.out, "index.json"))))
        outbox._now = time.time
        r = self.share(self.mkfile("p/old2.txt"))
        outbox._now = lambda: time.time() + 25 * 3600
        self.share(self.mkfile("p/new.txt"))                # purge on call
        self.assertFalse(os.path.exists(os.path.join(self.out, r["token"])))


class TestLookup(Base):
    def setUp(self):
        super().setUp()
        self.mkfile("lk/index.html", b"<html></html>"); self.mkfile("lk/a/b.txt", b"b")
        self.s = self.share(os.path.join(self.shared, "lk")); self.tok = self.s["token"]
        self.f = self.share(self.mkfile("lk2/file.txt", b"f")); self.ftok = self.f["token"]

    def test_ok(self):
        self.assertTrue(outbox.lookup(self.out, self.tok, "lk/a/b.txt").endswith("b.txt"))
        self.assertTrue(outbox.lookup(self.out, self.tok, "lk/index.html").endswith("index.html"))
        self.assertTrue(outbox.lookup(self.out, self.tok, "lk").endswith("index.html"))   # dir -> index.html

    def test_bad_token_shapes(self):
        for t in ("short", "x" * 30, "../" + self.tok[:18], self.tok + "!", ""):
            self.assertIsNone(outbox.lookup(self.out, t, "lk/index.html"))

    def test_traversal(self):
        for rel in ("lk/../../index.json", "../index.json", "lk/..", "lk/a/../../../index.json", "/etc/passwd", "lk//index.html", "lk/./index.html", "C:/x"):
            self.assertIsNone(outbox.lookup(self.out, self.tok, rel), rel)
        self.assertIsNone(outbox.lookup(self.out, self.ftok, "../" + self.tok + "/lk/index.html"))

    def test_name_mismatch_and_cross_token(self):
        self.assertIsNone(outbox.lookup(self.out, self.ftok, "other.txt"))
        self.assertIsNone(outbox.lookup(self.out, self.ftok, "lk/index.html"))     # token A with token B's name
        self.assertIsNone(outbox.lookup(self.out, self.tok, "file.txt"))

    def test_expired(self):
        outbox._now = lambda: time.time() + 25 * 3600
        self.assertEqual(outbox.lookup_status(self.out, self.tok, "lk/index.html")[0], 410)
        self.assertIsNone(outbox.lookup(self.out, self.tok, "lk/index.html"))


class TestHTTP(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tts_server.APPROVALS_URL = "http://127.0.0.1:%d" % APPR_PORT
        cls.tts_port = _free_port()
        cls.tts = ThreadingHTTPServer(("127.0.0.1", cls.tts_port), tts_server.make_handler(lambda *a, **k: b""))
        threading.Thread(target=cls.tts.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.tts.shutdown(); super().tearDownClass()

    def both(self, rel_url_path):
        """Fetch through the approvals server and through the tts proxy; return both results."""
        return get(APPR_PORT, rel_url_path), get(self.tts_port, rel_url_path)

    def publish_site(self):
        self.mkfile("web/index.html", b'<!doctype html><link rel="stylesheet" href="css/app.css"><img src="img/p.png"><script src="js/app.js"></script>')
        self.mkfile("web/css/app.css", b"body{}"); self.mkfile("web/js/app.js", b"1"); self.mkfile("web/img/p.png", b"\x89PNG")
        self.mkfile("web/data.json", b"{}"); self.mkfile("web/x.svg", b"<svg/>"); self.mkfile("web/readme.md", b"# hi")
        self.mkfile("web/bin.dat", b"\x00\x01")
        return self.share(os.path.join(self.shared, "web"))["token"]

    def test_site_over_http_with_relative_assets_and_headers(self):
        tok = self.publish_site()
        types = {"index.html": "text/html", "css/app.css": "text/css", "js/app.js": "text/javascript", "img/p.png": "image/png",
                 "data.json": "application/json", "x.svg": "image/svg+xml", "readme.md": "text/markdown"}
        for rel, ct in types.items():
            for res in self.both("/outbox/%s/web/%s" % (tok, rel)):
                st, h, body = res
                self.assertEqual(st, 200, rel)
                self.assertTrue(h["content-type"].startswith(ct), (rel, h["content-type"]))
                self.assertEqual(h["content-security-policy"], CSP, rel)
                self.assertEqual(h["x-content-type-options"], "nosniff"); self.assertEqual(h["cache-control"], "no-store")
                self.assertNotIn("content-disposition", h, rel)
        st, h, body = get(APPR_PORT, "/outbox/%s/web/bin.dat" % tok)
        self.assertEqual(st, 200); self.assertIn("attachment", h["content-disposition"])
        # relative link resolution like a browser: index.html at .../web/index.html + css/app.css
        self.assertEqual(get(self.tts_port, "/outbox/%s/web/css/app.css?v=1" % tok)[2], b"body{}")
        # tailscale may leave the /tts prefix on
        self.assertEqual(get(APPR_PORT, "/tts/outbox/%s/web/js/app.js" % tok)[0], 200)

    def test_pdf_inline_zip_attachment(self):
        p = self.share(self.mkfile("o/a.pdf", b"%PDF"))["token"]; z = self.share(os.path.join(self.shared, "o"), True)
        st, h, _ = get(APPR_PORT, "/outbox/%s/a.pdf" % p); self.assertEqual((st, h["content-type"]), (200, "application/pdf")); self.assertNotIn("content-disposition", h)
        zt, zrel = token_and_rel(z["url"])
        st, h, body = get(self.tts_port, "/outbox/%s/%s" % (zt, zrel))
        self.assertEqual(st, 200); self.assertEqual(h["content-type"], "application/zip"); self.assertIn("attachment", h["content-disposition"])
        self.assertEqual(h["content-security-policy"], CSP)
        self.assertEqual(body, open(os.path.join(self.out, zt, zrel), "rb").read())

    def test_errors_carry_csp_and_status(self):
        tok = self.publish_site()
        cases = [("/outbox/%s/web/nope.html" % tok, 404), ("/outbox/%s/other/index.html" % tok, 404), ("/outbox/short/web/index.html", 404),
                 ("/outbox/%s/web/../../index.json" % tok, 404), ("/outbox/%s/%%2e%%2e/index.json" % tok, 404),
                 ("/outbox/%s/web%%2Findex.html" % tok, 404), ("/outbox/" + "A" * 22 + "/web/index.html", 404), ("/outbox/%s/" % tok, 404)]
        for path, code in cases:
            for st, h, _ in self.both(path):
                self.assertEqual(st, code, path); self.assertEqual(h.get("content-security-policy"), CSP, path)
        # raw traversal that bypasses http.client normalisation
        s = socket.create_connection(("127.0.0.1", APPR_PORT)); s.sendall(("GET /outbox/%s/web/../../index.json HTTP/1.0\r\n\r\n" % tok).encode())
        self.assertIn(b" 404 ", s.recv(4096).split(b"\r\n")[0] + b" "); s.close()

    def test_expired_410_over_http(self):
        tok = self.publish_site()
        outbox._now = lambda: time.time() + 25 * 3600
        for st, h, _ in self.both("/outbox/%s/web/index.html" % tok):
            self.assertEqual(st, 410); self.assertEqual(h["content-security-policy"], CSP)

    def test_approvals_page_still_works_and_has_no_outbox_csp(self):
        st, h, body = get(APPR_PORT, "/approvals"); self.assertEqual(st, 200); self.assertIn(b"Tool approvals", body)
        self.assertNotIn("content-security-policy", h)
        st, h, body = get(self.tts_port, "/approvals/pending.json"); self.assertEqual(st, 401)
        # a file literally named approvals.html under outbox must not be taken for the approvals page
        tok = self.share(self.mkfile("ap/approvals.html", b"<p>mine</p>"))["token"]
        st, h, body = get(APPR_PORT, "/outbox/%s/approvals.html" % tok)
        self.assertEqual((st, body), (200, b"<p>mine</p>")); self.assertEqual(h["content-security-policy"], CSP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
