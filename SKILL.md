---
name: visiomaster
description: Windows-first Visio diagram reconstruction workflow for flowcharts, architecture diagrams, and paper-style module figures. Reuses ppt-master style analysis and composition discipline on the front half, but outputs editable Visio .vsdx plus exported .svg and .png through a scene.json to Visio pipeline. Use when the user wants a diagram recreated as editable Visio shapes instead of a pasted screenshot or PPT-only result.
---

# Visiomaster

## Overview

`visiomaster` is a standalone skill for rebuilding diagram images into editable Visio deliverables.

It is optimized for:
- flowcharts
- product or system architecture diagrams
- paper-style module/framework figures
- box-arrow process diagrams that should remain editable

It is not the right tool for:
- posters
- UI screenshots
- decorative layouts
- image-heavy slides where the main value is visual styling rather than structured diagram semantics

## Core Positioning

Use `ppt-master` ideas on the front half:
- source collection
- style extraction
- layout discipline
- image understanding
- visual polishing standards

Do **not** reuse `ppt-master`'s raw `SVG -> PPTX` output path for Visio.

For Visio, the stable path is:

`image -> scene.json -> validate -> Visio COM render -> .vsdx/.svg/.png`

The key rule is simple:
- main structure should be redrawn as editable nodes, labels, and connectors
- small thumbnails or texture snippets may remain raster only when redrawing them is not worth the loss in speed
- never solve a reconstruction request by pasting the whole original image unless the user explicitly asks for贴图

## Environment

This skill is Windows-first and expects:
- local Microsoft Visio desktop installed
- Python with `pywin32`

Use the active thread default Python interpreter. On this machine, prefer:

```powershell
C:\anaconda\envs\jht\python.exe
```

## Workflow

### 1. Confirm scope

First classify the source request:
- editable flowchart recreation
- architecture/module diagram recreation
- paper figure cleanup/redraw
- image-assisted redraw with a few raster sub-assets allowed

If the diagram is mostly boxes, arrows, labels, and containers, stay in `visiomaster`.

For image-based exact replicas, always secure a local source image file before claiming strict review readiness:
- If the user provides a filesystem path, use that path as `metadata.source_image` and all review `--original` inputs.
- If the user uploads or attaches an image without a local path, save/stage that image into the reconstruction workspace as `source/original.<ext>` before rendering the final deliverable. Do not treat a chat attachment alone as an acceptable strict-review source.
- If the current client does not expose an attached image as readable bytes and the image cannot be staged locally, clearly mark the work as a draft/manual preview and ask for a source file path before strict review or final exact delivery.
- Every exact replica must keep the staged/local source path stable across review rounds. Do not use screenshots of the replica, pair images, OCR output, or memory of the attachment as a substitute for the original source image.

When you have a source file path, stage it with the helper script so review manifests can use one stable canonical image:

```powershell
python ${SKILL_DIR}\scripts\stage_source_image.py `
  --input <source.png> `
  --workspace <reconstruction_workspace> `
  --id <figure_id>
