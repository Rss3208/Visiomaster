# Scene Schema

## Purpose

`scene.json` is the intermediate semantic format between image analysis and Visio rendering.

The format is intentionally small. It should describe structure, layout, style, and references without exposing Visio COM details directly.

## Coordinate Rules

- Units: inches by default
- Page origin: top-left
- Node `x` and `y`: top-left corner
- Node `w` and `h`: width and height
- Renderer is responsible for converting to Visio's bottom-left coordinate system

For exact replicas, author in source pixels instead of eyeballed inches:

```json
{
  "page": {
    "width": 1514,
    "height": 538,
    "units": "px",
    "origin": "top-left",
    "target_width_in": 13.333,
    "background": "#FFFFFF"
  }
}
```

The renderer scales all node coordinates, `from_point`, `to_point`, and edge `points` to inches. `target_height_in` is optional; if omitted it is calculated from the source aspect ratio.

## Top-Level Structure

```json
{
  "version": "0.1",
  "metadata": {},
  "page": {},
  "nodes": [],
  "edges": [],
  "assets": []
}
```

## `page`

Required fields:

```json
{
  "width": 13.333,
  "height": 7.5,
  "units": "in",
  "origin": "top-left",
  "background": "#FFFFFF"
}
```

## `metadata`

Recommended fields:

```json
{
  "title": "Radar Sorter Overview",
  "created_by": "visiomaster.image_to_scene",
  "style_profile": "paper_white",
  "fidelity": "exact",
  "source_image": "C:/path/source.png",
  "source_aspect_ratio": 2.817,
  "style_reference": "C:/path/style.jpg",
  "region_strategy": "region_first",
  "font_scale": {
    "frame_title": 15,
    "body": 12,
    "small_label": 9,
    "operator": 14,
    "formula": 11
  },
  "notes": [
    "Main structure should stay editable.",
    "Image tiles may remain raster when they are secondary."
  ]
}
```

For 1:1 replica tasks, set `fidelity` to `exact`, and provide either `source_image` or `source_aspect_ratio`. The validator compares the page aspect ratio against the source so a wide paper figure is not accidentally rebuilt on a taller canvas.

For large or dense figures, set `region_strategy` to one of:

- `region_first`: define every visible/invisible module as a region before detailed node authoring.
- `tiled_subscenes`: reconstruct source crops or local module scenes first, then convert their coordinates into the full page.
- `module_first`: build semantic modules first, then place them on the final canvas.

Use `font_scale` as a human-readable contract for consistent text sizing. The renderer does not require it, but `scene_validate.py` will warn when same-type nodes drift across a wide font range.

For exact replicas, add typography intent when the source uses distinctive fonts. `visiomaster` cannot guarantee that every machine has the same font, so scenes should record both the preferred source font and a role-based fallback:

```json
{
  "style": {
    "source_font_family": "Calibri",
    "font_family": "Calibri",
    "font_family_candidates": ["Calibri", "Arial", "Segoe UI"],
    "font_role": "ui_sans"
  }
}
```

Supported `font_role` values are `paper_serif`, `serif`, `ui_sans`, `sans`, `math`, `mono`, `cjk_sans`, and `cjk_serif`. The renderer resolves `font_family` / `font_family_candidates` against locally installed Windows fonts. If a requested font is missing, it picks a close role fallback; if `source_font_family` is installed but the scene resolves to a different font, `scene_audit.py` reports the mismatch.

## Large Figure Discipline

Large source images fail differently from small diagrams. The usual problem is not a missing Visio shape; it is global reasoning drift: a few nodes shift, one local font size changes, connectors cross a region boundary, and the whole figure still looks plausible at full scale.

Use this workflow when the scene has roughly 30+ visible nodes, 35+ edges, tiny paper labels, or a very wide aspect ratio:

1. Create the full page in source-pixel coordinates.
2. Add visible `group_container` and invisible `audit_region` boxes before authoring all details.
3. Assign `container_id` on every meaningful node.
4. Keep each region around 12-18 visible nodes when possible.
5. Freeze shared style tokens and font roles before merging region work.
6. Run `scripts/scene_complexity.py` before full Visio render.
7. Run `scripts/scene_audit.py` and review every region after assembly.

The complexity script reports uncovered nodes, dense regions, text-fit risks, same-type font spread, overlap risks, and validation warnings. Treat those warnings as layout defects before starting visual polish.

## `nodes`

Each node must contain:

```json
{
  "id": "node-id",
  "type": "process_box",
  "x": 1.0,
  "y": 1.2,
  "w": 2.4,
  "h": 0.9,
  "text": "Label"
}
```

Optional node fields:

