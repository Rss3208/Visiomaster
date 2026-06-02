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

For exact replicas, also record a visual-LLM source inventory before the first scene render. This is not an OCR result, a template match, or a script-generated similarity record. It is the source-faithful contract that prevents the scene from drifting into a plausible semantic redraw.

```json
{
  "metadata": {
    "fidelity": "exact",
    "replica_review_mode": "strict_replica",
    "replica_stage": "layout_topology",
    "source_visual_inventory": {
      "analysis_basis": "visual_llm_source_image",
      "language_profile": "cjk_dominant",
      "do_not_translate": true,
      "unknown_text_policy": "mark_unreadable_do_not_invent",
      "scene_authoring_mode": "fresh_from_source_inventory",
      "prior_scene_policy": "do_not_read_or_patch_prior_round_scene",
      "regions": [
        {
          "id": "left_input",
          "source_bbox_px": [0, 40, 360, 500],
          "required_crop_types": ["input", "small_text"],
          "required_labels": ["输入特征", "Length"],
          "required_formulas": ["f_tf", "g_tf"],
          "required_component_motifs": ["colored token grid", "thin feature sheets"],
          "required_edge_motifs": ["diagonal X crossing", "three-row fan-in"],
          "required_ports_or_boundaries": ["left frame boundary ports"],
          "text_layout_facts": [
            "left-aligned small labels",
            "math-like subscripts remain on one line",
            "CJK + Latin mixed baseline preserved"
          ],
          "box_style_facts": ["outer frame has light rounding", "inner panel uses tight left/right padding"],
          "line_style_facts": ["thin gray dashed frame", "left axis line is darker than bar fill"],
          "shadow_facts": ["panel shadow is soft and light, not a hard offset"],
          "density_facts": ["upper rows are visually tight; avoid loose vertical spacing"],
          "uncertain_text": ["tiny label above top tensor unreadable"]
        }
      ]
    }
  }
}
```

Rules for `source_visual_inventory`:

- Preserve source language exactly. Do not translate Chinese labels to English for an exact replica.
- Preserve visible formulas, variables, subscripts, Greek letters, numeric labels, and row/column text. If text is unreadable, add it to `uncertain_text` rather than inventing it.
- Describe visible motifs from the crop: colored cell grid, 3D tensor slabs, vertical strips, dashed frame, bus/junction, boundary port, brace merge, top-k bar panel, and similar source-visible structures.
- Record layout facts, not only names: text alignment, expected line breaks, no-wrap areas, caption centering, serif/sans/CJK/math role, visible shadows, and whether a text line contains embedded math fragments.
- Record style facts too: `box_style_facts`, `line_style_facts`, `shadow_facts`, and `density_facts` are how strict replica work remembers padding, rounding, line grammar, softness, and tight/loose spacing.
- Record `fidelity_obligations` for small or identity-bearing objects where simplification would visibly break the source, such as worker/person icons, crossed tools, neural-network node-link motifs, device icons, thick ribbon arrows, and dense symbol clusters.
- Use old scenes and old visual reviews only as failure evidence. A new capability evaluation scene should be authored fresh from this inventory.
- A batch script may export multiple already-authored scenes, but a batch script that writes all scenes is not evidence that the skill can reconstruct new images from visual analysis.

For strict dense replicas, add `metadata.style_calibration` before detailed authoring. This is mandatory when the scene is strict/exact and region-first, arrow-dense, formula-dense, or wide/dense enough that local styles can drift.

```json
{
  "metadata": {
    "style_calibration": {
      "forward_arrow": {
        "body_width_px": 48,
        "head_width_px": 110,
        "head_length_px": 68,
        "fill": "#111111",
        "outline_weight_px": 1,
        "shadow_offset_px": 0
      },
      "feedback_arrow": {
        "stroke_width_px": 6,
        "dash_length_px": 18,
        "dash_gap_px": 12,
        "arrowhead_px": 22,
        "curve_smoothness": "source_sampled",
        "z_policy": "behind_text"
      },
      "formula_box": {
        "typical_bbox_px": [150, 72],
        "corner_radius_px": 8,
        "padding_px": [10, 6],
        "fraction_bar_weight_px": 2,
        "math_font_role": "math",
        "line_spacing_policy": "tight_fraction"
      },
      "text_scale": {
        "body_label_pt": 12,
        "output_label_pt": 13,
        "branch_caption_pt": 10,
        "rotated_label_pt": 11,
        "formula_pt": 12,
        "legend_pt": 9
      },
      "paper_3d_block": {
        "front_fill": "#FFFFFF",
        "side_fill": "#D9E6F7",
        "top_fill": "#F3F7FF",
        "hatch_density": "source_matched",
        "shadow_offset_px": 4,
        "outline_weight_px": 1
      },
      "legend": {
        "frame_weight_px": 1,
        "inner_arrow_scale": 0.55,
        "formula_sample_scale": 0.70,
        "text_baseline_policy": "source_matched"
      }
    }
  }
}
```

Rules for `style_calibration`:

- Do not define groups that are irrelevant to the source. Do define every group represented by visible source content.
- `forward_arrow` and `feedback_arrow` are separate. A dashed feedback arrow must not inherit the thick filled-arrow scale.
- `legend` is a separate scale contract. Legend samples should not inherit main-diagram arrow or formula sizes unless the source visibly does.
- Formula-like content with visible fraction bars should use `math_formula_group`; compact inline formulas should use `math_text`, `formula_text_block`, or run-based math fragments.
- `scripts/style_calibration_gate.py --strict` enforces this contract only for strict dense replicas, so ordinary small diagrams can omit it.

For exact replicas, also add `metadata.visual_grammar_inventory` before choosing components. This is a source-fact inventory for visual primitives, not a component decision.

```json
{
  "metadata": {
    "visual_grammar_inventory": {
      "shape_facts": [
        {
          "role": "formula_box",
          "form": "small rounded rectangle",
          "relative_size": "compact",
          "must_not_render_as": ["large empty callout", "plain multiline text"]
        }
      ],
      "cell_facts": [
        {
          "role": "feature_cells",
          "form": "continuous rectangular cells",
          "count": 5,
          "rounding": "low",
          "must_not_render_as": ["rounded token_grid", "loose process boxes"]
        }
      ],
      "line_facts": [
        {
          "role": "feedback_arrow",
          "form": "curved dashed arrow",
          "dash_rhythm": "short_dense",
          "relative_width": "thin_to_medium",
          "arrowhead": "small_black_triangle",
          "must_not_render_as": ["long_sparse_dash_blocks", "oversized_black_ribbon"]
        }
      ],
      "symbol_facts": ["circle plus", "triangle gate"],
      "wave_facts": ["polyline-like", "single peak", "noisy high frequency"],
      "text_facts": [
        {
          "role": "output_label",
          "form": "single-line label",
          "must_not_render_as": ["wrapped label", "opposite rotation direction"]
        }
      ]
    }
  }
}
```

The rule is: components are rendering grammar, not recognition conclusions. Use the inventory to parameterize `cell_strip`, `micro_grid`, `polyline_wave`, `symbol_group`, `shape_cluster`, `primitive_group`, `ribbon_arrow`, `curved_ribbon_arrow`, `loop_ribbon_arrow`, or a higher-level component. If a component would change a source fact, for example turning rectangular cells into rounded tokens or a thick filled arrow into a thin connector, choose the source-matched primitive instead.

`fidelity_obligations` may live under `metadata.source_visual_inventory.regions[]` or on a source-bound node. They are review and audit contracts for details that should not be normalized into generic shapes.

```json
{
  "id": "icon_row",
  "source_bbox_px": [80, 420, 820, 520],
  "fidelity_obligations": [
    {
      "object": "worker_icons",
      "must_preserve": ["helmet", "torso", "arms", "legs", "workwear color split"],
      "allowed_simplification": ["minor facial features"],
      "forbidden_simplification": ["single generic circle plus rectangle person"]
    },
    {
      "object": "network_data_icon",
      "must_preserve": ["visible nodes", "inter-node lines", "blue/orange node colors"],
      "forbidden_simplification": ["plain grid without node-link motif"]
    }
  ]
}
```

In strict replica mode, every obligation should produce a review checklist item. If `forbidden_simplification` describes a known bad replacement, the review/audit result can be blocking even when the scene is structurally valid.

For exact replicas, add an arrow inventory before authoring edges. This is a source-image visual contract: it records which arrow connects what, whether it is straight/orthogonal/curved, where it lands, and whether it carries an arrowhead. Scene edges should reference these entries through `arrow_plan_id`.