```

This writes `source/original.<ext>` and `source/source_manifest.json` with SHA-256 hashes. Use the staged image path as `metadata.source_image` and as `make_review_assets.py --original`.

For wide or dense figures, do not start by authoring the whole page in one pass. This region-first rule is mandatory for strict/exact replicas when the source has any of these signals: 30+ visible nodes, 35+ visible arrows/edges, 5+ tiny formulas or math labels, 3+ arrow-dense subsystems, a very wide paper layout, or a dense multi-panel source where local details are unreadable at full-page scale. Simple/small diagrams do not need this ceremony.

For those large/dense sources, first create a region plan and do not author the full final scene in one pass:
- visible regions become `group_container`
- invisible logical work areas become `audit_region`
- every meaningful node gets `container_id`
- each region should usually stay under 12-18 visible nodes before whole-page assembly
- shared typography and arrow styles must be fixed before region scenes are merged
- each region should record `review_focus` and a `local_acceptance_checklist` with the concrete source facts that must pass before the region is accepted

For exact replicas, do not write `scene.json` until you have a source-faithful visual inventory for that specific image. This inventory is produced by visual LLM inspection of the source image, not by OCR, filename clues, warning logs, prior scenes, or a batch scene generator. It must preserve visible source language and notation exactly; do not translate Chinese labels to English, normalize formulas, invent unreadable text, or replace source modules with generic neural-network blocks unless the source visibly shows them.

Record the inventory in `metadata.source_visual_inventory` before the first render. At minimum it should include:
- `analysis_basis`: a short note such as `visual_llm_source_image`.
- `language_profile` and `do_not_translate`.
- `unknown_text_policy`: use `mark_unreadable_do_not_invent` for unclear tiny text.
- per-region `source_bbox_px`, required visible labels/formulas, component motifs, edge motifs, port/boundary/dashed-frame notes, uncertainty notes, and text layout facts.
- per-region `fidelity_obligations` for details that must not be simplified away, with `object`, `must_preserve`, `allowed_simplification`, and `forbidden_simplification` fields.

For strict dense replicas, add `metadata.style_calibration` before detailed authoring. This is the style contract that stops DANN-like figures from inheriting the wrong arrow thickness, dash rhythm, formula-box size, legend scale, or rotated-label scale from unrelated parts of the page. Required groups depend on the visible source content:
- `forward_arrow`: `body_width_px`, `head_width_px`, `head_length_px`, `fill`, `outline_weight_px`, `shadow_offset_px`
- `feedback_arrow`: `stroke_width_px`, `dash_length_px`, `dash_gap_px`, `arrowhead_px`, `curve_smoothness`, `z_policy`
- `formula_box`: `typical_bbox_px`, `corner_radius_px`, `padding_px`, `fraction_bar_weight_px`, `math_font_role`, `line_spacing_policy`
- `text_scale`: `body_label_pt`, `output_label_pt`, `branch_caption_pt`, `rotated_label_pt`, `formula_pt`, `legend_pt`
- `paper_3d_block`: `front_fill`, `side_fill`, `top_fill`, `hatch_density`, `shadow_offset_px`, `outline_weight_px`
- `legend`: `frame_weight_px`, `inner_arrow_scale`, `formula_sample_scale`, `text_baseline_policy`

Before choosing components, add a mandatory `metadata.visual_grammar_inventory` pass. Components are rendering grammar, not recognition conclusions. The source visual facts decide the component parameters; components must not normalize source-specific variation into a standard template.

Record facts such as:

```json
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
  "symbol_facts": ["circle plus", "triangle gate", "circular refresh arrow"],
  "wave_facts": ["polyline-like", "single peak", "noisy high frequency"],
  "text_facts": [
    {
      "role": "output_label",
      "form": "single-line label",
      "must_not_render_as": ["wrapped label", "opposite rotation direction"]
    }
  ]
}
```

Use this inventory to decide whether a source unit should become `cell_strip`, `micro_grid`, `polyline_wave`, `symbol_group`, `shape_cluster`, `primitive_group`, `ribbon_arrow`, `curved_ribbon_arrow`, `loop_ribbon_arrow`, or a higher-level semantic component. If a higher-level component would change the recorded facts, for example rectangular cells becoming rounded tokens or a sampled waveform becoming a smooth sine, switch to a primitive instead.

For source-visible thick arrows, do not normalize them into thin connectors:
- straight filled arrows use `ribbon_arrow` or the `qualitative_change_arrow` preset
- curved filled arrows use `curved_ribbon_arrow`
- cycle/update arrows that look like thick loop graphics use `loop_ribbon_arrow`
- record the required arrow body/head geometry in `must_match_facts`, and place broad ribbon arrows on `layer: "arrow_under_text"` unless the source visibly places them above labels

For source-visible dimension braces beside matrices, vertical stacks, tensors, timelines, or grouped rows/columns, use `dimension_brace` or `shape: "paper_curly"` instead of generic `shape: "curly"`. This component is a TeX-like stretch delimiter: short curled terminals, long near-vertical stems, and a small waist pinch. Generic curly braces are for merge/fusion-style grouping and can become visually wrong in high-aspect paper figures.

Use rendering layers when arrows and text overlap in the source. `z` is unified across nodes, edges, and edge labels, so an edge with `layer: "arrow_under_text"` or a negative `z` can render behind labels. Use `foreground_arrow` only when the source visibly draws an arrow above other marks.

Before authoring the first `edges` array for an exact replica, run a separate arrow-inventory pass from the source image. The goal is to lock topology before any Visio PNG exists. For arrow-dense local structures, this pass is not optional bookkeeping; it is the scene driver:
- record every source-visible arrow in `metadata.arrow_plan`
- each visible arrow or visible line segment gets its own independent `arrow_plan_id`; do not describe a whole local subgraph or multi-hop chain with one plan entry
- each entry needs `id`, `from_visual_object`, `from_anchor_description`, `to_visual_object`, `to_anchor_description`, `route_shape`, `line_style`, `arrowhead`, `semantic_intent`, `source_bbox_px`, `must_not_cross`, `relative_position_facts`, direction, endpoint/boundary facts, and certainty
- in strict replica mode, also record `arrow_template` and `arrowhead_policy`. Use the small template vocabulary instead of ad hoc curve wording: `straight_flow`, `vertical_flow`, `orthogonal_flow`, `rounded_orthogonal_flow`, `bezier_arc`, `fanout_arc`, `branch_arc`, `skip_arc_no_arrow`, `orthogonal_bus_no_arrow`, `feedback_path`, `feedback_loop`, and `boundary_flow`
- use `semantic_intent: "data_flow"` for normal flow, `"feedback"`/`"loss_backprop"` for dashed return paths, `"boundary_handoff"`/`"frame_output"` for frame-edge arrows, `"merge"`/`"fan_in"` for many-to-one joins, `"fork"`/`"fan_out"` for one-to-many branches, and `"loop_update"` for outer cycles
- use route shapes such as `straight_horizontal`, `straight_vertical`, `orthogonal`, `rounded_orthogonal`, `smooth_curve`, or `loop`; do not leave major arrows as vague `auto`
- prefer semantic endpoints such as `encoder:right@0.50 -> decoder:left@0.50`. Use raw `from_point`/`to_point` only when the source arrow is visibly free-floating, and mark that with `allow_free_endpoint` / `freeform_endpoint` in the plan or edge
- separate arrowed flow from arrowless visual lines. If the source line has no arrowhead, use `arrowhead_policy: "none"` and an arrowless template such as `orthogonal_bus_no_arrow` or `skip_arc_no_arrow`; do not rely on a default arrow style and then hope review catches it
- for strict paper/architecture arcs, use `arrow_template: "bezier_arc"` with explicit Bezier/control points unless the source is a waveform, decorative hand-drawn line, or true organic/freeform curve. If measured control points are not available yet, put `curve_mode: "bezier"` plus `arc_template: "upper_arc" | "lower_arc" | "left_bulge" | "right_bulge" | "fanout_upper" | "fanout_lower" | "small_bend_in"` on the edge so the renderer creates a deterministic editable arc. Use `source_tangent_in` / `target_tangent_in` when the source arc leaves a module with visible outward clearance; use `branch_spread_in` for fanout branches that should not look like straight spokes. Do not use `curve_mode: "smooth"` for ordinary skip arcs just to make them look rounded
- set `region` / `source_region` and, when useful, `region_regression_group` so repairs can review every related arrow in the same local subsystem after one arrow changes
- after authoring edges, bind every source-visible edge with `arrow_plan_id`
- one `arrow_plan_id` may bind to only one scene edge by default. If one source arrow truly needs multiple scene segments, every segment edge must declare `same_source_arrow: true`, `segment_index`, and `segment_count`
- when a source arrow is unreadable, mark `certainty: "uncertain"` and do not invent its destination

Treat `metadata.arrow_plan` as the source-truth checklist for later visual review: the reviewer should be able to say whether `A001`, `A002`, etc. match the original, rather than writing broad comments like "arrows are wrong". In strict mode, run `scripts/arrow_audit_gate.py <scene.json> --strict --write-audit <arrow_audit.json>` to derive the review table; do not hand-maintain a competing arrow audit file.

For attention-like motifs, decompose the visual grammar before drawing scene edges. A source crop that looks like `K/Q -> multiply -> score matrix -> value multiply -> value matrix -> Concat` is not one edge. Record the local motif, then inventory each visible connector separately, for example:
- `A101`: `K_w` right edge -> `qk_mul` left edge, horizontal, no arrowhead
- `A102`: `Q_a` right/top edge -> `qk_mul` lower-left edge, short diagonal/curved, no arrowhead
- `A103`: `qk_mul` right edge -> score matrix left edge, horizontal, arrowhead end
- `A104`: `V_w` right edge -> value multiply left edge, horizontal, no arrowhead
- `A105`: score matrix upper-right corner -> value multiply lower-left edge, diagonal, no arrowhead
- `A106`: value multiply right edge -> value matrix left edge, horizontal, arrowhead end
- `A107`: value matrix top edge -> Concat bottom edge, vertical, arrowhead end

When a local diagram matches a known motif such as `attention_score_motif`, `value_weighting_motif`, `residual_add_norm_motif`, or `concat_merge_motif`, generate the local scene from that motif grammar first. For `attention_score_motif`, Q/K feed the left-side multiply, Softmax is a floating label rather than an edge endpoint, the multiply output enters the score matrix, the score matrix connects diagonally to value multiplication, value multiplication enters the value matrix, and the value matrix outputs vertically to Concat.

For paper-style exact replicas, `source_visual_inventory` should record precise layout facts, not only module names:
- text alignment: left / center / right and baseline relation
- intended line breaks and no-wrap expectations
- whether a label is plain text, math-like, caption, annotation, or mixed CJK+math
- whether subscripts/superscripts are visible and must be preserved
- serif / sans / CJK / math font intent and visible source font if known
- whether visible shadow / glow / emphasis exists on the source text or bars
- caption prefix/body split such as bold `Fig. 6.` plus regular body
- crop obligations for that region, such as `caption`, `small_text`, or `arrow_dense`
- box/line/shadow/density facts for that region: padding, corner radius, dash rhythm, line weight, soft-shadow character, and whether the crop is visually tight or loose

For strict replica work, also mark:
- `metadata.replica_review_mode: "strict_replica"`
- `metadata.replica_stage: "layout_topology"` before the first render
- `metadata.replica_stage: "detail_polish"` only after layout/topology is already visually correct

Fresh capability evaluation means a fresh scene from the source inventory. Do not validate a skill change by patching an old scene and checking whether that old scene looks better. Old scenes and old reviews may explain failure modes, but after changing skill workflow, schema, renderer, or components, rebuild each test scene from the source image inventory. Batch exporting finished scenes is fine; batch-generating several scenes from one Python script is not valid proof that the skill works for normal users.

### 2. Build or refine `scene.json`

`scene.json` is the contract between the visual analysis step and Visio rendering.

When authoring or editing it:
- read `references/scene-schema.md`
- use `templates/visio_components.json` as the supported component vocabulary
- use `templates/style_profiles.json` to select `paper_white` or `clean_white`
- read `references/visio-component-map.md` if you need mapping guidance
- for exact replicas, author coordinates in source pixels when possible and let the renderer scale them to inches

Starter generation:

```powershell
python ${SKILL_DIR}\scripts\image_to_scene.py --image <source.png> --output <scene.json>
```

After authoring or editing a strict scene, run the advisory grammar scanner before the first validate pass. It prints each schema mistake together with the exact correct spelling (validator vocabularies, junction requirements, strict metadata fields), so grammar is fixed in one pass instead of by trial and error:

```powershell
python ${SKILL_DIR}\scripts\schema_hints.py <scene.json>
```

It is advisory only (exit 0 with hints) and never suggests content or layout; source-image analysis stays the only source of visual decisions. The full wrong→correct table lives in `references/scene-grammar-pitfalls.md`.

This script does not infer the real diagram structure from pixels. It only writes a blank or template starter scene. The actual first-pass `scene.json` for exact work must still be authored by the LLM from the source image.

For exact large-figure reconstruction, start in source pixels and record the region strategy:

```powershell
python ${SKILL_DIR}\scripts\image_to_scene.py --image <source.png> --pixel-page --region-strategy region_first --output <scene.json>
```

If the layout is close to a standard process flow, you can seed from the built-in example:

```powershell
python ${SKILL_DIR}\scripts\image_to_scene.py --image <source.png> --template basic-flow --output <scene.json>
```

Treat this as draft/bootstrap authoring only. It is not valid strict-replica proof.

For GAN/TFR training-cycle figures, AI-generated paper diagrams, or images with Real/Generated TFR panels, you may seed a draft/bootstrap pass from the canonical module template:

```powershell
python ${SKILL_DIR}\scripts\image_to_scene.py --image <source.png> --template gan-tfr --output <scene.json>
```

Do not use template-seeded scenes as final evidence for strict capability evaluation. For strict replica work, rebuild the scene from a blank source-driven authoring pass before judging the skill.

Before the first Visio render of a draft/bootstrap or legacy GAN/TFR scene, you may run the deterministic recipe pass explicitly:

```powershell
python ${SKILL_DIR}\scripts\scene_autofix.py <scene.json> --recipe gan-tfr --output <fixed.scene.json>
```

This recipe upgrades fragile local grammar before visual tuning: split Real/Generated boxes become `tfr_panel`, empty dashed loss frames become `loss_region`, raw `L_adv`/`L_rec` text becomes `math_text`, detached/broken outer loops become smooth `loop_arrow`, reversed GAN arrows are corrected, and crowded backprop arrows are bundled.

`scene_to_visio.py` no longer runs this autofix implicitly for strict/exact scenes. Use `--autofix-gan-tfr` only when you intentionally want an explicit bootstrap/render helper path, and treat the written `<basename>.autofixed.scene.json` as a non-final rewritten scene until you re-author a fresh strict-replica scene from source inventory.

For region-first exact replicas, local region work must remain editable scene geometry, not raster screenshots:
- author each dense region as editable nodes, edges, primitive groups, motif nodes, or component nodes
- wrap the region with a `group_container`, `audit_region`, or `metadata.region_plan` entry so it can be moved as one local subsystem
- during whole-page assembly, use only affine translation/scaling for the finished region geometry
- do not reroute internal region edges during full-page assembly; if internal topology is wrong, return to the local region scene/inventory
- cross-region edges should connect `boundary_port` to `boundary_port`, or a boundary port to a visible target anchor, rather than reaching into the middle of another region
- if a region was accepted locally, preserve its internal node ids and arrow-plan bindings so later review can tell whether the assembly step introduced drift

### 3. Validate scene data

Before touching Visio, validate structure and references:

```powershell
python ${SKILL_DIR}\scripts\scene_validate.py <scene.json>
```

If validation fails, fix the scene first. Do not guess around broken ids or unsupported types inside the renderer.

For large or complex figures, run a complexity preflight before full rendering:

```powershell
python ${SKILL_DIR}\scripts\scene_complexity.py <scene.json>
```

Use the complexity report to catch the large-image failure modes before Visio render: too few regions, uncovered nodes, over-dense modules, inconsistent font scale, text-fit risks, and likely overlaps.

For exact replicas, run a typography preflight when the source uses more than one visible font style:

```powershell
python ${SKILL_DIR}\scripts\font_inventory.py --check "Times New Roman" --check "Cambria Math" --check "Calibri" --check "Microsoft YaHei UI"
```

Do not treat all labels as one font. Classify visible text by role before rendering:
- paper serif labels: `font_role: "paper_serif"` with Times/Cambria-like candidates
- UI/product labels: `font_role: "ui_sans"` with Calibri/Arial/Segoe-like candidates
- formulas/operators: `font_role: "math"` or `symbol_font_role: "math"`
- Chinese labels: `font_role: "cjk_sans"` or `cjk_serif`

When the source font is known or strongly inferred, store `source_font_family` in the node style. If that font is installed but the effective render font differs, `scene_audit.py` reports it as a rebuild issue.

For complex paper figures with many modules, also generate a module-level audit report:

```powershell
python ${SKILL_DIR}\scripts\scene_audit.py <scene.json>
```

Use the audit report to review every `group_container` as a separate region: child count, labels, colors, internal arrows, incoming arrows, outgoing arrows, and whether cross-module arrows start from a boundary or from an internal component. Treat unchecked audit items as real defects before final export.

For exact replicas, run the rebuild gate after each rendered iteration:

```powershell
python ${SKILL_DIR}\scripts\scene_validate.py <scene.json> --strict
python ${SKILL_DIR}\scripts\arrow_audit_gate.py <scene.json> --strict --write-audit <arrow_audit.json>
python ${SKILL_DIR}\scripts\arrow_micro_geometry_gate.py <scene.json> --strict
python ${SKILL_DIR}\scripts\style_calibration_gate.py <scene.json> --strict
python ${SKILL_DIR}\scripts\scene_geometry_assert.py <scene.json> --strict
python ${SKILL_DIR}\scripts\text_render_audit.py <scene.json> --strict
python ${SKILL_DIR}\scripts\raster_policy_audit.py <scene.json> --strict
python ${SKILL_DIR}\scripts\scene_audit.py <scene.json> --fail-on-rebuild
```

In strict mode, missing `source_visual_inventory`, missing `region_plan`, missing strict-dense `style_calibration`, template-seeded starts, and recipe-rewritten exact scenes are treated as gate failures, not informal warnings. If validate/audit/style gates print a blocking contract failure or `[REBUILD]` item, stop coordinate nudging. Rebuild that local subsystem with the correct semantic component (`loop_arrow`, `dashed_region`, `dashed_feedback_path`, `boundary_port`, calibrated ribbon arrows, structured formula groups, etc.) before doing any more visual polishing.

In strict mode, missing `metadata.arrow_plan`, missing `arrow_plan_id` bindings, or route-shape violations are also gate failures. Do not render a strict replica whose long arrows still rely on center-to-center `auto` routing when the source shows fixed horizontal, vertical, boundary, merge, fork, feedback, or loop grammar.

In strict mode, `arrow_audit_gate.py` also treats these as blocking arrow defects: a no-arrow source line rendered with an arrowhead, a flow arrow without exactly one terminal arrowhead, a dashed no-arrow skip/bus line with an arrowhead, a strict flow arrow using raw endpoints without a freeform declaration, a straight/vertical/orthogonal template rendered with the wrong axes, a Bezier/skip arc rendered as generic smooth/Catmull-Rom without an explicit freeform reason, a dangling tiny arrow fragment, or a route crossing a prohibited non-endpoint node. These are topology/visual-grammar failures, not cosmetic issues.

When `metadata.arrow_plan[].geometry_contract` is present, run `scene_geometry_assert.py --strict` before final delivery. Use it for deterministic checks such as `start_y_equals_end_y`, `start_x_equals_end_x`, `endpoint_must_touch`, `target_boundary`, `source_boundary`, raw endpoint alignment, and shared bus alignment through `shared_bus_id` / `shared_bus_axis`. If an edge uses free `from_point` or `to_point` but still must touch a node boundary, declare `source_node` or `target_node` in the contract so the gate can compare the raw point to the intended bbox.

For exact replica work, validation passing is necessary but not sufficient. Render a PNG and compare it with the source for:
- page aspect ratio
- container bounds
- local topology
- distinctive shapes
- connector grammar
- feature-map coloring
- source-language preservation, formulas, tiny labels, ports, and arrow endpoints

Exact mode should run as a two-stage production loop, not one rushed render:
1. first render/review stage: lock layout, region bboxes, container bounds, and topology grammar
2. second render/review stage: fix text layout, caption behavior, shadows, local spacing, and visual polish

If a higher-level component stays visually wrong after two strict reviews, rebuild that local subsystem with smaller components or primitives. Do not keep nudging the whole page around one stubborn panel or text cluster.

For arrow-dense local structures, review the local crop before merging it into the full scene:
1. author a local scene such as `attention_core.scene.json` from the local source crop and motif/arrow plan
2. validate it with strict arrow-plan checks
3. render only that local scene
4. compare the local source crop and local replica crop as a pair
5. merge into the full scene only after every arrow-plan checklist item passes

Do not ship after a first-pass exact render unless the second review round is already represented and visually clean.

### 4. Render into Visio

Render the scene into a Visio drawing and export deliverables:

```powershell
python ${SKILL_DIR}\scripts\scene_to_visio.py <scene.json> --output-dir <exports>
```

Default outputs:
- `.vsdx`
- `.svg`
- `.png`

Use `--style-profile clean_white` when the user wants a polished white product/process style. Use the default `paper_white` for paper figures and academic module diagrams.

Read `references/visio-export-flow.md` when debugging Visio automation or export behavior.

After rendering complex replicas, compare the exported PNG module-by-module against the source. Do not rely on whole-image visual similarity; small topology errors often hide inside large figures.

For exact replicas, the first render is allowed to be a fast editable reconstruction pass, but the first render must be followed by at least one local-source review round before final delivery:
- Use the local/staged original image file and the exported replica PNG with `make_review_assets.py --write-review-bundle`.
- The reviewer input is the original source image plus the current replica image. Do not send a generated global pair when those two full images are already available; a global pair is only a human navigation/audit artifact and usually shrinks fine details.
- Generate local crop assets only for the regions under active doubt, such as `attention_core`, `arrow_dense`, `right_output`, `small_text`, or `caption`. Do not generate or review every crop by habit. If you generate a crop but neither a human nor the reviewer inspects it, it is only a stored debug artifact, not review evidence.
- Overlay assets are off by default. Generate overlays only when checking global alignment drift, frame offsets, or region bbox registration. Do not use overlays for arrow topology, text wrapping, operator endpoints, or formula fidelity; they tend to obscure those defects.
- During review, convert source-vs-replica visual comparison into two explicit checklists inside or alongside `review_findings.json`: a topology checklist and a visual-layout checklist.
- The topology checklist records source facts such as branches, merges, boundary crossings, operator order, arrow endpoints, and required routes. Examples: `S3 -> vertical trunk -> S1/common path`, `S2/S3 -> hollow circle -> minus`, `Linear -> f̂ -> [] -> fused feature`.
- The visual-layout checklist records overlap, label wrapping, bracket/tensor spacing, line-through-text defects, feature-stack thickness, font-role drift, and color/rounding/shadow mismatches.
- The fidelity-obligation checklist records "must not simplify" details from `fidelity_obligations`, such as worker limbs/helmets, crossed tools, neural-network node-link marks, ribbon-arrow body/head geometry, or dense icon internals.
- For region-first scenes, the review findings should also include `region_scores`. Each region should be judged on arrow direction, endpoint connection, line geometry, formula fidelity, text overlap, and unexpected grid/dash fragments. A region with a `fail` score needs a concrete `blocking_findings` item or it is not actionable.
- For strict dense replicas, full-page-only review is insufficient when these crop types exist: `arrow_dense`, `formula_dense`, `rotated_text`, `small_text`, `legend`, `paper_3d`, and `output_label`. Each one needs local visual review evidence and `region_scores`; in final mode, use `review_checklist_gate.py --final --strict-dense` so missing local coverage is treated as a review defect.
- A finding should reference the failed checklist item when possible. Do not write only broad notes such as "right output is wrong" when a specific missing branch, wrong landing point, or bracket overlap is visible.
- Repair rounds must re-check the same crop and checklist items, not only rerun validation or no-op gates.

For high-fidelity work, the reviewer should compare only two images:
- the original source image
- the current replica PNG

Do not give the reviewer pair/overlay images as the prompt when the original and replica are already available. A pair image is redundant with the two full images and often hides small connector or text defects through downscaling.

Targeted crops are allowed as secondary reviewer inputs only when the current task is explicitly local and the full images are too small to judge the detail. In that case, send the original full image, the replica full image, and the smallest useful number of local source-vs-replica crop pairs. Record which crop(s) were actually inspected. The review contract is still anchored by the two full images.

For exact/strict review packaging, call `make_review_assets.py --write-review-bundle` to write the manifest/templates. By default it does not generate global pairs, local crops, or overlays. Use:
- `--include-global-pair` only for human navigation/audit records.
- `--crops core arrow_dense caption` for hand-picked named crops.
- `--region-crops all` only when you intentionally want every `metadata.region_plan` crop pair.
- `--include-overlays` only for alignment-drift debugging.

The bundle also writes `<id>_human_review_checklist.md`. Use it as a human/visual-LLM navigation checklist for topology, visual grammar, and fidelity obligations; it is not a substitute for sending the original and replica images to a visual reviewer.

The reviewer should receive the two images and a concrete issue format. It should report specific visual differences, source appearance, replica appearance, impact on fidelity, focus regions, and the expected visible change after regeneration. Use script output only to package round evidence and to validate/export; the quality decision remains visual.

If using a separate reviewer agent, give it only the source image, the replica image, and the issue format. Do not give it intended fixes, prior conclusions, pair/crop packs, script warnings, similarity scores, or old scene JSON. The reviewer validates visual fidelity; the main agent turns that into a fresh scene rebuild.

Use the fixed reviewer prompt in `references/reviewer-two-image-prompt.md`.

Do not stop at natural-language review notes. In strict work, the review loop must produce:

1. `review_manifest.json` from `make_review_assets.py --write-review-bundle`
2. `review_findings.json` from the visual reviewer
3. `scene_rebuild_brief.json` from `review_findings_to_repair_plan.py`
4. a regeneration packet from `prepare_regeneration_packet.py`
5. a no-op proof from `round_noop_gate.py`

`review_findings.json` should contain both defect findings and the review checklists used to find them. At minimum, include:
- `topology_checklist`: visible source topology facts, each with an id, focus region, source fact, replica status, and pass/fail/uncertain status.
- `visual_checklist`: local layout/style facts, each with an id, focus region, source expectation, replica status, and pass/fail/uncertain status.
- `fidelity_checklist`: source-object details from `fidelity_obligations`, especially forbidden simplifications.
- findings that cite `checklist_refs` for failed checklist items when applicable.

Use `uncertain` instead of inventing facts when a source crop is unclear. Ask for a higher-resolution source or user confirmation only when the uncertain item affects topology or final fidelity.

After writing `review_findings.json`, run the checklist gate before generating the rebuild brief:

```powershell
python ${SKILL_DIR}\scripts\review_checklist_gate.py `
  <review_findings.json> `
  --manifest <review_manifest.json> `
  --require-failed-refs `
  --output-report <review_checklist_gate.json>
