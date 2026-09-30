/*
 * Atlas theme engine: a preload app plugin, hand-written AMD without a build step.
 * It has no colours of its own; it applies two data files from this directory:
 *   atlas-theme.json  Grafana theme definitions ("Atlas Light", "Atlas Dark") in Grafana's
 *                     theme-definition format, plus colour names Grafana has no slot for;
 *   atlas-style.json  what a theme cannot express: per-component CSS and canvas colours.
 * The rules they implement are pjan/atlas-dashboards CONVENTIONS.md.
 *
 * 1. Theme: builds the theme with createTheme() and publishes it as the active theme on
 *    load, on every theme change, and again after 200 ms, 1 s, and 3 s (Grafana may still
 *    publish its own theme while starting). The built theme also resolves the extra colour
 *    names (gray, teal, ...) and gives state-timeline values the cell or pill text colour.
 * 2. Stylesheet: one rule set per mode under html[data-atlas-theme], keyed on the colours
 *    Grafana writes into inline styles. Keys come from both modes, so elements that still
 *    carry the previous theme's colours after a switch are restyled too.
 * 3. Canvas: remaps the grid, tick, and axis-label colours uPlot panels draw, and the
 *    state-timeline outline (the pill ring), by wrapping the canvas colour setters.
 * 4. Theme switch: whenever an Atlas theme replaces a stock one (on load, on a switch), resets
 *    Grafana's cached continuous colour schemes and makes every panel of the open dashboard
 *    process its field config again; otherwise both keep the previous colours until a reload.
 *
 * All of it uses undocumented Grafana behaviour: publishing ThemeChangedEvent with a
 * replacement theme, the inline styles and data-testid attributes Grafana 13.2.3 renders,
 * the colours uPlot is given, FieldColorSchemeMode's cache fields, and the dashboard scene's
 * panels (window.__grafanaSceneContext, clearFieldConfigCache). After a Grafana
 * upgrade, run scripts/theme-probe.sh (README.md, Monitoring).
 * Without the plugin (it does not load for viewers without an org role, such as public
 * dashboards) the dashboards work with Grafana's stock colours, except the extra names:
 * super-light-gray timeline segments render black, gray ones in Grafana's CSS gray.
 *
 * Bump info.version in plugin.json with every change to this directory: Grafana loads this
 * file as module.js?_cache=<version>, and this file loads the JSON files with the same key.
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

  var THEME = null;
  var STYLE = null;
  var MODE = 'dark';
  // True until an Atlas theme is active, and again whenever Grafana puts a stock theme in
  // place: panels processed meanwhile hold stock colours.
  var stale = true;

  // ---- References: atlas.<key> is a palette colour, atlas.<key>/<alpha> the same with alpha.
  function ref(value) {
    return value.replace(/atlas\.([a-z]+[0-9]*)(?:\/([0-9.]+))?/g, function (match, key, alpha) {
      var hex = THEME.palette[key];
      if (!hex) { console.error('atlas-theme: unknown palette key ' + key); return match; }
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
  function rgb(hex) { return 'rgb(' + channels(hex).join(', ') + ')'; }
  function hex6(color) {
    if (typeof color !== 'string') { return null; }
    if (color[0] === '#') { return color.slice(0, 7).toLowerCase(); }
    var m = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color);
    return m ? '#' + [m[1], m[2], m[3]].map(function (n) { return ('0' + (+n).toString(16)).slice(-2); }).join('') : null;
  }
  // A slot value: a number is that step of the hue, a string a colour or reference.
  function slot(hue, mode, name) {
    var v = STYLE.slots[mode][name];
    return typeof v === 'number' ? THEME.palette[hue + v] : ref(v);
  }
  function modeOf(theme) { return theme && theme.colors && theme.colors.mode === 'light' ? 'light' : 'dark'; }
  // Lookups in maps keyed by colours or names, without inherited keys such as "constructor".
  function own(map, key) { return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined; }
  // The series palette of a mode: the other mode's role colours that are also series colours
  // here (orange 400 and 600) are not treated as roles in this mode.
  function series(mode) {
    var out = {};
    resolve(THEME.themes[mode].visualization.palette).forEach(function (c) { out[c.toLowerCase()] = true; });
    return out;
  }
  function otherModeKey(mode, m, color) { return m !== mode && own(series(mode), color.toLowerCase()); }

  // ---- 1. Theme
  // State timelines ask getContrastText for the text on each segment: on a role fill the state
  // cell text, on a pill fill the pill text (fills of either mode, for leftovers of a switch).
  function contrastMap(mode) {
    var out = {};
    Object.keys(STYLE.roles).forEach(function (name) {
      var hue = STYLE.roles[name];
      MODES.forEach(function (m) {
        [['fill', 'cell-fg'], ['pill-bg', 'pill-fg']].forEach(function (pair) {
          var bg = slot(hue, m, pair[0]);
          if (!otherModeKey(mode, m, bg)) { out[bg] = slot(hue, mode, pair[1]); }
        });
      });
    });
    return out;
  }
  function build(base) {
    var mode = modeOf(base);
    var theme = data.createTheme(resolve(THEME.themes[mode]));
    theme.flags = Object.assign({}, base.flags);
    theme.atlas = true;
    var names = resolve(THEME.names[mode]);
    var byName = theme.visualization.getColorByName;
    theme.visualization.getColorByName = function (name) { return (name && own(names, name)) || byName(name); };
    var contrast = contrastMap(mode);
    var contrastText = theme.colors.getContrastText;
    theme.colors.getContrastText = function (background, threshold) {
      return own(contrast, hex6(background)) || contrastText(background, threshold);
    };
    return theme;
  }
  function publish(base) {
    runtime.getAppEvents().publish(new runtime.ThemeChangedEvent(build(base)));
  }
  function apply() {
    var current = runtime.config.theme2;
    if (current && !current.atlas) { publish(current); } else { restyle(current); }
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

  // ---- 2. Stylesheet
  function get(obj, path) { return path.split('.').reduce(function (o, k) { return o == null ? o : o[k]; }, obj); }
  function decls(set) {
    return Object.keys(set).map(function (p) { return p + ':' + set[p] + ' !important'; }).join(';');
  }
  // Grafana name -> the rendered colours to match: its resolved colour in both modes (except
  // where the other mode's colour is a series colour in this one).
  function keys(mode) {
    var out = {};
    Object.keys(STYLE.roles).forEach(function (name) {
      out[name] = [];
      MODES.forEach(function (m) {
        var color = own(resolve(THEME.names[m]), name) || nameColor(m, name);
        if (!otherModeKey(mode, m, color) && out[name].indexOf(rgb(color)) < 0) { out[name].push(rgb(color)); }
      });
    });
    return out;
  }
  function nameColor(mode, name) {
    var found = null;
    resolve(THEME.themes[mode]).visualization.hues.forEach(function (hue) {
      hue.shades.forEach(function (s) { if (s.name === name) { found = s.color; } });
    });
    if (!found) { console.error('atlas-theme: no colour for ' + name + ' in ' + mode); }
    return found || '#000000';
  }
  function generate(theme) {
    var mode = modeOf(theme);
    var K = keys(mode);
    var names = Object.keys(K);
    var pre = 'html[data-atlas-theme="' + mode + '"] ';
    var root = Object.keys(STYLE.tokens).map(function (n) { return '--atlas-' + n + ':' + get(theme, STYLE.tokens[n]); });
    var css = ':root{' + root.join(';') + '}\n';
    function sels(match, name) {
      return K[name].map(function (k) { return pre + match.split('{c}').join(k); });
    }
    // Per name: bind the slot variables (--c-*) on every element that renders it.
    names.forEach(function (name) {
      var hue = STYLE.roles[name];
      var all = [];
      STYLE.components.forEach(function (c) { all = all.concat(sels(c.match, name)); });
      all = all.concat(sels(STYLE.sparkline.match, name));
      css += all.join(',') + '{' + Object.keys(STYLE.slots[mode]).map(function (s) {
        return '--c-' + s + ':' + slot(hue, mode, s);
      }).join(';') + '}\n';
    });
    // Per component: its declarations, once.
    STYLE.components.forEach(function (c) {
      var all = [];
      names.forEach(function (name) { all = all.concat(sels(c.match, name)); });
      css += '/* ' + c.name + ' */\n' + all.join(',') + '{' + decls(c.set) + '}\n';
      if (c.deep) { css += all.map(function (s) { return s + ' *'; }).join(',') + '{' + decls(c.deep) + '}\n'; }
    });
    STYLE['static'].forEach(function (r) { css += '/* ' + r.name + ' */\n' + r.match + '{' + decls(r.set) + '}\n'; });
    // Sparklines on coloured stat tiles: recoloured to the slot colour by an SVG filter.
    names.forEach(function (name) {
      css += sels(STYLE.sparkline.match, name).join(',') + '{filter:url(#atlas-spark-' + mode + '-' + name + ') !important;opacity:' +
        STYLE.sparkline.opacity + ' !important}\n';
    });
    return css;
  }
  function sparkFilters() {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>';
    MODES.forEach(function (mode) {
      Object.keys(STYLE.roles).forEach(function (name) {
        var c = channels(slot(STYLE.roles[name], mode, STYLE.sparkline.slot)).map(function (n) { return (n / 255).toFixed(4); });
        svg += '<filter id="atlas-spark-' + mode + '-' + name + '" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="' +
          '0 0 0 0 ' + c[0] + ' 0 0 0 0 ' + c[1] + ' 0 0 0 0 ' + c[2] + ' 0 0 0 1 0"/></filter>';
      });
    });
    var holder = document.createElement('div');
    holder.innerHTML = svg + '</defs></svg>';
    holder.firstChild.id = 'atlas-theme-filters';
    document.body.appendChild(holder.firstChild);
  }
  var style = document.createElement('style');
  style.id = 'atlas-theme-css';
  function restyle(theme) {
    if (!theme || !theme.colors) { return; }
    MODE = modeOf(theme);
    document.documentElement.setAttribute('data-atlas-theme', MODE);
    if (!theme.atlas) { stale = true; return; }
    if (stale) {
      stale = false;
      resetSchemes();
      setTimeout(reprocessPanels, 0);
    }
    var css = generate(theme);
    if (css !== style.textContent) { style.textContent = css; }
  }

  // ---- 3. Canvas
  var CANVAS = { light: {}, dark: {} };
  var RING = { light: {}, dark: {} };
  function canvasMaps() {
    var axes = STYLE.canvas.axes;
    MODES.forEach(function (mode) {
      axes[mode].forEach(function (r) { CANVAS[mode][ref(r.from)] = ref(r.to); });
      if (!STYLE.canvas.timeline.ring) { return; }
      Object.keys(STYLE.roles).forEach(function (name) {
        var hue = STYLE.roles[name];
        MODES.forEach(function (m) {
          var bg = slot(hue, m, 'pill-bg');
          if (!otherModeKey(mode, m, bg)) { RING[mode][bg] = slot(hue, mode, 'pill-ring'); }
        });
      });
    });
  }
  var SCOPE = new WeakMap();
  function scopeOf(canvas) {
    var s = SCOPE.get(canvas);
    if (s !== undefined) { return s; }
    if (!canvas || !canvas.closest) { return null; }
    var panel = canvas.closest('[data-plugin-id]');
    s = { axes: !!canvas.closest(STYLE.canvas.axes.scope),
      timeline: !!panel && /^(state-timeline|status-history)$/.test(panel.getAttribute('data-plugin-id')) };
    if (canvas.isConnected) { SCOPE.set(canvas, s); }
    return s;
  }
  function wrapCanvas() {
    var proto = CanvasRenderingContext2D.prototype;
    ['strokeStyle', 'fillStyle'].forEach(function (prop) {
      var d = Object.getOwnPropertyDescriptor(proto, prop);
      Object.defineProperty(proto, prop, {
        configurable: true, enumerable: d.enumerable, get: d.get,
        set: function (v) {
          if (typeof v === 'string') {
            var axis = own(CANVAS[MODE], v);
            // Grafana gives timeline strokes as #rrggbb, sometimes with an alpha suffix.
            var ring = prop === 'strokeStyle' && v[0] === '#' && own(RING[MODE], v.slice(0, 7).toLowerCase());
            if (axis || ring) {
              var s = scopeOf(this.canvas);
              if (s && s.axes && axis) { v = axis; } else if (s && s.timeline && ring) { v = ring; }
            }
          }
          d.set.call(this, v);
        }
      });
    });
  }

  // ---- Start
  function start() {
    canvasMaps();
    wrapCanvas();
    sparkFilters();
    document.head.appendChild(style);
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
  function load(name) {
    return fetch(BASE + name + '?_cache=' + VERSION).then(function (r) {
      if (!r.ok) { throw new Error(name + ': HTTP ' + r.status); }
      return r.json();
    });
  }
  Promise.all([load('atlas-theme.json'), load('atlas-style.json')]).then(function (files) {
    THEME = files[0];
    STYLE = files[1];
    start();
  }).catch(function (e) { console.error('atlas-theme: not applied', e); });

  return { plugin: new data.AppPlugin() };
});
