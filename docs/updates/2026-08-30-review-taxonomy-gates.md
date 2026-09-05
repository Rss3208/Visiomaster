# 2026-08-30 — Defect taxonomy, review sweep, and three deterministic gates

Source of this update: mining 65 human correction rounds (26 jobs) plus 18 review-subagent
reports from the automated delivery pipeline (June-August). The classes users actually
correct — arrow micro-geometry, formula subscripts, wrapped labels, and pasted-vs-editable
content — were exactly the classes the generic review rubric reported least.

## New deterministic gates

- `scripts/text_render_audit.py` — R1 raw `_`/`^` in rendered text (math_text fragment
  encoding exempt), R2 math-like labels on plain text components (strict), R3 likely wrap
  on single-line labels, R4 text escaping its container (strict).
- `scripts/raster_policy_audit.py` — R1 unregistered raster tiles, R2 redrawable-class
  paste violations (grid/matrix/cell/token/legend/icon), R3 raster area share budget
  (8% warn / 15% strict fail).
- `scripts/arrow_micro_geometry_gate.py` — R5 endpoint overshoot past the target boundary,
  R6 head-only arrow fragments, R7 tiny off-direction corner jogs, R8 rounded routes
  without `corner_radius_px`. Source-pixel scenes only; inch scenes are skipped.

`review_checklist_gate.py --require-sweep` now fails findings that lack `class_id`
(defect taxonomy A-G) or a page-wide `similar_instance_count` / `similar_locations` sweep.

## Contract updates

- `references/defect-taxonomy.md` (new): the shared A-G classification with the
  deterministic backstop for each class.
- `references/reviewer-two-image-prompt.md`: crop-pair input widened to six
  orchestrator-selected pairs; findings carry `class_id` / `similar_instance_count` /
  `similar_locations`; raster policy added to the focus list.
- `SKILL.md`: rules 91-98 (raster policy, subscript/wrap policy, arrow micro-geometry
  contract, class sweep, post-repair verification, review resolution, findings
  persistence, strict definition of done).

## Tests

`tests/test_gates_v04.py` builds synthetic scenes with planted defects and asserts every
gate flags its class (22 cases). All gates also ran against a real delivered production
scene: arrow micro-geometry passed clean, raster audit caught one unregistered photo tile.

## Evaluation evidence (L1)

Blind A/B review on three historical image pairs with known human corrections: new-rubric
recall 83% / 92% / 100% vs old rubric 17% / 67% / 100%, no false-positive increase
(`C:\visio-worker\eval\results\l1_report.md`).
