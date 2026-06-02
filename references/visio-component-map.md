# Visio Component Map

## Intent

This skill does not model all Visio shapes in version 1.

It uses a controlled semantic vocabulary so the analysis side stays stable while the renderer evolves from primitive geometry to richer stencil-aware rendering.

## Supported Node Types

| Type | Meaning | V1 renderer |
| --- | --- | --- |
| `page_background` | bottom export helper preserving canvas ratio | white rectangle ignored by semantic audits |
| `primitive_group` | editable group of basic rect/circle/line/text subshapes | subshape primitives in one local bbox |
| `shape_cluster` | icon-like or local structural cluster without business semantics | subshape primitives in one local bbox |
| `symbol_group` | small composed symbol such as circle-plus, triangle gate, cross, refresh mark | editable circle/line/triangle/text subshapes |
| `cell_strip` | repeated rectangular cells in a row/column | editable low-rounding cells with explicit count/gap |
| `micro_grid` | small matrix/tensor tile that should not become rounded tokens | editable rectangular cells and thin grid lines |
| `polyline_wave` | source-specific waveform/polyline silhouette | explicit samples/points, no generic sine in strict replicas |
| `ribbon_arrow` | straight filled/thick arrow used as a visual object | editable polygon-style arrow |
| `curved_ribbon_arrow` | broad curved arrow or gradient-like flow band | thick editable path with arrowhead |
| `loop_ribbon_arrow` | broad cycle/update loop arrow | sampled loop path with thick stroke and arrowhead |
| `qualitative_change_arrow` | preset for straight qualitative-change ribbon arrows | `ribbon_arrow` geometry with wider head defaults |
| `process_box` | standard process/module block | rectangle |
| `rounded_process` | softer process block | rounded rectangle |
| `stacked_process` | repeated offset feature/map block shown as one semantic node | repeated editable rounded rectangles |
| `stacked_token` | compact token/vector stack shown as one semantic node | repeated editable small rectangles |
| `notched_block` | CNN/cutout module with visible notches | base shape plus editable notch cutouts |
| `feature_map_banded` | striped or columnar feature-map patch | editable bands and overlays |
| `feature_map_grid` | heatmap-like feature map with colored rows and shaded columns | editable cell rectangles plus separators |
| `merge_bus` | visible fan-in/fan-out bus or merge spine | editable line segments |
| `decision_diamond` | decision/judge node | rotated rectangle approximation |
| `terminator` | start/end block | high-rounding rectangle |
| `group_container` | grouping frame | dashed rectangle with optional title |
| `dashed_region` | visible dashed annotation/evaluation frame | dashed rectangle container without process semantics |
| `loss_region` | compact GAN/TFR dashed loss/evaluation subsystem | editable dashed frame, title, and math-text formulas |
| `audit_region` | invisible logical review region for figures without visible frames | invisible rectangle used by validators/audit only |
| `text_pill` | small category/status label | pill |
| `ellipse_node` | oval/sum/add node | oval |
| `polygon_node` | arbitrary paper polygon fallback | editable Visio polyline/polygon where supported |
| `trapezoid_node` | quality heads, extractor wedges, directional paper blocks | editable trapezoid/triangle polygon |
| `cuboid_node` | 3D feature/impact-factor block | editable front face plus top/side faces |
| `modality_spine` | vertical shared-response or availability-mask bus with repeated side ports | editable spine rectangle plus port boxes |
| `math_vector` | compact formula/vector annotation such as `q=[q_RGB,q_IR,q_SAR]^T` | editable prefix text, bracket strokes, and entry text |
| `math_text` | short inline math labels such as GAN `L_adv` / `L_rec` losses | editable text fragments with smaller lowered subscript fragments |
| `math_formula_group` | structured formulas with visible fraction bars, such as `ω = numerator / denominator` | editable prefix/operator/fraction text plus a stable fraction bar |
| `tfr_panel` | Real/Generated/Reconstructed TFR paper module | editable rounded panel with title, subtitle, grid, input label, and optional internal arrow |
| `operator_node` | plus/multiply/tensor/add gate or explicit operator | editable oval with symbol text |
| `boundary_port` | module-frame input/output anchor | small visible/invisible port |
| `boundary_fanout` | parallel arrows emitted from a container boundary | editable line segments with arrowheads |
| `wave_signal` | waveform or signal snippet | editable polyline segments |
| `classifier_head` | AvgPool/Linear/output fan-out ending | editable composite blocks and lines |
| `text_block` | free text label, including rotated paper labels | invisible text box |
| `grid_matrix` | regular paper-style matrix/grid figure | editable cells plus grid lines |
| `bracket` | side grouping bracket or U-shaped paper marker | editable line segments |
| `dimension_brace` | TeX-like stretch dimension/grouping brace beside stacks, matrices, or columns | editable Bezier path with long stems and a small waist pinch |
| `junction_point` | tiny merge/fan anchor for many-to-one routing | tiny oval, usually invisible |
| `image_tile` | embedded secondary raster tile | imported image |
| `legend_block` | legend/annotation block | rectangle |

