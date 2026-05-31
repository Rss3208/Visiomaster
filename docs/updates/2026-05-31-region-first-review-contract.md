# 2026-05-31 Region-First Review Contract

## Why

Large exact replicas were still able to look globally plausible while hiding local failures: arrow endpoints drifted, dense text wrapped, formulas degraded, or a region passed review only because the reviewer described the whole image. This update strengthens the workflow before rendering and strengthens the review output after rendering without changing the normal path for small/simple diagrams.

## Changes

- Added a hard region-first trigger for strict/exact dense figures: 30+ visible nodes, 35+ edges/arrows, 5+ formulas/tiny math labels, 3+ arrow-dense subsystems, or very wide paper layouts.
- Required dense region plans to carry `review_focus` and optional `local_acceptance_checklist` source facts.
- Added an optional `arrow_plan[].geometry_contract` for strict arrow facts such as horizontal/vertical geometry, endpoint touch, target boundary, and pixel tolerance.
- Added an editable subscene assembly rule: dense regions should remain editable scene geometry, be assembled through affine translation/scaling, and connect across regions through `boundary_port`, `junction_point`, `merge_bus`, or visible target anchors.
- Added `region_scores` scaffolding to review bundles and reviewer instructions so visual review must judge each region on arrow direction, endpoint connection, line geometry, formula fidelity, text overlap, and unexpected grid/dash fragments.
- Updated review gates so optional `region_scores` are structurally validated, and a failed region score must name concrete blocking findings.
- Propagated `region_scores` into rebuild briefs and regeneration packets so the next fresh full-scene generation sees the region-level failures.

## Files Updated

- `SKILL.md`
- `references/scene-schema.md`
- `references/reviewer-two-image-prompt.md`
- `references/review-contract.md`
- `references/full-scene-regeneration-prompt.md`
- `scripts/scene_validate.py`
- `scripts/make_review_assets.py`
- `scripts/review_checklist_gate.py`
- `scripts/review_findings_to_repair_plan.py`
- `scripts/prepare_regeneration_packet.py`

## Expected Effect

The skill should be less likely to attempt dense paper figures as one large hand-authored scene. Important arrows can now carry stricter geometry contracts before rendering, and visual review can fail a specific region instead of producing vague global comments. Python gates still do not replace visual LLM review; they only enforce that the visual review has enough structured evidence to drive the next full-scene regeneration.

## Remaining Boundaries

This update does not add new Visio geometry primitives or improve OCR/font recognition by itself. It improves the generation/review contract so existing and future components are selected and reviewed more reliably.
