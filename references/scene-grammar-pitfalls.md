# Strict Scene Grammar Pitfalls (wrong → correct)

Authoring-time reference for exact-replica scenes. These are schema/grammar mistakes
that cost trial-and-error rounds in production runs; the visual content decisions stay
with source-image analysis. `scripts/schema_hints.py <scene.json>` scans a draft scene
and prints these fixes automatically before the first validate run.

## arrow_plan

| wrong | correct |
|---|---|
| `"direction": "right"` / `"lr"` / `"→"` | `"direction": "left_to_right"` — vocabulary: left_to_right, right_to_left, top_to_bottom, bottom_to_top, bidirectional, none, unknown |
| missing `semantic_intent` | one of: data_flow, control_flow, feedback, loss_backprop, boundary_handoff, frame_output, merge, fan_in, fork, fan_out, loop_update, annotation, callout |
| raw endpoints without declaration | prefer `from_anchor: "node_id:right@0.50"`; raw from_point/to_point only for visibly free-floating lines plus `allow_free_endpoint` |
| `geometry_contract` as a list of strings | object of booleans: `{"must_be_horizontal": true, "endpoint_must_touch": true, "tolerance_px": 3}` |
| `arrow_template` invented ad hoc | strict vocabulary: straight_flow, vertical_flow, orthogonal_flow, rounded_orthogonal_flow, bezier_arc, fanout_arc, branch_arc, skip_arc_no_arrow, orthogonal_bus_no_arrow, feedback_path, feedback_loop, boundary_flow |

## edges

| wrong | correct |
|---|---|
| `fork_connector` from a plain process box | fan-out must originate from `junction_point` / `merge_bus` / `multi_port_junction`; connect source → junction first |
| `join_connector` into a plain process box | fan-in must terminate at a junction type; sources → junction → destination |
| `"route": "elbow"` / `"right_angle"` / `"diagonal"` | use: straight, straight_horizontal, straight_vertical, horizontal, vertical, orthogonal, rounded_orthogonal, hv, vh, curved, smooth_curve, loop, freeform |
| edge `label` containing `_` or `^` | move math to a `math_text` node; edge labels carry no literal sub/superscript markers |

## nodes / text

| wrong | correct |
|---|---|
| `text_block` text like `L_SPAN` | `math_text` with `math_render_mode: "fragments"` (underscore is legal encoding only inside math components) |
| long label in a tight box without wrap policy | set `"single_line": true` (or text_fit single_line) and size the box, or plan an explicit two-line layout |

## strict metadata contract (before first render)

- `metadata.source_visual_inventory`: root keys `analysis_basis`, `language_profile`, `unknown_text_policy`, plus `do_not_translate` and per-region facts.
- `metadata.region_plan`: entries with `source_bbox_px`, `review_focus`, `local_acceptance_checklist` for region-first scenes.
- `metadata.replica_review_mode: "strict_replica"`, `replica_stage`, `region_strategy` must be set.

## Renderer gotchas seen in production runs

- `text_align` is an integer for the Visio renderer, not a string like "center".
- Nested subshape coordinates may expect normalized (0-1) values, not source pixels — prefer explicit top-level geometry.
- Visio raster filters can fail on some machines; the PDF → PyMuPDF export path is the fallback.
