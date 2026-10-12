"""Auto Production nodes for the Elz LTX-2.5 setup (MIT). No torch, no third-party imports: the stdlib only.

ElzProductionPrompt  builds an LTX-2.5 prompt from a short idea plus cheat-sheet entries (grading, sound, effects, styling, camera, lighting, shot, character).
                     'auto' picks entries by deterministic keyword matching of the idea. Template mode only, so it never touches the GPU.
ElzQwenDirector      optional: asks a local OpenAI-compatible LLM to rewrite the template prompt. Fail-soft: any problem returns the template prompt.
"""
import ipaddress, json, os, re, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SHEET_DIR = os.path.join(HERE, "cheatsheets")
MAX_PROMPT_CHARS = 1500
# node input name -> cheat-sheet file/id. Order is also the order the fragments are written in (and the reverse of the order they are dropped in when too long).
SHEETS = (("style", "styling"), ("shot", "shots"), ("camera", "camera"), ("lighting", "lighting"), ("grade", "grading"), ("effects", "effects"), ("sound", "sound"))
DROP_ORDER = ("effects", "shot", "lighting", "grade", "sound", "camera", "style")     # least important first
BASE_NEGATIVE = "worst quality, blurry, jittery motion, distorted anatomy, watermark, subtitles, on-screen text, logo overlays"
DEFAULT_IDEA = "A person stands in a quiet room and looks toward a window as the light slowly changes."
CHAR_FIELDS = ("name", "look", "wardrobe", "voice", "mannerisms")


# ---------- cheat sheets ----------
_CACHE = {}


def load_sheet(name, directory=None):
    """The parsed cheat sheet (dict) or an empty sheet when the file is missing or broken. Cached per path+mtime."""
    path = os.path.join(directory or SHEET_DIR, name + ".json")
    try:
        key = (path, os.path.getmtime(path))
        if key not in _CACHE:
            with open(path, encoding="utf-8") as f:
                _CACHE[key] = json.load(f)
        return _CACHE[key]
    except (OSError, ValueError):
        return {"schema": 1, "sheet": name, "entries": [], "guidance": []}


def entries_of(name, directory=None):
    return [e for e in load_sheet(name, directory).get("entries", []) if isinstance(e, dict) and e.get("id") and e.get("prompt")]


def sheet_choices(name):
    return ["auto", "none"] + [e["id"] for e in entries_of(name)]


def characters(directory=None):
    return [e for e in load_sheet("characters", directory).get("entries", []) if isinstance(e, dict) and e.get("id")]


def production_presets(directory=None):
    p = load_sheet("production_presets", directory).get("presets")
    return p if isinstance(p, dict) else {}


# ---------- deterministic auto selection ----------
def _words(text):
    return re.sub(r"[^a-z0-9' -]+", " ", str(text).lower().replace("_", " "))


def _kw_hit(text, kw):
    kw = _words(kw).strip()
    return bool(kw) and re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text) is not None


def auto_pick(sheet, idea, directory=None):
    """Entry id for this sheet, or None. Score = total words of matching keywords; ties go to the entry listed first; no match -> the entry flagged
    "default" (if any). Pure function of (sheet file, idea): the same idea always gives the same pick."""
    text = " " + _words(idea) + " "
    best, best_score, default = None, 0, None
    for e in entries_of(sheet, directory):
        if e.get("default") and default is None:
            default = e["id"]
        score = sum(max(1, len(_words(k).split())) for k in e.get("keywords", []) if _kw_hit(text, k))
        if score > best_score:
            best, best_score = e["id"], score
    return best or default


def resolve(choice, sheet, idea, auto, directory=None):
    """(entry or None, source) for one dropdown. source is manual / auto / none."""
    if choice in (None, "", "none"):
        return None, "none"
    if choice == "auto":
        if not auto:
            return None, "none"
        eid = auto_pick(sheet, idea, directory)
        src = "auto"
    else:
        eid, src = choice, "manual"
    for e in entries_of(sheet, directory):
        if e["id"] == eid:
            return e, src
    return None, "none"