```

For final strict/region-first delivery, add `--final`. This fails if `region_scores` is missing, if any region score is still `not_reviewed`, or if a region remains failed.

Then generate the rebuild brief with checklist enforcement:

```powershell
python ${SKILL_DIR}\scripts\review_findings_to_repair_plan.py `
  <review_findings.json> `
  --scene <prior.scene.json> `
  --manifest <review_manifest.json> `
  --require-checklists `
  --output <scene_rebuild_brief.json>
```

If either command fails, fix the review findings/checklists instead of continuing with regeneration.

For arrow-dense regions, the review checklist must be per-arrow, not only per-region. Include one checklist item per `arrow_plan_id`, such as:
- `[ ] A101 K_w -> qk_mul matches source`
- `[ ] A102 Q_a -> qk_mul matches source`
- `[ ] A103 qk_mul -> score grid matches source`
- `[ ] A104 V_w -> value_mul matches source`
- `[ ] A105 score grid -> value_mul matches source`
- `[ ] A106 value_mul -> value grid matches source`
- `[ ] A107 value grid -> Concat matches source`

Blocking review findings should name the exact arrow id and mismatch class: `unbound_source_arrows`, `multi_edge_plan_misuse`, `source_anchor_mismatch`, `route_shape_mismatch`, or `motif_rule_violation`.

