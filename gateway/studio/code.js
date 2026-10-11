// Studio code tab (M1): chat with the local Qwen ("Code" and "Plan" presets) over POST /approvals/studio/api/chat (SSE).
// ES module: export function mount(el, api). No external libraries. Every node is built with createElement/textContent, so nothing is ever parsed as markup.
// The Bearer key lives on the PC only; this file never sees it.

const CHAT_URL = "/approvals/studio/api/chat";
const MAX_FILE = 200 * 1024;
const MAX_INPUT = 250 * 1024;
const KEEP = 50;
const DB_NAME = "studio-code", STORE = "convs";

const TEMPLATES = [
  ["Explain", "Explain what this code does, step by step, and point out anything surprising:\n\n"],
  ["Refactor", "Refactor this for clarity and fewer moving parts. Keep behaviour identical and show the result:\n\n"],
  ["Write tests", "Write focused tests for this. Cover the normal path, edge cases and failure modes:\n\n"],
  ["Review diff", "Review this diff. List bugs and risks first, ordered by severity, then style nits:\n\n"],
];
const PRESETS = [["code", "Code"], ["plan", "Plan"]];

const CSS = `
.qc{--q-bg:var(--bg,#060a14);--q-deck:var(--deck,#0b1222);--q-raise:var(--raise,#111b33);--q-line:var(--line,#1e2b4a);--q-line2:var(--line2,#2d4070);--q-ink:var(--ink,#eaf0ff);--q-mute:var(--mute,#a3b1d1);--q-faint:var(--faint,#8493b8);--q-cobalt:var(--cobalt,#3f6fff);--q-hi:var(--cobalt-hi,#9db8ff);--q-ember:var(--ember,#ff6b2c);--q-stop:var(--stop,#ff6f86);--q-go:var(--go,#46d39a);--q-wait:var(--wait,#f5b94a);--q-mono:var(--mono,ui-monospace,"Cascadia Mono","SF Mono",Consolas,monospace);
 position:relative;display:flex;flex-direction:column;height:100%;min-height:0;color:var(--q-ink);font:15px/1.5 var(--body,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif);background:var(--q-bg)}
.qc *{box-sizing:border-box}.qc [hidden]{display:none!important}
.qc button{font:inherit;color:inherit;cursor:pointer;touch-action:manipulation}
.qc-top{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--q-deck);border-bottom:1px solid var(--q-line);flex:none}
.qc-btn{min-height:44px;min-width:44px;padding:6px 12px;border:1px solid var(--q-line2);border-radius:12px;background:var(--q-bg)}
.qc-btn:hover{border-color:var(--q-hi)}.qc-btn:active{transform:scale(.96)}
.qc-btn.go{background:var(--q-ember);border-color:var(--q-ember);color:#1b0b03;font-weight:700}
.qc-btn.stop{border-color:var(--q-stop);color:var(--q-stop);font-weight:700}
.qc-btn:disabled{opacity:.5;cursor:default}
.qc-seg{display:flex;border:1px solid var(--q-line2);border-radius:12px;overflow:hidden;flex:none}
.qc-seg button{border:0;border-radius:0;min-height:44px;padding:6px 14px;background:var(--q-bg);font-weight:600}
.qc-seg button[aria-pressed=true]{background:var(--q-cobalt);color:#fff}
.qc-title{flex:1 1 0;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--q-mute);font-size:13px}
.qc-body{position:relative;flex:1 1 0;min-height:0;display:flex}
.qc-list{flex:1 1 0;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:12px;display:flex;flex-direction:column;gap:12px}
.qc-empty{margin:auto;max-width:34ch;text-align:center;color:var(--q-faint)}
.qc-msg{max-width:100%;border:1px solid var(--q-line);border-radius:14px;padding:10px 12px;background:var(--q-deck);min-width:0}
.qc-msg.user{background:#14224a;border-color:var(--q-line2);align-self:flex-end;max-width:92%}
.qc-msg.err{border-color:var(--q-stop)}
.qc-role{font:700 11px var(--q-mono);letter-spacing:.1em;text-transform:uppercase;color:var(--q-faint);margin-bottom:4px}
.qc-p{white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 .5em}.qc-p:last-child{margin-bottom:0}
.qc-ic{font-family:var(--q-mono);font-size:.9em;background:var(--q-raise);border-radius:5px;padding:1px 5px}
.qc-think{margin:0 0 8px;border-left:2px solid var(--q-line2);padding-left:10px;color:var(--q-mute);font-size:13px}
.qc-think summary{cursor:pointer;min-height:32px;display:flex;align-items:center;color:var(--q-faint)}
.qc-think div{white-space:pre-wrap;overflow-wrap:anywhere}
.qc-code{margin:8px 0;border:1px solid var(--q-line2);border-radius:10px;overflow:hidden;background:#050810}
.qc-ch{display:flex;align-items:center;gap:6px;padding:4px 6px 4px 10px;background:var(--q-raise);border-bottom:1px solid var(--q-line)}
.qc-lang{flex:1;font:700 11px var(--q-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--q-faint)}
.qc-ch button{min-height:36px;min-width:36px;padding:2px 10px;border:1px solid var(--q-line2);border-radius:8px;background:var(--q-bg);font-size:13px}
.qc-code pre{margin:0;padding:10px 12px;overflow-x:auto;font:13px/1.45 var(--q-mono);tab-size:4;white-space:pre}
.qc-code.wrap pre{white-space:pre-wrap;overflow-wrap:anywhere}
.qc-k{color:#9db8ff}.qc-s{color:#7fe3b0}.qc-n{color:#ffb070}.qc-c{color:#7d8bb0;font-style:italic}.qc-f{color:#ffd37a}
.qc-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.qc-chip{font:12px var(--q-mono);border:1px solid var(--q-line2);border-radius:999px;padding:2px 10px;color:var(--q-mute);background:var(--q-bg)}
.qc-chip b{color:var(--q-ink);font-weight:600}
.qc-banner{margin:12px;padding:12px;border:1px solid var(--q-wait);border-radius:12px;background:#2a2008;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.qc-banner span{flex:1 1 200px}
.qc-bar{flex:none;padding:8px 12px calc(8px + env(safe-area-inset-bottom));background:var(--q-deck);border-top:1px solid var(--q-line);display:flex;flex-direction:column;gap:8px}
.qc-row{display:flex;gap:6px;flex-wrap:wrap}
.qc-tpl{min-height:36px;padding:2px 12px;border:1px solid var(--q-line2);border-radius:999px;background:var(--q-bg);font-size:13px;color:var(--q-mute)}
.qc-files{display:flex;gap:6px;flex-wrap:wrap}
.qc-file{display:flex;align-items:center;gap:6px;border:1px solid var(--q-cobalt);border-radius:999px;padding:2px 4px 2px 10px;font:12px var(--q-mono)}
.qc-file button{border:0;background:none;min-height:28px;min-width:28px;color:var(--q-stop)}
.qc-in{display:flex;gap:8px;align-items:flex-end}
.qc-in textarea{flex:1 1 0;min-width:0;min-height:48px;max-height:35vh;resize:none;padding:10px 12px;border:1px solid var(--q-line2);border-radius:12px;background:var(--q-bg);color:var(--q-ink);font:15px/1.4 var(--body,system-ui,sans-serif)}
.qc-in textarea:focus{outline:2px solid var(--q-hi);outline-offset:1px}
.qc-drop{position:absolute;inset:0;display:grid;place-items:center;background:#060a14cc;border:2px dashed var(--q-ember);border-radius:12px;pointer-events:none;font-weight:700;z-index:3}
.qc-drawer{position:absolute;inset:0 30% 0 0;min-width:260px;max-width:100%;z-index:4;background:var(--q-deck);border-right:1px solid var(--q-line2);display:flex;flex-direction:column;box-shadow:8px 0 24px #0008}
.qc-drawer h3{margin:0;padding:12px;font:700 13px var(--q-mono);letter-spacing:.1em;text-transform:uppercase;color:var(--q-faint)}
.qc-convs{flex:1;overflow-y:auto;padding:0 8px}
.qc-conv{display:flex;gap:6px;margin-bottom:6px}
.qc-conv button.o{flex:1;min-width:0;text-align:left;border:1px solid var(--q-line);border-radius:10px;background:var(--q-bg);padding:8px 10px;min-height:44px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qc-conv.cur button.o{border-color:var(--q-cobalt)}
.qc-conv small{display:block;color:var(--q-faint);font:11px var(--q-mono)}
.qc-foot{padding:8px;display:flex;gap:8px;border-top:1px solid var(--q-line)}
@media (max-width:520px){.qc-drawer{inset:0 12% 0 0}}
@media (prefers-reduced-motion:reduce){.qc *{transition:none!important;animation:none!important}}
`;