```json
{
  "metadata": {
    "arrow_plan": [
      {
        "id": "A001",
        "source_region": "encoder_to_decoder",
        "source_fact": "A solid horizontal arrow leaves the encoder right boundary and enters the decoder left boundary.",
        "from_visual_object": "encoder",
        "from": "encoder right boundary",
        "from_anchor_description": "right edge midpoint",
        "to_visual_object": "decoder",
        "to": "decoder left boundary",
        "to_anchor_description": "left edge midpoint",
        "from_anchor": "right@0.50",
        "to_anchor": "left@0.50",
        "direction": "left_to_right",
        "route_shape": "straight_horizontal",
        "arrow_template": "straight_flow",
        "line_style": "solid",
        "arrowhead": "end",
        "arrowhead_policy": "end_only",
        "semantic_intent": "data_flow",
        "region_regression_group": "encoder_decoder_main_lane",
        "source_bbox_px": [100, 120, 420, 145],
        "must_not_cross": ["decoder label", "top caption"],
        "relative_position_facts": ["source and target are horizontally aligned"],
        "must_be_axis_aligned": true,
        "geometry_contract": {
          "must_be_horizontal": true,
          "start_y_equals_end_y": true,
          "target_boundary": "left",
          "endpoint_must_touch": true,
          "tolerance_px": 3
        },
        "must_not_cross_text": true,
        "certainty": "certain"
      }
    ]
  }
}
```

Supported `semantic_intent` values are:

- `data_flow`, `control_flow`
- `feedback`, `loss_backprop`
- `boundary_handoff`, `frame_output`
- `merge`, `fan_in`
- `fork`, `fan_out`
- `loop_update`
- `annotation`, `callout`

Supported `route_shape` values are `straight`, `straight_horizontal`, `straight_vertical`, `horizontal`, `vertical`, `diagonal`, `short_diagonal`, `orthogonal`, `elbow`, `right_angle`, `rounded_orthogonal`, `hv`, `vh`, `curved`, `smooth_curve`, `loop`, and `freeform`.

Supported strict `arrow_template` values are:

- `straight_flow`: one solid or dashed straight flow arrow, normally horizontal, with one terminal arrowhead.
- `vertical_flow`: one vertical flow arrow with one terminal arrowhead.
- `orthogonal_flow`: axis-aligned routed flow with one terminal arrowhead.
- `rounded_orthogonal_flow`: axis-aligned routed flow with rounded 90-degree bends and one terminal arrowhead.
- `bezier_arc`: deterministic source-like arc with Bezier/control points and one terminal arrowhead.
- `fanout_arc` / `branch_arc`: one branch in a source-visible fan-out or fork whose source and target should keep a soft curved approach instead of a straight spoke.
- `skip_arc_no_arrow`: curved or arced skip connector with no arrowhead.
- `orthogonal_bus_no_arrow`: shared trunk, skip line, or bus segment with no arrowhead.
- `feedback_path`: dashed feedback/backprop route with the source-visible arrowhead policy.
- `feedback_loop`: loop/cycle/update route; use `loop_arrow` or an explicitly justified Bezier/loop path.
- `boundary_flow`: boundary/frame handoff arrow, normally through `boundary_port` / `boundary_arrow`.

Supported `arrowhead_policy` values are `end_only`, `none`, `start_only`, and `both`. Do not rely on edge-type defaults in strict replica mode: write the source policy in `arrow_plan`, then make the edge style match it.

Rules for `arrow_plan`:

- Every source-visible arrow in strict replica work should have an `arrow_plan` entry before the first `scene.json` is authored.
- Every visible arrow or visible line segment should have its own independent `arrow_plan_id`. Do not use one plan entry to describe a local chain or subgraph.
- Every source-visible scene edge should reference one entry with `arrow_plan_id`.
- One `arrow_plan_id` may bind to only one scene edge by default. If a single source arrow must be represented as multiple scene segments, each segment edge must set `same_source_arrow: true`, `segment_index`, and `segment_count`.
- In strict mode, each active plan should record `from_visual_object`, `from_anchor_description`, `to_visual_object`, `to_anchor_description`, `route_shape`, `line_style`, `arrowhead`, `semantic_intent`, `source_bbox_px`, `must_not_cross`, and `relative_position_facts`.
- In strict mode, prefer adding `arrow_template`, `arrowhead_policy`, `region_regression_group`, `expected_shape`, `source_bbox_px`, `confidence` or `certainty`, and `notes`. `scripts/arrow_audit_gate.py --write-audit` expands these fields into an `arrow_audit.json`/`.csv` table for visual review; the derived table must not replace `metadata.arrow_plan`.
- Use `certainty: "uncertain"` only when the source crop is genuinely unreadable; do not invent a connector.
- `feedback` and `loss_backprop` should map to `dashed_feedback_path`.
- `boundary_handoff` and `frame_output` should use `boundary_port` / `boundary_arrow`.
- `merge` / `fan_in` should terminate at a `junction_point`, `merge_bus`, or `multi_port_junction`.
- `fork` / `fan_out` should originate from a `junction_point`, `merge_bus`, or `multi_port_junction`.
- `loop_update` should use one continuous `loop_arrow`, not several line fragments plus a detached arrowhead.
- `rounded_orthogonal` should use `rounded_orthogonal_connector` or `route: "rounded_orthogonal"` with an explicit corner radius. Do not map it to `smooth_curve`.
- `bezier_arc` and `skip_arc_no_arrow` should use deterministic Bezier/arc control points. `curve_mode: "smooth"` / Catmull-Rom is allowed only for source-visible waves, decorative/hand-drawn curves, or explicit freeform curves, and should be declared with `allow_smooth_curve: true` or equivalent source facts.
- If a strict Bezier/skip/fanout arc has no hand-measured control points yet, set `curve_mode: "bezier"` plus `arc_template` / `bezier_template` on the edge. Supported templates include `upper_arc`, `lower_arc`, `left_bulge`, `right_bulge`, `fanout_upper`, `fanout_lower`, `branch_upper`, `branch_lower`, and `small_bend_in`. Optional `arc_lift_in` controls the arc height/outward bulge, `source_tangent_in` / `target_tangent_in` create source/target clearance before the curve bends, and `branch_spread_in` / `fanout_spread_in` keep fork branches from looking like rigid straight spokes. The renderer expands these into a stable editable Bezier path instead of a global smooth spline.
- Strict source-visible arrows and lines should use semantic side-ratio endpoints such as `node:right@0.50`, including arrowless bus/skip lines. Raw `from_point` / `to_point` is acceptable only for visibly free-floating source lines and should be declared with `allow_free_endpoint` or `freeform_endpoint`.
- Arrowless visual lines should be explicit. Use `arrowhead_policy: "none"` with `line_segment`, `join_connector`, or an edge style whose `begin_arrow` and `end_arrow` are both `none`.
- `scene_validate.py --strict` treats missing or violated arrow-plan bindings as errors.
- `scripts/arrow_audit_gate.py --strict` treats mismatched arrowhead policy, wrong template axes, unjustified smooth arcs, dangling tiny arrow fragments, and prohibited route crossings as rebuild defects for strict/exact scenes.
- Use `geometry_contract` when a source arrow has measurable visual geometry that must survive rendering. Supported contract fields include booleans such as `must_be_horizontal`, `must_be_vertical`, `start_y_equals_end_y`, `start_x_equals_end_x`, `endpoint_must_touch`, `must_touch_boundary`, `must_not_cross_text`, and optional `raw_endpoint_check`; string fields such as `source_boundary`, `target_boundary`, `source_node`, `target_node`, `start_anchor`, `end_anchor`, `shared_bus_id`, `shared_bus_axis`, and `shared_bus_point` (`raw_from`, `raw_to`, `route_start`, `route_end`, or `route_index:N`); and numeric tolerances such as `tolerance_px` or `tolerance_in`. This is an optional stricter contract for important arrows, not a replacement for `route_shape`. Run `scripts/scene_geometry_assert.py --strict` to enforce these contracts after the scene is authored. The geometry gate checks both resolved raw endpoints and routed path points, so `route: "horizontal"` cannot hide a misaligned `to_point`.

For local attention-like diagrams, record `metadata.local_motifs` or region-level motif facts before writing edges. Motif names can include `attention_score_motif`, `value_weighting_motif`, `residual_add_norm_motif`, and `concat_merge_motif`. Motif rules are source-level constraints, not decorative labels; for example Softmax in an attention-score motif is a floating label and should not become an edge endpoint.

When a motif renderer draws internal connectors that do not appear in the top-level `edges[]` array, expose those connectors in the motif node as `motif_edges`. Each `motif_edges[]` item should include `id`, `arrow_plan_id`, internal `from`/`to` descriptions or anchors, `route_shape`, `line_style`, and `arrowhead`. Validators and repair planning treat `edges[]` and `nodes[].motif_edges[]` together for arrow-plan coverage.