## Supported Edge Types

| Type | Meaning | V1 renderer |
| --- | --- | --- |
| `arrow_connector` | directional relation | straight line with arrow |
| `dynamic_connector` | routed relation | same renderer as arrow connector, with route support |
| `lane_arrow` | short horizontal/vertical paper-flow lane | forced-axis straight arrow with stricter validation |
| `rounded_orthogonal_connector` | orthogonal connector with rounded 90-degree bends | sampled quarter-arc path with final arrowhead |
| `curved_arrow` | smooth curved relation or cycle segment | one continuous editable path with arrowhead |
| `loop_arrow` | outer training/update loop arrow | one continuous editable path with tangent arrowhead |
| `dashed_feedback_path` | dashed loss/backprop/training feedback path | one continuous dashed path with final arrowhead |
| `line_segment` | visual line/stub/bus segment without semantic arrow target | straight line without arrow |
| `join_connector` | source leg into a merge junction/bus, normally no arrowhead | routed line without arrow |
| `fork_connector` | branch out of a fan junction/bus, normally arrowed | routed line with arrow |
| `boundary_arrow` | arrow emitted by a group/frame boundary | forced-axis routed arrow |
| `residual_connector` | skip/residual loop relation | routed arrow, normally with explicit points |
| `residual_loop` | alias-style residual/skip loop relation | routed arrow, normally with explicit points |

## Strict Arrow Templates

For strict replicas, choose the source arrow template before choosing the edge type. The template is recorded in `metadata.arrow_plan[].arrow_template` and checked by `scripts/arrow_audit_gate.py --strict`.

| Template | Source grammar | Preferred scene expression |
| --- | --- | --- |
| `straight_flow` | straight horizontal flow with one arrowhead | `arrow_connector` / `lane_arrow` with side-ratio endpoints |
| `vertical_flow` | straight vertical flow with one arrowhead | `lane_arrow` / `arrow_connector` with top/bottom side-ratio endpoints |
| `orthogonal_flow` | right-angle routed flow with one arrowhead | `arrow_connector` or `boundary_arrow` with explicit `hv`/`vh`/`orthogonal` route |
| `rounded_orthogonal_flow` | orthogonal route with rounded corners | `rounded_orthogonal_connector` with explicit corner radius |
| `bezier_arc` | paper/architecture arc with one arrowhead | `curved_arrow` with `curve_mode: "bezier"` and explicit control points |
| `fanout_arc` / `branch_arc` | curved source-visible fork branch | `curved_arrow` with `curve_mode: "bezier"`, `arc_template`, source/target tangents, and branch spread |
| `skip_arc_no_arrow` | curved skip relation without arrowhead | `curved_arrow` with `end_arrow: "none"` and deterministic arc/control points |
| `orthogonal_bus_no_arrow` | shared trunk/bus/skip line without arrowhead | `line_segment`, `join_connector`, or arrowless orthogonal route |
| `feedback_path` | dashed return/backprop path | `dashed_feedback_path` or arrowless bus legs plus one final feedback arrow |
| `feedback_loop` | visible cycle/update loop | one `loop_arrow` or source-justified Bezier loop, not fragments |
| `boundary_flow` | flow entering/leaving a frame boundary | `boundary_port` plus `boundary_arrow` or source-like side-ratio route |

