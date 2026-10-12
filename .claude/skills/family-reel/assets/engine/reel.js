// family-reel canvas engine. Everything on screen comes from scenes.json.
// renderFrame(t) is a pure function of time, so the same code plays live in a
// browser (with the music) and renders frame-exact video through render.cjs.
// Optional sections (title, ageing, reunion, endcard, sprites) are skipped when absent.
(async () => {
  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d');
  const RENDER = new URLSearchParams(location.search).has('render');
  if (RENDER) document.body.classList.add('render');

  const CFG = await (await fetch('scenes.json')).json();
  window.CFG = CFG;
  const W = CFG.width || 1080, H = CFG.height || 1920;
  canvas.width = W; canvas.height = H;
  if (CFG.name) document.title = CFG.name;
  CFG.photos = CFG.photos || {}; CFG.videos = CFG.videos || {}; CFG.shots = CFG.shots || [];
  CFG.captions = CFG.captions || []; CFG.blooms = CFG.blooms || []; CFG.lightLeaks = CFG.lightLeaks || [];
  const LOOK = Object.assign({ grade: 0.34, grain: 0.07, vignette: true, particles: 0.45, petals: true }, CFG.look || {});
  const INTRO_END = CFG.intro ? CFG.intro.t1 : 0;
  const END_T0 = CFG.endcard ? CFG.endcard.t0 : CFG.duration + 1;

  // ---------- helpers ----------
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, u) => a + (b - a) * u;
  const smooth = x => { x = clamp(x); return x * x * (3 - 2 * x); };
  const easeInOutSine = x => -(Math.cos(Math.PI * clamp(x)) - 1) / 2;
  const easeOutCubic = x => 1 - Math.pow(1 - clamp(x), 3);
  const easeOutBack = x => { x = clamp(x); const c1 = 1.5, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
  const window01 = (t, a, b, fin, fout) => smooth((t - a) / fin) * (1 - smooth((t - (b - fout)) / fout));
  function mulberry32(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  const mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return [c, c.getContext('2d')]; };
  const pad = (n, k) => String(n).padStart(k, '0');

  // ---------- assets ----------
  const loadImg = src => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('missing asset: ' + src)); i.src = src; });
  const tryImg = src => loadImg(src).catch(() => null);
  const count = async path => { try { const r = await fetch(path); return r.ok ? parseInt(await r.text(), 10) : 0; } catch (e) { return 0; } };
  const IMG = {}, DEPTH = {}, CARD = {}, SPRITE = {}, AGE = {};
  let DEPTH_META = {};
  try { const r = await fetch('assets/depth/depth.json'); if (r.ok) DEPTH_META = await r.json(); } catch (e) { DEPTH_META = {}; }

  const spriteNames = new Set();
  if (CFG.endcard && CFG.endcard.sprite) spriteNames.add(CFG.endcard.sprite.name);
  if (CFG.ageing) for (const s of CFG.ageing.slots) if (s.sprite) spriteNames.add(s.sprite);
  const ageFiles = new Set();
  if (CFG.ageing) for (const step of CFG.ageing.steps) for (const s of CFG.ageing.slots) if (s.key && step[s.key]) ageFiles.add(step[s.key]);

  await Promise.all([
    ...Object.keys(CFG.photos).map(async k => { IMG[k] = await loadImg(`assets/${k}.jpg`); }),
    ...Object.keys(CFG.photos).map(async k => { if (DEPTH_META[k]) DEPTH[k] = await tryImg(`assets/depth/${k}.png`); }),
    ...(CFG.endcard ? CFG.endcard.faces || [] : []).map(async f => { CARD[f.card] = await loadImg(`assets/cards/${f.card}.jpg`); }),
    ...[...spriteNames].map(async name => {
      const n = await count(`assets/sprites/${name}/count.txt`);
      SPRITE[name] = await Promise.all(Array.from({ length: n }, (_, i) => loadImg(`assets/sprites/${name}/${pad(i, 3)}.png`)));
    }),
    ...[...ageFiles].map(async f => { AGE[f] = await loadImg(`assets/${f}`); }),
  ]);
  // web fonts are optional: prep/doctor downloads them; system serif/sans/cursive fonts stand in otherwise
  await Promise.all(['italic 500 80px "Cormorant Garamond"', '120px "Great Vibes"', '500 34px Montserrat']
    .map(f => document.fonts.load(f).catch(() => null)));
  const SERIF_I = px => `italic 500 ${px}px "Cormorant Garamond", Georgia, "Times New Roman", serif`;
  const SANS = px => `500 ${px}px Montserrat, "Helvetica Neue", Arial, sans-serif`;
  const SCRIPT = px => `${px}px "Great Vibes", "Snell Roundhand", "Apple Chancery", cursive`;

  // video snippets and pre-rendered parallax shots are JPEG sequences at W x H, loaded on demand
  const VCOUNT = {}, PCOUNT = {};
  await Promise.all(Object.keys(CFG.videos).map(async v => { VCOUNT[v] = await count(`assets/vid/${v}/count.txt`); }));
  await Promise.all(CFG.shots.filter(s => s.photo && s.depth && !s.fit).map(async s => {
    const n = await count(`assets/par/${s.photo}/count.txt`); if (n) PCOUNT[s.photo] = n;
  }));
  const seqOf = s => s.video ? ['vid', s.video, VCOUNT[s.video]] : (PCOUNT[s.photo] ? ['par', s.photo, PCOUNT[s.photo]] : null);
  const vidIndex = (s, t) => clamp(Math.floor((t - s.t0) * CFG.fps + 1e-6), 0, seqOf(s)[2] - 1);
  const seqKey = (s, i) => { const [dir, name] = seqOf(s); return `assets/${dir}/${name}/${pad(i + 1, 4)}.jpg`; };
  const vcache = new Map();
  async function prepare(t) {
    const need = CFG.shots.filter(s => seqOf(s) && t >= s.t0 && t <= s.t1).map(s => seqKey(s, vidIndex(s, t)));
    await Promise.all(need.map(async k => { if (!vcache.has(k)) vcache.set(k, await loadImg(k)); }));
    for (const k of vcache.keys()) if (vcache.size > 24 && !need.includes(k)) vcache.delete(k);
  }
  const lastVid = {};

  // ---------- WebGL 2.5D parallax: fallback only, parallax.py pre-renders these shots much faster ----------
  const needGL = CFG.shots.some(s => s.photo && s.depth && !s.fit && !PCOUNT[s.photo] && DEPTH[s.photo]);
  const glc = document.createElement('canvas'); glc.width = W; glc.height = H;
  const gl = needGL ? glc.getContext('webgl', { preserveDrawingBuffer: true, premultipliedAlpha: false, antialias: false }) : null;
  let GL = null;
  if (gl) {
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, `attribute vec2 p; varying vec2 uv;
      void main(){ uv = vec2((p.x + 1.0) * 0.5, 1.0 - (p.y + 1.0) * 0.5); gl_Position = vec4(p, 0.0, 1.0); }`));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, `precision highp float; varying vec2 uv;
      uniform sampler2D img; uniform sampler2D dep; uniform vec4 rect; uniform vec2 cam; uniform float focus;
      void main(){
        vec2 src = rect.xy + uv * rect.zw;
        vec2 off = (texture2D(dep, src).r - focus) * cam * rect.zw;
        off = (texture2D(dep, src - off).r - focus) * cam * rect.zw;
        off = (texture2D(dep, src - off).r - focus) * cam * rect.zw;
        gl_FragColor = vec4(texture2D(img, clamp(src - off, vec2(0.001), vec2(0.999))).rgb, 1.0);
      }`));
    gl.linkProgram(prog); gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.uniform1i(gl.getUniformLocation(prog, 'img'), 0); gl.uniform1i(gl.getUniformLocation(prog, 'dep'), 1);
    GL = { rect: gl.getUniformLocation(prog, 'rect'), cam: gl.getUniformLocation(prog, 'cam'), focus: gl.getUniformLocation(prog, 'focus'), tex: new Map() };
    gl.viewport(0, 0, W, H);
  }
  function texFor(key, image) {
    if (GL.tex.has(key)) return GL.tex.get(key);
    const tx = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tx);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
    GL.tex.set(key, tx);
    if (GL.tex.size > 8) { const [k0, t0] = GL.tex.entries().next().value; gl.deleteTexture(t0); GL.tex.delete(k0); }
    return tx;
  }

  // ---------- pre-rendered layers ----------
  const [dust] = (() => { const [c, g] = mk(64, 64); const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    r.addColorStop(0, 'rgba(255,240,205,1)'); r.addColorStop(0.25, 'rgba(255,214,150,0.55)'); r.addColorStop(1, 'rgba(255,190,110,0)');
    g.fillStyle = r; g.fillRect(0, 0, 64, 64); return [c]; })();
  const [bokeh] = (() => { const [c, g] = mk(256, 256); const r = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    r.addColorStop(0, 'rgba(255,225,170,0.55)'); r.addColorStop(0.78, 'rgba(255,215,160,0.45)'); r.addColorStop(0.9, 'rgba(255,230,190,0.6)'); r.addColorStop(1, 'rgba(255,220,170,0)');
    g.fillStyle = r; g.fillRect(0, 0, 256, 256); return [c]; })();
  const [vignette] = (() => { const [c, g] = mk(W, H); const r = g.createRadialGradient(W / 2, H * 0.46, H * 0.28, W / 2, H * 0.5, H * 0.78);
    r.addColorStop(0, 'rgba(0,0,0,0)'); r.addColorStop(1, 'rgba(10,4,0,0.62)'); g.fillStyle = r; g.fillRect(0, 0, W, H); return [c]; })();
  const GW = Math.round(W / 2), GH = Math.round(H / 2);
  const grain = [0, 1, 2, 3].map(s => { const [c, g] = mk(GW, GH); const d = g.createImageData(GW, GH); const rnd = mulberry32(99 + s);
    for (let i = 0; i < d.data.length; i += 4) { const v = 128 + (rnd() - 0.5) * 90; d.data[i] = d.data[i + 1] = d.data[i + 2] = v; d.data[i + 3] = 255; }
    g.putImageData(d, 0, 0); return c; });
  const [backdrop] = (() => { const [c, g] = mk(512, 512); const r = g.createRadialGradient(256, 256, 0, 256, 256, 256);
    r.addColorStop(0, 'rgba(12,6,2,0.74)'); r.addColorStop(0.5, 'rgba(12,6,2,0.52)'); r.addColorStop(1, 'rgba(12,6,2,0)');
    g.fillStyle = r; g.fillRect(0, 0, 512, 512); return [c]; })();
  // blurred "cover" backdrops for landscape photos shown in fit mode
  const BLUR = {};
  for (const s of CFG.shots) if (s.fit && s.photo && !BLUR[s.photo]) {
    const img = IMG[s.photo]; const [c, g] = mk(270, Math.round(270 * H / W));
    const sc = Math.max(c.width / img.naturalWidth, c.height / img.naturalHeight);
    g.filter = 'blur(10px) brightness(0.72) saturate(1.1)';
    g.drawImage(img, (c.width - img.naturalWidth * sc) / 2, (c.height - img.naturalHeight * sc) / 2, img.naturalWidth * sc, img.naturalHeight * sc);
    BLUR[s.photo] = c;
  }

  // particles
  const rnd = mulberry32(2026);
  const DUST = Array.from({ length: 80 }, () => ({ x: rnd() * W, y: rnd() * (H + 200), vy: 10 + rnd() * 26, sway: 8 + rnd() * 34,
    f: 0.2 + rnd() * 0.6, ph: rnd() * 6.28, s: 6 + rnd() * 22, a: 0.25 + rnd() * 0.6, tw: 0.6 + rnd() * 2 }));
  const BOKEH = Array.from({ length: 11 }, () => ({ x: rnd() * W, y: rnd() * H, r: 60 + rnd() * 150, vx: (rnd() - 0.5) * 16, vy: -4 - rnd() * 10, a: 0.05 + rnd() * 0.1, ph: rnd() * 6.28 }));
  const PETALS = Array.from({ length: 26 }, () => ({ x: rnd() * W, y0: rnd() * H, vy: 45 + rnd() * 60, sway: 20 + rnd() * 60, f: 0.3 + rnd() * 0.5,
    ph: rnd() * 6.28, rot: rnd() * 6.28, vr: (rnd() - 0.5) * 2.2, s: 10 + rnd() * 14, hue: rnd() }));

  // ---------- drawing ----------
  // Ken Burns frame: from/to are [cx, cy, frame height] in the photo's "disp" space
  // (default [1, 1] = fractions of the photo), zooming at a constant rate.
  function frameRect(s, t, p, img) {
    const u = easeInOutSine((t - s.t0) / (s.t1 - s.t0));
    const disp = p.disp || [1, 1];
    const from = s.from || [disp[0] / 2, disp[1] / 2, disp[1]], to = s.to || from;
    const cx = lerp(from[0], to[0], u), cy = lerp(from[1], to[1], u);
    const fh = from[2] * Math.pow(to[2] / from[2], u);
    const kx = img.naturalWidth / disp[0], ky = img.naturalHeight / disp[1];
    const w = Math.min(fh * ky * W / H, img.naturalWidth), h = w * H / W;
    const x = clamp(cx * kx - w / 2, 0, img.naturalWidth - w), y = clamp(cy * ky - h / 2, 0, img.naturalHeight - h);
    return { x, y, w, h, u };
  }

  function drawShot(s, t, alpha) {
    let p, img, key;
    if (seqOf(s) && !s.fit) {  // video snippet or pre-rendered parallax: already framed at W x H
      const k = s.video || s.photo;
      img = vcache.get(seqKey(s, vidIndex(s, t))) || lastVid[k];
      if (!img) return;
      lastVid[k] = img;
      ctx.save(); ctx.globalAlpha = alpha; ctx.drawImage(img, 0, 0, W, H); ctx.restore();
      return;
    }
    key = s.photo; p = CFG.photos[key]; img = IMG[key];
    if (!img) return;
    ctx.save(); ctx.globalAlpha = alpha;
    if (s.fit) { // landscape photo: blurred cover + contained sharp photo drifting slowly
      ctx.drawImage(BLUR[key], 0, 0, W, H);
      const u = easeInOutSine((t - s.t0) / (s.t1 - s.t0));
      const sc = lerp(1.0, 1.08, u) * W / img.naturalWidth;
      const w = img.naturalWidth * sc, h = img.naturalHeight * sc;
      const x = (W - w) / 2 + lerp(-12, 12, u), y = (H - h) / 2 - 60;
      ctx.shadowColor = 'rgba(0,0,0,0.45)'; ctx.shadowBlur = 40; ctx.shadowOffsetY = 14;
      ctx.drawImage(img, x, y, w, h);
      ctx.restore();
      return;
    }
    const r = frameRect(s, t, p, img);
    if (GL && s.depth && DEPTH[key]) {
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texFor(key, img));
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, texFor(key + ':d', DEPTH[key]));
      gl.uniform4f(GL.rect, r.x / img.naturalWidth, r.y / img.naturalHeight, r.w / img.naturalWidth, r.h / img.naturalHeight);
      const dir = s.pan || [1, 0.25], m = (r.u - 0.5) * 2 * s.depth;
      gl.uniform2f(GL.cam, dir[0] * m, dir[1] * m);
      gl.uniform1f(GL.focus, DEPTH_META[key].focus);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      ctx.drawImage(glc, 0, 0);
    } else {
      ctx.drawImage(img, r.x, r.y, r.w, r.h, 0, 0, W, H);
    }
    ctx.restore();
  }

  function particles(t, amount) {
    if (amount <= 0) return;
    ctx.save();
    ctx.globalCompositeOperation = 'screen';
    for (const b of BOKEH) {
      const x = ((b.x + b.vx * t) % (W + 400) + W + 400) % (W + 400) - 200;
      const y = ((b.y + b.vy * t) % (H + 400) + H + 400) % (H + 400) - 200;
      ctx.globalAlpha = amount * b.a * (0.7 + 0.3 * Math.sin(t * 0.7 + b.ph));
      ctx.drawImage(bokeh, x - b.r, y - b.r, b.r * 2, b.r * 2);
    }
    ctx.globalCompositeOperation = 'lighter';
    for (const d of DUST) {
      const y = ((d.y - d.vy * t) % (H + 200) + H + 200) % (H + 200) - 100;
      const x = d.x + Math.sin(t * d.f + d.ph) * d.sway;
      ctx.globalAlpha = amount * d.a * (0.55 + 0.45 * Math.sin(t * d.tw + d.ph));
      ctx.drawImage(dust, x - d.s / 2, y - d.s / 2, d.s, d.s);
    }
    ctx.restore();
  }

  function petals(t, amount) {
    if (amount <= 0) return;
    ctx.save();
    for (const p of PETALS) {
      const y = ((p.y0 + p.vy * t) % (H + 100) + H + 100) % (H + 100) - 50;
      const x = p.x + Math.sin(t * p.f + p.ph) * p.sway;
      ctx.globalAlpha = amount * 0.55;
      ctx.translate(x, y); ctx.rotate(p.rot + p.vr * t); ctx.scale(1, 0.55 + 0.35 * Math.sin(t * 2 + p.ph));
      ctx.fillStyle = p.hue > 0.5 ? '#f6c9cf' : '#f9dde0';
      ctx.beginPath(); ctx.ellipse(0, 0, p.s, p.s * 0.62, 0, 0, Math.PI * 2); ctx.fill();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
    }
    ctx.restore();
  }

  function lightLeaks(t) {
    for (const L of CFG.lightLeaks) {
      const a = window01(t, L - 0.9, L + 1.8, 0.8, 1.4);
      if (a <= 0) continue;
      const u = (t - (L - 0.9)) / 2.7;
      const x = lerp(-150, W + 150, u), y = lerp(H * 0.25, H * 0.55, u);
      ctx.save(); ctx.globalCompositeOperation = 'screen'; ctx.globalAlpha = a * 0.6;
      const g = ctx.createRadialGradient(x, y, 0, x, y, 900);
      g.addColorStop(0, 'rgba(255,190,110,0.9)'); g.addColorStop(0.4, 'rgba(255,140,90,0.35)'); g.addColorStop(1, 'rgba(255,120,80,0)');
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H); ctx.restore();
    }
  }

  // Rich text: *italic*, ~script~, ^attribution, plain = spaced caps
  function parseLine(line) {
    if (line.startsWith('^')) return [{ kind: 'attr', text: line.slice(1) }];
    if (line.startsWith('~')) return [{ kind: 'script', text: line.replace(/~/g, '') }];
    const segs = []; let italic = false;
    for (const part of line.split('*')) { if (part) segs.push({ kind: italic ? 'italic' : 'caps', text: part }); italic = !italic; }
    return segs;
  }
  const STYLE = {
    italic: { font: SERIF_I, px: 86, ls: 0, lh: 92, up: false },
    caps:   { font: SANS,    px: 38, ls: 7, lh: 66, up: true },
    attr:   { font: SERIF_I, px: 48, ls: 1, lh: 70, up: false },
    script: { font: SCRIPT,  px: 150, ls: 0, lh: 170, up: false },
  };
  const MAX_W = W * 0.85;
  function setStyle(st, k) { ctx.font = st.font(st.px * k); ctx.letterSpacing = `${st.ls * k}px`; }
  function lineMetrics(segs, scale) {
    const measure = k => { let w = 0; for (const s of segs) { const st = STYLE[s.kind]; setStyle(st, k); s.w = ctx.measureText(st.up ? s.text.toUpperCase() : s.text).width; w += s.w; } return w; };
    let k = scale, w = measure(k);
    if (w > MAX_W) { k *= MAX_W / w; w = measure(k); }  // auto-fit long lines
    const lh = Math.max(...segs.map(s => STYLE[s.kind].lh)) * k;
    return { w, lh, k };
  }
  function drawRich(lines, cx, cy, t, t0, t1, theme, opts = {}) {
    const scale = opts.scale || 1;
    const parsed = lines.map(parseLine);
    const mets = parsed.map(s => lineMetrics(s, scale));
    const total = mets.reduce((a, m) => a + m.lh, 0);
    const out = 1 - smooth((t - (t1 - 0.6)) / 0.6);
    if (theme === 'photo' && opts.backdrop !== false) {
      const bw = Math.max(...mets.map(m => m.w)) + 520, bh = total + 380;
      ctx.save(); ctx.globalAlpha = smooth((t - t0) / 0.6) * out; ctx.drawImage(backdrop, cx - bw / 2, cy - bh / 2, bw, bh); ctx.restore();
    }
    let y = cy - total / 2;
    parsed.forEach((segs, i) => {
      const m = mets[i]; const start = t0 + i * (opts.stagger ?? 0.32);
      const a = smooth((t - start) / 0.75) * out;
      const rise = (1 - easeOutCubic((t - start) / 0.9)) * 28;
      const baseY = y + m.lh * 0.72 + rise;
      y += m.lh;
      if (a <= 0.001) return;
      let x = cx - m.w / 2;
      ctx.save();
      ctx.globalAlpha = a;
      const blur = (1 - a) * 6;
      if (blur > 0.3) ctx.filter = `blur(${blur.toFixed(2)}px)`;
      for (const s of segs) {
        const st = STYLE[s.kind]; setStyle(st, m.k);
        const txt = st.up ? s.text.toUpperCase() : s.text;
        if (theme === 'photo' || theme === 'intro') {
          ctx.shadowColor = 'rgba(0,0,0,0.55)'; ctx.shadowBlur = 18; ctx.shadowOffsetY = 2;
          ctx.fillStyle = s.kind === 'caps' ? 'rgba(255,255,255,0.93)' : s.kind === 'attr' ? 'rgba(242,214,160,0.95)' : '#fff4e2';
          if (s.kind === 'script') { ctx.shadowColor = 'rgba(255,196,110,0.75)'; ctx.shadowBlur = 36; ctx.fillStyle = '#fff6e8'; }
        } else { // paper
          ctx.shadowColor = s.kind === 'script' ? 'rgba(214,168,80,0.45)' : 'rgba(0,0,0,0)'; ctx.shadowBlur = s.kind === 'script' ? 24 : 0;
          ctx.fillStyle = s.kind === 'caps' ? '#5e4636' : '#7b2d3b';
          if (opts.soft) ctx.fillStyle = '#6a4a3a';
        }
        ctx.fillText(txt, x, baseY);
        x += s.w;
      }
      ctx.restore();
    });
  }

  function goldRing(cx, cy, r, prog, width = 7) {
    if (prog <= 0) return;
    const g = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
    g.addColorStop(0, '#b8893a'); g.addColorStop(0.5, '#f3dc9a'); g.addColorStop(1, '#c29440');
    ctx.save(); ctx.strokeStyle = g; ctx.lineWidth = width; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * clamp(prog)); ctx.stroke(); ctx.restore();
  }

  function heartPath(cx, cy, s) {
    ctx.beginPath();
    ctx.moveTo(cx, cy + s * 0.9);
    ctx.bezierCurveTo(cx - s * 1.4, cy, cx - s * 0.9, cy - s * 1.1, cx, cy - s * 0.35);
    ctx.bezierCurveTo(cx + s * 0.9, cy - s * 1.1, cx + s * 1.4, cy, cx, cy + s * 0.9);
  }

  // lift > 0 slides the image down inside the ring so the upper (face) part fills it
  function portrait(img, cx, cy, r, alpha, zoom = 1, lift = 0.12) {
    if (!img || alpha <= 0) return;
    ctx.save(); ctx.globalAlpha = alpha;
    ctx.beginPath(); ctx.arc(cx, cy, r - 2, 0, Math.PI * 2); ctx.clip();
    const s = Math.max((2 * r) / img.naturalWidth, (2 * r) / img.naturalHeight) * zoom;
    const w = img.naturalWidth * s, h = img.naturalHeight * s;
    ctx.drawImage(img, cx - w / 2, cy - h / 2 + (h - 2 * r) * lift, w, h);
    ctx.restore();
  }

  // an animated keyed sprite (a pet, a toy...) with a soft ground shadow and a script label
  function sprite(name, frame, x, y, h, alpha, scale = 1, label = '') {
    const frames = SPRITE[name]; if (!frames || !frames.length || alpha <= 0) return;
    const img = frames[clamp(frame, 0, frames.length - 1)];
    const w = h * img.naturalWidth / img.naturalHeight;
    ctx.save(); ctx.globalAlpha = alpha * 0.26; ctx.fillStyle = '#7a5a3a';
    ctx.beginPath(); ctx.ellipse(x, y + h * 0.43, w * 0.3 * scale, 15 * scale, 0, 0, Math.PI * 2); ctx.fill(); ctx.restore();
    ctx.save(); ctx.globalAlpha = alpha; ctx.translate(x, y); ctx.scale(scale, scale); ctx.drawImage(img, -w / 2, -h / 2, w, h); ctx.restore();
    if (label) { ctx.save(); ctx.globalAlpha = alpha; ctx.font = SCRIPT(52); ctx.letterSpacing = '0px'; ctx.textAlign = 'center';
      ctx.fillStyle = '#7b2d3b'; ctx.fillText(label, x + w * 0.45, y + h * 0.18); ctx.restore(); }
  }

  function paperBackground(alpha, warm = 0) {
    ctx.save(); ctx.globalAlpha = alpha;
    const g = ctx.createRadialGradient(W / 2, H * 0.4, 80, W / 2, H * 0.47, H * 0.65);
    g.addColorStop(0, warm ? '#fff3dc' : '#fffaf1'); g.addColorStop(0.55, warm ? '#f3dcb8' : '#f6ead8'); g.addColorStop(1, warm ? '#d9b48a' : '#e3cbab');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    const halo = ctx.createRadialGradient(W / 2, H * 0.36, 0, W / 2, H * 0.36, H * 0.36);
    halo.addColorStop(0, 'rgba(255,226,160,0.55)'); halo.addColorStop(1, 'rgba(255,226,160,0)');
    ctx.fillStyle = halo; ctx.fillRect(0, 0, W, H);
    ctx.restore();
  }

  // Chapter title card: dusk turning to sunrise
  function titleCard(t) {
    const T = CFG.title; if (!T || t < T.t0 || t > T.t1) return;
    const a = window01(t, T.t0, T.t1, 0.7, 0.6);
    ctx.save(); ctx.globalAlpha = a;
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, '#1d1230'); g.addColorStop(0.55, '#5a2f3a'); g.addColorStop(1, '#d58a4f');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    const sun = ctx.createRadialGradient(W / 2, H * 0.95, 0, W / 2, H * 0.95, 900 + 300 * smooth((t - T.t0) / 3));
    sun.addColorStop(0, 'rgba(255,214,150,0.85)'); sun.addColorStop(1, 'rgba(255,170,100,0)');
    ctx.fillStyle = sun; ctx.fillRect(0, 0, W, H);
    ctx.restore();
    drawRich(T.lines, W / 2, T.y || H * 0.48, t, T.t0 + 0.35, T.t1, 'intro', { stagger: 0.45 });
  }

  // Growing up together: portrait rings age side by side on paper, with an optional sprite.
  // The same layout returns later, frozen on the final ages, as the "reunion".
  function ageing(t) {
    const A = CFG.ageing, R = CFG.reunion;
    if (!A) return;
    let w0, w1, mode;
    if (t >= A.t0 - 0.6 && t <= A.t1 + 0.8) { w0 = A.t0; w1 = A.t1; mode = 'lapse'; }
    else if (R && t >= R.t0 - 0.6 && t <= R.t1 + 0.8) { w0 = R.t0; w1 = R.t1; mode = 'reunion'; }
    else return;
    const a = window01(t, w0 - 0.6, w1 + 0.8, 0.6, 0.8);
    paperBackground(a, 1);
    const n = A.steps.length, xfade = A.xfade ?? 0.45, zoom = A.zoom ?? 1.2, lift = A.lift ?? 0.3;
    let cur, nxt, x = 0;
    if (mode === 'lapse') {
      const dur = (A.t1 - A.t0) / n;
      const f = clamp((t - A.t0) / dur, 0, n - 1e-6);
      const i = Math.floor(f), u = f - i, xf = xfade / dur;
      x = i < n - 1 ? smooth((u - (1 - xf)) / xf) : 0; // crossfade at the end of each step
      cur = A.steps[i]; nxt = A.steps[Math.min(i + 1, n - 1)];
    } else {
      cur = nxt = Object.assign({}, A.steps[n - 1], { label: R.label, age: R.age });
    }
    const pulse = 1 + 0.012 * Math.sin(t * 2.2);
    for (const s of A.slots) {
      if (s.sprite) {
        const frames = SPRITE[s.sprite] || [], fps = s.fps || 12, loop = s.loop || [0, Math.max(0, frames.length - 1)];
        sprite(s.sprite, loop[0] + Math.floor(t * fps) % (loop[1] - loop[0] + 1), s.x, s.y, s.h || 280, a, 1, s.label || '');
        continue;
      }
      const { x: cx, y: cy, r } = s;
      ctx.save(); ctx.globalAlpha = a;
      ctx.shadowColor = 'rgba(110,70,30,0.35)'; ctx.shadowBlur = 30; ctx.shadowOffsetY = 10;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fillStyle = '#fbf6ee'; ctx.fill(); ctx.restore();
      portrait(AGE[cur[s.key]], cx, cy, r, a, zoom * pulse, lift);
      if (x > 0) portrait(AGE[nxt[s.key]], cx, cy, r, a * x, zoom * pulse, lift);
      ctx.save(); ctx.globalAlpha = a; goldRing(cx, cy, r, 1, 7); ctx.restore();
      if (s.label) {
        ctx.save(); ctx.globalAlpha = a; ctx.font = SCRIPT(s.big ? 64 : 52); ctx.letterSpacing = '0px'; ctx.textAlign = 'center'; ctx.fillStyle = '#7b2d3b';
        ctx.fillText(s.label, cx, cy + r + (s.big ? 70 : 60)); ctx.restore();
      }
    }
    const cy0 = A.counterY ?? H * 0.17;
    const drawAge = (step, alpha, dy) => {
      if (alpha <= 0) return;
      ctx.save(); ctx.globalAlpha = a * alpha; ctx.textAlign = 'center';
      ctx.font = SANS(34); ctx.letterSpacing = '8px'; ctx.fillStyle = '#5e4636'; ctx.fillText(step.label || '', W / 2, cy0 - 70 + dy);
      const age = String(step.age ?? '');
      ctx.font = SERIF_I(age.length > 8 ? 110 : 150); ctx.letterSpacing = '0px'; ctx.fillStyle = '#7b2d3b';
      ctx.shadowColor = 'rgba(214,168,80,0.5)'; ctx.shadowBlur = 24; ctx.fillText(age, W / 2, cy0 + 70 + dy); ctx.restore();
    };
    drawAge(cur, 1 - x, -x * 30);
    if (x > 0) drawAge(nxt, x, (1 - x) * 30);
  }

  function endCard(t) {
    const E = CFG.endcard; if (!E) return;
    const a = smooth((t - E.t0) / 1.0);
    if (a <= 0) return;
    paperBackground(a);
    (E.faces || []).forEach((f, i) => {
      const [cx, cy0, r] = f.slot;
      const p = (t - f.at);
      if (p <= 0) return;
      const sc = lerp(0.55, 1, easeOutBack(p / 0.75));
      const al = smooth(p / 0.45) * a;
      const cy = cy0 + Math.sin(t * 1.1 + i * 1.7) * 4 * smooth((p - 0.8) / 1);
      ctx.save(); ctx.globalAlpha = al;
      ctx.translate(cx, cy); ctx.scale(sc, sc);
      ctx.shadowColor = 'rgba(110,70,30,0.35)'; ctx.shadowBlur = 30; ctx.shadowOffsetY = 10;
      ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2); ctx.fillStyle = '#fbf6ee'; ctx.fill();
      ctx.shadowColor = 'transparent';
      ctx.save(); ctx.beginPath(); ctx.arc(0, 0, r - 2, 0, Math.PI * 2); ctx.clip();
      if (CARD[f.card]) ctx.drawImage(CARD[f.card], -r, -r, r * 2, r * 2);
      ctx.restore();
      goldRing(0, 0, r, easeInOutSine((p - 0.1) / 0.9), 7);
      ctx.restore();
      const na = smooth((p - 0.35) / 0.6) * a;
      if (na > 0 && f.label) { ctx.save(); ctx.globalAlpha = na; ctx.font = SCRIPT(58); ctx.letterSpacing = '0px'; ctx.textAlign = 'center';
        ctx.fillStyle = '#7b2d3b'; ctx.fillText(f.label, cx, cy0 + r + 64); ctx.restore(); }
    });

    // an animated sprite plays once, then holds its last pose
    const S = E.sprite;
    if (S && SPRITE[S.name]) {
      const sp = t - S.at;
      if (sp > 0) {
        const al = smooth(sp / 0.5) * a, sc = lerp(0.8, 1, easeOutBack(sp / 0.7));
        const la = smooth((sp - 0.5) / 0.6) * a;
        sprite(S.name, Math.floor(sp * (S.fps || 12)), S.x, S.y, S.h || 240, al, sc, '');
        if (S.label && la > 0) { const img = SPRITE[S.name][0], w = (S.h || 240) * img.naturalWidth / img.naturalHeight;
          ctx.save(); ctx.globalAlpha = la; ctx.font = SCRIPT(52); ctx.letterSpacing = '0px'; ctx.textAlign = 'center';
          ctx.fillStyle = '#7b2d3b'; ctx.fillText(S.label, S.x + w * 0.42, S.y + (S.h || 240) * 0.18); ctx.restore(); }
      }
    }

    for (const L of E.lines || []) {
      drawRich([L.text], W / 2, L.y, t, L.t, CFG.duration + 5, 'paper', { soft: !!L.soft, scale: L.scale || 1 });
    }
    if (E.divider) {
      const dp = easeInOutSine((t - E.divider.t) / 1.1);
      if (dp > 0) {
        ctx.save(); ctx.strokeStyle = '#c9a24a'; ctx.lineWidth = 2.5; ctx.globalAlpha = a;
        const half = 230 * dp, y = E.divider.y;
        ctx.beginPath(); ctx.moveTo(W / 2 - 34, y); ctx.lineTo(W / 2 - 34 - half, y); ctx.moveTo(W / 2 + 34, y); ctx.lineTo(W / 2 + 34 + half, y); ctx.stroke();
        heartPath(W / 2, y + 2, 17 * easeOutBack(dp)); ctx.fillStyle = '#c96b78'; ctx.fill();
        ctx.restore();
      }
    }
  }

  // dark, warm opening behind the first caption (e.g. a quote) until the first photo fades in
  function intro(t) {
    if (!CFG.intro || t > INTRO_END + 2) return;
    const g = ctx.createRadialGradient(W / 2, H * 0.45, 0, W / 2, H * 0.47, H * 0.6);
    g.addColorStop(0, '#3a2412'); g.addColorStop(0.5, '#170d06'); g.addColorStop(1, '#050302');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  }

  function bloom(t) {
    for (const b of CFG.blooms) {
      const a = window01(t, b.t - 1.1, b.t + 1.2, 1.1, 1.1) * 0.86;
      if (a <= 0) continue;
      const p = easeOutCubic((t - (b.t - 1.1)) / 1.6);
      const r = (150 + 1900 * p) * (b.size || 1);
      const y = b.y ?? H * 0.42;
      ctx.save(); ctx.globalAlpha = a;
      const g = ctx.createRadialGradient(W / 2, y, 0, W / 2, y, r);
      g.addColorStop(0, 'rgba(255,248,232,1)'); g.addColorStop(0.45, 'rgba(255,232,190,0.85)'); g.addColorStop(1, 'rgba(255,214,150,0)');
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H); ctx.restore();
    }
  }

  const inWin = (S, t) => S && t > S.t0 - 0.6 && t < S.t1 + 0.8;
  const inPaper = t => inWin(CFG.ageing, t) || inWin(CFG.reunion, t) || t > END_T0;

  function renderFrame(t) {
    ctx.save();
    ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.filter = 'none';
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
    intro(t);

    for (const s of CFG.shots) {
      if (t < s.t0 || t > s.t1) continue;
      drawShot(s, t, smooth((t - s.t0) / (s.fade || 0.9)));
    }

    // warm, gentle grade over the photos
    if (LOOK.grade > 0 && t > INTRO_END && t < END_T0 + 1.2) {
      ctx.save(); ctx.globalCompositeOperation = 'soft-light'; ctx.fillStyle = `rgba(255,176,100,${LOOK.grade})`; ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = 'source-over'; ctx.fillStyle = 'rgba(255,214,170,0.05)'; ctx.fillRect(0, 0, W, H); ctx.restore();
    }

    titleCard(t);
    ageing(t);
    endCard(t);
    lightLeaks(t);
    bloom(t);

    const paper = inPaper(t) ? 1 : 0;
    if (LOOK.vignette) { ctx.save(); ctx.globalAlpha = 1 - paper * 0.75; ctx.drawImage(vignette, 0, 0); ctx.restore(); }
    if (LOOK.particles) particles(t, t < INTRO_END ? 1 : paper ? 0.9 : LOOK.particles);
    if (LOOK.petals && CFG.petalsFrom != null) petals(t, window01(t, CFG.petalsFrom, CFG.duration + 5, 1.5, 1) * 0.9);

    for (const c of CFG.captions) {
      if (t < c.t0 - 0.1 || t > c.t1 + 0.1) continue;
      const theme = c.theme || 'photo';
      drawRich(c.lines, W / 2, c.y ?? H * 0.62, t, c.t0, c.t1, theme, { backdrop: !c.lines[0].startsWith('~'), scale: c.scale || 1 });
    }

    if (LOOK.grain > 0) { ctx.save(); ctx.globalCompositeOperation = 'overlay'; ctx.globalAlpha = LOOK.grain;
      ctx.drawImage(grain[Math.floor(t * 24) % 4], 0, 0, W, H); ctx.restore(); }

    const fb = smooth((t - (CFG.duration - 1.0)) / 0.95);
    if (fb > 0) { ctx.fillStyle = `rgba(0,0,0,${fb})`; ctx.fillRect(0, 0, W, H); }
    ctx.restore();
  }

  window.renderFrame = renderFrame;
  window.frameJPEG = async t => { await prepare(t); renderFrame(t); return canvas.toDataURL('image/jpeg', 0.95).slice(23); };
  window.GL_OK = !!GL;
  window.READY = true;

  if (!RENDER) {
    const audio = document.getElementById('music'), btn = document.getElementById('play');
    if (CFG.music) audio.src = CFG.music;
    renderFrame(Math.min(1.5, CFG.duration));
    btn.hidden = false;
    btn.onclick = () => {
      btn.hidden = true; audio.currentTime = 0; audio.play().catch(() => null);
      const start = performance.now();
      const loop = () => {
        const t = audio.duration && !audio.paused ? audio.currentTime : (performance.now() - start) / 1000;
        prepare(t + 0.15); renderFrame(t);
        if (t < CFG.duration) requestAnimationFrame(loop); else btn.hidden = false;
      };
      requestAnimationFrame(loop);
    };
  }
})().catch(e => { window.READY_ERROR = String(e && e.message || e); console.error(e); });
