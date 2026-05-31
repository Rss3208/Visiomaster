#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from scene_to_visio import (
    edge_route_points,
    edge_style,
    load_component_map,
    load_style_profiles,
    node_style,
    normalize_scene_coordinates,
    resolve_profile,
)
from scene_validate import (
    CONTAINER_TYPES,
    INTERNAL_EDGE_ROLES,
    RIBBON_ARROW_NODE_TYPES,
    STRICT_REPLICA_REVIEW_MODES,
    STRICT_REQUIRED_REGION_CATEGORIES,
    VISUAL_GRAMMAR_NODE_TYPES,
    arrow_plan_items,
    base_node_id,
    bbox_signature,
    container_for_point,
    endpoint_has_explicit_side_anchor,
    estimate_text_box,
    edge_point,
    edge_endpoint_role,
    exact_mode_from_metadata,
    endpoint_side,
    edge_arrow_plan_id,
    expanded_box,
    infer_containers,
    is_background_node,
    is_passive_loop_frame,
    font_validation_warnings,
    loss_feedback_stub_issue,
    node_box,
    node_center,
    node_motif_edges,
    node_text_for_font,
    path_bounds,
    point_in_box,
    polyline_intersects_box_bbox,
    region_categories,
    recursive_fact_text,
    scene_looks_like_gan_tfr,
    segment_has_diagonal,
    segment_intersects_box_interior,
    terminal_tangent_issue,
    text_looks_like_math_content,
    text_has_compact_loss_notation,
    text_has_raw_loss_subscript,
    tfr_panel_layout_issues,
    node_uses_math_contract,
    visible_semantic_nodes,
)
from font_utils import font_resolution_for_style

CURVED_EDGE_TYPES = {"curved_arrow", "loop_arrow"}
FEEDBACK_TOKENS = {"loss", "backprop", "feedback", "gradient", "penalty", "adv", "rec"}
RUN_TEXT_NODE_TYPES = {"text_block", "annotation_block", "caption_block"}


def truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_scene(path: Path) -> dict[str, Any]:
    return normalize_scene_coordinates(json.loads(path.read_text(encoding="utf-8")))


def endpoint_node_id(value: Any) -> str | None:
    if isinstance(value, str):
        return base_node_id(value)
    return None


def node_label(node: dict[str, Any]) -> str:
    text = str(node.get("text", node.get("symbol", ""))).replace("\n", "\\n").strip()
    return f"{node.get('id')}[{node.get('type')}]" + (f" `{text}`" if text else "")


def edge_label(edge: dict[str, Any]) -> str:
    return f"{edge.get('id')}[{edge.get('type')}] {edge.get('from', edge.get('from_point'))} -> {edge.get('to', edge.get('to_point'))}"