// ---------- tiny DOM helper (text only, never markup) ----------
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const k in attrs || {}) {
    const v = attrs[k];
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}

// ---------- tiny highlighter (py, js, ps1, json, sh, sql) ----------
const KW = {
  py: "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield self print",
  js: "async await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while yield",
  ps1: "begin break catch class continue data do dynamicparam else elseif end exit filter finally for foreach from function if in param process return switch throw trap try until using var while $true $false $null",
  json: "true false null",
  sh: "if then else elif fi for while until do done case esac function in select time echo export local return exit cd source alias unset set read",
  sql: "select from where group by order having join left right inner outer full on as and or not null is in like between insert into values update set delete create table alter drop index view distinct limit offset union all case when then else end primary key foreign references default count sum avg min max",
};
const ALIAS = { python: "py", py: "py", javascript: "js", js: "js", jsx: "js", ts: "js", typescript: "js", mjs: "js", powershell: "ps1", ps1: "ps1", pwsh: "ps1", json: "json",
  sh: "sh", bash: "sh", shell: "sh", zsh: "sh", sql: "sql" };
const COMMENT = { py: "#[^\\n]*", js: "\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/", ps1: "#[^\\n]*|<#[\\s\\S]*?#>", json: "(?!)", sh: "#[^\\n]*", sql: "--[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/" };
const RX = {};
function rxFor(l) {
  if (!RX[l]) {
    const kw = KW[l].split(" ").map((w) => w.replace(/[$]/g, "\\$")).join("|");
    const str = l === "py" ? "\"\"\"[\\s\\S]*?\"\"\"|'''[\\s\\S]*?'''|\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'" :
      l === "js" ? "`(?:\\\\[\\s\\S]|[^`\\\\])*`|\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'" : "\"(?:\\\\.|[^\"\\\\\\n])*\"|'(?:\\\\.|[^'\\\\\\n])*'";
    RX[l] = new RegExp("(" + COMMENT[l] + ")|(" + str + ")|(\\b\\d[\\d_.]*(?:e[+-]?\\d+)?\\b|0x[0-9a-f]+)|(\\b(?:" + kw + ")\\b)" +
      (l === "ps1" ? "|(\\b[A-Z][a-z]+-[A-Za-z]+\\b)" : l === "sh" || l === "json" ? "" : "|(\\b[A-Za-z_]\\w*(?=\\())"), l === "sql" ? "gi" : "g");
  }
  return RX[l];
}
function highlight(code, lang) {
  const l = ALIAS[String(lang || "").toLowerCase()];
  if (!l || code.length > 60000) return [document.createTextNode(code)];
  const rx = rxFor(l), out = [], cls = ["", "qc-c", "qc-s", "qc-n", "qc-k", "qc-f", "qc-f"];
  let last = 0, m;
  rx.lastIndex = 0;
  while ((m = rx.exec(code))) {
    if (m[0] === "") { rx.lastIndex++; continue; }
    if (m.index > last) out.push(document.createTextNode(code.slice(last, m.index)));
    let g = 1;
    while (g < m.length && m[g] === undefined) g++;
    out.push(h("span", { class: cls[g], text: m[0] }));
    last = m.index + m[0].length;
  }
  if (last < code.length) out.push(document.createTextNode(code.slice(last)));
  return out;
}

