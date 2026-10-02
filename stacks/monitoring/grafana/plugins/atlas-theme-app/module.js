/*
 * Atlas theme engine: a preload app plugin, hand-written AMD without a build step.
 * It has no colours of its own; it applies atlas-theme.json from this directory (see
 * README.md): Grafana theme definitions ("Atlas Light", "Atlas Dark") in Grafana's
 * theme-definition format, plus colour names Grafana has no slot for.
 * The rules it implements are pjan/atlas-dashboards CONVENTIONS.md.
 *
 * 1. Theme: builds the theme with createTheme() and publishes it as the active theme on
 *    load, on every theme change, and again after 200 ms, 1 s, and 3 s (Grafana may still
 *    publish its own theme while starting). The built theme also resolves the extra colour
 *    names (gray, teal, ...).
 * 2. Theme switch: whenever an Atlas theme replaces a stock one (on load, on a switch, after an
 *    edit), resets Grafana's cached continuous colour schemes and makes every panel of the open
 *    dashboard process its field config again; otherwise both keep the previous colours.
 * 3. Live editor: ?atlasEditor=1 opens a drawer to edit atlas-theme.json in the browser; edits
 *    apply at once and stay in this browser's localStorage until "Reset to file".
 *
 * All of it uses undocumented Grafana behaviour: publishing ThemeChangedEvent with a
 * replacement theme, FieldColorSchemeMode's cache fields, and the dashboard scene's panels
 * (window.__grafanaSceneContext, clearFieldConfigCache) (Grafana 13.2.3). After a Grafana
 * upgrade, run scripts/theme-probe.sh (README.md, Monitoring).
 * Without the plugin (it does not load for viewers without an org role, such as public
 * dashboards) the dashboards work with Grafana's stock colours, except the extra names:
 * super-light-gray timeline segments render black, gray ones in Grafana's CSS gray.
 *
 * Bump info.version in plugin.json with every change to this directory: Grafana loads this
 * file as module.js?_cache=<version>, and this file loads atlas-theme.json with the same key.
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

  var THEME = null;
  // True until an Atlas theme is active, and again whenever Grafana puts a stock theme in
  // place: panels processed meanwhile hold stock colours.
  var stale = true;

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
  function modeOf(theme) { return theme && theme.colors && theme.colors.mode === 'light' ? 'light' : 'dark'; }
  // Lookups in maps keyed by names, without inherited keys such as "constructor".
  function own(map, key) { return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined; }

  // ---- 1. Theme
  function build(base) {
    var mode = modeOf(base);
    var theme = data.createTheme(resolve(THEME.themes[mode]));
    theme.flags = Object.assign({}, base.flags);
    theme.atlas = true;
    var names = resolve(THEME.names[mode]);
    var byName = theme.visualization.getColorByName;
    theme.visualization.getColorByName = function (name) { return (name && own(names, name)) || byName(name); };
    return theme;
  }
  function publish(base) {
    runtime.getAppEvents().publish(new runtime.ThemeChangedEvent(build(base)));
  }
  function apply() {
    var current = runtime.config.theme2;
    if (current && !current.atlas) { stale = true; publish(current); } else { switched(current); }
  }

  // ---- 2. Theme switch
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
  function switched(theme) {
    if (!theme || !theme.colors) { return; }
    if (!theme.atlas) { stale = true; return; }
    if (stale) {
      stale = false;
      resetSchemes();
      setTimeout(reprocessPanels, 0);
    }
    paint(theme);
  }

  // ---- Start
  // Applies a theme: the file, or the live editor's local override.
  function activate(theme) {
    THEME = theme;
    stale = true;
    publish(runtime.config.theme2);
  }
  function start(theme) {
    THEME = theme;
    runtime.getAppEvents().subscribe(runtime.ThemeChangedEvent, function (event) {
      switched(event.payload);
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

  // ---- 3. Live editor: ?atlasEditor=1 on any page opens a drawer with atlas-theme.json. Edits
  // apply at once and are kept in this browser's localStorage (a local override) until "Reset
  // to file"; "Copy" copies the text for the repository. Other browsers and users keep seeing
  // the file.
  var OVERRIDE_KEY = 'atlas-theme-override';
  var FILE = '';
  function readOverride() {
    try {
      var o = JSON.parse(window.localStorage.getItem(OVERRIDE_KEY) || 'null');
      return o && typeof o.theme === 'string' ? o : null;
    } catch (e) { return null; }
  }
  function parseTheme(text) {
    var theme = JSON.parse(text);
    if (!theme.palette || !theme.themes || !theme.names) { throw new Error('atlas-theme.json needs palette, themes, and names'); }
    return theme;
  }
  // Palette keys atlas-theme.json refers to that do not exist.
  function problems(text, palette) {
    var out = [];
    text.replace(/atlas\.([a-z]+[0-9]*)/g, function (m, key) {
      if (!own(palette, key) && out.indexOf('atlas.' + key) < 0) { out.push('atlas.' + key); }
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
    badge.textContent = 'Atlas theme: local override' + (o.version !== VERSION ? ' (file is now ' + VERSION + ')' : '');
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
    var text = o ? o.theme : FILE;
    var timer = null;
    editor = document.createElement('div');
    editor.id = 'atlas-theme-editor';
    editor.style.cssText = 'position:fixed;top:0;right:0;bottom:0;width:560px;z-index:1400;display:flex;' +
      'flex-direction:column;border-left:1px solid;box-shadow:0 0 24px rgba(0,0,0,.25);font:13px/1.4 sans-serif';
    editor.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;padding:10px 12px">' +
      '<strong style="flex:1">Atlas theme editor: atlas-theme.json</strong>' +
      '<button data-a="reset">Reset to file</button><button data-a="copy">Copy</button>' +
      '<button data-a="close" aria-label="Close">✕</button></div>' +
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
    // Swatches insert atlas.<key>.
    function palette() {
      var box = editor.querySelector('[data-el="palette"]');
      box.innerHTML = '';
      Object.keys(THEME.palette).filter(function (k) { return /[0-9]00$/.test(k); }).forEach(function (key) {
        var sw = document.createElement('button');
        sw.type = 'button';
        sw.title = 'atlas.' + key + ' ' + THEME.palette[key] + ' (click inserts it)';
        sw.style.cssText = 'height:16px;border:0;border-radius:2px;padding:0;cursor:pointer;background:' + THEME.palette[key];
        sw.addEventListener('click', function () {
          var a = area.selectionStart, b = area.selectionEnd;
          var ins = 'atlas.' + key;
          area.value = area.value.slice(0, a) + ins + area.value.slice(b);
          area.selectionStart = area.selectionEnd = a + ins.length;
          area.focus();
          changed();
        });
        box.appendChild(sw);
      });
    }
    function say(message, bad) { status.textContent = message; status.style.color = bad ? '#ea5a53' : ''; }
    function changed() {
      text = area.value;
      clearTimeout(timer);
      timer = setTimeout(function () {
        var theme;
        try { theme = parseTheme(text); } catch (e) { say('atlas-theme.json: ' + ((e && e.message) || e), true); return; }
        var found = problems(text, theme.palette);
        window.localStorage.setItem(OVERRIDE_KEY, JSON.stringify({ version: VERSION, theme: text }));
        activate(theme);
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
      var a = b.getAttribute('data-a');
      if (a === 'close') { editor.remove(); editor = null; return; }
      if (a === 'copy') {
        navigator.clipboard.writeText(text.trim() + '\n')
          .then(function () { say('Copied atlas-theme.json'); }, function () { say('Copying failed; select the text instead', true); });
      }
      if (a === 'reset') {
        window.localStorage.removeItem(OVERRIDE_KEY);
        text = FILE;
        activate(parseTheme(FILE));
        area.value = text;
        palette();
        updateBadge();
        say('Back to the file (' + VERSION + ')');
      }
    });
    area.value = text;
    palette();
    paint();
    say(o ? 'Local override active' + (o.version !== VERSION ? '; it was made on ' + o.version + ', the file is now ' + VERSION : '') :
      'Editing a copy of the file (' + VERSION + ')', !!(o && o.version !== VERSION));
  }
  function editorRequested() { return /[?&]atlasEditor=1(&|$)/.test(window.location.search); }

  fetch(BASE + 'atlas-theme.json?_cache=' + VERSION).then(function (r) {
    if (!r.ok) { throw new Error('atlas-theme.json: HTTP ' + r.status); }
    return r.text();
  }).then(function (file) {
    FILE = file;
    var theme = parseTheme(FILE);
    var o = readOverride();
    if (o) {
      try { theme = parseTheme(o.theme); } catch (e) { console.error('atlas-theme: local override ignored', e); }
    }
    start(theme);
    updateBadge();
    if (editorRequested()) { openEditor(); }
    runtime.locationService.getHistory().listen(function () { if (editorRequested()) { openEditor(); } });
  }).catch(function (e) { console.error('atlas-theme: not applied', e); });

  return { plugin: new data.AppPlugin() };
});