Do not use a generic smooth curve for ordinary paper arcs. `curve_mode: "smooth"` / Catmull-Rom is for waveform, decorative, hand-drawn, organic, or explicitly freeform source curves. A normal skip arc should be a Bezier/arc template so the arrowhead tangent and endpoint relation stay stable.

When the source arc is a standard paper/architecture arc and exact control points are not yet measured, set `curve_mode: "bezier"` and an edge-level `arc_template`: `upper_arc`, `lower_arc`, `left_bulge`, `right_bulge`, `fanout_upper`, `fanout_lower`, `branch_upper`, `branch_lower`, or `small_bend_in`. Optional `arc_lift_in` controls how far the arc bulges outside the endpoints; `source_tangent_in` and `target_tangent_in` preserve visible clearance as the line leaves/enters a module; `branch_spread_in` / `fanout_spread_in` keep fork branches soft instead of rigid. This is deliberately different from `curve_mode: "smooth"`: the route semantics stay deterministic and the arrowhead remains tangent to the final Bezier segment.

Do not let defaults decide whether a line has an arrowhead. If the source is arrowless, set `arrowhead_policy: "none"` in the plan and `begin_arrow: "none"`, `end_arrow: "none"` in the rendered edge style. If the source has one terminal arrowhead, set `arrowhead_policy: "end_only"` and verify only the final segment has the arrowhead.

## Why The Vocabulary Is Small

This is deliberate:
- localized Visio stencil names are messy
- early overfitting to master names will make the system fragile
- most flowchart reconstruction work only needs a limited component family

## Component Selection Decision Tree

Components are rendering grammar, not recognition conclusions. Source visual facts decide component parameters.

Use this order:

1. Inventory the source visual facts first: shape family, cell count/gap/rounding, line style, symbol internals, wave samples, text role.
2. If the unit is just repeated rectangles/circles/lines/polylines or a thick filled arrow, use a primitive (`cell_strip`, `micro_grid`, `polyline_wave`, `ribbon_arrow`, `curved_ribbon_arrow`, `loop_ribbon_arrow`, `symbol_group`, `shape_cluster`, or `primitive_group`) instead of inventing a business component.
3. Use a higher-level component only when its parameters can preserve the recorded facts.
4. If a component would change the facts, such as rectangular cells becoming rounded tokens, a noisy source wave becoming a sine wave, or icon-internal lines becoming flow arrows, fail that component choice and switch to a primitive.
5. Mark icon/symbol internals with `subshape_role` or `edge_role: "symbol_internal"` / `"icon_internal"` / `"decorative_internal"` so topology audit does not treat them as main flow connectors.

## Future Upgrade Path

The current renderer strategy is:

`scene type -> Visio master when useful, otherwise controlled primitive geometry`

Later we can extend it to:

`scene type -> locale-aware Visio master map -> drop master -> glue connectors`

That future change should not require a schema rewrite if node and edge types remain stable.

## Styling Guidance

Keep defaults restrained:
- white background
- dark neutral strokes
- limited accent colors
- moderate line weight
- clean typography

Use `paper_white` for paper figures and `clean_white` for polished product/process diagrams.

Typography is part of component fidelity. For exact replicas, identify the source's visible font families or at least their roles:

- `paper_serif`: Times/Cambria/Georgia-like academic labels.
- `ui_sans`: Calibri/Arial/Segoe-like product or software labels.
- `math`: Cambria Math/Times-like formulas and operator symbols.
- `cjk_sans` / `cjk_serif`: Chinese labels that need stable glyph metrics.
- `mono`: code-like labels.

