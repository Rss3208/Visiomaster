#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scene_to_visio import (
    edge_point,
    edge_route_points,
    edge_style,
    load_component_map,
    load_style_profiles,
    node_center_point,
    node_id_from_endpoint,
    normalize_scene_coordinates,
    resolve_edge_endpoint,
)
from scene_validate import (
    base_node_id,
    bbox_signature,
    edge_arrow_plan_id,
    endpoint_side,
    node_box,
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def as_number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def tolerance_for(plan: dict[str, Any], contract: dict[str, Any], page: dict[str, Any]) -> float:
    if isinstance(contract.get("tolerance_in"), (int, float)):
        return max(0.0, float(contract["tolerance_in"]))
    if isinstance(contract.get("tolerance_px"), (int, float)):
        metadata = contract.get("_scene_metadata") if isinstance(contract.get("_scene_metadata"), dict) else {}
        scale_x = metadata.get("scale_x_in_per_px")
        scale_y = metadata.get("scale_y_in_per_px")
        if isinstance(scale_x, (int, float)) and isinstance(scale_y, (int, float)):
            return max(0.0, float(contract["tolerance_px"]) * max(float(scale_x), float(scale_y)))
        units = str(page.get("units", "")).lower()
        if units in {"px", "pixel", "pixels"}:
            return max(0.0, float(contract["tolerance_px"]))
        target_w = as_number(page.get("target_width_in"), as_number(page.get("width"), 1.0))
        source_w = as_number(page.get("source_width_px"), as_number(page.get("width"), 1.0))
        if source_w > 0:
            return max(0.0, float(contract["tolerance_px"]) * target_w / source_w)
    if isinstance(plan.get("source_bbox_px"), list) and bbox_signature(plan.get("source_bbox_px")):
        return 3.0 if str(page.get("units", "")).lower() in {"px", "pixel", "pixels"} else 0.035
    return 0.035


def contract_with_metadata(contract: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    if "scale_x_in_per_px" not in metadata and "scale_y_in_per_px" not in metadata:
        return contract
    merged = dict(contract)
    merged["_scene_metadata"] = metadata
    return merged


def point_to_boundary_distance(point: tuple[float, float], box: tuple[float, float, float, float], side: str | None) -> float:
    x, y = point
    left, top, right, bottom = box
    if side == "left":
        return abs(x - left) if top <= y <= bottom else min(abs(x - left), abs(y - top), abs(y - bottom))
    if side == "right":
        return abs(x - right) if top <= y <= bottom else min(abs(x - right), abs(y - top), abs(y - bottom))
    if side == "top":
        return abs(y - top) if left <= x <= right else min(abs(y - top), abs(x - left), abs(x - right))
    if side == "bottom":
        return abs(y - bottom) if left <= x <= right else min(abs(y - bottom), abs(x - left), abs(x - right))
    return min(abs(x - left), abs(x - right), abs(y - top), abs(y - bottom))


def edge_maps(scene: dict[str, Any], component_map: dict[str, Any], profile: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    nodes_by_id = {str(node.get("id")): node for node in scene.get("nodes", []) if isinstance(node, dict) and node.get("id")}
    by_id: dict[str, dict[str, Any]] = {}
    by_plan: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in scene.get("edges", []):
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("id", "")).strip()
        if edge_id:
            by_id[edge_id] = edge
        plan_id = edge_arrow_plan_id(edge)
        if plan_id:
            by_plan[plan_id].append(edge)
    for node in scene.get("nodes", []):
        if not isinstance(node, dict):
            continue
        for motif_edge in node.get("motif_edges", []) if isinstance(node.get("motif_edges"), list) else []:
            if not isinstance(motif_edge, dict):
                continue
            plan_id = edge_arrow_plan_id(motif_edge)
            if plan_id:
                by_plan[plan_id].append(motif_edge)
    return by_id, by_plan


def endpoint_node(edge: dict[str, Any], endpoint: str, nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    value = edge.get(endpoint)
    if not isinstance(value, str):
        return None
    return nodes_by_id.get(base_node_id(value))


def contract_node(
    edge: dict[str, Any],
    endpoint: str,
    contract: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    node = endpoint_node(edge, endpoint, nodes_by_id)
    if node is not None:
        return node
    key_options = (
        ("target_node", "target_node_id", "to_node", "to_node_id", "endpoint_must_touch_node")
        if endpoint == "to"
        else ("source_node", "source_node_id", "from_node", "from_node_id", "endpoint_must_touch_source_node")
    )
    for key in key_options:
        value = contract.get(key)
        if isinstance(value, str) and value.strip() in nodes_by_id:
            return nodes_by_id[value.strip()]
    return None


def raw_edge_endpoints(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> tuple[tuple[float, float], tuple[float, float]]:
    from_ref = edge.get("from")
    to_ref = edge.get("to")
    from_point = edge_point(edge, "from")
    to_point = edge_point(edge, "to")
    from_node = nodes_by_id[node_id_from_endpoint(from_ref)] if isinstance(from_ref, str) else None
    to_node = nodes_by_id[node_id_from_endpoint(to_ref)] if isinstance(to_ref, str) else None
    from_peer_point = to_point or (node_center_point(to_node) if to_node else from_point)
    to_peer_point = from_point or (node_center_point(from_node) if from_node else to_point)
    if from_peer_point is None or to_peer_point is None:
        raise ValueError(f"Edge `{edge.get('id', '<unknown>')}` requires resolvable raw endpoints.")
    return (
        resolve_edge_endpoint(edge, "from", from_peer_point, nodes_by_id),
        resolve_edge_endpoint(edge, "to", to_peer_point, nodes_by_id),
    )


def raw_endpoint_checks_enabled(contract: dict[str, Any]) -> bool:
    return str(contract.get("raw_endpoint_check", contract.get("raw_endpoint_checks", "true"))).lower() not in {
        "false",
        "0",
        "no",
        "off",
    }


def check_plan_edge(
    *,
    plan: dict[str, Any],
    edge: dict[str, Any],
    route_points: list[tuple[float, float]],
    raw_start: tuple[float, float],
    raw_end: tuple[float, float],
    nodes_by_id: dict[str, dict[str, Any]],
    page: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    plan_id = str(plan.get("id", "<unknown>"))
    edge_id = str(edge.get("id", "<edge>"))
    contract = plan.get("geometry_contract")
    if not isinstance(contract, dict) or len(route_points) < 2:
        return failures
    start = route_points[0]
    end = route_points[-1]
    tol = tolerance_for(plan, contract, page)

    if contract.get("start_y_equals_end_y") and abs(start[1] - end[1]) > tol:
        failures.append(f"{plan_id}/{edge_id}: start_y_equals_end_y failed ({start[1]:.3f} vs {end[1]:.3f}, tol {tol:.3f}).")
    if contract.get("start_x_equals_end_x") and abs(start[0] - end[0]) > tol:
        failures.append(f"{plan_id}/{edge_id}: start_x_equals_end_x failed ({start[0]:.3f} vs {end[0]:.3f}, tol {tol:.3f}).")
    if raw_endpoint_checks_enabled(contract):
        if contract.get("start_y_equals_end_y") and abs(raw_start[1] - raw_end[1]) > tol:
            failures.append(
                f"{plan_id}/{edge_id}: raw start_y_equals_end_y failed "
                f"({raw_start[1]:.3f} vs {raw_end[1]:.3f}, tol {tol:.3f}); route projection may be hiding endpoint drift."
            )
        if contract.get("start_x_equals_end_x") and abs(raw_start[0] - raw_end[0]) > tol:
            failures.append(
                f"{plan_id}/{edge_id}: raw start_x_equals_end_x failed "
                f"({raw_start[0]:.3f} vs {raw_end[0]:.3f}, tol {tol:.3f}); route projection may be hiding endpoint drift."
            )
    if contract.get("must_be_horizontal") and any(abs(a[1] - b[1]) > tol for a, b in zip(route_points, route_points[1:])):
        failures.append(f"{plan_id}/{edge_id}: must_be_horizontal failed; at least one segment is not horizontal.")
    if contract.get("must_be_vertical") and any(abs(a[0] - b[0]) > tol for a, b in zip(route_points, route_points[1:])):
        failures.append(f"{plan_id}/{edge_id}: must_be_vertical failed; at least one segment is not vertical.")

    target_boundary = str(contract.get("target_boundary", "")).strip().lower()
    source_boundary = str(contract.get("source_boundary", "")).strip().lower()
    if target_boundary:
        target_side = endpoint_side(edge.get("to")) if isinstance(edge.get("to"), str) else None
        if target_side and target_side.lower() != target_boundary:
            failures.append(f"{plan_id}/{edge_id}: target_boundary expected {target_boundary}, edge endpoint uses {target_side}.")
    if source_boundary:
        source_side = endpoint_side(edge.get("from")) if isinstance(edge.get("from"), str) else None
        if source_side and source_side.lower() != source_boundary:
            failures.append(f"{plan_id}/{edge_id}: source_boundary expected {source_boundary}, edge endpoint uses {source_side}.")

    if contract.get("endpoint_must_touch") or contract.get("must_touch_boundary"):
        target = contract_node(edge, "to", contract, nodes_by_id)
        if target_boundary:
            if target is None:
                failures.append(
                    f"{plan_id}/{edge_id}: target_boundary `{target_boundary}` with endpoint_must_touch requires "
                    "`to` to reference a node or geometry_contract.target_node/target_node_id."
                )
            else:
                distance = point_to_boundary_distance(end, node_box(target), target_boundary)
                if distance > tol:
                    failures.append(f"{plan_id}/{edge_id}: endpoint does not touch target {target_boundary} boundary (gap {distance:.3f}, tol {tol:.3f}).")
                if raw_endpoint_checks_enabled(contract):
                    raw_distance = point_to_boundary_distance(raw_end, node_box(target), target_boundary)
                    if raw_distance > tol:
                        failures.append(
                            f"{plan_id}/{edge_id}: raw endpoint does not touch target {target_boundary} boundary "
                            f"(gap {raw_distance:.3f}, tol {tol:.3f}); route projection may be hiding endpoint drift."
                        )
        source = contract_node(edge, "from", contract, nodes_by_id)
        if source_boundary:
            if source is None:
                failures.append(
                    f"{plan_id}/{edge_id}: source_boundary `{source_boundary}` with endpoint_must_touch requires "
                    "`from` to reference a node or geometry_contract.source_node/source_node_id."
                )
            else:
                distance = point_to_boundary_distance(start, node_box(source), source_boundary)
                if distance > tol:
                    failures.append(f"{plan_id}/{edge_id}: startpoint does not touch source {source_boundary} boundary (gap {distance:.3f}, tol {tol:.3f}).")
                if raw_endpoint_checks_enabled(contract):
                    raw_distance = point_to_boundary_distance(raw_start, node_box(source), source_boundary)
                    if raw_distance > tol:
                        failures.append(
                            f"{plan_id}/{edge_id}: raw startpoint does not touch source {source_boundary} boundary "
                            f"(gap {raw_distance:.3f}, tol {tol:.3f}); route projection may be hiding endpoint drift."
                        )
    return failures


def bus_point_for_contract(
    route_points: list[tuple[float, float]],
    raw_start: tuple[float, float],
    raw_end: tuple[float, float],
    contract: dict[str, Any],
) -> tuple[float, float]:
    selector = str(contract.get("shared_bus_point", contract.get("bus_point", ""))).strip().lower()
    if selector in {"raw_from", "from_raw", "source_raw"}:
        return raw_start
    if selector in {"raw_to", "to_raw", "target_raw"}:
        return raw_end
    if selector in {"route_start", "start", "from"}:
        return route_points[0]
    if selector in {"route_end", "end", "to", ""}:
        if not selector:
            index = int(contract.get("shared_bus_point_index", contract.get("bus_point_index", -1)))
            return route_points[index] if route_points and -len(route_points) <= index < len(route_points) else route_points[-1]
        return route_points[-1]
    if selector.startswith("route_index:"):
        try:
            index = int(selector.split(":", 1)[1])
        except ValueError:
            return route_points[-1]
        return route_points[index] if route_points and -len(route_points) <= index < len(route_points) else route_points[-1]
    return route_points[-1]


def check_shared_bus(groups: dict[str, list[tuple[str, list[tuple[float, float]], tuple[float, float], tuple[float, float], dict[str, Any], dict[str, Any]]]], page: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for bus_id, items in groups.items():
        if len(items) < 2:
            continue
        axis = ""
        values: list[float] = []
        labels: list[str] = []
        tolerance = 0.0
        for plan_id, route_points, raw_start, raw_end, plan, contract in items:
            tol = tolerance_for(plan, contract, page)
            tolerance = max(tolerance, tol)
            bus_axis = str(contract.get("shared_bus_axis", contract.get("bus_axis", ""))).lower()
            if not bus_axis:
                bus_axis = "x" if contract.get("shared_bus_x") or contract.get("shared_bus") else "y"
            axis = axis or bus_axis
            if bus_axis != axis:
                failures.append(f"{plan_id}: shared bus `{bus_id}` mixes bus axes `{axis}` and `{bus_axis}`.")
                continue
            point = bus_point_for_contract(route_points, raw_start, raw_end, contract)
            values.append(point[0] if axis == "x" else point[1])
            labels.append(plan_id)
        if values and max(values) - min(values) > tolerance:
            failures.append(
                f"shared_bus `{bus_id}` {axis}-alignment failed for {', '.join(labels)} "
                f"(spread {max(values) - min(values):.3f}, tol {tolerance:.3f})."
            )
    return failures


def run_assertions(scene: dict[str, Any], strict: bool = False) -> tuple[list[str], list[str]]:
    scene = normalize_scene_coordinates(scene)
    component_map = load_component_map()
    profiles = load_style_profiles()
    profile_name = scene.get("metadata", {}).get("style_profile", "paper_white") if isinstance(scene.get("metadata"), dict) else "paper_white"
    profile = profiles.get(str(profile_name), profiles.get("paper_white", {}))
    page = scene.get("page", {}) if isinstance(scene.get("page"), dict) else {}
    nodes_by_id = {str(node.get("id")): node for node in scene.get("nodes", []) if isinstance(node, dict) and node.get("id")}
    _by_id, by_plan = edge_maps(scene, component_map, profile)
    plans = scene.get("metadata", {}).get("arrow_plan", []) if isinstance(scene.get("metadata"), dict) else []
    failures: list[str] = []
    warnings: list[str] = []
    bus_groups: dict[str, list[tuple[str, list[tuple[float, float]], tuple[float, float], tuple[float, float], dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    if not isinstance(plans, list):
        return ["metadata.arrow_plan must be an array for geometry assertions."], warnings
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        contract = plan.get("geometry_contract")
        if not isinstance(contract, dict):
            continue
        contract = contract_with_metadata(contract, scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {})
        plan = dict(plan)
        plan["geometry_contract"] = contract
        plan_id = str(plan.get("id", "")).strip()
        edges = by_plan.get(plan_id, [])
        if not edges:
            message = f"{plan_id}: geometry_contract exists but no edge is bound to this arrow_plan."
            (failures if strict else warnings).append(message)
            continue
        for edge in edges:
            try:
                style = edge_style(edge, component_map, profile)
                route_points = edge_route_points(edge, style, nodes_by_id)
                raw_start, raw_end = raw_edge_endpoints(edge, nodes_by_id)
            except Exception as exc:
                failures.append(f"{plan_id}/{edge.get('id', '<edge>')}: route/raw endpoints could not be resolved: {exc}")
                continue
            failures.extend(
                check_plan_edge(
                    plan=plan,
                    edge=edge,
                    route_points=route_points,
                    raw_start=raw_start,
                    raw_end=raw_end,
                    nodes_by_id=nodes_by_id,
                    page=page,
                )
            )
            bus_id = str(contract.get("shared_bus_id", contract.get("bus_id", ""))).strip()
            if bus_id:
                bus_groups[bus_id].append((plan_id, route_points, raw_start, raw_end, plan, contract))
    failures.extend(check_shared_bus(bus_groups, page))
    return failures, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert route geometry contracts for a visiomaster scene.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--strict", action="store_true", help="Treat missing bound edges for geometry contracts as failures.")
    parser.add_argument("--output-report", help="Optional JSON report path.")
    args = parser.parse_args()
    scene_path = Path(args.scene).resolve()
    failures, warnings = run_assertions(load_json(scene_path), strict=args.strict)
    report = {
        "scene_path": str(scene_path),
        "status": "fail" if failures else "pass",
        "failures": failures,
        "warnings": warnings,
    }
    if args.output_report:
        output_path = Path(args.output_report).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if failures:
        print("GEOMETRY ASSERTIONS FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("GEOMETRY ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
