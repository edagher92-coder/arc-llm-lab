"""share_file outbox: lets the model hand a file or a finished website to the owner's phone/laptop over the tailnet.

The model builds something under a configured root (e.g. C:\\AI\\shared). `share_file(path, zip=False)` copies it into the
outbox under an unguessable token (secrets.token_urlsafe(16), 128 bits) and returns a link served by approvals.py at
GET /outbox/<token>/<name>  (published on the tailnet as <public_base>, normally https://<pc>.ts.net:8445/tts/outbox).

Safety (the tool is read-intent, so it runs without approval; it can only COPY from the roots into the outbox):
  * realpath of the source must sit inside a configured root (commonpath); the outbox dir, the gateway dir and any dir that
    holds approval-pin.json / gateway.json are never shareable, nor anything containing them.
  * directory trees may not contain symlinks/junctions (no escape through a link); a top-level symlink is resolved and then
    must still sit inside a root.
  * size cap cfg["outbox"]["max_mb"] (zip counts its final compressed size).
  * links expire (ttl_hours); expired entries and their files are purged on every call and at register().
  * the HTTP side (approvals.py) serves everything with a Content-Security-Policy sandbox so model-authored HTML never runs on
    the approvals page's origin.

Config (cfg["outbox"]): {"dir", "roots", "public_base", "ttl_hours", "max_mb"}.
"""
import json, os, re, secrets, shutil, tempfile, threading, time, zipfile
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,24}$")
INDEX = "index.json"
SECRET_FILES = ("approval-pin.json", "gateway.json")
SECRET_NAMES = SECRET_FILES + (".env",)
DEFAULT_TTL_H, DEFAULT_MAX_MB = 24, 200
DEFAULT_DENY = (r"C:\AI\gateway",)

_lock = threading.RLock()
_DIR = os.environ.get("GW_OUTBOX_DIR", "")      # active outbox dir; set by register(), read by the HTTP route
_now = time.time                                 # tests replace this to simulate time
_blist = list                                    # the builtin: this module also defines list(d) below


class ShareError(Exception):
    pass


def get_dir():
    return _DIR


def _real(p):
    return os.path.normcase(os.path.realpath(p))


def _inside(path, root):
    """True if realpath(path) is root or below it."""
    a, b = _real(path), _real(root)
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:      # different drives
        return False


# ---------------- index ----------------
def _index_path(d):
    return os.path.join(d, INDEX)