```json
{
  "style": {
    "fill": "#FFFFFF",
    "line": "#111827",
    "line_weight_pt": 1.25,
    "text_color": "#111827",
    "font_family": "Times New Roman",
    "font_family_candidates": ["Times New Roman", "Cambria", "Georgia"],
    "font_role": "paper_serif",
    "source_font_family": "Times New Roman",
    "font_weight": "regular",
    "font_size_pt": 16,
    "line_dash": "solid",
    "rounding_in": 0.12,
    "angle_deg": 90,
    "text_angle_deg": 0
  },
  "asset_ref": "asset-id",
  "container_id": "optional-parent-container-id",
  "align_to_container": ["center_y"],
  "align_group": "row-1",
  "align_axis": "center_y",
  "align_tolerance_in": 0.05,
  "z": 10
}
```

Use alignment fields when reconstructing module boxes such as AM-ResNet. If a component should sit on the visual midline of its parent block, set `container_id` and `align_to_container: ["center_y"]`. If several sibling nodes should share one row, give them the same `align_group` and `align_axis`.

Supported node `type` values are defined in `templates/visio_components.json`.

### `page_background`

Use `page_background` only as a bottom-layer export helper when Visio would otherwise crop the exported PNG to the drawn shapes. It preserves the intended canvas ratio without acting as a flowchart node.

```json
{
  "id": "page_background",
  "type": "page_background",
  "x": 0,
  "y": 0,
  "w": 900,
  "h": 575,
  "z": -100
}
```

Do not use a white `process_box` as a fake background. Background nodes are ignored by route-intersection checks; fake process boxes pollute validation and audit output.

### `stacked_process`

Use `stacked_process` for repeated offset feature maps or stacked module blocks that behave as one semantic node.

```json
{
  "id": "rgb_backbone",
  "type": "stacked_process",
  "x": 3.8,
  "y": 2.2,
  "w": 0.64,
  "h": 0.76,
  "text": "Backbone",
  "layers": 4,
  "stack_dx_in": -0.045,
  "stack_dy_in": 0.035,
  "style": {
    "fill": "#8FB2E6",
    "line": "#3A6DA8",
    "rounding_in": 0.05
  }
}
```

Do not author each visible offset layer as an independent node unless each layer is separately connected or labeled. Use one `stacked_process` so connector validation sees one semantic target.

Use `stacked_token` for smaller token/vector stacks. It uses the same fields as `stacked_process`, but has tighter default spacing and smaller type.

### `notched_block`

Use `notched_block` for CNN-like modules with visible cutouts or teeth. It renders an editable base rectangle plus editable white notch shapes.

```json
{
  "id": "cnn",
  "type": "notched_block",
  "x": 320,
  "y": 290,
  "w": 120,
  "h": 190,
  "text": "CNN",
  "notches": [
    {"x": 0.52, "y": 0.30, "w": 0.36, "h": 0.16, "shape": "diamond"},
    {"x": 0.52, "y": 0.74, "w": 0.36, "h": 0.16, "shape": "diamond"}
  ]
}
```

### `feature_map_banded`

Use `feature_map_banded` for paper feature maps with horizontal stripes, vertical dark columns, or fixed color bands. Do not use random grids when the source has recognizable bands.

```json
{
  "id": "wav_features",
  "type": "feature_map_banded",
  "x": 650,
  "y": 360,
  "w": 150,
  "h": 60,
  "bands": [
    {"fill": "#B7DCEB", "size": 1},
    {"fill": "#F8E49B", "size": 1},
    {"fill": "#B7DCEB", "size": 1},
    {"fill": "#C9C0D8", "size": 1}
  ],
  "overlays": [
    {"x": 0.52, "y": 0, "w": 0.18, "h": 1, "fill": "#1E1E1E"}
  ]
}
```

### `feature_map_grid`

Use `feature_map_grid` for AM-ResNet features, heatmap-like feature maps, and small paper feature blocks where each vertical column preserves the row colors but has different brightness or transparency. This avoids the common failure where semi-transparent dark columns become opaque black bars.

```json
{
  "id": "am_resnet_features",
  "type": "feature_map_grid",
  "x": 5.80,
  "y": 1.80,
  "w": 1.55,
  "h": 0.86,
  "rows": 6,
  "cols": 9,
  "row_colors": [
    "#F2A66F",
    "#A8D7E5",
    "#C8D9C2",
    "#F3E889",
    "#9BC6D9",
    "#F2A66F"
  ],
  "column_shades": [0.0, 0.20, 0.0, 0.45, 0.70, 0.45, 0.0, 0.20, 0.0],
  "max_shade": 0.58,
  "show_column_lines": true,
  "show_row_lines": false
}
```

`column_shades` values are normalized from `0` to `1`; the renderer blends the row color toward `shade_color` instead of laying an opaque black rectangle over the feature map. Use `column_weights` if the source has uneven column widths.

