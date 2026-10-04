// Theme probe for the Atlas Grafana theme (stacks/monitoring/grafana/plugins/atlas-theme-app).
// Slow (a browser renders the dashboard three times): run it only when pjan asks, for example
// after a Grafana upgrade or a change to the theme files. Never from validate.sh or CI.
// Run it through scripts/theme-probe.sh, which provides Playwright; see README.md, Monitoring.
//
// It opens a dashboard in Atlas Light, in Atlas Dark, and in Light switched live to Dark, and
// reports per element the colours the browser renders, as palette keys (for example emerald300),
// with APCA Lc for text. It also checks Grafana's colour picker on a temporary dashboard (created
// and deleted through the API): it must list Grafana's six hues and then the theme's extra names,
// and the last hue row must stay inside the picker when scrolled to. It ends with FAIL lines for
// what the theme no longer reaches.
//
// Environment: GRAFANA_URL (required), GRAFANA_USER and GRAFANA_PASSWORD (required),
// DASHBOARD (default /d/atlas-containers?from=now-24h&to=now).
import { chromium } from 'playwright';

const URL = (process.env.GRAFANA_URL || '').replace(/\/$/, '');
const USER = process.env.GRAFANA_USER;
const PASSWORD = process.env.GRAFANA_PASSWORD;
const DASHBOARD = process.env.DASHBOARD || '/d/atlas-containers?from=now-24h&to=now';
if (!URL || !USER || !PASSWORD) {
  console.error('theme-probe: set GRAFANA_URL, GRAFANA_USER, and GRAFANA_PASSWORD');
  process.exit(2);
}

// ---- Colour helpers (APCA 0.0.98G, as in CONVENTIONS.md)
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const Y = ([r, g, b]) => 0.2126729 * lin(r / 255) + 0.7151522 * lin(g / 255) + 0.072175 * lin(b / 255);
function lc(text, bg) {
  let t = Y(text), b = Y(bg);
  const clamp = (y) => (y > 0.022 ? y : y + (0.022 - y) ** 1.414);
  t = clamp(t); b = clamp(b);
  const s = b > t ? (b ** 0.56 - t ** 0.57) * 1.14 : (b ** 0.65 - t ** 0.62) * 1.14;
  return Math.abs(s) < 0.1 ? 0 : Math.round(Math.abs(s > 0 ? s - 0.027 : s + 0.027) * 100);
}
function parse(css) {
  const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/.exec(css || '');
  if (m) return { rgb: [+m[1], +m[2], +m[3]], a: m[4] === undefined ? 1 : +m[4] };
  const h = /^#([0-9a-f]{6})/i.exec(css || '');
  return h ? { rgb: [0, 2, 4].map((i) => parseInt(h[1].substr(i, 2), 16)), a: 1 } : null;
}
let PALETTE = {};
function name(css) {
  const c = parse(css);
  if (!c) return css || '-';
  if (c.a === 0) return 'transparent';
  const hex = '#' + c.rgb.map((n) => n.toString(16).padStart(2, '0')).join('');
  const key = Object.keys(PALETTE).find((k) => PALETTE[k].toLowerCase() === hex);
  return (key || hex) + (c.a < 1 ? `/${+c.a.toFixed(2)}` : '');
}

// ---- What the page reports (runs in the browser)
function collect() {
  const cs = (el) => getComputedStyle(el);
  const pick = (sel, max = 12) => [...document.querySelectorAll(sel)].slice(0, max);
  const panelOf = (el) => el.closest('[data-viz-panel-key]')?.querySelector('h2')?.textContent?.trim() || '?';
  const out = { pageBg: cs(document.body).backgroundColor, rows: [] };
  const row = (kind, el, bgEl = el) => out.rows.push({ kind, panel: panelOf(el), text: (el.textContent || '').trim().slice(0, 18),
    bg: cs(bgEl).backgroundColor, fg: cs(el).color, weight: cs(el).fontWeight, ring: cs(el).boxShadow, radius: cs(bgEl).borderRadius });
  pick('[data-testid^="stat-panel-"] [style*="display: flex; background"]').forEach((el) => row('stat tile', el.querySelector('span') || el, el));
  pick('[data-testid^="table-panel-"] [role="gridcell"][style*="background: rgb"]').forEach((el) => row('state cell', el));
  pick('[data-testid^="table-panel-"] [role="gridcell"] span[style*="background-color"]', 40).forEach((el) => row('pill', el));
  pick('[data-testid^="table-panel-"] [role="gridcell"][style*="color: rgb"]:not([style*="background"])').forEach((el) => row('coloured text', el));
  pick('div[style*="2px solid"]').forEach((el) => row('bar gauge bar', el));
  // Toolbar buttons and the selector's value box (the part right of the gray label) must match.
  const btn = document.querySelector('[data-testid="data-testid dashboard controls"] button[class*="toolbar-button"]');
  const sel = document.querySelector('[data-testid="data-testid template variable"] > div');
  const box = (el) => el && { border: cs(el).borderTopColor, bg: cs(el).backgroundColor, height: Math.round(el.getBoundingClientRect().height) };
  out.controls = { button: box(btn), selector: box(sel) };
  out.canvas = window.__probeCanvas;
  return out;
}

