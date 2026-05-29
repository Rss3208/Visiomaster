# 2026-05-30 Visual Grammar Primitives

## Problem

Some source figures contain local visual units that are not business components: repeated rectangular cells, tiny icon symbols, wave silhouettes, decorative internal strokes, and compact grids. Previous workflows could recognize the high-level module but still normalize these details into generic rounded tokens, smooth waves, or main-flow arrows.

## Changes

- Added a mandatory `metadata.visual_grammar_inventory` workflow step before component selection.
- Added generic primitive node types: `primitive_group`, `shape_cluster`, `symbol_group`, `cell_strip`, `micro_grid`, and `polyline_wave`.
- Added renderer support for editable primitive subshapes, rectangular cell strips/grids, symbol groups, and sampled polyline waves.
- Added schema fields for `primitive_family`, `motif_binding`, `visual_facts`, `source_visual_facts`, `must_match_facts`, `subshape_role`, `source_bbox_px`, and edge `edge_role`.
- Added strict validation for visual facts, including cell count/gap/rounding, sampled waves, symbol internals, source bbox binding, and text shrink floors.
- Split audit concerns so `decorative_internal`, `symbol_internal`, and `icon_internal` edges are reviewed as visual grammar instead of topology arrows.
- Extended review bundles with source-derived `visual_checklist` entries from `visual_grammar_inventory` and primitive nodes.
- Extended complexity reporting so dense/primitive regions require visual grammar inventory and local crop review.
- Added `templates/examples/visual_grammar_primitives.scene.json` and smoke tests.

## Capability Impact

This improves first-pass reconstruction for diagrams where the critical fidelity problem is not module names, but local drawing grammar: rectangular cells should stay rectangular, waves should preserve their source silhouette, and icon internals should not be mistaken for flow arrows.

## Remaining Boundaries

Primitive groups are editable subshapes drawn in one local coordinate system, but they are not yet guaranteed to become a single locked Visio group object in every environment. Visual LLM comparison remains the final fidelity judge.