### `polygon_node`

Use `polygon_node` as a controlled fallback for unusual paper shapes that are not rectangles, brackets, cuboids, feature maps, or standard trapezoids.

```json
{
  "id": "hourglass_left",
  "type": "polygon_node",
  "x": 1190,
  "y": 410,
  "w": 120,
  "h": 240,
  "points": [[0, 0], [1, 0.5], [0, 1]],
  "style": {
    "fill": "#B9CBEF",
    "line": "#4B5563"
  }
}
```

Points are local to the node. Values in `[-1, 1]` are treated as normalized node-relative coordinates; larger values are treated as absolute offsets in scene units. Prefer semantic components such as `trapezoid_node` or `cuboid_node` when they match the source.

### `trapezoid_node`

Use `trapezoid_node` for directional paper modules such as quality heads, extractor wedges, aggregation modules, or triangular arrow-like processors.

```json
{
  "id": "quality_head",
  "type": "trapezoid_node",
  "x": 980,
  "y": 160,
  "w": 130,
  "h": 190,
  "text": "Quality\nHead Qm",
  "orientation": "right",
  "taper_ratio": 0.22,
  "style": {
    "fill": "#D9D9D9",
    "line": "#333333",
    "font_size_pt": 12
  }
}
```

`orientation` accepts `left`, `right`, `up`, and `down`. Use `pointed: true` for triangular or nearly triangular blocks.

### `cuboid_node`

Use `cuboid_node` for 3D paper blocks where depth is part of the visual encoding, such as modality-related impact factors or tensor blocks.

```json
{
  "id": "impact_factor",
  "type": "cuboid_node",
  "x": 520,
  "y": 540,
  "w": 250,
  "h": 90,
  "text": "cm",
  "depth_x_in": 0.20,
  "depth_y_in": -0.18,
  "style": {
    "fill": "#B9DDA6",
    "side_fill": "#8FC36A",
    "top_fill": "#D9EFCF"
  }
}
```

The renderer creates editable front, top, and side faces. Keep the front face as the semantic endpoint for connectors.

### `modality_spine`

Use `modality_spine` for a vertical shared-response or availability-mask bar with repeated modality ports, as in RGB/IR/SAR availability pipelines.

```json
{
  "id": "availability_mask",
  "type": "modality_spine",
  "x": 360,
  "y": 150,
  "w": 34,
  "h": 500,
  "ports": [
    {"position": 0.08, "text": "P_RGB", "side": "center"},
    {"position": 0.50, "text": "P_IR", "side": "center"},
    {"position": 0.92, "text": "P_SAR", "side": "center"}
  ],
  "style": {
    "fill": "#C9C9C9",
    "port_fill": "#CFE8BE"
  }
}
```

`position` values in `[0, 1]` are normalized along the spine height; larger values are treated as scene-unit offsets from the spine top. Ports are part of the node, so route connectors to explicit side endpoints or separate `junction_point` anchors when individual ports need distinct topology.

### `math_vector`

Use `math_vector` for compact paper formulas such as `q = [q_RGB, q_IR, q_SAR]^T`. Do not build these with a plain multi-line `text_block` containing Unicode bracket glyphs; the line spacing and bracket alignment will drift across fonts and Visio versions.

```json
{
  "id": "q_vector",
  "type": "math_vector",
  "x": 1129,
  "y": 126,
  "w": 87,
  "h": 93,
  "prefix": "q =",
  "entries": ["q_RGB", "q_IR", "q_SAR"],
  "container_id": "panel_quality",
  "style": {
    "font_family": "Times New Roman",
    "font_size_pt": 10,
    "entry_font_size_pt": 10
  }
}
```

`math_vector` renders the optional prefix, bracket strokes, and entries as editable shapes/text. Tuning fields: `prefix_w`, `gap_in`, `bracket_w`, `bracket_tick_in`, `entry_font_size_pt`, `left_bracket`, and `right_bracket`.

### `math_text`

Use `math_text` for short inline formulas that need subscript-like notation but do not need a full vector bracket. This is the preferred component for GAN/TFR loss labels such as `L_adv` and `L_rec`.

```json
{
  "id": "adv_loss_text",
  "type": "math_text",
  "x": 356,
  "y": 222,
  "w": 205,
  "h": 48,
  "text": "Adversarial Loss L_adv\nGradient Penalty GP",
  "container_id": "adv_loss_box",
  "style": {
    "font_family": "Times New Roman",
    "font_size_pt": 14
  }
}
```