When one arrow in a dense region changes, run a region regression pass for every arrow sharing the same `source_region` or `region_regression_group`. Review the local crop and the derived `arrow_audit.json` rows together; do not only inspect the single arrow the user pointed out. The checklist should confirm direction, presence/absence of arrowheads, dashed/solid rhythm, endpoint boundary contact, route shape, curve smoothness, and absence of dangling half-lines for all arrows in that local group.

The no-op gate is mandatory when claiming a new round improved the scene. It fails when:
- the scene diff is metadata-only
- only weak style fields changed
- the rendered PNG pixel diff is zero

If you have a `scene_rebuild_brief.json`, pass it into `round_noop_gate.py --rebuild-brief ...` so the report keeps the focus-region and likely-scene-id evidence for that round.

Use `references/review-contract.md` for the structured review format and `references/renderer-effective-fields.json` for the current renderer-effective-field whitelist. During reauthoring, do not claim progress from notes, region-plan edits, review assets, or metadata changes alone.

Use the fixed regeneration prompt in `references/full-scene-regeneration-prompt.md` when authoring the next full scene after a failed review.

Use `scripts/prepare_regeneration_packet.py` to turn `scene_rebuild_brief.json` into a round-specific handoff packet and prompt file before the next LLM full-scene regeneration pass.
If the packet step cannot recover both reviewer image paths, stop and fix the review bundle instead of continuing with an incomplete rebuild handoff.

When several visual reviews say the replica looks like a semantic redraw instead of a source-faithful figure, stop component-level polishing and recalibrate the scene:
- mark the source image's real outer frame, titled region boxes, input/core/output bboxes, and major bus lines in source-pixel coordinates
- record those bindings in `metadata.region_plan` and on region nodes with `source_bbox_px` / `source_aspect_ratio`
- keep region-local node density close to the source before drawing small labels
- if you generate debug pairs/crops for yourself, compare only the selected focus regions and adjust region bboxes first
- only after the region bboxes match should you tune fonts, shadows, gradients, arrowheads, and individual labels

Do not replace this loop with a student/expert mode, whole-image template selector, or automatic template matching system. Reusable templates and examples are syntax references or first-pass seeds only; every high-fidelity result must still come from source-image visual analysis, source-pixel scene authoring, rendered PNG review, and visual reviewer findings.

For repeated internal layer modules, choose the visual grammar from the source crop before rendering:
- colored 2D strips: use `layer_sequence` with `block_style_mode: "colored_paper_strip"` and source-matched `block_fills`.
- if source strips are colored, preserve them with `block_fill_policy: "preserve"` or `preserve_block_fills: true`; never leave `ignore_block_fills: true` on a colored sequence.

Keep scene authoring and scene reauthoring separate:
- authoring: build the first valid scene from the source image and source visual inventory
- reauthoring: consume source/replica review findings, regenerate a fresh full scene, rerender, and prove the change with the no-op gate

After review, do not patch the prior scene when the finding says the region is semantically wrong or the topology/component grammar changed; rebuild that scene or local subsystem from the source and findings. For narrow checklist failures after the topology is already correct, a small targeted repair is acceptable, but it still must be backed by the same local source crop, updated review findings/checklist status, and a no-op gate. The prior scene may be read as failure evidence, but it must not override source-image facts.
- white 2D vertical strips: use `block_style_mode: "paper_vertical_strip"` and set `block_fill_policy: "white"` if old `block_fills` remain in the scene.
- white 3D/high vertical blocks: use `block_style_mode: "paper_vertical_cuboid"` or `white_3d`; do not convert them to colored strips just because `block_fills` exists.
- dense gate/projection/QKV modules should set `density_mode: "source_dense"` (or `dense: true`) after the region bbox is locked; do not enlarge the whole module to hide text/arrow problems.
- if the source already has a surrounding module frame and only the repeated bars are visible, set `layer_sequence.frame_visible: false` instead of drawing a second inner frame.
- if the source layer sequence has visible arrows between adjacent strips, keep them inside the component with `draw_internal_arrows: true` rather than scattering loose edge fragments.

If visual review reports text wrapping in operators, formulas, CJK labels, or rotated layer labels, treat it as a renderer/schema or scene-box defect. Do not enlarge the whole module to hide the wrap; fix the text box policy, math/operator component, local font scale, or source-coordinate label box.

Use `math_text` for hat variables such as `f̂`, `concat_operator` for visible `[]` concat brackets, and `brace_merge` for curly many-to-one merge braces. Do not model these as loose text glyphs or generic rectangles when the source shows a semantic operator/merge mark.

