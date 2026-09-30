# Atlas theme plugin

`atlas-theme-app` gives Grafana the Atlas Light and Atlas Dark themes. It is a preload app plugin with no build step, and every Grafana page loads it. Three files matter:

| File | What it holds |
|---|---|
| `atlas-theme.json` | The palette, and one Grafana theme definition per mode in Grafana's own format. These cover backgrounds, text, borders, buttons, accent, status colours, the named colours dashboards use (`green`, `yellow`, …), and the series palette. It also holds the colour names Grafana has no slot for (`gray`, `teal`, …). |
| `atlas.css` | A plain stylesheet: styling rules, and the canvas variables below. |
| `module.js` | The engine that applies both files. It contains no colours. |

The rules the files implement are in `pjan/atlas-dashboards` `CONVENTIONS.md`.

## Editing

- **Live, in the browser:** add `?atlasEditor=1` to any Grafana URL. A drawer opens with both files, and every edit applies at once without a reload.
  - Palette swatches insert `var(--atlas-<hue>-<step>)` in `atlas.css` and `atlas.<key>` in `atlas-theme.json`.
  - Edits stay in that browser only (localStorage), shown by a badge, until you click **Reset to files**.
  - **Copy both** copies the two files so they can be committed.
- **In Chrome DevTools:** DevTools lists the stylesheet as `atlas.css`. Its rules show in the Styles pane with line numbers and can be edited there.
- **In the repository:** edit the files and bump `info.version` in `plugin.json`, because browsers cache all three files by that version. Then run `scripts/validate.sh`. It checks:
  - `atlas-theme.json` against Grafana's theme schema;
  - every `atlas.<key>` reference;
  - the mirroring rule (dark step = 1000 − light step) in the theme definitions and colour names;
  - that every `var(--atlas-…)` in `atlas.css` is defined;
  - that every canvas variable name exists.

## atlas.css

- **Theme blocks:** `html[data-atlas-theme="light"]` and `html[data-atlas-theme="dark"]`. The plugin keeps the attribute in sync with the active theme. Rules outside the blocks apply in both themes.
- **Palette variables,** generated from `atlas-theme.json`:
  - `--atlas-gray-100` … `--atlas-gray-900`, and the same for red, orange, amber, emerald, sky, indigo, purple, violet, lime, teal, cyan, pink and green;
  - `--atlas-ink` (`#010206`), `--atlas-white`, and `--atlas-page` (`#f4f7fa`).

  Don't redefine them; `validate.sh` fails if you do.
- **Selectors:** Grafana's own class names (`css-…`) change with every Grafana build, so don't use them. Use these instead:

  | To select | Selector |
  |---|---|
  | An area | its `data-testid`, for example `[data-testid="data-testid dashboard controls"]`, `[data-testid^="stat-panel-"]` or `[data-testid^="table-panel-"]` |
  | One panel | `[data-viz-panel-key="panel-<id>"]` |
  | A panel type | `[data-plugin-id="<type>"]`, for example `[data-plugin-id="state-timeline"]` |
  | A control | its `aria-label` |

- **Specificity:** Grafana adds its styles after this sheet. Prefix a rule with a theme block selector, which also raises its specificity, or use `!important`.
- **States:** Grafana writes a state's colour inline on the element, so a rule for one state matches that colour. For example:
  - `[style*="background: rgb(111, 198, 134)"]` is a green (OK) stat tile or table cell in light;
  - `span[style*="background-color: rgb(111, 198, 134)"]` is a green pill.

  The comment at the top of `atlas.css` lists the value for every state and mode. The values follow `atlas-theme.json`, so update the selectors when it changes.
- **Normal CSS works for these chart parts,** because they are page elements:
  - the hover crosshair (`.u-cursor-x`, `.u-cursor-y`) and the drag-to-zoom area (`.u-select`);
  - legends, tooltips, and annotation markers;
  - pie charts, gauges and bar gauges.

## Canvas variables

Chart panels draw on a `<canvas>`, which CSS can't style, so the plugin reads these variables and draws with them instead of Grafana's colours.
- **Where they're read:** on each canvas element itself. Any selector can set them, and they inherit like any CSS variable: a theme block for every chart, `[data-plugin-id="…"]` for a panel type, `[data-viz-panel-key="panel-<id>"]` for one panel.
- **Values:** any CSS colour works, including `var(--atlas-…)`, `color-mix()`, `transparent` and `rgb(… / alpha)`.
- **Unset:** a variable that isn't set keeps Grafana's colour.
- **Which panels:** checked on Grafana 13.2.3 with time series, bar chart, state timeline, status history, histogram, heatmap, trend, candlestick and stat. XY chart uses the same axis code but didn't load in the test Grafana, so it's unverified there.

| Variable | What it colours | Panels |
|---|---|---|
| `--atlas-grid` | Grid lines and axis ticks | Every chart panel: time series, bar chart, state timeline, status history, histogram, heatmap, trend, candlestick (XY chart unverified) |
| `--atlas-axis-text` | Axis labels. In bar charts also the value labels on the bars, which Grafana draws in the same colour. | Same panels |
| `--atlas-<role>-outline` | The outline of a segment in that state | State timeline, status history |
| `--atlas-<role>-text` | The value text on a segment in that state | State timeline, status history |
| `--atlas-<role>-sparkline` | The sparkline line on a stat tile coloured in that state (`colorMode: background_solid`) | Stat |
| `--atlas-<role>-sparkline-fill` | The area under that sparkline | Stat |

`<role>` is the state, and each maps to the colour name dashboards use for it:

| Role | Colour name |
|---|---|
| `ok` | `green` |
| `warning` | `yellow` |
| `critical` | `red` |
| `progress` | `blue` |
| `pending` | `purple` |
| `unknown` | `gray` |

The plugin recognises a state from the segment's or tile's colour in any shade of that name. For example, `super-light-green` and `green` both count as `ok`.

**Defaults in `atlas.css`,** matching the look before 3.0.0:

| Variable | Light | Dark |
|---|---|---|
| `--atlas-grid` | gray 200 | gray 800 |
| `--atlas-axis-text` | gray 700 | gray 300 |
| `--atlas-<role>-outline` | the role hue at 400 | the role hue at 600 |
| `--atlas-<role>-text` | the role hue at 800 | the role hue at 200 |
| `--atlas-<role>-sparkline` | the role hue at 900, 45 % | the role hue at 100, 45 % |
| `--atlas-<role>-sparkline-fill` | the role hue at 900, 18 % | the role hue at 100, 18 % |

The role hues are emerald, amber, red, sky, purple and gray.

**What canvas variables don't cover.** These colours come from `atlas-theme.json` and are shared with other roles, so a variable could not tell them apart:
- series lines, bars and areas (the series palette);
- threshold lines, annotation regions, and candlestick up and down colours (the named colours);
- heatmap cells (the colour scheme);
- sparklines on tiles that aren't coloured by state (they use the field colour).

## Theme switch and Grafana upgrades

- **Theme switch:** after a switch, or after an edit in the drawer, the plugin makes every panel of the open dashboard process its colours again, and refreshes it once.
- **Grafana upgrades:** the plugin relies on undocumented Grafana behaviour, listed in the header of `module.js`. After a Grafana upgrade, run `scripts/theme-probe.sh` (see the repository README, Monitoring).
- **Without the plugin:** the dashboards keep working with Grafana's stock colours, except that `super-light-gray` timeline segments render black. That happens if a file fails to load, or for viewers without an org role, such as public dashboards.
