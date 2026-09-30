/*
 * Atlas theme: a preload app plugin, hand-written AMD without a build step.
 * The rules it implements are pjan/atlas-dashboards CONVENTIONS.md sections 1-4.
 *
 * 1. Replaces Grafana's active theme with one built by createTheme() on load, on
 *    every theme change, and again after 200 ms, 1 s, and 3 s (Grafana may still
 *    publish its own theme while starting). The theme sets:
 *    - the page and panel backgrounds;
 *    - Grafana's named colours, remapped per theme onto the Atlas palette
 *      (green = emerald, yellow = amber, red, blue = sky, purple, orange), so
 *      dashboards keep theme-independent names and every panel, DOM or canvas,
 *      follows the theme;
 *    - the palette-classic series order.
 * 2. Adds one stylesheet for what a theme cannot express: text colour, weight,
 *    and radius of stat tiles and table state cells, the pill style, the gray
 *    fills (dashboards use #95a49f for gray), and solid bar gauge bars. Rules are
 *    keyed on the per-theme resolved fills and switched by html[data-atlas-theme],
 *    which this plugin keeps in sync with the active theme.
 *
 * Both parts use undocumented Grafana behaviour: publishing ThemeChangedEvent
 * with a replacement theme, and CSS selectors on the inline styles and
 * data-testid attributes Grafana 13.2.2 renders. After a Grafana upgrade, check
 * in both themes (and after switching theme) that backgrounds, stat tiles, table
 * state cells, pills, bar gauge and gauge-cell bars, and state timelines show the
 * Atlas colours; then compare these inline styles with the new release:
 *   stat tile        [data-testid^="stat-panel-"] ... style "display: flex; background: rgb(...)"
 *   table cell       [data-testid^="table-panel-"] [role="gridcell"] style "background: rgb(...)"
 *   pill             ... [role="gridcell"] span style "background-color: rgb(...)"
 *   bar gauge bar    style "background: rgba(..., 0.35); border-...: 2px solid rgb(...)"
 * Without the plugin every dashboard still works, with Grafana's stock colours.
 *
 * Bump info.version in plugin.json with every change: Grafana loads this file as
 * module.js?_cache=<version>, so browsers keep the old file until the version changes.
 */