Use `font_family_candidates` when the exact font is uncertain or not installed. Use `source_font_family` when the source font is known; if that font is available but the scene resolves to a different family, `scene_audit.py` flags it. Check local availability with:

```powershell
python scripts/font_inventory.py --check "Times New Roman" --check "Calibri" --check "Cambria Math"
```

For exact replicas, prefer explicit `points` and `route` fields over manually nudging node boxes until arrows look right.

Use `cell_strip` when the source has a row/column of rectangular cells. Set `cell_count` or `rows`/`cols`, `cell_gap_in`, `cell_rounding_in`, and `must_match_facts`. Low-rounding source cells should use `cell_rounding_in` near zero; do not reuse token-grid defaults.

Use `micro_grid` when the source has a compact matrix/tensor tile with thin rectangular cells. Use `grid_matrix` for larger semantic matrices; use `micro_grid` for local icon-scale or tensor-scale grids where exact cell grammar matters.

Use `polyline_wave` for source-specific waveforms and signal silhouettes. Provide explicit `points` or `samples`; do not use a generic sine fallback in exact replica scenes.

Use `ribbon_arrow` / `curved_ribbon_arrow` / `loop_ribbon_arrow` when the source arrow is a filled or very thick graphic. Ordinary connectors are for thin lines; they should not replace broad qualitative-change arrows, infographic bands, or loop arrows that visually sit behind labels. Put broad arrows on `layer: "arrow_under_text"` unless the source places them above text.

For strict dense paper figures, calibrate arrow families before authoring nodes. `metadata.style_calibration.forward_arrow` controls filled/solid ribbon arrows, while `metadata.style_calibration.feedback_arrow` controls dashed or backprop arrows. Do not let dashed feedback arrows inherit filled-arrow body widths, large arrowheads, or sparse dash rhythms unless the source visibly shows that scale. Legend arrow samples should use `metadata.style_calibration.legend.inner_arrow_scale` instead of copying main-diagram arrow dimensions.

Use `symbol_group`, `shape_cluster`, or `primitive_group` for composed symbols and small local structures. Provide `subshapes` when the built-in `symbol_kind` is not enough. Subshape `bbox` values are local `[x, y, w, h]` values relative to the parent bbox when between 0 and 1.

For merge/fan connectors, do not draw several arrows directly into the same box edge when the source has a visible shared trunk. Add a `junction_point` at the merge/fan position, route source arrows into that point without arrowheads, then route one final arrow to the destination.

For paper module figures, use `join_connector` for the no-arrow legs into the merge point and `fork_connector` for arrowed fan-out branches. Use `operator_node` when the source has a visible `+`, multiply, or tensor operator; do not replace that symbol with a generic ellipse or plain text.

`operator_node` is a dedicated circle-plus-symbol renderer. Put the operator in `symbol` or `text` on the same node; do not layer a separate `text_block` over an ellipse, because small baseline differences can push `×` or `⊗` outside the circle.

For arrows that enter or leave a dashed module frame, add `boundary_port` nodes on the frame edge. This prevents connector endpoints from drifting to the group box center and makes source-like horizontal stubs possible.

When an arrow should run horizontally from a frame boundary to a target component whose center is at a different height, use a side-ratio endpoint such as `feature_map:left@0.58`. Do not connect boundary ports to default component centers if the source shows a straight horizontal lane.

Use `boundary_arrow` when the visible source arrow starts at the dashed frame edge. Do not add an internal `line_segment` from the previous component to the frame unless that line is actually visible in the source. This prevents false long arrows that appear to originate from a vector strip or internal block.

For classifier outputs, distinguish two grammars:
- If arrows start after `Linear` from a shared internal trunk, use `classifier_head` with explicit `fanout_count`.
- If arrows start from the dashed classifier boundary, set `classifier_head.output_mode: "boundary"` or omit fanout fields, then use `boundary_fanout` on the frame edge.
- If `AvgPool` sits above `Linear`, set `classifier_head.orientation: "vertical"` so the internal arrow is drawn with a visible short shaft and a small arrowhead.