The renderer normalizes compact loss spellings such as `Ladv`, `Lrec`, `L adv`, and `L rec` to `L_adv` / `L_rec`, then splits patterns like `L_adv` into editable fragments (`L` plus smaller lowered `adv`). Tuning fields: `subscript_scale`, `subscript_offset_in`, `line_gap_in`, `segment_gap_in`, `fragment_pad_in`, `subscript_pad_in`, `subscript_box_pad_in`, and `padding_in`. For exact paper figures, compact or raw underscore loss notation inside a normal `text_block` should be treated as a local rebuild issue.

### `tfr_panel`

Use `tfr_panel` for Real/Generated/Reconstructed TFR blocks in GAN-style paper diagrams. It is a composite editable node: the rounded background, title, optional subtitle, internal grid, input label, and optional internal input arrow stay under one semantic component.

```json
{
  "id": "generated_panel",
  "type": "tfr_panel",
  "x": 630,
  "y": 238,
  "w": 168,
  "h": 177,
  "title": "Generated",
  "subtitle": "Reconstructed TFR",
  "input_label": "Input",
  "rows": 4,
  "cols": 5,
  "grid_y": 306,
  "input_y": 389,
  "input_arrow": true,
  "style": {
    "fill": "#C4D8FA",
    "title_font_size_pt": 20,
    "subtitle_font_size_pt": 14,
    "input_font_size_pt": 18
  }
}
```

Prefer `tfr_panel` over a loose group of `rounded_process` + title `text_block` + `grid_matrix` + `Input` label. The loose form is fragile: feedback arrows often cross the `Input` label, internal arrows become external topology, and paired Real/Generated grids drift apart.

For pixel-coordinate exact replicas, `grid_x`, `grid_y`, `grid_w`, `grid_h`, and `input_y` are scaled with the page. This keeps the internal grid from drifting when `page.units` is `px`.

Use `colored_cells` when the source cell colors are meaningful. If omitted, the renderer uses a restrained pink/blue default palette suitable for GAN/TFR examples.

### `merge_bus`

Use `merge_bus` for visible bus/spine merges or fan-in/fan-out trunks. It is a visible topology component, unlike invisible `junction_point`.

```json
{
  "id": "concat_bus",
  "type": "merge_bus",
  "x": 980,
  "y": 250,
  "w": 40,
  "h": 80,
  "orientation": "vertical",
  "side": "left",
  "port_positions": [0, 1],
  "port_length_in": 0.16
}
```

`group_container` labels are rendered as top labels by default. Optional title controls:

```json
{
  "shape": "capsule",
  "corner_radius_in": 0.38,
  "max_rounding_in": 0.45,
  "title_align": 0,
  "title_pad_x_in": 0.08,
  "title_pad_y_in": 0.02,
  "title_font_size_pt": 13
}
```

Use `shape: "capsule"` or `shape: "rounded"` when the source has paper-style rounded dashed frames. Keep plain rectangles only when the source frame is visibly square.

### `dashed_region`

Use `dashed_region` for visible dashed annotation frames, such as the loss/evaluation box in GAN training diagrams. It renders like a visible container but is semantically different from an ordinary `process_box`.

```json
{
  "id": "forward_loss_region",
  "type": "dashed_region",
  "x": 292,
  "y": 210,
  "w": 297,
  "h": 90
}
```

Keep the title as a separate `text_block` and formulas as `math_text` nodes inside the region. Do not use an empty dashed `process_box` as a fake frame. If a dashed path leaves the region, use `dashed_feedback_path` with explicit points, and set `allow_cross_container: true` only when the visible source path deliberately crosses that logical boundary.

Do not route `dashed_feedback_path` segments through the interior of the dashed frame unless the source visibly shows an internal dashed path. For GAN evaluation boxes, the usual pattern is: clean `dashed_region` frame, internal `math_text`, then a boundary point/`boundary_port` where feedback exits.

### `loss_region`

Use `loss_region` when a dashed GAN/TFR evaluation frame, its title, and its formulas form one local subsystem. It renders the dashed frame, title, and formula lines as editable Visio shapes while keeping the node as one semantic region for validation and audit.

```json
{
  "id": "adv_loss_region",
  "type": "loss_region",
  "x": 305,
  "y": 211,
  "w": 286,
  "h": 72,
  "title": "Forward Reconstruction -> Discriminator Evaluation",
  "formulas": [
    "Adversarial Loss L_adv",
    "Gradient Penalty GP"
  ],
  "style": {
    "line": "#6F6F6F",
    "line_dash": "dash",
    "font_size_pt": 14,
    "title_font_size_pt": 16
  }
}
```

Use `loss_region` as the first-pass component for compact adversarial/evaluation boxes. The default title layout is inside the frame so the dashed border cannot cut through long captions. Use a header cutout only when the source visibly places the title on the frame line and leave enough white fill behind the title. Use `dashed_region` plus separate child nodes only when the source has unusual title placement or multiple independent internal items that must be routed separately.

