# Component Selection Cheat Sheet (source morphology → candidate components)

Decision aid for draft authoring. **Not a lookup table**: every entry lists
discriminating features between candidates. If the source crop matches none of the
features cleanly, stop and decide from the crop itself — the taxonomy in
`references/defect-taxonomy.md` and rules 87-88 still apply. Rule 96 (crop
verification) is mandatory after choosing via this table: confirm the chosen
component's rendered form against the source crop before locking the scene.

## Quick decisions seen in production runs (B1/B3 evidence)

| source morphology | primary candidate | switch to → when | key params that bit us |
|---|---|---|---|
| colored grid of small squares, repeated/stacked | `micro_grid` (compact) / `grid_matrix` (large contiguous, shared lines) | `cell_strip` if one row/col of continuous cells | `square_cells: true` + `grid_align_x/y` instead of stretching; per-cell text → `token_grid` |
| pasted-looking grid in source (must redraw) | same as above; register nothing raster | — | raster_policy_audit fails grid-class image_tile unconditionally |
| trapezoid encoder/extractor wedge | `trapezoid_node` | `polygon_node` if notch/asymmetric | `orientation`, `pointed`; taper semantics differ per orientation |
| small circle operator ⊗ ⊕ × | `operator_node` (renders symbol centered) | never ellipse+separate text | symbol size scales with node; check glyph centering |
| variable with word-like subscript (S_rgb, h_j) | `math_text` + `math_render_mode: "fragments"` | `math_vector` if brackets/entries visible | underscore is legal encoding ONLY inside math types; text_fit "math_label" |
| scattered dot cluster (point cloud) | `primitive_group` with vector dots | `image_tile` ONLY if source is photographic | keep count/density from crop; no white backing rect |
| fan of thin rays (light rays, attention spokes) | `primitive_group` (lines from common origin) | `polygon_node` if source shows filled cone | line vs arrowhead per source; avoid generic arrows |
| rounded network of nodes + edges (attention mechanism) | `primitive_group` or small `ellipse_node`/`process_box` mesh inside one container | `graph_motif`-style components if listed in visio_components.json | keep node count from source; orange highlight = ellipse behind mesh |
| flow between aligned modules (horizontal/vertical) | `lane_arrow` with route horizontal/vertical | `arrow_connector` only when free route | lane_arrow avoids diagonal drift; endpoints `node:side@ratio` |
| orthogonal flow with rounded 90° bends | `rounded_orthogonal_connector` | never smooth/Catmull-Rom for paper figures | explicit `corner_radius_px`; smooth needs allow_smooth_curve + source facts |
| dashed feedback/return path | `dashed_feedback_path` (rule 54) | `dashed_region` boundary port for frame exits | explicit orthogonal points; no allow_diagonal |
| fork/merge at one point | junction first: `junction_point`/`merge_bus` | — | fork_connector must START at junction type, join_connector must END at one |
| photo / complex bitmap | `image_tile` + `justification` + `source_bbox_px` | — | the ONLY legal raster; area budget 8%/15% |
| rotated side label | `text_block` + `angle_deg` | — | separate rotated overlay; never rotate inside process shape |
| region frame (dashed/titled) | `group_container` (solid) / `dashed_region` (dashed) | `audit_region` invisible for logical areas | containers are not edge endpoints; use boundary_port/junction |
| brace next to stack/matrix (dimension) | `dimension_brace` / `paper_curly` | generic curly only for merge grouping | TeX-like: curled terminals + near-vertical stems + waist pinch |
| stacked colored sheets / slabs (feature bank) | `tensor_stack` (`stack_render_mode` per crop) | `cuboid_node` for single thick block | thin_feature_slabs vs feature_cuboids decided by crop |

## Renderer gotchas (each cost a production round)

- `text_align` is an **integer** for the Visio renderer, not "center"/"left" strings.
- Subshape coordinates inside composite components are **normalized (0-1)**, not source pixels — absolute px silently render nothing.
- `(K⁻¹)`-style superscripts: renderer does not parse `^`; use Unicode superscript glyphs (true superscript chars only, digits safe) or a `caption_block` with runs.
- Visio PNG export filter can fail intermittently; fallback is `ExportAsFixedFormat` PDF → PyMuPDF rasterize. Retry once after killing VISIO.EXE on COM dropout.
- A container's own bbox is not an arrow endpoint; `boundary_port` on the frame edge is.

## Discipline

1. Identify morphology from the source crop (never from the whole page).
2. Take candidates from this table only when features match; otherwise decide from the crop.
3. Author, then verify the chosen component's form against the crop (rule 96).
4. Run `schema_hints.py` before the first validate pass.