```json
{
  "id": "upper_attention_score",
  "type": "attention_score_motif",
  "motif_edges": [
    {
      "id": "upper_attention_score.operator_to_grid",
      "arrow_plan_id": "A103",
      "from": "operator_right",
      "to": "grid_left",
      "route_shape": "straight_horizontal",
      "line_style": "solid",
      "arrowhead": "end"
    }
  ]
}
```

For strict 1:1 work, distinguish semantic redraw and true replica explicitly:

- `replica_review_mode: "strict_replica"` means the scene will be judged on font behavior, padding, rounding, shadow, connector landing points, and crop-level detail.
- `replica_stage: "layout_topology"` is the first stage. Lock page ratio, region boxes, container bounds, and line grammar first.
- `replica_stage: "detail_polish"` is the second stage. Only after layout is stable should you refine text baselines, caption spacing, shadows, panel internals, and micro-gaps.

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

For high-fidelity paper figures, record the source-region plan before local polishing. This is a visual-analysis contract, not an automatic detector:

```json
{
  "metadata": {
    "region_strategy": "region_first",
    "region_plan": [
      {
        "id": "global_layout",
        "source_bbox_px": [0, 0, 1514, 538],
        "target_bbox": [0, 0, 13.333, 4.739],
        "review_focus": "page aspect, module positions, density",
        "local_acceptance_checklist": [
          "page aspect ratio and outer whitespace match source",
          "major module positions are source-aligned"
        ]
      },
      {
        "id": "left_input",
        "source_bbox_px": [0, 40, 360, 500],
        "container_id": "input_region",
        "review_focus": "input tokens, feature vectors, entry arrows",
        "local_acceptance_checklist": [
          "input token/cell visual grammar matches the source crop",
          "entry arrows land on the same visible boundaries as the source"
        ]
      }
    ]
  }
}
```

For visible or invisible region nodes, record at least one of `source_bbox_px` or `source_aspect_ratio`. For region-first exact replicas, add `review_focus` and `local_acceptance_checklist` to each important region. The checklist should contain source-visible pass criteria that a visual reviewer can answer locally, such as arrow endpoints, formula wrapping, grid cell count, line geometry, boundary crossings, and text overlap. When the source crop is dense, add `expected_node_density` after visual analysis. Audit and complexity warnings can flag likely drift, but the quality judge is still visual LLM comparison of the source image and rendered replica. Pair/crop/overlay assets remain author-side debug material.

## Large Figure Discipline

Large source images fail differently from small diagrams. The usual problem is not a missing Visio shape; it is global reasoning drift: a few nodes shift, one local font size changes, connectors cross a region boundary, and the whole figure still looks plausible at full scale.

Use this workflow when the scene has roughly 30+ visible nodes, 35+ edges, 5+ tiny formulas/math labels, 3+ arrow-dense subsystems, or a very wide paper aspect ratio:

1. Create the full page in source-pixel coordinates.
2. Add visible `group_container` and invisible `audit_region` boxes before authoring all details.
3. Assign `container_id` on every meaningful node.
4. Keep each region around 12-18 visible nodes when possible.
5. Reconstruct dense regions as editable local subscenes or editable grouped scene fragments.
6. Freeze shared style tokens and font roles before merging region work.
7. Assemble accepted regions with affine translation/scaling only; do not reroute internal region edges in the final page.
8. Draw cross-region edges through `boundary_port`, `junction_point`, `merge_bus`, or visible target anchors.
9. Run `scripts/scene_complexity.py` before full Visio render.
10. Run `scripts/scene_audit.py` and review every region after assembly.

The complexity script reports uncovered nodes, dense regions, text-fit risks, same-type font spread, overlap risks, and validation warnings. Treat those warnings as layout defects before starting visual polish.

For exact replicas, each visual review round should generate a global pair and local debug pairs tied to the region plan for the author. Use at least these crop intents: global layout, left/input, center/core, right/output, arrow-dense topology, small text/formula/matrix/port, and boundary/dashed-frame. Contact sheets are only navigation aids; small text, formulas, port locations, and arrow endpoints should still be inspected on separate debug crop pairs.