// ---------- safe markdown-lite: fenced code blocks, `inline code`, paragraphs ----------
function splitBlocks(text) {
  const parts = [], rx = /(^|\n)(`{3,})([^\n`]*)\n([\s\S]*?)(?:\n\2`*(?=\n|$)|$)/g;
  let last = 0, m;
  while ((m = rx.exec(text))) {
    const start = m.index + m[1].length;
    if (start > last) parts.push({ t: "text", v: text.slice(last, start) });
    parts.push({ t: "code", lang: m[3].trim().split(/\s+/)[0] || "", v: m[4] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ t: "text", v: text.slice(last) });
  return parts;
}
function inline(text) {
  return text.split(/(`[^`\n]+`)/).map((s) => (s.length > 2 && s[0] === "`" && s[s.length - 1] === "`") ? h("code", { class: "qc-ic", text: s.slice(1, -1) }) : s);
}
function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type: type || "text/plain" }));
  const a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
const EXT = { py: "py", js: "js", ps1: "ps1", json: "json", sh: "sh", sql: "sql" };
function codeBlock(lang, code) {
  const wrap = h("div", { class: "qc-code" });
  const pre = h("pre", {}, h("code", {}, highlight(code, lang)));
  const copy = h("button", { type: "button", text: "Copy", "aria-label": "Copy code" });
  copy.addEventListener("click", async () => {
    let ok = false;
    try { await navigator.clipboard.writeText(code); ok = true; } catch (_) {
      const t = h("textarea", { style: "position:fixed;opacity:0" }); t.value = code; document.body.append(t); t.select();
      try { ok = document.execCommand("copy"); } catch (_) { /* ignore */ } t.remove();
    }
    copy.textContent = ok ? "Copied" : "Copy failed"; setTimeout(() => { copy.textContent = "Copy"; }, 1400);
  });
  const dl = h("button", { type: "button", text: "Save", "aria-label": "Download code", onclick: () => download("snippet." + (EXT[ALIAS[String(lang).toLowerCase()]] || "txt"), code) });
  const wr = h("button", { type: "button", text: "Wrap", "aria-pressed": "false", onclick: () => { const on = wrap.classList.toggle("wrap"); wr.setAttribute("aria-pressed", on ? "true" : "false"); } });
  wrap.append(h("div", { class: "qc-ch" }, h("span", { class: "qc-lang", text: lang || "text" }), wr, dl, copy), pre);
  return wrap;
}
function renderBody(into, text) {
  into.replaceChildren();
  for (const p of splitBlocks(text)) {
    if (p.t === "code") into.append(codeBlock(p.lang, p.v));
    else for (const para of p.v.split(/\n{2,}/)) if (para.trim()) into.append(h("p", { class: "qc-p" }, inline(para.replace(/^\n+|\n+$/g, ""))));
  }
}

