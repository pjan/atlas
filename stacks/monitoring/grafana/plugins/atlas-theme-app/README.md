# Atlas theme plugin

`atlas-theme-app` gives Grafana the Atlas Light and Atlas Dark themes. It is a preload app plugin with no build step, and every Grafana page loads it. It only changes Grafana's theme; styling beyond the theme belongs in panel options (for example the looks of the State timeline plus panel plugin). Two files matter:

| File | What it holds |
|---|---|
| `atlas-theme.json` | The palette, and one Grafana theme definition per mode in Grafana's own format. These cover backgrounds, text, borders, buttons, accent, status colours, the named colours dashboards use (`green`, `yellow`, …), and the series palette. It also holds the colour names Grafana has no slot for (`gray`, `teal`, …). |
| `module.js` | The engine that applies the file. It contains no colours. |

The rules the file implements are in `pjan/atlas-dashboards` `CONVENTIONS.md`.

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
- **Without the plugin:** the dashboards keep working with Grafana's stock colours, except that `super-light-gray` timeline segments render black. That happens if the file fails to load, or for viewers without an org role, such as public dashboards.