For strict paper replicas, also include a `caption` crop when the source has a paper caption, legend, or long explanatory footer. Overlay images are author-side debug material too: pair images show semantic differences, overlay images catch alignment drift. The reviewer prompt itself should still receive only the source image and replica image.

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
    "text_angle_deg": 0,
    "text_fit": "shrink_to_fit",
    "min_font_size_pt": 6
  },
  "semantic_role": "paper_caption",
  "text_role": "caption",
  "source_bbox_px": [120, 980, 1330, 1048],
  "source_font_family": "Times New Roman",
  "font_role": "paper_serif",
  "label_anchor": "right",
  "layout_motif": "centered_single_line_caption",
  "topology_motif": "branch_trunk",
  "asset_ref": "asset-id",
  "container_id": "optional-parent-container-id",
  "align_to_container": ["center_y"],
  "align_group": "row-1",
  "align_axis": "center_y",
  "align_tolerance_in": 0.05,
  "layer": "text",
  "z": 10
}
```

Use alignment fields when reconstructing module boxes such as AM-ResNet. If a component should sit on the visual midline of its parent block, set `container_id` and `align_to_container: ["center_y"]`. If several sibling nodes should share one row, give them the same `align_group` and `align_axis`.

Rendering order is unified across nodes, edges, and edge labels. Use `z` for exact local order, or use layer names when the source has a common depth relationship:

`background < panel < arrow_under_text < icon < text < foreground_arrow`

This means broad loop arrows, ribbon arrows, and dashed feedback paths can sit behind labels without moving their geometry away from the source.

Supported node `type` values are defined in `templates/visio_components.json`.

Recommended semantic fields:
- `semantic_role`: semantic meaning such as `paper_caption`, `classifier_head`, `branch_trunk`, `merge_trunk`, `annotation`.
- `text_role`: text intent such as `caption`, `annotation`, `formula`, `module_title`, `small_label`.
- In strict replica mode, roles such as `module_title`, `panel_title`, `output_label`, `caption`, `formula`, and `small_label` should not rely on extreme shrink-to-fit. If the source keeps them on one line, fix the bbox or use ordered `runs`.
- `source_bbox_px`: local source crop binding for exact review.
- `source_font_family`, `font_role`: source typography contract.
- `label_anchor`: preferred anchor such as `left`, `right`, `top`, `bottom`, `center`.
- `layout_motif`: local layout grammar such as `centered_single_line_caption`, `vector_plus_label`, `vertical_bar_group`.
- `topology_motif`: local connection grammar such as `branch_trunk`, `merge_trunk`, `paper_bus`.

Recommended visual-grammar fields for small source-bound primitives:
- `primitive_family`: one of `cell_strip`, `polyline_wave`, `ribbon_arrow`, `symbol_group`, `shape_cluster`, `primitive_group`, `compact_grid`, `micro_grid`, or `text_formula`.
- `motif_binding`: stable id linking this node to a source motif/fact such as `m2_gate_symbol`.
- `visual_facts` / `source_visual_facts`: object or array describing what the source unit visibly is, such as `primitive_family: symbol_group`, `shape: triangle_in_circle`, `rounding: low`, `line_weight: thin`, or `fill_policy: source_matched`.
- `must_match_facts`: source facts that visual review must check after rendering, for example `5 rectangular cells`, `single-peak polyline`, or `triangle remains inside circle`.
- `subshape_role`: for primitive internals such as `symbol_internal`, `icon_internal`, or `decorative_detail`.
- `source_bbox_px`: required for crop-sensitive small components in strict exact mode, not only for large modules.

Example:

```json
{
  "id": "m2_gate_symbol",
  "type": "symbol_group",
  "primitive_family": "symbol_group",
  "motif_binding": "m2_gate_symbol",
  "source_bbox_px": [420, 180, 462, 222],
  "source_visual_facts": {
    "primitive_family": "symbol_group",
    "shape": "triangle_in_circle",
    "rounding": "none",
    "line_weight": "thin",
    "fill_policy": "source_matched"
  },
  "must_match_facts": ["outlined circle", "right-facing triangle", "thin line"],
  "symbol_kind": "triangle_in_circle",
  "x": 3.1,
  "y": 1.2,
  "w": 0.24,
  "h": 0.24
}
```

### Text Fitting

Visio may wrap short formulas, CJK/English labels, and rotated layer names even when the source keeps them on one line. For exact replicas, do not accept broken text such as `GEL / U`, `f_fu / sed`, `Lay / er / Norm`, or split Chinese labels.

Use style-level text fitting when a label must stay inside a known box:

```json
{
  "id": "g_tf_label",
  "type": "math_text",
  "x": 1420,
  "y": 512,
  "w": 74,
  "h": 34,
  "text": "g_tf",
  "style": {
    "font_role": "math",
    "font_size_pt": 14,
    "text_fit": "math_label",
    "min_font_size_pt": 6
  }
}
```

Supported values:
- `shrink_to_fit` / `fit`: shrink text to both width and height.
- `single_line`, `no_wrap`, `nowrap`: prioritize one-line labels and shrink rather than wrapping.
- `math_label`: one-line math labels with subscript-like fragments.

Use `math_text` for variables with underscores or subscripts (`g_tf`, `f_fused`, `s1`) instead of raw `text_block` strings. Use a smaller `font_size_pt` and `text_fit: "math_label"` for edge labels and small feature annotations.

For strict replicas, keep word-like subscripts in fragment math by default. Labels such as `P_RGB`, `q_hrrp`, `f_fused`, and `H=[h_1,...,h_T]` should not silently fall back to compact Unicode just because they fit in one box. Use explicit compact/unicode math only when the source really looks like that.

For narrow vertical strips, do not rely on generic rotated text. Add an explicit width-budget contract before polishing:

```json
{
  "style": {
    "text_angle_deg": 90,
    "text_fit": "single_line",
    "rotated_text_width_budget_in": 0.30,
    "rotated_text_inset_in": 0.01,
    "rotated_text_box_safety_factor": 1.12
  }
}
```

Use the same idea on repeated-strip components such as `layer_sequence`: set `block_text_fit`, `block_constrain_text_box`, block font sizes, and narrow-strip text budget fields explicitly instead of leaving vertical labels on defaults.

For exact replicas, ordinary `text_block` / `annotation_block` / `caption_block` content that contains subscripts, hats, primes, Greek letters, or formula syntax should be upgraded to `math_text`, `formula_text_block`, or run-based math fragments. Do not depend on a plain text box with a math-like font.

Compact operator marks should also record size intent explicitly:

```json
{
  "type": "operator_node",
  "symbol": "+",
  "operator_size_tier": "small"
}
```

```json
{
  "type": "concat_operator",
  "glyph_mode": "source_bracket",
  "concat_size_tier": "source_small"
}
```

These tiers are shortcuts for stable symbol-box / bracket sizing. Exact scenes may still override `symbol_box_*`, `symbol_font_size_pt`, `tick_in`, or `gap_ratio` directly when the crop needs it.

Useful math-text controls:
- `prime_scale`, `prime_tuck_in`, `prime_box_pad_in`, `prime_offset_y_in` for prime/apostrophe fidelity
- `auto_compact_math: false` to keep fragment math as the stable default in exact paper mode
- `subscript_scale`, `subscript_offset_in`, `subscript_box_pad_in` for baseline-locked subscripts

Renderer default: ordinary text boxes now auto-shrink compact one-line labels when no explicit `text_fit` is set. This is a safety net for short labels such as `GELU`, `Concat`, `Softmax`, `LayerNorm`, and CJK module captions. Do not rely on the default when the source label is semantically math-like, contains underscores, or is a dense formula; author those as `math_text` with `text_fit: "math_label"` so review agents can map formula failures to the right component.

For 90-degree labels, the renderer uses a separate rotated single-line overlay with CJK/Latin width safety factors. If visual review still reports split words, first reduce the local `font_size_pt` or set `rotated_text_box_safety_factor` / `cjk_text_width_safety_factor` on that node; do not enlarge the whole module unless the source module is also larger.

Edge labels are rendered as dynamic single-line text boxes sized from the label text. For dense diagrams, prefer separate `text_block`/`math_text` label nodes with stable coordinates when a label must sit away from the route midpoint.

Use `caption_block` for paper captions or headers that mix bold prefixes with regular descriptive text. Put the visible runs in order; do not model a caption as one untyped `text_block` when visual review needs to identify which run is bold or too small.

For inline mixed typography such as Chinese notes plus English tokens or formulas, use `annotation_block` or `text_block` with ordered `runs`. Each run may override `font_role`, `font_family_candidates`, `source_font_family`, `font_size_pt`, and `math: true` / `render_as: "math_text"` for inline formula fragments. In exact mode, bind these run-based text nodes to `source_bbox_px` so caption/annotation spacing and baseline drift can be reviewed locally instead of guessed from the full page.

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

### Compact Paper Detail Components

Use these components when the source crop contains small editable details rather than large semantic boxes:

- `feature_vector_stack`: compact vertical/horizontal rows of vector cells, optional brackets, and source-bound cell spacing.
- `token_grid`: compact token blocks or small table-like labels.
- `grid_matrix`: matrix cells, heatmap grids, or feature maps with exact row/column count.
- `operator_node`: small circles such as `+`, `×`, `⊗`, `r`, or activation gates.
- `concat_operator`: visible `[]`/bracket concat marks or compact concat bars; add `ports`/`port_positions` when three or more inputs converge.
- `brace_merge`: curly many-to-one braces; add `tick_positions`/`port_positions` for visible aligned merge ticks.
- `dimension_brace`: thin paper-style curly dimension/grouping braces beside stacks, matrices, tensors, timelines, or grouped rows/columns.
- `multi_port_junction`: explicit editable junction/bus spine when several arrows share one vertical or horizontal connection line.
- `ribbon_arrow`, `curved_ribbon_arrow`, `loop_ribbon_arrow`: filled/thick arrows used as visual objects, not thin connectors.

Bind compact grids/vectors/operators to `source_bbox_px` when the original crop has exact cell counts, tiny labels, or port positions. This lets later visual review distinguish a scene-analysis mistake from renderer limitations.

### Ribbon Arrow Nodes

Use ribbon-arrow nodes when the source arrow is a thick filled graphic or gradient-like band. Do not replace it with a normal connector just because it has a direction.

```json
{
  "id": "qualitative_change",
  "type": "ribbon_arrow",
  "x": 312,
  "y": 485,
  "w": 95,
  "h": 56,
  "direction": "right",
  "body_width_px": 22,
  "head_width_px": 58,
  "head_length_px": 42,
  "fill": "#2E88B5",
  "layer": "arrow_under_text",
  "must_match_facts": ["filled right arrow", "wide triangular head", "sits behind row labels"]
}
```

For broad curved arrows, use `curved_ribbon_arrow` with source-sampled `points`; for cycle/update bands, use `loop_ribbon_arrow` with `start_angle_deg`, `sweep_angle_deg`, and source-matched `body_width_px`. These are visual arrow objects, so they should usually be nodes rather than `edges[]`.

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
  ],
  "separator_count": 3,
  "separator_line": "#111111",
  "separator_line_weight_pt": 0.8
}
```

For source images with repeated horizontal colored bands and a few full-height vertical split lines, keep the bands as one `feature_map_banded` node and add separators with either `separator_count` or explicit normalized `separator_positions`. Do not switch to `feature_map_grid` unless the source has visible cell-by-cell variation.

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

### `dual_wing_encoder`

Use `dual_wing_encoder` for symmetric paper modules that show two tapered side wings feeding a narrow center block, such as environment encoders, dual-source fusion encoders, or hourglass-like local processors. Keep it as one semantic node when the source treats the three visible parts as one module; use separate `trapezoid_node` parts only when the side wings have independent topology.

```json
{
  "id": "environment_encoder",
  "type": "dual_wing_encoder",
  "x": 1220,
  "y": 360,
  "w": 340,
  "h": 230,
  "text": "Environment\nEncoder",
  "center_ratio": 0.28,
  "taper_ratio": 0.30,
  "style": {
    "left_fill": "#CFE7F8",
    "center_fill": "#FFFFFF",
    "right_fill": "#CFE7F8",
    "line": "#111111",
    "font_size_pt": 12,
    "text_fit": "shrink_to_fit"
  }
}
```

`center_ratio` controls the width of the rectangular center section. `left_fill`, `center_fill`, and `right_fill` may be supplied in the node or style. Connectors should normally target the node boundary or explicit ports rather than the internal faces unless the source has visibly separate side-wing connections.

Set `shape_mode: "opposing_trapezoids"` for paper modules where two tapered wings pinch toward a short center strip instead of a full-height center rectangle. Set `shape_mode: "custom_polygon"` with `points` when the source has an asymmetric or notched encoder outline. These are still one semantic component; do not split them into unrelated polygons unless each side has separate topology.

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

### `tensor_stack`

Use `tensor_stack` when the source shows several parallel 3D feature-map slabs that represent one tensor or station feature. This is the common paper-figure encoding for stacked blue, green, or orange feature blocks. Do not hand-place many separate `cuboid_node` layers unless individual slabs have different topology.

