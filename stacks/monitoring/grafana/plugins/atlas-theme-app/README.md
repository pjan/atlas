# Atlas theme plugin

`atlas-theme-app` gives Grafana the Atlas Light and Atlas Dark themes. It is a preload app plugin with no build step, and every Grafana page loads it. It only changes Grafana's theme; styling beyond the theme belongs in panel options (for example the looks of the State timeline plus panel plugin). Two files matter:

| File | What it holds |
|---|---|
| `atlas-theme.json` | The palette, and one Grafana theme definition per mode in Grafana's own format. These cover backgrounds, text, borders, buttons, accent, status colours, the named colours dashboards use (`green`, `yellow`, …), and the series palette. It also holds the colour names Grafana has no slot for (`gray`, `teal`, …), each hue with Grafana's five shade names (`super-light-teal` … `dark-teal`). |
| `module.js` | The engine that applies the file. It contains no colours. |

The rules the file implements are in `pjan/atlas-dashboards` `CONVENTIONS.md`.

**Extra hues.** Grafana's `createTheme()` ignores hue names it doesn't have, so `module.js` appends the extra names' hues (gray, indigo, violet, lime, teal, cyan, pink: the order of `names`) to the built theme's `theme.visualization.hues`, each with the five shades (base as primary) resolved through the theme's own colour names. Two things follow:

- Every colour picker in Grafana lists them as rows after Grafana's six hues, so they can be picked like `green`.
- Panel plugins that read the theme's hues see them: the plus plugins give a colour without a name (the hex series palette) the shades of its nearest hue, so a lime series gets the lime shades.

Dashboards that use these names depend on the Atlas theme: without it, Grafana reads `lime`, `teal`, `pink`, … as CSS colours (`lime` is `#00ff00`), and `super-light-gray` and the other shade names as unknown (timeline boxes in them render black).

Each mode's `text.maxContrast` is the other mode's page colour (light: `atlas.ink`, dark: `atlas.page`). The plus panel plugins' "Automatic" text colour searches between a theme's page colour and its `maxContrast`, so in both modes it ends at the two page colours.

## Editing

- **Live, in the browser:** add `?atlasEditor=1` to any Grafana URL. A drawer opens with `atlas-theme.json`, and every edit applies at once without a reload.
  - Palette swatches insert `atlas.<key>`.
  - Edits stay in that browser only (localStorage), shown by a badge, until you click **Reset to file**.
  - **Copy** copies the file so it can be committed.
- **In the repository:** edit the file and bump `info.version` in `plugin.json`, because browsers cache both files by that version. Then run `scripts/validate.sh`. It checks:
  - `atlas-theme.json` against Grafana's theme schema;
  - every `atlas.<key>` reference;
  - the mirroring rule (dark step = 1000 − light step) in the theme definitions and colour names.

## Theme switch and Grafana upgrades

- **Theme switch:** after a switch, or after an edit in the drawer, the plugin makes every panel of the open dashboard process its colours again, and refreshes it once.
- **Grafana upgrades:** the plugin relies on undocumented Grafana behaviour, listed in the header of `module.js`. After a Grafana upgrade, run `scripts/theme-probe.sh` (see the repository README, Monitoring).
- **Without the plugin:** the dashboards keep working with Grafana's stock colours, except the extra names: `super-light-gray` timeline segments render black, and `lime`, `teal`, … are CSS colours. That happens if the file fails to load, or for viewers without an org role, such as public dashboards.
