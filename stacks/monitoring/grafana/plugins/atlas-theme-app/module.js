/*
 * Atlas theme engine: a preload app plugin, hand-written AMD without a build step.
 * It has no colours of its own; it applies two files from this directory (see README.md):
 *   atlas-theme.json  Grafana theme definitions ("Atlas Light", "Atlas Dark") in Grafana's
 *                     theme-definition format, plus colour names Grafana has no slot for;
 *   atlas.css         a plain stylesheet, including the canvas variables (--atlas-grid, ...).
 * The rules they implement are pjan/atlas-dashboards CONVENTIONS.md.
 *
 * 1. Theme: builds the theme with createTheme() and publishes it as the active theme on
 *    load, on every theme change, and again after 200 ms, 1 s, and 3 s (Grafana may still
 *    publish its own theme while starting). The built theme also resolves the extra colour
 *    names (gray, teal, ...).
 * 2. Stylesheet: atlas.css as one <style> element (DevTools names it atlas.css), after one with
 *    the palette as variables (--atlas-gray-100, ...), from atlas-theme.json. The plugin keeps
 *    html[data-atlas-theme] set to light or dark.
 * 3. Canvas: CSS cannot reach what charts draw on a canvas, so the plugin reads the canvas
 *    variables that apply to each canvas element (any selector can set them) and uses them
 *    instead of the colours Grafana draws: grid, axis text, state-timeline outline and text,
 *    and the sparkline on a coloured stat tile. An unset variable keeps Grafana's colour.
 * 4. Theme switch: whenever an Atlas theme replaces a stock one (on load, on a switch, after an
 *    edit), resets Grafana's cached continuous colour schemes and makes every panel of the open
 *    dashboard process its field config again; otherwise both keep the previous colours.
 * 5. Live editor: ?atlasEditor=1 opens a drawer to edit both files in the browser; edits apply
 *    at once and stay in this browser's localStorage until "Reset to files".
 *
 * All of it uses undocumented Grafana behaviour: publishing ThemeChangedEvent with a
 * replacement theme, the colours uPlot and the stat sparkline are given (Grafana 13.2.3),
 * FieldColorSchemeMode's cache fields, and the dashboard scene's panels
 * (window.__grafanaSceneContext, clearFieldConfigCache). After a Grafana upgrade, run
 * scripts/theme-probe.sh (README.md, Monitoring).
 * Without the plugin (it does not load for viewers without an org role, such as public
 * dashboards) the dashboards work with Grafana's stock colours, except the extra names:
 * super-light-gray timeline segments render black, gray ones in Grafana's CSS gray.
 *
 * Bump info.version in plugin.json with every change to this directory: Grafana loads this
 * file as module.js?_cache=<version>, and this file loads the other files with the same key.
 */
