# 2026-06-02 Strict Arrow Audit Gate

## Why

Several strict replica failures were not renderer crashes; they were arrow grammar failures that survived full-page review:

- no-arrow skip/bus lines inherited arrowheads
- straight or vertical source arrows became slightly diagonal
- source arcs were rendered as generic smooth curves with unstable tangent direction
- one fixed arrow repair left related arrows in the same region unchecked
- short dashed fragments looked like extra boxes or detached arrowheads

These are strict-replica problems. Ordinary lightweight flowcharts should not pay the cost of heavy arrow gating.

## Changed

- Added `scripts/arrow_audit_gate.py`.
- Wired it into `scene_to_visio.py` rebuild gate after `scene_validate.py --strict`.
- Added opt-in standardized Bezier arc generation in `scene_to_visio.py` for edges with `curve_mode: "bezier"` plus `arc_template` / `bezier_template` / `arrow_template`.
- Added strict arrow fields and rules in `SKILL.md` and `references/scene-schema.md`.
- Added arrow template mapping in `references/visio-component-map.md`.
- Added arrow-template fields to `references/renderer-effective-fields.json`.
- Extended `scripts/make_review_assets.py` arrow checklist entries with `expected_arrow_template`, `expected_arrowhead`, and `region_regression_group`.

## Strict Template Vocabulary

- `straight_flow`
- `vertical_flow`
- `orthogonal_flow`
- `rounded_orthogonal_flow`
- `bezier_arc`
- `skip_arc_no_arrow`
- `orthogonal_bus_no_arrow`
- `feedback_path`
- `feedback_loop`
- `boundary_flow`

The gate derives an `arrow_audit.json` or `.csv` from `metadata.arrow_plan`; the derived table is for review and must not replace the source-image arrow inventory.

For standard paper arcs, edges can now declare `curve_mode: "bezier"` and `arc_template` values such as `upper_arc`, `lower_arc`, `left_bulge`, `right_bulge`, or `small_bend_in`. The renderer expands them into stable editable Bezier control points instead of using global smooth splines.

## Blocking In Strict Mode

- source no-arrow line rendered with any arrowhead
- flow arrow missing exactly one terminal arrowhead
- dashed no-arrow route rendered with an arrowhead
- strict flow arrow using raw endpoints without freeform justification
- straight/vertical/orthogonal template rendered with wrong axes
- ordinary Bezier/skip arc rendered as generic smooth/Catmull-Rom without a source-visible freeform reason
- dangling tiny arrow fragments
- route crossing a prohibited non-endpoint node

## Scope Control

The new gate is invoked by the existing rebuild gate, which is only used for exact/strict reconstruction and GAN/TFR rebuild-sensitive scenes. The renderer defaults for ordinary `arrow_connector`, `curved_arrow`, and `line_segment` were not changed.

## Remaining Boundary

The gate checks scene contracts and routed geometry. It is still not a substitute for visual LLM review of the source image and rendered PNG, especially for exact dash rhythm, arrowhead pixel scale, and curve aesthetic match.