# ---------- characters ----------
def _clean(v, n=240):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def parse_characters(raw, directory=None):
    """The `character` input -> (list of normalised dicts, list of warnings). Accepts '', an example id, a JSON object, a JSON list (max 3) or plain text."""
    warnings, out = [], []
    raw = (raw or "").strip()
    if not raw:
        return out, warnings
    items = None
    if raw[0] in "{[":
        try:
            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
        except ValueError:
            warnings.append("character JSON is not valid; used as plain text")
    elif re.fullmatch(r"[A-Za-z0-9_-]{1,40}", raw):
        items = [c for c in characters(directory) if c["id"] == raw.lower()]
        if not items:
            warnings.append("unknown character id %r; used as plain text" % raw[:40])
    if items is None:
        return [{"text": _clean(raw, 400)}], warnings
    for it in items[:3]:
        if isinstance(it, dict):
            c = {k: _clean(it.get(k)) for k in CHAR_FIELDS if it.get(k)}
            if c:
                out.append(c)
    if len(items) > 3:
        warnings.append("only the first 3 characters are used")
    return out, warnings


def _lower_first(s):
    return s[:1].lower() + s[1:] if s and not s[:2].isupper() else s


def character_text(chars):
    parts = []
    for c in chars:
        if "text" in c:
            parts.append(c["text"].rstrip(".") + ".")
            continue
        name, look, ward = c.get("name"), c.get("look"), c.get("wardrobe")
        head = name or "A character"
        if look:
            head += (", " if name else " is ") + look
        if ward:
            head += ", wearing " + ward.rstrip(".")
        s = head + "."
        if c.get("mannerisms"):
            s += " " + (name or "They") + " " + c["mannerisms"].rstrip(".") + "."
        if c.get("voice"):
            s += " " + ((name + "'s") if name else "Their") + " voice is " + c["voice"].rstrip(".") + "."
        parts.append(s)
    return " ".join(parts)


# ---------- the prompt ----------
def _pace(length):
    if length <= 3:
        return "A single quick beat."
    if length >= 9:
        return "The scene unfolds over a few unhurried beats."
    return ""


def _sentence(s):
    s = _clean(s, 2000)
    return s if not s or s[-1] in ".!?\"'" else s + "."


def _assemble(idea, char_txt, pace, frags):
    parts = [_sentence(idea), char_txt, pace] + [frags[k] for k, _ in SHEETS if k in frags]
    return " ".join(p for p in parts if p)