```json
{
  "id": "station_feature_1",
  "type": "tensor_stack",
  "x": 46,
  "y": 120,
  "w": 42,
  "h": 118,
  "layers": 6,
  "layer_dx_in": -5,
  "layer_dy_in": 4,
  "depth_x_in": 20,
  "depth_y_in": -18,
  "style": {
    "fill": "#BFD3E4",
    "side_fill": "#8FA6B7",
    "top_fill": "#E4EFF7"
  }
}
```

For pixel-coordinate exact replicas, set depth and layer offsets in source-pixel units; the renderer scales them with the page. Keep the front face as the connector endpoint, and use nearby `junction_point` nodes if multiple edges attach to different visual layers.

When the source shows thick black-edged 3D feature maps, use `stack_render_mode: "feature_cuboids"` (aliases: `"thick_cuboids"`, `"feature_stack"`, `"paper_feature_stack"`, `"thick_feature_map"`). This keeps each visible slab as a cuboid with top/right faces instead of flattening it into paper sheets. Tune `depth_x_in`, `depth_y_in`, `layer_dx_in`, `layer_dy_in`, `line_weight_pt`, `side_fill`, and `top_fill` from the crop. If these values are between `-1` and `1`, depth is interpreted relative to the tensor width/height; larger values are scene units and are scaled in pixel-coordinate scenes.

When the source shows many narrow layered feature sheets with light perspective, use `stack_render_mode: "thin_feature_slabs"` (aliases: `"thin_feature_stack"`, `"layered_slabs"`, `"source_thin_slabs"`, `"paper_thin_feature"`). This still draws editable top/right faces, but avoids turning the tensor into a large cuboid block. Use it for station tensors or input/output slabs when the crop looks like a thin paper-stack feature map rather than a thick cube.

When the source shows many thin parallel sheets rather than full cuboids, keep the same semantic component and set `stack_render_mode: "thin_sheets"` (or `sheets`). This draws repeated editable front faces without heavy top/side slabs, which is more faithful for flat paper tensor columns.

When the source sheets are slanted parallelograms, use `stack_render_mode: "slanted_sheets"` / `"paper_sheets"` and tune `skew_x_in`, `layer_dx_in`, and `layer_dy_in`. This is the preferred grammar for compact station-feature and output-feature stacks that visual reviewers describe as thin layered slabs rather than bulky cubes.

When the source shows oblique 3D feature slabs with visible slanted top/right faces, set `stack_render_mode: "oblique_slabs"` (or `paper_3d`). Tune `depth_x_in`, `depth_y_in`, `skew_x_in`, `layer_dx_in`, `layer_dy_in`, `sheet_line_weight_pt`, and `layer_fill_delta`. Do not replace a tensor with many unrelated boxes unless each visible sheet has distinct topology.

For more stable source-faithful parameterization, use `perspective_mode` when the source clearly belongs to one visual family:
- `flat` / `front`
- `light` / `paper_light`
- `medium` / `paper_medium`
- `strong` / `heavy`
- `source_thin`
- `source_thick`

`perspective_mode` is not a template selector. It is a compact way to keep depth, skew, and layer offsets internally consistent before fine crop matching.

Do not use a global tensor default to solve all feature blocks. Visual review must decide from the crop whether the source is a thick feature cuboid stack, thin feature slabs, thin front sheets, slanted sheets, or oblique slabs. A reviewer complaint like "feature map became flat paper sheets" means the scene may need `feature_cuboids`; a complaint like "became a big cube/block" means the scene should switch to `thin_feature_slabs`, not merely nudge coordinates.

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

The renderer normalizes compact loss spellings such as `Ladv`, `Lrec`, `L adv`, and `L rec` to `L_adv` / `L_rec`, then splits patterns like `L_adv` into editable fragments (`L` plus smaller lowered `adv`). Tuning fields: `subscript_scale`, `subscript_offset_in`, `line_gap_in`, `segment_gap_in`, `fragment_pad_in`, `subscript_pad_in`, `subscript_box_pad_in`, and `padding_in`.

For paper figures with dense labels such as `P_RGB`, `q_IR`, `f_tf`, `g_hrrp`, and `f_fused`, prefer `math_render_mode: "fragments"` when the subscript contains uppercase or word-like tokens. The renderer only uses compact Unicode automatically when every subscript character has a true subscript glyph; otherwise fragment mode avoids the visual failure where `RGB`, `SAR`, or `fused` become superscript-like fallback letters.

Use `math_text` for hat notation such as `f̂` or `f\u0302`. Do not leave hat labels as ordinary `text_block`; the renderer treats hat fragments as math and overlays the hat mark so Visio does not substitute or split the glyph unpredictably.

Use `math_text` or `formula_text_block` when the visible source line mixes natural language and inline math, such as `最后 token 嵌入 e_T` or `H=[h_1,...,h_T]`. Do not degrade those lines to a plain `text_block` if the math fragment alignment matters visually.

### `math_formula_group`

Use `math_formula_group` for structured editable formulas with a visible fraction bar, especially when the source shows an equation such as `ω = numerator / denominator`. This component keeps the prefix, equals sign, numerator, fraction bar, denominator, and optional suffix in one local formula group so baseline and fraction alignment do not drift as separate loose text boxes.

```json
{
  "id": "omega_fraction",
  "type": "math_formula_group",
  "x": 280,
  "y": 620,
  "w": 260,
  "h": 68,
  "left_text": "ω",
  "operator": "=",
  "numerator": "exp(s_i)",
  "denominator": "Σ_j exp(s_j)",
  "baseline_y_ratio": 0.52,
  "fraction_bar_weight_pt": 0.8,
  "source_bbox_px": [560, 1240, 820, 1308]
}
```

Use `math_text` for short inline labels like `L_adv`; use `math_formula_group` when a real stacked fraction or aligned equation is visible. Tuning fields: `left_w_in`, `operator_w_in`, `fraction_w_in`, `fraction_width_policy`, `fraction_padding_in`, `fraction_min_w_in`, `fraction_font_size_pt`, `fraction_text_mode`, `baseline_y_ratio`, `fraction_bar_weight_pt`, `gap_in`, `numerator_gap_in`, and `denominator_gap_in`. Default `fraction_width_policy: "fit_content"` keeps the fraction close to the equals sign instead of filling the whole formula box. Keep `fraction_text_mode: "tight_fragments"` for tight paper-style formulas with visible editable subscripts; use `"compact"` only when Unicode subscript rendering matches the source better, or `"fragments"` when maximum editability matters more than compact spacing.

### `math_label_box`

Use `math_label_box` for compact colored or white labels where the box itself is visible and the label is math-like, such as `Q_a`, `K_w`, `V_w`, `P_RGB`, `q_IR`, `f_tf`, or `f_fused`. Do not put these labels in ordinary `process_box` text when the source relies on a subscript baseline inside a small module.

```json
{
  "id": "q_label",
  "type": "math_label_box",
  "x": 880,
  "y": 320,
  "w": 88,
  "h": 38,
  "text": "Q_a",
  "style": {
    "fill": "#E8F0FF",
    "line": "#111111",
    "font_size_pt": 20,
    "subscript_scale": 0.62,
    "subscript_offset_in": 4,
    "text_fit": "math_label"
  }
}
```

Use separate `math_text` when the source has floating math without a visible box. Use `math_label_box` when the visible rectangle/capsule and its math label are one semantic object.

For `modality_spine` ports, set `math_label: true` on port entries whose visible port label is math-like. Port text containing `_` is also treated as math by the renderer. This preserves a single spine component while keeping labels such as `P_RGB`, `P_IR`, and `P_SAR` from rendering as flat ordinary text.

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

You may use semantic aliases that render with the same family but express local grammar more clearly:
- `branch_trunk`: one shared trunk splitting to many outputs
- `merge_trunk`: many inputs collapsing into one shared trunk
- `paper_bus`: shared horizontal/vertical bus segment
- `collector_bar`: compact merge collector near one side of a module
- `junction_bus`: explicit junction spine using the multi-port junction renderer

### `concat_operator`

Use `concat_operator` for visible bracket concat marks such as `[]` when the source shows a bracket-shaped operator rather than a rounded `Concat` module. It renders the two bracket strokes as editable lines and keeps connectors anchored to one semantic operator.

```json
{
  "id": "concat_mark",
  "type": "concat_operator",
  "x": 2398,
  "y": 823,
  "w": 80,
  "h": 110,
  "orientation": "vertical",
  "style": {
    "line": "#000000",
    "line_weight_pt": 1.4
  }
}
```

