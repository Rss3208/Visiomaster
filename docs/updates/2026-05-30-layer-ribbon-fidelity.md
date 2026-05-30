# 2026-05-30 Layer, Ribbon Arrow, and Fidelity Gate Update

## Why

The current replica failures showed three system-level issues:

- broad or curved arrows could not reliably sit behind labels because nodes and edges were rendered in separate passes
- filled/thick source arrows were often approximated as thin connectors
- visual review tracked layout and topology, but source-object details such as icon internals or ribbon arrow geometry were not first-class checklist items

## Changed

- Added a unified node/edge/edge-label render queue in `scripts/scene_to_visio.py`.
- Added `layer` support with common layers: `background`, `panel`, `arrow_under_text`, `icon`, `text`, and `foreground_arrow`.
- Added reusable ribbon-arrow node renderers:
  - `ribbon_arrow`
  - `curved_ribbon_arrow`
  - `loop_ribbon_arrow`
  - `qualitative_change_arrow`
- Added schema and component-map guidance for choosing ribbon arrows instead of thin connectors when the source arrow is a thick filled visual object.
- Added `fidelity_obligations` contracts for source details that must not be simplified away.
- Extended review bundles to emit `fidelity_checklist` and `<id>_human_review_checklist.md`.
- Extended checklist, rebuild-brief, and regeneration-packet scripts so fidelity checklist items stay in the review loop.
- Added a `ribbon_arrow_layering.scene.json` example for smoke-testing arrow layering and ribbon geometry.

## Improved Capability

- Broad arrows can now render under text without moving away from the source geometry.
- Infographic-style arrows no longer need to be forced into ordinary connector syntax.
- Visual review can explicitly track forbidden simplifications for icons, dense symbols, node-link motifs, and ribbon arrows.

## Remaining Boundary

Curved ribbon arrows are currently rendered as thick editable paths with arrowheads. This is useful for Visio editability and first-pass fidelity, but fully filled variable-width curved arrow bodies with gradient fills are still a future renderer improvement.