For compact math labels with word-like subscripts such as `a_RGB`, `P_SAR`, `q_hrrp`, `f_fused`, or `S_i`, prefer `math_text` / `math_vector` with fragment subscript rendering when the subscript contains uppercase or multi-letter tokens. Compact Unicode is only safe for digits and true Unicode subscript letters; do not render `RGB`, `SAR`, `IR`, or `fused` with superscript-looking fallback glyphs. If visual review reports letters scattered vertically, split into `fuse d`, or raised like superscripts, treat that as renderer/schema debt and fix the component or local text box before coordinate polishing.

For tensor-like feature maps, decide from the crop whether the source is a thick 3D cuboid stack, thin front-sheet stack, slanted-sheet stack, or oblique slab stack. Use `tensor_stack.stack_render_mode: "thin_feature_slabs"` for source crops with many narrow feature sheets and light perspective; use `feature_cuboids` only when the crop clearly shows thick black-edged cuboid blocks. A repeated review complaint that tensors look flat or too blocky is a component-mode error, not a coordinate issue.

For final concat marks, use `concat_operator` with `glyph_mode: "source_bracket"` when the source shows a compact heavy `[]` bracket. Use `operator_node` only for circular or text operators; a small bracket-like fusion symbol should not become a white rectangle or oversized Concat box.

For Top-k/probability panels, use `probability_bar_list` with `bar_value_label` and `bar_value_anchor: "bar_area"`, `"row"`, or `"after_bar"` based on the source crop. If bars run through the row text, reduce `bar_max_fraction` or move labels to `after_bar`; do not position row text as loose overlays or push it into bars with offsets unless the source visibly does that.
In strict replica mode, do not leave panel internals on defaults. Record padding, axis position, bar start, row alignments, baseline offsets, and explicit shadow presence or `null`.

When a defect is reported, classify it before editing:
- component problem: the chosen component family is wrong for the crop
- topology problem: branches/merges/boundaries are encoded with the wrong connection grammar
- text problem: role, baseline, rotation, math attachment, or shrink behavior is wrong
- style problem: padding, rounding, density, line weight, dash rhythm, gradient, or shadow is wrong after structure is already correct

Use one repair order for exact replicas:
1. component choice
2. topology and anchors
3. math text and rotated text
4. container/title/content proportions
5. shadows, gradients, line weight, dash rhythm

If a local subsystem is still wrong after two micro-adjustment rounds, stop nudging coordinates and rebuild that local subsystem with the correct component or renderer rule.

Treat these as blocking defects in strict replica mode:
- broken or compressed vertical strip text
- wrong or missing subscript / hat / Greek math glyph
- line crossing through visible text
- long cross-module flow that still lands center-to-center
- long paper-flow segments that stay diagonal
- concat/operator syntax rendered with the wrong component family
- repeated strips, panels, or tensor geometry still depending on hidden defaults instead of explicit scene contract
- rotated text has the wrong angle sign or reads in the opposite visual direction from the source
- source single-line labels wrap into multiple lines
- legend arrows/formula samples inherit main-diagram scale and become too heavy
- feedback dashed arrows have visibly wrong dash rhythm or oversized arrowheads
- formula boxes are more than about 20% larger/smaller than the same source role
- a formula box, arrowhead, or rotated label is visibly placed in the opposite whitespace relationship from the source

For cross-module flow, do not connect large modules center-to-center by default. Use boundary ports, buses, trunks, junctions, or explicit side anchors. For math-like text, do not keep it on plain `text_block` just because the font looks close enough; use `math_text`, `formula_text_block`, or run-based math fragments.

For environment encoders and other tapered paper modules, use `dual_wing_encoder` with `shape_mode: "opposing_trapezoids"` or `custom_polygon` when the source is pinched/notched rather than a full-height three-part block. For brace aggregation near plus/sum nodes, use `brace_merge` with `brace_shape: "tight_curly"` and `waist_width_in` instead of a generic wavy brace when the source has a tight waist.

## Component Strategy

Version 1 intentionally uses a **small controlled vocabulary** instead of trying to expose all Visio masters.

Supported node families:
- `page_background`
- `process_box`
- `rounded_process`
- `stacked_process`
- `stacked_token`
- `notched_block`
- `feature_map_banded`
- `feature_map_grid`
- `merge_bus`
- `decision_diamond`
- `terminator`
- `group_container`
- `dashed_region`
- `loss_region`
- `audit_region`
- `text_pill`
- `ellipse_node`
- `polygon_node`
- `trapezoid_node`
- `cuboid_node`
- `tensor_stack`
- `modality_spine`
- `math_vector`
- `math_text`
- `feature_vector_stack`
- `tfr_panel`
- `operator_node`
- `multi_port_junction`
- `concat_operator`
- `brace_merge`
- `boundary_port`
- `boundary_fanout`
- `wave_signal`
- `classifier_head`
- `layer_sequence`
- `text_block`
- `caption_block`
- `grid_matrix`
- `cell_strip`
- `micro_grid`
- `token_grid`
- `polyline_wave`
- `ribbon_arrow`
- `curved_ribbon_arrow`
- `loop_ribbon_arrow`
- `qualitative_change_arrow`
- `symbol_group`
- `shape_cluster`
- `primitive_group`
- `bracket`
- `dimension_brace`
- `junction_point`
- `image_tile`
- `legend_block`

Supported edge families:
- `arrow_connector`
- `dynamic_connector`
- `lane_arrow`
- `curved_arrow`
- `loop_arrow`
- `dashed_feedback_path`
- `line_segment`
- `join_connector`
- `fork_connector`
- `boundary_arrow`
- `residual_connector`
- `residual_loop`

Why this matters:
- it keeps `scene.json` stable
- it avoids binding the whole system to localized Visio stencil names too early
- it lets us start with primitive geometry rendering, then add real stencil/master mapping later without breaking the scene schema

## Execution Rules