define(['@grafana/data', '@grafana/runtime'], function (data, runtime) {
  // Atlas palette, steps 100 to 900 (CONVENTIONS.md section 2).
  var PAL = {
    gray: ['#ededed', '#dadbd7', '#c5c9c3', '#aeb6b0', '#95a49f', '#7c908f', '#647a7f', '#4c606d', '#344154'],
    red: ['#ffe8e5', '#fed0ca', '#fcb6ae', '#f99a91', '#f47c72', '#d66c63', '#b55a53', '#904641', '#652f2b'],
    orange: ['#fee9e0', '#fbd1c0', '#f9b99e', '#f59f7a', '#f08250', '#d27145', '#b15e39', '#8d4a2c', '#63321c'],
    amber: ['#f9ebdb', '#f2d6b5', '#ebc08d', '#e4a95f', '#dc8f11', '#c07d0f', '#a2690a', '#815307', '#5a3803'],
    emerald: ['#def2e7', '#bae4ce', '#93d5b4', '#64c699', '#24b57f', '#049e6c', '#01855b', '#026947', '#01492f'],
    sky: ['#deeffc', '#badff9', '#94cef7', '#67bcf3', '#1fa9f0', '#2c93ce', '#157cb2', '#0f628d', '#074363'],
    indigo: ['#e5edff', '#cadbff', '#aec8ff', '#91b3ff', '#739dff', '#6489df', '#5474bd', '#415b96', '#2c3f6a'],
    purple: ['#f6e8f8', '#eed1f2', '#e5b9eb', '#db9fe4', '#d183dd', '#b773c1', '#9a60a3', '#7a4b82', '#55335b'],
    violet: ['#efeafd', '#dfd5fb', '#cfbffa', '#bfa8f8', '#af8ef6', '#997cd7', '#8168b6', '#665291', '#463866'],
    lime: ['#ebefdb', '#d8deb6', '#c4cd8f', '#b0bb62', '#9ca81e', '#88931b', '#727c14', '#5a620f', '#3e4307']
  };
  function step(hue, n) { return PAL[hue][n / 100 - 1]; }

  var BG = {
    light: { canvas: '#f4f7fa', page: '#f4f7fa', primary: '#ffffff' },
    dark: { canvas: '#020918', page: '#020918', primary: '#020918' }
  };
  // Grafana's named hue -> Atlas hue (CONVENTIONS.md section 4).
  var HUE = { green: 'emerald', yellow: 'amber', red: 'red', blue: 'sky', purple: 'violet', orange: 'orange' };
  // Grafana shade -> Atlas step. The base name is the role fill: 400 light, 600 dark.
  // super-light-* is the pill fill (200 light, 800 dark), used by state timelines.
  var SHADE = {
    light: { 'super-light': 200, light: 300, base: 400, 'semi-dark': 500, dark: 700 },
    dark: { 'super-light': 800, light: 300, base: 600, 'semi-dark': 500, dark: 700 }
  };
  var FILL = { light: 400, dark: 600 };
  var TEXT = { light: '#020918', dark: '#ffffff' };
  // Stat tiles in light: the 300 fill with the 900 as text (dark keeps the role fill and TEXT).
  var TILE = { light: { bg: 300, fg: 900 } };
  var PILL = { light: { bg: 200, fg: 800 }, dark: { bg: 800, fg: 200 } };
  // Table colour-text cells: the role colour as bold text, 700 light, 200 dark.
  var CTEXT = { light: 700, dark: 200 };
  // Grafana's strong border colour per theme: the dashboard link buttons use it.
  var BORDER = { light: 'rgba(36, 41, 46, 0.4)', dark: 'rgba(204, 204, 220, 0.3)' };
  // Gray has no Grafana name; dashboards use gray 500, which the CSS turns into the gray fill.
  var GRAY = step('gray', 500);
  // palette-classic: five series hues at 500, then gray 500 for every further series.
  var PALETTE = [step('sky', 500), step('orange', 500), step('purple', 500), step('lime', 500), step('indigo', 500)];
  while (PALETTE.length < 50) { PALETTE.push(GRAY); }

  function hues(mode) {
    return Object.keys(HUE).map(function (name) {
      return {
        name: name,
        shades: ['super-light', 'light', 'base', 'semi-dark', 'dark'].map(function (shade) {
          var s = { name: shade === 'base' ? name : shade + '-' + name, color: step(HUE[name], SHADE[mode][shade]) };
          if (shade === 'base') { s.primary = true; }
          return s;
        })
      };
    });
  }

  // 1. Theme replacement.
  function build(base) {
    var mode = base.colors.mode === 'light' ? 'light' : 'dark';
    var theme = data.createTheme({
      name: base.name,
      colors: { mode: mode, background: BG[mode] },
      visualization: { hues: hues(mode), palette: PALETTE }
    });
    theme.flags = Object.assign({}, base.flags);
    theme.atlas = true;
    return theme;
  }
  function publish(base) {
    runtime.getAppEvents().publish(new runtime.ThemeChangedEvent(build(base)));
  }
  function setThemeAttr(theme) {
    if (theme && theme.colors) { document.documentElement.setAttribute('data-atlas-theme', theme.colors.mode); }
  }
  function apply() {
    var current = runtime.config.theme2;
    if (current && !current.atlas) { publish(current); }
  }
  runtime.getAppEvents().subscribe(runtime.ThemeChangedEvent, function (event) {
    setThemeAttr(event.payload);
    if (event.payload && !event.payload.atlas) {
      setTimeout(function () { publish(event.payload); }, 0);
    }
  });
  setThemeAttr(runtime.config.theme2);
  apply();
  [200, 1000, 3000].forEach(function (ms) { setTimeout(apply, ms); });

  // 2. CSS keyed on the colours Grafana writes into inline styles.
  function rgb(hex) {
    return [1, 3, 5].map(function (i) { return parseInt(hex.substr(i, 2), 16); }).join(', ');
  }
  var css = '';
  ['light', 'dark'].forEach(function (mode) {
    var pre = 'html[data-atlas-theme="' + mode + '"] ';
    Object.keys(HUE).map(function (name) { return HUE[name]; }).concat(['gray']).forEach(function (hue) {
      var fill = step(hue, FILL[mode]);
      // What Grafana renders: the resolved named colour, or #95a49f for gray.
      var key = rgb(hue === 'gray' ? GRAY : fill);
      var bg = hue === 'gray' ? 'background:' + fill + ' !important;' : '';
      var tile = pre + '[data-testid^="stat-panel-"] [style*="display: flex; background: rgb(' + key + ')"]';
      var cell = pre + '[data-testid^="table-panel-"] [role="gridcell"][style*="background: rgb(' + key + ')"]';
      var pill = pre + '[data-testid^="table-panel-"] [role="gridcell"] span[style*="background-color: rgb(' + key + ')"]';
      var bar = pre + '[style*="background: rgba(' + key + ', 0.35)"][style*="2px solid rgb(' + key + ')"]';
      var ctext = pre + '[data-testid^="table-panel-"] [role="gridcell"][style*="color: rgb(' + key + ')"]:not([style*="background"])';
      var tileBg = TILE[mode] ? 'background:' + step(hue, TILE[mode].bg) + ' !important;' : bg;
      var tileFg = TILE[mode] ? step(hue, TILE[mode].fg) : TEXT[mode];
      css += tile + '{' + tileBg + 'border-radius:6px !important;overflow:hidden !important}\n';
      css += tile + ',' + tile + ' *{color:' + tileFg + ' !important}\n';
      if (bg) { css += cell + '{' + bg + '}\n'; }
      css += cell + ',' + cell + ' *{color:' + TEXT[mode] + ' !important;font-weight:600 !important}\n';
      css += pill + '{background-color:' + step(hue, PILL[mode].bg) + ' !important;color:' + step(hue, PILL[mode].fg) +
        ' !important;box-shadow:inset 0 0 0 1px ' + fill + ' !important;border-radius:4px !important}\n';
      // Bar gauges and table gauge cells (basic mode) draw the bar at 35 % alpha; draw it solid.
      css += bar + '{background:' + fill + ' !important;border-color:' + fill + ' !important}\n';
      css += ctext + ',' + ctext + ' *{color:' + step(hue, CTEXT[mode]) + ' !important;font-weight:600 !important}\n';
    });
  });
  // The toolbar buttons on the right of the dashboard controls (time range, refresh,
  // share, edit) look like the dashboard link buttons on the left: transparent with
  // the strong border and 12 px text; Grafana's hover background stays.
  ['light', 'dark'].forEach(function (mode) {
    var btn = 'html[data-atlas-theme="' + mode + '"] [data-testid="data-testid dashboard controls"] button[class*="toolbar-button"]';
    css += btn + '{border-color:' + BORDER[mode] + ' !important;font-size:12px !important}\n';
    css += btn + ':not(:hover){background:transparent !important}\n';
  });
  // A colour-background cell without a colour (a transparent step) keeps the theme text.
  // Grafana resolves "transparent" to rgba(0, 0, 0, 0) in dark and rgba(255, 255, 255, 0) in light.
  css += '[data-testid^="table-panel-"] [role="gridcell"][style*="background: rgba(0, 0, 0, 0)"],' +
    '[data-testid^="table-panel-"] [role="gridcell"][style*="background: rgba(255, 255, 255, 0)"]{color:inherit !important}\n';
  var style = document.createElement('style');
  style.id = 'atlas-theme-css';
  style.textContent = css;
  document.head.appendChild(style);

  return { plugin: new data.AppPlugin() };
});
