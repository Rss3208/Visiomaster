# Reviewer Prompt

Use this prompt when reviewing a visiomaster exact-replica round.

## Input Contract

You will receive only:

1. the original source image
2. the current replica image

Do not ask for pair images, crop packs, overlays, prior scene JSON, audit logs, or intended fixes.

If the task provides targeted local crop pairs (at most six, chosen by the orchestrator from arrow-dense, formula, and small-text regions), use them to confirm A/B/C-class defects at crop scale. Do not treat a global pair/contact sheet as a substitute for the two full images, because it can downscale away fine connector, operator, formula, and text defects.

## Task

Compare the two images visually and decide whether the replica is a source-faithful reconstruction.

Do not only describe global similarity. If a region checklist, region id, crop intent, or local acceptance checklist is provided as context, inspect each region separately and answer whether that region passes. A globally similar figure can still fail when one local region has wrong arrows, broken formulas, line-through-text, or unexpected dashed/grid fragments.

Focus on visible fidelity only, sweeping each class from `references/defect-taxonomy.md` page-wide:

- global layout and aspect
- module count and placement
- local topology
- arrow direction, landing points, route shape (straight, orthogonal, rounded orthogonal, smooth curve, loop), endpoint contact, breaks, overshoot, head-only fragments, and corner spurs
- formula and subscript rendering (raw `_`/`^`, split subscripts, missing fraction bars)
- text integrity (wrapped single-line labels, split words, text-over-graphic overlap)
- missing and extra elements, including small panel-internal details
- raster policy: grid/matrix/cell-stack/legend-sample/simple-icon content that ships as a pasted image is a defect; only photographic or complex-bitmap content may stay raster
- node/component visual grammar
- density, spacing, and alignment
- container and boundary grammar
- strict dense local details: arrow_dense, formula_dense, rotated_text, small_text, legend, paper_3d, and output_label areas when present

Do not judge by semantic similarity alone. If the source uses a specific visual grammar and the replica uses a generic substitute, report it as a defect.

## Output Rules

Return JSON only. No prose before or after the JSON.

Use this schema:

```json
{
  "figure_id": "<same figure id>",
  "round": 2,
  "overall_verdict": "needs_rebuild",
  "rebuild_required": true,
  "reviewer_inputs": {
    "original_path": "<path if provided>",
    "replica_path": "<path if provided>"
  },
  "topology_checklist": [
    {
      "id": "T001",
      "focus_region": "arrow_dense",
      "source_fact": "Concrete source-visible graph/topology fact, such as a branch, merge, shared trunk, operator order, boundary crossing, or arrow endpoint.",
      "replica_status": "Whether the replica matches, misses, reverses, misroutes, or ambiguously renders that fact.",
      "status": "pass",
      "certainty": "certain"
    }
  ],
  "visual_checklist": [
    {
      "id": "V001",
      "focus_region": "right_outputs",
      "source_expectation": "Concrete source-visible layout/style fact, such as non-overlap, label placement, tensor thickness, bracket spacing, color, rounding, or line-through-text avoidance.",
      "replica_status": "Whether the replica matches, overlaps, wraps, drifts, or ambiguously renders that fact.",
      "status": "fail",
      "certainty": "certain"
    }
  ],
  "fidelity_checklist": [
    {
      "id": "F001",
      "focus_region": "icon_or_ribbon_detail",
      "source_expectation": "Concrete source-object detail that must not be simplified, such as visible nodes/links, crossed tools, worker limbs/helmet, or thick ribbon arrow head/body geometry.",
      "replica_status": "Whether the replica preserves, simplifies, omits, or ambiguously renders that detail.",
      "status": "uncertain",
      "certainty": "certain"
    }
  ],
  "region_scores": [
    {
      "region_id": "arrow_dense",
      "scores": {
        "arrow_direction": "fail",
        "endpoint_connection": "fail",
        "line_geometry": "uncertain",
        "formula_fidelity": "not_applicable",
        "text_overlap": "pass",
        "unexpected_grid_or_dash": "fail"
      },
      "blocking_findings": ["F001"]
    }
  ],
  "findings": [
    {
      "id": "F001",
      "severity": "blocking",
      "class_id": "A",
      "summary": "Short one-line defect title",
      "visible_diff": "Concrete visual difference between source and replica.",
      "source_appearance": "What the source visibly looks like in that area.",
      "replica_appearance": "What the replica visibly looks like in that area.",
      "impact_on_fidelity": "Why this difference matters for source-faithful reconstruction.",
      "focus_regions": ["output_right"],
      "checklist_refs": ["T001", "V001"],
      "similar_instance_count": 1,
      "similar_locations": [],
      "expected_visible_change": "What should visibly change after regeneration."
    }
  ]
}
```

