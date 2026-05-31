# 2026-05-31 Style Calibration Gate

## Why

DANN-style paper figures exposed a capability gap that was not just coordinate drift:

- dashed feedback arrows could inherit thick main-arrow styling and become oversized
- formulas with visible fractions could degrade into plain multiline text
- legend samples could inherit main-diagram scale
- rotated labels could have the wrong direction without any hard contract
- full-page review could miss small local defects in arrow/formula/legend/output regions

## Changed

- Added `scripts/style_calibration_gate.py`.
- Wired the gate into `scripts/scene_to_visio.py` before geometry/audit rebuild checks.
- Added `metadata.style_calibration` documentation for strict dense replicas.
- Upgraded `metadata.visual_grammar_inventory` examples to object facts with `must_not_render_as`.
- Added strict blocking defects for rotated text, wrapped source labels, legend over-scaling, feedback dash rhythm, formula-box size drift, and opposite whitespace relationships.
- Added `review_checklist_gate.py --strict-dense` crop coverage checks for final review.
- Improved review asset checklist generation for object-form visual grammar facts.

## Scope

The new hard gate applies only to strict/exact dense replicas. Ordinary small diagrams and simple flowcharts can omit `metadata.style_calibration` and continue through the normal pipeline.

## Remaining Boundary

This gate checks authoring contracts and component choice; it does not replace two-image visual review. A calibrated scene can still be visually wrong if the source inventory or scene geometry is wrong.