### `audit_region`

Use `audit_region` for figures that have no visible dashed modules but still need module-level review. It behaves like an invisible container: it does not render a frame or label, but `scene_validate.py` and `scene_audit.py` use it to group child nodes and edges.

```json
{
  "id": "residual_block_1",
  "type": "audit_region",
  "x": 0.80,
  "y": 1.10,
  "w": 3.20,
  "h": 1.70,
  "label": "Residual block 1"
}
```

Use this when the source visually contains a logical block such as residual network, attention, classifier, feature extraction chain, or repeated BN/R/M/C sequence, but no visible boundary is drawn. Do not connect edges to `audit_region`; use normal component endpoints or `boundary_port` only when a visible boundary output exists.

### `legend_block`

Use `legend_block` for compact color/key explanations that should remain editable. It draws a frame plus editable swatches and labels from `items`:

```json
{
  "id": "legend",
  "type": "legend_block",
  "x": 0.6,
  "y": 6.8,
  "w": 4.8,
  "h": 0.8,
  "items": [
    {"label": "Planning", "color": "#219653"},
    {"label": "Simulation", "color": "#F2994A"}
  ]
}
```

Optional layout controls include `columns`, `padding_x_in`, `padding_y_in`, `swatch_size_in`, `label_gap_in`, and `item_gap_in`.

### `operator_node`

Use `operator_node` for explicit paper-figure operators such as plus, multiply, tensor product, add, concat markers, or attention gates. Do not fake these as text floating over a connector.

```json
{
  "id": "residual_add",
  "type": "operator_node",
  "x": 6.10,
  "y": 2.42,
  "w": 0.22,
  "h": 0.22,
  "symbol": "⊗"
}
```

`operator_node` renders the circle and the symbol as a controlled pair, with the symbol centered in the circle. Prefer `symbol` over a separate `text_block`. Keep `w` and `h` equal for exact replicas. Optional tuning fields: `symbol_font_size_pt`, `symbol_font_family`, `symbol_offset_x_in`, `symbol_offset_y_in`, and `symbol_inset_in`.

### `boundary_port`

Use `boundary_port` for module-frame entry/exit anchors. This is the preferred fix when a connector should touch the dashed frame boundary without connecting to the `group_container` itself.

```json
{
  "id": "am_resnet_out",
  "type": "boundary_port",
  "container_id": "am_resnet",
  "side": "right",
  "shape": "none",
  "x": 7.52,
  "y": 2.95,
  "w": 0.04,
  "h": 0.04
}
```

Set `shape` to `circle`, `square`, `tick`, or `none`. Use `visible: false` or `shape: "none"` for an invisible but editable routing anchor.

### `wave_signal`

Use `wave_signal` for waveform inputs or signal snippets. It renders as editable line segments inside the node box.

```json
{
  "id": "audio_wave",
  "type": "wave_signal",
  "x": 0.55,
  "y": 2.20,
  "w": 1.20,
  "h": 0.42,
  "cycles": 3,
  "point_count": 64
}
```

For source-faithful waveform shapes, provide normalized `samples` in `[-1, 1]`.

### `classifier_head`

Use `classifier_head` for common paper endings such as `AvgPool -> Linear`. It is a compact editable composite; for 1:1 replicas with unusual spacing, you can still break it into separate `process_box`, `junction_point`, and connector nodes.

Do not let `classifier_head` draw internal fan-out when the source shows arrows starting on the dashed classifier frame. In that case set `output_mode: "boundary"` or omit `fanout_count`, then add a `boundary_fanout` node on the frame's right side.

```json
{
  "id": "cls_head",
  "type": "classifier_head",
  "x": 10.45,
  "y": 2.15,
  "w": 1.85,
  "h": 0.95,
  "labels": ["AvgPool", "Linear"],
  "orientation": "vertical",
  "vertical_block_gap_in": 0.18,
  "internal_arrow_size": "tiny",
  "output_mode": "boundary"
}
```

Use `fanout_count` and `output_labels` only when the source truly has a shared internal branch after the last classifier block.

For vertical classifier blocks, use `orientation: "vertical"` so the renderer creates a visible short shaft between `AvgPool` and `Linear`. Do not model this with an extremely short generic edge; Visio arrowheads can consume the whole line segment if the arrow size is not reduced. Use `internal_arrow_size: "tiny"` for compact paper figures.

### `boundary_fanout`

Use `boundary_fanout` when several arrows originate from a dashed container boundary, as in many paper classifier outputs. It draws parallel editable arrows from the frame edge outward, instead of inventing a central merge point after `Linear`.