// ---------- IndexedDB (falls back to memory when the browser refuses it) ----------
function openDb() {
  return new Promise((res) => {
    let done = false; const fin = (v) => { if (!done) { done = true; res(v); } };
    try {
      const rq = indexedDB.open(DB_NAME, 1);
      rq.onupgradeneeded = () => rq.result.createObjectStore(STORE, { keyPath: "id" });
      rq.onsuccess = () => fin(rq.result);
      rq.onerror = rq.onblocked = () => fin(null);
    } catch (_) { fin(null); }
  });
}
function store(db) {
  const mem = new Map();
  const tx = (mode, fn) => new Promise((res) => {
    try { const t = db.transaction(STORE, mode); const out = fn(t.objectStore(STORE)); t.oncomplete = () => res(out && out.result !== undefined ? out.result : undefined); t.onerror = t.onabort = () => res(undefined); }
    catch (_) { res(undefined); }
  });
  return {
    async all() { return db ? ((await tx("readonly", (s) => s.getAll())) || []) : [...mem.values()]; },
    async put(c) { if (db) await tx("readwrite", (s) => s.put(c)); else mem.set(c.id, c); },
    async del(id) { if (db) await tx("readwrite", (s) => s.delete(id)); else mem.delete(id); },
  };
}

// ---------- SSE reader ----------
async function* sse(resp) {
  const rd = resp.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await rd.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const blk = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = "message", data = "";
      for (const ln of blk.split("\n")) { if (ln.startsWith("event:")) ev = ln.slice(6).trim(); else if (ln.startsWith("data:")) data += ln.slice(5).trim(); }
      if (!data) continue;
      try { yield [ev, JSON.parse(data)]; } catch (_) { /* skip a damaged frame */ }
    }
  }
}

