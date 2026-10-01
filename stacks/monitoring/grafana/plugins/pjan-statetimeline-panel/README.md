# State timeline ++

Grafana's state timeline, as a separate panel plugin. With nothing configured, it looks and behaves like the core **State timeline** panel of Grafana 13.2.3: same options, defaults, rendering, tooltip, legend, annotations, shared crosshair, and drag to zoom. It starts from Grafana's own code. Additions are opt-in (off by default): [annotations on matching rows](#annotations-on-matching-rows) and [styling](#styling).

## Using it

- **Convert an existing state timeline:** change the panel's `type` from `state-timeline` to `pjan-statetimeline-panel` in the dashboard JSON (lossless), or pick **State timeline ++** in the panel editor (options, field config and overrides carry over).
- **Go back:** change `type` back to `state-timeline`. Core keeps this plugin's panel options in the JSON (and ignores them), but drops its field options when it loads the panel: **Annotation key**, **Line color**, **Fill color**, **Value color** and **Row name color**, in the field defaults and in overrides. Changing `type` to `pjan-statetimeline-panel` again brings back what the panel options set (such as **Look**), not the field options.
- **Annotations:** shown as in the core panel. Users who may add annotations can Ctrl/Cmd-click or Ctrl/Cmd-drag on empty plot space to add one, and edit or delete it from its tooltip.

## Annotations on matching rows

Draws an annotation on the timeline row it belongs to (a deploy on the `web` row) instead of across all rows. The events are the dashboard's annotations: any annotation query, with its colour and its "Show in" panel filter. Off by default.

- **Options** (panel options, group **Annotations**, after core's options; shown once the panel has annotations):
  - **Show on matching rows**: turns it on.
  - **Annotation field**: the annotation field compared with the rows, `tags` when not set. Lists the fields the panel's annotations have, such as `tags`, `title`, `text`, `type` (the annotation query's name), or a field added by a transformation.
  - **Row key**: what each row is matched by: its **Display name** (as on the y axis; used when not set) or the value of one of its **Label**s (pick the label name). A row without the label has no key and matches nothing.
  - **Annotation key** (field override, group Annotations): replaces the row key of the rows the override applies to, for rows whose name differs from the annotations' value. Add it with an override such as "Fields with name".
- **Matching:** an annotation matches a row when its field equals the row's key. For a list field such as `tags`, any value of the list can match. An annotation that matches several rows is drawn on each of them; one that matches no row is drawn as before, full height (or in its multi-row lane, and clustered, as the core options say).
  - **Rows not drawn:** with pagination ("Page size"), an annotation that matches a row on another page is not drawn on the current page at all (not full height either); it shows on its row's page. The same holds for a row hidden with "Hide in area" (`hideFrom.viz`).
  - **Multi-row lanes:** with "Enable multi-row annotations", each annotation query keeps its lane below the plot even when all its annotations are on rows, so that lane can be empty.
- **On a row:** a point annotation is a marker at the top of the row, pointing down, with a dashed line over that row only; a region is a bar along the top of the row, with dashed lines at its start and end. Markers have Grafana's annotation tooltip (edit, delete). "Enable annotation clustering" clusters close annotations per row, and "Hide lines and areas" hides the lines.
  - **Pinned tooltips:** clicking a marker pins its tooltip, and any click elsewhere unpins it, so one tooltip is pinned at a time. While one is pinned, hovering a marker of the other kind (a row marker while a full-height one is pinned, or the other way round) can still open a second, unpinned tooltip.
- **Adding an annotation on a row:** with **Annotation field** `tags` (or not set), Ctrl/Cmd-click on empty plot space of the row, Ctrl/Cmd-drag from it (the row where the drag starts counts), or "Add annotation" in the tooltip of a value on the row opens the annotation editor with the row's key as a tag; the saved annotation then shows on that row. A click between rows, on a row without a key, or with another annotation field adds core's untagged, full-height annotation. Changing the page or the rows while the editor is open cancels it.
- **Prometheus:** the annotation query puts the values of its **Tag keys** labels into `tags` (for tag keys `job`, an annotation for `job="web"` gets the tag `web`), so a row whose name or chosen label is `web` matches with the default field. Alternatively, set the query's **Title** format to `{{job}}` and match on `title`.

Limits in Grafana 13.2.3 (not worked around by this plugin):

- **Annotation transformations on classic dashboards:** a transformation set to "Apply transformation to: Annotation data" loses that setting when Grafana converts a dashboard stored as classic JSON (for example a provisioned file) on load (`transformPanelTransformations` in `apps/dashboard/pkg/migration/conversion/v1_to_v2alpha1.go`), and then runs on the query results instead. Saving such a dashboard from the UI stores it without the setting. Dashboards saved in the new (v2) format keep it.
- **Tooltip links:** a dashboard author can't add data links or actions to annotation tooltips: the panel's links and overrides don't apply to annotations, and annotation queries have no link settings.
- **Data source columns:** an annotation query's "Field mapping" carries only Grafana's annotation fields (time, end time, title, text, tags, id, and a few more); any other column of the query reaches the panel only when mapped into title, text or tags.

## Styling

Colours and looks beyond core's, set with Grafana's own colours: colour names, which the theme resolves (so they follow light and dark mode and theme plugins), and the colour picker. With nothing set, the panel looks like the core panel, and nothing is saved in the dashboard until an option is used.

- **Options** (group **State timeline**, next to core's options; the panel options come first in the group, then the field options):
  - **Look** (panel): **Grafana** (as core, when not set) or **Pill**: the softest shade of each state's colour as an opaque fill, a line in its base shade, and the value in its strongest shade; values that don't fit are hidden. Its fill is opaque, so **Fill opacity** doesn't apply. Its line is 1 px, unless **Line width** is set above 0: core saves a Line width of 0 on every new panel, so 0 counts as not set, and a Pill always has a line. It only sets the options left unset: a **Fill color**, **Line color**, **Value color**, **Value overflow** or **Line width** of your own wins. Pill sets no corner radius; combine it with **Corner radius** for rounded pills.
  - **Corner radius** (panel, after **Look**): rounds every box and its line, from 0 to 12 px; at most half a box's width and height (a short box gets round ends). Not set (clear the slider) or 0: square, as core. The hover highlight is rounded the same way; row annotation markers and the space left around values stay as for square boxes, so on a low row with a large radius a value can come close to a corner.
  - **Value overflow** (panel, after **Show values**): **Truncate** (core's) or **Hide**: a value that doesn't fit its box whole, or that would reach past the plot's edges where **Align values** puts it, is left out; so are all values on rows lower than 16 px. Not set (clear the select): as the look, so hide with Pill and truncate otherwise.
  - **Line color** (field, after **Line width**): a shade of the state colour, or a fixed colour. Drawn when **Line width** is set (or with Pill).
  - **Fill color** (field, after **Fill opacity**): a shade of the state colour. **Fill opacity** still applies.
  - **Value color** (field): **Best contrast** (black or white, whichever contrasts more with the box), a shade of the state colour, or a fixed colour. A shade or a fixed colour is used only where it reaches a contrast of 4.5:1 with the box as drawn (with its fill opacity, over the panel background); elsewhere best contrast. Not set: core's automatic contrast. The weight stays core's.
  - **Row name color** (field): a fixed colour, or **Current state color**: the colour of the row's state at its last value in the time range (ignoring empty values), in the softest shade of that colour that reaches 4.5:1 against the panel background; with none, the row name keeps the axis colour.
  - **Grid line color**, **Axis text color** (panel): fixed colours for the time grid and ticks, and for the time labels and row names.
  - **Day boundaries** (panel): **On** draws a line at 00:00 (in the dashboard's or panel's time zone) over the boxes, across the whole plot, and its time label bold; the grid line there is left out. **Day boundary color** sets that line's colour (the theme's strong border colour when not set). With a time axis whose every label is a day, nothing is set apart.
- **Per row:** the field options apply to every row, or to some rows with an override (such as "Fields with name"). Each row uses its own field's options.
- **Shades:** **Softer**, **Soft**, **Base**, **Strong**, **Stronger**. They are the five shades of the state colour's hue (`super-light-green`, `light-green`, `green`, `semi-dark-green`, `dark-green`), ranked by their contrast with the panel background in the active theme: softer is the shade nearest the background, stronger the farthest. So **Softer** is a light shade in a light theme and a dark one in a dark theme, and it means the same in any theme that defines the five names. The rank doesn't depend on which shade the state itself uses: a state in `semi-dark-green` gets the same softer shade as one in `green`.
- **Colours without a name:** a shade needs the state colour to be a Grafana colour name with five shades (from a value mapping, thresholds, the fixed colour, booleans, or the classic palette). Otherwise (a hex colour such as `#8e8e8e`, a continuous scheme such as the default "Green-Yellow-Red (by value)" for unmapped values, a palette of hex colours such as the Atlas theme's classic palette, `text`, `transparent`):
  - **Fill color** and **Line color** use the state colour;
  - **Value color** uses best contrast;
  - **Row name color** "Current state color" uses the state colour itself if it reaches 4.5:1 against the panel background, otherwise the axis colour.
- **Legend and tooltip:** their swatches show the fill drawn (without fill opacity, as core's show the state colour). The legend has one entry per state for all rows: with **Fill color** set per row, an entry shows the fill of the first row whose colours include that state.
- **Theme plugins:** the colours the styling sets are drawn as `rgb()` colours (a **Fill color** shade with **Fill opacity** applied is drawn as core draws its fills), which theme plugins that recolour Grafana's own canvas colours (such as the Atlas theme plugin) don't recognise, so they stay as set. The colours left unset are still Grafana's, and such a plugin recolours them as in the core panel.

## Differences from the core panel

- **No Grafana Assistant button** in the tooltip (not available to plugins).
- **No panel suggestions** in the visualization picker, so it doesn't show a second card next to the core state timeline.
- **Labels are in English only.** The plugin ships no translations.
- **No grouped-label filter buttons in the tooltip.** Core shows them only with Grafana's `grafana.filterablePanels` feature flag (off by default); this plugin doesn't read that flag, so they stay off.

## Source code

https://github.com/pjan/grafana-plugins (`plugins/pjan-statetimeline-panel`)

## Licence

AGPL-3.0, because it is derived from Grafana's core state-timeline panel. Code copied from Grafana's Apache-2.0 packages keeps that licence (`LICENSE_APACHE2`). Notices for bundled third-party packages are in `THIRD_PARTY_NOTICES.txt`.