```json
{
  "id": "classifier_outputs",
  "type": "boundary_fanout",
  "container_id": "classifier",
  "side": "right",
  "x": 12.28,
  "y": 2.05,
  "w": 0.62,
  "h": 1.70,
  "branch_positions": [0.08, 0.38, 0.68, 0.92],
  "labels": ["N", "S", "V", "F"]
}
```

For right-side output arrows, set `x` to the container's right boundary and `w` to the outward arrow length. `branch_positions` values in `[0, 1]` are normalized over `h`; larger values are treated as absolute offsets in scene units.

### `grid_matrix`

Use `grid_matrix` for convolution kernels, receptive fields, checkerboard masks, and paper figures with regular cells.

```json
{
  "id": "kernel_a",
  "type": "grid_matrix",
  "x": 1.0,
  "y": 0.8,
  "w": 2.3,
  "h": 2.3,
  "rows": 9,
  "cols": 9,
  "index_base": 0,
  "colored_cells": [
    {"row": 2, "col": 2, "fill": "#2F7F91"},
    {"row": 4, "col": 4, "fill": "#F07A00"}
  ],
  "style": {
    "cell_fill": "#FFFFFF",
    "grid_line": "#000000",
    "grid_line_weight_pt": 1.0
  }
}
```

`colored_cells` also accepts compact entries: `[row, col, fill]`.

The renderer creates editable cell rectangles and separate grid lines inside Visio. Do not hand-place 81 small boxes when one `grid_matrix` can express the structure.

### `bracket`

Use `bracket` for modality grouping marks, braces, and paper-style side brackets. Do not fake these with ultra-thin `process_box` rectangles.

```json
{
  "id": "input_modalities_bracket",
  "type": "bracket",
  "x": 1.65,
  "y": 2.4,
  "w": 0.35,
  "h": 3.05,
  "orientation": "right",
  "tick_positions": [0, 0.5, 1],
  "style": {
    "line": "#333333",
    "line_weight_pt": 1.1
  }
}
```

`orientation` values:
- `right`: spine on the right edge, arms extend left; visually like `]`
- `left`: spine on the left edge, arms extend right; visually like `[`
- `down`: bottom spine, arms extend upward
- `up`: top spine, arms extend downward

Use `tick_positions` when the source bracket has a middle merge arm. Values are normalized from `0` to `1` along the bracket span. A left-side modality merge often needs `[0, 0.5, 1]`, not just `[0, 1]`.

### `junction_point`

Use `junction_point` for explicit 2-to-1, many-to-one, and fan-out routing. It is usually invisible and tiny, but gives connectors a semantic merge/fan point.

```json
{
  "id": "evidence_merge",
  "type": "junction_point",
  "x": 8.86,
  "y": 7.74,
  "w": 0.04,
  "h": 0.04,
  "role": "merge",
  "style": {
    "fill": "none",
    "line": "none"
  }
}
```

Pattern:

```json
[
  {"id": "rgb_to_merge", "type": "arrow_connector", "from": "z_rgb:right", "to": "evidence_merge:center", "style": {"end_arrow": "none"}},
  {"id": "ir_to_merge", "type": "arrow_connector", "from": "z_ir:right", "to": "evidence_merge:center", "style": {"end_arrow": "none"}},
  {"id": "merge_to_layer", "type": "arrow_connector", "from": "evidence_merge:center", "to": "evidence_layer:left"}
]
```

Do not connect arrows directly to `group_container`; containers are frames, not flow targets.

For cross-container connectors, place boundary anchors on the relevant frame edges:

```json
{
  "id": "feature_out_portal",
  "type": "junction_point",
  "role": "boundary_anchor",
  "container_id": "feature_container",
  "x": 7.60,
  "y": 2.68,
  "w": 0.03,
  "h": 0.03
}
```

Then split the connector into internal, bridge, and internal segments. Mark only the bridge segment with `allow_cross_container: true`.

## `edges`

Each edge must contain:

```json
{
  "id": "edge-id",
  "type": "arrow_connector",
  "from": "node-a",
  "to": "node-b"
}
```

For a purely visual line segment that should not snap to a component, use point endpoints:

```json
{
  "id": "contact_to_avgpool_stub",
  "type": "line_segment",
  "from_point": [4.10, 2.35],
  "to_point": [5.20, 2.35],
  "route": "straight",
  "style": {
    "end_arrow": "none"
  }
}
```

This is the correct representation when the source figure shows a horizontal line only, not an arrow pointing into `AvgPool`.

Optional edge fields:

```json
{
  "label": "Optional label",
  "allow_diagonal": false,
  "allow_cross_container": false,
  "style": {
    "line": "#64748B",
    "line_weight_pt": 1.25,
    "line_dash": "solid",
    "end_arrow": "triangle"
  },
  "z": 100
}
```