// Records every colour set on a canvas, per panel type: installed before Grafana and the plugin
// load, so it sees every colour drawn.
function recordCanvas() {
  const log = (window.__probeCanvas = {});
  const proto = CanvasRenderingContext2D.prototype;
  for (const prop of ['strokeStyle', 'fillStyle']) {
    const d = Object.getOwnPropertyDescriptor(proto, prop);
    Object.defineProperty(proto, prop, { configurable: true, get() { return d.get.call(this); }, set(v) {
      if (typeof v === 'string') {
        const type = this.canvas.closest?.('[data-plugin-id]')?.getAttribute('data-plugin-id') || '?';
        const k = type + ' ' + prop;
        (log[k] ||= {})[v] = ((log[k] || {})[v] || 0) + 1;
      }
      d.set.call(this, v);
    } });
  }
}

const b = await chromium.launch();
const fails = [];
async function page(theme) {
  const ctx = await b.newContext({ viewport: { width: 1600, height: 4400 } });
  const p = await ctx.newPage();
  await p.addInitScript(recordCanvas);
  await p.goto(URL + '/login');
  await p.fill('input[name="user"]', USER);
  await p.fill('input[name="password"]', PASSWORD);
  await p.click('button[type="submit"]');
  await p.waitForURL((u) => !u.pathname.startsWith('/login'));
  await p.goto(URL + DASHBOARD + (DASHBOARD.includes('?') ? '&' : '?') + 'theme=' + theme);
  await p.waitForTimeout(10000);
  return p;
}
function report(label, r, expect) {
  // The page background is a palette colour only with an Atlas theme active; its lightness
  // tells the mode.
  const page = parse(r.pageBg);
  const mode = page && Y(page.rgb) > 0.5 ? 'light' : 'dark';
  console.log(`\n== ${label}: ${mode}, page ${name(r.pageBg)}`);
  if (!name(r.pageBg).match(/^[a-z]+\d*$/)) fails.push(`${label}: the page background ${name(r.pageBg)} is not a palette colour: no Atlas theme`);
  if (mode !== expect) fails.push(`${label}: the page is ${mode}, expected ${expect}`);
  const seen = new Set();
  for (const x of r.rows) {
    const k = [x.kind, x.bg, x.fg, x.ring].join('|');
    if (seen.has(k)) continue;
    seen.add(k);
    const f = parse(x.fg), g = parse(x.bg);
    const contrast = f && g && g.a > 0 ? `Lc ${lc(f.rgb, g.rgb)}` : '';
    const ring = /rgb/.test(x.ring || '') ? ` ring ${name(x.ring.match(/rgba?\([^)]*\)/)[0])}` : '';
    console.log(`  ${x.kind.padEnd(14)} ${x.panel.slice(0, 18).padEnd(18)} ${x.text.padEnd(18)} bg ${name(x.bg).padEnd(12)} text ${name(x.fg).padEnd(12)} ${contrast.padEnd(7)} w${x.weight}${ring}`);
    // A bar at 35 % white or black comes from a transparent step: no role colour, not restyled.
    const transparentStep = x.kind === 'bar gauge bar' && /^(white|#000000)\/0\.35$/.test(name(x.bg));
    if (g && g.a > 0 && !name(x.bg).match(/^[a-z]+\d+/) && x.kind !== 'coloured text' && !transparentStep) fails.push(`${label}: ${x.kind} "${x.text}" has a background outside the palette (${name(x.bg)})`);
  }
  const c = r.controls;
  if (c.button && c.selector) {
    console.log(`  controls       button   border ${name(c.button.border)} bg ${name(c.button.bg)} ${c.button.height}px`);
    console.log(`                 selector border ${name(c.selector.border)} bg ${name(c.selector.bg)} ${c.selector.height}px`);
    for (const k of ['border', 'bg', 'height']) if (c.button[k] !== c.selector[k]) fails.push(`${label}: toolbar button ${k} ${c.button[k]} differs from the selector (${c.selector[k]})`);
  }
  for (const [k, colours] of Object.entries(r.canvas || {}).sort()) {
    console.log(`  canvas ${k.padEnd(24)} ${Object.keys(colours).map(name).filter((v, i, a) => a.indexOf(v) === i).join(', ')}`);
  }
}

// Everything a report shows, for comparing a live switch with a fresh load.
function colours(r) {
  const out = new Set();
  for (const x of r.rows) out.add(`${x.kind} bg ${name(x.bg)} text ${name(x.fg)}`);
  for (const [k, cs] of Object.entries(r.canvas || {})) for (const c of Object.keys(cs)) out.add(`canvas ${k} ${name(c)}`);
  return out;
}
const clearCanvas = () => { for (const k of Object.keys(window.__probeCanvas)) delete window.__probeCanvas[k]; };

const light = await page('light');
PALETTE = await light.evaluate(async (u) => (await (await fetch(u)).json()).palette, URL + '/public/plugins/atlas-theme-app/atlas-theme.json?_cache=probe');
report('Atlas Light', await light.evaluate(collect), 'light');
const dark = await page('dark');
const darkReport = await dark.evaluate(collect);
report('Atlas Dark', darkReport, 'dark');
// Live switch: Grafana's "c t" shortcut changes the theme without a page load (and saves it
// as the user's preference, which the probe restores). After the switch settles, a resize
// redraws every canvas without new data, so what is drawn then is what the plugin's own
// re-processing left; it must match a fresh load.
const prefs = URL + '/api/user/preferences';
const before = await light.evaluate(async (u) => (await (await fetch(u)).json()).theme, prefs);
try {
  await light.keyboard.press('c');
  await light.keyboard.press('t');
  await light.waitForTimeout(8000);
  await light.evaluate(clearCanvas);
  await light.setViewportSize({ width: 1580, height: 4400 });
  await light.waitForTimeout(4000);
  const switched = await light.evaluate(collect);
  report('Light switched to Dark', switched, 'dark');
  const fresh = colours(darkReport);
  for (const c of colours(switched)) if (!fresh.has(c)) fails.push(`Light switched to Dark: ${c} (not in a fresh Atlas Dark load: stale after the switch)`);
} finally {
  await light.evaluate(async ([u, theme]) => fetch(u, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme }) }), [prefs, before || '']);
}

