# Reviewer Prompt

Use this prompt when reviewing a visiomaster exact-replica round.

## Input Contract

You will receive only:

1. the original source image
2. the current replica image

Do not ask for pair images, crop packs, overlays, prior scene JSON, audit logs, or intended fixes.

If the task explicitly provides one or two targeted local crop pairs, use them only to inspect the named local defect. Do not treat a global pair/contact sheet as a substitute for the two full images, because it can downscale away fine connector, operator, formula, and text defects.

## Task

Compare the two images visually and decide whether the replica is a source-faithful reconstruction.

Focus on visible fidelity only:

- global layout and aspect
- module count and placement
- local topology
- arrow direction, landing points, and route shape (straight, orthogonal, rounded orthogonal, smooth curve, loop)
- node/component visual grammar
- text appearance
- density, spacing, and alignment
- container and boundary grammar

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
  "findings": [
    {
      "id": "F001",
      "severity": "blocking",
      "summary": "Short one-line defect title",
      "visible_diff": "Concrete visual difference between source and replica.",
      "source_appearance": "What the source visibly looks like in that area.",
      "replica_appearance": "What the replica visibly looks like in that area.",
      "impact_on_fidelity": "Why this difference matters for source-faithful reconstruction.",
      "focus_regions": ["output_right"],
      "checklist_refs": ["T001", "V001"],
      "expected_visible_change": "What should visibly change after regeneration."
    }
  ]
}
```

The checklist fields are mandatory for exact-replica reviews:

- `topology_checklist`: source-derived graph facts. Check branches, merges, shared trunks, operator order, arrow direction, arrow endpoints, boundary crossings, and required special components.
- `visual_checklist`: source-derived layout/style/visual-grammar facts. Check overlap, line-through-text, label wrapping, cell count/gap/rounding, symbol internals, sampled wave shape, math text attachment, bracket/tensor spacing, feature-stack thickness, title placement, color, rounding, line weight, and shadow.
- `status`: use `pass`, `fail`, or `uncertain`.
- `certainty`: use `certain`, `inferred`, or `uncertain`.
- Use `uncertain` instead of inventing details when a source crop is unclear.
- Every non-acceptable finding should cite failed checklist items through `checklist_refs` when possible.
- Include pass items for critical details that already match, so later rounds can avoid regressions.

## Severity

Use:

- `blocking`: the replica is visibly wrong in structure, topology, or major layout
- `important`: the replica is recognizably the same figure, but a visible subsystem is still wrong
- `general`: minor but still real visual drift
- `acceptable`: only if the difference is too small to matter visually

## Review Discipline

- If there is no concrete visual difference, return `"findings": []` and set `"overall_verdict": "acceptable"`, `"rebuild_required": false`.
- Even if there are no findings, include topology and visual checklist items for the critical regions you inspected, with statuses set to `pass` or `uncertain`.
- Do not output patch instructions.
- Do not output scene ids unless they are explicitly supplied and you are asked to reference them.
- Do not say "basically similar", "continue optimizing", or other vague summaries.
- Every finding must be grounded in what is visible in the two images.