Edge labels are rendered as small editable text boxes with a white background and a slight default offset from the route midpoint. This prevents the connector from visually cutting through the label. For dense diagrams, prefer explicit `text_block` labels placed in free space when the default midpoint is not semantically clear.

Endpoint syntax currently supports:
- `node-id`
- `node-id:left`
- `node-id:right`
- `node-id:top`
- `node-id:bottom`
- `node-id:center`
- `node-id:left@0.62`
- `node-id:right@0.58`

If no side is given, the renderer auto-selects a side based on relative position.

Use `@ratio` side anchors when a line must hit a component edge at the same visual height as a boundary port or bus lane. For `left`/`right`, the ratio is vertical from top `0` to bottom `1`; for `top`/`bottom`, it is horizontal from left `0` to right `1`. This is the preferred way to keep a frame-to-feature-map arrow horizontal without moving the target component.

Point endpoint fields:
- `from_point`: `[x, y]`
- `to_point`: `[x, y]`

Point endpoints may be combined with node endpoints, for example from `contact:right` to a free `to_point`, or from a free `from_point` to `avgpool:left`. Use this only when the figure's geometry needs a free-floating segment or bus stub.

Routing fields:

```json
{
  "route": "auto",
  "points": [[1.2, 3.5], [7.4, 3.5]],
  "snap_tolerance_in": 0.2
}
```

`route` values:
- `auto`: snap nearly aligned endpoints and use right-angle routes for opposite sides
- `straight`: draw one direct segment
- `horizontal`: force a horizontal line from source x/y to target x at the source y
- `vertical`: force a vertical line from source x/y to target y at the source x
- `orthogonal`, `elbow`, `right_angle`: force right-angle routing
- `hv`, `horizontal_then_vertical`: horizontal segment first, then vertical
- `vh`, `vertical_then_horizontal`: vertical segment first, then horizontal

Use `join_connector` for source-to-merge legs that should reach a shared junction or bus without arrowheads. Use `fork_connector` for fan-out branches leaving a junction or bus. These edge types keep fan-in/fan-out topology explicit instead of drawing several unrelated arrows into one box edge.

Use `residual_connector` or `residual_loop` for skip/residual loops. They render like arrow connectors but signal that the route must preserve loop topology and should normally use explicit axis-aligned `points`.

Use `boundary_arrow` when the source arrow starts from a group/frame boundary rather than from the last internal component:

```json
{
  "id": "frame_to_features",
  "type": "boundary_arrow",
  "from": "module_out:center",
  "to": "features:left@0.58",
  "route": "horizontal",
  "allow_cross_container": true
}
```

Do not add an internal line from `vector:right` to `module_out:center` unless that internal line is visible in the source. The boundary arrow should usually be the only visible external output.

Use `lane_arrow` for short paper-flow lanes that should be perfectly horizontal or vertical, such as small cuboid blocks feeding an extractor, `GAP -> GMP`, or feature-map patches feeding aggregation:

```json
{
  "id": "grad_to_extractor",
  "type": "lane_arrow",
  "from_point": [882, 521],
  "to_point": [912, 521],
  "route": "horizontal",
  "lane_axis": "horizontal"
}
```

`lane_arrow` is intentionally stricter than `arrow_connector`. It is the preferred fix when a source lane should be axis-aligned but tiny endpoint differences would make `route: "straight"` render as a visibly tilted arrow. Do not silence these with `allow_diagonal: true`.

Use `loop_arrow` or `curved_arrow` for smooth outer loops and circular training cycles. These render as one continuous Visio path, so the curve does not break into separate segments and the arrowhead follows the path tangent:

```json
{
  "id": "outer_loop_to_latent",
  "type": "loop_arrow",
  "semantic_role": "outer_update_loop",
  "label_id": "alternating_updates",
  "from_point": [147, 481],
  "points": [[60, 410], [42, 215], [135, 80], [290, 28]],
  "end_tangent_point": [326, 24],
  "to_point": [348, 22],
  "curve_mode": "smooth",
  "style": {
    "line": "#6F6F6F",
    "line_weight_pt": 1.4
  }
}
```

Do not draw a curved loop as several `line_segment` edges plus detached short `arrow_connector` heads. That is the common cause of broken outer arrows and wrong arrow directions. Bind large outer loops to a semantic label (`label_id`/`loop_label_id`) so the path reads as "Alternating Updates" or similar process flow instead of page decoration.

Use `end_tangent_point` when the final arrowhead must enter a target smoothly. It is inserted between the final sampled loop point and the endpoint before smoothing/export. Use `start_tangent_point` for the same control at the beginning of a curved path. For outer update loops, `scene_audit.py --fail-on-rebuild` treats a missing `end_tangent_point` as a rebuild issue because the last arrowhead often looks kinked even when the rest of the ellipse is smooth.

