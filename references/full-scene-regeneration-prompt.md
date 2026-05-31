# Full-Scene Regeneration Prompt

Use this prompt after a visiomaster review round fails.

## Inputs

You will receive:

1. the original source image
2. the current replica image
3. a structured `review_findings.json`
4. the visiomaster scene schema and supported component vocabulary
5. optionally, the prior scene JSON as failure evidence only

## Goal

Produce a brand-new full `scene.json` that more faithfully reconstructs the source image.

This is not a patch task.

## Hard Rules

- Rebuild the entire scene from scratch.
- Do not patch or incrementally edit the prior scene geometry.
- Do not copy old coordinates, routes, or bbox values as the starting point.
- Use the prior scene only to understand what looked wrong.
- Preserve visible source language and formulas exactly.
- If the source visually differs from the prior component choice, choose a better component family instead of nudging the old one.

## Required Working Order

1. Re-read the original source image.
2. Re-read the current replica image.
3. Read all review findings.
4. Read the topology, visual, fidelity, arrow-plan, and region-score checklists as constraints.
5. Build a fresh source visual inventory for the full figure.
6. Build a fresh `metadata.region_plan` with region-local acceptance criteria for dense areas.
7. Author a fresh full `scene.json`.

Do not skip directly from review findings to coordinate edits.

## Authoring Priorities

Before fine style tuning, lock:

1. page ratio and outer frame
2. major region layout
3. component families
4. topology and connection grammar
5. text roles and math handling

Only then tune:

- spacing
- density
- shadows
- gradients
- line weight
- small offsets

## Output Contract

Return a complete new `scene.json`.

The new scene must:

- include exact-replica metadata
- include a fresh `source_visual_inventory`
- include a fresh `region_plan`
- include `review_focus` and `local_acceptance_checklist` for dense/arrow/formula regions
- be authorable without relying on pair/crop packs
- differ materially from the prior scene in the defect areas described by review findings

## Failure Avoidance

Avoid these mistakes:

- reusing the old wrong topology with tiny coordinate changes
- preserving old generic component choices after review already said they were wrong
- translating source labels
- normalizing formulas that were visible in the source
- keeping the old scene's spacing just because it was already written

## Completion Check

Before returning the new scene, ask:

1. Did I genuinely rebuild the full scene?
2. Did I use the review findings as constraints, not as a patch checklist?
3. Would the new rendered PNG visibly change in the reported problem areas?

If any answer is no, rebuild the scene again before returning it.
