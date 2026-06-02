#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from scene_to_visio import (
    edge_point,
    edge_route_points,
    edge_style,
    load_component_map,
    load_style_profiles,
    node_id_from_endpoint,
    normalize_scene_coordinates,
    resolve_profile,
)
from scene_validate import (
    base_node_id,
    edge_arrow_plan_id,
    endpoint_has_explicit_side_anchor,
    exact_mode_from_metadata,
    is_background_node,
    is_internal_edge,
    node_box,
    route_axes,
    segment_intersects_box_interior,
)


NO_ARROW_TEMPLATES = {
    "skip_arc_no_arrow",
    "orthogonal_bus_no_arrow",
    "straight_no_arrow",
    "dashed_no_arrow",
    "bus_no_arrow",
    "annotation_no_arrow",
}
END_ARROW_TEMPLATES = {
    "straight_flow",
    "vertical_flow",
    "orthogonal_flow",
    "rounded_orthogonal_flow",
    "bezier_arc",
    "fanout_arc",
    "branch_arc",
    "feedback_loop",
    "feedback_path",
    "boundary_flow",
}
CURVE_TEMPLATES = {"bezier_arc", "skip_arc_no_arrow", "fanout_arc", "branch_arc", "feedback_loop"}
SMOOTH_ALLOWED_TOKENS = {"wave", "wavy", "decorative", "hand_drawn", "hand-drawn", "freeform", "organic"}
AUDIT_FIELDS = (
    "id",
    "region",
    "region_regression_group",
    "from",
    "to",
    "color",
    "dash",
    "arrow_start",
    "arrow_end",
    "route_type",
    "curve_type",
    "expected_shape",
    "source_bbox",
    "confidence",
    "edge_id",
    "edge_type",
    "notes",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def object_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(object_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(object_text(item) for item in value)
    return ""


def arrow_plan_items(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    plan = metadata.get("arrow_plan")
    if plan is None:
        plan = metadata.get("edge_inventory")
    if plan is None:
        inventory = metadata.get("source_visual_inventory")
        if isinstance(inventory, dict):
            plan = inventory.get("arrow_plan", inventory.get("edge_inventory"))
    if not isinstance(plan, list):
        return []
    return [item for item in plan if isinstance(item, dict)]


def active_plan(plan: dict[str, Any]) -> bool:
    certainty = str(plan.get("certainty", "")).strip().lower()
    status = str(plan.get("status", "")).strip().lower()
    return certainty not in {"uncertain", "unknown"} and status not in {"optional", "skipped", "not_visible"}


def endpoint_label(plan: dict[str, Any], key: str) -> str:
    value = plan.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    aliases = ("source", "from_visual_object", "source_endpoint") if key == "from" else ("target", "to_visual_object", "target_endpoint")
    for alias in aliases:
        value = plan.get(alias)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalized_arrowhead_policy(plan: dict[str, Any]) -> str:
    value = str(plan.get("arrowhead_policy", plan.get("arrowhead", ""))).strip().lower().replace("-", "_")
    if not value:
        return "end_only"
    if value in {"none", "no", "no_arrow", "no_arrowhead", "arrowless"}:
        return "none"
    if value in {"end", "target", "terminal", "end_only", "end_triangle", "arrow_end"}:
        return "end_only"
    if value in {"start", "source", "begin", "start_only", "begin_only"}:
        return "start_only"
    if value in {"both", "bidirectional", "double"}:
        return "both"
    return value


def infer_template(plan: dict[str, Any]) -> str:
    explicit = str(plan.get("arrow_template", plan.get("template", ""))).strip().lower()
    if explicit:
        return explicit
    route_shape = str(plan.get("route_shape", plan.get("shape", ""))).strip().lower()
    intent = str(plan.get("semantic_intent", plan.get("intent", ""))).strip().lower()
    policy = normalized_arrowhead_policy(plan)
    line_style = object_text(plan.get("line_style")).lower()
    if intent in {"feedback", "loss_backprop"}:
        return "feedback_loop" if route_shape == "loop" else "feedback_path"
    if intent in {"merge", "fan_in"} and policy == "none":
        return "orthogonal_bus_no_arrow"
    if intent in {"boundary_handoff", "frame_output"}:
        return "boundary_flow"
    if route_shape in {"straight_vertical", "vertical"}:
        return "vertical_flow" if policy != "none" else "straight_no_arrow"
    if route_shape in {"straight", "straight_horizontal", "horizontal"}:
        return "straight_flow" if policy != "none" else "straight_no_arrow"
    if route_shape in {"orthogonal", "elbow", "right_angle", "hv", "vh"}:
        return "orthogonal_flow" if policy != "none" else "orthogonal_bus_no_arrow"
    if route_shape == "rounded_orthogonal":
        return "rounded_orthogonal_flow" if policy != "none" else "orthogonal_bus_no_arrow"
    if intent in {"fork", "fan_out"} and route_shape in {"curved", "smooth_curve"}:
        return "fanout_arc"
    if route_shape in {"curved", "smooth_curve", "loop"}:
        return "skip_arc_no_arrow" if policy == "none" or "dash" in line_style else "bezier_arc"
    return "freeform" if route_shape in {"freeform", "diagonal", "short_diagonal"} else ""


def arrow_value(value: Any) -> str:
    return str(value or "none").strip().lower()


def actual_arrowhead_policy(style: dict[str, Any]) -> str:
    begin = arrow_value(style.get("begin_arrow"))
    end = arrow_value(style.get("end_arrow"))
    has_begin = begin not in {"", "none", "0", "false", "no"}
    has_end = end not in {"", "none", "0", "false", "no"}
    if has_begin and has_end:
        return "both"
    if has_begin:
        return "start_only"
    if has_end:
        return "end_only"
    return "none"


def arrow_policy_matches(expected: str, actual: str) -> bool:
    if expected in {"end", "end_only", "end_triangle"}:
        return actual == "end_only"
    if expected in {"none", "no_arrow", "arrowless"}:
        return actual == "none"
    if expected in {"start", "start_only"}:
        return actual == "start_only"
    if expected == "both":
        return actual == "both"
    return True


def line_dash(style: dict[str, Any]) -> str:
    return str(style.get("line_dash", style.get("dash", "solid")) or "solid").strip().lower()


def route_type(edge: dict[str, Any], style: dict[str, Any]) -> str:
    return str(edge.get("route_shape", edge.get("route", style.get("route", "auto"))) or "auto").strip().lower()


def curve_type(edge: dict[str, Any], style: dict[str, Any]) -> str:
    return str(edge.get("curve_type", edge.get("curve_mode", edge.get("curve", style.get("curve_mode", "polyline")))) or "polyline").strip().lower()


def line_length(points: list[tuple[float, float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def endpoint_is_semantic(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and endpoint_has_explicit_side_anchor(value)


def free_endpoint_allowed(plan: dict[str, Any], edge: dict[str, Any]) -> bool:
    text = object_text(
        {
            "plan": plan,
            "edge_role": edge.get("edge_role"),
            "semantic_role": edge.get("semantic_role"),
            "route_shape": plan.get("route_shape"),
        }
    ).lower()
    if any(token in text for token in {"freeform", "free point", "floating", "decorative", "callout", "annotation"}):
        return True
    return any(
        bool(source.get(key))
        for source in (plan, edge)
        for key in (
            "freeform_endpoint",
            "allow_free_endpoint",
            "free_point",
            "source_is_free_point",
            "target_is_free_point",
            "allow_raw_endpoint",
        )
    )


def side_for_endpoint(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    if ":" not in value:
        return ""
    return value.split(":", 1)[1].split("@", 1)[0].lower()


def direction_matches(edge: dict[str, Any], direction: str) -> bool:
    direction = direction.strip().lower()
    if direction in {"", "unknown", "none", "bidirectional"}:
        return True
    from_side = side_for_endpoint(edge.get("from"))
    to_side = side_for_endpoint(edge.get("to"))
    if direction == "left_to_right":
        return from_side == "right" and to_side == "left"
    if direction == "right_to_left":
        return from_side == "left" and to_side == "right"
    if direction == "top_to_bottom":
        return from_side == "bottom" and to_side == "top"
    if direction == "bottom_to_top":
        return from_side == "top" and to_side == "bottom"
    return True


def endpoint_node_ids(edge: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("from", "to"):
        value = edge.get(key)
        if isinstance(value, str) and value.strip():
            ids.add(base_node_id(value))
    return ids


def visible_obstacle_nodes(scene: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for node in scene.get("nodes", []) or []:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        if is_background_node(node):
            continue
        node_type = str(node.get("type", ""))
        if node_type in {"audit_region", "group_container", "dashed_region", "loss_region"}:
            continue
        if node.get("allow_overlap") is True or node.get("ignore_arrow_crossing") is True:
            continue
        nodes.append(node)
    return nodes


def route_crosses_obstacle(edge: dict[str, Any], points: list[tuple[float, float]], obstacles: list[dict[str, Any]]) -> str | None:
    if edge.get("allow_node_crossing") or edge.get("allow_text_overlap") or edge.get("allow_cross_container"):
        return None
    endpoint_ids = endpoint_node_ids(edge)
    for node in obstacles:
        node_id = str(node.get("id", ""))
        if node_id in endpoint_ids:
            continue
        box = node_box(node)
        for start, end in zip(points, points[1:]):
            if segment_intersects_box_interior(start, end, box, clearance=0.015):
                return node_id
    return None


def raw_endpoint_gap(edge: dict[str, Any], endpoint_name: str, nodes_by_id: dict[str, dict[str, Any]]) -> float | None:
    point = edge_point(edge, endpoint_name)
    value = edge.get(endpoint_name)
    if point is None or not isinstance(value, str):
        return None
    node = nodes_by_id.get(node_id_from_endpoint(value))
    if node is None:
        return None
    x, y = point
    left, top, right, bottom = node_box(node)
    side = side_for_endpoint(value)
    if side == "left":
        return abs(x - left)
    if side == "right":
        return abs(x - right)
    if side == "top":
        return abs(y - top)
    if side == "bottom":
        return abs(y - bottom)
    return min(abs(x - left), abs(x - right), abs(y - top), abs(y - bottom))


def build_maps(scene: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    nodes_by_id = {str(node.get("id")): node for node in scene.get("nodes", []) or [] if isinstance(node, dict) and node.get("id")}
    edges_by_plan: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in scene.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        plan_id = edge_arrow_plan_id(edge)
        if plan_id:
            edges_by_plan[plan_id].append(edge)
    for node in scene.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        motif_edges = node.get("motif_edges")
        if not isinstance(motif_edges, list):
            continue
        for motif_edge in motif_edges:
            if not isinstance(motif_edge, dict):
                continue
            plan_id = edge_arrow_plan_id(motif_edge)
            if plan_id:
                edges_by_plan[plan_id].append(motif_edge)
    return nodes_by_id, edges_by_plan


def audit_scene(scene: dict[str, Any], strict: bool = False) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    exact_mode = exact_mode_from_metadata(metadata)
    enforce = strict and (exact_mode or metadata.get("arrow_audit_required") is True)
    component_map = load_component_map()
    profile_name, profile = resolve_profile(scene, load_style_profiles(), None)
    del profile_name
    nodes_by_id, edges_by_plan = build_maps(scene)
    obstacles = visible_obstacle_nodes(scene)
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    plans = arrow_plan_items(metadata)

    def issue(message: str, hard: bool = True) -> None:
        if enforce and hard:
            errors.append(message)
        else:
            warnings.append(message)

    if enforce and not plans and any(isinstance(edge, dict) and not is_internal_edge(edge) for edge in scene.get("edges", []) or []):
        errors.append("Strict arrow audit requires metadata.arrow_plan before rendering source-visible edges.")

    for plan in plans:
        plan_id = str(plan.get("id", "")).strip()
        if not plan_id:
            issue("metadata.arrow_plan item without id cannot be audited.")
            continue
        template = infer_template(plan)
        expected_policy = normalized_arrowhead_policy(plan)
        bindings = edges_by_plan.get(plan_id, [])
        if active_plan(plan) and not bindings:
            issue(f"{plan_id}: active arrow_plan has no bound edge/motif_edge.")
        if not template and active_plan(plan):
            issue(f"{plan_id}: cannot infer arrow template; declare arrow_template or route_shape.")

        if not bindings:
            rows.append(
                {
                    "id": plan_id,
                    "region": plan.get("source_region", plan.get("region", "")),
                    "region_regression_group": plan.get("region_regression_group", plan.get("region", "")),
                    "from": endpoint_label(plan, "from"),
                    "to": endpoint_label(plan, "to"),
                    "color": "",
                    "dash": object_text(plan.get("line_style")),
                    "arrow_start": "",
                    "arrow_end": expected_policy,
                    "route_type": str(plan.get("route_shape", "")),
                    "curve_type": str(plan.get("curve_type", "")),
                    "expected_shape": template,
                    "source_bbox": plan.get("source_bbox_px", ""),
                    "confidence": plan.get("certainty", plan.get("confidence", "")),
                    "edge_id": "",
                    "edge_type": "",
                    "notes": plan.get("notes", ""),
                }
            )
            continue

        for edge in bindings:
            edge_id = str(edge.get("id", "<motif-edge>"))
            edge_type = str(edge.get("type", "motif_edge"))
            if is_internal_edge(edge):
                continue
            try:
                if edge_type != "motif_edge" and edge_type in component_map.get("edge_types", {}):
                    style = edge_style(edge, component_map, profile)
                    points = edge_route_points(edge, style, nodes_by_id)
                else:
                    style = edge.get("style", {}) if isinstance(edge.get("style"), dict) else {}
                    points = []
            except Exception as exc:
                issue(f"{plan_id}/{edge_id}: route/style could not be resolved: {exc}")
                style = {}
                points = []

            actual_policy = actual_arrowhead_policy(style)
            actual_curve = curve_type(edge, style)
            actual_route = route_type(edge, style)
            actual_dash = line_dash(style)
            row = {
                "id": plan_id,
                "region": plan.get("source_region", plan.get("region", edge.get("region", ""))),
                "region_regression_group": plan.get(
                    "region_regression_group",
                    edge.get("region_regression_group", plan.get("source_region", plan.get("region", ""))),
                ),
                "from": str(edge.get("from", edge.get("from_point", endpoint_label(plan, "from")))),
                "to": str(edge.get("to", edge.get("to_point", endpoint_label(plan, "to")))),
                "color": style.get("line", ""),
                "dash": actual_dash,
                "arrow_start": arrow_value(style.get("begin_arrow")),
                "arrow_end": arrow_value(style.get("end_arrow")),
                "route_type": actual_route,
                "curve_type": actual_curve,
                "expected_shape": template,
                "source_bbox": plan.get("source_bbox_px", ""),
                "confidence": plan.get("certainty", plan.get("confidence", "")),
                "edge_id": edge_id,
                "edge_type": edge_type,
                "notes": plan.get("notes", edge.get("notes", "")),
            }
            rows.append(row)

            if template in NO_ARROW_TEMPLATES and actual_policy != "none":
                issue(f"{plan_id}/{edge_id}: template `{template}` must be arrowless but edge has `{actual_policy}` arrowheads.")
            if template in END_ARROW_TEMPLATES and expected_policy != "none" and actual_policy != "end_only":
                issue(f"{plan_id}/{edge_id}: template `{template}` should have only an end arrowhead, got `{actual_policy}`.")
            if not arrow_policy_matches(expected_policy, actual_policy):
                issue(f"{plan_id}/{edge_id}: arrowhead policy `{expected_policy}` does not match rendered policy `{actual_policy}`.")

            line_style_text = object_text(plan.get("line_style")).lower()
            if "dash" in line_style_text and actual_dash in {"", "none", "solid"}:
                issue(f"{plan_id}/{edge_id}: source line_style is dashed but edge renders `{actual_dash or 'solid'}`.")
            if actual_dash not in {"", "none", "solid"} and expected_policy == "none" and actual_policy != "none":
                issue(f"{plan_id}/{edge_id}: dashed no-arrow source line rendered with arrowhead `{actual_policy}`.")

            if template == "straight_flow" and points:
                axes = route_axes(points)
                if "diagonal" in axes or "vertical" in axes:
                    issue(f"{plan_id}/{edge_id}: straight_flow should stay horizontal, got axes {sorted(axes)}.")
            if template == "vertical_flow" and points:
                axes = route_axes(points)
                if "diagonal" in axes or "horizontal" in axes:
                    issue(f"{plan_id}/{edge_id}: vertical_flow should stay vertical, got axes {sorted(axes)}.")
            if template in {"orthogonal_flow", "orthogonal_bus_no_arrow", "rounded_orthogonal_flow"} and points:
                axes = route_axes(points)
                if "diagonal" in axes and not edge.get("allow_diagonal"):
                    issue(f"{plan_id}/{edge_id}: `{template}` should be axis-aligned, got diagonal segment(s).")

            if template in CURVE_TEMPLATES:
                source_text = object_text({"plan": plan, "edge": edge}).lower()
                smooth_allowed = bool(plan.get("allow_smooth_curve") or edge.get("allow_smooth_curve")) or any(
                    token in source_text for token in SMOOTH_ALLOWED_TOKENS
                )
                if template in {"bezier_arc", "skip_arc_no_arrow"} and actual_curve in {"smooth", "spline", "catmull_rom"} and not smooth_allowed:
                    issue(
                        f"{plan_id}/{edge_id}: `{template}` should use deterministic bezier/arc control, not `{actual_curve}`. "
                        "Use allow_smooth_curve only for source-visible waves, decorative curves, or hand-drawn/freeform lines."
                    )

            if active_plan(plan) and not free_endpoint_allowed(plan, edge):
                if not endpoint_is_semantic(edge.get("from")) or not endpoint_is_semantic(edge.get("to")):
                    issue(
                        f"{plan_id}/{edge_id}: strict source-visible arrow/line should use semantic side-ratio endpoints like node:right@0.50; "
                        "raw points are allowed only when the source arrow is visibly free-floating."
                    )
                direction = str(plan.get("direction", "")).strip().lower()
                if expected_policy != "none" and direction and not direction_matches(edge, direction):
                    issue(f"{plan_id}/{edge_id}: endpoint sides do not match declared direction `{direction}`.")

            if points:
                length = line_length(points)
                min_length = float(metadata.get("strict_arrow_min_length_in", 0.06) or 0.06)
                if length < min_length and not edge.get("allow_short_arrow") and not plan.get("allow_short_arrow"):
                    issue(f"{plan_id}/{edge_id}: route length {length:.3f}in looks like a dangling/half arrow fragment.")
                if active_plan(plan):
                    crossed = route_crosses_obstacle(edge, points, obstacles)
                    if crossed and plan.get("must_not_cross") not in (None, [], ""):
                        issue(f"{plan_id}/{edge_id}: route crosses non-endpoint node `{crossed}` despite must_not_cross.")
                    elif crossed:
                        issue(f"{plan_id}/{edge_id}: route crosses non-endpoint node `{crossed}`; mark allow_node_crossing only if source shows it.", hard=False)

            for endpoint_name in ("from", "to"):
                gap = raw_endpoint_gap(edge, endpoint_name, nodes_by_id)
                if gap is not None and gap > float(metadata.get("strict_arrow_endpoint_gap_in", 0.04) or 0.04):
                    issue(f"{plan_id}/{edge_id}: raw {endpoint_name}_point is {gap:.3f}in away from declared `{endpoint_name}` boundary.")

    return rows, warnings, errors


def write_audit(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(row.get(key), ensure_ascii=False) if isinstance(row.get(key), (list, dict)) else row.get(key, "") for key in AUDIT_FIELDS})
        return
    path.write_text(json.dumps({"arrow_audit": rows}, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit strict-replica arrow plans against rendered edge contracts.")
    parser.add_argument("scene", type=Path)
    parser.add_argument("--strict", action="store_true", help="Fail strict/exact scenes on arrow contract violations.")
    parser.add_argument("--write-audit", type=Path, help="Write derived arrow_audit.json or arrow_audit.csv.")
    args = parser.parse_args()

    scene = normalize_scene_coordinates(load_json(args.scene))
    rows, warnings, errors = audit_scene(scene, strict=args.strict)
    if args.write_audit:
        write_audit(args.write_audit, rows)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        print("ARROW AUDIT FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"ARROW AUDIT PASSED ({len(rows)} planned arrow binding(s) checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