Default `glyph_mode: "bracket_pair"` draws two editable bracket strokes. Use `glyph_mode: "glyph"` only when the source literally shows a typed `[]` glyph and the stroke geometry is less important, or `glyph_mode: "boxed"` when the source has a small square concat box.

Use `glyph_mode: "source_bracket"` (aliases: `"solid_bracket"`, `"bold_bracket"`, `"paper_bracket"`) when the source concat mark is a compact heavy `[]` symbol rather than a thin decorative pair. Tune `tick_in`, `gap_ratio`, and `line_weight_pt` from the local crop, and add `ports`/`port_positions` when upper/lower paths converge into the bracket.

Do not use `operator_node` with the text `[]` for exact replicas unless the source literally shows typed square brackets. Use `operator_node` for circular or textual operators such as `+`, `×`, `⊗`, or `1-x`.

`group_container` labels are rendered as top labels by default. Optional title controls:

### `layer_sequence`

Use `layer_sequence` for titled modules containing repeated Linear/ReLU/LayerNorm/Dropout/Q/K/V bars. Choose the block grammar from the crop:

- Tall white 2D strips: `block_style_mode: "paper_vertical_strip"`.
- Tall white 3D blocks with visible top/right faces: `block_style_mode: "paper_vertical_cuboid"` or `"source_3d_strip"`.
- Colored source strips: `block_style_mode: "colored_paper_strip"` with explicit `block_fills`.

For dense paper modules, set `density_mode: "source_dense"` (or `dense: true`) so the renderer keeps tighter gaps, taller blocks, and constrained single-line labels. This is useful for gate modules, fusion projection stacks, Q/K/V blocks, and compact classifier strips. It is not a substitute for source bbox matching; still bind the module to its region bbox and review the crop.

When the source bars are colored, preserve colors explicitly:

```json
{
  "id": "classifier",
  "type": "layer_sequence",
  "block_style_mode": "colored_paper_strip",
  "block_fill_policy": "preserve",
  "preserve_block_fills": true,
  "block_fills": ["#F6D96D", "#9DD5F2", "#D7B3F4"],
  "blocks": ["AvgPool", "Linear", "Softmax"]
}
```

Do not set `ignore_block_fills: true` on colored layer sequences. If an old scene contains both colored mode and `ignore_block_fills`, remove it or set `block_fill_policy: "preserve"` before visual review; otherwise a later refactor can regress colored bars to white.

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

For titled repeated-bar modules, treat the title area and content area as separate layout zones. Useful fields:
- `title_h_in` or `title_area_ratio`
- `title_align`
- `padding_left_in` / `padding_right_in` / `padding_top_in` / `padding_bottom_in`
- `content_padding_left_in` / `content_padding_right_in` / `content_padding_top_in` / `content_padding_bottom_in`
- `content_align_x` / `content_align_y`

Use these instead of pushing every inner block by hand. Exact replica work should first lock the title/content split, then tune block sizes and gaps.

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

`operator_node` renders the circle and the symbol as a controlled pair, with the symbol centered in the circle. Prefer `symbol` over a separate `text_block`. Keep `w` and `h` equal for exact replicas unless the source uses a pill/label-like operator.

Optional tuning fields: `symbol_font_size_pt`, `symbol_font_family`, `symbol_offset_x_in`, `symbol_offset_y_in`, `symbol_inset_in`, `symbol_text_fit`, `symbol_box_w_in`, `symbol_box_h_in`, `symbol_constrain_text_box`, and `symbol_text_box_policy`.

For multi-character operators such as `1-x`, `cat`, `gate`, or short labels inside an operator marker, set `symbol_text_fit: "single_line"` and keep `symbol_constrain_text_box: true` so Visio does not split the operator into stacked characters. Increase `symbol_font_size_pt` or the visible node size only when the source circle is also larger. Use `operator_shape: "none"` only when the source has text on a connector without a visible circle; do not fake it as an unrelated floating text block because the topology audit then loses the operator.

### `attention_score_motif`

Use `attention_score_motif` for compact attention-score substructures where two Q/K-style inputs feed a multiply operator, the operator points to a small score grid, and the arrow carries a `Softmax` label. This is a single topology motif, not a loose group of `operator_node` + `text_block` + `grid_matrix` shapes.

```json
{
  "id": "score_top",
  "type": "attention_score_motif",
  "x": 500,
  "y": 120,
  "w": 108,
  "h": 42,
  "label": "Softmax",
  "operator_x_ratio": 0.04,
  "operator_y_ratio": 0.52,
  "operator_size_ratio": 0.36,
  "grid_x_ratio": 0.66,
  "grid_y_ratio": 0.20,
  "grid_w_ratio": 0.34,
  "grid_h_ratio": 0.60
}
```

External connectors may target motif subports:
- `score_top:operator_left@0.38` / `score_top:operator_left@0.72` for Q/K fan-in.
- `score_top:grid_top@0.5` or `score_top:grid_bottom@0.5` for vertical score-grid output.
- `score_top:grid_right@0.5` when the score grid feeds a right-side operator.

Prefer these subports over free `to_point` / `from_point` stubs. Free points often create broken-looking joins because the external arrow and the motif's internal arrow do not share a real endpoint. If visual review reports Softmax labels crowded between the operator and grid, increase motif width or move the grid with `grid_x_ratio`/`grid_x_in`; do not replace the label with a separate `text_block`.

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

### `layer_sequence`

Use `layer_sequence` for a rounded module containing repeated visible internal layers such as Linear, ReLU, LayerNorm, Dropout, Q/K/V bars, or horizontal model-stage rows. This keeps the container title, internal block spacing, and labels under one semantic component.

```json
{
  "id": "fusion_projection",
  "type": "layer_sequence",
  "x": 1910,
  "y": 420,
  "w": 560,
  "h": 640,
  "title": "融合投影",
  "orientation": "horizontal",
  "blocks": ["Linear", "LayerNorm", "ReLU", "Dropout"],
  "block_text_angle_deg": 90,
  "style": {
    "fill": "#FFF2B6",
    "line": "#111111",
    "rounding_in": 26,
    "title_font_size_pt": 24
  }
}
```

Use `classifier_head` when the internal layers are primarily a classifier chain with internal arrows or fan-out behavior. Use `layer_sequence` when the source mainly emphasizes repeated vertical layer bars inside a titled module.

For paper classifier or projection strips, prefer parameterized block grammar over hand-placing many bars. Each block may carry local overrides such as `w`, `h`, `w_ratio`, `h_ratio`, `gap_after_in`, `style`, and text role. This keeps the layer group as one semantic component while still allowing source-like uneven bar widths and spacing.

Orientation grammar:
- `horizontal` / `horizontal_bars`: side-by-side narrow vertical bars, usually with `block_text_angle_deg: 90`.
- `vertical` / `vertical_stack`: stacked horizontal rounded rows, usually with `block_text_angle_deg: 0`.

Set `frame_visible: false` when the source already has a surrounding `group_container` or when the visible object is only a strip sequence, such as classifier strips or Q/K/V bars. Keep the default `frame_visible: true` for titled modules where the outer rounded module is visible. This prevents the common artifact where a local layer sequence gets an extra inner rectangle that the source does not have.

For paper figures where those bars are visibly colored or have a small 3D side face, keep the same `layer_sequence` component and add reusable appearance fields:

```json
{
  "id": "classifier",
  "type": "layer_sequence",
  "orientation": "horizontal_bars",
  "blocks": ["LayerNorm", "Linear", "GELU", "Dropout", "Linear"],
  "block_text_angle_deg": 90,
  "block_style_mode": "colored_paper_strip",
  "block_fills": ["#CFE7F8", "#F7DCA8", "#D7EBC0", "#E6D8F1", "#F7C9D7"],
  "style": {
    "block_constrain_text_box": true,
    "block_depth_x_in": 0.04,
    "block_depth_y_in": -0.03,
    "block_text_fit": "single_line",
    "block_min_font_size_pt": 5.5
  }
}
```

Use this for classifier/QKV/MLP stacks across figures. Do not create a full-image template just to get colored vertical bars.

Set `block_style_mode` deliberately instead of relying on one global default:
- `flat_colored`: simple flat colored bars, useful for classifier heads and attention MLP stacks.
- `white_capsule`: white rounded bars inside a colored container, useful for Q/K/V, gate, Linear/LayerNorm/ReLU, and projection blocks in paper figures.
- `paper_vertical_strip` / `rounded_strip` / `tall_rounded`: tall 2D white rounded strips with optional soft shadow and no 3D side faces. Use this when visual review says the source layer blocks are pure rounded vertical strips, as in many gate/fusion/projection modules.
- `colored_paper_strip` / `colored_vertical_strip` / `paper_colored_strip`: tall 2D strips that honor `block_fills`, with no 3D side faces. Use this when the source has colored classifier or layer bars but visual review rejects cuboid depth.
- `white_cuboid` / `paper_vertical_cuboid` / `white_3d`: white narrow bars with small top/side faces, useful for high vertical paper layer blocks where `Linear`, `LayerNorm`, `ReLU`, `Sigmoid`, or Chinese+Latin labels must stay one rotated label.
- `cuboid` / `cuboid_layers` / `3d`: offset side faces for backbone or encoder stacks that visibly look layered.

