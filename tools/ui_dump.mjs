/**
 * Dev tool: headless-Edge DOM geometry dump for the Zapret2 GUI.
 *
 * Requires the dump backend:  python tools/ui_dump_server.py
 * Run:                        node tools/ui_dump.mjs
 *
 * Writes ui_dump.json + ui_dump.png (in cwd) and prints a compact digest.
 * Env overrides: UI_URL, UI_OUT, UI_SHOT, UI_WAIT_MS, UI_EDGE
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const EDGE_CANDIDATES = [
  process.env.UI_EDGE,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);
const EDGE = EDGE_CANDIDATES.find(p => fs.existsSync(p));
if (!EDGE) { console.error('msedge.exe not found'); process.exit(1); }

const APP_URL = process.env.UI_URL || 'http://127.0.0.1:18888/?token=dump';
const UI_HASH = process.env.UI_HASH || '';
const NAV_URL = UI_HASH ? APP_URL + '#' + UI_HASH : APP_URL;
const OUT_JSON = process.env.UI_OUT || 'ui_dump.json';
const OUT_SHOT = process.env.UI_SHOT || 'ui_dump.png';
const WAIT_MS = Number(process.env.UI_WAIT_MS || 12000);
const CDP_PORT = Number(process.env.UI_CDP_PORT || 9333);

const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-ui-dump-'));
const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
  '--disable-extensions', '--mute-audio',
  `--remote-debugging-port=${CDP_PORT}`,
  `--user-data-dir=${profileDir}`,
  '--window-size=1280,840',
  'about:blank',
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function waitForCDP(tries = 80) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      if (r.ok) return await r.json();
    } catch {}
    await sleep(250);
  }
  throw new Error('CDP endpoint did not come up');
}

async function newTab(url) {
  let r = await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
  if (!r.ok) r = await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?${encodeURIComponent(url)}`);
  if (!r.ok) throw new Error('cannot create tab: ' + r.status);
  return await r.json();
}

function connectWS(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => resolve(ws);
    ws.onerror = e => reject(new Error('ws error'));
  });
}

let msgId = 0;
const pending = new Map();
let ws;
function send(method, params = {}) {
  const id = ++msgId;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    setTimeout(() => {
      if (pending.has(id)) { pending.delete(id); reject(new Error('timeout: ' + method)); }
    }, 30000);
  });
}

const DUMP_JS = `(() => {
  const out = [];
  const vw = innerWidth, vh = innerHeight;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
    const ov = el.closest('.modal-overlay');
    if (ov && !ov.classList.contains('open')) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const cls = (typeof el.className === 'string' ? el.className : '').trim();
    out.push({
      tag: el.tagName.toLowerCase(), id: el.id || '', cls,
      text: el.childElementCount === 0 ? (el.textContent || '').trim().slice(0, 60) : '',
      x: Math.round(r.x * 10) / 10, y: Math.round(r.y * 10) / 10,
      w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
      disp: cs.display, pos: cs.position, flexGrow: cs.flexGrow, flexShrink: cs.flexShrink,
      flexBasis: cs.flexBasis, ai: cs.alignItems, js: cs.justifyContent, gap: cs.gap,
      fs: cs.fontSize, lh: cs.lineHeight, wsn: cs.whiteSpace, ta: cs.textAlign,
      minW: cs.minWidth, maxW: cs.maxWidth, hgt: cs.height, minH: cs.minHeight,
      pad: cs.padding, bd: cs.borderWidth, br: cs.borderRadius,
      pTag: el.parentElement ? el.parentElement.tagName.toLowerCase() : '',
      pId: el.parentElement ? el.parentElement.id || '' : '',
      pCls: el.parentElement ? ((typeof el.parentElement.className === 'string' ? el.parentElement.className : '').trim()) : ''
    });
  }
  return JSON.stringify({ vw, vh, url: location.href, title: document.title, els: out });
})()`;

const DIGEST_TAGS = new Set(['button', 'select', 'input', 'textarea', 'summary', 'h1']);
const DIGEST_CLS = ['panel', 'row', 'field', 'svc-actions', 'topbar-actions', 'notice', 'opt-ctl', 'diag-actions', 'list-head', 'probe-actions', 'probe-input-row', 'panel-head', 'banner', 'state', 'nav-link', 'prot-chip', 'step', 'run-head', 'test-options', 'opt-line', 'modal-actions', 'probe-row'];

function digest(els) {
  const lines = [];
  const isInteresting = e => DIGEST_TAGS.has(e.tag) ||
    DIGEST_CLS.some(c => e.cls.split(/\s+/).includes(c)) ||
    ['btn'].some(c => e.cls.split(/\s+/).includes(c));
  for (const e of els) {
    if (!isInteresting(e)) continue;
    if (e.tag === 'div' && e.w === 0) continue;
    const label = `${e.tag}${e.id ? '#' + e.id : ''}${e.cls ? '.' + e.cls.split(/\s+/).join('.') : ''}`;
    const txt = e.text ? ` "${e.text}"` : '';
    const par = `${e.pTag}${e.pId ? '#' + e.pId : ''}${e.pCls ? '.' + e.pCls.split(/\s+/).join('.') : ''}`;
    lines.push(
      `y${String(e.y).padStart(6)} x${String(e.x).padStart(6)} ${String(e.w).padStart(7)}x${String(e.h).padStart(5)}  ${label}${txt}\n` +
      `         parent=${par} disp=${e.disp} pos=${e.pos} grow=${e.flexGrow} fs=${e.fs} lh=${e.lh} wsn=${e.wsn} minW=${e.minW} maxW=${e.maxW} hgt=${e.hgt} minH=${e.minH} pad=${e.pad} gap=${e.gap} ai=${e.ai} js=${e.js}`
    );
  }
  return lines.join('\n');
}

function asciiMap(els, vw, vh, cell = 8) {
  const W = Math.floor(vw / cell), H = Math.floor(vh / cell);
  const g = Array.from({ length: H }, () => Array(W).fill(' '));
  const put = (x, y, ch) => {
    const cx = Math.floor(x / cell), cy = Math.floor(y / cell);
    if (cx >= 0 && cx < W && cy >= 0 && cy < H) g[cy][cx] = ch;
  };
  const box = (e, ch) => {
    const x1 = Math.floor(e.x / cell), y1 = Math.floor(e.y / cell);
    const x2 = Math.floor((e.x + e.w - 1) / cell), y2 = Math.floor((e.y + e.h - 1) / cell);
    for (let x = Math.max(0, x1); x <= Math.min(W - 1, x2); x++) {
      if (y1 >= 0 && y1 < H) g[y1][x] = g[y1][x] === ' ' ? '-' : g[y1][x];
      if (y2 >= 0 && y2 < H) g[y2][x] = g[y2][x] === ' ' ? '-' : g[y2][x];
    }
    for (let y = Math.max(0, y1); y <= Math.min(H - 1, y2); y++) {
      if (x1 >= 0 && x1 < W) g[y][x1] = g[y][x1] === ' ' ? '|' : g[y][x1];
      if (x2 >= 0 && x2 < W) g[y][x2] = g[y][x2] === ' ' ? '|' : g[y][x2];
    }
    if (ch) put(e.x + e.w / 2, e.y + e.h / 2, ch);
  };
  const has = (e, c) => e.cls.split(/\s+/).includes(c);
  for (const e of els) if (has(e, 'panel')) box(e);
  for (const e of els) if (has(e, 'notice')) box(e, '!');
  for (const e of els) if (has(e, 'step')) box(e, 's');
  for (const e of els) if (has(e, 'test-options')) box(e, 'o');
  for (const e of els) if (e.tag === 'select' || e.tag === 'input' || e.tag === 'textarea') box(e, 'S');
  for (const e of els) if (e.tag === 'button' || has(e, 'btn')) box(e, 'B');
  for (const e of els) if (e.tag === 'nav-link' || has(e, 'nav-link')) box(e, 'n');
  for (const e of els) if (e.tag === 'h1') box(e, 'H');
  return g.map(r => r.join('')).join('\n');
}

const json = await (async () => {
  try {
    await waitForCDP();
    const tab = await newTab(APP_URL);
    ws = await connectWS(tab.webSocketDebuggerUrl);
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) {
        const { resolve, reject } = pending.get(m.id);
        pending.delete(m.id);
        m.error ? reject(new Error(m.error.message)) : resolve(m.result);
      }
    };
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1280, height: 840, deviceScaleFactor: 1, mobile: false,
    });
    await send('Page.navigate', { url: NAV_URL });
    await sleep(WAIT_MS);
    const res = await send('Runtime.evaluate', { expression: DUMP_JS, returnByValue: true });
    const data = JSON.parse(res.result.value);
    try {
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(OUT_SHOT, Buffer.from(shot.data, 'base64'));
      console.log(`screenshot -> ${OUT_SHOT}`);
    } catch (e) {
      console.error('screenshot failed:', e.message);
    }
    return data;
  } finally {
    try { ws && ws.close(); } catch {}
    edge.kill();
    await sleep(500);
    try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}
  }
})();

fs.writeFileSync(OUT_JSON, JSON.stringify(json, null, 1));
const digestText =
  `json -> ${OUT_JSON}  (${json.els.length} visible elements, viewport ${json.vw}x${json.vh})\n` +
  `\n===== DIGEST (main page) =====\n${digest(json.els)}\n` +
  `\n===== ASCII MAP (8px/cell) =====\n${asciiMap(json.els, json.vw, json.vh)}\n`;
const digestFile = OUT_JSON.replace(/\.json$/, '.digest.txt');
fs.writeFileSync(digestFile, digestText);
console.log(`digest -> ${digestFile}`);


