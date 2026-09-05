# Defect Taxonomy (A-G)

Shared classification for review findings, repair prompts, and deterministic gates.
Introduced 2026-08 from mining 65 human correction rounds across the automated delivery
pipeline; every class below maps to real recurrence in production.

| class | name | what counts | deterministic backstop |
|---|---|---|---|
| A | arrows & connections | endpoint not touching / hanging / crossing the target, broken line body, head-only fragments, overshoot past the target, wrong direction, extra bend segments, overlapping arrows, wrong connection object | `arrow_audit_gate.py`, `arrow_micro_geometry_gate.py`, `scene_geometry_assert.py` |
| B | formulas & subscripts | subscript rendered as `_` or scattered letters, missing fraction bars, formula wrapping, superscript/subscript direction wrong, semantic formula errors | `text_render_audit.py` (R1/R2), crop review |
| C | text integrity | single-line labels wrapped, words split (`12/8`, `FF/N`), text overlapping graphics, wrong line breaks | `text_render_audit.py` (R3), crop review |
| D | missing & extra elements | source elements absent (panel-internal details, inner rules, small arrows); replica-only elements the source does not have | crop review, `scene_audit.py` child counts |
| E | raster policy | grid/matrix/cell-stack/legend-sample/simple-icon content delivered as pasted raster; unregistered `image_tile` | `raster_policy_audit.py` |
| F | layout & proportion | module position/size/margins drifting from the source | `scene_complexity.py`, region bboxes |
| G | style | color, font hierarchy, rounding, shadows, 3D character, icon fidelity | `style_calibration_gate.py`, full-page review |

## Finding fields required under `--require-sweep`

```json
{
  "id": "F003",
  "class_id": "A",
  "severity": "important",
  "summary": "two arrows into local+HG retrieval bulge at the bend",
  "similar_instance_count": 3,
  "similar_locations": ["panel b lower-left feeder", "panel a bank feed line", "output panel arrow"],
  "checklist_refs": ["T002"]
}
```

- `class_id`: one of A-G; required for every finding under the sweep gate.
- `similar_instance_count`: integer total of same-class instances page-wide (1 if unique).
- `similar_locations`: required when count > 1; for class E this is the per-tile list.

Reviewers must sweep each class page-wide before reporting; repair must fix the whole
class in one pass, not only the named instance.