For narrow vertical labels, set `block_text_fit: "single_line"`, `block_constrain_text_box: true`, and a realistic `block_min_font_size_pt`. If the source label is CJK+Latin or a long word like `LayerNorm`, keep it as one block label and let the renderer shrink it; do not split it into stacked characters.
The renderer uses a constrained rotated text box for 90-degree layer labels. If visual review reports `Linear`, `LayerNorm`, `ReLU`, Chinese captions, or Q/K/V labels split into fragments, classify it as a renderer/schema or scene-box defect and fix the text policy or local font scale. Do not enlarge the whole module to hide the wrap.

When the source layer sequence has visible arrows between adjacent layer strips, set `draw_internal_arrows: true`. Keep this inside the `layer_sequence` component for MLP/FiLM/private-path pipelines so visual review can attribute missing layer-to-layer arrows to one component instead of many loose edges.

If the source uses white layer strips or white 3D layer blocks but an older scene still contains `block_fills`, keep the visual intent explicit:

```json
{
  "block_style_mode": "paper_vertical_strip",
  "block_fill_policy": "white",
  "block_fill": "#FFFFFF",
  "block_text_fit": "single_line",
  "block_constrain_text_box": true
}
```

Use `colored_paper_strip` only when the visible source crop actually has colored internal bars. Do not infer colored bars from the presence of `block_fills` alone.

For containers like LocalEchoGRU or a Shallow Shared Backbone where the source shows stacked horizontal layers, use `orientation: "vertical_stack"` and preserve each visible layer name as one block:

```json
{
  "id": "local_echo_gru",
  "type": "layer_sequence",
  "title": "LocalEchoGRU",
  "orientation": "vertical_stack",
  "blocks": [
    "Embedding + 周期特征",
    "LocalPatternMixer",
    "BiGRU",
    "多路池化融合",
    "分类器"
  ],
  "block_text_angle_deg": 0,
  "block_text_fit": "shrink_to_fit",
  "block_min_font_size_pt": 7
}
```

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

When the source uses a visible shared trunk instead of independent arrows, do not replace it with `boundary_fanout`; use `branch_trunk`, `merge_trunk`, `paper_bus`, or `collector_bar` as appropriate.

### `vector_label_group`

Use `vector_label_group` for a compact vector/tensor cell strip plus its nearby label when the label baseline and spacing relative to the cells matter visually. This is a semantic alias over `feature_vector_stack`, but it signals that review should judge the vector cells and the attached label together.

Recommended fields:
- usual `feature_vector_stack` cell fields
- `label`, `label_side`, `label_gap_in`, `label_w_in`, `label_h_in`
- `label_math: true` when the label contains subscripts or inline math

### `caption_block`

Use `caption_block` for paper captions or structured figure footers. In strict paper mode:
- keep the caption on a single shared baseline
- keep the whole caption centered unless the source visibly left-aligns it
- model `Fig. 6.` or similar prefixes as a bold run, not a separate floating text node
- use `strict_mode: true` when visual fidelity depends on prefix/body spacing and centered alignment

Do not replace a visible paper caption with one generic `text_block` if the bold prefix/body split or centering matters.

For non-caption mixed text, keep using `annotation_block` or `text_block`, but author the inline pieces as ordered `runs` instead of hand-placing several free text nodes. This keeps audit/validate aware of the intended baseline, font roles, and math fragments.

When a run-based text node must stay on one line in the source, keep `min_font_size_pt` reasonably close to the requested font size. Do not silently allow replica text to pass only because Visio compressed it to a tiny width.

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

Selection priority for cell-like visuals:
- use `cell_strip` for repeated unlabeled rectangular cells in a row or column, especially when the source shows low rounding or continuous cell grammar
- use `micro_grid` for compact matrix/tensor tiles with thin rectangular cells
- use `grid_matrix` for larger contiguous shared-line matrices without per-cell text
- use `token_grid` only when the source visibly shows readable numbers or short labels, separated token/index cells, or intentionally rounded/gapped token tiles

### `token_grid`

Use `token_grid` for visible colored token or index tiles that contain readable numbers or short labels. This differs from `cell_strip`, `micro_grid`, and `grid_matrix`: cells have gaps, intentional rounding, per-cell fill colors, and optional centered text. It is useful for variable-length prefix sequences, padded batch matrices, top-k probability rows, and small numbered grids where token identity or per-cell labels are visible.

```json
{
  "id": "prefix_batch",
  "type": "token_grid",
  "x": 620,
  "y": 690,
  "w": 410,
  "h": 190,
  "rows": 3,
  "cols": 5,
  "cell_gap_in": 9,
  "cells": [
    {"row": 0, "col": 0, "text": "21", "fill": "#A7D8EA"},
    {"row": 0, "col": 1, "text": "27", "fill": "#FF9A52"},
    {"row": 0, "col": 2, "text": "25", "fill": "#CFE7B3"}
  ],
  "style": {
    "cell_font_size_pt": 16,
    "cell_text_fit": "single_line",
    "cell_min_font_size_pt": 6,
    "cell_rounding_in": 3
  }
}
```

Use `cell_strip`, `micro_grid`, or `grid_matrix` instead when the source shows unlabeled rectangular cells. Do not use `token_grid` merely because the unit is a small colored cell group; doing so can turn source-rectangular cells into rounded token-like marks.

For dense batch matrices, keep the grid as one `token_grid` with explicit row/col cells. Do not hand-place individual token boxes unless the source truly has irregular spacing. If cell text overlaps after render, reduce `cell_font_size_pt` or rely on `cell_text_fit`, then re-review the crop visually.

When the source shows square token cells, set `square_cells: true` and use `grid_align_x` / `grid_align_y` to anchor the resulting square grid inside the source bbox. Do not stretch square tokens into wide rectangles to fill the bbox; that changes the visual grammar and visual reviewers should flag it as a scene/schema issue.

### `probability_bar_list`

Use `probability_bar_list` for Top-k/probability panels where each row has a label or token id, a colored bar, and a value. Do not model this as one rounded multiline text box; Visio line spacing and CJK fallback often collapse dense rows.

```json
{
  "id": "topk_probs",
  "type": "probability_bar_list",
  "x": 2300,
  "y": 650,
  "w": 390,
  "h": 300,
  "items": [
    {"pre_value_label": "0.42", "label": "18", "value": 0.42, "bar_value_label": "0.42 18: 0.42", "fill": "#4E9AD1"},
    {"pre_value_label": "0.21", "label": "07", "value": 0.21, "bar_value_label": "0.21 07: 0.21", "fill": "#4E9AD1"},
    {"pre_value_label": "0.13", "label": "31", "value": 0.13, "bar_value_label": "0.13 31: 0.13", "fill": "#4E9AD1"}
  ],
  "style": {
    "fill": "#FFB8DB",
    "line": "#FFB8DB",
    "rounding_in": 26,
    "label_font_size_pt": 24,
    "panel_inner_padding_left_in": 18,
    "panel_inner_padding_right_in": 18,
    "panel_inner_padding_top_in": 16,
    "panel_inner_padding_bottom_in": 16,
    "pre_value_w_in": 0.45,
    "label_w_in": 0.35,
    "axis_w_in": 0.08,
    "axis_offset_x_in": 4,
    "value_w_in": 0.50,
    "bar_start_offset_x_in": 4,
    "row_gap_in": 16
  }
}
```

Use separate `text_block` nodes for panel titles when the title sits outside the rounded probability body.

Use `pre_value_label` for source panels that show the probability number before the token or bar. Use `label` for the token/category, `value` for normalized bar length, `value_label` for the displayed number after the bar, and `bar_value_label` when the source overlays or aligns the large row text with the bar area itself. Set `bar_value_anchor: "bar_area"` when the row text should align to the full plot area, `"row"` when it should span the whole row, or `"after_bar"` when the source text starts just after the colored bar. Tune `pre_value_w_in`, `label_w_in`, `axis_w_in`, `value_w_in`, `bar_value_w_in`, and `bar_value_text_gap_in`; use positive `bar_value_offset_x_in` only when the source visibly starts the text inside the bar, because visual review often flags this as text/bar overlap.

