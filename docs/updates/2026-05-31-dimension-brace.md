# 2026-05-31 Dimension Brace Component

## Why

Paper figures often use a thin single-sided curly brace beside a matrix, tensor stack, timeline, or grouped rows/columns to mark a dimension or range. The existing generic curly bracket path was intended for loose grouping and merge-like braces; in high-aspect cases it could read as an S-shaped wave.

## Changed

- Added `dimension_brace` as a node type rendered through the bracket renderer.
- Added `shape: "paper_curly"` / `dimension_brace` / `latex_brace` / `thin_curly` handling in `draw_bracket`.
- Added deterministic `paper_curly_brace_points()` geometry for narrow Bezier braces.
- Preserved existing `shape: "curly"` behavior so older scenes keep their old rendering.
- Added scene schema, component map, effective-field, and SKILL.md guidance.
- Added `templates/examples/paper_figures/dimension_brace.scene.json`.

## Usage

Use `dimension_brace` when the brace is a visual dimension/range marker with no merge semantics. Use `brace_merge` when multiple inputs converge into a brace waist. Use `bracket` for square/U-shaped marks or legacy generic braces.