def line_length(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return total


def source_ratio_for_container(node: dict[str, Any]) -> float | None:
    value = node.get("source_aspect_ratio")
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    bbox = node.get("source_bbox_px", node.get("source_bbox"))
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            width = abs(float(bbox[2]) - float(bbox[0]))
            height = abs(float(bbox[3]) - float(bbox[1]))
        except (TypeError, ValueError):
            return None
        if height > 0:
            return width / height
    return None


def node_or_style_has_key(node: dict[str, Any], key: str) -> bool:
    if key in node:
        return True
    style = node.get("style")
    return isinstance(style, dict) and key in style


def estimate_run_text_box(node: dict[str, Any], style: dict[str, Any]) -> tuple[float, float]:
    runs = node.get("runs")
    if not isinstance(runs, list) or not runs:
        return estimate_text_box(node_text_for_font(node), float(style.get("font_size_pt", 12) or 12))

    gap = float(node.get("run_gap_in", style.get("run_gap_in", 0.0)) or 0.0)
    total_width = 0.0
    max_height = 0.0
    run_count = 0
    for run in runs:
        if isinstance(run, dict):
            text = str(run.get("text", "")).strip()
            font_size = float(run.get("font_size_pt", style.get("font_size_pt", 12)) or style.get("font_size_pt", 12) or 12)
            explicit_w = run.get("w", run.get("width"))
            explicit_h = run.get("h", run.get("height"))
        else:
            text = str(run).strip()
            font_size = float(style.get("font_size_pt", 12) or 12)
            explicit_w = None
            explicit_h = None
        if not text:
            continue
        estimated_w, estimated_h = estimate_text_box(text.replace("\r", " ").replace("\n", " "), font_size)
        total_width += float(explicit_w) if isinstance(explicit_w, (int, float)) else estimated_w
        max_height = max(max_height, float(explicit_h) if isinstance(explicit_h, (int, float)) else estimated_h)
        run_count += 1
    if run_count > 1:
        total_width += gap * (run_count - 1)
    return total_width, max_height


def metadata_region_plan_items(metadata: dict[str, Any], nodes: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    plan = metadata.get("region_plan", metadata.get("source_region_plan", metadata.get("source_regions")))
    exact_mode = exact_mode_from_metadata(metadata)
    if not exact_mode:
        return items
    if not isinstance(plan, list) or len(plan) < 3:
        items.append(
            "- [ ] [REBUILD] Exact figure has no usable `metadata.region_plan`; first mark global/input/core/output/arrow-dense/small-text/boundary source bboxes and target bboxes, then rerender."
        )
        return items
    caption_required = any(
        (
            node.get("type") == "caption_block"
            or (
                isinstance(node.get("text"), str)
                and len(str(node.get("text", "")).strip()) >= 8
                and any(token in str(node.get("text", "")) for token in ("Fig.", "Figure", "图"))
            )
        )
        for node in nodes
        if isinstance(node, dict)
    )
    required_categories = list(STRICT_REQUIRED_REGION_CATEGORIES)
    if caption_required:
        required_categories.append("caption")
    coverage: set[str] = set()
    source_boxes: dict[str, tuple[float, float, float, float]] = {}
    for region in plan:
        if not isinstance(region, dict):
            continue
        categories = region_categories(region)
        coverage.update(categories)
        source_sig = bbox_signature(region.get("source_bbox_px", region.get("source_bbox", region.get("bbox_px"))))
        if source_sig is not None:
            for category in categories:
                source_boxes.setdefault(category, source_sig)
    missing = [label for label in required_categories if label not in coverage]
    if missing:
        items.append(
            f"- [ ] [REBUILD] Exact figure region_plan misses review regions `{', '.join(missing)}`; visual LLM crops may hide the local defect class."
        )
    global_box = source_boxes.get("global")
    for category in ("input", "core", "output", "arrow_dense", "small_text", "caption"):
        if global_box and source_boxes.get(category) == global_box:
            items.append(
                f"- [ ] [REBUILD] region_plan coverage for `{category}` reuses the full-page/global source bbox; strict QA needs a source-bound local crop."
            )
    trio = [source_boxes.get(category) for category in ("input", "core", "output")]
    if all(box is not None for box in trio) and len(set(trio)) < 3:
        items.append(
            "- [ ] [REBUILD] region_plan input/core/output source bboxes are not distinct; strict regional review would collapse into repeated crops."
        )
    return items


def source_visual_inventory_items(metadata: dict[str, Any], nodes: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    exact_mode = exact_mode_from_metadata(metadata)
    if not exact_mode:
        return items

    inventory = metadata.get("source_visual_inventory")
    if not isinstance(inventory, dict):
        return [
            "- [ ] [REBUILD] Exact figure has no `metadata.source_visual_inventory`; rebuild the scene from a per-image visual LLM source inventory instead of patching a prior scene or using a batch scene generator."
        ]

    analysis_basis = str(inventory.get("analysis_basis", "")).lower()
    if "visual" not in analysis_basis or "source" not in analysis_basis:
        items.append(
            "- [ ] [REBUILD] `metadata.source_visual_inventory.analysis_basis` does not prove visual LLM inspection of the source image."
        )
    if inventory.get("do_not_translate") is not True:
        items.append(
            "- [ ] [REBUILD] `metadata.source_visual_inventory.do_not_translate` is not true; exact replicas must preserve source-language labels instead of translating them."
        )
    unknown_policy = str(inventory.get("unknown_text_policy", "")).lower()
    if "unreadable" not in unknown_policy or "invent" not in unknown_policy:
        items.append(
            "- [ ] [REBUILD] `metadata.source_visual_inventory.unknown_text_policy` must say to mark unreadable source text rather than inventing replacements."
        )
    authoring_mode = str(inventory.get("scene_authoring_mode", "")).lower()
    if "fresh" not in authoring_mode or "source" not in authoring_mode:
        items.append(
            "- [ ] [REBUILD] `metadata.source_visual_inventory.scene_authoring_mode` must state that the scene was freshly authored from the source inventory."
        )
    prior_policy = str(inventory.get("prior_scene_policy", "")).lower()
    if prior_policy and not any(token in prior_policy for token in ("do_not", "not", "no")):
        items.append(
            "- [ ] [REBUILD] `metadata.source_visual_inventory.prior_scene_policy` should forbid reading or patching prior-round scenes during capability evaluation."
        )

    regions = inventory.get("regions")
    if not isinstance(regions, list) or len(regions) < 3:
        items.append(
            "- [ ] [REBUILD] `metadata.source_visual_inventory.regions` is missing or too small; exact dense figures need source-inspected global/input/core/output/arrow-dense/small-text regions."
        )
        return items
    caption_required = any(
        (
            node.get("type") == "caption_block"
            or (
                isinstance(node.get("text"), str)
                and len(str(node.get("text", "")).strip()) >= 8
                and any(token in str(node.get("text", "")) for token in ("Fig.", "Figure", "图"))
            )
        )
        for node in nodes
        if isinstance(node, dict)
    )

    required_categories = list(STRICT_REQUIRED_REGION_CATEGORIES)
    if caption_required:
        required_categories.append("caption")
    coverage: set[str] = set()
    source_boxes: dict[str, tuple[float, float, float, float]] = {}
    for region in regions:
        if not isinstance(region, dict):
            continue
        categories = region_categories(region, include_required_crop_types=True)
        coverage.update(categories)
        source_sig = bbox_signature(region.get("source_bbox_px", region.get("source_bbox", region.get("bbox_px"))))
        if source_sig is not None:
            for category in categories:
                source_boxes.setdefault(category, source_sig)
    missing_terms = [label for label in required_categories if label not in coverage]
    if missing_terms:
        items.append(
            f"- [ ] [REBUILD] `metadata.source_visual_inventory.regions` misses review coverage for `{', '.join(missing_terms)}`."
        )

    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            items.append(f"- [ ] [REBUILD] source_visual_inventory.regions[{index}] is not an object.")
            continue
        region_name = region.get("id", region.get("name", f"region_{index}"))
        has_source = any(region.get(key) is not None for key in ("source_bbox_px", "source_bbox", "bbox_px"))
        if not has_source:
            items.append(f"- [ ] [REBUILD] source_visual_inventory region `{region_name}` has no source bbox.")
        has_contract = any(
            isinstance(region.get(key), list) and len(region.get(key, [])) > 0
            for key in (
                "required_labels",
                "required_formulas",
                "required_component_motifs",
                "required_edge_motifs",
                "required_ports_or_boundaries",
            )
        )
        if not has_contract:
            items.append(
                f"- [ ] [REBUILD] source_visual_inventory region `{region_name}` has no required visible labels/formulas/motifs/ports contract."
            )
        layout_facts = region.get("text_layout_facts")
        if layout_facts is None:
            items.append(
                f"- [ ] [REBUILD] source_visual_inventory region `{region_name}` has no text_layout_facts; exact review needs alignment/wrap/math/subscript/font/shadow facts, not only module names."
            )
        elif not isinstance(layout_facts, list) or not layout_facts:
            items.append(
                f"- [ ] [REBUILD] source_visual_inventory region `{region_name}` text_layout_facts is empty or invalid."
            )
        has_style_facts = any(
            isinstance(region.get(key), list) and len(region.get(key, [])) > 0
            for key in ("box_style_facts", "line_style_facts", "shadow_facts", "density_facts")
        )
        if not has_style_facts:
            items.append(
                f"- [ ] [REBUILD] source_visual_inventory region `{region_name}` has no box/line/shadow/density facts; "
                "exact review needs explicit style evidence for padding, rounding, line grammar, shadow softness, or region density."
            )
        obligations = region.get("fidelity_obligations")
        if obligations is not None and not isinstance(obligations, list):
            items.append(
                f"- [ ] [REBUILD] source_visual_inventory region `{region_name}` has invalid fidelity_obligations; use an array of source objects with must_preserve/forbidden_simplification."
            )
        elif isinstance(obligations, list):
            for obligation in obligations:
                if not isinstance(obligation, dict):
                    continue
                if not obligation.get("must_preserve"):
                    items.append(
                        f"- [ ] [REBUILD] source_visual_inventory region `{region_name}` has a fidelity_obligation without must_preserve details."
                    )
                    break
    global_box = source_boxes.get("global")
    for category in ("input", "core", "output", "arrow_dense", "small_text", "caption"):
        if global_box and source_boxes.get(category) == global_box:
            items.append(
                f"- [ ] [REBUILD] source_visual_inventory coverage for `{category}` reuses the full-page/global source bbox; strict QA needs a source-bound local crop."
            )
    trio = [source_boxes.get(category) for category in ("input", "core", "output")]
    if all(box is not None for box in trio) and len(set(trio)) < 3:
        items.append(
            "- [ ] [REBUILD] source_visual_inventory input/core/output source bboxes are not distinct; strict regional review would collapse into repeated crops."
        )
    return items


def strict_replica_workflow_items(metadata: dict[str, Any]) -> list[str]:
    items: list[str] = []
    exact_mode = exact_mode_from_metadata(metadata)
    if not exact_mode:
        return items

    review_mode = str(metadata.get("replica_review_mode", metadata.get("review_mode", ""))).lower()
    if not review_mode:
        items.append(
            "- [ ] [REBUILD] Exact figure should declare `metadata.replica_review_mode`, ideally `strict_replica`, so review does not slide into semantic redraw criteria."
        )
    elif review_mode not in STRICT_REPLICA_REVIEW_MODES:
        items.append(
            f"- [ ] [REBUILD] Exact figure uses review mode `{review_mode}`; source-faithful work should use a strict replica review mode."
        )
    replica_stage = str(metadata.get("replica_stage", metadata.get("production_stage", ""))).lower()
    if not replica_stage:
        items.append(
            "- [ ] [REBUILD] Exact figure has no `metadata.replica_stage`; keep the two-stage loop explicit (`layout_topology` then `detail_polish`)."
        )
    elif replica_stage not in {"layout_topology", "detail_polish"}:
        items.append(
            f"- [ ] [REBUILD] Exact figure uses unsupported replica_stage `{replica_stage}`; use `layout_topology` or `detail_polish`."
        )
    if metadata.get("starter_template") or str(metadata.get("starter_mode", "")).lower() == "template_seed":
        items.append(
            "- [ ] [REBUILD] Exact figure metadata records a template-seeded start; strict capability evaluation must rebuild from a blank source-driven scene."
        )
    autofix_history = metadata.get("autofix_history")
    if isinstance(autofix_history, list) and autofix_history:
        items.append(
            "- [ ] [REBUILD] Exact figure metadata records recipe/autofix rewrites; strict capability evaluation must review a freshly authored scene, not a scene rewritten by scene_autofix or pre-render recipes."
        )
    return items


def arrow_plan_audit_items(metadata: dict[str, Any], edges: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    if not exact_mode_from_metadata(metadata):
        return items

    plans = arrow_plan_items(metadata)
    if not isinstance(plans, list) or not plans:
        return [
            "- [ ] [REBUILD] Exact figure has no usable `metadata.arrow_plan`; inventory every source-visible arrow before authoring scene edges."
        ]

    plan_by_id: dict[str, dict[str, Any]] = {}
    active_plan_ids: set[str] = set()
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        plan_id = str(plan.get("id", "")).strip()
        if not plan_id:
            continue
        plan_by_id[plan_id] = plan
        certainty = str(plan.get("certainty", "")).lower()
        status = str(plan.get("status", "")).lower()
        if certainty not in {"uncertain", "unknown"} and status not in {"optional", "skipped", "not_visible"}:
            active_plan_ids.add(plan_id)

    edges_by_plan: dict[str, list[dict[str, Any]]] = {}
    motif_edges_by_plan: dict[str, list[dict[str, Any]]] = {}
    ribbon_nodes_by_plan: dict[str, list[dict[str, Any]]] = {}
    unplanned_edges: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("id", "<missing-id>"))
        plan_id = edge_arrow_plan_id(edge)
        if plan_id:
            edges_by_plan.setdefault(plan_id, []).append(edge)
        elif edge.get("type") not in {"line_segment"}:
            unplanned_edges.append(edge_id)

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "<missing-node>"))
        node_type = str(node.get("type", ""))
        node_plan_id = edge_arrow_plan_id(node)
        if node_type in RIBBON_ARROW_NODE_TYPES:
            if node_plan_id:
                ribbon_nodes_by_plan.setdefault(node_plan_id, []).append(node)
            else:
                unplanned_edges.append(node_id)
        for motif_edge in node_motif_edges(node):
            motif_edge_id = str(motif_edge.get("id", f"{node_id}.motif_edge"))
            plan_id = edge_arrow_plan_id(motif_edge)
            if plan_id:
                motif_edges_by_plan.setdefault(plan_id, []).append(motif_edge)
            else:
                unplanned_edges.append(f"{node_id}.{motif_edge_id}")

    covered_plan_ids = set(edges_by_plan) | set(motif_edges_by_plan) | set(ribbon_nodes_by_plan)
    missing_edges = sorted(active_plan_ids - covered_plan_ids)
    unknown_refs = sorted(covered_plan_ids - set(plan_by_id))
    if missing_edges:
        items.append(
            f"- [ ] [REBUILD] arrow_plan_coverage: active source arrows with no scene edge, motif_edge, or ribbon arrow node: `{', '.join(missing_edges[:12])}`."
        )
    if unknown_refs:
        items.append(
            f"- [ ] [REBUILD] unbound_source_arrows: scene edges reference unknown arrow_plan ids `{', '.join(unknown_refs[:12])}`."
        )
    if unplanned_edges:
        items.append(
            f"- [ ] [REBUILD] arrow_plan_coverage: visible scene arrow elements without arrow_plan_id: `{', '.join(unplanned_edges[:12])}`."
        )

    for plan_id in sorted(covered_plan_ids):
        plan_edges = edges_by_plan.get(plan_id, [])
        all_bindings = [*plan_edges, *motif_edges_by_plan.get(plan_id, [])]
        if len(all_bindings) <= 1:
            continue
        segment_count_values = {
            binding.get("segment_count")
            for binding in all_bindings
            if isinstance(binding.get("segment_count"), int)
        }
        segment_indexes = [
            binding.get("segment_index")
            for binding in all_bindings
            if isinstance(binding.get("segment_index"), int)
        ]
        expected_count = len(all_bindings)
        all_segmented = all(
            binding.get("same_source_arrow") is True
            and isinstance(binding.get("segment_index"), int)
            and isinstance(binding.get("segment_count"), int)
            for binding in all_bindings
        )
        if not all_segmented or segment_count_values != {expected_count} or sorted(segment_indexes) != list(range(1, expected_count + 1)):
            items.append(
                f"- [ ] [REBUILD] multi_edge_plan_misuse: arrow_plan `{plan_id}` binds {len(all_bindings)} scene/motif edges without complete same_source_arrow segment metadata."
            )

    strict_fields = (
        "from_visual_object",
        "from_anchor_description",
        "to_visual_object",
        "to_anchor_description",
        "line_style",
        "arrowhead",
        "semantic_intent",
        "source_bbox_px",
        "must_not_cross",
        "relative_position_facts",
    )
    for plan_id, plan in sorted(plan_by_id.items()):
        missing = [field for field in strict_fields if field not in plan]
        if missing:
            items.append(
                f"- [ ] [REBUILD] source_anchor_mismatch risk: arrow_plan `{plan_id}` misses strict fields `{', '.join(missing[:6])}{' ...' if len(missing) > 6 else ''}`."
            )
        plan_text = recursive_fact_text(
            {
                "visual_form": plan.get("visual_form", plan.get("arrow_form")),
                "line_style": plan.get("line_style"),
                "source_fact": plan.get("source_fact"),
                "relative_position_facts": plan.get("relative_position_facts"),
            }
        )
        plan_requires_ribbon = any(token in plan_text for token in {"ribbon", "thick arrow", "filled arrow", "broad arrow", "band arrow"})
        if plan_requires_ribbon and not ribbon_nodes_by_plan.get(plan_id):
            items.append(
                f"- [ ] [REBUILD] arrow_plan `{plan_id}` describes a ribbon/thick arrow but is not bound to a `ribbon_arrow`, `curved_ribbon_arrow`, or `loop_ribbon_arrow` node."
            )
        if plan_requires_ribbon and edges_by_plan.get(plan_id):
            items.append(
                f"- [ ] [REBUILD] arrow_plan `{plan_id}` describes a ribbon/thick arrow but is also bound to thin connector edge(s); use a ribbon arrow node instead of ordinary connectors."
            )

    return items


def looks_like_vector_formula(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(char in text for char in "⎡⎢⎣⎤⎥⎦"):
        return True
    if any(word in text.lower() for word in {"loss", "penalty", "reconstruction", "adversarial", "gradient"}):
        return False
    if len(lines) < 2 or len(lines) > 6:
        return False
    underscored = [line for line in lines if "_" in line]
    if len(underscored) < 2:
        return False
    return all(" " not in line and len(line) <= 24 for line in underscored)


def edge_containers(
    edge: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    node_types_by_id: dict[str, str],
    containers_by_node: dict[str, str | None],
) -> tuple[str | None, str | None, str | None, str | None]:
    source_id = endpoint_node_id(edge.get("from"))
    target_id = endpoint_node_id(edge.get("to"))
    source_point = edge_point(edge, "from")
    target_point = edge_point(edge, "to")
    source_container = (
        containers_by_node.get(source_id)
        if source_id
        else container_for_point(source_point, nodes_by_id, node_types_by_id)
    )
    target_container = (
        containers_by_node.get(target_id)
        if target_id
        else container_for_point(target_point, nodes_by_id, node_types_by_id)
    )
    return source_id, target_id, source_container, target_container


def audit_scene(scene: dict[str, Any]) -> str:
    component_map = load_component_map()
    profiles = load_style_profiles()
    profile_name, profile = resolve_profile(scene, profiles, None)
    page = scene.get("page", {}) if isinstance(scene.get("page"), dict) else {}
    nodes = scene.get("nodes", [])
    edges = scene.get("edges", [])
    nodes_by_id = {node["id"]: node for node in nodes if node.get("id")}
    node_types_by_id = {node["id"]: node.get("type") for node in nodes if node.get("id")}
    warnings: list[str] = []
    containers_by_node = infer_containers(nodes_by_id, node_types_by_id, warnings)
    containers = [node for node in nodes if node.get("type") in CONTAINER_TYPES]
    visible_ids = visible_semantic_nodes(nodes_by_id, node_types_by_id)

    route_cache: dict[str, list[tuple[float, float]]] = {}
    edge_container_cache: dict[str, tuple[str | None, str | None, str | None, str | None]] = {}
    rebuild_items: list[str] = []
    audit_items: list[str] = []
    typography_items: list[str] = []
    visual_grammar_items: list[str] = []
    decorative_internal_items: list[str] = []
    resolved_font_counts: dict[str, int] = {}
    gan_tfr_context = scene_looks_like_gan_tfr(scene, nodes_by_id)
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    exact_mode = exact_mode_from_metadata(metadata)
    audit_items.extend(strict_replica_workflow_items(metadata))
    audit_items.extend(metadata_region_plan_items(metadata, nodes))
    audit_items.extend(arrow_plan_audit_items(metadata, edges, nodes))
    rebuild_items.extend(source_visual_inventory_items(metadata, nodes))

    for edge in edges:
        edge_id = str(edge.get("id", "<missing-id>"))
        edge_container_cache[edge_id] = edge_containers(edge, nodes_by_id, node_types_by_id, containers_by_node)
        try:
            style = edge_style(edge, component_map, profile)
            route_cache[edge_id] = edge_route_points(edge, style, nodes_by_id)
        except Exception as exc:
            audit_items.append(f"- [ ] Route for `{edge_id}` could not be computed: {exc}")

    for node in nodes:
        resolved_style: dict[str, Any] = {}
        if node.get("id") and node.get("type") in component_map.get("node_types", {}):
            try:
                _, resolved_style, _ = node_style(node, component_map, profile)
                text = node_text_for_font(node)
                resolution = font_resolution_for_style(resolved_style, text)
                if resolution.resolved:
                    resolved_font_counts[resolution.resolved] = resolved_font_counts.get(resolution.resolved, 0) + 1
                for issue in font_validation_warnings(node, resolved_style, exact_mode=exact_mode):
                    rebuild_prefix = (
                        "[REBUILD] "
                        if "records source font" in issue and "installed as" in issue and "effective render font" in issue
                        else ""
                    )
                    typography_items.append(f"- [ ] {rebuild_prefix}{issue}")
            except Exception as exc:
                typography_items.append(f"- [ ] Font style for `{node.get('id')}` could not be resolved: {exc}")
        node_type = node.get("type")
        if node_type in VISUAL_GRAMMAR_NODE_TYPES:
            node_id = str(node.get("id"))
            if exact_mode and not node.get("source_bbox_px", node.get("source_bbox")):
                visual_grammar_items.append(
                    f"- [ ] `{node_id}` is `{node_type}` without source_bbox_px; bind it to the crop so review can judge the preserved visual facts."
                )
            if exact_mode and not node.get("must_match_facts"):
                visual_grammar_items.append(
                    f"- [ ] `{node_id}` is `{node_type}` without must_match_facts; list the source facts this primitive must retain."
                )
            fact_text = recursive_fact_text(
                {
                    "visual_facts": node.get("visual_facts"),
                    "source_visual_facts": node.get("source_visual_facts"),
                    "must_match_facts": node.get("must_match_facts"),
                }
            )
            if node_type in {"cell_strip", "micro_grid"}:
                rounding = node.get("cell_rounding_in", node.get("rounding_in", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("cell_rounding_in")))
                if ("low_rounding" in fact_text or "rectangular" in fact_text) and isinstance(rounding, (int, float)) and float(rounding) > 0.06:
                    visual_grammar_items.append(
                        f"- [ ] [REBUILD] `{node_id}` records rectangular/low-rounding cells but uses rounding {float(rounding):.2f} in; use `cell_strip`/`micro_grid` with near-zero rounding."
                    )
                if not any(node.get(key) for key in ("cell_count", "count", "cells_count", "rows", "cols", "columns")):
                    visual_grammar_items.append(f"- [ ] `{node_id}` is `{node_type}` without explicit cell count/rows/cols.")
            if node_type == "polyline_wave" and not (node.get("points") or node.get("samples")):
                visual_grammar_items.append(
                    f"- [ ] [REBUILD] `{node_id}` is `polyline_wave` without points/samples; source-specific waves must not fall back to a generic curve."
                )
            if node_type in RIBBON_ARROW_NODE_TYPES:
                if not any(node.get(key) is not None for key in ("body_width_in", "body_width_px", "head_width_in", "head_width_px")):
                    visual_grammar_items.append(
                        f"- [ ] [REBUILD] `{node_id}` is `{node_type}` without explicit body/head width; thick source arrows should preserve visible ribbon geometry."
                    )
                if not edge_arrow_plan_id(node):
                    visual_grammar_items.append(
                        f"- [ ] [REBUILD] `{node_id}` is a source-visible ribbon arrow without arrow_plan_id; bind it to the arrow inventory so direction and endpoint can be reviewed."
                    )
            if node_type == "symbol_group":
                subshapes = node.get("subshapes", node.get("parts", node.get("primitives")))
                if exact_mode and not subshapes and not node.get("symbol_kind"):
                    visual_grammar_items.append(
                        f"- [ ] `{node_id}` is `symbol_group` without subshapes or symbol_kind; encode the visible circle/triangle/line parts explicitly."
                    )
        if node_type == "ellipse_node" and str(node.get("text", "")).strip() in {"+", "x", "×", "⊗", "*"}:
            audit_items.append(f"- [ ] `{node.get('id')}` looks like an operator but uses `ellipse_node`; use `operator_node`.")
        if node_type == "operator_node":
            width = float(node.get("w", 0) or 0)
            height = float(node.get("h", 0) or 0)
            if max(width, height) > 0.42 and not node.get("allow_large_operator"):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a large operator node ({width:.2f}x{height:.2f} in); source paper figures usually use compact operators unless the crop shows a large circle."
                )
            symbol_box_w = float(
                node.get(
                    "symbol_box_w_in",
                    node.get("symbol_box_width_in", resolved_style.get("symbol_box_w_in", max(0.01, width))),
                )
                or max(0.01, width)
            )
            symbol_box_h = float(
                node.get(
                    "symbol_box_h_in",
                    node.get("symbol_box_height_in", resolved_style.get("symbol_box_h_in", max(0.01, height))),
                )
                or max(0.01, height)
            )
            symbol_ratio = min(symbol_box_w / max(0.01, width), symbol_box_h / max(0.01, height))
            if exact_mode and symbol_ratio < 0.40:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` operator symbol box only covers about {symbol_ratio:.2f} of the circle size; source operators usually keep the glyph more legible and visually centered."
                )
            offset_x = abs(float(node.get("symbol_offset_x_in", resolved_style.get("symbol_offset_x_in", 0.0)) or 0.0))
            offset_y = abs(float(node.get("symbol_offset_y_in", resolved_style.get("symbol_offset_y_in", 0.0)) or 0.0))
            if exact_mode and (offset_x > width * 0.12 or offset_y > height * 0.12):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` offsets its operator glyph by {offset_x:.2f}x{offset_y:.2f} in; compare the crop and recentre unless the source explicitly shows an off-center symbol."
                )
            if exact_mode and not any(node_or_style_has_key(node, key) for key in ("operator_size_tier", "symbol_font_size_pt", "symbol_box_w_in", "symbol_box_h_in")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` operator mark has no explicit size contract. "
                    "Set `operator_size_tier` or explicit symbol box/font size so plus/minus/multiply nodes do not float between crops."
                )
        if node_type == "tensor_stack":
            mode = str(node.get("stack_render_mode", node.get("render_mode", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("stack_render_mode", "")))).lower()
            perspective_raw = node.get("perspective_mode", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("perspective_mode", ""))
            perspective_mode = "" if perspective_raw in {None, ""} else str(perspective_raw).lower()
            aspect = float(node.get("w", 0) or 0) / max(0.001, float(node.get("h", 0) or 0))
            semantic = " ".join(str(node.get(key, "")) for key in ("id", "role", "semantic_role", "label", "text")).lower()
            if exact_mode and mode in {"slanted_sheets", "thin_slabs", "paper_sheets", "parallelogram_sheets"} and (
                "feature" in semantic or "tensor" in semantic or "station" in semantic or "fused" in semantic or aspect > 0.9
            ):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` uses thin/slanted tensor sheets for a likely feature tensor; if the crop shows thick black-edged 3D slabs, use `stack_render_mode: \"feature_cuboids\"`."
                )
            if exact_mode and mode in {"feature_cuboids", "thick_cuboids", "feature_stack", "paper_feature_stack", "thick_feature_map"} and float(node.get("line_weight_pt", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("line_weight_pt", 1.0)) or 1.0) < 1.0:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a thick feature tensor with light outline; source-like 3D stacks often need line_weight_pt around 1.1-1.5."
                )
            if exact_mode and mode in {"feature_cuboids", "thick_cuboids", "feature_stack", "paper_feature_stack", "thick_feature_map"} and any(token in semantic for token in {"thin", "slab", "sheet", "paper_sheet"}):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is semantically marked as a thin/slab tensor but uses a thick cuboid mode; if the crop shows narrow layered slabs, use `stack_render_mode: \"thin_feature_slabs\"`."
                )
            if exact_mode and mode in {"thin_feature_slabs", "thin_feature_stack", "layered_slabs", "source_thin_slabs", "paper_thin_feature"} and not node.get("source_bbox_px", node.get("source_bbox")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` uses crop-sensitive thin feature slabs without source_bbox_px; bind it to the tensor crop so later visual review can judge thickness and layer count."
                )
            if exact_mode and not perspective_mode and not node.get("source_bbox_px", node.get("source_bbox")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` tensor stack has neither perspective_mode nor source_bbox_px; thickness and perspective may drift during polishing."
                )
            if exact_mode and perspective_mode in {"flat", "front"} and mode in {"feature_cuboids", "thick_cuboids", "feature_stack", "paper_feature_stack", "thick_feature_map"}:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` asks for flat/front perspective but still uses thick cuboid tensor mode; compare the crop before spending time on color or shadow."
                )
            if exact_mode and not any(node_or_style_has_key(node, key) for key in ("stack_render_mode", "render_mode")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` tensor stack has no explicit shape-family contract. "
                    "Choose thin slabs, thick cuboids, slanted sheets, or flat sheets explicitly before depth tuning."
                )
        if node_type == "math_text":
            text_value = str(node.get("text", "\n".join(str(item) for item in node.get("lines", [])))).strip()
            render_mode = str(node.get("math_render_mode", node.get("render_mode", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("math_render_mode", "")))).lower()
            if exact_mode and render_mode in {"compact_unicode", "unicode", "single_box", "single_text", "plain_compact"} and re.search(r"[A-Za-z]_([A-Za-z]{2,}|[A-Z0-9_]{2,})", text_value):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` uses compact/unicode math mode for a word-like subscript; paper labels such as `P_RGB` or `f_fused` usually need fragment math so the subscript stays attached."
                )
            if exact_mode and any(marker in text_value for marker in ("′", "'", "^")) and render_mode in {"compact_unicode", "unicode", "single_box", "single_text", "plain_compact"}:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` contains prime/hat notation in a compact math mode; use fragment math before coordinate nudging."
                )
        if node_type == "concat_operator":
            mode = str(node.get("glyph_mode", node.get("shape_mode", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("glyph_mode", "")))).lower()
            if exact_mode and mode in {"boxed", "box", "rect", "square_box"}:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` renders concat as a box; if the source shows a compact `[]` glyph, use `glyph_mode: \"source_bracket\"` or `glyph_mode: \"text\"`."
                )
            width = float(node.get("w", 0) or 0)
            height = float(node.get("h", 0) or 0)
            if max(width, height) > 0.55 and not node.get("allow_large_operator"):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a large concat operator; compare the source crop and use compact bracket/bar sizing if it should be a small merge glyph."
                )
            in_edges = [
                edge
                for edge in edges
                if endpoint_node_id(edge.get("to")) == node.get("id")
            ]
            if len(in_edges) >= 3 and not (node.get("port_positions") or node.get("ports")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` has {len(in_edges)} incoming edges but no explicit concat port positions; source-like fan-in needs stable ports."
                )
            if exact_mode and not node_or_style_has_key(node, "glyph_mode"):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` concat mark has no explicit glyph_mode. "
                    "Do not leave paper concat syntax to a generic default when the source crop shows a specific bracket/bar mark."
                )
            if exact_mode and not any(node_or_style_has_key(node, key) for key in ("concat_size_tier", "tick_in", "gap_ratio")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` concat mark has no explicit size contract. "
                    "Set `concat_size_tier` or explicit bracket tick/gap values so the merge glyph does not drift."
                )
        if node_type == "brace_merge":
            incoming = [edge for edge in edges if endpoint_node_id(edge.get("to")) == node.get("id")]
            if len(incoming) >= 3 and not (node.get("tick_positions") or node.get("port_positions")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` merges {len(incoming)} inputs but has no tick/port positions; source-like braces need visible aligned merge ticks."
                )
            if exact_mode and max(float(node.get("w", 0) or 0), float(node.get("h", 0) or 0)) > 0.9 and str(node.get("brace_shape", node.get("shape", ""))).lower() not in {"tight", "tight_curly", "paper", "pinched", "source_like"}:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a large smooth brace; if the source crop has a short tight merge brace, set `brace_shape: \"source_like\"` or add `curve_tightness`, then lock tick positions."
                )
        if node_type == "bracket":
            shape = str(node.get("shape", node.get("bracket_shape", ""))).lower()
            width = float(node.get("w", 0) or 0)
            height = float(node.get("h", 0) or 0)
            aspect = max(width, height) / max(1e-9, min(width, height))
            if exact_mode and shape in {"curly", "brace", "curly_brace"} and aspect >= 4.0:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a high-aspect generic curly bracket; if it is a dimension/range marker, use `dimension_brace` or `shape: \"paper_curly\"` so it stays narrow instead of becoming wave-like."
                )
        if node_type == "multi_port_junction":
            raw_ports = node.get("ports", node.get("port_positions", []))
            if isinstance(raw_ports, list) and raw_ports:
                if any(isinstance(item, dict) for item in raw_ports):
                    unresolved = [
                        item
                        for item in raw_ports
                        if isinstance(item, dict) and float(item.get("length_in", item.get("port_length_in", 0)) or 0) <= 0
                    ]
                    if len(unresolved) == len([item for item in raw_ports if isinstance(item, dict)]):
                        audit_items.append(
                            f"- [ ] `{node.get('id')}` uses explicit junction port positions without visible tick lengths; verify connected edges land on those positions in the visual crop."
                        )
        if node_type in {"token_grid", "grid_matrix", "feature_vector_stack"}:
            source_bbox = node.get("source_bbox_px", node.get("source_bbox"))
            if exact_mode and not source_bbox and not node.get("source_aspect_ratio"):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a compact paper grid/vector without source_bbox_px; count/spacing mistakes are hard to catch without source-region binding."
                )
        if node_type == "token_grid":
            if float(node.get("w", 0) or 0) and float(node.get("h", 0) or 0):
                rows = int(node.get("rows", 1) or 1)
                cols = int(node.get("cols", 1) or 1)
                gap = float(node.get("cell_gap_in", 0) or 0)
                cell_w = (float(node.get("w", 0) or 0) - gap * max(0, cols - 1)) / max(1, cols)
                cell_h = (float(node.get("h", 0) or 0) - gap * max(0, rows - 1)) / max(1, rows)
                if exact_mode and rows == 1 and cols > 1 and max(cell_w, cell_h) / max(1e-6, min(cell_w, cell_h)) > 1.45 and not node.get("square_cells"):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` token cells are strongly non-square ({cell_w:.2f}x{cell_h:.2f}); if the source shows square tokens, set `square_cells: true` before visual review."
                    )
        if node_type == "layer_sequence":
            mode = str(node.get("block_style_mode", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("block_style_mode", ""))).lower()
            block_fills = node.get("block_fills", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("block_fills") if isinstance(node.get("style"), dict) else None)
            title_text = str(node.get("title", node.get("text", ""))).strip()
            blocks = node.get("blocks", node.get("labels", []))
            if mode in {"colored_paper_strip", "colored_vertical_strip", "paper_colored_strip"} and not isinstance(block_fills, list):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` uses colored layer strips without block_fills; preserve source colors explicitly before visual review."
                )
            if mode in {"colored_paper_strip", "colored_vertical_strip", "paper_colored_strip"} and node.get("ignore_block_fills"):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is colored but still has ignore_block_fills; remove it or set block_fill_policy/preserve_block_fills so future scene edits do not regress colored bars to white."
                )
            if exact_mode and str(node.get("density_mode", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("density_mode", ""))).lower() not in {"dense", "source_dense", "paper_dense", "compact"}:
                if isinstance(blocks, list) and len(blocks) >= 4:
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` has {len(blocks)} layer blocks but no density_mode; if the source crop is tight, use `density_mode: \"source_dense\"` before tuning text."
                    )
            if exact_mode and title_text:
                if not any(node_or_style_has_key(node, key) for key in ("title_h_in", "title_area_ratio")):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` has a visible title but no explicit title area contract. Add `title_h_in` or `title_area_ratio` before micro-adjusting block sizes."
                    )
                if not any(node_or_style_has_key(node, key) for key in ("content_padding_top_in", "content_padding_bottom_in", "padding_top_in", "padding_bottom_in")):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` has no explicit content/title spacing contract. In strict replica mode, title band spacing should not be left to generic defaults."
                    )
            if exact_mode and isinstance(blocks, list) and len(blocks) >= 4:
                if not any(
                    node_or_style_has_key(node, key)
                    for key in ("block_gap_in", "padding_in", "padding_left_in", "padding_right_in", "content_padding_left_in", "content_padding_right_in")
                ):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` has repeated strips but no explicit density spacing contract. "
                        "Write strip gap and padding explicitly instead of inheriting generic defaults."
                    )
                if not any(node_or_style_has_key(node, key) for key in ("block_rounding_in", "block_shadow")):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` has no explicit strip rounding/shadow contract. "
                        "Paper-style repeated modules should not rely only on profile defaults."
                    )
            if isinstance(blocks, list) and all(isinstance(node.get(key), (int, float)) for key in ("w", "h")):
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    block_w = block.get("w", block.get("width"))
                    block_h = block.get("h", block.get("height"))
                    label = block.get("text", block.get("label", "<unnamed>"))
                    if isinstance(block_w, (int, float)) and float(block_w) > float(node["w"]) * 1.25:
                        rebuild_items.append(
                            f"- [ ] [REBUILD] `{node.get('id')}` nested block `{label}` width is larger than its parent; pixel-scene local block geometry was likely not normalized."
                        )
                    if isinstance(block_h, (int, float)) and float(block_h) > float(node["h"]) * 1.25:
                        rebuild_items.append(
                            f"- [ ] [REBUILD] `{node.get('id')}` nested block `{label}` height is larger than its parent; pixel-scene local block geometry was likely not normalized."
                        )
        if node_type == "feature_map_banded":
            overlays = node.get("overlays", node.get("vertical_bands", []))
            for overlay in overlays or []:
                fill = str(overlay.get("fill", "")).lower() if isinstance(overlay, dict) else ""
                if fill in {"#000000", "#111111", "black"}:
                    audit_items.append(f"- [ ] `{node.get('id')}` uses opaque dark overlay; use `feature_map_grid` if the source is a shaded heatmap.")
                    break
        if node_type == "process_box":
            style = node.get("style", {}) if isinstance(node.get("style"), dict) else {}
            if style.get("line_dash") in {"dash", "dot", "long_dash"} and not str(node.get("text", "")).strip():
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{node.get('id')}` is a dashed empty `process_box`; use `dashed_region` for annotation frames and keep labels as separate text."
                )
        if node_type == "ellipse_node":
            node_id = str(node.get("id", "")).lower()
            if not str(node.get("text", "")).strip() and any(token in node_id for token in {"outer", "loop", "cycle"}):
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{node.get('id')}` looks like a passive ellipse used as a training/cycle loop. Use `loop_arrow`/`curved_arrow` paths for visible flow direction instead of an ellipse plus detached arrowheads."
                )
        if node_type == "text_block":
            text = str(node.get("text", ""))
            style = node.get("style", {}) if isinstance(node.get("style"), dict) else {}
            font_size = float(style.get("font_size_pt", 12) or 12)
            if exact_mode and len(text.strip()) >= 30 and not node.get("role") and not node.get("semantic_role"):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a long text block without role/semantic_role; classify it as title/caption/header/formula/annotation before visual polishing."
                )
            if text.strip() and all(isinstance(node.get(key), (int, float)) for key in ("w", "h")):
                estimated_w, estimated_h = estimate_text_box(text, font_size)
                if float(node.get("w", 0)) > 0 and float(node.get("h", 0)) > 0:
                    if estimated_w > float(node["w"]) * 1.45 or estimated_h > float(node["h"]) * 1.35:
                        audit_items.append(
                            f"- [ ] `{node.get('id')}` text is likely to shrink/wrap ({estimated_w:.2f}x{estimated_h:.2f} estimated vs {float(node['w']):.2f}x{float(node['h']):.2f}); use `math_text`, caption runs, or source-sized text box."
                        )
            if looks_like_vector_formula(text):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` looks like a vector/matrix formula but uses `text_block`; use `math_vector` for aligned brackets and entries."
                )
            if text_has_raw_loss_subscript(text):
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{node.get('id')}` uses raw underscore loss notation; use `math_text` or explicit text runs so `L_adv`/`L_rec` render as subscript-style formulas."
                )
            if exact_mode and any(token in text for token in ("Fig.", "Figure", "图")) and len(text) >= 12:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` looks like a paper caption but uses `text_block`; use `caption_block` so bold prefix, centering, and single-baseline runs stay stable."
                )
        if node_type in {"math_text", "loss_region"}:
            text_parts: list[str] = []
            if node.get("text"):
                text_parts.append(str(node.get("text")))
            formulas = node.get("formulas", node.get("lines"))
            if isinstance(formulas, list):
                text_parts.extend(str(item) for item in formulas)
            elif isinstance(formulas, str):
                text_parts.append(formulas)
            if any(text_has_compact_loss_notation(part) for part in text_parts):
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{node.get('id')}` uses compact loss notation like `Ladv`/`Lrec`; normalize to `L_adv`/`L_rec` so `math_text` can render subscripts."
                )
        if node_type == "caption_block":
            runs = node.get("runs")
            if exact_mode and not node.get("source_bbox_px", node.get("source_bbox")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a caption_block without source_bbox_px; caption centering, prefix/body spacing, and baseline drift are hard to judge without source binding."
                )
            if truthy(node.get("strict_mode"), False):
                if not isinstance(runs, list) or len(runs) < 2:
                    rebuild_items.append(
                        f"- [ ] [REBUILD] `{node.get('id')}` uses strict caption mode but does not provide separate runs for prefix/body; paper captions should not collapse into one floating text run."
                    )
                else:
                    first_run = runs[0] if isinstance(runs[0], dict) else {}
                    if str(first_run.get("font_weight", "")).lower() not in {"bold", "semibold", "heavy"}:
                        audit_items.append(
                            f"- [ ] `{node.get('id')}` strict caption first run is not bold; source-like captions usually keep the `Fig.` prefix bold."
                        )
        if node_type in RUN_TEXT_NODE_TYPES and all(isinstance(node.get(key), (int, float)) for key in ("w", "h")):
            text_style = resolved_style or (node.get("style", {}) if isinstance(node.get("style"), dict) else {})
            text_value = node_text_for_font(node)
            text_role = str(node.get("text_role", node.get("semantic_role", ""))).lower()
            if exact_mode and text_value.strip():
                if (text_looks_like_math_content(text_value) or text_role in {"formula", "math", "math_label"}) and not node_uses_math_contract(node):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` contains math-like content but still uses plain `{node_type}` rendering. "
                        "Rebuild it as `math_text`, `formula_text_block`, or run-based math fragments before coordinate nudging."
                    )
            if text_value.strip():
                estimated_w, estimated_h = estimate_run_text_box(node, text_style)
                node_w = float(node.get("w", 0) or 0)
                node_h = float(node.get("h", 0) or 0)
                if node_w > 0 and node_h > 0:
                    width_ratio = estimated_w / node_w
                    height_ratio = estimated_h / node_h
                    if exact_mode and width_ratio < 0.32 and height_ratio < 0.55 and node_type != "caption_block":
                        audit_items.append(
                            f"- [ ] `{node.get('id')}` text occupies only about {width_ratio:.2f}x{height_ratio:.2f} of its box; the label area is likely too loose versus the source crop."
                        )
                    if exact_mode and node_type == "caption_block" and width_ratio < 0.45:
                        audit_items.append(
                            f"- [ ] `{node.get('id')}` caption content is much narrower than its box ({width_ratio:.2f} width ratio); compare the caption crop and tighten the caption bbox or run spacing."
                        )
                    if isinstance(node.get("runs"), list) and len(node.get("runs")) >= 2 and exact_mode and not node.get("source_bbox_px", node.get("source_bbox")):
                        audit_items.append(
                            f"- [ ] `{node.get('id')}` uses mixed text runs without source_bbox_px; local baseline and run-spacing drift will be hard to attribute in crop review."
                        )
                    if node_type == "annotation_block" and isinstance(node.get("runs"), list):
                        text_role = str(node.get("text_role", node.get("semantic_role", ""))).lower()
                        if exact_mode and text_role not in {"annotation", "note", "callout", "caption", "formula"}:
                            audit_items.append(
                                f"- [ ] `{node.get('id')}` uses run-based annotation text but has no explicit text_role/semantic_role; classify it so later review knows whether to judge it as note, caption, or formula."
                            )
        if exact_mode and node_type in {"rounded_process", "dashed_region", "group_container", "probability_bar_list", "tfr_panel", "layer_sequence", "operator_node", "concat_operator"}:
            explicit_shape_keys: dict[str, tuple[str, ...]] = {
                "rounded_process": ("rounding_in",),
                "dashed_region": ("rounding_in", "line_dash"),
                "group_container": ("line_dash",),
                "probability_bar_list": ("rounding_in", "padding_in", "row_gap_in", "label_w_in", "bar_max_fraction"),
                "tfr_panel": ("rounding_in",),
                "layer_sequence": ("block_gap_in",),
                "operator_node": ("symbol_font_size_pt",),
                "concat_operator": ("glyph_mode",),
            }
            missing_keys = [key for key in explicit_shape_keys.get(node_type, ()) if not node_or_style_has_key(node, key)]
            if missing_keys:
                audit_items.append(
                    f"- [ ] `{node.get('id')}` (`{node_type}`) lacks explicit replica shape/layout controls `{', '.join(missing_keys)}`; "
                    "do not leave rounding, padding, or spacing to generic profile defaults in strict replica mode."
                )
        if exact_mode and node_type in {"rounded_process", "annotation_block", "caption_block", "probability_bar_list", "layer_sequence", "tfr_panel"}:
            if not any(node_or_style_has_key(node, key) for key in ("shadow", "panel_shadow", "block_shadow")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` (`{node_type}`) should set shadow explicitly, even when the value is `null`, so soft-paper depth is part of the scene contract."
                )
        if node_type == "probability_bar_list":
            items = node.get("items", node.get("rows", []))
            if exact_mode:
                if not node.get("source_bbox_px", node.get("source_bbox")):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` probability panel has no source_bbox_px; panel corner radius, padding, and bar/text anchoring are hard to judge without a source-bound crop."
                    )
                if not (
                    node_or_style_has_key(node, "axis_w_in")
                    or node_or_style_has_key(node, "axis_offset_x_in")
                ):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` probability panel does not state the axis position explicitly. This often causes the left rule and bar start to drift."
                    )
                if not node_or_style_has_key(node, "bar_value_anchor"):
                    audit_items.append(
                        f"- [ ] `{node.get('id')}` probability panel does not state `bar_value_anchor`; internal text/bar placement is a major fidelity control."
                    )
                if isinstance(items, list) and any(isinstance(item, dict) and item.get("bar_value_label") for item in items):
                    if not (
                        node_or_style_has_key(node, "bar_value_w_in")
                        or node_or_style_has_key(node, "bar_value_align")
                    ):
                        audit_items.append(
                            f"- [ ] `{node.get('id')}` uses inline panel row text but does not state `bar_value_w_in` or `bar_value_align`; the probability-panel typography is underconstrained."
                        )
        if node_type in {"formula_text_block", "annotation_block", "vector_label_group", "branch_trunk", "merge_trunk", "paper_bus", "collector_bar", "junction_bus"}:
            if exact_mode and not node.get("source_bbox_px", node.get("source_bbox")):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` (`{node_type}`) has no source_bbox_px; local shape/text drift will be hard to attribute during crop review."
                )
        if node_type == "image_tile":
            node_id = str(node.get("id", "")).lower()
            asset_ref = str(node.get("asset_ref", "")).lower()
            if any(token in node_id or token in asset_ref for token in {"quality_head", "extractor", "aggregation_quality"}):
                audit_items.append(
                    f"- [ ] `{node.get('id')}` is a raster tile for a paper wedge/module; prefer editable `trapezoid_node`/`polygon_node` unless this is an intentional fidelity-speed tradeoff."
                )

    for issue in tfr_panel_layout_issues(nodes_by_id, node_types_by_id):
        audit_items.append(f"- [ ] {issue}")

    children_by_container: dict[str, list[str]] = {}
    for node_id in visible_ids:
        container_id = containers_by_node.get(node_id)
        if container_id:
            children_by_container.setdefault(str(container_id), []).append(node_id)
    for container in containers:
        container_id = str(container.get("id", ""))
        if not container_id or not all(isinstance(container.get(key), (int, float)) for key in ("w", "h")):
            continue
        child_ids = children_by_container.get(container_id, [])
        if exact_mode:
            source_ratio = source_ratio_for_container(container)
            if source_ratio is None and container.get("type") != "audit_region":
                audit_items.append(
                    f"- [ ] `{container_id}` lacks source_bbox_px/source_aspect_ratio; visual LLM cannot tell whether region proportion or child coordinates caused mismatch."
                )
            elif source_ratio:
                ratio = float(container["w"]) / max(0.001, float(container["h"]))
                if abs(ratio - source_ratio) / source_ratio > 0.22:
                    rebuild_items.append(
                        f"- [ ] [REBUILD] `{container_id}` target aspect {ratio:.2f} differs from source region {source_ratio:.2f}; lock region bbox before tuning nodes."
                    )
        if child_ids and all(isinstance(container.get(key), (int, float)) for key in ("w", "h")):
            area = max(0.001, float(container["w"]) * float(container["h"]))
            density = len(child_ids) / area
            expected_density = container.get("expected_node_density", container.get("source_node_density"))
            if expected_density is not None:
                try:
                    expected = float(expected_density)
                    if expected > 0 and (density / expected < 0.55 or density / expected > 1.85):
                        rebuild_items.append(
                            f"- [ ] [REBUILD] `{container_id}` density {density:.2f} nodes/sq in differs from expected {expected:.2f}; region is likely too loose/tight compared with source."
                        )
                except (TypeError, ValueError):
                    audit_items.append(f"- [ ] `{container_id}` expected/source node density is not numeric.")

    for edge in edges:
        edge_id = str(edge.get("id", "<missing-id>"))
        edge_role = str(edge.get("edge_role", edge.get("semantic_role", ""))).lower()
        if edge_role in INTERNAL_EDGE_ROLES:
            decorative_internal_items.append(
                f"- [ ] `{edge_id}` is `{edge_role}`; review it as symbol/icon geometry, not as a main topology arrow."
            )
            continue
        source_id, target_id, source_container, target_container = edge_container_cache.get(edge_id, (None, None, None, None))
        source_type = node_types_by_id.get(source_id or "")
        target_type = node_types_by_id.get(target_id or "")
        points = route_cache.get(edge_id, [])
        route_name = str(edge.get("route", edge.get("style", {}).get("route", ""))).lower()
        path_length = line_length(points) if points else 0.0
        diagonal = any(segment_has_diagonal(start, end) for start, end in zip(points, points[1:]))
        edge_type = str(edge.get("type", ""))

        if gan_tfr_context:
            from_role = edge_endpoint_role(edge, "from", nodes_by_id, node_types_by_id)
            to_role = edge_endpoint_role(edge, "to", nodes_by_id, node_types_by_id)
            if from_role == "discriminator" and to_role == "generated":
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{edge_id}` appears reversed for a GAN/TFR diagram: Generated/Reconstructed TFR should feed into Discriminator, not Discriminator into Generated."
                )

        if diagonal and not edge.get("allow_diagonal") and edge_type not in {"fork_connector", "residual_connector", "residual_loop", *CURVED_EDGE_TYPES}:
            audit_items.append(f"- [ ] `{edge_id}` is diagonal; most 1-to-1 paper-flow arrows should be horizontal/vertical.")
        if diagonal and edge.get("allow_diagonal") and edge_type in {"arrow_connector", "dynamic_connector"}:
            edge_name = edge_id.lower()
            if any(token in edge_name for token in {"gap", "gmp", "extractor", "quality", "aggregation", "projection", "environment", "spine"}):
                audit_items.append(
                    f"- [ ] `{edge_id}` allows diagonal routing but looks like a paper-flow lane; use `lane_arrow`, forced axis routing, or aligned explicit points."
                )
            if any(token in edge_name for token in FEEDBACK_TOKENS):
                audit_items.append(
                    f"- [ ] `{edge_id}` allows diagonal routing but looks like a loss/backprop feedback path; use `dashed_feedback_path` with explicit orthogonal points."
                )
        if diagonal and edge_type == "lane_arrow":
            audit_items.append(f"- [ ] `{edge_id}` is a `lane_arrow` but still contains a diagonal segment; align endpoints or force the lane axis.")
        if edge_type in {"fork_connector"} and str(edge.get("topology_motif", edge.get("semantic_role", ""))).lower() not in {"branch_trunk", "shared_branch", "trunk_branch", "one_to_many_trunk"}:
            audit_items.append(
                f"- [ ] `{edge_id}` uses fork_connector without a trunk-like topology motif; if the source is one shared main trunk then split, encode that explicitly."
            )
        if edge_type in {"join_connector"} and str(edge.get("topology_motif", edge.get("semantic_role", ""))).lower() not in {"merge_trunk", "shared_merge", "many_to_one_trunk"}:
            audit_items.append(
                f"- [ ] `{edge_id}` uses join_connector without a merge-trunk topology motif; if the source visually merges into one trunk, encode that explicitly."
            )
        if edge_type == "dashed_feedback_path":
            if diagonal:
                rebuild_items.append(f"- [ ] [REBUILD] `{edge_id}` is a `dashed_feedback_path` but still contains a diagonal segment; make the feedback path orthogonal.")
            if edge.get("allow_diagonal"):
                rebuild_items.append(f"- [ ] [REBUILD] `{edge_id}` is a `dashed_feedback_path` but relies on `allow_diagonal`; encode the actual path with explicit points.")
            if not edge.get("allow_region_interior_path"):
                for region in containers:
                    if region.get("type") not in {"dashed_region", "loss_region"}:
                        continue
                    if any(
                        segment_intersects_box_interior(start, end, node_box(region), clearance=0.01)
                        for start, end in zip(points, points[1:])
                    ):
                        rebuild_items.append(
                            f"- [ ] [REBUILD] `{edge_id}` draws through dashed region `{region.get('id')}`; route from a boundary point/port and keep the dashed annotation frame clean."
                        )
                        break
            stub_issue = loss_feedback_stub_issue(edge, points, nodes_by_id, node_types_by_id)
            if stub_issue:
                rebuild_items.append(f"- [ ] [REBUILD] {stub_issue}")
        if edge_type == "loop_arrow" and any(token in edge_id.lower() for token in {"outer", "loop", "cycle"}):
            style = edge_style(edge, component_map, profile)
            curve_mode = str(edge.get("curve_mode", edge.get("curve", style.get("curve_mode", "polyline")))).lower()
            if curve_mode in {"", "polyline", "straight"}:
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{edge_id}` is an outer update loop rendered as `{curve_mode or 'polyline'}`; use `curve_mode: \"smooth\"` and evenly sampled points so it does not look like a polygon border."
                )
            if not (edge.get("semantic_role") or edge.get("loop_role") or edge.get("label_id") or edge.get("loop_label_id")):
                audit_items.append(
                    f"- [ ] `{edge_id}` has no semantic role/label binding; set `semantic_role: \"outer_update_loop\"` and bind the bottom update label so the outer curve reads as process flow, not decoration."
                )
            tangent_issue = terminal_tangent_issue(edge, points)
            if tangent_issue:
                rebuild_items.append(f"- [ ] [REBUILD] {tangent_issue}")
            bounds = path_bounds(points)
            if bounds and isinstance(page.get("width"), (int, float)) and isinstance(page.get("height"), (int, float)):
                x1, y1, x2, y2 = bounds
                page_w = float(page["width"])
                page_h = float(page["height"])
                margin = float(edge.get("page_margin_in", style.get("page_margin_in", 0.0)))
                if x1 < margin or y1 < margin or x2 > page_w - margin or y2 > page_h - margin:
                    rebuild_items.append(
                        f"- [ ] [REBUILD] `{edge_id}` reaches page/export bounds ({x1:.2f},{y1:.2f},{x2:.2f},{y2:.2f}); keep the loop inside `page_background` so PNG/SVG export does not crop it."
                    )
            label_id = edge.get("label_id") or edge.get("loop_label_id")
            if isinstance(label_id, str) and label_id in nodes_by_id:
                label_box = expanded_box(node_box(nodes_by_id[label_id]), 0.025)
                if polyline_intersects_box_bbox(points, label_box, clearance=0.0):
                    rebuild_items.append(
                        f"- [ ] [REBUILD] `{edge_id}` overlaps its update label `{label_id}`; reshape the bottom arc or move the label so the loop and text do not collide."
                    )
        if edge_type in {"line_segment", "arrow_connector"} and any(token in edge_id.lower() for token in {"outer", "loop", "cycle"}):
            if edge_type == "line_segment" and len(points) >= 4:
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{edge_id}` is part of an outer loop drawn as a plain line segment; combine the loop into one `loop_arrow`/`curved_arrow` so the curve is continuous and the arrowhead follows the tangent."
                )
            elif edge_type == "arrow_connector":
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{edge_id}` looks like a detached arrowhead for an outer loop; put the arrowhead on the `loop_arrow`/`curved_arrow` path instead."
                )

        line_dash = str(edge.get("style", {}).get("line_dash", "")).lower()
        feedback_like = (
            edge_type == "dashed_feedback_path"
            or line_dash in {"dash", "dot", "long_dash"}
            or any(token in edge_id.lower() for token in FEEDBACK_TOKENS)
        )
        if feedback_like and edge_type not in {"dashed_feedback_path", "line_segment"}:
            rebuild_items.append(
                f"- [ ] [REBUILD] `{edge_id}` looks like a dashed/loss/backprop feedback route but uses `{edge_type}`; convert it to `dashed_feedback_path` before further coordinate tuning."
            )
        if feedback_like and edge_type == "line_segment" and str(edge_style(edge, component_map, profile).get("end_arrow", "")).lower() not in {"", "none"}:
            rebuild_items.append(
                f"- [ ] [REBUILD] `{edge_id}` is a dashed feedback-like `line_segment` with an arrowhead; replace fragmented short arrows with one semantic `dashed_feedback_path` or a shared bus."
            )
        if feedback_like and gan_tfr_context:
            target_role = edge_endpoint_role(edge, "to", nodes_by_id, node_types_by_id)
            source_role = edge_endpoint_role(edge, "from", nodes_by_id, node_types_by_id)
            effective_style = edge_style(edge, component_map, profile)
            end_arrow = str(effective_style.get("end_arrow", "")).lower()
            if target_role in {"real_tfr", "generated"} and end_arrow not in {"", "none"}:
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{edge_id}` points a feedback/loss arrow into `{target_role}`; panel/backprop legs should leave TFR panels toward a bus, not terminate at the panel input area."
                )
            if source_role in {"real_tfr", "generated"} and end_arrow not in {"", "none"} and any(token in edge_id.lower() for token in FEEDBACK_TOKENS):
                rebuild_items.append(
                    f"- [ ] [REBUILD] `{edge_id}` starts at a TFR panel but carries an arrowhead; use an arrowless panel-to-bus leg plus separate discriminator stubs."
                )
        if feedback_like and not edge.get("allow_text_overlap"):
            for text_node in nodes:
                text_id = str(text_node.get("id", ""))
                if node_types_by_id.get(text_id) not in (RUN_TEXT_NODE_TYPES | {"math_text", "formula_text_block"}):
                    continue
                if not str(text_node.get("text", text_node.get("lines", ""))).strip():
                    continue
                if is_background_node(text_node):
                    continue
                text_box = expanded_box(node_box(text_node), 0.025)
                if any(
                    segment_intersects_box_interior(start, end, text_box, clearance=0.0)
                    for start, end in zip(points, points[1:])
                ):
                    rebuild_items.append(
                        f"- [ ] [REBUILD] `{edge_id}` crosses text node `{text_id}`; reroute dashed/loss/backprop paths around labels instead of nudging text."
                    )
                    break

        if (
            source_container != target_container
            and edge_type not in {"line_segment", "boundary_arrow"}
            and not edge.get("allow_cross_container")
            and not edge.get("allow_direct_cross_container")
        ):
            if source_type != "boundary_port" and target_type != "boundary_port":
                audit_items.append(
                    f"- [ ] `{edge_id}` crosses module boundary from `{source_container}` to `{target_container}` without a `boundary_port`/`boundary_arrow`."
                )
        if exact_mode and source_container != target_container:
            from_endpoint = edge.get("from")
            to_endpoint = edge.get("to")
            if source_type != "boundary_port" and not endpoint_has_explicit_side_anchor(from_endpoint) and not edge.get("allow_direct_cross_container"):
                audit_items.append(
                    f"- [ ] `{edge_id}` leaves `{source_id}` across a module boundary without an explicit side anchor. "
                    "Paper-figure cross-module flow should not default to center-to-center routing."
                )
            if target_type != "boundary_port" and not endpoint_has_explicit_side_anchor(to_endpoint) and not edge.get("allow_direct_cross_container"):
                audit_items.append(
                    f"- [ ] `{edge_id}` enters `{target_id}` across a module boundary without an explicit side anchor. "
                    "Use boundary ports, side anchors, or junction/bus grammar to lock the landing point."
                )
            if path_length > 0.75 and edge_type in {"arrow_connector", "dynamic_connector", "line_segment"} and route_name in {"", "auto", "straight"} and not edge.get("points") and not edge.get("force_axis"):
                audit_items.append(
                    f"- [ ] `{edge_id}` is a long cross-module route but leaves routing grammar implicit. "
                    "Set an axis-aligned route, force_axis, or explicit orthogonal points before detail polishing."
                )

        if edge_type == "line_segment" and source_container != target_container and path_length > 0.35:
            audit_items.append(
                f"- [ ] `{edge_id}` is a long cross-boundary visual line; if the source shows a frame output, replace it with `boundary_arrow`."
            )
        if edge_type in {"arrow_connector", "dynamic_connector", "line_segment"} and str(edge.get("topology_motif", "")).lower() in {"branch_trunk", "merge_trunk", "paper_bus", "collector_bar"}:
            audit_items.append(
                f"- [ ] `{edge_id}` is tagged with topology motif `{edge.get('topology_motif')}` but still uses a generic edge; promote that local structure to a semantic trunk/bus component."
            )
        if edge_type in {"arrow_connector", "dynamic_connector", "lane_arrow"} and points:
            length = path_length
            if length > 2.6 and not any(edge.get(key) for key in ("bus_id", "bundle_id", "junction_id", "source_region_id")) and not edge.get("allow_long_sparse"):
                audit_items.append(
                    f"- [ ] `{edge_id}` is a long sparse connector ({length:.2f} in); source-like dense paper figures usually need an explicit bus/junction/boundary port or region bbox check."
                )
            if len(points) <= 2 and source_container != target_container and source_container and target_container and not edge.get("allow_direct_cross_container"):
                audit_items.append(
                    f"- [ ] `{edge_id}` directly jumps between regions with no intermediate point; compare source crop for orthogonal lane, bus, or boundary crossing."
                )

    if gan_tfr_context:
        parallel_backprop: list[tuple[str, float, float]] = []
        for edge in edges:
            edge_id = str(edge.get("id", ""))
            if edge.get("type") != "dashed_feedback_path":
                continue
            if not any(token in edge_id.lower() for token in {"backprop", "bottom", "disc", "loss"}):
                continue
            points = route_cache.get(edge_id, [])
            if len(points) < 2:
                continue
            start, end = points[0], points[-1]
            if abs(start[0] - end[0]) <= 0.03 and abs(start[1] - end[1]) > 0.35:
                target_role = edge_endpoint_role(edge, "to", nodes_by_id, node_types_by_id)
                if target_role == "discriminator" or "disc" in edge_id.lower():
                    parallel_backprop.append((edge_id, start[0], start[1]))
        if len(parallel_backprop) >= 3:
            xs = sorted(item[1] for item in parallel_backprop)
            min_spacing = min((b - a for a, b in zip(xs, xs[1:])), default=999.0)
            unbundled = [
                edge_id
                for edge_id, _, _ in parallel_backprop
                if not any(edge.get("id") == edge_id and edge.get("bundle_id") for edge in edges)
            ]
            if min_spacing < 0.18 or unbundled:
                rebuild_items.append(
                    "- [ ] [REBUILD] GAN/TFR backprop arrows contain three or more parallel dashed vertical paths into the discriminator; "
                    "use a shared `merge_bus`/`junction_point` with `bundle_id` and controlled spacing so the bottom loss system reads as one clean feedback bus."
                )

    lines: list[str] = []
    title = scene.get("metadata", {}).get("title", "visiomaster scene")
    lines.append(f"# Visiomaster Audit: {title}")
    lines.append("")
    lines.append(f"- Style profile: `{profile_name}`")
    lines.append(f"- Nodes: {len(nodes)}")
    lines.append(f"- Edges: {len(edges)}")
    visible_count = sum(1 for node in containers if node.get("type") in {"group_container", "dashed_region", "loss_region"})
    dashed_count = sum(1 for node in containers if node.get("type") == "dashed_region")
    loss_count = sum(1 for node in containers if node.get("type") == "loss_region")
    audit_count = sum(1 for node in containers if node.get("type") == "audit_region")
    lines.append(f"- Containers: {len(containers)} (`visible frames`: {visible_count}, `dashed_region`: {dashed_count}, `loss_region`: {loss_count}, `audit_region`: {audit_count})")
    lines.append("")

    lines.append("## Typography Review")
    if resolved_font_counts:
        summary = ", ".join(
            f"`{font}` ({count})"
            for font, count in sorted(resolved_font_counts.items(), key=lambda item: (-item[1], item[0].lower()))
        )
        lines.append(f"- Resolved fonts: {summary}")
    else:
        lines.append("- No text-bearing font usage found.")
    if typography_items:
        lines.extend(typography_items)
    else:
        lines.append("- No obvious font availability or source-font mismatch items found.")
    lines.append("")

    if warnings:
        lines.append("## Container Inference Warnings")
        lines.extend(f"- [ ] {warning}" for warning in warnings)
        lines.append("")

    lines.append("## Module Checklist")
    if not containers:
        lines.append("- [ ] No `group_container` or `audit_region` modules found. Complex paper figures should encode visible frames or invisible logical audit regions.")
    for container in containers:
        container_id = str(container.get("id"))
        child_ids = [
            node_id
            for node_id, parent_id in containers_by_node.items()
            if parent_id == container_id and node_id != container_id
        ]
        ingress = []
        egress = []
        internal = []
        for edge in edges:
            edge_id = str(edge.get("id", "<missing-id>"))
            _, _, source_container, target_container = edge_container_cache.get(edge_id, (None, None, None, None))
            if source_container == container_id and target_container == container_id:
                internal.append(edge)
            elif source_container != container_id and target_container == container_id:
                ingress.append(edge)
            elif source_container == container_id and target_container != container_id:
                egress.append(edge)

        lines.append(f"### `{container_id}`")
        if container.get("type") == "audit_region":
            lines.append("- Frame: invisible logical audit region")
        else:
            lines.append(f"- Frame: `{container.get('shape', container.get('container_shape', 'rectangle'))}` `{container.get('line_dash', container.get('style', {}).get('line_dash', 'style/default'))}`")
        lines.append(f"- Children ({len(child_ids)}): " + (", ".join(f"`{child}`" for child in child_ids) if child_ids else "none"))
        lines.append(f"- Incoming edges ({len(ingress)}): " + (", ".join(f"`{edge.get('id')}`" for edge in ingress) if ingress else "none"))
        lines.append(f"- Outgoing edges ({len(egress)}): " + (", ".join(f"`{edge.get('id')}`" for edge in egress) if egress else "none"))
        lines.append(f"- Internal edges ({len(internal)}): " + (", ".join(f"`{edge.get('id')}`" for edge in internal) if internal else "none"))
        lines.append("- [ ] Compare this module against the source crop: frame bounds, child count, labels, colors, and arrow directions.")
        lines.append("- [ ] Check every outgoing edge: does it originate from a component, a boundary, or a bus in the source?")
        lines.append("")

    lines.append("## Visual Grammar Audit Items")
    if visual_grammar_items:
        lines.extend(visual_grammar_items)
    else:
        lines.append("- No visual-grammar primitive issues found. Still compare source facts such as cell count, low rounding, wave samples, and symbol internals visually.")
    lines.append("")

    lines.append("## Decorative/Internal Audit Items")
    if decorative_internal_items:
        lines.extend(decorative_internal_items)
    else:
        lines.append("- No decorative/internal edge roles found.")
    lines.append("")

    lines.append("## Topology Review Items")
    if rebuild_items:
        lines.append("### Rebuild Required")
        lines.extend(rebuild_items)
        lines.append("")
    if audit_items:
        lines.extend(audit_items)
    elif rebuild_items:
        lines.append("- Additional topology review can continue after the rebuild-required items are fixed.")
    else:
        lines.append("- No obvious topology review items found. Still compare the rendered PNG against the source by module.")
    lines.append("")

    lines.append("## Edge Inventory")
    for edge in edges:
        edge_id = str(edge.get("id", "<missing-id>"))
        _, _, source_container, target_container = edge_container_cache.get(edge_id, (None, None, None, None))
        route = edge.get("route", edge.get("style", {}).get("route", "style/default"))
        lines.append(f"- `{edge_id}`: `{edge.get('type')}` `{route}` `{source_container}` -> `{target_container}`")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a module-level audit report for a visiomaster scene.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--output", help="Optional markdown report path")
    parser.add_argument(
        "--fail-on-rebuild",
        action="store_true",
        help="Exit non-zero when audit finds [REBUILD] items that require local subsystem reconstruction.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scene_path = Path(args.scene).resolve()
    report = audit_scene(load_scene(scene_path))
    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = scene_path.with_suffix(".audit.md")
    output_path.write_text(report, encoding="utf-8")
    print(f"Wrote audit report: {output_path}")
    rebuild_count = report.count("[REBUILD]")
    if args.fail_on_rebuild and rebuild_count:
        print(f"Rebuild-required items: {rebuild_count}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
