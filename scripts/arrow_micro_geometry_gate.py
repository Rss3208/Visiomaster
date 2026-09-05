#!/usr/bin/env python3
"""Micro-geometry gate for arrow defects that full-page review tends to miss.

Checks (SKILL.md rule 93):
- R5 endpoint_overshoot: an edge endpoint that penetrates past its target node's
  boundary by more than max(2px, 0.15 x head_length) along the incoming direction.
- R6 head_only_fragment: terminal segment shorter than 1.5 x head_length while the
  edge still declares an end arrowhead (a bare triangle with no line body).
- R7 corner_spur: near-zero-length jog in an otherwise orthogonal route (the
  "extra stub at the bend" defect).
- R8 rounded route without corner_radius_px (warning).

The gate runs on source-pixel scenes (`page.units == "px"`); stylized inch scenes
are skipped with a notice because px tolerances do not apply.

Usage:
    python arrow_micro_geometry_gate.py <scene.json> [--strict] [--output-report report.json]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

NO_ARROW_TYPES = {"line_segment"}
NO_ARROW_POLICIES = {"none", ""}


def segment(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def points_of(edge: dict) -> list[tuple[float, float]] | None:
    raw = edge.get("points")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    pts: list[tuple[float, float]] = []
    for item in raw:
        try:
            pts.append((float(item[0]), float(item[1])))
        except (TypeError, ValueError, IndexError):
            return None
    return pts


def endpoint_of(edge: dict, pts: list[tuple[float, float]] | None) -> tuple[float, float] | None:
    raw = edge.get("to_point")
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            return None
    if pts:
        return pts[-1]
    return None


def has_end_arrow(edge: dict) -> bool:
    if str(edge.get("arrowhead_policy", "")).lower() in NO_ARROW_POLICIES and "arrowhead_policy" in edge:
        return False
    if str(edge.get("arrowhead", "")).lower() in {"none", "no_arrow"}:
        return False
    if str(edge.get("type", "")).lower() in NO_ARROW_TYPES:
        return False
    style = edge.get("style") if isinstance(edge.get("style"), dict) else {}
    if str(style.get("end_arrow", "")).lower() in {"none", ""} and "end_arrow" in style:
        return False
    return True


def bbox_of(node: dict) -> tuple[float, float, float, float] | None:
    try:
        return float(node["x"]), float(node["y"]), float(node["w"]), float(node["h"])
    except (KeyError, TypeError, ValueError):
        return None


def penetration_past_bbox(point: tuple[float, float], prev: tuple[float, float],
                          bbox: tuple[float, float, float, float]) -> float | None:
    """Depth by which segment prev->point crosses into and past the bbox boundary."""
    x, y = point
    px_, py, pw, ph = bbox
    inside = px_ <= x <= px_ + pw and py <= y <= py + ph
    if not inside:
        return None
    distances = sorted([x - px_, px_ + pw - x, y - py, py + ph - y])
    return distances[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit overshoot, head-only fragments, and corner spurs.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    parser.add_argument("--output-report", help="Optional JSON report path.")
    args = parser.parse_args()

    scene_path = Path(args.scene)
    try:
        doc = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ARROW MICRO GEOMETRY GATE ERROR: cannot read {scene_path}: {exc}")
        return 2

    page = doc.get("page") or {}
    if str(page.get("units", "px")) != "px":
        print("ARROW MICRO GEOMETRY GATE SKIPPED (page is not in source-pixel units; px tolerances do not apply)")
        return 0

    metadata = doc.get("metadata") or {}
    calibration = metadata.get("style_calibration") or {}
    forward = calibration.get("forward_arrow") or {}
    head_length = forward.get("head_length_px")
    if not isinstance(head_length, (int, float)) or head_length <= 0:
        head_length = 12.0
    overshoot_tolerance = max(2.0, 0.15 * float(head_length))

    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    bboxes: dict[str, tuple[float, float, float, float]] = {}
    for node in nodes:
        if isinstance(node, dict) and node.get("id"):
            box = bbox_of(node)
            if box:
                bboxes[str(node["id"])] = box

    defects: list[dict] = []

    def add(rule: str, severity: str, edge_id: str, detail: str) -> None:
        defects.append({"rule": rule, "severity": severity, "edge_id": edge_id, "detail": detail})

    edges = doc.get("edges") if isinstance(doc.get("edges"), list) else []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("id", "?"))
        pts = points_of(edge)
        arrow = has_end_arrow(edge)

        if arrow and pts:
            (ax, ay), (bx, by) = pts[-2], pts[-1]
            tail_length = segment(ax, ay, bx, by)
            if tail_length < 1.5 * float(head_length):
                add("R6_head_only_fragment", "fail", edge_id,
                    f"terminal segment {tail_length:.1f}px < 1.5 x head {float(head_length):.1f}px; arrow renders as a bare triangle")

        endpoint = endpoint_of(edge, pts)
        target_id = str(edge.get("to", "")).split("@")[0].strip()
        target_box = bboxes.get(target_id)
        if endpoint and target_box and target_id:
            prev = pts[-2] if pts and len(pts) >= 2 else None
            depth = penetration_past_bbox(endpoint, prev, target_box) if prev else None
            if depth is not None and depth > overshoot_tolerance:
                add("R5_endpoint_overshoot", "fail", edge_id,
                    f"endpoint penetrates {depth:.1f}px past target `{target_id}` boundary (tol {overshoot_tolerance:.1f}px)")

        if pts:
            route = str(edge.get("route", "")).lower()
            lengths = [segment(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(len(pts) - 1)]
            total = sum(lengths)
            for i in range(len(pts) - 2):
                if min(lengths[i], lengths[i + 1]) < max(3.0, 0.03 * total):
                    (x0, y0), (x1, y1), (x2, y2) = pts[i], pts[i + 1], pts[i + 2]
                    v1 = (x1 - x0, y1 - y0)
                    v2 = (x2 - x1, y2 - y1)
                    norm = math.hypot(*v1) * math.hypot(*v2)
                    cos_angle = (v1[0] * v2[0] + v1[1] * v2[1]) / norm if norm else 1.0
                    if cos_angle < 0.9:  # tiny segment with a real direction change = visible kink/spur
                        add("R7_corner_spur", "warn" if not args.strict else "fail", edge_id,
                            f"tiny off-direction jog at points[{i + 1}] (segment {min(lengths[i], lengths[i + 1]):.1f}px, turn {math.degrees(math.acos(max(-1.0, min(1.0, cos_angle)))):.0f}deg)")
                        break
            if "rounded" in route and not edge.get("corner_radius_px"):
                add("R8_rounded_route_missing_radius", "warn", edge_id,
                    "rounded_orthogonal route without explicit corner_radius_px")

    evaluated = [{"rule": d["rule"], "severity": d["severity"]} for d in defects]
    failures = [d for d in defects if d["severity"] == "fail"]
    warnings = [d for d in defects if d["severity"] == "warn"]
    report = {
        "scene": str(scene_path),
        "strict": bool(args.strict),
        "head_length_px": head_length,
        "overshoot_tolerance_px": overshoot_tolerance,
        "status": "fail" if failures else "pass",
        "defects": defects,
        "fail_count": len(failures),
        "warn_count": len(warnings),
        "evaluated": evaluated,
    }
    if args.output_report:
        report_path = Path(args.output_report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if failures:
        print("ARROW MICRO GEOMETRY GATE FAILED")
        for defect in failures:
            print(f"- [{defect['rule']}] {defect['edge_id']}: {defect['detail']}")
        return 1
    print(f"ARROW MICRO GEOMETRY GATE PASSED ({len(warnings)} warnings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