1. Prefer editable reconstruction over screenshot embedding.
2. Recreate hierarchy first: containers, major nodes, main connectors, then secondary labels.
3. Preserve the source image's information design before chasing decorative detail.
4. Keep coordinates in `scene.json` in top-left page space; let the renderer convert to Visio coordinates.
5. If a source figure contains one non-essential photographic or map tile, isolate that asset instead of rasterizing the full page.
6. When a shape is ambiguous, fall back to the nearest supported component and note the approximation.
7. For arrows, use `route` and explicit `points`; do not rely on diagonal lines unless the source really uses diagonals.
8. For rotated paper labels, use `text_block` with `angle_deg` instead of rotating text inside a process shape.
9. For convolution kernels, receptive fields, masks, and other regular cell diagrams, use `grid_matrix`; do not manually author each square.
10. For modality grouping marks such as `]`, `[`, `U`, and inverted `U`, use `bracket`; do not fake them with ultra-thin process boxes.
10a. For thin high-aspect paper dimension braces beside a stack, matrix, tensor, timeline, or row/column group, use `dimension_brace` or `bracket` with `shape: "paper_curly"`. It should look like a TeX stretch delimiter with short curled terminals, long near-vertical stems, and a small waist pinch. Do not use Unicode `{`/`}` glyphs, raster crops, or generic `shape: "curly"` when the source shows a narrow dimension/range brace.
11. For 2-to-1, 3-to-1, or 1-to-many arrows, place a tiny `junction_point` at the merge/fan location, connect sources to the junction, then connect the junction to the destination.
12. Do not connect arrows directly to `group_container`. Containers frame regions only; use a nearby `junction_point` or explicit node on the border when a callout line is needed.
13. For brackets with a middle merge arm, set `tick_positions: [0, 0.5, 1]`; a plain two-arm bracket is not enough for modality merge symbols.
14. For cross-container flow, split the edge through `junction_point` nodes with `role: boundary_anchor`; set `allow_cross_container: true` only on the short bridge between anchors.
15. For dense mini-module diagrams, keep all connectors axis-aligned with `hv`, `vh`, or explicit aligned points. A connector must not cross through a non-endpoint node.
15a. When an exact paper-flow route has explicit points but still renders slightly diagonal, set `orthogonalize_points: true` or add the missing elbow point. Do not use `allow_diagonal: true` unless the source visibly has a diagonal callout/fan line.
16. Run `scene_validate.py` after authoring. Treat route-quality warnings as defects, not cosmetic suggestions, before rendering through Visio.
17. For repeated offset feature blocks, use `stacked_process`; do not author each visible layer as an independent process node unless each layer is a real semantic node.
18. For module interiors such as AM-ResNet, encode intended alignment with `align_to_container` or `align_group`; do not rely on eyeballed y values.
19. For source lines that are only visual stubs or bus segments, use `line_segment` with `from_point`/`to_point`. Do not force those lines to terminate on a component just because Visio can connect to shapes.
20. For 1:1 or exact replica requests, set `metadata.fidelity: "exact"` and include `metadata.source_image` or `metadata.source_aspect_ratio`. Do not deliver only because validation passes; compare the rendered PNG against the source and revise until proportions, module positions, special shapes, and connector semantics match.
21. Do not invent random feature maps, generic CNN rectangles, or approximate classifier wiring when the source has distinctive visual encodings. Encode those visual encodings explicitly with `grid_matrix`, `line_segment`, point endpoints, or isolated small raster assets when editability is less important than faithful local appearance.
22. Prefer pixel coordinate authoring for exact replicas: set `page.units: "px"`, `page.width`, `page.height`, and `page.target_width_in`; the renderer will normalize nodes and edge points to inches.
23. Use `notched_block` for CNN or cutout modules, `feature_map_banded` for simple striped/columnar feature maps, `feature_map_grid` for AM-ResNet/heatmap-like feature maps with colored rows and shaded columns, `merge_bus` for visible bus/spine merges, and `residual_connector` for residual or skip loops.
24. Use `scripts/enumerate_visio_masters.py` only to research local Visio master names. Do not hard-code a large master catalog into scenes; local Office language and stencil availability vary.
25. For paper module figures, prefer semantic primitives over generic boxes: use `operator_node` for +/x/tensor operators, `boundary_port` for frame entry/exit anchors, `boundary_fanout` for arrows emitted from a dashed frame boundary, `wave_signal` for waveform inputs, `classifier_head` for AvgPool/Linear blocks, `join_connector` for source-to-merge legs, and `fork_connector` for fan-out branches.
26. When an arrow must meet a dashed frame edge, do not connect to the frame. Place a small `boundary_port` on the frame boundary, connect internal flow to that port, then use a short bridge segment or connector to the next module.
27. Do not use `classifier_head` internal fan-out when the source shows output arrows starting on the container boundary. Set `classifier_head.output_mode: "boundary"` or omit `fanout_count`, then draw those branches with `boundary_fanout`.
28. For compact internal arrows such as `AvgPool -> Linear`, use `classifier_head.orientation: "vertical"` with `internal_arrow_size: "tiny"`, or set `arrow_size: "small"` on a normal edge. A default Visio arrowhead can consume very short line segments and appear as a head-only triangle.
29. For operator symbols, use one `operator_node` with `symbol` instead of an `ellipse_node` plus separate text. The renderer centers `+`, `×`, and `⊗` inside the circle.
30. For arrows from a frame boundary to a target component at a different vertical position, use side-ratio endpoints such as `feature_map:left@0.58` to preserve a horizontal lane. Do not accept a diagonal center-to-center edge unless the source truly shows a diagonal.
31. When the source shows the dashed frame itself exporting to the next module, use `boundary_arrow` from a `boundary_port` and do not draw an internal `line_segment` from the last component to the frame. Component-to-frame-to-component long lines are usually wrong unless visibly present in the source.
32. For ordinary 1-to-1 arrows, prefer `route: "horizontal"` or `route: "vertical"` when the source line is straight. Reserve diagonal arrows for fan-in/fan-out, callouts, or explicit source diagonals.
33. For complex figures, run `scripts/scene_audit.py` and review the generated checklist by module before delivery. The goal is to catch plausible-looking but wrong details: missing dashed frames, wrong child counts, hidden cross-frame arrows, misplaced operators, and incorrect boundary outputs.
34. If the source has no visible dashed module frames, add invisible `audit_region` nodes around logical areas such as residual block, attention block, classifier head, and feature extraction chain. These regions do not render but make `scene_audit.py` review the figure module-by-module.
35. For multimodal paper pipelines with RGB/IR/SAR inputs, preserve each modality lane as a lane: `image_tile` input, `text_pill` or `process_box` availability flag, `modality_spine` shared vertical bus, and explicit horizontal connectors into the fusion module.
36. Use `modality_spine` for vertical gray shared-response or availability-mask bars with repeated `P_RGB`/`P_IR`/`P_SAR` side ports. Do not model the bar as a plain rectangle plus unrelated tiny boxes unless each port has separate topology.
37. Use `cuboid_node` for editable 3D paper blocks such as modality-related impact factors, stacked feature tensors, and small blue/orange depth blocks. Use `feature_map_grid` only when the visible face is a grid or heatmap.
38. Use `trapezoid_node` for quality heads, extractor heads, aggregation modules, and other wedge/trapezoid paper blocks. Set `orientation` and `pointed` so the narrow side or tip matches the source direction.
39. Use `polygon_node` only when the shape cannot be expressed by `trapezoid_node`, `cuboid_node`, `notched_block`, or another semantic primitive. Include normalized points when authoring in source-pixel scenes.
40. For formula/vector annotations such as `q = [q_RGB, q_IR, q_SAR]^T`, use `math_vector` instead of a plain multi-line `text_block`. This keeps brackets, entries, and the optional prefix aligned as editable shapes/text. Do not make formula labels connector endpoints.
40a. For small variables and formula labels such as `g_tf`, `g_hrrp`, `f_fused`, `P_RGB`, `q_IR`, `s1`, `f1`, or `L_adv`, use `math_text` with `math_render_mode: "fragments"` and `text_fit: "math_label"` when the subscript has uppercase or word-like tokens. `compact_unicode` is allowed only for digit or true-subscript lowercase labels that visually match the source. Never leave them as raw text that Visio can wrap into `g_ / tf`, `f_fu / sed`, or superscript-like `RGB`.
40b. For structured formulas with a visible fraction bar, such as `ω = numerator / denominator`, use `math_formula_group` instead of several loose `math_text` nodes. It keeps the equals sign, fraction bar, numerator, denominator, and optional suffix as one editable formula group with stable baseline alignment.
41. For wide multi-panel figures, create `audit_region` nodes for every titled panel even when the visible frame is drawn with `group_container`; this lets `scene_audit.py` review inputs, outputs, and cross-panel arrows panel by panel.
42. For large source images, use `metadata.region_strategy: "region_first"` or `"tiled_subscenes"` before rendering. Also add `metadata.region_plan` entries for global/input/core/output/arrow-dense/small-text/boundary areas, each with `source_bbox_px` and a target bbox/container. If the figure is too complex to reason about at full-page scale, author each region as a local subscene, validate it, then copy the region nodes into the full scene with the same style tokens.
42a. Apply the region-first rule before full-scene authoring when a strict/exact source has 30+ visible nodes, 35+ visible arrows/edges, 5+ tiny formulas, 3+ arrow-dense subsystems, or a very wide paper layout. Write `metadata.region_plan[].review_focus` and `metadata.region_plan[].local_acceptance_checklist` before detailed node authoring. Small diagrams can stay single-scene.
42b. Treat region subscenes as editable scene fragments, not raster tiles. During assembly, translate/scale the accepted region geometry, preserve its internal node ids and `arrow_plan_id` bindings, and connect regions through `boundary_port`, `junction_point`, or visible target anchors. Do not reroute accepted internal edges during final assembly.
43. Do not let every region invent its own font sizes. Define a small scale and reuse it: frame titles, body labels, small labels, operator symbols, formula labels, and edge labels. If `scene_validate.py` reports same-type font spread, normalize the style before rendering.
44. When reconstructing from cropped subregions, keep crop-local coordinates only during analysis. Convert to the full-page pixel coordinate system before final assembly so arrows and labels do not drift at seams.
45. Use `scene_complexity.py` before full-page Visio output whenever the scene has roughly 30+ visible nodes, 35+ edges, or a very wide aspect ratio. Treat text-fit, overlap, uncovered-node, and dense-region warnings as actionable defects.
46. A region with more than 18 visible nodes is usually too dense for reliable one-pass reconstruction. Split it into smaller invisible `audit_region` areas such as input stack, feature extractor, fusion, classifier, and output head.
47. For large figures, never fix alignment only by nudging text boxes after the whole render. First enforce region-local alignment with `align_group`, `align_to_container`, explicit `container_id`, and side-ratio endpoints; then tune final positions.
48. In whole-page assembly, use cross-region edges only for true inter-module flow. Keep internal arrows inside their source region and use boundary ports or junction anchors when a connector leaves a region.
49. For short paper-flow lanes between nearby blocks, especially cube/feature blocks into extractor or GAP/GMP blocks, use `lane_arrow` with `route: "horizontal"` or `"vertical"`. Do not use `arrow_connector` with `route: "straight"` and `allow_diagonal: true` to hide small endpoint y/x mismatches.
50. If a generated diagram has arrows that look slightly tilted, inspect the scene for `straight` edges whose endpoints are almost but not exactly aligned. Convert them to `lane_arrow`, force the route axis, or align `from_point`/`to_point` exactly.
50a. When the source connector is axis-aligned but its 90-degree bends are visibly rounded, use `rounded_orthogonal_connector` with `route: "rounded_orthogonal"`, `orthogonalize_points: true`, and an explicit `corner_radius_px`/`corner_radius_in`. Do not use `smooth`/Catmull-Rom curves for this case; smooth curves change the straight lane geometry and often create waves or endpoint drift.
51. For paper wedges such as `Quality Head`, `Environment Response extractor`, and `Aggregation Quality-aware`, prefer editable `trapezoid_node`/`polygon_node` unless the user explicitly accepts a small raster tile for speed. Raster tiles should be recorded as a fidelity/speed tradeoff.
52. For GAN/training-cycle figures with a large outer curved arrow, use one `loop_arrow` or `curved_arrow` with sampled `points` and an explicit `end_tangent_point` near the arrowhead. Do not split the loop into several `line_segment` arcs plus detached short arrowheads; that causes visible breaks and wrong tangent direction.
53. For visible dashed annotation boxes such as `Forward Reconstruction -> Discriminator Evaluation`, use `dashed_region` with separate `text_block` labels. Do not use an empty dashed `process_box` as a fake frame.
54. For dashed reconstruction/adversarial/backpropagation paths, use `dashed_feedback_path` with explicit orthogonal points. Do not set `allow_diagonal: true` on loss/backprop arrows just to suppress warnings.
55. When a dashed feedback path leaves a visible dashed region, encode the exact crossing intentionally with `allow_cross_container: true` and explicit points. If the source arrow starts at the frame edge, add a `boundary_port` instead of connecting from the region center.
56. If `scene_audit.py --fail-on-rebuild` reports `[REBUILD]`, do not spend another iteration moving boxes or text. Replace the wrong local grammar first; only after the rebuild gate passes should you tune positions.
57. If the same `[REBUILD]` item appears after one attempted fix, discard that local subsystem and redraw it from a minimal local scene. This is mandatory for outer loops, dashed feedback paths, and dashed annotation frames.
58. For Visio PNG export crop control, use `page_background` as the bottom node. Do not use a fake `process_box` background, because it pollutes route intersection checks and audit output.
59. For GAN/TFR loop figures, the minimum delivery gate is: no passive ellipse used as the training loop, no detached loop arrowheads, no empty dashed process boxes, no dashed/loss/backprop route drawn as a plain `arrow_connector`, and no dashed feedback path crossing text labels.
60. In GAN/TFR diagrams, the generated/reconstructed TFR sample feeds into the Discriminator. If an edge runs `Discriminator -> Generated`, treat it as reversed unless the source explicitly marks it as discriminator output.
61. Outer update loops should use `loop_arrow` with `curve_mode: "smooth"`, enough sampled points, `semantic_role: "outer_update_loop"`, and a `label_id`/`loop_label_id` tied to the update label. Otherwise the loop reads like a decorative border.
62. Keep dashed evaluation/loss frames visually clean. A `dashed_feedback_path` should leave a `dashed_region`/`loss_region` from a boundary point or `boundary_port`; do not draw extra horizontal/vertical stubs through the region interior.
63. For bottom GAN loss/backprop systems with multiple vertical dashed arrows into the discriminator, use a shared `merge_bus`/`junction_point` and `bundle_id` rather than several unrelated vertical arrows.
64. For loss formulas such as `L_adv` and `L_rec`, use `math_text` instead of raw underscore `text_block` strings. Raw underscores are a rebuild defect in exact paper-figure replicas.
65. For Real/Generated TFR panels, use `tfr_panel` as the first-pass component. Do not split the panel into a rounded box, title labels, grid, input label, and a separate internal arrow unless there is a source-specific reason.
66. When a render looks globally close but local details do not improve after one pass, run `scene_audit.py --fail-on-rebuild` and fix every `[REBUILD]` item before visual tuning.
67. For GAN/TFR source images, use `--template gan-tfr` only for draft/bootstrap authoring. Do not treat a template-seeded scene as valid strict-replica capability evidence.
68. Before rendering a draft/bootstrap or legacy GAN/TFR scene, you may run `scene_autofix.py --recipe gan-tfr` once. If the recipe rewrites local grammar, validate and audit the fixed scene instead of continuing from the old file. For strict/exact work, do not rely on implicit render-time autofix; use `--autofix-gan-tfr` only as an explicit helper path and then re-author a fresh strict scene from source inventory.
69. Use `loss_region` for the dashed adversarial/evaluation area when the title and formulas belong to one local subsystem. Use `dashed_region` only when the frame has no formula semantics or the source requires separate child nodes.
70. When a `loss_region` and its target block overlap horizontally, route feedback as short vertical boundary stubs into `target:top@ratio` or `target:bottom@ratio`. Do not connect from loss-frame corners to `target:left/right`; that usually creates the false "dashed box plus extra arrow" artifact.
71. If the outer loop arrowhead still looks kinked after smoothing, change the semantic geometry (`end_tangent_point`, sampled points, or local loop subsystem) before nudging unrelated nodes. The arrowhead tangent is part of the component grammar, not a final polish detail.
72. Normalize GAN/TFR loss text before rendering. `Ladv`, `Lrec`, `L adv`, and `L rec` should be converted to `L_adv` / `L_rec` or explicit `math_text` fragments before export.
73. For `loss_region` titles, prefer `title_position: "inside"` or a header-cutout layout. Do not let the dashed frame cross a long title; split the title line or widen the region first.
74. For exact or GAN/TFR renders, do not call `scene_to_visio.py` as a blind final step. Run the rebuild gate first, or let the renderer's built-in gate stop the export when `[REBUILD]` items remain.
75. If a dashed feedback path looks like a tiny isolated arrow fragment, treat that as a semantic-route failure, not a cosmetic issue. Rebuild it as one `dashed_feedback_path` or a bus/port route instead of preserving the fragment.
76. Before writing edges for exact replicas, produce `metadata.arrow_plan` from source-image visual inspection. Then bind each source-visible edge with `arrow_plan_id`; run `scene_validate.py --strict` before rendering so missing arrows, diagonal drift, wrong boundary endpoints, fragmented feedback paths, and broken loop arrows fail early.
76a. For source arrows with strict geometry, add `geometry_contract` inside the `arrow_plan` entry. Use it for facts such as `must_be_horizontal`, `must_be_vertical`, `start_y_equals_end_y`, `start_x_equals_end_x`, `target_boundary`, `source_boundary`, `endpoint_must_touch`, `must_touch_boundary`, `source_node`, `target_node`, `shared_bus_id`, `shared_bus_axis`, `shared_bus_point`, and `tolerance_px`. This is stronger than a vague route label and lets `scene_geometry_assert.py` compare visible raw endpoints and routed endpoints instead of arguing about intent.
76b. Do a typography pass for exact replicas. Identify whether the source uses serif, sans, math, mono, CJK, or mixed typography before finalizing nodes; do not let every text node inherit a generic default by accident.
76c. Do a `visual_grammar_inventory` pass before component selection. First write source facts for shapes, cells, lines, symbols, waves, and text; only then choose renderer components.
76c1. For strict dense figures, write `metadata.style_calibration` before detailed node authoring and run `style_calibration_gate.py --strict` before export. Do not let feedback arrows, formula boxes, legend samples, paper 3D blocks, rotated labels, or output labels inherit unrelated main-diagram scale.
76d. For repeated small rectangular cells, use `cell_strip` or `micro_grid` with explicit `cell_count`/`rows`/`cols`, `cell_gap_in`, and `cell_rounding_in`. Do not use rounded token/grid defaults when the source facts say rectangular, continuous, or low rounding.
76e. For waveform-like details whose local silhouette matters, use `polyline_wave` with explicit `points` or `samples`. Do not let exact replicas fall back to a generic sine wave.
76f. For small icon-like structures made from circles, triangles, plus/cross marks, arcs, or local decorative lines, use `symbol_group`, `shape_cluster`, or `primitive_group` with `subshapes`. Mark internal lines with `subshape_role`/`edge_role` such as `symbol_internal`, `icon_internal`, or `decorative_internal` so topology audit does not mistake icon geometry for main flow.
77. Use `font_family_candidates` and `font_role` instead of a single fragile font name when exact family matching is uncertain. The renderer resolves to the first installed close match.
78. If the source font is known, set `source_font_family` as well as `font_family`/`font_family_candidates`. This lets audit catch the case where the font exists locally but the scene still renders with the wrong family.
79. Run `scripts/font_inventory.py` when a figure appears to use Calibri/Aptos/Arial/Times/Cambria/Chinese fonts. A missing source font should lead to a candidate list; an installed source font should be used directly.
80. Use math-capable fonts for operators and formula fragments: `Cambria Math`, `Cambria`, or `Times New Roman` depending on source style. Do not render `+`, `×`, `⊗`, or subscript formulas with a random UI font unless the source visibly does.
81. For Chinese or mixed Chinese/English diagrams, use `font_role: "cjk_sans"` or `cjk_serif`; otherwise Visio may silently substitute glyphs and shift text metrics.
82. Review the `Typography Review` section in `scene_audit.py` output before coordinate polishing. Font fallbacks can change text width and make a previously aligned layout look wrong.
83. For paper figures with repeated feature slabs, use `tensor_stack` instead of many separate `cuboid_node` shapes. Use `stack_render_mode: "slanted_sheets"`/`paper_sheets` for thin parallelogram station/output features, `oblique_slabs` for heavier 3D slabs, and `thin_sheets` for flat front-face stacks. Tune `layers`, `layer_dx_in`, `layer_dy_in`, `depth_x_in`, `depth_y_in`, and `skew_x_in` to match the visual stack while keeping it one semantic tensor node.
84. Choose cell-like primitives by source facts. Use `cell_strip` for repeated unlabeled rectangular cells in a row/column, especially continuous or low-rounding strips. Use `micro_grid` for compact matrix/tensor tiles with thin rectangular cells. Use `grid_matrix` for larger contiguous shared-line matrices without per-cell text. Use `token_grid` only when the source visibly shows readable numbers or short labels, separated token/index cells, or intentionally rounded/gapped token tiles. If the source cells are square, set `square_cells: true` and anchor with `grid_align_x`/`grid_align_y` instead of stretching cells to fill the bbox. Do not model cell groups as dozens of unrelated `process_box` nodes.
85. For titled modules containing repeated Linear/ReLU/LayerNorm/Dropout/Q/K/V bars, use `layer_sequence` with `orientation: "horizontal"` or `"horizontal_bars"`. If the source layer bars are tall 2D rounded white strips, use `block_style_mode: "paper_vertical_strip"`; use 3D/cuboid modes only when the source visibly has top/side faces. Use `classifier_head` only when the source shows classifier-specific internal arrows or fan-out; otherwise `layer_sequence` preserves the visual layer grammar with less scene drift.
85a. For containers whose internals are stacked horizontal rounded rows, such as LocalEchoGRU or shallow backbone layers, use `layer_sequence` with `orientation: "vertical_stack"` and `block_text_angle_deg: 0`. Do not represent these as side-by-side vertical bars.
85b. For compact source vectors, availability flags, small modality rows, and thin token stacks, first decide whether the visible unit is unlabeled rectangular cells, labeled token cells, or a vector with ports/brackets. Use `cell_strip`/`micro_grid` for unlabeled rectangular cell grammar, `token_grid` for readable token/index cells, and `feature_vector_stack` when labels, brackets, ports, or vector semantics are visible. Do not approximate these as one large process box if individual cells or ports are visible in the crop.
85c. For many-to-one or one-to-many paper junctions where several arrows share a visible spine, use `multi_port_junction`, `merge_bus`, or explicit `junction_point` ports. Use explicit dict ports with `length_in: 0` when the source has no visible ticks; this prevents stray short stubs at fusion/brace boundaries. Do not let long sparse arrows jump across modules without a bus, junction, boundary port, or region-plan justification.
85d. For probability panels, keep `probability_bar_list` as the semantic unit and tune `bar_max_fraction`, `bar_value_anchor`, and row widths after crop review. A pass where the blue bars visibly cross the text is not visually acceptable.
85e. For figure captions, page headers, and labels with mixed bold/regular text, use `caption_block` with ordered runs. Do not collapse them into one untyped text block when the source styling is visually important.
86. When authoring exact replicas in source pixels, give `tensor_stack`, `cell_strip`, `micro_grid`, `token_grid`, and `layer_sequence` local dimensions in source-pixel units as well. The renderer scales these fields with the page; mixing pixel node positions with inch-sized internal gaps causes visible local distortion.
87. During visual review, explicitly check whether repeated slabs, cell strips, compact grids, token grids, formulas, and internal layer sequences were expressed by source-matched semantic components. If they were faked with loose boxes and lines, or if the chosen component changes the recorded visual facts, classify the issue as scene organization or component-choice debt, not as a coordinate polish problem.
88. During visual review, inspect local crops for text and formula wrapping. Broken `GELU`, `LayerNorm`, CJK labels, or subscript variables are blocking/important visual defects even if validate/audit passes. Fix with role-specific fonts, `text_fit`, smaller local font scales, or `math_text`; do not hide the problem by enlarging the whole module.
89. For labels such as `f_tf`, `g_hrrp`, `f_fused`, and `S_i`, use `math_text` or `math_label_box` so only the visible variable is the base and the rest is subscript. If visual review reports `f_t^f`-like rendering, split letters, or `fuse d` spacing, classify it as formula rendering failure.
90. For every complex figure iteration, record the reviewed images, main visual differences, cross-image common issues, skill changes, improved/unchanged/regressed figures, and remaining failures. A global contact sheet can help navigation but is not valid evidence for fine-detail acceptance. Prefer two full images plus targeted local crops over global pair images for fine-detail review.
91. Raster/paste policy: every geometric or rule-regular graphic (grid tables, matrices, color-block stacks, legend samples, simple icons, process boxes, arrows) must be rebuilt as editable components. `image_tile` is allowed only for photographic, complex-bitmap, or otherwise-unreadable source content, and every tile must register `justification` (`photographic` / `complex_bitmap` / `source_unreadable_otherwise`) plus `source_bbox_px`. Keep total raster area under 8% of the page or justify it in the delivery notes. Enforce with `scripts/raster_policy_audit.py <scene.json> --strict`.
92. Subscript and wrap policy: rendered text must never contain a literal `_` or `^`; word-like subscripts (`L_adv`, `P_RGB`, `f_fused`) belong on `math_text` fragments. Source single-line labels must declare `single_line`/`no_wrap` and must not wrap; never hide a wrap by enlarging the whole module. Enforce with `scripts/text_render_audit.py <scene.json> --strict`. Inside `math_text` the underscore is legal fragment encoding; the audit exempts math components for that reason.
93. Arrow micro-geometry contract: before delivery, every edge must visibly touch its target boundary without overshooting past it, must not render as a bare arrowhead with no line body, and orthogonal routes must not carry tiny off-direction jogs at bends. Enforce with `scripts/arrow_micro_geometry_gate.py <scene.json> --strict` (source-pixel scenes only). Full-page review cannot reliably see a few pixels of line body, so this gate is the deterministic backstop for that defect class.
94. Class sweep: when a review finds one defect instance, it must answer "how many more of the same class exist page-wide". Record this as `class_id` (defect taxonomy A-G, see `references/defect-taxonomy.md`), `similar_instance_count`, and `similar_locations` on each finding, and repair all same-class instances in one pass. Enforce completeness with `review_checklist_gate.py --require-sweep`.
95. Post-repair verification: repair all planned defect classes first, then re-render once and verify every repaired region through source-vs-replica crop pairs in a single batched pass. Only a region that fails verification gets a targeted extra render cycle (at most two). Do not re-render once per class; Visio export is the most expensive operation in the loop.
96. Review resolution: `arrow_dense`, `formula`, and `small_text` regions must be reviewed through local crop pairs, not from the full page alone. A full-page pass is only the anchor; A/B/C-class defects are confirmed at crop scale.
97. Findings persistence: every review round must persist its structured conclusion as `review_findings.json` (the main session writes it when the reviewer runs in a clean subagent). A review that leaves no findings file is a process failure, because the next round cannot diff against it.
98. Definition of done (strict mode): all strict gates green (`scene_validate`, `arrow_audit_gate`, `arrow_micro_geometry_gate`, `style_calibration_gate`, `scene_geometry_assert`, `scene_audit --fail-on-rebuild`, `text_render_audit`, `raster_policy_audit`), `review_checklist_gate` passing with `--require-sweep` where findings exist, `round_noop_gate` proving the final round changed pixels, and the three deliverable files present and non-empty.