For short internal arrows, use `arrow_size: "small"` on normal edges and `internal_arrow_size: "tiny"` inside vertical classifiers. Visio's default arrowhead is too large for compact paper-module gaps and can look like a standalone triangle.

For waveform input strips and classifier endings, use `wave_signal`, `classifier_head`, and `boundary_fanout` before falling back to raster tiles. These components cover common paper-figure grammar while keeping the result editable.

For input modality brackets and paper-side grouping marks, use `bracket` instead of skinny rectangles. If the bracket has a middle merge arm, set `tick_positions: [0, 0.5, 1]`.

For source-visible dimension braces beside matrices, vertical stacks, tensors, timelines, or grouped rows/columns, use `dimension_brace` or `bracket` with `shape: "paper_curly"`. Use this when the brace is a thin single-sided range marker with no incoming merge lines: the source usually looks like a TeX stretch delimiter with short curled terminals, long near-vertical stems, and a small center waist pinch. Use `brace_merge` only when the brace has many-to-one fusion/aggregation semantics, and use `bracket` for square/U-shaped brackets.

For multimodal pipeline figures, preserve the visible lane grammar:
- Use `image_tile` for source RGB/IR/SAR thumbnails when exact image content matters.
- Use `text_pill` or small `process_box` nodes for `1 or 0` availability flags.
- Use `modality_spine` for the shared vertical gray availability/response bar and encode side ports with `ports`.
- Use explicit horizontal connectors from each modality lane into the projection/fusion module instead of diagonal center-to-center edges.
- Use `lane_arrow` for short local lanes such as cuboid feature blocks into an extractor, `GAP -> GMP`, and feature maps into aggregation. Do not use `route: "straight"` with slightly different y values; it will render as a visibly tilted arrow.

Use `rounded_orthogonal_connector` for source connectors that are visibly axis-aligned but have rounded 90-degree corners. Set `route: "rounded_orthogonal"`, `orthogonalize_points: true`, and `corner_radius_in` or `corner_radius_px`. Do not replace these with `curved_arrow`/`loop_arrow` or `curve_mode: "smooth"`; smooth curves globally bend the lane and can turn an intended right-angle route into a wavy connector.

Use `math_vector` for formula blocks with brackets and stacked entries, especially `q = [q_RGB, q_IR, q_SAR]^T` after a `Quality Head`. Do not rely on Unicode bracket glyphs inside a normal `text_block`; line height and font fallback vary and the bracket/entry alignment often drifts in Visio exports.

Use `math_text` for loss labels such as `Adversarial Loss L_adv`, `Reconstruction Loss L_rec`, and similar inline formulas. Normalize compact spellings (`Ladv`, `Lrec`, `L adv`, `L rec`) to `L_adv` / `L_rec` before rendering. Raw or compact loss notation inside `text_block` is acceptable for rough drafts but is a rebuild issue for exact paper replicas because it visibly differs from math subscript notation.

Use `loop_arrow` or `curved_arrow` for outer GAN/training cycle arrows. A visible loop should be one continuous path with `points`, `end_tangent_point`, and its own arrowhead. For outer update loops, prefer `loop_arrow` with `curve_mode: "smooth"`, `semantic_role: "outer_update_loop"`, and `label_id`/`loop_label_id` bound to the bottom update label. Do not split the loop into several `line_segment` arcs and then draw detached `arrow_connector` heads; that is what makes curves look broken and reverses arrow direction.

Use `tfr_panel` for Real/Generated/Reconstructed TFR panels in GAN-style diagrams. It prevents a common first-pass failure where the panel is split into a background box, floating title labels, grid cells, `Input` text, and a separate internal arrow; that split makes feedback routes cross labels and makes paired grids drift. Use separate child nodes only when the source panel has unusual, independently routed internals.