def build_plan(idea="", style="auto", grade="auto", sound="auto", effects="auto", camera="auto", lighting="auto", character="", length_seconds=5,
               auto=True, shot="auto", negative_extra="", directory=None):
    """Everything ElzProductionPrompt does, as a pure function returning the plan dict (positive, negative, picks, warnings...)."""
    idea = _clean(idea, 1200) or DEFAULT_IDEA
    idea = idea[:1].upper() + idea[1:]
    try:
        length = max(1, min(60, int(length_seconds)))
    except (TypeError, ValueError):
        length = 5
    choices = {"style": style, "shot": shot, "camera": camera, "lighting": lighting, "grade": grade, "effects": effects, "sound": sound}
    picks, frags, negs, warnings = {}, {}, [], []
    for key, sheet in SHEETS:
        e, src = resolve(choices[key], sheet, idea, bool(auto), directory)
        picks[key] = {"id": e["id"] if e else None, "label": e["label"] if e else None, "source": src}
        if e:
            frags[key] = _sentence(e["prompt"])
            if e.get("negative"):
                negs.append(e["negative"])
    chars, cw = parse_characters(character, directory)
    warnings += cw
    char_txt, pace = character_text(chars), _pace(length)
    dropped = []
    positive = _assemble(idea, char_txt, pace, frags)
    for k in DROP_ORDER:                                             # deterministic trimming: lowest-priority fragments first, never the idea
        if len(positive) <= MAX_PROMPT_CHARS:
            break
        if k in frags:
            del frags[k]; dropped.append(k)
            positive = _assemble(idea, char_txt, pace, frags)
    if len(positive) > MAX_PROMPT_CHARS:
        positive = positive[:MAX_PROMPT_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "."
        warnings.append("prompt cut to %d characters" % MAX_PROMPT_CHARS)
    if dropped:
        warnings.append("dropped to fit %d characters: %s" % (MAX_PROMPT_CHARS, ", ".join(dropped)))
    for k in dropped:
        picks[k]["dropped"] = True
    neg_parts, seen = [], set()
    for n in [_clean(negative_extra, 600)] + negs + [BASE_NEGATIVE]:
        for piece in (p.strip() for p in n.split(",")):
            if piece and piece.lower() not in seen:
                seen.add(piece.lower()); neg_parts.append(piece)
    return {"schema": 1, "idea": idea, "length_seconds": length, "auto": bool(auto), "picks": picks, "characters": chars, "positive": positive,
            "negative": ", ".join(neg_parts), "chars": len(positive), "warnings": warnings}


class ProductionPrompt:
    """Idea + cheat-sheet choices -> LTX-2.5 positive prompt, negative prompt and a JSON plan. 'auto' picks by keywords in the idea; 'none' leaves a category out."""
    @classmethod
    def INPUT_TYPES(s):
        c = lambda sheet: (sheet_choices(sheet), {"default": "auto"})
        return {"required": {"idea": ("STRING", {"multiline": True, "default": ""}),
                             "style": c("styling"), "grade": c("grading"), "sound": c("sound"), "effects": c("effects"), "camera": c("camera"), "lighting": c("lighting"),
                             "length_seconds": ("INT", {"default": 5, "min": 1, "max": 60, "step": 1}),
                             "auto": ("BOOLEAN", {"default": True})},
                "optional": {"character": ("STRING", {"multiline": True, "default": ""}), "shot": c("shots"),
                             "negative_extra": ("STRING", {"forceInput": True})}}
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive", "negative", "plan")
    FUNCTION = "run"
    CATEGORY = "elz/production"

    def run(self, idea, style="auto", grade="auto", sound="auto", effects="auto", camera="auto", lighting="auto", length_seconds=5, auto=True,
            character="", shot="auto", negative_extra=""):
        plan = build_plan(idea, style, grade, sound, effects, camera, lighting, character, length_seconds, auto, shot, negative_extra)
        print("ELZ_PRODUCTION chars=%d picks=%s" % (plan["chars"], ",".join("%s=%s" % (k, v["id"] or "-") for k, v in plan["picks"].items())), flush=True)
        return (plan["positive"], plan["negative"], json.dumps(plan, indent=1, ensure_ascii=False))


# ---------- optional LLM expansion ----------
DEFAULT_ENDPOINT = "http://127.0.0.1:8090/v1/chat/completions"
DEFAULT_MODEL = "qwen3.8-27b"
DEFAULT_KEY_FILE = r"C:\AI\llama-swap\api-key.txt"
MAX_KEY_BYTES = 512
KEY_FILE_ENV = "ELZ_LLM_KEY_FILE"


def _is_local(url):
    """True only for a loopback host: localhost, 127.0.0.0/8 or ::1."""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _realpath(p):
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def key_file_allowed(path):
    """A key file is read only when it is the default key file or the one named by ELZ_LLM_KEY_FILE (compared by resolved real path)."""
    if not path:
        return False
    allowed = [DEFAULT_KEY_FILE] + ([os.environ[KEY_FILE_ENV]] if os.environ.get(KEY_FILE_ENV) else [])
    try:
        return _realpath(path) in {_realpath(a) for a in allowed}
    except (OSError, ValueError):
        return False


def read_key(path):
    """The key text, or '' when unset/unreadable/not allowed. Only an allowed small plain file is read; the value is never logged."""
    try:
        if key_file_allowed(path) and os.path.isfile(path) and os.path.getsize(path) <= MAX_KEY_BYTES:
            with open(path, encoding="utf-8", errors="ignore") as f:
                return f.read().strip()
    except OSError:
        pass
    return ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the Authorization header must not be carried anywhere else."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_open(req, timeout=None):
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)