## References

- `references/scene-schema.md`: `scene.json` fields and coordinate rules
- `references/scene-grammar-pitfalls.md`: wrong→correct table for strict scene grammar (directions, junctions, strict metadata fields, renderer gotchas)
- `scripts/schema_hints.py`: advisory authoring-time scanner that prints each grammar mistake with its exact correct spelling
- `references/visio-component-map.md`: supported components and renderer intent
- `references/visio-export-flow.md`: Windows + Visio export path and current limitations
- `templates/style_profiles.json`: `paper_white` and `clean_white` rendering profiles
- `templates/examples/basic_flow.scene.json`: starter example
- `templates/examples/multimodal_paper_components.scene.json`: smoke example for multimodal spines, cuboids, trapezoids, and polygons
- `templates/examples/gan_loop_feedback.scene.json`: smoke example for smooth loop arrows, dashed regions, and dashed feedback paths
- `templates/examples/gan_tfr_full.scene.json`: canonical first-pass GAN/TFR template using `tfr_panel`, `loss_region`, `math_text`, smooth `loop_arrow`, and bundled backprop arrows
- `scripts/scene_complexity.py`: preflight report for large/dense figures before Visio rendering
- `scripts/font_inventory.py`: local Windows font inventory and preferred role fallback check
- `scripts/stage_source_image.py`: copies a source image into `source/original.<ext>` and records hashes for stable strict review manifests
- `scripts/review_checklist_gate.py`: validates `topology_checklist`, `visual_checklist`, `fidelity_checklist`, local source-image paths, and `checklist_refs` before rebuild planning; `--require-sweep` enforces per-finding class sweep completeness
- `scripts/text_render_audit.py`: deterministic audit for raw `_`/`^` text, math labels on plain text components, likely single-line wraps, and container overflow
- `scripts/raster_policy_audit.py`: deterministic audit for unregistered raster tiles, redrawable-class paste violations, and raster area share
- `scripts/arrow_micro_geometry_gate.py`: deterministic audit for endpoint overshoot, head-only arrow fragments, and corner spurs
- `references/defect-taxonomy.md`: the A-G defect classification shared by review prompts and gates
- `scripts/scene_autofix.py`: deterministic GAN/TFR local grammar upgrade pass before Visio rendering
- `docs/updates/2026-05-19-multimodal-paper-figure.md`: detailed analysis of a complex multimodal paper figure and the related component upgrade

## Current Boundaries

Version 1 is deliberately conservative:
- connectors support auto snap, orthogonal routing, and explicit points before full glue-aware connectors
- core flowchart shapes use local Visio masters when available, with controlled fallbacks
- export is handled by Visio after scene rendering rather than by translating raw SVG into Visio

That is the right tradeoff for a reusable first release.