Use `loss_region` for compact dashed adversarial/evaluation frames where the title and formulas belong to one subsystem. It is the preferred first-pass component for `Forward Reconstruction -> Discriminator Evaluation` plus `L_adv` / `GP` content. Keep the title inside the frame or in a protected header cutout; never let the dashed border run through the title. Use a plain `dashed_region` plus separate `math_text` children only when the source has multiple independently placed items inside the frame.

Use `dashed_region` for dashed annotation rectangles that do not have loss/evaluation semantics. Keep it as a frame, not a generic process node.

Use `dashed_feedback_path` for dashed reconstruction/adversarial/backpropagation paths. Keep these paths orthogonal with explicit points unless the source truly shows a diagonal dashed callout. Do not use `allow_diagonal: true` to hide a wrong dashed route. Do not let these paths draw through the interior of a dashed evaluation frame; route from a boundary point/`boundary_port` and keep the frame clean.

For `loss_region -> target` connections where the target sits directly below/above and horizontally overlaps the loss frame, use short vertical stubs into `target:top@ratio`/`target:bottom@ratio`. Avoid mirrored corner-to-side L-routes; they visually create a second dashed frame and extra arrow around the target.

For GAN/TFR diagrams, generated/reconstructed TFR normally flows into the Discriminator. A main arrow from `Discriminator -> Generated` is usually reversed and should be rebuilt unless the source explicitly labels it as discriminator output.

For bottom loss/backprop systems with several vertical dashed arrows into the same discriminator, use a visible or invisible `merge_bus`/`junction_point` and give related paths a `bundle_id`. This is more stable than drawing several unrelated vertical arrows that crowd the loss text.

Feedback arrows should not terminate at Real/Generated TFR input panels. Panel-to-backprop-bus legs are usually arrowless dashed legs; the arrowheads belong on the discriminator-facing stubs or on the final feedback target.

For Real/Generated TFR panels, keep paired `grid_matrix` nodes on the same y-position with matching size, rows, columns, and cell palette. Keep a clear gap above the `Input` label so arrows, grid, and label do not occupy one strip.

For GAN/TFR first-pass generation, prefer the bundled template and recipe before hand-authoring from scratch:

```powershell
python scripts/image_to_scene.py --image <source.png> --template gan-tfr --output <scene.json>
python scripts/scene_autofix.py <scene.json> --recipe gan-tfr --output <fixed.scene.json>
```

The template expresses the expected topology with `tfr_panel`, `loss_region`, `math_text`, `loop_arrow`, `dashed_feedback_path`, and a bundled backprop bus. The recipe upgrades legacy scenes that used loose panels, empty dashed boxes, raw underscore formulas, reversed discriminator arrows, or detached loop arrowheads.

Run `scripts/scene_audit.py <scene.json> --fail-on-rebuild` after each exact-replica render. A `[REBUILD]` item is not a styling suggestion; it means the local grammar is wrong and coordinate nudging should stop until the subsystem is redrawn.

`scripts/scene_to_visio.py` runs the GAN/TFR autofix once before the rebuild gate and writes `<basename>.autofixed.scene.json` when it changes local grammar. It then runs the rebuild gate automatically for exact-replica and GAN/TFR scenes. Use `--no-autofix` or `--skip-rebuild-gate` only for debugging a known-bad scene; do not use either for delivery.

Use `page_background` when you need to force Visio PNG export to keep the intended canvas. Do not use a blank white `process_box` for this purpose, because it behaves like a real process node and creates false route-intersection warnings.

Use `cuboid_node` for paper blocks that visually show depth, such as modality-related impact factors or tensor-like feature blocks. This keeps the front face editable while preserving the 3D cue with top and side faces. Do not replace these with flat rounded rectangles when the depth cue carries meaning in the source.

Use `trapezoid_node` for directional processing heads and wedge modules, such as `Quality Head`, `Environment Response extractor`, and `Aggregation Quality-aware`. Set `orientation` to the direction of flow. Set `pointed: true` when the source block is triangular or nearly triangular.