define(['@grafana/data', '@grafana/runtime'], function (data, runtime) {
  var ID = 'atlas-theme-app';
  var VERSION = ((runtime.config.apps || {})[ID] || {}).version || '0';
  var BASE = (runtime.config.appSubUrl || '') + '/public/plugins/' + ID + '/';
  // Grafana's continuous schemes built from colour names (fieldColor.ts); the d3 schemes
  // (viridis, magma, ...) have fixed colours and are left alone.
  var NAMED_SCHEMES = ['continuous-GrYlRd', 'continuous-RdYlGr', 'continuous-BlYlRd', 'continuous-YlRd',
    'continuous-BlPu', 'continuous-YlBl', 'continuous-blues', 'continuous-reds', 'continuous-greens',
    'continuous-purples'];
  var MODES = ['light', 'dark'];
  // Atlas role -> the Grafana colour name dashboards use for it (CONVENTIONS.md section 4).
  var ROLES = { ok: 'green', warning: 'yellow', critical: 'red', progress: 'blue', pending: 'purple', unknown: 'gray' };
  var SHADES = ['super-light-', 'light-', '', 'semi-dark-', 'dark-'];
  // The grid colour uPlot panels hard-code (UPlotAxisBuilder.ts), per mode.
  var GRID = { light: 'rgba(0, 10, 23, 0.09)', dark: 'rgba(240, 250, 255, 0.09)' };
  // The canvas variables, without the --atlas- prefix (README.md, Canvas variables).
  var CANVAS_VARS = ['grid', 'axis-text'];
  Object.keys(ROLES).forEach(function (role) {
    ['outline', 'text', 'sparkline', 'sparkline-fill'].forEach(function (part) { CANVAS_VARS.push(role + '-' + part); });
  });

  var THEME = null;
  var CSS = '';
  var MODE = 'dark';
  // True until an Atlas theme is active, and again whenever Grafana puts a stock theme in
  // place: panels processed meanwhile hold stock colours.
  var stale = true;
  // Bumped whenever the stylesheet or the mode changes: cached canvas variables expire.
  var generation = 0;

  // ---- References in atlas-theme.json: atlas.<key> is a palette colour, atlas.<key>/<alpha>
  // the same with alpha.
  var reported = {};
  function ref(value) {
    return value.replace(/atlas\.([a-z]+[0-9]*)(?:\/([0-9.]+))?/g, function (match, key, alpha) {
      var hex = own(THEME.palette, key);
      if (!hex) {
        if (!own(reported, key)) { reported[key] = true; console.error('atlas-theme: unknown palette key ' + key); }
        return match;
      }
      if (alpha === undefined) { return hex; }
      return 'rgba(' + channels(hex).join(', ') + ', ' + alpha + ')';
    });
  }
  function resolve(node) {
    if (typeof node === 'string') { return ref(node); }
    if (Array.isArray(node)) { return node.map(resolve); }
    if (node && typeof node === 'object') {
      var out = {};
      Object.keys(node).forEach(function (k) { if (k[0] !== '$') { out[k] = resolve(node[k]); } });
      return out;
    }
    return node;
  }
  function channels(hex) { return [1, 3, 5].map(function (i) { return parseInt(hex.substr(i, 2), 16); }); }
  function hex6(color) {
    if (typeof color !== 'string') { return null; }
    if (color[0] === '#') { return color.slice(0, 7).toLowerCase(); }
    var m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color);
    return m ? '#' + [m[1], m[2], m[3]].map(function (n) { return ('0' + (+n).toString(16)).slice(-2); }).join('') : null;
  }
  function modeOf(theme) { return theme && theme.colors && theme.colors.mode === 'light' ? 'light' : 'dark'; }
  // Lookups in maps keyed by colours or names, without inherited keys such as "constructor".
  function own(map, key) { return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined; }
  // palette key -> CSS variable: gray100 -> --atlas-gray-100, ink -> --atlas-ink.
  function paletteVar(key) { return '--atlas-' + key.replace(/^([a-z]+)([0-9]+)$/, '$1-$2'); }

  // ---- Roles: the colour each role name resolves to, in every shade and both modes. A colour
  // from the other mode that is a series colour in this one (orange 400 and 600) is left out.
  var ROLE_BY_COLOR = { light: {}, dark: {} };
  function roleColors() {
    MODES.forEach(function (mode) {
      var series = {};
      resolve(THEME.themes[mode].visualization.palette).forEach(function (c) { series[c.toLowerCase()] = true; });
      var map = {};
      MODES.forEach(function (m) {
        var colors = {};
        resolve(THEME.themes[m]).visualization.hues.forEach(function (hue) {
          hue.shades.forEach(function (s) { colors[s.name] = s.color; });
        });
        Object.assign(colors, resolve(THEME.names[m]));
        Object.keys(ROLES).forEach(function (role) {
          SHADES.forEach(function (shade) {
            var c = own(colors, shade + ROLES[role]);
            if (c && !(m !== mode && own(series, c.toLowerCase()))) { map[c.toLowerCase()] = role; }
          });
        });
      });
      ROLE_BY_COLOR[mode] = map;
    });
  }

  // ---- Canvas variables: read per element, so selectors and inheritance work as in CSS.
  var resolver = null;
  var resolved = {};
  // Any CSS colour (var() already substituted), as the browser computes it: rgb() or rgba().
  function color(value) {
    value = (value || '').trim();
    if (!value) { return null; }
    if (own(resolved, value) !== undefined) { return resolved[value]; }
    if (!resolver) {
      resolver = document.createElement('span');
      resolver.style.display = 'none';
      document.body.appendChild(resolver);
    }
    resolver.style.color = '';
    resolver.style.color = value;
    var out = resolver.style.color ? getComputedStyle(resolver).color : null;
    // color-mix() and relative colours compute to color(srgb r g b / a); canvases take rgba().
    var m = out && /^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)$/.exec(out);
    if (m) {
      out = 'rgba(' + [m[1], m[2], m[3]].map(function (x) { return Math.round(x * 255); }).join(', ') + ', ' + (m[4] === undefined ? 1 : +m[4]) + ')';
    }
    resolved[value] = out;
    return out;
  }
  var VARS = new WeakMap();
  function varsOf(el) {
    var c = VARS.get(el);
    if (c && c.generation === generation) { return c.values; }
    var style = getComputedStyle(el);
    var values = {};
    CANVAS_VARS.forEach(function (name) { values[name] = color(style.getPropertyValue('--atlas-' + name)); });
    if (el.isConnected) { VARS.set(el, { generation: generation, values: values }); }
    return values;
  }
  // The page-level value of each role's text colour -> role: getContrastText returns those,
  // and a canvas with its own value gets it swapped in when the colour is set.
  function textRoles() {
    var page = varsOf(document.documentElement);
    var out = {};
    Object.keys(ROLES).forEach(function (role) { if (page[role + '-text']) { out[page[role + '-text']] = role; } });
    return out;
  }
  var textRoleCache = { generation: -1, map: {} };

  // ---- 1. Theme
  function build(base) {
    var mode = modeOf(base);
    var theme = data.createTheme(resolve(THEME.themes[mode]));
    theme.flags = Object.assign({}, base.flags);
    theme.atlas = true;
    var names = resolve(THEME.names[mode]);
    var byName = theme.visualization.getColorByName;
    theme.visualization.getColorByName = function (name) { return (name && own(names, name)) || byName(name); };
    // State timelines ask getContrastText for the text on each segment.
    var contrastText = theme.colors.getContrastText;
    theme.colors.getContrastText = function (background, threshold) {
      var role = own(ROLE_BY_COLOR[mode], hex6(background));
      var text = role && varsOf(document.documentElement)[role + '-text'];
      return text || contrastText(background, threshold);
    };
    return theme;
  }
  function publish(base) {
    runtime.getAppEvents().publish(new runtime.ThemeChangedEvent(build(base)));
  }
  function apply() {
    var current = runtime.config.theme2;
    if (current && !current.atlas) { stale = true; publish(current); } else { restyle(current); }
  }
  function resetSchemes() {
    NAMED_SCHEMES.forEach(function (id) {
      var scheme = data.fieldColorModeRegistry.getIfExists(id);
      if (scheme) { scheme.interpolator = undefined; scheme.colorCache = undefined; scheme.colorCacheTheme = undefined; }
    });
  }
  // Panels keep the colours they resolved with the previous theme: each panel caches its
  // processed field config, and state timelines keep their chart until that changes. Clearing
  // the cache, as Grafana does when a variable changes, re-processes every panel of the open
  // dashboard (window.__grafanaSceneContext is the active dashboard scene) with the new theme.
  // Annotation colours are resolved when the annotation queries return, so the dashboard is
  // also refreshed once.
  function reprocessPanels() {
    var scene = window.__grafanaSceneContext;
    (function visit(obj) {
      if (!obj) { return; }
      if (typeof obj.clearFieldConfigCache === 'function' && typeof obj.forceRender === 'function') {
        obj.clearFieldConfigCache();
        obj.forceRender();
      }
      if (typeof obj.forEachChild === 'function') { obj.forEachChild(visit); }
    })(scene);
    var range = scene && scene.state && scene.state.$timeRange;
    if (range && typeof range.onRefresh === 'function') { range.onRefresh(); }
  }

  // ---- 2. Stylesheets
  var paletteStyle = document.createElement('style');
  paletteStyle.id = 'atlas-theme-palette';
  var cssStyle = document.createElement('style');
  cssStyle.id = 'atlas-theme-css';
  function writeStyles() {
    paletteStyle.textContent = ':root {\n' + Object.keys(THEME.palette).map(function (key) {
      return '  ' + paletteVar(key) + ': ' + THEME.palette[key] + ';';
    }).join('\n') + '\n}\n/*# sourceURL=atlas-palette.css */';
    cssStyle.textContent = CSS + '\n/*# sourceURL=atlas.css */';
  }
  function restyle(theme) {
    if (!theme || !theme.colors) { return; }
    var mode = modeOf(theme);
    if (mode !== MODE) { generation++; }
    MODE = mode;
    document.documentElement.setAttribute('data-atlas-theme', MODE);
    if (!theme.atlas) { stale = true; return; }
    if (stale) {
      stale = false;
      generation++;
      resetSchemes();
      setTimeout(reprocessPanels, 0);
    }
    paint(theme);
  }

  // ---- 3. Canvas
  var SCOPE = new WeakMap();
  function scopeOf(canvas) {
    var s = SCOPE.get(canvas);
    if (s !== undefined) { return s; }
    if (!canvas || !canvas.closest) { return null; }
    var panel = canvas.closest('[data-plugin-id]');
    var type = panel ? panel.getAttribute('data-plugin-id') : '';
    s = { axes: !!canvas.closest('.uplot'), timeline: type === 'state-timeline' || type === 'status-history', stat: type === 'stat' };
    if (canvas.isConnected) { SCOPE.set(canvas, s); }
    return s;
  }
  // The role of the coloured stat tile a sparkline canvas sits on, from the tile's inline fill.
  function tileRole(canvas) {
    var tile = canvas.parentElement && canvas.parentElement.closest('div[style*="background"]');
    var role = tile && own(ROLE_BY_COLOR[MODE], hex6(tile.style.backgroundColor || tile.style.background));
    return role || null;
  }
  function canvasColor(ctx, prop, v) {
    var canvas = ctx.canvas;
    var s = scopeOf(canvas);
    if (!s || !(s.axes || s.stat)) { return v; }
    var vars, role;
    if (s.axes) {
      if (v === GRID[MODE]) { return varsOf(canvas).grid || v; }
      if (v === THEME.axisText[MODE]) { return varsOf(canvas)['axis-text'] || v; }
    }
    if (s.timeline) {
      if (prop === 'strokeStyle' && v[0] === '#') {
        role = own(ROLE_BY_COLOR[MODE], v.slice(0, 7).toLowerCase());
        if (role) { return varsOf(canvas)[role + '-outline'] || v; }
      }
      if (prop === 'fillStyle') {
        if (textRoleCache.generation !== generation) { textRoleCache = { generation: generation, map: textRoles() }; }
        role = own(textRoleCache.map, v);
        if (role) { return varsOf(canvas)[role + '-text'] || v; }
      }
    }
    if (s.stat) {
      role = tileRole(canvas);
      if (role) {
        vars = varsOf(canvas);
        return (prop === 'strokeStyle' ? vars[role + '-sparkline'] : vars[role + '-sparkline-fill']) || v;
      }
    }
    return v;
  }
  function wrapCanvas() {
    var proto = CanvasRenderingContext2D.prototype;
    ['strokeStyle', 'fillStyle'].forEach(function (prop) {
      var d = Object.getOwnPropertyDescriptor(proto, prop);
      Object.defineProperty(proto, prop, {
        configurable: true, enumerable: d.enumerable, get: d.get,
        set: function (v) { d.set.call(this, typeof v === 'string' ? canvasColor(this, prop, v) : v); }
      });
    });
  }

  // ---- Start
  // Applies a theme and a stylesheet: the files, or the live editor's local override.
  function load(theme, css) {
    THEME = theme;
    CSS = css;
    // The colour Grafana draws axis text in: the theme's text colour, per mode.
    THEME.axisText = { light: ref(THEME.themes.light.colors.text.primary), dark: ref(THEME.themes.dark.colors.text.primary) };
    roleColors();
    writeStyles();
    generation++;
  }
  function activate(theme, css) {
    load(theme, css);
    stale = true;
    publish(runtime.config.theme2);
  }
  function start(theme, css) {
    load(theme, css);
    wrapCanvas();
    document.head.appendChild(paletteStyle);
    document.head.appendChild(cssStyle);
    runtime.getAppEvents().subscribe(runtime.ThemeChangedEvent, function (event) {
      restyle(event.payload);
      if (event.payload && !event.payload.atlas) { setTimeout(function () { publish(event.payload); }, 0); }
    });
    apply();
    [200, 1000, 3000].forEach(function (ms) { setTimeout(apply, ms); });
    // With the "system" theme preference, Grafana follows the OS light/dark switch by putting a
    // stock theme in place without a ThemeChangedEvent.
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
      [100, 1000].forEach(function (ms) { setTimeout(apply, ms); });
    });
  }

  // ---- 5. Live editor: ?atlasEditor=1 on any page opens a drawer with both files. Edits apply
  // at once and are kept in this browser's localStorage (a local override) until "Reset to
  // files"; "Copy both" copies them for the repository. Other browsers and users keep seeing
  // the files.
  var OVERRIDE_KEY = 'atlas-theme-override';
  var FILES = { theme: '', css: '' };
  function readOverride() {
    try {
      var o = JSON.parse(window.localStorage.getItem(OVERRIDE_KEY) || 'null');
      return o && typeof o.theme === 'string' && typeof o.css === 'string' ? o : null;
    } catch (e) { return null; }
  }
  function parseTheme(text) {
    var theme = JSON.parse(text);
    if (!theme.palette || !theme.themes || !theme.names) { throw new Error('atlas-theme.json needs palette, themes, and names'); }
    return theme;
  }
  // Palette keys atlas-theme.json refers to that do not exist, and --atlas- variables atlas.css
  // uses that neither the palette nor the stylesheet defines.
  function problems(themeText, css, palette) {
    var out = [];
    themeText.replace(/atlas\.([a-z]+[0-9]*)/g, function (m, key) {
      if (!own(palette, key) && out.indexOf('atlas.' + key) < 0) { out.push('atlas.' + key); }
      return m;
    });
    var defined = {};
    Object.keys(palette).forEach(function (key) { defined[paletteVar(key)] = true; });
    css.replace(/(--atlas-[a-z0-9-]+)\s*:/g, function (m, name) { defined[name] = true; return m; });
    css.replace(/var\(\s*(--atlas-[a-z0-9-]+)/g, function (m, name) {
      if (!own(defined, name) && out.indexOf(name) < 0) { out.push(name); }
      return m;
    });
    return out;
  }
  var editor = null;
  var badge = null;
  function updateBadge() {
    var o = readOverride();
    if (!o) { if (badge) { badge.remove(); badge = null; } return; }
    if (!badge) {
      badge = document.createElement('button');
      badge.type = 'button';
      badge.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:1400;padding:4px 10px;border-radius:6px;' +
        'font:500 12px/20px sans-serif;cursor:pointer;border:1px solid;';
      badge.addEventListener('click', openEditor);
      document.body.appendChild(badge);
    }
    badge.textContent = 'Atlas theme: local override' + (o.version !== VERSION ? ' (files are now ' + VERSION + ')' : '');
    paint();
  }
  // The drawer and badge take their colours from the active theme.
  function paint(theme) {
    var t = theme || runtime.config.theme2;
    if (!t || !t.colors) { return; }
    [editor, badge].forEach(function (el) {
      if (!el) { return; }
      el.style.background = t.colors.background.primary;
      el.style.color = t.colors.text.primary;
      el.style.borderColor = t.colors.border.medium;
    });
  }
  function openEditor() {
    if (editor) { return; }
    var o = readOverride();
    var texts = { theme: o ? o.theme : FILES.theme, css: o ? o.css : FILES.css };
    var tab = 'css';
    var timer = null;
    editor = document.createElement('div');
    editor.id = 'atlas-theme-editor';
    editor.style.cssText = 'position:fixed;top:0;right:0;bottom:0;width:560px;z-index:1400;display:flex;' +
      'flex-direction:column;border-left:1px solid;box-shadow:0 0 24px rgba(0,0,0,.25);font:13px/1.4 sans-serif';
    editor.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;padding:10px 12px">' +
      '<strong style="flex:1">Atlas theme editor</strong>' +
      '<button data-a="reset">Reset to files</button><button data-a="copy">Copy both</button>' +
      '<button data-a="close" aria-label="Close">✕</button></div>' +
      '<div style="display:flex;gap:4px;padding:0 12px"><button data-tab="css">atlas.css</button>' +
      '<button data-tab="theme">atlas-theme.json</button></div>' +
      '<div data-el="palette" style="display:grid;grid-template-columns:repeat(9,1fr);gap:2px;padding:8px 12px"></div>' +
      '<div data-el="status" style="padding:0 12px 6px;min-height:18px"></div>' +
      '<textarea data-el="text" spellcheck="false" style="flex:1;margin:0 12px 12px;padding:8px;resize:none;' +
      'font:12px/1.45 ui-monospace,Menlo,monospace;background:transparent;color:inherit;border:1px solid;' +
      'border-color:inherit;border-radius:4px;tab-size:2;white-space:pre"></textarea>';
    document.body.appendChild(editor);
    editor.querySelectorAll('button').forEach(function (b) {
      b.style.cssText = 'padding:3px 8px;border-radius:4px;border:1px solid;border-color:inherit;background:transparent;' +
        'color:inherit;font:inherit;cursor:pointer';
    });
    var area = editor.querySelector('[data-el="text"]');
    var status = editor.querySelector('[data-el="status"]');
    // Swatches insert var(--atlas-<key>) in atlas.css and atlas.<key> in atlas-theme.json.
    function palette() {
      var box = editor.querySelector('[data-el="palette"]');
      box.innerHTML = '';
      Object.keys(THEME.palette).filter(function (k) { return /[0-9]00$/.test(k); }).forEach(function (key) {
        var sw = document.createElement('button');
        sw.type = 'button';
        sw.title = paletteVar(key) + ' / atlas.' + key + ' ' + THEME.palette[key] + ' (click inserts it)';
        sw.style.cssText = 'height:16px;border:0;border-radius:2px;padding:0;cursor:pointer;background:' + THEME.palette[key];
        sw.addEventListener('click', function () {
          var a = area.selectionStart, b = area.selectionEnd;
          var ins = tab === 'css' ? 'var(' + paletteVar(key) + ')' : 'atlas.' + key;
          area.value = area.value.slice(0, a) + ins + area.value.slice(b);
          area.selectionStart = area.selectionEnd = a + ins.length;
          area.focus();
          changed();
        });
        box.appendChild(sw);
      });
    }
    function show(t) {
      tab = t;
      area.value = texts[t];
      editor.querySelectorAll('[data-tab]').forEach(function (b) { b.style.fontWeight = b.getAttribute('data-tab') === t ? '700' : '400'; });
    }
    function say(text, bad) { status.textContent = text; status.style.color = bad ? '#ea5a53' : ''; }
    function changed() {
      texts[tab] = area.value;
      clearTimeout(timer);
      timer = setTimeout(function () {
        var theme;
        try { theme = parseTheme(texts.theme); } catch (e) { say('atlas-theme.json: ' + ((e && e.message) || e), true); return; }
        var found = problems(texts.theme, texts.css, theme.palette);
        window.localStorage.setItem(OVERRIDE_KEY, JSON.stringify({ version: VERSION, theme: texts.theme, css: texts.css }));
        activate(theme, texts.css);
        palette();
        updateBadge();
        say(found.length ? 'Applied; undefined: ' + found.join(', ') : 'Applied (local override in this browser)', found.length > 0);
      }, 300);
    }
    area.addEventListener('input', changed);
    // Keep Grafana's keyboard shortcuts out of the editor; Tab indents.
    area.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Tab') {
        e.preventDefault();
        var a = area.selectionStart;
        area.value = area.value.slice(0, a) + '  ' + area.value.slice(area.selectionEnd);
        area.selectionStart = area.selectionEnd = a + 2;
        changed();
      }
    });
    editor.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) { return; }
      if (b.getAttribute('data-tab')) { texts[tab] = area.value; show(b.getAttribute('data-tab')); return; }
      var a = b.getAttribute('data-a');
      if (a === 'close') { editor.remove(); editor = null; return; }
      if (a === 'copy') {
        navigator.clipboard.writeText('/* atlas.css */\n' + texts.css.trim() + '\n\n// atlas-theme.json\n' + texts.theme.trim() + '\n')
          .then(function () { say('Copied both files'); }, function () { say('Copying failed; select the text instead', true); });
      }
      if (a === 'reset') {
        window.localStorage.removeItem(OVERRIDE_KEY);
        texts = { theme: FILES.theme, css: FILES.css };
        activate(parseTheme(FILES.theme), FILES.css);
        show(tab);
        palette();
        updateBadge();
        say('Back to the files (' + VERSION + ')');
      }
    });
    palette();
    show('css');
    paint();
    say(o ? 'Local override active' + (o.version !== VERSION ? '; it was made on ' + o.version + ', the files are now ' + VERSION : '') :
      'Editing a copy of the files (' + VERSION + ')', !!(o && o.version !== VERSION));
  }
  function editorRequested() { return /[?&]atlasEditor=1(&|$)/.test(window.location.search); }

  function fetchText(name) {
    return fetch(BASE + name + '?_cache=' + VERSION).then(function (r) {
      if (!r.ok) { throw new Error(name + ': HTTP ' + r.status); }
      return r.text();
    });
  }
  Promise.all([fetchText('atlas-theme.json'), fetchText('atlas.css')]).then(function (files) {
    FILES = { theme: files[0], css: files[1] };
    var theme = parseTheme(FILES.theme);
    var css = FILES.css;
    var o = readOverride();
    if (o) {
      try { theme = parseTheme(o.theme); css = o.css; } catch (e) { console.error('atlas-theme: local override ignored', e); }
    }
    start(theme, css);
    updateBadge();
    if (editorRequested()) { openEditor(); }
    runtime.locationService.getHistory().listen(function () { if (editorRequested()) { openEditor(); } });
  }).catch(function (e) { console.error('atlas-theme: not applied', e); });

  return { plugin: new data.AppPlugin() };
});
