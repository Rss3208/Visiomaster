#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


STRICT_FIDELITY_MODES = {"exact", "strict", "replica", "reconstruction", "1:1"}
STRICT_REVIEW_MODES = {"strict_replica", "strict", "exact_replica", "strict_exact"}
REGION_FIRST_STRATEGIES = {"region_first", "tiled_subscenes", "module_first", "section_first"}
TEXT_NODE_TYPES = {"text_block", "annotation_block", "caption_block", "title_block", "label"}
MATH_NODE_TYPES = {"math_text", "formula_text_block", "math_label_box", "math_vector", "math_formula_group"}
RIBBON_ARROW_TYPES = {"ribbon_arrow", "curved_ribbon_arrow", "loop_ribbon_arrow", "qualitative_change_arrow"}
FORMULA_LIKE_RE = re.compile(
    r"(\b[A-Za-z]\s*_[A-Za-z0-9]+|\b[A-Za-z]\s*\^[A-Za-z0-9]+|=|\u2202|\u03b8|\u03bb|"
    r"\u03c9|\u03a3|\u03b1|\u03b2|\u03b3|\u0394|\u03a9|\u2500{2,}|exp\s*\(|sin\s*\(|cos\s*\()"
)


STYLE_CALIBRATION_REQUIRED_KEYS = {
    "forward_arrow": (
        "body_width_px",
        "head_width_px",
        "head_length_px",
        "fill",
        "outline_weight_px",
        "shadow_offset_px",
    ),
    "feedback_arrow": (
        "stroke_width_px",
        "dash_length_px",
        "dash_gap_px",
        "arrowhead_px",
        "curve_smoothness",
        "z_policy",
    ),
    "formula_box": (
        "typical_bbox_px",
        "corner_radius_px",
        "padding_px",
        "fraction_bar_weight_px",
        "math_font_role",
        "line_spacing_policy",
    ),
    "text_scale": (
        "body_label_pt",
        "output_label_pt",
        "branch_caption_pt",
        "rotated_label_pt",
        "formula_pt",
        "legend_pt",
    ),
    "paper_3d_block": (
        "front_fill",
        "side_fill",
        "top_fill",
        "hatch_density",
        "shadow_offset_px",
        "outline_weight_px",
    ),
    "legend": (
        "frame_weight_px",
        "inner_arrow_scale",
        "formula_sample_scale",
        "text_baseline_policy",
    ),
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def node_text(node: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("text", "label", "title", "caption", "left_text", "operator", "numerator", "denominator", "right_text"):
        value = node.get(key)
        if isinstance(value, str):
            parts.append(value)
    formula = node.get("fraction")
    if isinstance(formula, dict):
        for key in ("numerator", "denominator"):
            value = formula.get(key)
            if isinstance(value, str):
                parts.append(value)
    return " ".join(parts)


def object_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(object_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(object_text(item) for item in value)
    return ""


def exact_mode(metadata: dict[str, Any]) -> bool:
    fidelity = str(metadata.get("fidelity", metadata.get("reconstruction_mode", ""))).strip().lower()
    review_mode = str(metadata.get("replica_review_mode", metadata.get("review_mode", ""))).strip().lower()
    return fidelity in STRICT_FIDELITY_MODES or review_mode in STRICT_REVIEW_MODES


def node_is_visible(node: dict[str, Any]) -> bool:
    if node.get("hidden") is True or node.get("visible") is False:
        return False
    node_type = str(node.get("type", ""))
    if node_type in {"audit_region"}:
        return False
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    if str(style.get("visibility", "")).lower() == "hidden":
        return False
    return True


def region_plan(metadata: dict[str, Any]) -> list[Any]:
    for key in ("region_plan", "source_region_plan", "source_regions"):
        value = metadata.get(key)
        if isinstance(value, list):
            return value
    return []


def scene_is_dense(scene: dict[str, Any]) -> tuple[bool, list[str]]:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    nodes = [node for node in as_list(scene.get("nodes")) if isinstance(node, dict)]
    edges = [edge for edge in as_list(scene.get("edges")) if isinstance(edge, dict)]
    visible_nodes = [node for node in nodes if node_is_visible(node)]
    region_strategy = str(metadata.get("region_strategy", metadata.get("large_figure_strategy", ""))).strip().lower()
    regions = region_plan(metadata)
    arrow_like_nodes = [
        node
        for node in nodes
        if str(node.get("type", "")) in RIBBON_ARROW_TYPES
        or "arrow" in " ".join(str(node.get(key, "")) for key in ("id", "type", "semantic_role")).lower()
    ]
    arrow_like_edges = [
        edge
        for edge in edges
        if "arrow" in " ".join(str(edge.get(key, "")) for key in ("id", "type", "semantic_role", "edge_role")).lower()
        or str(edge.get("semantic_intent", "")).lower() in {"feedback", "loss_backprop", "data_flow", "control_flow"}
    ]
    formula_like_nodes = [
        node
        for node in nodes
        if str(node.get("type", "")) in MATH_NODE_TYPES or FORMULA_LIKE_RE.search(node_text(node) or "")
    ]
    aspect = metadata.get("source_aspect_ratio")
    wide = isinstance(aspect, (int, float)) and float(aspect) >= 2.2

    reasons: list[str] = []
    if region_strategy in REGION_FIRST_STRATEGIES:
        reasons.append(f"region_strategy={region_strategy}")
    if len(visible_nodes) >= 30:
        reasons.append(f"{len(visible_nodes)} visible nodes")
    if len(edges) >= 35:
        reasons.append(f"{len(edges)} edges")
    if len(arrow_like_nodes) + len(arrow_like_edges) >= 8:
        reasons.append(f"{len(arrow_like_nodes) + len(arrow_like_edges)} arrow-like objects")
    if len(formula_like_nodes) >= 5:
        reasons.append(f"{len(formula_like_nodes)} formula-like nodes")
    if wide and len(visible_nodes) >= 20:
        reasons.append("wide paper layout")
    if len(regions) >= 5 and len(visible_nodes) >= 20:
        reasons.append(f"{len(regions)} source regions")
    return bool(reasons), reasons


def contains_legend(scene: dict[str, Any]) -> bool:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    corpus = object_text(metadata.get("region_plan", "")) + " "
    for node in as_list(scene.get("nodes")):
        if isinstance(node, dict):
            corpus += " ".join(str(node.get(key, "")) for key in ("id", "type", "semantic_role", "container_id")) + " "
            corpus += node_text(node) + " "
    return "legend" in corpus.lower()


def contains_paper_3d(scene: dict[str, Any]) -> bool:
    tokens = ("3d", "cuboid", "cube", "slab", "stack", "tensor", "paper_3d", "feature_map", "feature_stack")
    for node in as_list(scene.get("nodes")):
        if not isinstance(node, dict):
            continue
        corpus = " ".join(str(node.get(key, "")) for key in ("id", "type", "semantic_role", "primitive_family"))
        if any(token in corpus.lower() for token in tokens):
            return True
    return False


def contains_formula(scene: dict[str, Any]) -> bool:
    for node in as_list(scene.get("nodes")):
        if not isinstance(node, dict):
            continue
        if str(node.get("type", "")) in MATH_NODE_TYPES:
            return True
        if FORMULA_LIKE_RE.search(node_text(node) or ""):
            return True
    return False


def contains_text(scene: dict[str, Any]) -> bool:
    for node in as_list(scene.get("nodes")):
        if isinstance(node, dict) and (node_text(node).strip() or str(node.get("type", "")) in TEXT_NODE_TYPES | MATH_NODE_TYPES):
            return True
    return False


def arrow_style_kind(node_or_edge: dict[str, Any]) -> str | None:
    corpus = " ".join(
        str(node_or_edge.get(key, ""))
        for key in ("id", "type", "semantic_role", "edge_role", "semantic_intent", "arrow_plan_id", "label")
    ).lower()
    style = node_or_edge.get("style") if isinstance(node_or_edge.get("style"), dict) else {}
    dash = str(style.get("line_dash", node_or_edge.get("line_dash", ""))).lower()
    if any(token in corpus for token in ("feedback", "backprop", "gradient", "loss", "dashed", "dash")) or dash not in {"", "solid", "none"}:
        return "feedback_arrow"
    if str(node_or_edge.get("type", "")) in RIBBON_ARROW_TYPES or "arrow" in corpus:
        return "forward_arrow"
    return None


def required_calibration_groups(scene: dict[str, Any]) -> set[str]:
    groups: set[str] = set()
    if contains_text(scene):
        groups.add("text_scale")
    if contains_formula(scene):
        groups.add("formula_box")
    if contains_paper_3d(scene):
        groups.add("paper_3d_block")
    if contains_legend(scene):
        groups.add("legend")
    for node in as_list(scene.get("nodes")):
        if isinstance(node, dict):
            kind = arrow_style_kind(node)
            if kind:
                groups.add(kind)
    for edge in as_list(scene.get("edges")):
        if isinstance(edge, dict):
            kind = arrow_style_kind(edge)
            if kind:
                groups.add(kind)
    return groups


def has_style_reference(item: dict[str, Any]) -> bool:
    for key in ("style_token", "style_calibration_role", "calibration_role", "style_role", "style_preset"):
        if item.get(key):
            return True
    style = item.get("style") if isinstance(item.get("style"), dict) else {}
    return any(style.get(key) for key in ("style_token", "style_calibration_role", "calibration_role", "style_role", "style_preset"))


def has_forward_arrow_contract(node: dict[str, Any]) -> bool:
    if has_style_reference(node):
        return True
    keys = {"body_width_px", "head_width_px", "head_length_px", "body_width_in", "head_width_in", "head_length_in"}
    return len([key for key in keys if key in node]) >= 3


def has_feedback_arrow_contract(node: dict[str, Any]) -> bool:
    if has_style_reference(node):
        return True
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    has_width = any(key in node for key in ("stroke_width_px", "body_width_px", "body_width_in")) or "line_weight_pt" in style
    has_dash = all(key in node for key in ("dash_length_px", "dash_gap_px")) or all(key in style for key in ("dash_length_px", "dash_gap_px"))
    has_head = any(key in node for key in ("arrowhead_px", "head_width_px", "head_length_px")) or "arrowhead_px" in style
    return has_width and has_dash and has_head


def is_formula_like_plain_text(node: dict[str, Any]) -> bool:
    node_type = str(node.get("type", ""))
    if node_type in MATH_NODE_TYPES or node_type not in TEXT_NODE_TYPES:
        return False
    text = node_text(node)
    if not text:
        return False
    return bool(FORMULA_LIKE_RE.search(text))


def rotated_text_unverified(node: dict[str, Any]) -> bool:
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    angle = node.get("text_angle_deg", style.get("text_angle_deg", node.get("angle_deg", style.get("angle_deg"))))
    if not isinstance(angle, (int, float)) or abs(float(angle)) < 0.1:
        return False
    if "source_angle_deg" in node or "source_angle_deg" in style:
        return False
    if node.get("angle_sign_verified") is True or style.get("angle_sign_verified") is True:
        return False
    return True


def no_wrap_missing(node: dict[str, Any]) -> bool:
    facts = object_text(node.get("source_visual_facts")) + " " + object_text(node.get("visual_facts"))
    facts += " " + object_text(node.get("must_match_facts"))
    lower = facts.lower()
    if not any(token in lower for token in ("single-line", "single line", "one-line", "no-wrap", "nowrap", "must_not_wrap")):
        return False
    if node.get("no_wrap") is True:
        return False
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    return style.get("no_wrap") is not True


def validate_style_calibration(scene: dict[str, Any], strict: bool) -> tuple[list[str], list[str], list[str]]:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    failures: list[str] = []
    warnings: list[str] = []
    info: list[str] = []

    if not exact_mode(metadata):
        info.append("scene is not strict/exact replica mode")
        return failures, warnings, info
    dense, dense_reasons = scene_is_dense(scene)
    if not dense:
        info.append("strict scene is not dense enough to require style_calibration")
        return failures, warnings, info
    info.append("strict dense scene: " + ", ".join(dense_reasons))

    calibration = metadata.get("style_calibration")
    if not isinstance(calibration, dict):
        failures.append("Strict dense replica requires metadata.style_calibration before detailed authoring.")
        calibration = {}

    required_groups = required_calibration_groups(scene)
    for group in sorted(required_groups):
        value = calibration.get(group)
        if not isinstance(value, dict):
            failures.append(f"metadata.style_calibration.{group} is required for this scene.")
            continue
        missing = [key for key in STYLE_CALIBRATION_REQUIRED_KEYS[group] if key not in value]
        if missing:
            failures.append(f"metadata.style_calibration.{group} is missing keys: {', '.join(missing)}.")

    for node in as_list(scene.get("nodes")):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "<node>"))
        node_type = str(node.get("type", ""))
        kind = arrow_style_kind(node)
        if node_type in RIBBON_ARROW_TYPES:
            if kind == "feedback_arrow" and not has_feedback_arrow_contract(node):
                failures.append(
                    f"{node_id} is a feedback/dashed ribbon arrow without a style token or explicit width/dash/arrowhead contract."
                )
            elif kind == "forward_arrow" and not has_forward_arrow_contract(node):
                failures.append(
                    f"{node_id} is a ribbon arrow without a style token or explicit body/head geometry contract."
                )
        if is_formula_like_plain_text(node):
            failures.append(
                f"{node_id} contains formula-like text in a plain text node; use math_text, formula_text_block, math_label_box, or math_formula_group."
            )
        if rotated_text_unverified(node):
            failures.append(
                f"{node_id} is rotated text without source_angle_deg or angle_sign_verified; strict replicas must verify angle direction."
            )
        if no_wrap_missing(node):
            failures.append(f"{node_id} records a source single-line/no-wrap fact but does not set no_wrap: true.")

    if strict and warnings:
        failures.extend(warnings)
        warnings = []
    return failures, warnings, info


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate strict dense scene style calibration contracts.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures where applicable.")
    parser.add_argument("--output-report", help="Optional JSON report path.")
    args = parser.parse_args()

    scene_path = Path(args.scene).resolve()
    scene = load_json(scene_path)
    failures, warnings, info = validate_style_calibration(scene, strict=args.strict)
    report = {
        "scene_path": str(scene_path),
        "status": "fail" if failures else "pass",
        "failures": failures,
        "warnings": warnings,
        "info": info,
    }
    if args.output_report:
        output = Path(args.output_report).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if failures:
        print("STYLE CALIBRATION GATE FAILED")
        for item in info:
            print(f"- {item}")
        for failure in failures:
            print(f"- {failure}")
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"- {warning}")
        return 1
    print("STYLE CALIBRATION GATE PASSED")
    for item in info:
        print(f"- {item}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