const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
const fmt = (n, d = 1) => (typeof n === "number" && isFinite(n) ? n.toFixed(d) : "?");
const bytes = (s) => new TextEncoder().encode(s).length;

export function mount(el, api) {
  if (!document.getElementById("qc-css")) document.head.append(h("style", { id: "qc-css", text: CSS }));
  const S = { conv: null, convs: [], files: [], busy: false, paused: false, ctl: null, drawer: false, db: null, st: null, err: "" };
  const off = [];

  const title = h("div", { class: "qc-title" });
  const seg = h("div", { class: "qc-seg", role: "group", "aria-label": "Model preset" });
  const presetBtns = PRESETS.map(([k, label]) => h("button", { type: "button", text: label, "aria-pressed": "false", onclick: () => { if (S.conv) { S.conv.preset = k; persist(); drawTop(); } } }));
  seg.append(...presetBtns);
  const listBtn = h("button", { class: "qc-btn", type: "button", text: "Chats", "aria-label": "Conversations", onclick: () => { S.drawer = !S.drawer; drawDrawer(); } });
  const newBtn = h("button", { class: "qc-btn", type: "button", text: "New", "aria-label": "New chat", onclick: () => newConv() });
  const top = h("div", { class: "qc-top" }, listBtn, seg, title, newBtn);
  const list = h("div", { class: "qc-list", role: "log", "aria-live": "polite" });
  const banner = h("div", { class: "qc-banner", hidden: true });
  const drawer = h("div", { class: "qc-drawer", hidden: true });
  const drop = h("div", { class: "qc-drop", text: "Drop text files to add as context", hidden: true });
  const body = h("div", { class: "qc-body" }, list, drawer, drop);
  const files = h("div", { class: "qc-files" });
  const tpl = h("div", { class: "qc-row" }, TEMPLATES.map(([n, t]) => h("button", { class: "qc-tpl", type: "button", text: n, onclick: () => { ta.value = t + (ta.value ? ta.value : ""); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); grow(); } })));
  const ta = h("textarea", { rows: "1", placeholder: "Ask about code, or paste or drop a file", "aria-label": "Message", enterkeyhint: "send" });
  const attach = h("button", { class: "qc-btn", type: "button", text: "File", "aria-label": "Attach a text file", onclick: () => pick.click() });
  const pick = h("input", { type: "file", multiple: true, hidden: true, onchange: () => { addFiles([...pick.files]); pick.value = ""; } });
  const send = h("button", { class: "qc-btn go", type: "button", text: "Send", onclick: () => go() });
  const stop = h("button", { class: "qc-btn stop", type: "button", text: "Stop", hidden: true, onclick: () => { if (S.ctl) S.ctl.abort(); } });
  const bar = h("div", { class: "qc-bar" }, tpl, files, h("div", { class: "qc-in" }, attach, ta, send, stop), pick);
  const root = h("div", { class: "qc" }, top, banner, body, bar);
  el.replaceChildren(root);

  const grow = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight + 2, window.innerHeight * 0.35) + "px"; };
  ta.addEventListener("input", grow);
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); go(); } });
  ta.addEventListener("paste", (e) => { const fs = [...(e.clipboardData && e.clipboardData.files || [])]; if (fs.length) { e.preventDefault(); addFiles(fs); } });
  let dragN = 0;
  root.addEventListener("dragenter", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { dragN++; drop.hidden = false; } });
  root.addEventListener("dragleave", () => { dragN = Math.max(0, dragN - 1); if (!dragN) drop.hidden = true; });
  root.addEventListener("dragover", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) e.preventDefault(); });
  root.addEventListener("drop", (e) => { dragN = 0; drop.hidden = true; if (e.dataTransfer && e.dataTransfer.files.length) { e.preventDefault(); addFiles([...e.dataTransfer.files]); } });

  // ----- context files -----
  async function addFiles(fs) {
    for (const f of fs) {
      if (f.size > MAX_FILE) { note(f.name + " is over 200 KB"); continue; }
      let t = "";
      try { t = await f.text(); } catch (_) { note("Could not read " + f.name); continue; }
      if (t.includes("\0")) { note(f.name + " is not a text file"); continue; }
      if (S.files.length >= 8) { note("At most 8 files"); break; }
      if (S.files.reduce((a, x) => a + bytes(x.text), 0) + bytes(t) > MAX_INPUT) { note("Too much context; remove a file first"); break; }
      S.files.push({ name: f.name, text: t });
    }
    drawFiles();
  }
  function drawFiles() {
    files.replaceChildren(...S.files.map((f, i) => h("span", { class: "qc-file" }, f.name + " (" + Math.ceil(bytes(f.text) / 1024) + " KB)",
      h("button", { type: "button", "aria-label": "Remove " + f.name, text: "x", onclick: () => { S.files.splice(i, 1); drawFiles(); } }))));
  }
  function note(t) { S.err = t; drawBanner(); setTimeout(() => { if (S.err === t) { S.err = ""; drawBanner(); } }, 5000); }

  // ----- persistence -----
  async function persist() {
    if (!S.conv) return;
    S.conv.updated = Date.now();
    if (!S.convs.includes(S.conv)) S.convs.unshift(S.conv);
    S.convs.sort((a, b) => b.updated - a.updated);
    await S.st.put(S.conv);
    for (const old of S.convs.splice(KEEP)) await S.st.del(old.id);
  }
  function newConv() {
    if (S.busy) return;
    S.conv = { id: uid(), title: "New chat", preset: S.conv ? S.conv.preset : "code", messages: [], updated: Date.now() };
    S.drawer = false; drawAll(); ta.focus();
  }

  // ----- drawing -----
  function drawTop() {
    title.textContent = S.conv ? S.conv.title : "";
    presetBtns.forEach((b, i) => b.setAttribute("aria-pressed", S.conv && S.conv.preset === PRESETS[i][0] ? "true" : "false"));
    seg.querySelectorAll("button").forEach((b) => { b.disabled = S.busy; });
    send.hidden = S.busy; stop.hidden = !S.busy; send.disabled = S.paused; newBtn.disabled = S.busy;
  }
  function drawBanner() {
    banner.replaceChildren();
    if (S.paused) {
      banner.hidden = false;
      const sw = h("button", { class: "qc-btn go", type: "button", text: "Switch GPU to Qwen" });
      sw.addEventListener("click", async () => {
        sw.disabled = true; sw.textContent = "Switching...";
        try { await api.post("mode", { mode: "llm" }); S.paused = false; S.err = ""; }
        catch (e) { S.err = (e && e.error) || "Could not switch the GPU. A render may still be running."; }
        drawAll();
      });
      banner.append(h("span", { text: "Qwen is paused while the GPU is on video work." }), sw);
    } else if (S.err) { banner.hidden = false; banner.append(h("span", { text: S.err })); }
    else banner.hidden = true;
    send.disabled = S.paused && !S.busy;
  }
  function statChips(st) {
    if (!st) return null;
    const c = [];
    const add = (k, v) => c.push(h("span", { class: "qc-chip" }, k + " ", h("b", { text: v })));
    if (st.tps != null) add("gen", fmt(st.tps) + " tok/s");
    if (st.pps != null) add("prompt", fmt(st.pps, 0) + " tok/s");
    if (st.ct != null) add("tokens", String(st.ct) + (st.pt != null ? " out / " + st.pt + " in" : ""));
    if (st.ttft != null) add("first token", fmt(st.ttft / 1000, 2) + " s");
    if (st.ms != null) add("time", fmt(st.ms / 1000) + " s");
    return c.length ? h("div", { class: "qc-chips" }, c) : null;
  }
  function msgNode(m, live) {
    const n = h("div", { class: "qc-msg " + (m.role === "user" ? "user" : "ai") + (m.error ? " err" : "") });
    n.append(h("div", { class: "qc-role", text: m.role === "user" ? "You" : (m.preset === "plan" ? "Qwen Plan" : "Qwen Code") }));
    if (m.files && m.files.length) n.append(h("div", { class: "qc-chips" }, m.files.map((f) => h("span", { class: "qc-chip", text: f }))));
    if (m.think) {
      const d = h("details", { class: "qc-think" }, h("summary", { text: live && !m.content ? "Thinking..." : "Thinking" }), h("div", { text: m.think }));
      if (live && !m.content) d.open = true;
      n.append(d);
    }
    const b = h("div", { class: "qc-bodytxt" }); renderBody(b, m.content || ""); n.append(b);
    if (m.error) n.append(h("div", { class: "qc-p", text: m.error }));
    const ch = live ? null : statChips(m.stats); if (ch) n.append(ch);
    return n;
  }
  function drawList() {
    const near = list.scrollHeight - list.scrollTop - list.clientHeight < 120;
    list.replaceChildren();
    if (!S.conv || !S.conv.messages.length) list.append(h("div", { class: "qc-empty", text: "Qwen runs on your PC. Pick Code or Plan, paste a file or a snippet, and ask." }));
    else S.conv.messages.forEach((m, i) => list.append(msgNode(m, S.busy && i === S.conv.messages.length - 1)));
    if (near) list.scrollTop = list.scrollHeight;
  }
  function drawDrawer() {
    drawer.hidden = !S.drawer;
    if (!S.drawer) return;
    drawer.replaceChildren(h("h3", { text: "Conversations" }),
      h("div", { class: "qc-convs" }, S.convs.length ? S.convs.map((c) => h("div", { class: "qc-conv" + (S.conv && c.id === S.conv.id ? " cur" : "") },
        h("button", { class: "o", type: "button", onclick: () => { if (S.busy) return; S.conv = c; S.drawer = false; drawAll(); } }, c.title, h("small", { text: new Date(c.updated).toLocaleString() + " - " + c.messages.length + " msgs" })),
        h("button", { class: "qc-btn", type: "button", text: "Del", "aria-label": "Delete " + c.title, onclick: async () => {
          if (S.busy) return; S.convs = S.convs.filter((x) => x !== c); await S.st.del(c.id); if (S.conv === c) newConv(); else drawDrawer();
        } }))) : h("div", { class: "qc-empty", text: "No saved chats yet." })),
      h("div", { class: "qc-foot" },
        h("button", { class: "qc-btn", type: "button", text: "Export markdown", onclick: () => exportMd() }),
        h("button", { class: "qc-btn", type: "button", text: "Close", onclick: () => { S.drawer = false; drawDrawer(); } })));
  }
  function exportMd() {
    const cs = S.convs.length ? S.convs : (S.conv ? [S.conv] : []);
    const out = ["# Studio code chats", "", "Exported " + new Date().toISOString(), ""];
    for (const c of cs) {
      out.push("## " + c.title, "", "_" + new Date(c.updated).toISOString() + ", preset " + c.preset + "_", "");
      for (const m of c.messages) {
        out.push("### " + (m.role === "user" ? "You" : "Qwen"), "");
        if (m.files && m.files.length) out.push("Context: " + m.files.join(", "), "");
        out.push(m.content || "", "");
      }
    }
    download("studio-code-chats.md", out.join("\n"), "text/markdown");
  }
  function drawAll() { drawTop(); drawBanner(); drawList(); drawDrawer(); }

  // ----- sending -----
  function history(upto) {
    const ms = S.conv.messages.slice(0, upto).filter((m) => !m.error && (m.content || m.role === "user")).map((m) => ({ role: m.role, content: m.content }));
    let size = ms.reduce((a, m) => a + bytes(m.content), 0);
    while (ms.length > 1 && size > MAX_INPUT) size -= bytes(ms.shift().content);       // oldest turns drop first
    while (ms.length && ms[0].role !== "user") ms.shift();
    return ms;
  }
  async function go() {
    const text = ta.value.trim();
    if (!text || S.busy || !S.conv) return;
    if (S.paused) { drawBanner(); return; }
    const ctx = S.files.slice();
    const um = { role: "user", content: text, files: ctx.map((f) => f.name) };
    const am = { role: "assistant", content: "", think: "", preset: S.conv.preset, stats: null };
    S.conv.messages.push(um, am);
    if (S.conv.messages.length === 2) S.conv.title = text.replace(/\s+/g, " ").slice(0, 48);
    ta.value = ""; grow(); S.files = []; drawFiles(); S.err = "";
    S.busy = true; S.ctl = new AbortController(); drawAll();
    const t0 = performance.now(); let first = null, nd = 0, tl = null;
    const st = { tps: null, pps: null, ct: null, pt: null, ttft: null, ms: null };
    let raf = 0;
    const redraw = () => { raf = 0; const nodes = list.children; const last = nodes[nodes.length - 1]; if (last) last.replaceWith(msgNode(am, true)); if (list.scrollHeight - list.scrollTop - list.clientHeight < 160) list.scrollTop = list.scrollHeight; };
    const later = () => { if (!raf) raf = requestAnimationFrame(redraw); };
    const mark = () => { if (first == null) { first = performance.now(); st.ttft = first - t0; } };
    try {
      const resp = await fetch(CHAT_URL, { method: "POST", credentials: "same-origin", signal: S.ctl.signal,
        headers: { "Content-Type": "application/json", "X-Requested-With": "approvals" },
        body: JSON.stringify({ preset: S.conv.preset, messages: history(S.conv.messages.length - 1).concat([{ role: "user", content: text }]).slice(-40), max_tokens: 4096, context_files: ctx }) });
      if (!resp.ok) {
        let d = {}; try { d = await resp.json(); } catch (_) { /* not json */ }
        if (resp.status === 409 && d.reason === "paused") { S.paused = true; S.conv.messages.splice(-2, 2); ta.value = text; S.files = ctx; drawFiles(); }
        else if (resp.status === 429) { am.error = "Another chat is generating (or too many live streams are open). Try again in a few seconds."; }
        else if (resp.status === 401) { am.error = "Your session has expired. Log in with your PIN and try again."; }
        else am.error = d.error || ("The chat failed (HTTP " + resp.status + ").");
        throw new Error("refused");
      }
      for await (const [ev, d] of sse(resp)) {
        if (ev === "think") { mark(); am.think += d.text || ""; later(); }
        else if (ev === "delta") { mark(); am.content += d.text || ""; nd++; tl = performance.now(); later(); }
        else if (ev === "usage") { st.pt = d.prompt_tokens; st.ct = d.completion_tokens; }
        else if (ev === "timings") { st.tps = d.predicted_per_s; st.pps = d.prompt_per_s; }
        else if (ev === "error") { am.error = d.error || "The model stopped with an error."; }
        else if (ev === "done") { if (d.finish_reason === "length") am.error = "Stopped: reached the token limit. Ask it to continue."; else if (d.error && !am.error) am.error = d.error; }
      }
    } catch (e) {
      if (e && e.name === "AbortError") am.stopped = true;
      else if (e && e.message !== "refused") am.error = am.error || "The connection to the PC dropped.";
    } finally {
      st.ms = performance.now() - t0;
      if (st.tps == null && nd > 1 && first != null && tl > first) st.tps = (nd - 1) / ((tl - first) / 1000);   // fall back to chunks per second when llama.cpp sent no timings
      am.stats = st;
      if (am.stopped && am.content) am.content += "";
      S.busy = false; S.ctl = null;
      if (S.paused) { /* nothing was kept */ } else if (!am.content && !am.think && !am.error && !am.stopped) am.error = "The model returned nothing.";
      if (!S.paused) await persist();
      drawAll();
    }
  }

  // ----- live GPU state (the page's own stream; the 409 is the source of truth) -----
  const unsub = api && api.on ? api.on("sys", (s) => {
    if (S.busy || !s) return;
    const p = s.mode === "video" || s.mode === "busy";
    if (p !== S.paused) { S.paused = p; drawBanner(); drawTop(); }
  }) : null;
  if (typeof unsub === "function") off.push(unsub);
  try { const cur = api && api.state && api.state.sys; if (cur && (cur.mode === "video" || cur.mode === "busy")) S.paused = true; } catch (_) { /* ignore */ }

  (async () => {
    S.db = await openDb(); S.st = store(S.db);
    S.convs = (await S.st.all()).sort((a, b) => b.updated - a.updated).slice(0, KEEP);
    S.conv = S.convs[0] || null;
    if (!S.conv) S.conv = { id: uid(), title: "New chat", preset: "code", messages: [], updated: Date.now() };
    drawAll(); grow();
  })();

  return { destroy() { if (S.ctl) S.ctl.abort(); off.forEach((f) => { try { f(); } catch (_) { /* ignore */ } }); el.replaceChildren(); } };
}

export default { mount };
