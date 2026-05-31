# 2026-05-31 Geometry, Formula, and Final Review Gates

## Why

The previous region-first update added the right workflow ideas, but three important parts were still only partly enforced:

- `geometry_contract` existed, but it mostly validated field shape and route labels. It did not independently assert visible endpoint facts such as same-y, same-x, boundary touch, or shared bus alignment.
- `region_scores` were structurally checked when present, but final strict delivery could still leave a key region as `not_reviewed`.
- Complex stacked formulas still had to be assembled from separate text boxes or ordinary `math_text`, which made fraction bars, equals signs, numerator/denominator alignment, and subscript spacing unstable.

## Changes

- Added `scripts/scene_geometry_assert.py` as an independent deterministic gate for `metadata.arrow_plan[].geometry_contract`.
- Wired `scene_geometry_assert.py --strict` into the renderer rebuild gate after `scene_validate.py --strict` and before `scene_audit.py --fail-on-rebuild`.
- Added geometry assertions for:
  - `start_y_equals_end_y`
  - `start_x_equals_end_x`
  - `must_be_horizontal`
  - `must_be_vertical`
  - `source_boundary`
  - `target_boundary`
  - `endpoint_must_touch` / `must_touch_boundary`
  - shared bus alignment through `shared_bus_id`, `shared_bus_axis`, and optional bus point index.
- Added raw endpoint checks so forced routes such as `route: "horizontal"` cannot hide a misaligned `from_point` or `to_point`.
- Fixed `tolerance_px` handling after pixel scenes are normalized to inches; the gate now uses the scene scale metadata instead of treating pixel tolerance as inches.
- Added `source_node` / `target_node` support for free-point endpoints that still must touch a declared node boundary.
- Added `shared_bus_point` selectors such as `raw_from` and `raw_to` for bus assertions that must inspect author-entered endpoints instead of post-routed points.
- Tightened strict region categorization so global review text mentioning arrows does not accidentally satisfy `arrow_dense` or `small_text` local crop coverage.
- Added `review_checklist_gate.py --final`, which fails final review if `region_scores` are missing, any region score is `not_reviewed`, or any region score remains `fail`.
- Added `math_formula_group` to the component map, schema, style profiles, effective renderer fields, strict validation, and Visio renderer.
- Implemented `math_formula_group` rendering as editable prefix/operator/fraction/suffix shapes with a stable fraction bar and compact fraction text mode.
- Changed `math_formula_group` fraction width defaults to `fit_content`, so a stacked fraction stays close to the equals sign instead of filling the whole formula group and drifting far to the right.
- Added `templates/examples/geometry_formula_contract.scene.json` to exercise geometry assertions and the new formula component together.

## Files Updated

- `SKILL.md`
- `references/scene-schema.md`
- `references/visio-component-map.md`
- `references/renderer-effective-fields.json`
- `scripts/scene_geometry_assert.py`
- `scripts/scene_validate.py`
- `scripts/scene_to_visio.py`
- `scripts/review_checklist_gate.py`
- `templates/visio_components.json`
- `templates/style_profiles.json`
- `templates/examples/geometry_formula_contract.scene.json`

## Verification

- `scene_validate.py --strict` passes for `templates/examples/geometry_formula_contract.scene.json`.
- `scene_geometry_assert.py --strict` passes for `templates/examples/geometry_formula_contract.scene.json`.
- A deliberately bad raw endpoint fixture fails `scene_geometry_assert.py --strict`, proving route projection no longer hides endpoint drift.
- Existing `templates/examples/rounded_orthogonal_connector.scene.json` still passes strict validation and geometry assertions.
- `review_checklist_gate.py --final` passes a complete reviewed-region fixture and fails a fixture containing `not_reviewed`.
- `scene_to_visio.py` exports VSDX/SVG/PNG for the formula contract example.

## Expected Effect

This should reduce the repeated failure pattern where a visually wrong arrow or formula survives because the scene is technically valid. Important arrows can now be checked against visible geometry facts before final rendering, final region review cannot silently skip a region, and stacked equations have a dedicated editable component instead of loose text fragments.

## Remaining Boundaries

The geometry gate is still a deterministic helper, not a replacement for visual LLM review. It checks declared contracts; it cannot infer every missing arrow from the source image by itself. `math_formula_group` covers common stacked fractions and aligned equations, but it is not a full LaTeX engine.