The checklist fields are mandatory for exact-replica reviews:

- `topology_checklist`: source-derived graph facts. Check branches, merges, shared trunks, operator order, arrow direction, arrow endpoints, boundary crossings, and required special components.
- `visual_checklist`: source-derived layout/style/visual-grammar facts. Check overlap, line-through-text, label wrapping, cell count/gap/rounding, symbol internals, sampled wave shape, math text attachment, bracket/tensor spacing, feature-stack thickness, title placement, color, rounding, line weight, and shadow.
- `fidelity_checklist`: source-object obligations that must not be simplified away. Check worker/person details, crossed tools, neural-network node-link motifs, dense device/icon internals, and thick/ribbon arrow body-head shape.
- `region_scores`: per-region review status when region context is provided. For every region, answer whether arrow directions are correct, endpoints visibly connect to the right boundary/port, horizontal/vertical/curved lines match the source, formulas render as formulas rather than raw `_`/`^` text, text overlaps are absent, and there are no unexpected grids, dashed fragments, broken connector gaps, or stray arrow stubs. Use `pass`, `fail`, `uncertain`, `not_reviewed`, or `not_applicable`.
- For strict dense replicas, full-page-only review is insufficient for `arrow_dense`, `formula_dense`, `rotated_text`, `small_text`, `legend`, `paper_3d`, or `output_label` regions. If those regions are supplied, inspect them locally and include `region_scores`.
- `status`: use `pass`, `fail`, or `uncertain`.
- `certainty`: use `certain`, `inferred`, or `uncertain`.
- `class_id`: one of the taxonomy classes A-G (see `references/defect-taxonomy.md`); required for every finding.
- `similar_instance_count`: after finding one instance, sweep the whole page for the same class and report the total count (1 if unique). Do not report only the first instance you see.
- `similar_locations`: list the other same-class locations when `similar_instance_count` > 1; for class E findings this is the per-tile verdict list.
- Use `uncertain` instead of inventing details when a source crop is unclear.
- Every non-acceptable finding should cite failed checklist items through `checklist_refs` when possible.
- Every region score with `fail` must cite concrete finding ids in `blocking_findings`; do not mark a region failed without saying what visible defect caused the failure.
- Include pass items for critical details that already match, so later rounds can avoid regressions.

## Severity

Use:

- `blocking`: the replica is visibly wrong in structure, topology, or major layout
- `important`: the replica is recognizably the same figure, but a visible subsystem is still wrong
- `general`: minor but still real visual drift
- `acceptable`: only if the difference is too small to matter visually

Treat these as blocking in strict replica mode:

- rotated text has the wrong angle sign or reads in the opposite visual direction from the source
- source single-line labels wrap into multiple lines
- legend elements inherit main-diagram scale and become too heavy
- feedback dashed arrows have visibly wrong dash rhythm or oversized arrowheads
- formula boxes are more than about 20% larger/smaller than the same source role
- a formula box, arrowhead, or rotated label is visibly placed in a whitespace relationship opposite to the source

## Review Discipline

- If there is no concrete visual difference, return `"findings": []` and set `"overall_verdict": "acceptable"`, `"rebuild_required": false`.
- Even if there are no findings, include topology and visual checklist items for the critical regions you inspected, with statuses set to `pass` or `uncertain`.
- Do not output patch instructions.
- Do not output scene ids unless they are explicitly supplied and you are asked to reference them.
- Do not say "basically similar", "continue optimizing", or other vague summaries.
- Every finding must be grounded in what is visible in the two images.
