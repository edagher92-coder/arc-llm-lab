// Frame-exact renderer: drives reel.html in a headless browser and pipes every frame into ffmpeg.
//   node render.cjs                      -> out/reel.mp4 (or scenes.json "output")
//   node render.cjs --stills 3,21,40     -> out/still-3.00.jpg ... (spot-check before a full render)
//   node render.cjs --range 60,75        -> out/segment-60-75.mp4 (video only; splice with scripts/finish.py)
//   node render.cjs --music song.mp3     -> use your own audio instead of score.wav
// Browser: Playwright's Chromium if installed, else an installed Chrome / Edge, else $CHROME_PATH.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { spawn, execSync } = require('node:child_process');

const ROOT = __dirname;
const args = process.argv.slice(2);
const arg = k => (args.includes(k) ? args[args.indexOf(k) + 1] : null);

function loadPlaywright() {
  const cache = path.join(require('node:os').homedir(), '.cache', 'family-reel', 'node', 'node_modules');  // doctor.py --install core
  let globalRoot = null;
  try { globalRoot = execSync('npm root -g', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); } catch (e) { /* no npm */ }
  for (const m of ['playwright', 'playwright-core']) {
    const places = [m, path.join(ROOT, 'node_modules', m), path.join(cache, m)];
    if (globalRoot) places.push(path.join(globalRoot, m));
    for (const where of places) {
      try { return require(where); } catch (e) { /* try the next */ }
    }
  }
  throw new Error('Playwright is not installed. Run: python scripts/doctor.py --install core   (or: npm install playwright)');
}

function findFfmpeg() {
  if (process.env.FFMPEG) return process.env.FFMPEG;
  for (const py of ['python3', 'python', 'py -3']) {
    try { return execSync(`${py} -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"`, { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim(); } catch (e) { /* next */ }
  }
  return 'ffmpeg';
}

async function launchBrowser(chromium) {
  const tries = [
    ['bundled Chromium', {}],
    ['Google Chrome', { channel: 'chrome' }],
    ['Microsoft Edge', { channel: 'msedge' }],
  ];
  const envPath = process.env.CHROME_PATH || process.env.BROWSER_PATH;
  if (envPath) tries.unshift(['$CHROME_PATH', { executablePath: envPath }]);
  for (const p of ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']) if (fs.existsSync(p)) tries.push([p, { executablePath: p }]);
  const errs = [];
  for (const [name, opts] of tries) {
    try { const b = await chromium.launch(opts); console.log('browser:', name); return b; } catch (e) { errs.push(`${name}: ${String(e.message).split('\n')[0]}`); }
  }
  throw new Error('No browser could start.\n  ' + errs.join('\n  ') + '\nInstall one with: npx playwright install chromium  (or set CHROME_PATH)');
}

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.jpg': 'image/jpeg',
  '.png': 'image/png', '.ttf': 'font/ttf', '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.txt': 'text/plain' };

(async () => {
  const { chromium } = loadPlaywright();
  const FFMPEG = findFfmpeg();
  // serve over http: file:// URLs taint the canvas and block toDataURL
  const server = http.createServer((req, res) => {
    const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
    if (!p.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
    fs.readFile(p, (e, d) => {
      if (e) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { 'Content-Type': TYPES[path.extname(p).toLowerCase()] || 'application/octet-stream' });
      res.end(d);
    });
  }).listen(0, '127.0.0.1');
  await new Promise(r => server.once('listening', r));
  const port = server.address().port;

  const cfgFile = JSON.parse(fs.readFileSync(path.join(ROOT, 'scenes.json'), 'utf8'));
  const W = cfgFile.width || 1080, H = cfgFile.height || 1920;
  // WebGL (software) is only needed when parallax shots were not pre-rendered; it also slows the 2D canvas, so opt in.
  const browser = process.env.WEBGL
    ? await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl'] })
    : await launchBrowser(chromium);
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  page.on('pageerror', e => console.error('PAGE ERROR', e));
  await page.goto(`http://127.0.0.1:${port}/reel.html?render=1`);
  await page.waitForFunction(() => window.READY === true || !!window.READY_ERROR, null, { timeout: 300000 });
  const err = await page.evaluate(() => window.READY_ERROR);
  if (err) throw new Error('reel.js failed to load: ' + err + '\n(check that prep.py ran and every asset in scenes.json exists)');
  const cfg = await page.evaluate(() => window.CFG);
  fs.mkdirSync(path.join(ROOT, 'out'), { recursive: true });
  if (cfg.photos && Object.keys(cfg.photos).length === 0) console.warn('warning: scenes.json has no photos');
  console.log('WebGL parallax fallback:', await page.evaluate(() => window.GL_OK));

  const stills = arg('--stills');
  const range = arg('--range') ? arg('--range').split(',').map(Number) : null;
  if (stills) {
    for (const s of stills.split(',').map(Number)) {
      const b64 = await page.evaluate(t => window.frameJPEG(t), s);
      const f = path.join(ROOT, 'out', `still-${s.toFixed(2)}.jpg`);
      fs.writeFileSync(f, Buffer.from(b64, 'base64'));
      console.log('wrote', f);
    }
  } else {
    const N = Math.round(cfg.duration * cfg.fps);
    const [i0, i1] = range ? [Math.round(range[0] * cfg.fps), Math.round(range[1] * cfg.fps)] : [0, N];
    const OUT = path.join(ROOT, arg('--out') || (range ? `out/segment-${range[0]}-${range[1]}.mp4` : (cfg.output || 'out/reel.mp4')));
    fs.mkdirSync(path.dirname(OUT), { recursive: true });
    const musicArg = arg('--music') || cfg.music || (fs.existsSync(path.join(ROOT, 'score.wav')) ? 'score.wav' : null);
    const music = musicArg ? path.resolve(ROOT, musicArg) : null;
    if (!range && !music) console.warn('warning: no score.wav or music file, rendering without sound');
    const audio = range || !music ? ['-an'] : ['-i', music, '-map', '0:v', '-map', '1:a', '-af', `apad,atrim=0:${cfg.duration}`,
      '-c:a', 'aac', '-b:a', '192k', '-ar', '48000'];
    const ff = spawn(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y',
      '-f', 'image2pipe', '-framerate', String(cfg.fps), '-c:v', 'mjpeg', '-i', '-', ...audio,
      '-c:v', 'libx264', '-preset', 'slow', '-crf', arg('--crf') || '17', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.1',
      '-r', String(cfg.fps), '-movflags', '+faststart', OUT],
      { stdio: ['pipe', 'inherit', 'inherit'] });
    const t0 = Date.now();
    console.log(`frames ${i0}..${i1 - 1} of ${N}`);
    for (let i = i0; i < i1; i++) {
      const b64 = await page.evaluate(t => window.frameJPEG(t), i / cfg.fps);
      if (!ff.stdin.write(Buffer.from(b64, 'base64'))) await new Promise(r => ff.stdin.once('drain', r));
      if ((i - i0) % 150 === 0) {
        const done = i - i0, el = (Date.now() - t0) / 1000;
        console.log(`frame ${i}/${N}  ${el.toFixed(0)}s` + (done ? `  ~${((i1 - i) * el / done / 60).toFixed(1)} min left` : ''));
      }
    }
    ff.stdin.end();
    const code = await new Promise(r => ff.on('close', r));
    console.log(code === 0 ? `wrote ${OUT}` : `ffmpeg exited ${code}`);
    if (code !== 0) process.exitCode = 1;
  }
  await browser.close();
  server.close();
})().catch(e => { console.error(String(e.message || e)); process.exit(1); });