def _load(d):
    try:
        with open(_index_path(d), encoding="utf-8") as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def _save(d, idx):
    fd, tmp = tempfile.mkstemp(prefix=".index-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(idx, f)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, _index_path(d))
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def purge(d):
    """Remove expired tokens and orphan token dirs. Returns number removed."""
    if not d or not os.path.isdir(d):
        return 0
    n = 0
    with _lock:
        idx = _load(d); now = _now(); changed = False
        for tok in [t for t, v in idx.items() if not isinstance(v, dict) or float(v.get("expires", 0)) <= now]:
            shutil.rmtree(os.path.join(d, tok), ignore_errors=True)
            idx.pop(tok, None); changed = True; n += 1
        for name in os.listdir(d):             # orphans: crashed copies, leftover temp dirs (older than 10 min)
            full = os.path.join(d, name)
            if name == INDEX or name in idx or not os.path.isdir(full):
                continue
            if (TOKEN_RE.match(name) or name.startswith(".tmp-")) and time.time() - os.path.getmtime(full) > 600:
                shutil.rmtree(full, ignore_errors=True); n += 1
        if changed:
            _save(d, idx)
    return n


# ---------------- source validation ----------------
def _deny_dirs(d, cfg):
    extra = (cfg.get("outbox") or {}).get("deny") or []
    out = [d, HERE, cfg.get("gateway_dir") or "", *DEFAULT_DENY, *extra]
    return [x for x in out if x]


def _holds_secrets(directory):
    return any(os.path.exists(os.path.join(directory, n)) for n in SECRET_FILES)


def _walk_files(top, max_bytes):
    """Yield (abs, rel, size) for every file under top (sorted, deterministic). Rejects symlinks/junctions, secret files and
    total size above max_bytes."""
    total = 0
    for cur, dirs, files in os.walk(top, followlinks=False):
        dirs.sort(); files.sort()
        for n in _blist(dirs) + _blist(files):
            full = os.path.join(cur, n)
            if os.path.islink(full) or _real(full) != os.path.join(_real(cur), os.path.normcase(n)):
                raise ShareError("refusing %r: contains a link (symlink/junction) that could point outside" % os.path.relpath(full, top))
        if _holds_secrets(cur):
            raise ShareError("refusing: the folder contains gateway secrets (approval-pin.json / gateway.json)")
        for n in files:
            if n.lower() in SECRET_NAMES:
                raise ShareError("refusing: the folder contains a secrets file (%s)" % n)
            full = os.path.join(cur, n)
            if not os.path.isfile(full):
                continue
            sz = os.path.getsize(full); total += sz
            if total > max_bytes:
                raise ShareError("too big: more than %d MB" % (max_bytes // (1024 * 1024)))
            yield full, os.path.relpath(full, top).replace(os.sep, "/"), sz


def validate_source(path, cfg):
    """Return realpath of an allowed source or raise ShareError."""
    oc = cfg.get("outbox") or {}
    d = oc.get("dir") or _DIR
    roots = oc.get("roots") or []
    if not roots:
        raise ShareError("share_file is not configured (no roots)")
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        raise ShareError("path is required")
    rp = os.path.realpath(path)
    if not os.path.exists(rp):
        raise ShareError("not found: %s" % path)
    if not any(_inside(rp, r) for r in roots):
        raise ShareError("not allowed: %s is outside the shareable folders (%s)" % (path, ", ".join(roots)))
    for bad in _deny_dirs(d, cfg):
        if _inside(rp, bad) or _inside(bad, rp):
            raise ShareError("not allowed: that location is private to the gateway")
    # no ancestor (up to and including the root it sits under) may hold gateway secrets
    cur = rp if os.path.isdir(rp) else os.path.dirname(rp)
    while True:
        if _holds_secrets(cur):
            raise ShareError("not allowed: that folder holds gateway secrets")
        if any(_real(cur) == _real(r) for r in roots):
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    if os.path.isfile(rp) and os.path.basename(rp).lower() in SECRET_NAMES:
        raise ShareError("not allowed: secrets file")
    if not os.path.isfile(rp) and not os.path.isdir(rp):
        raise ShareError("not a regular file or folder")
    if not os.path.basename(rp):
        raise ShareError("cannot share a filesystem root")
    return rp


# ---------------- publishing ----------------
def _zip_to(top_or_file, dest, max_bytes):
    """Deterministic zip (sorted names, fixed timestamps). Aborts if the zip grows beyond max_bytes."""
    if os.path.isdir(top_or_file):
        items = [(a, r) for a, r, _ in _walk_files(top_or_file, max_bytes * 10)]
        base = os.path.basename(top_or_file.rstrip("/\\"))
        items = [(a, base + "/" + r) for a, r in items]
    else:
        items = [(top_or_file, os.path.basename(top_or_file))]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for a, arc in items:
            zi = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(a, "rb") as src, z.open(zi, "w", force_zip64=True) as out:
                shutil.copyfileobj(src, out, 1 << 20)
            if os.path.getsize(dest) > max_bytes:
                raise ShareError("too big: the zip is larger than %d MB" % (max_bytes // (1024 * 1024)))
    if os.path.getsize(dest) > max_bytes:
        raise ShareError("too big: the zip is larger than %d MB" % (max_bytes // (1024 * 1024)))


def _tree_bytes(path):
    return sum(os.path.getsize(os.path.join(c, f)) for c, _, fs in os.walk(path) for f in fs)


def share(path, zip_it, cfg):
    """Publish path; returns dict(url, name, bytes, expires, token, kind)."""
    global _DIR
    oc = cfg.get("outbox") or {}
    d = oc.get("dir")
    if not d or not oc.get("public_base"):
        raise ShareError("share_file is not configured (outbox.dir / outbox.public_base)")
    os.makedirs(d, exist_ok=True)
    _DIR = d
    ttl_h = float(oc.get("ttl_hours", DEFAULT_TTL_H))
    max_bytes = int(float(oc.get("max_mb", DEFAULT_MAX_MB)) * 1024 * 1024)
    with _lock:
        purge(d)
        rp = validate_source(path, cfg)
        name = os.path.basename(rp)
        token = secrets.token_urlsafe(16)
        tmp = tempfile.mkdtemp(prefix=".tmp-", dir=d)
        try:
            is_dir = os.path.isdir(rp)
            site = is_dir and os.path.isfile(os.path.join(rp, "index.html")) and not zip_it
            if is_dir and not zip_it and not site:
                zip_it = True                       # not a website: ship as one zip
            if site:
                files = _blist(_walk_files(rp, max_bytes))        # validates links/secrets/size first
                for a, r, _ in files:
                    t = os.path.join(tmp, name, *r.split("/"))
                    os.makedirs(os.path.dirname(t), exist_ok=True)
                    shutil.copyfile(a, t)
                kind, entry, size = "site", name + "/index.html", sum(s for _, _, s in files)
            elif zip_it:
                zname = (name if is_dir else os.path.splitext(name)[0] or name) + ".zip"
                _zip_to(rp, os.path.join(tmp, zname), max_bytes)
                kind, entry, name = "zip", zname, zname
                size = os.path.getsize(os.path.join(tmp, zname))
            else:
                size = os.path.getsize(rp)
                if size > max_bytes:
                    raise ShareError("too big: %.1f MB is over the %d MB limit" % (size / 1048576, max_bytes // 1048576))
                shutil.copyfile(rp, os.path.join(tmp, name))
                kind, entry = "file", name
            os.replace(tmp, os.path.join(d, token))
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        expires = _now() + ttl_h * 3600
        idx = _load(d)
        idx[token] = {"name": name, "expires": expires, "bytes": size, "kind": kind, "entry": entry, "created": _now()}
        _save(d, idx)
    url = oc["public_base"].rstrip("/") + "/" + token + "/" + "/".join(quote(p) for p in entry.split("/"))
    return {"url": url, "name": name, "bytes": size, "expires": expires, "token": token, "kind": kind}


# ---------------- list / revoke (Control Centre Files tab) ----------------
def _count_files(base):
    try:
        return sum(len(fs) for _, _, fs in os.walk(base))
    except OSError:
        return 0


def list(d, public_base=None):      # noqa: A001  (deliberate: outbox.list(d) is the contract name)
    """Entries of index.json, newest first, as plain dicts: token, name, kind, size, created, expires, ttl_s (seconds left,
    negative when expired), expired, files (site only) and url (when public_base is given). Pure read: nothing is purged, so
    the result always mirrors index.json (expired entries stay listed until the next purge)."""
    if not d or not os.path.isdir(d):
        return []
    with _lock:
        idx = _load(d)
    now = _now(); out = []
    for tok, v in idx.items():
        if not isinstance(v, dict) or not TOKEN_RE.match(tok):
            continue
        exp = float(v.get("expires", 0))
        base = os.path.join(d, tok)
        try:
            created = float(v.get("created") or os.path.getmtime(base))
        except (OSError, ValueError, TypeError):
            created = 0.0
        e = {"token": tok, "name": str(v.get("name", "")), "kind": v.get("kind", "file"), "size": int(v.get("bytes", 0)),
             "created": created, "expires": exp, "ttl_s": int(exp - now), "expired": exp <= now}
        if e["kind"] == "site":
            e["files"] = _count_files(base)
        if public_base:
            e["url"] = public_base.rstrip("/") + "/" + tok + "/" + "/".join(quote(p) for p in str(v.get("entry") or v.get("name", "")).split("/"))
        out.append(e)
    out.sort(key=lambda e: e["created"], reverse=True)
    return out


def revoke(d, token):
    """Delete the token's files and its index entry now. True if it existed, False if unknown or malformed."""
    if not d or not isinstance(token, str) or not TOKEN_RE.match(token) or not os.path.isdir(d):
        return False
    with _lock:
        idx = _load(d)
        had = token in idx
        base = os.path.join(d, token)
        if os.path.isdir(base) and not os.path.islink(base):
            shutil.rmtree(base, ignore_errors=True); had = True
        if token in idx:
            idx.pop(token, None); _save(d, idx)
    return had


def _qs(req, key):
    q = req.get("query") or ""
    if isinstance(q, dict):
        v = q.get(key)
        return v[0] if isinstance(v, (list, tuple)) and v else (v or "")
    from urllib.parse import parse_qs
    return (parse_qs(str(q).lstrip("?")).get(key) or [""])[0]


def _json_body(req):
    b = req.get("body")
    if isinstance(b, dict):
        return b
    try:
        if isinstance(b, (bytes, bytearray)):
            b = b.decode("utf-8", "replace")
        j = json.loads(b or "{}")
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def register_routes(register_extra, cfg):
    """Hook the Files tab endpoints into approvals.py. register_extra(table) takes {"GET /approvals/outbox/list": handler, ...}
    with handler(req) -> (status, body, ctype), req = {"path", "query", "body", "authed"}. The list exposes live tokens, so it
    is session-only (401 without it); Lane B's dispatcher already enforces the header and session for POSTs, and revoke checks
    req["authed"] again anyway."""
    oc = cfg.get("outbox") or {}
    jt = "application/json"

    def _dir():
        return oc.get("dir") or _DIR

    def h_list(req):
        if not req.get("authed"):
            return 401, json.dumps({"error": "log in with your PIN first"}), jt
        d = _dir()
        pb = oc.get("public_base")
        try:
            return 200, json.dumps(list(d, pb)), jt
        except OSError as e:
            return 500, json.dumps({"error": str(e.strerror or e)}), jt

    def h_revoke(req):
        if not req.get("authed"):
            return 401, json.dumps({"error": "log in with your PIN first"}), jt
        tok = _qs(req, "token") or str(_json_body(req).get("token", ""))
        if not TOKEN_RE.match(tok):
            return 400, json.dumps({"error": "bad token"}), jt
        return (200, json.dumps({"revoked": True}), jt) if revoke(_dir(), tok) else (404, json.dumps({"error": "unknown token"}), jt)

    register_extra({"GET /approvals/outbox/list": h_list, "POST /approvals/outbox/revoke": h_revoke})


# ---------------- lookup for the HTTP route ----------------
def lookup_status(d, token, relpath):
    """Returns (code, abs_path). 200 + path, 404 unknown/unsafe, 410 expired."""
    if not d or not isinstance(token, str) or not TOKEN_RE.match(token):
        return 404, None
    with _lock:
        ent = _load(d).get(token)
    if not isinstance(ent, dict):
        return 404, None
    if float(ent.get("expires", 0)) <= _now():
        return 410, None
    if not isinstance(relpath, str) or "\x00" in relpath:
        return 404, None
    parts = [p for p in relpath.replace("\\", "/").split("/")]
    if parts and parts[-1] == "":
        parts = parts[:-1]                      # trailing slash
    if not parts or any(p in ("", ".", "..") or ":" in p for p in parts):
        return 404, None
    base = os.path.join(d, token)
    if not os.path.isdir(base) or os.path.islink(base):
        return 404, None
    target = os.path.join(base, *parts)
    # first component must be the published name (also keeps stray files out)
    if parts[0] != ent.get("name"):
        return 404, None
    try:
        rt = _real(target)
        rb = _real(base)
        if os.path.commonpath([rt, rb]) != rb or rt == rb:
            return 404, None
        # no symlink anywhere along the way
        cur = base
        for p in parts:
            cur = os.path.join(cur, p)
            if os.path.islink(cur):
                return 404, None
    except (ValueError, OSError):
        return 404, None
    if os.path.isdir(target):
        idx_html = os.path.join(target, "index.html")
        if ent.get("kind") == "site" and os.path.isfile(idx_html):
            return 200, idx_html
        return 404, None
    if os.path.isfile(target):
        return 200, target
    return 404, None


def lookup(d, token, relpath):
    """Absolute file path to serve, or None."""
    code, p = lookup_status(d, token, relpath)
    return p if code == 200 else None


# ---------------- tool registration ----------------
def register(server, cfg):
    """Add the share_file tool to a fastmcp.FastMCP server. Safe to call when outbox is not configured (adds nothing)."""
    global _DIR
    oc = cfg.get("outbox") or {}
    if not oc.get("dir"):
        return None
    _DIR = oc["dir"]
    try:
        os.makedirs(_DIR, exist_ok=True)
        purge(_DIR)
    except OSError:
        pass
    ttl_h = float(oc.get("ttl_hours", DEFAULT_TTL_H))

    @server.tool(name="share_file", description=(
        "Give the user a link to open or download a file or finished website on their phone/laptop. "
        "path must be inside the shared work folders. A folder that contains index.html is published as a website "
        "(link opens index.html); any other folder is zipped. Set zip=true to force a zip. Returns the link to show the user."))
    def share_file(path: str, zip: bool = False) -> str:
        try:
            r = share(path, bool(zip), cfg)
        except ShareError as e:
            return "Not shared: %s" % e
        except OSError as e:
            return "Not shared: %s" % (e.strerror or e)
        kb = max(1, (r["bytes"] + 1023) // 1024)
        hrs = ("%g" % ttl_h)
        return "Shared: %s (%d KB, link works for %s h on your tailnet devices)" % (r["url"], kb, hrs)

    return share_file