For strict replicas, also control these panel micro-layout fields explicitly when the panel is a key visual motif:

- `panel_inner_padding_left_in` / `right_in` / `top_in` / `bottom_in`
- `panel_shadow` or an explicit `shadow: null`
- `axis_offset_x_in`, `bar_start_offset_x_in`, `bar_end_padding_in`
- `label_align`, `pre_value_align`, `value_align`, `bar_value_align`, `row_vertical_align`
- `label_baseline_offset_in`, `pre_value_baseline_offset_in`, `value_baseline_offset_in`, `bar_value_baseline_offset_in`
- `label_offset_x_in`, `label_offset_y_in`, and the matching `pre_value_*` / `value_*` / `bar_value_*` offsets when row text needs pixel-like nudging

These fields exist so a probability panel can behave like a local grammar, not just a colored box with generic bars.

If visual review reports the colored bars running through the row text, reduce `bar_max_fraction` or switch to `bar_value_anchor: "after_bar"`. Do not replace the panel with loose text boxes; keep the row grammar inside `probability_bar_list` so later reviews can map bar/text defects to one component.

In pixel-coordinate scenes, these `_in` layout fields may be authored in source pixels and are normalized with the scene. Keep all row sub-elements inside the same `probability_bar_list`; if the exported PNG shows probability numbers or bars far outside the panel, treat it as a renderer/schema unit bug, not a visual success.

### `bracket`

Use `bracket` for modality grouping marks, square/U-shaped grouping marks, and legacy generic curly braces. Do not fake these with ultra-thin `process_box` rectangles.

```json
{
  "id": "input_modalities_bracket",
  "type": "bracket",
  "x": 1.65,
  "y": 2.4,
  "w": 0.35,
  "h": 3.05,
  "orientation": "right",
  "shape": "curly",
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

Set `shape: "curly"` for legacy/general brace-like aggregation marks. Use the default straight bracket only when the source has square bracket geometry. A curly brace plus explicit `junction_point` or `boundary_port` nodes is preferred for many-to-one gate/fusion topology; do not fake a brace with a rotated parenthesis character.

### `dimension_brace`

Use `dimension_brace` for thin paper-style dimension or grouping curly braces placed beside matrices, vertical stacks, tensors, timelines, or grouped rows/columns. It renders a single editable Bezier path using `shape: "paper_curly"` and stays narrow in high-aspect layouts, unlike generic `shape: "curly"` which remains the old/general behavior. The intended grammar is a narrow TeX-like stretch delimiter: very short curled terminals, long near-vertical stems, and a small center waist pinch. It should read as a range marker, not as an ornamental S-shaped brace. Do not use this component for many-to-one merge braces with incoming connector ticks.

```json
{
  "id": "stack_height_brace",
  "type": "dimension_brace",
  "x": 7.2,
  "y": 3.4,
  "w": 0.12,
  "h": 1.8,
  "orientation": "right",
  "style": {
    "line": "#000000",
    "line_weight_pt": 1.05
  },
  "source_visual_facts": {
    "shape": "thin TeX-like stretch dimension brace",
    "opens_toward": "left"
  },
  "must_match_facts": [
    "not S-shaped",
    "long near-vertical stems",
    "single editable path",
    "thin high-aspect brace",
    "no arrowhead"
  ]
}
```

`dimension_brace` tuning fields are `orientation`, `curve_mode`, `bezier_samples`, `terminal_indent_ratio`, `outer_bulge_ratio`, `waist_indent_ratio`, `neck_ratio`, and `lobe_ratio`. Use `dimension_brace` or `bracket` with `shape: "paper_curly"` when the source brace annotates a dimension/range and has no merge-connector semantics. Use `brace_merge` when the brace is part of a many-to-one input/fusion topology.

### `brace_merge`

Use `brace_merge` for many-to-one curly merge braces near fusion/sum structures. It is stricter than `bracket`: the rendered brace is a smooth editable path with optional short tick marks at normalized port positions.

```json
{
  "id": "fusion_brace",
  "type": "brace_merge",
  "x": 1852,
  "y": 475,
  "w": 82,
  "h": 610,
  "orientation": "right",
  "tick_positions": [0.0, 0.5, 1.0],
  "style": {
    "line": "#000000",
    "line_weight_pt": 1.8
  }
}
```

Use `bracket` for square/U-shaped grouping marks. Use `dimension_brace` for thin high-aspect paper dimension braces. Use `brace_merge` when the visual issue is a curly aggregation shape or when incoming branches need to meet a brace waist consistently.

For source figures where the brace pinches inward at a plus/sum junction, set `brace_shape: "tight_curly"` and `waist_width_in` to pull the brace waist toward the junction. Use `tick_positions` for source-visible branch levels, and keep separate `junction_point` nodes for the actual connector merge.

Use `curve_tightness` when the source brace is visibly compact and the default smooth curve looks too open. This keeps the brace as one general component while making its curvature more source-like.

### `multi_port_junction`

Use `multi_port_junction` when the source has an explicit bus or shared trunk: Q/K/V汇流线, gate trunks, vertical merge spines, or top/bottom routes feeding a concat. `ports` may be dictionaries with `position`, `side`, and optional `length_in`. Set `length_in: 0` when the source has no visible tick marks and only the connected edges should meet the spine.

Do not rely on default generated left/right ticks for exact replicas. If a visual review reports stray short stubs along a fusion block or brace, set explicit `ports` and keep `port_length_in: 0`, then route the real edges to those positions.

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
  "arrow_plan_id": "A001",
  "edge_role": "data_flow",
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

`edge_role` separates topology edges from visual internals:
- `data_flow`, `context_flow`, `feedback_flow`: source-visible connectors that should usually bind to `metadata.arrow_plan`.
- `decorative_internal`, `symbol_internal`, `icon_internal`: lines inside icons, motifs, symbols, or graph-like decorative structures. These do not satisfy arrow-plan topology and should be reviewed by visual grammar checks instead.

Endpoint syntax currently supports:
- `node-id`
- `node-id:left`
- `node-id:right`
- `node-id:top`
- `node-id:bottom`
- `node-id:center`
- `node-id:left@0.62`
- `node-id:right@0.58`
- `attention_score_motif-id:operator_left@0.38`
- `attention_score_motif-id:grid_top@0.5`

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
- `rounded_orthogonal`: force right-angle routing but render visible 90-degree bends as fixed-radius rounded corners
- `hv`, `horizontal_then_vertical`: horizontal segment first, then vertical
- `vh`, `vertical_then_horizontal`: vertical segment first, then horizontal

Use `join_connector` for source-to-merge legs that should reach a shared junction or bus without arrowheads. Use `fork_connector` for fan-out branches leaving a junction or bus. These edge types keep fan-in/fan-out topology explicit instead of drawing several unrelated arrows into one box edge.

Use `residual_connector` or `residual_loop` for skip/residual loops. They render like arrow connectors but signal that the route must preserve loop topology and should normally use explicit axis-aligned `points`.

Explicit point routes can be made axis-aligned without calculating every intermediate corner:

```json
{
  "id": "gate_to_mul_top",
  "type": "lane_arrow",
  "from": "gate_split:right",
  "to": "mul_top:bottom",
  "route": "orthogonal",
  "orthogonalize_points": true,
  "points": [[1640, 620], [1840, 515]]
}
```

Use `orthogonalize_points: true` when the source path is a right-angle paper-flow route but the scene only records bend waypoints. The renderer inserts missing horizontal/vertical elbow points so tiny endpoint mismatches do not become visible diagonals. Keep `allow_diagonal: true` only for source-visible diagonal callouts or fan-in/fan-out strokes.

Use `rounded_orthogonal_connector` when the source path is still orthogonal, but each 90-degree turn is visibly rounded. This is different from a smooth curve: the straight horizontal/vertical lanes must stay straight, and only the bend corners are rounded.

```json
{
  "id": "branch_to_output",
  "type": "rounded_orthogonal_connector",
  "arrow_plan_id": "A012",
  "from": "branch_bus:right@0.50",
  "points": [[620, 310], [620, 410]],
  "to": "output:left@0.50",
  "route": "rounded_orthogonal",
  "orthogonalize_points": true,
  "corner_radius_px": 14,
  "style": {
    "end_arrow": "triangle",
    "line_weight_pt": 1.2
  }
}
```

For exact replicas, set the matching arrow inventory item to `route_shape: "rounded_orthogonal"`. Do not use `curve_mode: "smooth"` or `loop_arrow` for a rounded orthogonal connector unless the source line is truly a free curve or an outer loop.

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
- If an `orthogonal` edge has `points`, each adjacent point pair must share either `x` or `y`, or set `orthogonalize_points: true` so the renderer inserts missing elbows.
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
