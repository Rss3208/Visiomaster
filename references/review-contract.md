# Review Contract

`visiomaster` review is only useful when it produces actionable visual findings. The primary reviewer inputs are always the original source image and the current replica image. Pair/crop/overlay images are optional debug aids, not default reviewer inputs.

Use these external files for every exact-replica round:

- `review_manifest.json`: generated next to the review assets. It records the two reviewer image inputs and optional debug assets.
- `review_findings.json`: written by the visual reviewer. This is the first machine-readable output of the visual comparison.
- `scene_rebuild_brief.json`: derived from the findings. This is the execution contract for the next full-scene regeneration.

These files live outside `scene.json`. They do not replace scene authoring; they make the rebuild loop explicit.

## Source Image Contract

Exact-review rounds require a local original image path.

- If the user provides a filesystem path, use that file as the canonical `original`.
- If the user only uploads an image, stage the attachment into the reconstruction workspace, for example `source/original.png`, before rendering the final exact deliverable.
- Do not run or claim strict review from memory of a chat attachment, OCR text, a screenshot of the source, or a pair/crop image. `make_review_assets.py --original` must receive the real local source image.
- If the attachment cannot be saved or otherwise recovered as a local file, mark the result as a draft/manual preview and request a source file path before final strict review.
- Keep the same local original path stable in every review manifest for the figure unless the user intentionally provides a higher-quality source.

Recommended staging command:

```powershell
python scripts\stage_source_image.py `
  --input source.png `
  --workspace figure_workspace `
  --id figure_01
```

Use the staged `figure_workspace\source\original.<ext>` as `make_review_assets.py --original`.

## Review Manifest

Generate the review bundle first. This default command writes the manifest/templates and records the two full-image paths; it does not create pair/crop/overlay debug images unless optional flags are added:

```powershell
python scripts\make_review_assets.py `
  --original source.png `
  --replica export.png `
  --scene scene.json `
  --id figure_01 `
  --round 2 `
  --write-review-bundle `
  --output-dir review_round_02
```

The reviewer should receive these two full images:

- the original source image
- the current replica image

Do not send a global pair image when those two full images are already available. A global pair is a convenience contact sheet for humans, but it downscales both sides and can hide small arrow endpoints, operator circles, formula subscripts, or text wrapping.

Targeted local crops are optional secondary inputs only when the defect under review is too small to judge from the full images. Use the smallest useful set of crop pairs, such as one attention-core crop for connector/arrow issues or one caption crop for footer typography. Record the crop ids or paths that were actually inspected. Crops that were generated but not inspected are not review evidence.

Overlay images should not be sent to the reviewer by default. They are only useful for checking alignment drift, frame offset, or region bbox registration. For topology, text, formula, arrow, and component grammar defects, overlays usually obscure the problem.

The manifest is optional reviewer context. It should not add pair/crop/overlay images to the reviewer prompt by default. It only tells the workflow:

- which two image paths belong to this round
- what the figure id and round number are
- which fields every finding must contain
- which optional debug assets exist, if any, and which ones were actually inspected

Use the fixed reviewer prompt in:

- `references/reviewer-two-image-prompt.md`

## Optional Debug Asset Policy

`make_review_assets.py --write-review-bundle` defaults to manifest/template generation plus the two full-image paths. It intentionally does not generate global pairs, local crops, or overlays unless asked.

Use optional assets narrowly:

- `--include-global-pair`: generate a global contact sheet for human navigation or archival evidence only.
- `--crops <names...>`: generate selected named crop pairs for active local doubts.
- `--region-crops all`: generate all scene `metadata.region_plan` crop pairs only when a deliberate exhaustive local review is needed.
- `--include-overlays`: generate overlays only for alignment-drift checks.

Avoid producing large review directories full of images that no one inspects. They create false confidence and make it unclear which evidence actually drove the repair.

## `review_findings.json`

The visual reviewer writes concrete diffs in this format:

```json
{
  "figure_id": "crosssite_attention",
  "round": 2,
  "overall_verdict": "needs_rebuild",
  "rebuild_required": true,
  "topology_checklist": [
    {
      "id": "T001",
      "focus_region": "projection_private_path",
      "source_fact": "S3 right output has a vertical upward branch joining the S1/common trunk.",
      "replica_status": "Missing in replica.",
      "status": "fail",
      "certainty": "certain"
    }
  ],
  "visual_checklist": [
    {
      "id": "V001",
      "focus_region": "right_outputs",
      "source_expectation": "The [] concat bracket is separated from the fused feature stack.",
      "replica_status": "The bracket overlaps the feature stack.",
      "status": "fail",
      "certainty": "certain"
    }
  ],
  "fidelity_checklist": [
    {
      "id": "F001",
      "focus_region": "icon_row",
      "source_expectation": "Worker icons preserve helmets, limbs, and workwear color split; they are not simplified to generic person blobs.",
      "replica_status": "Not reviewed.",
      "status": "uncertain",
      "certainty": "certain"
    }
  ],
  "region_scores": [
    {
      "region_id": "output_right",
      "scores": {
        "arrow_direction": "fail",
        "endpoint_connection": "fail",
        "line_geometry": "uncertain",
        "formula_fidelity": "not_applicable",
        "text_overlap": "pass",
        "unexpected_grid_or_dash": "pass"
      },
      "blocking_findings": ["D001"]
    }
  ],
  "findings": [
    {
      "id": "D001",
      "severity": "blocking",
      "summary": "Right-side output topology is wrong",
      "visible_diff": "The source has a vertical Linear -> inverse projection -> f-hat -> bracket merge chain. The replica keeps a horizontal capsule-like Linear node and the merge landing point is wrong.",
      "source_appearance": "A vertical right-side projection chain ending in a bracket merge.",
      "replica_appearance": "A horizontal capsule-style output block with the merge landing in the wrong place.",
      "impact_on_fidelity": "The whole output grammar is wrong even though the labels are partially recognizable.",
      "focus_regions": ["output_right"],
      "checklist_refs": ["T001", "V001"],
      "expected_visible_change": "Restore the vertical output chain and rejoin at the bracket merge."
    }
  ]
}
```

The checklist fields are the reviewer's source-derived acceptance criteria:

- `topology_checklist` is for visible source graph facts: arrow direction, endpoints, route shape, branches, merges, shared trunks, boundary crossings, operator order, and required special components. It is not a schema check; it comes from visual comparison of the original source and replica.
- `visual_checklist` is for local appearance and visual grammar facts: overlap, line-through-text, label wrapping, cell count/gap/rounding, symbol internals, sampled wave shape, bracket/tensor spacing, tensor thickness, title position, font role, line weight, color, rounding, and shadow.
- `fidelity_checklist` is for source-object obligations that must not be simplified away: worker/person details, crossed tools, node-link motifs, dense device icons, and ribbon-arrow body/head geometry.
- `region_scores` is for region-first exact scenes. Each region can score `arrow_direction`, `endpoint_connection`, `line_geometry`, `formula_fidelity`, `text_overlap`, and `unexpected_grid_or_dash` as `pass`, `fail`, `uncertain`, `not_reviewed`, or `not_applicable`. A `fail` score must list concrete finding ids in `blocking_findings`; otherwise the region review is not actionable.
- `status` should be `pass`, `fail`, or `uncertain`. Use `uncertain` when the source crop is unclear; do not invent topology.
- Findings should cite failed checklist ids through `checklist_refs` when possible.
- A review may include passing checklist items. They help later rounds avoid regressing details that already match.

For strict dense replicas, these crop types require local review before final when they exist in the source/scene: `arrow_dense`, `formula_dense`, `rotated_text`, `small_text`, `legend`, `paper_3d`, and `output_label`. Full-page-only review is not enough for these categories. Use `review_checklist_gate.py --final --strict-dense` with the review manifest so missing local `region_scores` coverage is caught as a review defect.

Also treat these as blocking in strict replica mode:

- rotated text has the wrong angle sign or reads in the opposite visual direction from the source
- source single-line labels wrap into multiple lines
- legend elements inherit main-diagram scale and become too heavy
- feedback dashed arrows have visibly wrong dash rhythm or oversized arrowheads
- formula boxes are more than about 20% larger/smaller than the same source role
- a formula box, arrowhead, or rotated label is visibly placed in a whitespace relationship opposite to the source

When the scene includes `metadata.arrow_plan`, the topology checklist should reference those arrow ids whenever possible. For example, report `A003 fails: source is a horizontal boundary-to-module arrow, replica lands on the module center and becomes diagonal`. Do not collapse several arrow defects into one broad note such as "arrows are wrong"; the rebuild brief needs per-arrow evidence.

