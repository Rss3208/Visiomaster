#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scene_to_visio import load_component_map, load_style_profiles, normalize_scene_coordinates, resolve_profile
from scene_validate import (
    CONTAINER_TYPES,
    VISUAL_GRAMMAR_NODE_TYPES,
    exact_mode_from_metadata,
    estimate_text_box,
    has_valid_box,
    infer_containers,
    node_box,
    node_center,
    safe_node_style,
    validate_scene,
    visible_semantic_nodes,
)


def load_scene(path: Path) -> dict[str, Any]:
    return normalize_scene_coordinates(json.loads(path.read_text(encoding="utf-8")))


def scene_complexity_report(scene: dict[str, Any], strict: bool = False) -> str:
    component_map = load_component_map()
    profiles = load_style_profiles()
    profile_name, profile = resolve_profile(scene, profiles, None)
    errors, warnings = validate_scene(scene, strict=strict)

    nodes = scene.get("nodes", [])
    edges = scene.get("edges", [])
    nodes_by_id = {node["id"]: node for node in nodes if node.get("id")}
    node_types_by_id = {node["id"]: node.get("type") for node in nodes if node.get("id")}
    container_warnings: list[str] = []
    containers_by_node = infer_containers(nodes_by_id, node_types_by_id, container_warnings)
    visible_ids = visible_semantic_nodes(nodes_by_id, node_types_by_id)
    containers = [
        node
        for node in nodes
        if node.get("type") in CONTAINER_TYPES and has_valid_box(node)
    ]
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    region_plan = metadata.get("region_plan", metadata.get("source_region_plan", metadata.get("source_regions")))
    visual_grammar_inventory = metadata.get("visual_grammar_inventory")
    exact_mode = exact_mode_from_metadata(metadata)

    page = scene.get("page", {}) if isinstance(scene.get("page"), dict) else {}
    page_width = float(page.get("width", 0) or 0)
    page_height = float(page.get("height", 0) or 0)
    aspect_ratio = page_width / page_height if page_height else 0.0

    children_by_container: dict[str, list[str]] = defaultdict(list)
    uncovered: list[str] = []
    for node_id in visible_ids:
        container_id = containers_by_node.get(node_id)
        if container_id:
            children_by_container[str(container_id)].append(node_id)
        else:
            uncovered.append(node_id)

    font_sizes_by_type: dict[str, list[float]] = defaultdict(list)
    text_fit_items: list[str] = []
    for node_id in visible_ids:
        node = nodes_by_id[node_id]
        if not has_valid_box(node):
            continue
        text = str(node.get("text", node.get("symbol", ""))).strip()
        style = safe_node_style(node, component_map, profile)
        font_size = style.get("font_size_pt")
        if isinstance(font_size, (int, float)):
            font_sizes_by_type[str(node_types_by_id.get(node_id))].append(float(font_size))
        if text:
            estimated_w, estimated_h = estimate_text_box(text, float(font_size or 12))
            x1, y1, x2, y2 = node_box(node)
            available_w = max(0.0, (x2 - x1) - 0.10)
            available_h = max(0.0, (y2 - y1) - 0.10)
            if available_w and available_h and (estimated_w > available_w * 1.18 or estimated_h > available_h * 1.15):
                text_fit_items.append(
                    f"`{node_id}` {estimated_w:.2f}x{estimated_h:.2f} in estimated vs {available_w:.2f}x{available_h:.2f} in"
                )

    dense_regions = [
        (container_id, child_ids)
        for container_id, child_ids in children_by_container.items()
        if len(child_ids) > 18
    ]
    visual_grammar_ids = [
        node_id
        for node_id in visible_ids
        if str(node_types_by_id.get(node_id)) in VISUAL_GRAMMAR_NODE_TYPES
    ]
    primitive_regions = sorted(
        {
            str(containers_by_node.get(node_id))
            for node_id in visual_grammar_ids
            if containers_by_node.get(node_id)
        }
    )
    cross_region_edges = 0
    for edge in edges:
        source = edge.get("from")
        target = edge.get("to")
        source_id = source.split(":", 1)[0] if isinstance(source, str) else None
        target_id = target.split(":", 1)[0] if isinstance(target, str) else None
        if source_id and target_id and containers_by_node.get(source_id) != containers_by_node.get(target_id):
            cross_region_edges += 1

    lines: list[str] = []
    title = scene.get("metadata", {}).get("title", "visiomaster scene")
    lines.append(f"# Visiomaster Complexity Report: {title}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Style profile: `{profile_name}`")
    lines.append(f"- Page: {page_width:.2f} x {page_height:.2f} in, aspect {aspect_ratio:.2f}")
    lines.append(f"- Visible semantic nodes: {len(visible_ids)}")
    lines.append(f"- Edges: {len(edges)}")
    lines.append(f"- Regions: {len(containers)}")
    lines.append(f"- Region-covered visible nodes: {len(visible_ids) - len(uncovered)}/{len(visible_ids)}")
    lines.append(f"- Cross-region edges: {cross_region_edges}")
    lines.append(f"- Region plan entries: {len(region_plan) if isinstance(region_plan, list) else 0}")
    lines.append(f"- Visual grammar primitive nodes: {len(visual_grammar_ids)}")
    lines.append(f"- Visual grammar inventory: {'present' if isinstance(visual_grammar_inventory, dict) else 'missing'}")
    lines.append(f"- Validation warnings: {len(warnings)}")
    lines.append(f"- Validation errors: {len(errors)}")
    lines.append("")

    lines.append("## Source Region Plan")
    if not exact_mode:
        lines.append("- Not in exact reconstruction mode.")
    elif not isinstance(region_plan, list) or not region_plan:
        lines.append("- MISSING: add `metadata.region_plan` with source and target bboxes before full-page tuning.")
    else:
        for index, region in enumerate(region_plan):
            if not isinstance(region, dict):
                lines.append(f"- region[{index}]: invalid entry")
                continue
            region_id = str(region.get("id", region.get("name", f"region_{index}")))
            source = region.get("source_bbox_px", region.get("source_bbox", region.get("bbox_px")))
            target = region.get("target_bbox", region.get("target_bbox_in", region.get("scene_bbox", region.get("container_id", region.get("node_id")))))
            status = "ok" if source and target else "incomplete"
            lines.append(f"- `{region_id}`: {status}, source={source}, target={target}")
    lines.append("")

    lines.append("## Recommended Build Mode")
    if len(visible_ids) >= 32 or len(edges) >= 35 or aspect_ratio >= 2.2:
        lines.append("- Use `region_first` or `tiled_subscenes`: rebuild each logical module/crop, validate it, then assemble the full-page scene.")
        lines.append("- Add invisible `audit_region` boxes for source areas that do not have visible dashed frames.")
        lines.append("- Freeze shared style tokens before assembly: body font, small label font, operator font, frame title font, and arrow weight.")
        lines.append("- Dense regions must include `metadata.visual_grammar_inventory` plus local crop review before full-page polishing.")
    else:
        lines.append("- Whole-scene authoring is acceptable, but still run module audit before final Visio render.")
    if visual_grammar_ids and not isinstance(visual_grammar_inventory, dict):
        lines.append("- Add `metadata.visual_grammar_inventory`; primitive nodes without source facts are hard to review consistently.")
    lines.append("")

    lines.append("## Region Load")
    if containers:
        for container in sorted(containers, key=lambda node: (node.get("y", 0), node.get("x", 0))):
            container_id = str(container.get("id"))
            child_ids = children_by_container.get(container_id, [])
            cx, cy = node_center(container)
            area = max(0.001, float(container.get("w", 0.0)) * float(container.get("h", 0.0)))
            density = len(child_ids) / area
            source_ratio = container.get("source_aspect_ratio")
            source_bbox = container.get("source_bbox_px", container.get("source_bbox"))
            if source_ratio is None and isinstance(source_bbox, list) and len(source_bbox) == 4:
                try:
                    source_w = abs(float(source_bbox[2]) - float(source_bbox[0]))
                    source_h = abs(float(source_bbox[3]) - float(source_bbox[1]))
                    if source_h > 0:
                        source_ratio = source_w / source_h
                except (TypeError, ValueError):
                    source_ratio = None
            label = "dense" if len(child_ids) > 18 else "ok"
            ratio_text = f", source_ar={float(source_ratio):.2f}" if isinstance(source_ratio, (int, float)) else ""
            lines.append(f"- `{container_id}`: {len(child_ids)} visible nodes, density={density:.2f}/sqin, center=({cx:.2f}, {cy:.2f}) `{label}`{ratio_text}")
    else:
        lines.append("- No regions found.")
    if uncovered:
        preview = ", ".join(f"`{node_id}`" for node_id in uncovered[:12])
        suffix = " ..." if len(uncovered) > 12 else ""
        lines.append(f"- Uncovered visible nodes: {preview}{suffix}")
    lines.append("")

    lines.append("## Font Scale")
    for node_type, sizes in sorted(font_sizes_by_type.items()):
        if not sizes:
            continue
        lines.append(f"- `{node_type}`: {min(sizes):.1f}-{max(sizes):.1f} pt across {len(sizes)} nodes")
    if text_fit_items:
        lines.append("")
        lines.append("## Text Fit Risks")
        for item in text_fit_items[:12]:
            lines.append(f"- {item}")
        if len(text_fit_items) > 12:
            lines.append(f"- {len(text_fit_items) - 12} additional text-fit risks suppressed.")
    lines.append("")

    lines.append("## Dense Region Risks")
    if dense_regions:
        for container_id, child_ids in dense_regions:
            lines.append(f"- `{container_id}` has {len(child_ids)} visible nodes; split this region or create a local subscene.")
        if not isinstance(visual_grammar_inventory, dict):
            lines.append("- Dense-region gate: add `metadata.visual_grammar_inventory`; otherwise small cells, symbols, and waves can drift without a source-fact contract.")
        lines.append("- Dense-region gate: generate local crop review assets for each dense/primitive-bearing region before accepting the full-page render.")
    else:
        lines.append("- No region exceeds the default density threshold.")
    lines.append("")

    lines.append("## Paper Detail Grammar Risks")
    compact_types = {
        "grid_matrix",
        "token_grid",
        "feature_vector_stack",
        "math_vector",
        "math_text",
        "operator_node",
        "concat_operator",
        "brace_merge",
        "multi_port_junction",
        *VISUAL_GRAMMAR_NODE_TYPES,
    }
    compact_counts: dict[str, int] = defaultdict(int)
    for node_id in visible_ids:
        node_type = str(node_types_by_id.get(node_id))
        if node_type in compact_types:
            compact_counts[node_type] += 1
    if compact_counts:
        for node_type, count in sorted(compact_counts.items()):
            lines.append(f"- `{node_type}`: {count}")
        if visual_grammar_ids:
            preview = ", ".join(f"`{node_id}`" for node_id in visual_grammar_ids[:12])
            suffix = " ..." if len(visual_grammar_ids) > 12 else ""
            lines.append(f"- Visual grammar nodes requiring local visual checks: {preview}{suffix}")
            if primitive_regions:
                lines.append(f"- Primitive-bearing regions: {', '.join(f'`{region}`' for region in primitive_regions)}")
            if not isinstance(visual_grammar_inventory, dict):
                lines.append("- MISSING: `metadata.visual_grammar_inventory` should record shape/cell/line/symbol/wave/text facts before choosing these primitives.")
    else:
        lines.append("- No compact paper-detail primitives found; if the source has matrices, small operators, ports, or formulas, scene grammar is likely too coarse.")
    long_edges = []
    for edge in edges:
        points = []
        for key in ("from_point", "to_point"):
            value = edge.get(key)
            if isinstance(value, list) and len(value) == 2 and all(isinstance(item, (int, float)) for item in value):
                points.append((float(value[0]), float(value[1])))
        if edge.get("points") and isinstance(edge["points"], list):
            points = [
                (float(point[0]), float(point[1]))
                for point in edge["points"]
                if isinstance(point, list) and len(point) == 2 and all(isinstance(item, (int, float)) for item in point)
            ]
        if len(points) >= 2:
            length = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(points, points[1:]))
            if length > 2.6:
                long_edges.append((str(edge.get("id", "<missing-id>")), length))
    if long_edges:
        for edge_id, length in sorted(long_edges, key=lambda item: -item[1])[:8]:
            lines.append(f"- Long explicit path `{edge_id}` length={length:.2f} in; check for missing bus/junction/boundary port.")
    lines.append("")

    if errors or warnings or container_warnings:
        lines.append("## Validation Snapshot")
        for error in errors[:12]:
            lines.append(f"- ERROR: {error}")
        for warning in [*container_warnings, *warnings][:24]:
            lines.append(f"- WARN: {warning}")
        if len(errors) > 12 or len(warnings) + len(container_warnings) > 24:
            lines.append("- Additional validation items suppressed; run `scene_validate.py` for the full list.")
        lines.append("")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a large-figure complexity report for a visiomaster scene.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--output", help="Optional markdown report path")
    parser.add_argument("--strict", action="store_true", help="Pass strict mode through to scene validation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scene_path = Path(args.scene).resolve()
    report = scene_complexity_report(load_scene(scene_path), strict=args.strict)
    output_path = Path(args.output).resolve() if args.output else scene_path.with_suffix(".complexity.md")
    output_path.write_text(report + "\n", encoding="utf-8")
    print(f"Wrote complexity report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