Use `dashed_feedback_path` for training/loss/backpropagation paths. It renders the route as one dashed path with the arrowhead on the final segment:

```json
{
  "id": "left_backprop_to_disc",
  "type": "dashed_feedback_path",
  "from_point": [194, 415],
  "points": [[194, 492], [426, 492]],
  "to_point": [426, 368]
}
```

Keep feedback paths orthogonal unless the source visibly uses a diagonal dashed callout. Do not use `allow_diagonal: true` to silence loss/backprop arrows that should be horizontal/vertical.

Do not use short dashed `line_segment` arrows as feedback fragments. In GAN/TFR figures, dashed arrows should be semantic `dashed_feedback_path` routes or arrowless bus segments. An arrowhead on a tiny dashed line is usually the artifact that makes the discriminator look surrounded by an extra dashed box.

When a `loss_region` sits above a target such as `Discriminator` and the two boxes overlap horizontally, use short vertical stubs from the loss frame boundary to `target:top@ratio`:

```json
{
  "id": "adv_loss_to_disc_left",
  "type": "dashed_feedback_path",
  "from_point": [420, 266],
  "to": "discriminator:top@0.36",
  "route": "vertical"
}
```

Do not route this case from the loss frame corner to `target:left/right`; mirrored L-shaped paths read as an extra dashed box around the target.

For bottom loss/backprop systems with three or more parallel vertical arrows into the same discriminator/module, add a shared `merge_bus` or `junction_point` and give related paths a `bundle_id`. This keeps the feedback system visually grouped and prevents several independent dashed arrows from crowding the loss label.

GAN/TFR direction rule: generated/reconstructed TFR normally flows into the Discriminator for evaluation. If a main horizontal arrow runs from `Discriminator` to `Generated`, treat it as reversed unless the source explicitly labels it as discriminator output.

For exact GAN/training-loop replicas, run:

```powershell
python ${SKILL_DIR}\scripts\scene_audit.py <scene.json> --fail-on-rebuild
```

Any `[REBUILD]` item means the local grammar is wrong. Stop nudging coordinates and rebuild that subsystem before continuing.

For GAN/TFR figures, seed the scene from the first-pass template when possible:

```powershell
python ${SKILL_DIR}\scripts\image_to_scene.py --image <source.png> --template gan-tfr --output <scene.json>
```

For legacy or hand-authored GAN/TFR scenes, apply the deterministic grammar upgrade before rendering:

```powershell
python ${SKILL_DIR}\scripts\scene_autofix.py <scene.json> --recipe gan-tfr --output <fixed.scene.json>
```

The `gan-tfr` recipe compacts split TFR panels into `tfr_panel`, compacts dashed loss boxes into `loss_region`, converts raw loss formulas to `math_text`, smooths outer loops, fixes the common Generated/Discriminator direction error, and bundles crowded bottom backprop arrows.

`scene_to_visio.py` applies the same GAN/TFR recipe automatically before its rebuild gate unless `--no-autofix` is passed. If the renderer writes `<basename>.autofixed.scene.json`, validate and audit that file when debugging. This prevents a scene from bypassing semantic components with ordinary dashed connectors or compact loss text on the first export attempt.

Use `points` for exact paper-style residual paths, skip connections, and hand-tuned replicas.

Arrow sizing:

```json
{
  "style": {
    "arrow_size": "small"
  }
}
```

`arrow_size` accepts `tiny`, `small`, `medium`, `large`, or an integer code. The renderer also shrinks arrowheads on very short segments so small internal arrows remain a line plus a head instead of a head-only mark.

Routing quality rules:
- Do not use diagonal `straight` lines for flow connectors unless the source is a real callout; set `allow_diagonal: true` only for intentional callouts.
- For short horizontal/vertical paper lanes, use `lane_arrow` or forced `horizontal`/`vertical` routes. A `straight` edge with slightly mismatched endpoint y/x values will look visibly tilted.
- Do not force every line to terminate on a shape. If the source has a standalone horizontal or vertical stub, use `line_segment` with `from_point` and `to_point`.
- If an `orthogonal` edge has `points`, each adjacent point pair must share either `x` or `y`; otherwise the renderer will still draw a diagonal segment.
- Keep intra-module connectors inside their `group_container`.
- For connectors between modules, use `junction_point` with `role: boundary_anchor` at the frame edges and split the route. Do not let one long edge run through multiple dashed frames.
- If a route crosses a non-endpoint process node, move it to a bus lane or add explicit points around the node.

## `assets`

Assets are optional and mainly used by `image_tile` nodes.

```json
{
  "id": "asset-map",
  "kind": "image",
  "path": "C:/path/map.png"
}
```

## Example

See `templates/examples/basic_flow.scene.json` for a working starter file.