When the scene includes `metadata.region_plan[].local_acceptance_checklist`, use those region-local facts as the visible acceptance criteria. A global verdict is not enough; the reviewer should say which region fails and whether the failure is arrow direction, endpoint connection, line geometry, formula fidelity, text overlap, or unexpected grid/dash artifacts.

Required fields:

- `id`
- `severity`
- `summary`
- `visible_diff`
- `source_appearance`
- `replica_appearance`
- `impact_on_fidelity`
- `focus_regions`
- `expected_visible_change`

The reviewer should describe image differences only. It should not write renderer code, scene JSON, or prose-only advice like "continue improving".

If you are converting an older patch-oriented review file, the rebuild script will still accept fields such as `region`, `target_ids`, and `patch_kind`, but it will downgrade them into failure evidence only. They are no longer execution instructions.

## `scene_rebuild_brief.json`

Build it from the findings. The script keeps its historical filename for compatibility, but the output is now a full-scene rebuild brief:

```powershell
python scripts\review_checklist_gate.py `
  review_round_02\figure_01_review_findings.json `
  --manifest review_round_02\figure_01_review_manifest.json `
  --require-failed-refs `
  --output-report review_round_02\figure_01_review_checklist_gate.json
```

Then:

```powershell
python scripts\review_findings_to_repair_plan.py `
  review_round_02\figure_01_review_findings.json `
  --scene scene.json `
  --manifest review_round_02\figure_01_review_manifest.json `
  --require-checklists `
  --output review_round_02\figure_01_scene_rebuild_brief.json
```

Do not continue to rebuild planning if `review_checklist_gate.py` fails. Fix the reviewer output first: missing local source image path, empty checklists, invalid statuses, or findings that do not cite failed checklist items are review defects, not scene defects.

For final strict dense delivery, run the stricter review gate after the last visual review says the figure is acceptable:

```powershell
python scripts\review_checklist_gate.py `
  review_round_final\figure_01_review_findings.json `
  --manifest review_round_final\figure_01_review_manifest.json `
  --require-failed-refs `
  --final --strict-dense `
  --output-report review_round_final\figure_01_review_checklist_gate.json
```

`scene_rebuild_brief.json` does not choose among patch modes. It always instructs the next authoring round to:

- rebuild the full scene from the original image and review findings
- avoid copying prior-scene coordinates or routes
- treat the prior scene only as failure evidence
- preserve source language and visible formulas exactly

Use the fixed regeneration prompt in:

- `references/full-scene-regeneration-prompt.md`

Before the next LLM authoring pass, package the rebuild brief into a round-specific regeneration handoff:

```powershell
python scripts\prepare_regeneration_packet.py `
  review_round_02\figure_01_scene_rebuild_brief.json `
  --output-dir review_round_02
```

This writes a JSON packet plus a prompt file that bundles:

- the original image path
- the current replica image path
- the rebuild brief and findings digest
- the fixed regeneration prompt reference
- the scene schema / review contract references needed for the next full-scene authoring pass

`prepare_regeneration_packet.py` expects both reviewer image paths to be recoverable from the rebuild brief, findings, or manifest. If they are missing, the script fails by default instead of silently producing an incomplete handoff.

## No-Op Gate

After regenerating and rerendering, run the hard round gate:

```powershell
python scripts\round_noop_gate.py `
  --before-scene round_01.scene.json `
  --after-scene round_02.scene.json `
  --before-png round_01.png `
  --after-png round_02.png `
  --rebuild-brief review_round_02\figure_01_scene_rebuild_brief.json `
  --output-report review_round_02\figure_01_noop_gate.json
```

This gate fails the round when:

- the scene diff is metadata-only
- only weak style fields changed
- the rendered PNG pixel diff is zero

It also records scene SHA-256 hashes and optional rebuild-brief target-hint diagnostics. Those hint checks are evidence only; full-scene rebuilds may rename ids.

The no-op gate is not a quality judge. It only answers one question: did the regenerated scene actually produce a different diagram?

## Rebuild Policy

After every failed visual review, rebuild the whole scene.

- do not patch the prior scene
- do not reuse old coordinates as the starting point
- do not decide between local patch and local rebuild
- use the prior scene only to understand failure modes

This is intentionally blunt. The first scene already comes from LLM-based visual authoring, so the second scene should also come from LLM-based visual re-authoring instead of incremental JSON surgery.