When speed requires a small raster tile for a hard wedge/hourglass, record it as a fidelity tradeoff. The audit script flags likely wedge tiles such as `quality_head`, `environment_extractor`, and `aggregation_quality` so they can be replaced with editable primitives later.

Use `polygon_node` as an escape hatch for unusual paper geometry, such as hourglass encoders or asymmetric wedges. Prefer semantic components first; generic polygons should not become the default for ordinary boxes.

`group_container` should not be used as a connector endpoint. It represents a visual frame around a region only. If a figure needs a callout from a framed area, place a small `junction_point` on the desired border and connect to that.

`group_container` titles render as a small top label, not centered text. This keeps dashed module frames from covering internal arrows and blocks. Use `shape: "capsule"` or `shape: "rounded"` when the source has rounded dashed frames.

If the source has no visible module frames, use `audit_region` around logical areas instead of inventing dashed boxes. `audit_region` does not render, but it gives `scene_audit.py` a module boundary for child counts, incoming/outgoing edges, and topology review.

For cross-container flow, split the route:

`source node -> source boundary_anchor -> target boundary_anchor -> target node`

Set `allow_cross_container: true` only on the boundary-anchor bridge. This prevents arrows from visually leaking through dashed module frames.

For dense mini-flow diagrams, use `hv`/`vh` routes or explicit axis-aligned points. A connector must not pass through a non-endpoint node; route it around the node or move it into a bus lane.

For stacked feature maps or repeated blocks, use `stacked_process`. Do not model each offset layer as a separate node unless each layer has separate meaning; otherwise the validator will correctly treat connectors crossing hidden layers as topology defects.

For standalone stubs like a horizontal line from `Contact` toward `AvgPool` that should not visibly point into the `AvgPool` component, use `line_segment` with `from_point` and `to_point`. Use `arrow_connector` only when the source figure clearly has a directional arrowhead or terminates on a shape.

For module interiors such as AM-ResNet, add alignment metadata:
- `align_to_container: ["center_y"]` when a child should sit on the parent frame's midline.
- `align_group` plus `align_axis: "center_y"` when several internal components must share a row.

For exact replicas, set `metadata.fidelity: "exact"` and preserve the source aspect ratio before editing node coordinates. A scene that passes structural validation can still fail as a replica if it uses a tall canvas, random feature-map colors, generic CNN rectangles, or arrows that only satisfy graph semantics instead of the source's visible line grammar.

For exact replicas, prefer pixel-coordinate scenes. Set `page.units: "px"` with the source image dimensions and `target_width_in`; this keeps positions traceable to the source image and avoids drift caused by manual inch estimates.

For large exact replicas, start with a region plan instead of a full-page node list. Use `metadata.region_strategy: "region_first"` or `"tiled_subscenes"`, then add `group_container` and `audit_region` boxes before detailed node authoring. Every meaningful node should have `container_id`; this lets `scene_complexity.py`, `scene_validate.py`, and `scene_audit.py` catch drift, dense regions, uncovered nodes, text-fit problems, and cross-region arrows before Visio rendering.

Keep typography role-based in large scenes. Use a small font scale for frame titles, body labels, small labels, operators, formulas, and edge labels. If validation reports same-type font spread, normalize style tokens before moving nodes around; otherwise visual cleanup becomes fragile and local fixes can make neighboring regions worse.

For AM-ResNet features and similar paper heatmaps, use `feature_map_grid` rather than `feature_map_banded` overlays. Encode row colors and `column_shades` so dark vertical regions blend with the underlying row palette. Do not use opaque black overlays unless the source column is actually solid black.

Visio masters are useful but local. Use `scripts/enumerate_visio_masters.py` to inspect the installed master names on the current machine, then map only the few masters needed for the figure. Do not treat a master dump as a portable schema: stencil names differ by Office version, language, and installed templates.

Do not push chart junk or decorative gradient effects into the schema. The scene should encode structure first and style second.