// ---- Colour picker: the extra names as hue rows (module.js build()), and the rows scrolling
// inside the picker (module.js styleColorPicker()).
const GRAFANA_HUES = ['red', 'orange', 'yellow', 'green', 'blue', 'purple'];
const SHADE_PREFIXES = ['super-light-', 'light-', '', 'semi-dark-', 'dark-'];
async function checkPicker(p) {
  const file = await p.evaluate(async (u) => (await fetch(u)).json(), URL + '/public/plugins/atlas-theme-app/atlas-theme.json?_cache=probe');
  const names = file.names.light;
  const extra = [];
  for (const n of Object.keys(names)) {
    const hue = n.replace(/^(super-light-|light-|semi-dark-|dark-)/, '');
    if (!extra.includes(hue) && SHADE_PREFIXES.every((prefix) => prefix + hue in names)) extra.push(hue);
  }
  const expected = [...GRAFANA_HUES, ...extra];
  const api = URL + '/api/dashboards';
  const uid = 'atlas-theme-probe-picker';
  const created = await p.evaluate(async ([u, dashboard]) => (await fetch(u + '/db', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ overwrite: true, dashboard }) })).status, [api, { uid, title: 'Atlas theme probe: colour picker', schemaVersion: 42,
    panels: [{ id: 1, type: 'stat', title: 'picker', gridPos: { x: 0, y: 0, w: 12, h: 8 } }] }]);
  if (created !== 200) { fails.push(`colour picker: could not create the temporary dashboard (HTTP ${created})`); return; }
  try {
    await p.goto(URL + '/d/' + uid + '?editPanel=1&theme=light');
    await p.waitForTimeout(8000);
    await p.getByRole('button', { name: 'green color', exact: true }).click();
    await p.waitForTimeout(1000);
    // Each hue row has a dark-<hue> swatch, labelled "<shade name> color"
    const rows = await p.locator('button[aria-label^="dark-"]').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label').replace(/^dark-| color$/g, '')));
    console.log(`\n== Colour picker: ${rows.join(', ')}`);
    if (rows.join() !== expected.join()) fails.push(`colour picker: hue rows ${rows.join(', ')}; expected ${expected.join(', ')}`);
    // The palette is a fixed-height box; scrolled to, the last row must still be inside it
    const last = p.getByRole('button', { name: `${expected[expected.length - 1]} color`, exact: true });
    await last.scrollIntoViewIfNeeded();
    await p.waitForTimeout(300);
    const inside = await last.evaluate((el) => {
      const box = el.closest('div:has(> div > div > div > div > button[aria-label*="super-light-"])');
      if (!box) return 'no palette box found';
      const r = el.getBoundingClientRect(), bb = box.getBoundingClientRect();
      return r.top >= bb.top - 1 && r.bottom <= bb.bottom + 1 ? 'inside' : `outside (row ${Math.round(r.top)}-${Math.round(r.bottom)}, box ${Math.round(bb.top)}-${Math.round(bb.bottom)})`;
    });
    console.log(`  last row (${expected[expected.length - 1]}) scrolled to: ${inside}`);
    if (inside !== 'inside') fails.push(`colour picker: the last hue row scrolled to is ${inside}: the rows spill out of the picker`);
  } finally {
    await p.evaluate(async (u) => fetch(u, { method: 'DELETE' }), api + '/uid/' + uid);
  }
}
await checkPicker(dark);
await b.close();

console.log(fails.length ? '\n' + fails.map((f) => 'FAIL ' + f).join('\n') : '\ntheme-probe: no failures');
process.exit(fails.length ? 1 : 0);