def director_system_prompt():
    lines = ["You write prompts for the LTX-2.5 video model with audio.",
             "Write ONE flowing present-tense paragraph of at most 180 words. Start with the main action, then specific movements and gestures, appearance, environment, camera angle and movement, and lighting and colour.",
             "Describe the sound: ambient sound, any dialogue in quotes with the speaker named, and music.",
             "Keep every choice from the draft (grade, sound, effects, styling, camera, lighting, characters). You may smooth the wording and add concrete detail that fits the idea. Never add new characters, text on screen, logos or brand names.",
             "Reply with the prompt only: no title, no notes, no quotes around it. Vocabulary examples by category:"]
    for key, sheet in SHEETS:
        es = entries_of(sheet)[:4]
        lines.append("- %s: %s" % (key, "; ".join(_clean(e["prompt"], 110) for e in es)))
    return "\n".join(lines)


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def clean_llm_text(text):
    t = _THINK.sub("", text or "").strip()
    t = re.sub(r"^```[a-z]*\s*|\s*```$", "", t).strip().strip('"').strip()
    t = re.sub(r"\s*\n+\s*", " ", t)
    if len(t) > MAX_PROMPT_CHARS:
        t = t[:MAX_PROMPT_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return t


def direct(template, idea, endpoint, model, key_file, timeout, opener=None):
    """(prompt, status). Raises nothing: on any failure returns (template, 'fallback: <reason>')."""
    note = ""
    try:
        parsed = urllib.parse.urlparse(endpoint or "")
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return template, "fallback: endpoint must be an http(s) URL"
        headers = {"Content-Type": "application/json"}
        if not _is_local(endpoint):
            return template, "fallback: remote endpoint refused (loopback only)"      # nothing is sent, no key is read
        if key_file and not key_file_allowed(key_file):
            key, note = "", " (key file not allowed)"
        else:
            key, note = read_key(key_file), ""
        if key:
            headers["Authorization"] = "Bearer " + key
        body = {"model": model, "temperature": 0.4, "max_tokens": 500, "stream": False, "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "system", "content": director_system_prompt()},
                             {"role": "user", "content": "Idea: %s\n\nDraft prompt to improve:\n%s" % (_clean(idea, 1200), template)}]}
        req = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with (opener or _default_open)(req, timeout=max(1, int(timeout))) as r:
            data = json.loads(r.read(2_000_000).decode("utf-8", "replace"))
        out = clean_llm_text(data["choices"][0]["message"]["content"])
        if len(out) < 20:
            return template, "fallback: empty reply" + note
        return out, "llm: " + str(model) + note
    except urllib.error.HTTPError as ex:
        reason = "HTTP %s" % ex.code
    except Exception as ex:                                   # noqa: BLE001 - fail soft, whatever went wrong
        reason = type(ex).__name__
    return template, "fallback: " + reason + note                    # only the exception class name, never its message: nothing here can carry the key


class QwenDirector:
    """Optional LLM rewrite of the template prompt. Default is fail-soft: unreachable or bad reply -> the template prompt, unchanged. Run it BEFORE the GPU lease
    (the LLM is normally unloaded while ComfyUI runs) or point it at a small CPU model. Sends the key only to a loopback endpoint."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"endpoint": ("STRING", {"default": DEFAULT_ENDPOINT}), "model": ("STRING", {"default": DEFAULT_MODEL}),
                             "api_key_file": ("STRING", {"default": DEFAULT_KEY_FILE}), "timeout": ("INT", {"default": 20, "min": 1, "max": 300}),
                             "skip_if_unavailable": ("BOOLEAN", {"default": True})},
                "optional": {"plan": ("STRING", {"forceInput": True}), "idea": ("STRING", {"multiline": True, "default": ""})}}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive", "status")
    FUNCTION = "run"
    CATEGORY = "elz/production"

    def run(self, endpoint=DEFAULT_ENDPOINT, model=DEFAULT_MODEL, api_key_file=DEFAULT_KEY_FILE, timeout=20, skip_if_unavailable=True, plan="", idea=""):
        template, base_idea = "", idea
        try:
            p = json.loads(plan) if plan and plan.strip().startswith("{") else None
        except ValueError:
            p = None
        if isinstance(p, dict) and p.get("positive"):
            template, base_idea = str(p["positive"]), idea or p.get("idea", "")
        elif plan and plan.strip():
            template = plan.strip()                           # a plain prompt string wired in is fine too
        else:
            template = build_plan(idea)["positive"]
        out, status = direct(template, base_idea, endpoint, model, api_key_file, timeout)
        if status.startswith("fallback") and not skip_if_unavailable:
            raise RuntimeError("ElzQwenDirector: LLM unavailable (%s)" % status)
        print("ELZ_DIRECTOR %s" % status, flush=True)
        return (out, status)


NODE_CLASS_MAPPINGS = {"ElzProductionPrompt": ProductionPrompt, "ElzQwenDirector": QwenDirector}
NODE_DISPLAY_NAME_MAPPINGS = {"ElzProductionPrompt": "Auto Production prompt (Elz)", "ElzQwenDirector": "Qwen director (Elz, optional)"}
