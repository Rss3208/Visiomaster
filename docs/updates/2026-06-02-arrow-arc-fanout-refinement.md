# 2026-06-02 Arrow Arc And Fanout Refinement

## Why

Follow-up visual review still found strict-replica arrow issues:

- some Bezier arcs had the right direction but hugged the source module too tightly
- fork/fanout branches were topologically correct but looked too straight compared with the source
- some source-visible lines could still use raw points instead of semantic node anchors

These are capability problems in strict replica mode, not one-off scene coordinate problems.

## Changed

- Extended opt-in Bezier arc generation in `scene_to_visio.py`.
- Added endpoint tangent controls: `source_tangent_in`, `start_tangent_in`, `target_tangent_in`, and `end_tangent_in`.
- Added fanout/branch templates: `fanout_arc`, `branch_arc`, `fanout_upper`, `fanout_lower`, `branch_upper`, and `branch_lower`.
- Added spread controls: `branch_spread_in` and `fanout_spread_in`.
- Tightened `arrow_audit_gate.py` so strict source-visible arrowless lines also need semantic side-ratio endpoints unless explicitly declared free-floating.
- Updated skill and reference docs so first-pass strict scene generation can express outward clearance and soft fanout branches directly.

## Scope Control

The renderer change is opt-in. Existing ordinary connectors and curves keep their old defaults unless an edge explicitly declares `curve_mode: "bezier"` plus `arc_template` / `arrow_template` / tangent fields.

## Remaining Boundary

Full-page layout, typography scale, and module proportions still require source-image visual review and style/layout calibration. This update improves arrow grammar expressiveness and gates endpoint stability; it does not claim pixel-perfect global layout.
