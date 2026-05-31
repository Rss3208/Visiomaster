#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from font_utils import CJK_FONT_NAMES, font_resolution_for_style, has_cjk_text, installed_font_match, normalize_font_key
from scene_to_visio import (
    approximate_text_height,
    approximate_text_width,
    edge_route_points,
    edge_style,
    load_style_profiles,
    merge_style,
    node_style,
    normalize_scene_coordinates,
    resolve_profile,
)


POINT_TOLERANCE = 0.03
CONTAINER_TOLERANCE = 0.02
ASPECT_RATIO_TOLERANCE = 0.08
CONTAINER_TYPES = {"group_container", "dashed_region", "loss_region", "audit_region"}
CURVED_EDGE_TYPES = {"curved_arrow", "loop_arrow"}
CONTINUOUS_PATH_EDGE_TYPES = {"curved_arrow", "loop_arrow", "dashed_feedback_path"}
RIBBON_ARROW_NODE_TYPES = {"ribbon_arrow", "curved_ribbon_arrow", "loop_ribbon_arrow", "qualitative_change_arrow"}
VISUAL_GRAMMAR_NODE_TYPES = {
    "primitive_group",
    "shape_cluster",
    "symbol_group",
    "cell_strip",
    "micro_grid",
    "polyline_wave",
    "dimension_brace",
    *RIBBON_ARROW_NODE_TYPES,
}
PRIMITIVE_FAMILIES = {
    "cell_strip",
    "polyline_wave",
    "ribbon_arrow",
    "symbol_group",
    "shape_cluster",
    "primitive_group",
    "compact_grid",
    "micro_grid",
    "text_formula",
}
VISUAL_GRAMMAR_INVENTORY_KEYS = (
    "shape_facts",
    "cell_facts",
    "line_facts",
    "symbol_facts",
    "wave_facts",
    "text_facts",
)
EDGE_ROLES = {"data_flow", "context_flow", "feedback_flow", "decorative_internal", "symbol_internal", "icon_internal"}
INTERNAL_EDGE_ROLES = {"decorative_internal", "symbol_internal", "icon_internal"}
LAYER_SEQUENCE_HORIZONTAL_ORIENTATIONS = {"horizontal", "h", "horizontal_bars", "bars", "side_by_side"}
LAYER_SEQUENCE_VERTICAL_ORIENTATIONS = {"vertical", "v", "vertical_stack", "stack", "rows", "row_stack"}
LAYER_SEQUENCE_ORIENTATIONS = LAYER_SEQUENCE_HORIZONTAL_ORIENTATIONS | LAYER_SEQUENCE_VERTICAL_ORIENTATIONS
ATTENTION_SCORE_MOTIF_ENDPOINT_SIDES = {
    "operator_left",
    "operator_right",
    "operator_top",
    "operator_bottom",
    "operator_center",
    "op_left",
    "op_right",
    "op_top",
    "op_bottom",
    "op_center",
    "mul_left",
    "mul_right",
    "mul_top",
    "mul_bottom",
    "mul_center",
    "grid_left",
    "grid_right",
    "grid_top",
    "grid_bottom",
    "grid_center",
}
GAN_TEXT_TOKENS = {"gan", "generator", "discriminator", "generated", "reconstructed tfr"}
LOSS_FORMULA_PATTERN = re.compile(r"\bL_([A-Za-z][A-Za-z0-9]*)\b")
COMPACT_LOSS_FORMULA_PATTERN = re.compile(r"\bL\s*_?\s*(adv|rec)\b", re.IGNORECASE)
GENERIC_SUBSCRIPT_LABEL_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9][A-Za-z0-9_]*\b")
COMBINING_CIRCUMFLEX = "\u0302"
MATHISH_UNICODE_PATTERN = re.compile(r"[α-ωΑ-ΩϑϕφΦλμσΣΔΩπΠψΨτβγ]")
MATHISH_PRIME_PATTERN = re.compile(r"[A-Za-z0-9][′']")
MATHISH_HAT_PATTERN = re.compile(r"[A-Za-z0-9](?:\u0302|ˆ|\^)")
FORMULA_LIKE_PATTERN = re.compile(r"[=\[\]{}]")
OPERATOR_SIZE_TIERS = {"tiny", "small", "medium", "large", "source_small", "source_medium"}
CONCAT_SIZE_TIERS = {"tiny", "small", "medium", "large", "source_small", "source_medium"}
EXACT_FIDELITY_MODES = {"exact", "strict", "replica", "reconstruction", "1:1"}
STRICT_REPLICA_REVIEW_MODES = {"strict_replica", "strict", "exact_replica", "strict_exact"}
STRICT_REGION_CATEGORY_TOKENS = {
    "global": {"global", "whole", "layout"},
    "input": {"input", "left"},
    "core": {"core", "center", "central"},
    "output": {"output", "right"},
    "arrow_dense": {"arrow", "dense", "topology", "junction"},
    "small_text": {"small", "text", "formula", "matrix", "port", "boundary"},
    "caption": {"caption", "fig", "legend"},
}
STRICT_REQUIRED_REGION_CATEGORIES = ("global", "input", "core", "output", "arrow_dense", "small_text")
ARROW_PLAN_INTENTS = {
    "data_flow",
    "control_flow",
    "feedback",
    "loss_backprop",
    "boundary_handoff",
    "frame_output",
    "merge",
    "fan_in",
    "fork",
    "fan_out",
    "loop_update",
    "annotation",
    "callout",
}
ARROW_PLAN_ROUTE_SHAPES = {
    "straight",
    "straight_horizontal",
    "straight_vertical",
    "horizontal",
    "vertical",
    "diagonal",
    "short_diagonal",
    "orthogonal",
    "elbow",
    "right_angle",
    "rounded_orthogonal",
    "hv",
    "vh",
    "curved",
    "smooth_curve",
    "loop",
    "freeform",
}
ARROW_PLAN_DIRECTIONS = {
    "left_to_right",
    "right_to_left",
    "top_to_bottom",
    "bottom_to_top",
    "bidirectional",
    "none",
    "unknown",
}
GEOMETRY_CONTRACT_BOOL_FIELDS = {
    "must_be_horizontal",
    "must_be_vertical",
    "start_y_equals_end_y",
    "start_x_equals_end_x",
    "endpoint_must_touch",
    "must_touch_boundary",
    "must_not_cross_text",
    "must_be_axis_aligned",
}
GEOMETRY_CONTRACT_STRING_FIELDS = {
    "source_boundary",
    "target_boundary",
    "start_anchor",
    "end_anchor",
    "source_anchor",
    "target_anchor",
}
GEOMETRY_CONTRACT_NUMBER_FIELDS = {
    "tolerance_px",
    "tolerance_in",
    "max_endpoint_gap_px",
    "max_endpoint_gap_in",
}


def exact_mode_from_metadata(metadata: Any) -> bool:
    if not isinstance(metadata, dict):
        return False
    fidelity = str(metadata.get("fidelity", metadata.get("reconstruction_mode", ""))).lower()
    review_mode = str(metadata.get("replica_review_mode", metadata.get("review_mode", ""))).lower()
    return fidelity in EXACT_FIDELITY_MODES or review_mode in STRICT_REPLICA_REVIEW_MODES


def recursive_fact_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(recursive_fact_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(recursive_fact_text(item) for item in value)
    return str(value).lower()


def edge_visual_role(edge: dict[str, Any]) -> str:
    return str(edge.get("edge_role", edge.get("semantic_role", ""))).lower()


def is_internal_edge(edge: dict[str, Any]) -> bool:
    return edge_visual_role(edge) in INTERNAL_EDGE_ROLES


def region_label_text(
    region: dict[str, Any],
    *,
    include_required_crop_types: bool = False,
    include_review_focus: bool = True,
) -> str:
    values = [
        region.get("id", ""),
        region.get("name", ""),
        region.get("crop_type", ""),
        region.get("review_crop_type", ""),
    ]
    if include_review_focus:
        values.append(region.get("review_focus", ""))
    if include_required_crop_types and isinstance(region.get("required_crop_types"), list):
        values.extend(str(item) for item in region.get("required_crop_types", []) if isinstance(item, str))
    return " ".join(str(value) for value in values).lower()


def region_categories(region: dict[str, Any], *, include_required_crop_types: bool = False) -> set[str]:
    header_text = region_label_text(
        region,
        include_required_crop_types=include_required_crop_types,
        include_review_focus=False,
    )
    focus_text = region_label_text(
        region,
        include_required_crop_types=False,
        include_review_focus=True,
    )
    categories: set[str] = set()
    for category, tokens in STRICT_REGION_CATEGORY_TOKENS.items():
        haystack = focus_text if category in {"global", "input", "core", "output", "caption"} else header_text
        if any(token in haystack for token in tokens):
            categories.add(category)
    return categories


def bbox_signature(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        left, top, right, bottom = [round(float(item), 3) for item in value]
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def string_list_signature(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        result.append(item.strip())
    return result


def line_length(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(segment_length(start, end) for start, end in zip(points, points[1:]))


def load_component_map() -> dict:
    path = Path(__file__).resolve().parents[1] / "templates" / "visio_components.json"
    return json.loads(path.read_text(encoding="utf-8"))


def base_node_id(endpoint: str) -> str:
    return endpoint.split(":", 1)[0]


def edge_point(edge: dict, endpoint_name: str) -> tuple[float, float] | None:
    value = edge.get(f"{endpoint_name}_point")
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        return None
    if not all(isinstance(item, (int, float)) for item in value):
        return None
    return float(value[0]), float(value[1])


def endpoint_side(endpoint: str) -> str | None:
    if ":" not in endpoint:
        return None
    return endpoint.split(":", 1)[1].split("@", 1)[0]


def endpoint_position(endpoint: str) -> float | None:
    if "@" not in endpoint:
        return None
    raw_value = endpoint.rsplit("@", 1)[1]
    try:
        return float(raw_value)
    except ValueError:
        return None


def endpoint_has_explicit_side_anchor(endpoint: str | None) -> bool:
    if not isinstance(endpoint, str):
        return False
    side = endpoint_side(endpoint)
    return side is not None and side != "center"


def allowed_endpoint_sides_for_node(node_type: str | None) -> set[str]:
    sides = {"left", "right", "top", "bottom", "center"}
    if node_type == "attention_score_motif":
        return sides | ATTENTION_SCORE_MOTIF_ENDPOINT_SIDES
    return sides


def node_box(node: dict) -> tuple[float, float, float, float]:
    x = float(node["x"])
    y = float(node["y"])
    return x, y, x + float(node["w"]), y + float(node["h"])


def node_center(node: dict) -> tuple[float, float]:
    x1, y1, x2, y2 = node_box(node)
    return (x1 + x2) / 2, (y1 + y2) / 2


def box_area(node: dict) -> float:
    return float(node["w"]) * float(node["h"])


def is_background_node(node: dict) -> bool:
    node_id = str(node.get("id", "")).lower()
    if node.get("type") == "page_background" or "background" in node_id:
        return True
    role = str(node.get("role", node.get("semantic_role", ""))).lower()
    if role in {"background", "page_background", "export_background"}:
        return True
    style = node.get("style", {}) if isinstance(node.get("style"), dict) else {}
    text = str(node.get("text", node.get("symbol", ""))).strip()
    return (
        not text
        and bool(node.get("allow_overlap"))
        and str(style.get("line", "")).lower() == "none"
        and str(style.get("fill", "")).lower() in {"#ffffff", "white"}
        and box_area(node) >= 10.0
    )


def is_passive_loop_frame(node: dict) -> bool:
    node_id = str(node.get("id", "")).lower()
    text = str(node.get("text", node.get("symbol", ""))).strip()
    return (
        node.get("type") == "ellipse_node"
        and not text
        and any(token in node_id for token in {"outer", "loop", "cycle"})
    )


def node_semantic_text(node: dict) -> str:
    return " ".join(
        str(node.get(key, ""))
        for key in ("id", "text", "symbol", "title", "subtitle", "input_label", "semantic_role")
    ).lower()


def node_text_for_font(node: dict) -> str:
    parts: list[str] = []
    for key in ("text", "symbol", "title", "subtitle", "input_label"):
        value = node.get(key)
        if value:
            parts.append(str(value))
    runs = node.get("runs")
    if isinstance(runs, list):
        for run in runs:
            if isinstance(run, dict):
                value = run.get("text")
            else:
                value = run
            if value:
                parts.append(str(value))
    formulas = node.get("formulas", node.get("lines"))
    if isinstance(formulas, list):
        parts.extend(str(item) for item in formulas)
    elif formulas:
        parts.append(str(formulas))
    blocks = node.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict):
                value = block.get("text", block.get("label"))
                if value:
                    parts.append(str(value))
    return "\n".join(parts)


RUN_TEXT_NODE_TYPES = {"text_block", "annotation_block", "caption_block"}
MATH_CONTRACT_NODE_TYPES = {"math_text", "formula_text_block", "math_label_box", "math_vector", "math_formula_group"}
TEXT_ROUTE_OVERLAP_NODE_TYPES = RUN_TEXT_NODE_TYPES | {"math_text", "math_label_box", "formula_text_block", "math_formula_group"}
TEXT_FIT_WIDTH_MODES = {"shrink", "shrink_to_fit", "fit", "single_line", "no_wrap", "nowrap", "math_label"}
TEXT_FIT_HEIGHT_MODES = {"shrink", "shrink_to_fit", "fit", "multi_line"}
TEXT_FIT_SINGLE_LINE_MODES = {"single_line", "no_wrap", "nowrap", "math_label"}
STRICT_TEXT_ROLE_TYPES = {
    "annotation",
    "callout",
    "caption",
    "edge_label",
    "formula",
    "header",
    "module_title",
    "output_label",
    "panel_title",
    "small_label",
    "title",
}
TENSOR_PERSPECTIVE_MODES = {
    "flat",
    "front",
    "light",
    "paper_light",
    "medium",
    "paper_medium",
    "strong",
    "heavy",
    "source_thin",
    "source_thick",
}


def node_or_style_has_key(node: dict[str, Any], key: str) -> bool:
    if key in node:
        return True
    style = node.get("style")
    return isinstance(style, dict) and key in style


def truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def text_looks_like_math_content(text: str) -> bool:
    stripped = str(text).strip()
    if not stripped:
        return False
    if LOSS_FORMULA_PATTERN.search(stripped) or GENERIC_SUBSCRIPT_LABEL_PATTERN.search(stripped):
        return True
    if MATHISH_UNICODE_PATTERN.search(stripped):
        return True
    if MATHISH_PRIME_PATTERN.search(stripped):
        return True
    if MATHISH_HAT_PATTERN.search(stripped):
        return True
    if FORMULA_LIKE_PATTERN.search(stripped) and any(char.isalpha() for char in stripped):
        return True
    return any(token in stripped for token in ("⊕", "⊗", "∥", "∑", "∏", "≠", "≤", "≥"))


def node_uses_math_contract(node: dict[str, Any]) -> bool:
    node_type = str(node.get("type", "")).lower()
    if node_type in MATH_CONTRACT_NODE_TYPES:
        return True
    runs = node.get("runs")
    if not isinstance(runs, list):
        return False
    for run in runs:
        if not isinstance(run, dict):
            continue
        render_as = str(run.get("render_as", run.get("renderer", run.get("type", "")))).lower()
        if (
            truthy(run.get("math"), False)
            or truthy(run.get("force_math"), False)
            or render_as in {"math", "math_text", "formula", "formula_text", "inline_math"}
            or str(run.get("font_role", "")).lower() == "math"
            or str(run.get("text_role", "")).lower() in {"formula", "math", "math_label"}
        ):
            return True
    return False


def explicit_text_fit_mode(style: dict[str, Any]) -> str:
    value = style.get("text_fit", style.get("fit_text"))
    if value is None:
        return ""
    return str(value).strip().lower()


def approximate_text_scale_ratio(
    text: str,
    font_size_pt: float,
    box_width: float,
    box_height: float,
    fit_mode: str,
    *,
    angle_deg: float = 0.0,
    margin_in: float = 0.0,
    width_safety: float = 1.10,
    cjk_width_safety: float = 1.18,
) -> float | None:
    if not str(text).strip() or font_size_pt <= 0 or box_width <= 0 or box_height <= 0:
        return None
    rotated = abs((angle_deg % 180) - 90) <= 1e-3
    available_w = max(0.01, box_width - margin_in * 2)
    available_h = max(0.01, box_height - margin_in * 2)
    if rotated:
        available_w, available_h = available_h, available_w

    display_text = str(text)
    if fit_mode in TEXT_FIT_SINGLE_LINE_MODES:
        display_text = display_text.replace("\r", " ").replace("\n", " ")

    scale = 1.0
    effective_width_safety = width_safety
    if any(ord(char) > 255 for char in display_text):
        effective_width_safety = max(effective_width_safety, cjk_width_safety)

    estimated_w, estimated_h = estimate_text_box(display_text, font_size_pt)
    estimated_w *= effective_width_safety
    if fit_mode in TEXT_FIT_WIDTH_MODES and estimated_w > available_w:
        scale = min(scale, available_w / max(estimated_w, 1e-6))
    if fit_mode in TEXT_FIT_HEIGHT_MODES and estimated_h > available_h:
        scale = min(scale, available_h / max(estimated_h, 1e-6))
    elif fit_mode in TEXT_FIT_SINGLE_LINE_MODES:
        single_line_h = font_size_pt / 72.0 * 1.18
        if single_line_h > available_h:
            scale = min(scale, available_h / max(single_line_h, 1e-6))
    return max(0.0, min(1.0, scale))


def validate_text_runs_payload(
    node: dict[str, Any],
    node_id: str,
    label: str,
    errors: list[str],
    warnings: list[str],
    exact_mode: bool = False,
) -> None:
    runs = node.get("runs")
    if runs is None:
        return
    if not isinstance(runs, list):
        errors.append(f"{label} `{node_id}` runs must be an array.")
        return
    if not runs:
        warnings.append(f"{label} `{node_id}` runs is empty.")
        return
    for index, run in enumerate(runs):
        if isinstance(run, (str, int, float)):
            continue
        if not isinstance(run, dict):
            errors.append(f"{label} `{node_id}` runs[{index}] must be an object or plain text.")
            continue
        if run.get("text") is not None and not isinstance(run.get("text"), (str, int, float)):
            errors.append(f"{label} `{node_id}` runs[{index}].text must be text-like.")
        for key in (
            "w",
            "width",
            "h",
            "height",
            "font_size_pt",
            "min_font_size_pt",
            "max_font_size_pt",
            "target_font_size_pt",
            "baseline_offset_in",
            "offset_x_in",
            "x_offset_in",
            "offset_y_in",
            "y_offset_in",
            "subscript_scale",
            "subscript_offset_in",
            "line_gap_in",
            "short_run_width_safety_factor",
            "short_run_min_width_in",
        ):
            value = run.get(key)
            if value is not None and (not isinstance(value, (int, float)) or float(value) < 0):
                errors.append(f"{label} `{node_id}` runs[{index}].{key} must be a non-negative number.")
        for key in ("font_family", "font_role", "source_font_family", "text_fit", "render_as", "font_weight", "text_role", "semantic_role"):
            value = run.get(key)
            if value is not None and not isinstance(value, str):
                errors.append(f"{label} `{node_id}` runs[{index}].{key} must be a string.")
        candidates = run.get("font_family_candidates")
        if candidates is not None and (
            not isinstance(candidates, list)
            or not all(isinstance(item, str) for item in candidates)
        ):
            errors.append(f"{label} `{node_id}` runs[{index}].font_family_candidates must be an array of strings.")
        math_flag = run.get("math")
        if math_flag is not None and not isinstance(math_flag, bool):
            warnings.append(f"{label} `{node_id}` runs[{index}].math should be boolean.")
        for key in ("allow_shrink", "force_single_line"):
            value = run.get(key)
            if value is not None and not isinstance(value, bool):
                warnings.append(f"{label} `{node_id}` runs[{index}].{key} should be boolean.")

    if exact_mode and not node.get("source_bbox_px", node.get("source_bbox")):
        warnings.append(
            f"Exact text node `{node_id}` uses mixed text runs without source_bbox_px/source_bbox; baseline, spacing, and anchor drift are hard to review."
        )


def font_validation_warnings(
    node: dict,
    style: dict[str, Any],
    exact_mode: bool = False,
) -> list[str]:
    node_id = node.get("id", "<missing-id>")
    text = node_text_for_font(node)
    if not text.strip() and node.get("type") not in {"operator_node"}:
        return []

    warnings: list[str] = []
    def append_style_warnings(context_label: str, text_value: str, effective_style: dict[str, Any], source_font_override: Any = None) -> None:
        if not str(text_value).strip():
            return
        resolution = font_resolution_for_style(effective_style, text_value)
        requested = resolution.requested
        if requested and not installed_font_match(requested):
            if resolution.resolved and resolution.resolved != requested:
                warnings.append(
                    f"{context_label} requests font `{requested}`, which is not installed; renderer will use `{resolution.resolved}` via `{resolution.role or 'default'}` fallback."
                )
            else:
                warnings.append(
                    f"{context_label} requests font `{requested}`, which is not installed and has no matching fallback."
                )
        elif requested and resolution.used_fallback and resolution.resolved:
            warnings.append(
                f"{context_label} requested `{requested}` but renderer resolved `{resolution.resolved}`. Check whether this is an intended alias/fallback."
            )

        source_font = source_font_override or effective_style.get("source_font_family")
        if source_font:
            source_match = installed_font_match(source_font)
            if source_match and resolution.resolved and normalize_font_key(source_match) != normalize_font_key(resolution.resolved):
                warnings.append(
                    f"{context_label} records source font `{source_font}`, which is installed as `{source_match}`, but effective render font is `{resolution.resolved}`. Set `font_family`/`font_family_candidates` to use the source font."
                )
            elif not source_match:
                warnings.append(
                    f"{context_label} records source font `{source_font}`, but it is not installed; choose a visually close `font_family_candidates` fallback."
                )

        if has_cjk_text(text_value) and resolution.resolved and resolution.resolved not in CJK_FONT_NAMES:
            warnings.append(
                f"{context_label} contains CJK text but resolves to `{resolution.resolved}`; use `font_role: cjk_sans`/`cjk_serif` or a CJK-capable font to avoid Visio font substitution."
            )

        if exact_mode and str(text_value).strip() and not (
            effective_style.get("font_family") or effective_style.get("font_family_candidates") or effective_style.get("font_role")
        ):
            warnings.append(
                f"{context_label} has text in an exact replica but no explicit font family, candidates, or role after style resolution."
            )

    append_style_warnings(f"Node `{node_id}`", text, style, style.get("source_font_family") or node.get("source_font_family"))

    runs = node.get("runs")
    if isinstance(runs, list):
        for index, run in enumerate(runs):
            if isinstance(run, dict):
                run_text = str(run.get("text", "")).strip()
                if not run_text:
                    continue
                run_style = merge_style(style, run.get("style") if isinstance(run.get("style"), dict) else None)
                for key in ("font_family", "font_family_candidates", "font_role", "font_weight", "font_italic", "font_size_pt", "text_color"):
                    if key in run:
                        run_style[key] = run[key]
                append_style_warnings(
                    f"Node `{node_id}` run[{index}]",
                    run_text,
                    run_style,
                    run.get("source_font_family"),
                )
    return warnings


def text_fit_warnings(node: dict, style: dict[str, Any], exact_mode: bool = False) -> list[str]:
    node_id = node.get("id", "<missing-id>")
    node_type = node.get("type")
    warnings: list[str] = []

    def style_value(key: str, default: Any = None) -> Any:
        node_style = node.get("style", {}) if isinstance(node.get("style"), dict) else {}
        return node.get(key, node_style.get(key, style.get(key, default)))

    def risky_text(text: str, font_size_pt: float, width: float, height: float, angle: float = 0.0) -> bool:
        if not text.strip() or width <= 0 or height <= 0:
            return False
        rotated = abs((angle % 180) - 90) <= 1e-3
        fit_width = height if rotated else width
        fit_height = width if rotated else height
        widest = max(approximate_text_width(line, font_size_pt) for line in text.splitlines() or [text])
        text_h = approximate_text_height(text, font_size_pt)
        return widest > fit_width * 0.92 or text_h > fit_height * 0.92

    text = node_text_for_font(node)
    text_role = str(node.get("text_role", node.get("semantic_role", ""))).lower()
    if exact_mode and node_type in RUN_TEXT_NODE_TYPES and text.strip():
        if (text_looks_like_math_content(text) or text_role in {"formula", "math", "math_label"}) and not node_uses_math_contract(node):
            warnings.append(
                f"Exact text node `{node_id}` contains math-like content but still uses plain `{node_type}` rendering. "
                "Use `math_text`, `formula_text_block`, or run-based math fragments instead of ordinary text-box fallback."
            )
    if text and all(key in node for key in ("w", "h")):
        try:
            font_size = float(style.get("font_size_pt", 12))
            angle = float(style.get("text_angle_deg", 0) or 0)
            if risky_text(text, font_size, float(node["w"]), float(node["h"]), angle):
                fit = style_value("text_fit", style_value("fit_text", "none"))
                if str(fit).lower() in {"", "none", "off", "false"}:
                    warnings.append(
                        f"Node `{node_id}` text is likely to wrap or overflow; set `text_fit: \"shrink_to_fit\"` or use `math_text`/smaller role-specific font."
                    )
            if exact_mode and abs((angle % 180) - 90) <= 1e-3:
                fit = str(style_value("text_fit", "none")).lower()
                if fit not in TEXT_FIT_SINGLE_LINE_MODES:
                    warnings.append(
                        f"Exact rotated text node `{node_id}` should use a single-line text policy. "
                        "Do width budgeting first; do not rely on generic multi-line Visio text inside a narrow vertical strip."
                    )
                if not any(node_or_style_has_key(node, key) for key in ("rotated_text_box_safety_factor", "rotated_text_width_budget_in", "rotated_text_inset_in")):
                    warnings.append(
                        f"Exact rotated text node `{node_id}` has no explicit rotated width-budget contract. "
                        "Add `rotated_text_width_budget_in`, `rotated_text_inset_in`, or an explicit rotated text safety factor before micro-tuning."
                    )
        except Exception:
            pass

    if node_type in {"layer_sequence", "classifier_head"}:
        orientation = str(node.get("orientation", style.get("orientation", "horizontal"))).lower()
        block_angle = float(style_value("block_text_angle_deg", 90 if orientation in LAYER_SEQUENCE_HORIZONTAL_ORIENTATIONS else 0) or 0)
        block_fit = str(style_value("block_text_fit", "none")).lower()
        frame_visible = style_value("frame_visible", True)
        title = str(node.get("title", node.get("text", ""))).strip()
        if frame_visible is False and title:
            warnings.append(
                f"{node_type} `{node_id}` has `frame_visible: false` but also a title/text; the title will still render without an enclosing module frame."
            )
        if block_fit in {"", "none", "off", "false"}:
            warnings.append(f"{node_type} `{node_id}` has no block_text_fit; repeated layer labels may wrap or split.")
        blocks = node.get("blocks", [])
        if isinstance(blocks, list):
            labels = []
            for block in blocks:
                if isinstance(block, dict):
                    labels.append(str(block.get("text", block.get("label", ""))))
                    if all(isinstance(node.get(key), (int, float)) for key in ("w", "h")):
                        block_w = block.get("w", block.get("width"))
                        block_h = block.get("h", block.get("height"))
                        if isinstance(block_w, (int, float)) and float(block_w) > float(node["w"]) * 1.25:
                            warnings.append(
                                f"{node_type} `{node_id}` block `{block.get('text', block.get('label', '<unnamed>'))}` width exceeds the parent width; "
                                "pixel-scene nested block sizes may be unscaled."
                            )
                        if isinstance(block_h, (int, float)) and float(block_h) > float(node["h"]) * 1.25:
                            warnings.append(
                                f"{node_type} `{node_id}` block `{block.get('text', block.get('label', '<unnamed>'))}` height exceeds the parent height; "
                                "pixel-scene nested block sizes may be unscaled."
                            )
                else:
                    labels.append(str(block))
            if any(len(label) >= 7 for label in labels) and abs((block_angle % 180) - 90) <= 1e-3 and block_fit not in {"single_line", "no_wrap", "nowrap", "math_label"}:
                warnings.append(
                    f"{node_type} `{node_id}` has long rotated layer labels; use `block_text_fit: \"single_line\"` with a small block font."
                )
            if abs((block_angle % 180) - 90) <= 1e-3:
                constrain_text = style_value("block_constrain_text_box", None)
                if constrain_text is not True:
                    warnings.append(
                        f"{node_type} `{node_id}` has rotated layer labels without `block_constrain_text_box: true`; Visio may expand/crop the label outside the strip."
                    )
                if exact_mode and not any(
                    node_or_style_has_key(node, key)
                    for key in ("block_font_size_pt", "block_min_font_size_pt", "rotated_text_width_budget_in", "rotated_text_inset_in")
                ):
                    warnings.append(
                        f"{node_type} `{node_id}` has rotated strip labels but no explicit width-budget contract. "
                        "Set narrow-strip text parameters before rendering instead of waiting for broken vertical text."
                    )

    if node_type == "token_grid":
        cell_fit = str(style_value("cell_text_fit", "none")).lower()
        if cell_fit in {"", "none", "off", "false"}:
            warnings.append(f"Token grid `{node_id}` has no cell_text_fit; numbered cells can overlap in dense matrices.")

    if node_type == "math_text":
        fit = str(style_value("text_fit", "none")).lower()
        if fit in {"", "none", "off", "false"}:
            warnings.append(f"Math text `{node_id}` has no text_fit; subscript labels and formulas may wrap in Visio.")

    if node_type == "math_label_box":
        text = node_text_for_font(node)
        if "_" not in text and not any(char in text for char in {"′", "'", "^"}):
            warnings.append(f"Math label box `{node_id}` has no visible subscript/prime marker; use a normal text block unless the source uses math styling.")

    if node_type == "probability_bar_list":
        items = node.get("items", node.get("rows", []))
        if not items and not str(node.get("text", "")).strip():
            warnings.append(f"Probability bar list `{node_id}` has no rows/items; it may render as an empty rounded panel.")
        style_dict = node.get("style", {}) if isinstance(node.get("style"), dict) else {}
        anchor = str(node.get("bar_value_anchor", style_dict.get("bar_value_anchor", style_value("bar_value_anchor", "")))).lower()
        if any(isinstance(item, dict) and item.get("bar_value_label") for item in items or []):
            if anchor not in {"bar_area", "row", "panel", "inner", "after_axis", "plot", "after_bar", "bar_end", "bar_right", "before_bar", "bar_left"}:
                warnings.append(
                    f"Probability bar list `{node_id}` has inline bar value labels without `bar_value_anchor`; "
                    "use `bar_area` or `row` so row text does not collide with the visible bar."
                )
            if anchor in {"bar_area", "plot"} and float(style_dict.get("bar_max_fraction", node.get("bar_max_fraction", 1)) or 1) >= 0.98:
                warnings.append(
                    f"Probability bar list `{node_id}` places row text over the full bar area with full-length bars; set `bar_max_fraction` below 1 or use `bar_value_anchor: \"after_bar\"` when visual review reports text/bar overlap."
                )
            if float(style_dict.get("bar_value_offset_x_in", node.get("bar_value_offset_x_in", 0)) or 0) > 0:
                warnings.append(
                    f"Probability bar list `{node_id}` offsets value labels into the bars; visual review often reports this as text/bar overlap."
                )

    if node_type == "dual_wing_encoder":
        raw_points = node.get("points")
        shape_mode = str(node.get("shape_mode", style.get("shape_mode", "three_part"))).lower()
        if raw_points and shape_mode == "three_part":
            warnings.append(
                f"Dual wing encoder `{node_id}` has custom points but no shape_mode; use `shape_mode: \"custom_polygon\"` or `opposing_trapezoids` so the intended paper shape is explicit."
            )
        if shape_mode in {"opposing_trapezoids", "hourglass", "pinched"} and node.get("center_ratio", style.get("center_ratio")) is None:
            warnings.append(
                f"Dual wing encoder `{node_id}` uses {shape_mode} without center_ratio; set a narrow center strip ratio for source-like encoder modules."
            )

    return warnings


def strict_text_shrink_findings(node: dict[str, Any], style: dict[str, Any], exact_mode: bool, strict_contract: bool = False) -> tuple[list[str], list[str]]:
    if not exact_mode or not all(isinstance(node.get(key), (int, float)) for key in ("w", "h")):
        return [], []

    text = node_text_for_font(node).strip()
    if not text:
        return [], []

    fit_mode = explicit_text_fit_mode(style)
    if fit_mode not in (TEXT_FIT_WIDTH_MODES | TEXT_FIT_HEIGHT_MODES):
        return [], []

    try:
        font_size = float(style.get("font_size_pt", 12) or 12)
        min_font = float(style.get("min_font_size_pt", style.get("text_min_font_size_pt", max(6.0, font_size * 0.55))) or max(6.0, font_size * 0.55))
        angle = float(style.get("text_angle_deg", 0) or 0)
        margin = float(style.get("text_fit_margin_in", style.get("text_margin_in", 0.02)) or 0.0)
        width_safety = float(style.get("text_width_safety_factor", style.get("single_line_width_safety_factor", 1.10)) or 1.0)
        cjk_safety = float(style.get("cjk_text_width_safety_factor", 1.18) or 1.18)
    except (TypeError, ValueError):
        return [], []

    scale_ratio = approximate_text_scale_ratio(
        text,
        font_size,
        float(node["w"]),
        float(node["h"]),
        fit_mode,
        angle_deg=angle,
        margin_in=margin,
        width_safety=width_safety,
        cjk_width_safety=cjk_safety,
    )
    if scale_ratio is None:
        return [], []

    warnings: list[str] = []
    errors: list[str] = []
    text_role = str(node.get("text_role", node.get("semantic_role", ""))).lower()
    tight_threshold = 0.75
    if text_role in STRICT_TEXT_ROLE_TYPES or node.get("type") in (RUN_TEXT_NODE_TYPES | {"math_text", "formula_text_block"}):
        tight_threshold = 0.78
    min_ratio = min(1.0, min_font / max(font_size, 1e-6))
    if fit_mode in TEXT_FIT_SINGLE_LINE_MODES and scale_ratio < 0.60:
        message = (
            f"Exact text node `{node.get('id')}` would need roughly {scale_ratio:.0%} font scaling to stay on one line. "
            "This is below the strict 60% floor; rebuild the text bbox/runs instead of hiding a font mismatch with compression."
        )
        (errors if strict_contract else warnings).append(message)
    if fit_mode in TEXT_FIT_SINGLE_LINE_MODES and scale_ratio < tight_threshold:
        warnings.append(
            f"Exact text node `{node.get('id')}` would need roughly {scale_ratio:.0%} font scaling to stay on one line. "
            "Widen the source-bound bbox, split into runs, or rebuild the local text layout instead of relying on heavy shrink."
        )
    if fit_mode in TEXT_FIT_SINGLE_LINE_MODES and min_ratio < 0.60 and len(text.replace('\n', ' ').strip()) >= 4:
        message = (
            f"Exact text node `{node.get('id')}` allows shrink down to about {min_ratio:.0%} of its requested font size. "
            "Strict replica text must not pass with a minimum font below 60%."
        )
        (errors if strict_contract else warnings).append(message)
    elif fit_mode in TEXT_FIT_SINGLE_LINE_MODES and min_ratio < 0.75 and len(text.replace('\n', ' ').strip()) >= 4:
        warnings.append(
            f"Exact text node `{node.get('id')}` allows shrink down to about {min_ratio:.0%} of its requested font size. "
            "Single-line strict replica text should not pass only by aggressive font compression."
        )
    return warnings, errors


def visual_grammar_node_findings(
    node: dict[str, Any],
    node_id: str,
    node_type: str | None,
    *,
    exact_mode: bool,
    strict_contract: bool,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    def issue(message: str) -> None:
        if strict_contract:
            errors.append(message)
        else:
            warnings.append(message)

    primitive_family = node.get("primitive_family")
    if primitive_family is not None:
        if not isinstance(primitive_family, str):
            errors.append(f"Node `{node_id}` primitive_family must be a string.")
        elif primitive_family not in PRIMITIVE_FAMILIES:
            errors.append(f"Node `{node_id}` primitive_family `{primitive_family}` is unsupported.")

    for key in ("visual_facts", "source_visual_facts"):
        value = node.get(key)
        if value is not None and not isinstance(value, (dict, list)):
            errors.append(f"Node `{node_id}` {key} must be an object or array of source visual facts.")
    for key in ("must_match_facts",):
        value = node.get(key)
        if value is not None and not isinstance(value, list):
            errors.append(f"Node `{node_id}` {key} must be an array.")
    if node.get("motif_binding") is not None and not isinstance(node.get("motif_binding"), str):
        errors.append(f"Node `{node_id}` motif_binding must be a string.")
    if node.get("subshape_role") is not None and not isinstance(node.get("subshape_role"), str):
        errors.append(f"Node `{node_id}` subshape_role must be a string.")
    obligations = node.get("fidelity_obligations")
    if obligations is not None and not isinstance(obligations, list):
        errors.append(f"Node `{node_id}` fidelity_obligations must be an array.")
    if isinstance(obligations, list):
        for index, obligation in enumerate(obligations):
            if not isinstance(obligation, dict):
                errors.append(f"Node `{node_id}` fidelity_obligations[{index}] must be an object.")
                continue
            if not str(obligation.get("object", "")).strip():
                issue(f"Node `{node_id}` fidelity_obligations[{index}] should name the source object.")
            for key in ("must_preserve", "allowed_simplification", "forbidden_simplification"):
                value = obligation.get(key)
                if value is not None and not isinstance(value, list):
                    errors.append(f"Node `{node_id}` fidelity_obligations[{index}].{key} must be an array.")
            if exact_mode and not obligation.get("must_preserve"):
                issue(f"Node `{node_id}` fidelity_obligations[{index}] should list must_preserve details.")

    if node_type not in VISUAL_GRAMMAR_NODE_TYPES:
        return warnings, errors

    if exact_mode:
        if not node.get("source_bbox_px", node.get("source_bbox")):
            issue(
                f"Visual grammar node `{node_id}` (`{node_type}`) has no source_bbox_px/source_bbox; "
                "crop-bound small components are required to judge cell count, wave shape, or symbol geometry."
            )
        if not isinstance(node.get("must_match_facts"), list) or not node.get("must_match_facts"):
            issue(
                f"Visual grammar node `{node_id}` (`{node_type}`) should list must_match_facts so review checks the source facts this primitive is preserving."
            )

    fact_text = recursive_fact_text(
        {
            "visual_facts": node.get("visual_facts"),
            "source_visual_facts": node.get("source_visual_facts"),
            "must_match_facts": node.get("must_match_facts"),
        }
    )

    if node_type in {"cell_strip", "micro_grid"}:
        rows = node.get("rows")
        cols = node.get("cols", node.get("columns"))
        count = node.get("cell_count", node.get("count", node.get("cells_count")))
        if node_type == "micro_grid" or rows is not None:
            if rows is not None and (not isinstance(rows, int) or rows <= 0):
                errors.append(f"{node_type} `{node_id}` rows must be a positive integer.")
            if cols is not None and (not isinstance(cols, int) or cols <= 0):
                errors.append(f"{node_type} `{node_id}` cols/columns must be a positive integer.")
        elif count is None:
            issue(f"cell_strip `{node_id}` must declare cell_count/count/cells_count or explicit rows/cols.")
        elif not isinstance(count, int) or count <= 0:
            errors.append(f"cell_strip `{node_id}` cell_count/count/cells_count must be a positive integer.")
        for key in ("cell_gap_in", "gap_in", "cell_rounding_in", "rounding_in"):
            value = node.get(key)
            if value is not None and (not isinstance(value, (int, float)) or float(value) < 0):
                errors.append(f"{node_type} `{node_id}` {key} must be a non-negative number.")
        if node.get("continuous") is not None and not isinstance(node.get("continuous"), bool):
            warnings.append(f"{node_type} `{node_id}` continuous should be boolean.")
        rounding = node.get("cell_rounding_in", node.get("rounding_in"))
        if rounding is None and isinstance(node.get("style"), dict):
            rounding = node["style"].get("cell_rounding_in", node["style"].get("rounding_in"))
        if "low_rounding" in fact_text or "low rounding" in fact_text or "rectangular" in fact_text:
            try:
                if rounding is not None and float(rounding) > 0.06:
                    issue(
                        f"{node_type} `{node_id}` records low-rounding/rectangular source cells but uses cell_rounding_in={float(rounding):.3f}; "
                        "use low or zero rounding instead of a token-like capsule default."
                    )
            except (TypeError, ValueError):
                errors.append(f"{node_type} `{node_id}` rounding value must be numeric.")
        cells = node.get("cells")
        if cells is not None and not isinstance(cells, list):
            errors.append(f"{node_type} `{node_id}` cells must be an array.")

    if node_type == "polyline_wave":
        points = node.get("points")
        samples = node.get("samples")
        has_points = isinstance(points, list) and len(points) >= 2
        has_samples = isinstance(samples, list) and len(samples) >= 2 and all(isinstance(item, (int, float)) for item in samples)
        if strict_contract and exact_mode and not (has_points or has_samples):
            errors.append(
                f"polyline_wave `{node_id}` is exact/strict but has no explicit points or samples; "
                "do not fall back to a generic sine wave for source-specific waveforms."
            )
        if points is not None:
            if not isinstance(points, list):
                errors.append(f"polyline_wave `{node_id}` points must be an array.")
            else:
                for index, point in enumerate(points):
                    if not isinstance(point, list) or len(point) != 2 or not all(isinstance(value, (int, float)) for value in point):
                        errors.append(f"polyline_wave `{node_id}` points[{index}] must be [x, y] numbers.")
        if samples is not None and not has_samples:
            errors.append(f"polyline_wave `{node_id}` samples must contain at least two numeric values.")

    if node_type in RIBBON_ARROW_NODE_TYPES:
        if node_type in {"curved_ribbon_arrow", "loop_ribbon_arrow"}:
            points = node.get("points")
            if node_type == "curved_ribbon_arrow" and (not isinstance(points, list) or len(points) < 2):
                issue(f"{node_type} `{node_id}` should provide source-sampled points; otherwise it may become a generic smooth band.")
            if node_type == "loop_ribbon_arrow" and not (isinstance(points, list) and len(points) >= 3) and not all(
                key in node for key in ("start_angle_deg", "sweep_angle_deg")
            ):
                issue(f"{node_type} `{node_id}` should provide points or start_angle_deg/sweep_angle_deg to lock the visible loop arc.")
        if node_type in {"ribbon_arrow", "qualitative_change_arrow"}:
            direction = str(node.get("direction", "")).lower()
            if direction and direction not in {"right", "left", "up", "down", "east", "west", "north", "south", "n", "s", "e", "w", "top", "bottom"}:
                errors.append(f"{node_type} `{node_id}` direction `{direction}` is unsupported.")
        for key in ("body_width_in", "body_width_px", "head_width_in", "head_width_px", "head_length_in", "head_length_px"):
            value = node.get(key)
            if value is not None and (not isinstance(value, (int, float)) or float(value) <= 0):
                errors.append(f"{node_type} `{node_id}` {key} must be a positive number.")
        if exact_mode and "ribbon" in fact_text and not any(
            node.get(key) is not None for key in ("body_width_in", "body_width_px", "head_width_in", "head_width_px")
        ):
            issue(f"{node_type} `{node_id}` records a ribbon/thick-arrow source fact but has no explicit body/head width.")

    if node_type in {"primitive_group", "shape_cluster", "symbol_group"}:
        subshapes = node.get("subshapes", node.get("parts", node.get("primitives")))
        symbol_kind = node.get("symbol_kind", node.get("motif"))
        if subshapes is not None and not isinstance(subshapes, list):
            errors.append(f"{node_type} `{node_id}` subshapes/parts/primitives must be an array.")
        if exact_mode and node_type == "symbol_group" and not subshapes and not symbol_kind:
            issue(f"symbol_group `{node_id}` needs subshapes or symbol_kind so the symbol geometry is explicit.")
        if isinstance(subshapes, list):
            for index, subshape in enumerate(subshapes):
                if not isinstance(subshape, dict):
                    errors.append(f"{node_type} `{node_id}` subshapes[{index}] must be an object.")
                    continue
                role = str(subshape.get("subshape_role", subshape.get("role", ""))).lower()
                if exact_mode and role and role not in {"decorative_detail", "decorative_internal", "symbol_internal", "icon_internal", "primitive", "label"}:
                    warnings.append(
                        f"{node_type} `{node_id}` subshapes[{index}] role `{role}` is not a known internal/decorative role."
                    )
                if exact_mode and not role and str(subshape.get("shape", subshape.get("kind", ""))).lower() in {"line", "polyline", "path"}:
                    warnings.append(
                        f"{node_type} `{node_id}` subshape line/path {index} has no subshape_role; mark it symbol_internal/icon_internal so arrow audit does not treat it as a main connector."
                    )

    if node_type == "math_formula_group":
        formula_kind = str(node.get("formula_kind", node.get("kind", ""))).lower()
        if formula_kind and formula_kind not in {"fraction", "ratio", "stacked_fraction", "inline_group", "equation"}:
            errors.append(f"math_formula_group `{node_id}` formula_kind `{formula_kind}` is unsupported.")
        has_fraction = any(node.get(key) for key in ("numerator", "denominator", "fraction"))
        if has_fraction or formula_kind in {"fraction", "ratio", "stacked_fraction"}:
            fraction = node.get("fraction")
            if fraction is not None and not isinstance(fraction, dict):
                errors.append(f"math_formula_group `{node_id}` fraction must be an object.")
            numerator = node.get("numerator")
            denominator = node.get("denominator")
            if isinstance(fraction, dict):
                numerator = numerator or fraction.get("numerator")
                denominator = denominator or fraction.get("denominator")
            if not numerator:
                errors.append(f"math_formula_group `{node_id}` fraction requires numerator.")
            if not denominator:
                errors.append(f"math_formula_group `{node_id}` fraction requires denominator.")
        if node.get("parts") is not None and not isinstance(node.get("parts"), list):
            errors.append(f"math_formula_group `{node_id}` parts must be an array.")
        for key in ("fraction_bar_weight_pt", "baseline_y_ratio", "fraction_width_ratio"):
            value = node.get(key)
            if value is not None and not isinstance(value, (int, float)):
                errors.append(f"math_formula_group `{node_id}` {key} must be numeric.")

    return warnings, errors


def node_has_role(node: dict, role: str) -> bool:
    text = node_semantic_text(node)
    if role == "discriminator":
        return "discriminator" in text or re.search(r"\bdisc\b", text) is not None
    if role == "generated":
        return "generated" in text or "reconstructed tfr" in text
    if role == "generator":
        return "generator" in text and "discriminator" not in text
    if role == "real_tfr":
        return "real" in text and "tfr" in text
    return role in text


def scene_looks_like_gan_tfr(scene: dict, nodes_by_id: dict[str, dict]) -> bool:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    corpus = " ".join(
        [
            str(metadata.get("title", "")),
            str(metadata.get("notes", "")),
            *[node_semantic_text(node) for node in nodes_by_id.values()],
        ]
    ).lower()
    return (
        ("gan" in corpus or "generator" in corpus)
        and "discriminator" in corpus
        and ("generated" in corpus or "reconstructed tfr" in corpus)
    )


def point_touching_node_id(
    point: tuple[float, float] | None,
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
    tolerance: float = 0.04,
) -> str | None:
    if point is None:
        return None
    candidates: list[dict] = []
    for node_id, node in nodes_by_id.items():
        if not has_valid_box(node):
            continue
        if is_background_node(node):
            continue
        if node_types_by_id.get(node_id) in CONTAINER_TYPES | {"audit_region", "text_block", "junction_point"}:
            continue
        if point_in_box(point, node_box(node), tolerance=tolerance):
            candidates.append(node)
    if not candidates:
        return None
    return min(candidates, key=box_area).get("id")


def edge_endpoint_node_id(
    edge: dict,
    endpoint_name: str,
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
) -> str | None:
    endpoint = edge.get(endpoint_name)
    if isinstance(endpoint, str):
        node_id = base_node_id(endpoint)
        if node_id in nodes_by_id:
            return node_id
    return point_touching_node_id(edge_point(edge, endpoint_name), nodes_by_id, node_types_by_id)


def edge_endpoint_role(
    edge: dict,
    endpoint_name: str,
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
) -> str | None:
    node_id = edge_endpoint_node_id(edge, endpoint_name, nodes_by_id, node_types_by_id)
    if not node_id:
        return None
    node = nodes_by_id[node_id]
    for role in ("discriminator", "generated", "generator", "real_tfr"):
        if node_has_role(node, role):
            return role
    return None


def segment_length(start: tuple[float, float], end: tuple[float, float]) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def turn_angle_degrees(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    len1 = math.hypot(*v1)
    len2 = math.hypot(*v2)
    if len1 <= 1e-9 or len2 <= 1e-9:
        return 0.0
    dot = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)))
    return math.degrees(math.acos(dot))


def terminal_tangent_issue(edge: dict, route_points: list[tuple[float, float]]) -> str | None:
    if len(route_points) < 4:
        return None
    edge_id = str(edge.get("id", "<missing-id>"))
    if not edge.get("end_tangent_point"):
        return (
            f"Outer loop `{edge_id}` has no `end_tangent_point`. Add an explicit near-end tangent point so the "
            "arrowhead approaches the target smoothly instead of inheriting a kink from the last sampled loop point."
        )
    angle = turn_angle_degrees(route_points[-3], route_points[-2], route_points[-1])
    if angle > 55 and not edge.get("allow_terminal_kink"):
        return (
            f"Outer loop `{edge_id}` has a {angle:.1f} degree turn at the arrowhead. Move `end_tangent_point` "
            "onto the visual approach direction, or mark `allow_terminal_kink: true` only when the source really bends there."
        )
    final_len = segment_length(route_points[-2], route_points[-1])
    prev_len = segment_length(route_points[-3], route_points[-2])
    if prev_len > 0 and (final_len / prev_len < 0.18 or final_len / prev_len > 3.2):
        return (
            f"Outer loop `{edge_id}` has an imbalanced final approach segment. Keep the final tangent segment close "
            "to neighboring segment length so the arrowhead does not look detached or abruptly stretched."
        )
    return None


def axis_overlap(
    box_a: tuple[float, float, float, float],
    box_b: tuple[float, float, float, float],
    axis: str,
) -> float:
    if axis == "x":
        return max(0.0, min(box_a[2], box_b[2]) - max(box_a[0], box_b[0]))
    if axis == "y":
        return max(0.0, min(box_a[3], box_b[3]) - max(box_a[1], box_b[1]))
    return 0.0


def feedback_source_region_id(
    edge: dict,
    route_points: list[tuple[float, float]],
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
    region_types: set[str] | None = None,
) -> str | None:
    region_types = region_types or {"dashed_region", "loss_region"}
    source = edge.get("from")
    if isinstance(source, str):
        source_id = base_node_id(source)
        if node_types_by_id.get(source_id) in region_types:
            return source_id
    start = route_points[0] if route_points else edge_point(edge, "from")
    if start is None:
        return None
    containing = [
        node
        for node_id, node in nodes_by_id.items()
        if node_types_by_id.get(node_id) in region_types
        and point_in_box(start, node_box(node), tolerance=CONTAINER_TOLERANCE)
    ]
    if not containing:
        return None
    return min(containing, key=box_area).get("id")


def loss_feedback_stub_issue(
    edge: dict,
    route_points: list[tuple[float, float]],
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
) -> str | None:
    if edge.get("type") != "dashed_feedback_path" or len(route_points) < 2:
        return None
    source_region_id = feedback_source_region_id(edge, route_points, nodes_by_id, node_types_by_id, {"loss_region"})
    if not source_region_id:
        return None
    target_id = edge_endpoint_node_id(edge, "to", nodes_by_id, node_types_by_id)
    if not target_id or target_id == source_region_id or target_id not in nodes_by_id:
        return None
    target_type = node_types_by_id.get(target_id)
    if target_type in CONTAINER_TYPES | {"text_block", "junction_point", "boundary_port", "merge_bus"}:
        return None

    region_box = node_box(nodes_by_id[source_region_id])
    target_box = node_box(nodes_by_id[target_id])
    region_w = max(1e-9, region_box[2] - region_box[0])
    region_h = max(1e-9, region_box[3] - region_box[1])
    target_w = max(1e-9, target_box[2] - target_box[0])
    target_h = max(1e-9, target_box[3] - target_box[1])
    horizontal_overlap = axis_overlap(region_box, target_box, "x")
    vertical_overlap = axis_overlap(region_box, target_box, "y")
    source_center = ((region_box[0] + region_box[2]) / 2, (region_box[1] + region_box[3]) / 2)
    target_center = ((target_box[0] + target_box[2]) / 2, (target_box[1] + target_box[3]) / 2)
    target_endpoint = edge.get("to")
    side = endpoint_side(target_endpoint) if isinstance(target_endpoint, str) else None
    edge_id = str(edge.get("id", "<missing-id>"))

    if horizontal_overlap >= min(region_w, target_w) * 0.25 and target_center[1] >= source_center[1]:
        clean_vertical_stub = (
            side == "top"
            and len(route_points) == 2
            and segment_axis(route_points[0], route_points[-1]) == "vertical"
        )
        if not clean_vertical_stub:
            return (
                f"Loss feedback path `{edge_id}` leaves `{source_region_id}` toward overlapping target `{target_id}` "
                "as a side/L-shaped route. Use short vertical boundary-to-top stubs; otherwise the loss frame reads as "
                "an extra dashed box plus arrow."
            )
    if horizontal_overlap >= min(region_w, target_w) * 0.25 and target_center[1] < source_center[1]:
        clean_vertical_stub = (
            side == "bottom"
            and len(route_points) == 2
            and segment_axis(route_points[0], route_points[-1]) == "vertical"
        )
        if not clean_vertical_stub:
            return (
                f"Loss feedback path `{edge_id}` leaves `{source_region_id}` toward overlapping target `{target_id}` "
                "without a clean vertical boundary stub."
            )
    if vertical_overlap >= min(region_h, target_h) * 0.25 and target_center[0] >= source_center[0]:
        clean_horizontal_stub = (
            side == "left"
            and len(route_points) == 2
            and segment_axis(route_points[0], route_points[-1]) == "horizontal"
        )
        if not clean_horizontal_stub:
            return (
                f"Loss feedback path `{edge_id}` leaves `{source_region_id}` toward side target `{target_id}` "
                "without a clean horizontal boundary stub."
            )
    if vertical_overlap >= min(region_h, target_h) * 0.25 and target_center[0] < source_center[0]:
        clean_horizontal_stub = (
            side == "right"
            and len(route_points) == 2
            and segment_axis(route_points[0], route_points[-1]) == "horizontal"
        )
        if not clean_horizontal_stub:
            return (
                f"Loss feedback path `{edge_id}` leaves `{source_region_id}` toward side target `{target_id}` "
                "without a clean horizontal boundary stub."
            )
    return None


def text_has_raw_loss_subscript(text: str) -> bool:
    lowered = text.lower()
    return (
        bool(LOSS_FORMULA_PATTERN.search(text))
        or bool(COMPACT_LOSS_FORMULA_PATTERN.search(text))
    ) and any(
        token in lowered for token in {"loss", "penalty", "adversarial", "reconstruction", "gradient", "l_", "ladv", "lrec"}
    )


def text_has_generic_subscript_label(text: str) -> bool:
    return bool(GENERIC_SUBSCRIPT_LABEL_PATTERN.search(str(text)))


def text_has_hat_notation(text: str) -> bool:
    return COMBINING_CIRCUMFLEX in str(text) or bool(re.search(r"\b[A-Za-z]\^", str(text)))


def text_has_compact_loss_notation(text: str) -> bool:
    return bool(COMPACT_LOSS_FORMULA_PATTERN.search(str(text))) and "_" not in str(text)


def segment_bbox_intersects_box(
    start: tuple[float, float],
    end: tuple[float, float],
    box: tuple[float, float, float, float],
    clearance: float = 0.0,
) -> bool:
    lo_x, hi_x = sorted((start[0], end[0]))
    lo_y, hi_y = sorted((start[1], end[1]))
    x1, y1, x2, y2 = box
    return max(lo_x, x1 + clearance) <= min(hi_x, x2 - clearance) and max(lo_y, y1 + clearance) <= min(hi_y, y2 - clearance)


def polyline_intersects_box_bbox(
    points: list[tuple[float, float]],
    box: tuple[float, float, float, float],
    clearance: float = 0.0,
) -> bool:
    return any(segment_bbox_intersects_box(start, end, box, clearance=clearance) for start, end in zip(points, points[1:]))


def path_bounds(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def expanded_box(box: tuple[float, float, float, float], padding: float) -> tuple[float, float, float, float]:
    return (box[0] - padding, box[1] - padding, box[2] + padding, box[3] + padding)


def point_in_box(point: tuple[float, float], box: tuple[float, float, float, float], tolerance: float = 0.0) -> bool:
    x, y = point
    x1, y1, x2, y2 = box
    return x1 - tolerance <= x <= x2 + tolerance and y1 - tolerance <= y <= y2 + tolerance


def segment_crosses_box(
    start: tuple[float, float],
    end: tuple[float, float],
    box: tuple[float, float, float, float],
    clearance: float = 0.0,
) -> bool:
    x1, y1, x2, y2 = expanded_box(box, -clearance) if clearance else box
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    p = [-dx, dx, -dy, dy]
    q = [sx - x1, x2 - sx, sy - y1, y2 - sy]
    u1 = 0.0
    u2 = 1.0
    for pi, qi in zip(p, q):
        if abs(pi) <= 1e-12:
            if qi < 0:
                return False
            continue
        ratio = qi / pi
        if pi < 0:
            if ratio > u2:
                return False
            u1 = max(u1, ratio)
        else:
            if ratio < u1:
                return False
            u2 = min(u2, ratio)
    if u1 > u2:
        return False
    return u2 > 0.0 and u1 < 1.0


def segment_has_diagonal(start: tuple[float, float], end: tuple[float, float]) -> bool:
    return abs(start[0] - end[0]) > POINT_TOLERANCE and abs(start[1] - end[1]) > POINT_TOLERANCE


def segment_axis(start: tuple[float, float], end: tuple[float, float]) -> str:
    if abs(start[1] - end[1]) <= POINT_TOLERANCE:
        return "horizontal"
    if abs(start[0] - end[0]) <= POINT_TOLERANCE:
        return "vertical"
    return "diagonal"


def route_axes(points: list[tuple[float, float]]) -> set[str]:
    return {segment_axis(start, end) for start, end in zip(points, points[1:])}


def segment_intersects_box_interior(
    start: tuple[float, float],
    end: tuple[float, float],
    box: tuple[float, float, float, float],
    clearance: float = 0.015,
) -> bool:
    x1, y1, x2, y2 = box
    sx, sy = start
    ex, ey = end

    if abs(sy - ey) <= POINT_TOLERANCE:
        y = (sy + ey) / 2
        if not (y1 + clearance < y < y2 - clearance):
            return False
        lo, hi = sorted((sx, ex))
        return max(lo, x1 + clearance) < min(hi, x2 - clearance)

    if abs(sx - ex) <= POINT_TOLERANCE:
        x = (sx + ex) / 2
        if not (x1 + clearance < x < x2 - clearance):
            return False
        lo, hi = sorted((sy, ey))
        return max(lo, y1 + clearance) < min(hi, y2 - clearance)

    return False


def infer_containers(nodes_by_id: dict[str, dict], node_types_by_id: dict[str, str], warnings: list[str]) -> dict[str, str | None]:
    containers = [
        node
        for node in nodes_by_id.values()
        if node_types_by_id.get(node.get("id")) in CONTAINER_TYPES
    ]
    container_ids = {node["id"] for node in containers}
    result: dict[str, str | None] = {}

    for node_id, node in nodes_by_id.items():
        if is_background_node(node):
            result[node_id] = None
            continue
        if node_types_by_id.get(node_id) in CONTAINER_TYPES:
            result[node_id] = None
            continue

        explicit_container = node.get("container_id")
        if explicit_container:
            if explicit_container not in container_ids:
                warnings.append(
                    f"Node `{node_id}` has unknown container_id `{explicit_container}`."
                )
                result[node_id] = None
            else:
                result[node_id] = str(explicit_container)
            continue

        center = node_center(node)
        containing = [
            container
            for container in containers
            if point_in_box(center, node_box(container), tolerance=CONTAINER_TOLERANCE)
        ]
        if not containing:
            result[node_id] = None
        else:
            result[node_id] = min(containing, key=box_area)["id"]

    return result


def container_for_point(point: tuple[float, float] | None, nodes_by_id: dict[str, dict], node_types_by_id: dict[str, str]) -> str | None:
    if point is None:
        return None
    containing = [
        node
        for node in nodes_by_id.values()
        if node_types_by_id.get(node.get("id")) in CONTAINER_TYPES
        and point_in_box(point, node_box(node), tolerance=CONTAINER_TOLERANCE)
    ]
    if not containing:
        return None
    return min(containing, key=box_area)["id"]


def normalize_alignment_axes(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def validate_alignment(
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
    containers_by_node: dict[str, str | None],
    warnings: list[str],
) -> None:
    align_groups: dict[tuple[str, str], list[str]] = {}

    for node_id, node in nodes_by_id.items():
        if node_types_by_id.get(node_id) in CONTAINER_TYPES:
            continue

        tolerance = float(node.get("align_tolerance_in", 0.05))
        for axis in normalize_alignment_axes(node.get("align_to_container")):
            container_id = str(node.get("container_id") or containers_by_node.get(node_id) or "")
            if not container_id or container_id not in nodes_by_id:
                warnings.append(
                    f"Node `{node_id}` requests align_to_container `{axis}` but has no valid container."
                )
                continue
            node_cx, node_cy = node_center(node)
            container_cx, container_cy = node_center(nodes_by_id[container_id])
            if axis == "center_y" and abs(node_cy - container_cy) > tolerance:
                warnings.append(
                    f"Node `{node_id}` is not vertically centered in container `{container_id}` "
                    f"(delta={node_cy - container_cy:.3f} in)."
                )
            elif axis == "center_x" and abs(node_cx - container_cx) > tolerance:
                warnings.append(
                    f"Node `{node_id}` is not horizontally centered in container `{container_id}` "
                    f"(delta={node_cx - container_cx:.3f} in)."
                )
            elif axis not in {"center_x", "center_y"}:
                warnings.append(f"Node `{node_id}` has unsupported align_to_container axis `{axis}`.")

        group_id = node.get("align_group")
        if group_id:
            axis = str(node.get("align_axis", "center_y"))
            align_groups.setdefault((str(group_id), axis), []).append(node_id)

    for (group_id, axis), node_ids in align_groups.items():
        if len(node_ids) < 2:
            continue
        tolerance = max(float(nodes_by_id[node_id].get("align_tolerance_in", 0.05)) for node_id in node_ids)
        centers = [node_center(nodes_by_id[node_id]) for node_id in node_ids]
        values = [center[1] if axis == "center_y" else center[0] for center in centers]
        if axis not in {"center_x", "center_y"}:
            warnings.append(f"Alignment group `{group_id}` has unsupported axis `{axis}`.")
            continue
        if max(values) - min(values) > tolerance:
            warnings.append(
                f"Alignment group `{group_id}` is not aligned on `{axis}` "
                f"(spread={max(values) - min(values):.3f} in; nodes={', '.join(node_ids)})."
            )


def distance_to_container_side(
    point: tuple[float, float],
    container_box: tuple[float, float, float, float],
    side: str,
) -> float:
    x, y = point
    x1, y1, x2, y2 = container_box
    if side == "left":
        return abs(x - x1)
    if side == "right":
        return abs(x - x2)
    if side == "top":
        return abs(y - y1)
    if side == "bottom":
        return abs(y - y2)
    return min(abs(x - x1), abs(x - x2), abs(y - y1), abs(y - y2))


def validate_boundary_ports(
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
    warnings: list[str],
    errors: list[str],
) -> None:
    allowed_sides = {"left", "right", "top", "bottom"}
    allowed_shapes = {"circle", "oval", "dot", "square", "rectangle", "rect", "tick", "line", "none"}
    for node_id, node in nodes_by_id.items():
        if node_types_by_id.get(node_id) != "boundary_port":
            continue

        side = str(node.get("side", "")).lower()
        if side and side not in allowed_sides:
            errors.append(f"Boundary port `{node_id}` has unsupported side `{side}`.")

        shape = str(node.get("shape", "circle")).lower()
        if shape not in allowed_shapes:
            errors.append(f"Boundary port `{node_id}` has unsupported shape `{shape}`.")

        container_id = node.get("container_id")
        if not container_id:
            warnings.append(
                f"Boundary port `{node_id}` has no container_id; use explicit container_id so cross-frame routes stay traceable."
            )
            continue
        if container_id not in nodes_by_id or node_types_by_id.get(container_id) not in CONTAINER_TYPES:
            warnings.append(f"Boundary port `{node_id}` references non-container `{container_id}`.")
            continue

        try:
            center = node_center(node)
            container_box = node_box(nodes_by_id[str(container_id)])
        except Exception:
            continue
        tolerance = float(node.get("boundary_tolerance_in", 0.12))
        if side:
            distance = distance_to_container_side(center, container_box, side)
        else:
            distance = distance_to_container_side(center, container_box, "")
        if distance > tolerance:
            side_text = f" `{side}`" if side else ""
            warnings.append(
                f"Boundary port `{node_id}` is not close to container{side_text} boundary "
                f"(distance={distance:.3f} in)."
            )


def source_aspect_ratio(metadata: dict, warnings: list[str]) -> float | None:
    value = metadata.get("source_aspect_ratio")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)

    source_image = metadata.get("source_image")
    if not source_image:
        return None
    path = Path(str(source_image))
    if not path.exists():
        warnings.append(f"metadata.source_image does not exist: {path}")
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        if height <= 0:
            return None
        return width / height
    except Exception as exc:
        warnings.append(f"Could not read metadata.source_image aspect ratio: {exc}")
        return None


def validate_fidelity_metadata(
    scene: dict,
    warnings: list[str],
    errors: list[str] | None = None,
    strict_contract: bool = False,
) -> None:
    metadata = scene.get("metadata", {})
    if not isinstance(metadata, dict):
        return
    if not exact_mode_from_metadata(metadata):
        return

    def contract_issue(message: str) -> None:
        if strict_contract and errors is not None:
            errors.append(message)
        else:
            warnings.append(message)

    if not metadata.get("source_image") and not metadata.get("source_aspect_ratio"):
        contract_issue(
            "Exact reconstruction mode needs metadata.source_image or metadata.source_aspect_ratio; "
            "otherwise page proportions cannot be checked against the source."
        )
    review_mode = str(metadata.get("replica_review_mode", metadata.get("review_mode", ""))).lower()
    if not review_mode:
        contract_issue(
            "Exact reconstruction should set `metadata.replica_review_mode`, typically `strict_replica`, so semantic redraw and source-faithful review are not confused."
        )
    elif review_mode not in STRICT_REPLICA_REVIEW_MODES:
        contract_issue(
            f"Exact reconstruction uses replica_review_mode `{review_mode}`. Use a strict replica mode instead of a semantic-redraw review contract."
        )
    replica_stage = str(metadata.get("replica_stage", metadata.get("production_stage", ""))).lower()
    if not replica_stage:
        contract_issue(
            "Exact reconstruction should set `metadata.replica_stage` such as `layout_topology` or `detail_polish`; the workflow is intentionally two-stage."
        )
    elif replica_stage not in {"layout_topology", "detail_polish"}:
        contract_issue(
            f"Exact reconstruction uses unsupported replica_stage `{replica_stage}`. Use `layout_topology` or `detail_polish`."
        )

    if metadata.get("starter_template") or str(metadata.get("starter_mode", "")).lower() == "template_seed":
        contract_issue(
            "Exact reconstruction metadata records a template-seeded start. Strict capability evaluation must rebuild from a blank source-driven scene instead of validating a template bootstrap."
        )
    autofix_history = metadata.get("autofix_history")
    if isinstance(autofix_history, list) and autofix_history:
        contract_issue(
            "Exact reconstruction metadata records recipe/autofix rewrites. Strict capability evaluation must review a freshly authored scene, not a scene rewritten by scene_autofix or pre-render recipes."
        )

    inventory = metadata.get("source_visual_inventory")
    nodes = scene.get("nodes", []) if isinstance(scene.get("nodes"), list) else []
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
    if not isinstance(inventory, dict):
        contract_issue(
            "Exact reconstruction should record `metadata.source_visual_inventory` from visual LLM source-image analysis before scene authoring; "
            "region_plan alone cannot prevent semantic redraw drift."
        )
    else:
        analysis_basis = str(inventory.get("analysis_basis", "")).lower()
        if "visual" not in analysis_basis or "source" not in analysis_basis:
            contract_issue(
                "metadata.source_visual_inventory.analysis_basis should state that the source image was inspected visually, e.g. `visual_llm_source_image`."
            )
        if inventory.get("do_not_translate") is not True:
            contract_issue(
                "metadata.source_visual_inventory.do_not_translate should be true for exact replicas so source labels are not silently translated or normalized."
            )
        unknown_policy = str(inventory.get("unknown_text_policy", "")).lower()
        if "unreadable" not in unknown_policy or "invent" not in unknown_policy:
            contract_issue(
                "metadata.source_visual_inventory.unknown_text_policy should require marking unreadable text instead of inventing replacements."
            )
        authoring_mode = str(inventory.get("scene_authoring_mode", "")).lower()
        prior_policy = str(inventory.get("prior_scene_policy", "")).lower()
        if "fresh" not in authoring_mode or "source" not in authoring_mode:
            contract_issue(
                "metadata.source_visual_inventory.scene_authoring_mode should make clear that this scene was authored fresh from the source inventory."
            )
        if prior_policy and not any(token in prior_policy for token in ("do_not", "not", "no")):
            contract_issue(
                "metadata.source_visual_inventory.prior_scene_policy should forbid reading or patching a prior-round scene during capability evaluation."
            )
        regions = inventory.get("regions")
        if not isinstance(regions, list) or len(regions) < 3:
            contract_issue(
                "metadata.source_visual_inventory.regions should list source-inspected regions; dense exact figures usually need global/input/core/output/arrow-dense/small-text coverage."
            )
        else:
            inventory_region_text = ""
            inventory_coverage: set[str] = set()
            inventory_source_boxes: dict[str, tuple[float, float, float, float]] = {}
            for index, region in enumerate(regions):
                if not isinstance(region, dict):
                    contract_issue(f"metadata.source_visual_inventory.regions[{index}] should be an object.")
                    continue
                categories = region_categories(region, include_required_crop_types=True)
                inventory_coverage.update(categories)
                inventory_region_text += " " + " ".join(
                    str(value)
                    for value in (
                        region.get("id", ""),
                        region.get("name", ""),
                        " ".join(str(item) for item in region.get("required_crop_types", []) if isinstance(item, str))
                        if isinstance(region.get("required_crop_types"), list)
                        else "",
                    )
                ).lower()
                if not (region.get("id") or region.get("name")):
                    contract_issue(f"metadata.source_visual_inventory.regions[{index}] needs an id/name.")
                source_sig = bbox_signature(region.get("source_bbox_px", region.get("source_bbox", region.get("bbox_px"))))
                if source_sig is None:
                    contract_issue(
                        f"metadata.source_visual_inventory.regions[{index}] should include source_bbox_px/source_bbox so review crops bind to the source image."
                    )
                else:
                    for category in categories:
                        inventory_source_boxes.setdefault(category, source_sig)
                text_layout = region.get("text_layout_facts")
                if text_layout is not None and not isinstance(text_layout, list):
                    contract_issue(
                        f"metadata.source_visual_inventory.regions[{index}].text_layout_facts should be an array of source typography/layout facts."
                    )
                for key in ("box_style_facts", "line_style_facts", "shadow_facts", "density_facts"):
                    value = region.get(key)
                    if value is not None and not isinstance(value, list):
                        contract_issue(
                            f"metadata.source_visual_inventory.regions[{index}].{key} should be an array of source-visible style facts."
                        )
                obligations = region.get("fidelity_obligations")
                if obligations is not None and not isinstance(obligations, list):
                    contract_issue(f"metadata.source_visual_inventory.regions[{index}].fidelity_obligations should be an array.")
                if isinstance(obligations, list):
                    for obligation_index, obligation in enumerate(obligations):
                        if not isinstance(obligation, dict):
                            contract_issue(
                                f"metadata.source_visual_inventory.regions[{index}].fidelity_obligations[{obligation_index}] should be an object."
                            )
                            continue
                        if not str(obligation.get("object", "")).strip():
                            contract_issue(
                                f"metadata.source_visual_inventory.regions[{index}].fidelity_obligations[{obligation_index}] needs an object name."
                            )
                        for obligation_key in ("must_preserve", "allowed_simplification", "forbidden_simplification"):
                            value = obligation.get(obligation_key)
                            if value is not None and not isinstance(value, list):
                                contract_issue(
                                    f"metadata.source_visual_inventory.regions[{index}].fidelity_obligations[{obligation_index}].{obligation_key} should be an array."
                                )
                        if not obligation.get("must_preserve"):
                            contract_issue(
                                f"metadata.source_visual_inventory.regions[{index}].fidelity_obligations[{obligation_index}] should list must_preserve details."
                            )
                crop_targets = region.get("required_crop_types")
                if crop_targets is not None and not isinstance(crop_targets, list):
                    contract_issue(
                        f"metadata.source_visual_inventory.regions[{index}].required_crop_types should be an array."
                    )
                has_visible_contract = any(
                    isinstance(region.get(key), list) and len(region.get(key, [])) > 0
                    for key in (
                        "required_labels",
                        "required_formulas",
                        "required_component_motifs",
                        "required_edge_motifs",
                        "required_ports_or_boundaries",
                    )
                )
                if not has_visible_contract:
                    contract_issue(
                        f"metadata.source_visual_inventory.regions[{index}] has no required labels/formulas/component motifs/edge motifs/ports; "
                        "the scene can drift into a generic redraw without a visible-source contract."
                    )
                has_style_contract = any(
                    isinstance(region.get(key), list) and len(region.get(key, [])) > 0
                    for key in ("box_style_facts", "line_style_facts", "shadow_facts", "density_facts")
                )
                if not has_style_contract:
                    contract_issue(
                        f"metadata.source_visual_inventory.regions[{index}] has no box/line/shadow/density facts. "
                        "Exact review needs explicit style facts for padding, rounding, shadow, line weight, or density, not only labels."
                    )
            missing_inventory_categories = [category for category in required_categories if category not in inventory_coverage]
            if missing_inventory_categories:
                contract_issue(
                    f"metadata.source_visual_inventory.regions misses review coverage for `{', '.join(missing_inventory_categories)}`."
                )
            global_inventory_box = inventory_source_boxes.get("global")
            for category in ("input", "core", "output", "arrow_dense", "small_text", "caption"):
                if global_inventory_box and inventory_source_boxes.get(category) == global_inventory_box:
                    contract_issue(
                        f"metadata.source_visual_inventory region coverage for `{category}` reuses the global source bbox; strict review crops must be source-bound local regions."
                    )
            trio_inventory = [inventory_source_boxes.get(category) for category in ("input", "core", "output")]
            if all(box is not None for box in trio_inventory) and len(set(trio_inventory)) < 3:
                contract_issue(
                    "metadata.source_visual_inventory input/core/output source bboxes are not distinct; strict regional review would collapse into repeated crops."
                )
            if caption_required and "caption" not in inventory_region_text:
                contract_issue(
                    "Exact reconstruction includes a caption-like node but source_visual_inventory.regions does not advertise caption crop coverage."
                )

    visual_grammar = metadata.get("visual_grammar_inventory")
    if not isinstance(visual_grammar, dict):
        contract_issue(
            "Exact reconstruction should record `metadata.visual_grammar_inventory` before choosing components. "
            "List source shape/cell/line/symbol/wave/text facts so components preserve visual grammar instead of normalizing the figure."
        )
    else:
        non_empty_keys = 0
        for key in VISUAL_GRAMMAR_INVENTORY_KEYS:
            value = visual_grammar.get(key)
            if value is None:
                contract_issue(f"metadata.visual_grammar_inventory.{key} is missing; record source-visible facts even when the list is short.")
                continue
            if not isinstance(value, list):
                contract_issue(f"metadata.visual_grammar_inventory.{key} should be an array of source-visible facts.")
                continue
            if value:
                non_empty_keys += 1
        if non_empty_keys < 2:
            contract_issue(
                "metadata.visual_grammar_inventory is too sparse; exact replicas need at least two visual-fact categories such as cells plus lines, or symbols plus text."
            )

    page = scene.get("page", {})
    if not isinstance(page, dict):
        return
    page_width = page.get("width")
    page_height = page.get("height")
    if not isinstance(page_width, (int, float)) or not isinstance(page_height, (int, float)) or page_height <= 0:
        return

    src_ratio = source_aspect_ratio(metadata, warnings)
    if src_ratio is None:
        return
    page_ratio = float(page_width) / float(page_height)
    delta = abs(page_ratio - src_ratio) / src_ratio
    if delta > ASPECT_RATIO_TOLERANCE:
        contract_issue(
            f"Page aspect ratio {page_ratio:.3f} differs from source {src_ratio:.3f} by {delta:.1%}; "
            "exact reconstruction should preserve the source canvas ratio before tuning coordinates."
        )

    region_plan = metadata.get("region_plan", metadata.get("source_region_plan", metadata.get("source_regions")))
    if region_plan is None:
        contract_issue(
            "Exact reconstruction should record `metadata.region_plan` with source/target bboxes for global, input, core, output, arrow-dense, small-text, and boundary review regions."
        )
    elif not isinstance(region_plan, list):
        contract_issue("metadata.region_plan should be an array of region objects with id/name and source_bbox_px/target_bbox.")
    else:
        plan_text = ""
        plan_coverage: set[str] = set()
        plan_source_boxes: dict[str, tuple[float, float, float, float]] = {}
        if len(region_plan) < 3:
            contract_issue(
                f"metadata.region_plan has only {len(region_plan)} regions; dense exact figures need explicit source bboxes for multiple review crops."
            )
        for index, region in enumerate(region_plan):
            if not isinstance(region, dict):
                contract_issue(f"metadata.region_plan[{index}] should be an object.")
                continue
            categories = region_categories(region)
            plan_coverage.update(categories)
            plan_text += " " + " ".join(
                str(value)
                for value in (
                    region.get("id", ""),
                    region.get("name", ""),
                    region.get("crop_type", ""),
                    region.get("review_crop_type", ""),
                    region.get("review_focus", ""),
                )
            ).lower()
            if not (region.get("id") or region.get("name")):
                contract_issue(f"metadata.region_plan[{index}] needs an id/name so visual review can refer to it.")
            source_sig = bbox_signature(region.get("source_bbox_px", region.get("source_bbox", region.get("bbox_px"))))
            has_target = any(region.get(key) is not None for key in ("target_bbox", "target_bbox_in", "scene_bbox", "node_id", "container_id"))
            if source_sig is None or not has_target:
                contract_issue(
                    f"metadata.region_plan[{index}] should bind a source bbox to a target bbox/container; otherwise density drift is hard to review."
                )
            else:
                for category in categories:
                    plan_source_boxes.setdefault(category, source_sig)
            crop_type = str(region.get("crop_type", region.get("review_crop_type", ""))).lower()
            if not crop_type:
                contract_issue(
                    f"metadata.region_plan[{index}] should record crop_type/review_crop_type so QA can generate the intended regional crop."
                )
            local_acceptance = region.get("local_acceptance_checklist")
            if local_acceptance is not None and string_list_signature(local_acceptance) is None:
                contract_issue(
                    f"metadata.region_plan[{index}].local_acceptance_checklist should be an array of non-empty strings."
                )
            if strict_contract and ({"arrow_dense", "small_text"} & categories) and not local_acceptance:
                contract_issue(
                    f"metadata.region_plan[{index}] is a dense review region but has no local_acceptance_checklist."
                )
            review_focus = region.get("review_focus")
            if strict_contract and ({"arrow_dense", "small_text"} & categories) and not (
                isinstance(review_focus, str) and review_focus.strip()
            ):
                contract_issue(
                    f"metadata.region_plan[{index}] is a dense review region but has no review_focus."
                )
        missing_plan_categories = [category for category in required_categories if category not in plan_coverage]
        if missing_plan_categories:
            contract_issue(
                f"metadata.region_plan misses strict review regions `{', '.join(missing_plan_categories)}`."
            )
        global_plan_box = plan_source_boxes.get("global")
        for category in ("input", "core", "output", "arrow_dense", "small_text", "caption"):
            if global_plan_box and plan_source_boxes.get(category) == global_plan_box:
                contract_issue(
                    f"metadata.region_plan coverage for `{category}` reuses the global source bbox; strict review assets must include source-bound local crops."
                )
        trio_plan = [plan_source_boxes.get(category) for category in ("input", "core", "output")]
        if all(box is not None for box in trio_plan) and len(set(trio_plan)) < 3:
            contract_issue(
                "metadata.region_plan input/core/output source bboxes are not distinct; strict review would collapse into repeated crops."
            )
        if caption_required and "caption" not in plan_text:
            contract_issue(
                "Exact reconstruction includes caption-like content but metadata.region_plan has no caption crop region."
            )


def arrow_plan_items(metadata: dict[str, Any]) -> list[Any] | None:
    plan = metadata.get("arrow_plan")
    if plan is None:
        plan = metadata.get("edge_inventory")
    if plan is None:
        inventory = metadata.get("source_visual_inventory")
        if isinstance(inventory, dict):
            plan = inventory.get("arrow_plan", inventory.get("edge_inventory"))
    return plan if isinstance(plan, list) else None


def edge_arrow_plan_id(edge: dict[str, Any]) -> str | None:
    value = edge.get("arrow_plan_id", edge.get("source_arrow_id", edge.get("edge_inventory_id")))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def node_motif_edges(node: dict[str, Any]) -> list[dict[str, Any]]:
    value = node.get("motif_edges")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def edge_endpoint_type(edge: dict[str, Any], endpoint_name: str, node_types_by_id: dict[str, str]) -> str | None:
    endpoint = edge.get(endpoint_name)
    if not isinstance(endpoint, str):
        return None
    return node_types_by_id.get(base_node_id(endpoint))


def endpoint_matches_anchor(endpoint: Any, anchor: Any) -> bool:
    if not isinstance(endpoint, str) or not isinstance(anchor, str) or not anchor.strip():
        return True
    anchor = anchor.strip().lower()
    if anchor in {"any", "unknown", "unspecified"}:
        return True
    if ":" in anchor:
        return endpoint.lower().endswith(anchor[anchor.index(":") :])
    side = endpoint_side(endpoint)
    return bool(side and side.lower() == anchor.split("@", 1)[0])


def validate_arrow_plan_contract(
    scene: dict[str, Any],
    edges: list[Any],
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
    component_map: dict,
    profile: dict,
    warnings: list[str],
    errors: list[str],
    strict_contract: bool = False,
) -> None:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    exact_mode = exact_mode_from_metadata(metadata)
    plans = arrow_plan_items(metadata)

    def contract_issue(message: str) -> None:
        if strict_contract:
            errors.append(message)
        else:
            warnings.append(message)

    if plans is None:
        if exact_mode and edges:
            contract_issue(
                "Exact reconstruction should include `metadata.arrow_plan` before first scene authoring. "
                "List every source-visible arrow with intent, endpoints, route_shape, arrowhead, and certainty so later review can check arrow fidelity."
            )
        return

    if not isinstance(plans, list):
        contract_issue("metadata.arrow_plan should be an array of source-visible arrow facts.")
        return

    plan_ids: set[str] = set()
    active_plan_ids: set[str] = set()
    for index, plan in enumerate(plans):
        if not isinstance(plan, dict):
            contract_issue(f"metadata.arrow_plan[{index}] should be an object.")
            continue
        plan_id = str(plan.get("id", "")).strip()
        if not plan_id:
            contract_issue(f"metadata.arrow_plan[{index}] needs an `id` so scene edges and review findings can refer to it.")
            continue
        if plan_id in plan_ids:
            contract_issue(f"metadata.arrow_plan has duplicate id `{plan_id}`.")
        plan_ids.add(plan_id)
        certainty = str(plan.get("certainty", "")).lower()
        status = str(plan.get("status", "")).lower()
        if certainty not in {"uncertain", "unknown"} and status not in {"optional", "skipped", "not_visible"}:
            active_plan_ids.add(plan_id)
        intent = str(plan.get("semantic_intent", plan.get("intent", ""))).lower()
        if not intent:
            contract_issue(f"metadata.arrow_plan `{plan_id}` should record semantic_intent, such as data_flow, feedback, boundary_handoff, merge, fork, or loop_update.")
        elif intent not in ARROW_PLAN_INTENTS:
            contract_issue(f"metadata.arrow_plan `{plan_id}` has unsupported semantic_intent `{intent}`.")
        route_shape = str(plan.get("route_shape", plan.get("shape", ""))).lower()
        if not route_shape:
            contract_issue(f"metadata.arrow_plan `{plan_id}` should record route_shape, such as straight_horizontal, orthogonal, rounded_orthogonal, smooth_curve, or loop.")
        elif route_shape not in ARROW_PLAN_ROUTE_SHAPES:
            contract_issue(f"metadata.arrow_plan `{plan_id}` has unsupported route_shape `{route_shape}`.")
        direction = str(plan.get("direction", "")).lower()
        if direction and direction not in ARROW_PLAN_DIRECTIONS:
            contract_issue(f"metadata.arrow_plan `{plan_id}` has unsupported direction `{direction}`.")
        if not any(plan.get(key) for key in ("from", "source", "source_fact", "source_endpoint")):
            contract_issue(f"metadata.arrow_plan `{plan_id}` should describe the visible source endpoint.")
        if not any(plan.get(key) for key in ("to", "target", "target_endpoint")):
            contract_issue(f"metadata.arrow_plan `{plan_id}` should describe the visible target endpoint.")
        if strict_contract:
            for required_key in (
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
            ):
                if required_key not in plan:
                    contract_issue(f"metadata.arrow_plan `{plan_id}` misses strict field `{required_key}`.")
        if plan.get("must_be_axis_aligned") and route_shape in {"curved", "smooth_curve", "loop", "freeform"}:
            contract_issue(f"metadata.arrow_plan `{plan_id}` asks for axis alignment but route_shape is `{route_shape}`.")
        bbox = plan.get("source_bbox_px")
        if strict_contract and bbox is not None and bbox_signature(bbox) is None:
            contract_issue(f"metadata.arrow_plan `{plan_id}` has invalid source_bbox_px; expected [left, top, right, bottom].")
        geometry_contract = plan.get("geometry_contract")
        if geometry_contract is not None:
            if not isinstance(geometry_contract, dict):
                contract_issue(f"metadata.arrow_plan `{plan_id}` geometry_contract should be an object.")
            else:
                for key, value in geometry_contract.items():
                    if key in GEOMETRY_CONTRACT_BOOL_FIELDS and not isinstance(value, bool):
                        contract_issue(f"metadata.arrow_plan `{plan_id}` geometry_contract.{key} should be boolean.")
                    elif key in GEOMETRY_CONTRACT_STRING_FIELDS and not isinstance(value, str):
                        contract_issue(f"metadata.arrow_plan `{plan_id}` geometry_contract.{key} should be a string.")
                    elif key in GEOMETRY_CONTRACT_NUMBER_FIELDS and not isinstance(value, (int, float)):
                        contract_issue(f"metadata.arrow_plan `{plan_id}` geometry_contract.{key} should be numeric.")
                horizontal_contract = bool(geometry_contract.get("must_be_horizontal"))
                vertical_contract = bool(geometry_contract.get("must_be_vertical"))
                if horizontal_contract and route_shape in {"straight_vertical", "vertical"}:
                    contract_issue(f"metadata.arrow_plan `{plan_id}` geometry_contract requires horizontal geometry but route_shape is `{route_shape}`.")
                if vertical_contract and route_shape in {"straight_horizontal", "horizontal"}:
                    contract_issue(f"metadata.arrow_plan `{plan_id}` geometry_contract requires vertical geometry but route_shape is `{route_shape}`.")
                if horizontal_contract and route_shape in {"curved", "smooth_curve", "loop", "freeform"}:
                    contract_issue(f"metadata.arrow_plan `{plan_id}` geometry_contract requires horizontal geometry but route_shape is `{route_shape}`.")
                if vertical_contract and route_shape in {"curved", "smooth_curve", "loop", "freeform"}:
                    contract_issue(f"metadata.arrow_plan `{plan_id}` geometry_contract requires vertical geometry but route_shape is `{route_shape}`.")

    edges_by_plan: dict[str, list[dict[str, Any]]] = {}
    motif_edges_by_plan: dict[str, list[dict[str, Any]]] = {}
    ribbon_nodes_by_plan: dict[str, list[dict[str, Any]]] = {}
    unplanned_edges: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("id", "<unknown>"))
        plan_id = edge_arrow_plan_id(edge)
        if plan_id:
            edges_by_plan.setdefault(plan_id, []).append(edge)
            if plan_id not in plan_ids:
                contract_issue(f"Edge `{edge_id}` references unknown arrow_plan_id `{plan_id}`.")
        elif exact_mode and edge.get("type") not in {"line_segment"} and not is_internal_edge(edge):
            unplanned_edges.append(edge_id)

    for node_id, node in nodes_by_id.items():
        node_type = str(node.get("type", ""))
        node_plan_id = edge_arrow_plan_id(node)
        if node_plan_id:
            if node_type in RIBBON_ARROW_NODE_TYPES:
                ribbon_nodes_by_plan.setdefault(node_plan_id, []).append(node)
            if node_plan_id not in plan_ids:
                contract_issue(f"Node `{node_id}` references unknown arrow_plan_id `{node_plan_id}`.")
        elif exact_mode and node_type in RIBBON_ARROW_NODE_TYPES:
            contract_issue(f"Ribbon arrow node `{node_id}` has no arrow_plan_id; bind thick visible arrows to metadata.arrow_plan.")
        for motif_edge in node_motif_edges(node):
            motif_edge_id = str(motif_edge.get("id", f"{node_id}.motif_edge"))
            plan_id = edge_arrow_plan_id(motif_edge)
            if plan_id:
                motif_edges_by_plan.setdefault(plan_id, []).append(motif_edge)
                if plan_id not in plan_ids:
                    contract_issue(f"Node `{node_id}` motif_edge `{motif_edge_id}` references unknown arrow_plan_id `{plan_id}`.")
            elif exact_mode and not is_internal_edge(motif_edge):
                contract_issue(f"Node `{node_id}` motif_edge `{motif_edge_id}` has no arrow_plan_id.")

    for plan_id in sorted(active_plan_ids):
        if plan_id not in edges_by_plan and plan_id not in motif_edges_by_plan and plan_id not in ribbon_nodes_by_plan:
            contract_issue(f"metadata.arrow_plan `{plan_id}` has no scene edge, motif_edge, or ribbon arrow node with matching `arrow_plan_id`.")

    if exact_mode and plans and unplanned_edges:
        contract_issue(
            "Exact reconstruction has visible edges without arrow_plan_id: "
            f"{', '.join(unplanned_edges[:8])}{' ...' if len(unplanned_edges) > 8 else ''}. "
            "Bind every source-visible arrow to metadata.arrow_plan so review can check the same topology facts."
        )

    plan_by_id = {str(plan.get("id", "")).strip(): plan for plan in plans if isinstance(plan, dict)}
    for plan_id in sorted(set(edges_by_plan) | set(motif_edges_by_plan) | set(ribbon_nodes_by_plan)):
        plan_edges = edges_by_plan.get(plan_id, [])
        motif_plan_edges = motif_edges_by_plan.get(plan_id, [])
        ribbon_plan_nodes = ribbon_nodes_by_plan.get(plan_id, [])
        plan = plan_by_id.get(plan_id)
        if not plan:
            continue
        all_bindings = [*plan_edges, *motif_plan_edges]
        if len(all_bindings) > 1:
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
            all_segmented = all(
                binding.get("same_source_arrow") is True
                and isinstance(binding.get("segment_index"), int)
                and isinstance(binding.get("segment_count"), int)
                for binding in all_bindings
            )
            expected_count = len(all_bindings)
            if not all_segmented or segment_count_values != {expected_count} or sorted(segment_indexes) != list(range(1, expected_count + 1)):
                contract_issue(
                    f"metadata.arrow_plan `{plan_id}` is bound to {len(all_bindings)} scene/motif edges. "
                    "One arrow_plan_id may map to multiple edges only when every edge declares "
                    "same_source_arrow=true, segment_index, and segment_count with complete 1-based segment coverage."
                )
        intent = str(plan.get("semantic_intent", plan.get("intent", ""))).lower()
        route_shape = str(plan.get("route_shape", plan.get("shape", ""))).lower()
        arrow_form_text = recursive_fact_text(
            {
                "visual_form": plan.get("visual_form", plan.get("arrow_form")),
                "line_style": plan.get("line_style"),
                "source_fact": plan.get("source_fact"),
                "relative_position_facts": plan.get("relative_position_facts"),
            }
        )
        plan_requires_ribbon = any(token in arrow_form_text for token in {"ribbon", "thick arrow", "filled arrow", "broad arrow", "band arrow"})
        from_anchor = plan.get("from_anchor", plan.get("source_anchor"))
        to_anchor = plan.get("to_anchor", plan.get("target_anchor"))
        geometry_contract = plan.get("geometry_contract") if isinstance(plan.get("geometry_contract"), dict) else {}
        must_axis = bool(plan.get("must_be_axis_aligned")) or route_shape in {
            "straight_horizontal",
            "straight_vertical",
            "horizontal",
            "vertical",
            "orthogonal",
            "elbow",
            "right_angle",
            "rounded_orthogonal",
            "hv",
            "vh",
        } or bool(geometry_contract.get("must_be_axis_aligned"))
        geometry_horizontal = bool(geometry_contract.get("must_be_horizontal"))
        geometry_vertical = bool(geometry_contract.get("must_be_vertical"))

        for motif_edge in motif_plan_edges:
            motif_edge_id = str(motif_edge.get("id", "<motif-edge>"))
            route_shape_value = str(motif_edge.get("route_shape", motif_edge.get("route", ""))).lower()
            if route_shape and route_shape_value and route_shape_value != route_shape:
                contract_issue(
                    f"Arrow plan `{plan_id}` expects route_shape `{route_shape}` but motif_edge `{motif_edge_id}` declares `{route_shape_value}`."
                )
            if not motif_edge.get("from") and not motif_edge.get("from_anchor_description"):
                contract_issue(f"Arrow plan `{plan_id}` motif_edge `{motif_edge_id}` should declare an internal source/from endpoint.")
            if not motif_edge.get("to") and not motif_edge.get("to_anchor_description"):
                contract_issue(f"Arrow plan `{plan_id}` motif_edge `{motif_edge_id}` should declare an internal target/to endpoint.")

        for ribbon_node in ribbon_plan_nodes:
            ribbon_node_id = str(ribbon_node.get("id", "<ribbon-node>"))
            ribbon_type = str(ribbon_node.get("type", ""))
            if plan_requires_ribbon and ribbon_type not in RIBBON_ARROW_NODE_TYPES:
                contract_issue(f"Arrow plan `{plan_id}` requires a ribbon/thick arrow but node `{ribbon_node_id}` uses `{ribbon_type}`.")
            if route_shape in {"curved", "smooth_curve"} and ribbon_type not in {"curved_ribbon_arrow"}:
                contract_issue(f"Arrow plan `{plan_id}` expects a curved ribbon arrow but node `{ribbon_node_id}` uses `{ribbon_type}`.")
            if route_shape == "loop" and ribbon_type not in {"loop_ribbon_arrow"}:
                contract_issue(f"Arrow plan `{plan_id}` expects a loop ribbon arrow but node `{ribbon_node_id}` uses `{ribbon_type}`.")

        for edge in plan_edges:
            edge_id = str(edge.get("id", "<unknown>"))
            edge_type = str(edge.get("type", ""))
            if plan_requires_ribbon:
                contract_issue(f"Arrow plan `{plan_id}` requires a ribbon/thick arrow but edge `{edge_id}` uses thin connector `{edge_type}`; use a ribbon arrow node.")
            if intent in {"feedback", "loss_backprop"} and edge_type != "dashed_feedback_path":
                contract_issue(f"Arrow plan `{plan_id}` is `{intent}` but edge `{edge_id}` uses `{edge_type}`; use `dashed_feedback_path`.")
            if intent in {"boundary_handoff", "frame_output"}:
                source_type = edge_endpoint_type(edge, "from", node_types_by_id)
                target_type = edge_endpoint_type(edge, "to", node_types_by_id)
                if edge_type != "boundary_arrow" and "boundary_port" not in {source_type, target_type}:
                    contract_issue(
                        f"Arrow plan `{plan_id}` is `{intent}` but edge `{edge_id}` is not bound to a boundary_port/boundary_arrow."
                    )
            if intent in {"merge", "fan_in"}:
                target_type = edge_endpoint_type(edge, "to", node_types_by_id)
                if target_type not in {"junction_point", "merge_bus", "multi_port_junction"} and edge_type not in {"join_connector"}:
                    contract_issue(
                        f"Arrow plan `{plan_id}` is `{intent}` but edge `{edge_id}` does not terminate at a junction/merge bus."
                    )
            if intent in {"fork", "fan_out"}:
                source_type = edge_endpoint_type(edge, "from", node_types_by_id)
                if source_type not in {"junction_point", "merge_bus", "multi_port_junction"} and edge_type not in {"fork_connector"}:
                    contract_issue(
                        f"Arrow plan `{plan_id}` is `{intent}` but edge `{edge_id}` does not originate from a junction/merge bus."
                    )
            if intent == "loop_update" and edge_type != "loop_arrow":
                contract_issue(f"Arrow plan `{plan_id}` is a loop_update but edge `{edge_id}` uses `{edge_type}`; use one continuous `loop_arrow`.")

            if from_anchor and not endpoint_matches_anchor(edge.get("from"), from_anchor):
                contract_issue(f"Arrow plan `{plan_id}` expects from_anchor `{from_anchor}` but edge `{edge_id}` uses `{edge.get('from')}`.")
            if to_anchor and not endpoint_matches_anchor(edge.get("to"), to_anchor):
                contract_issue(f"Arrow plan `{plan_id}` expects to_anchor `{to_anchor}` but edge `{edge_id}` uses `{edge.get('to')}`.")

            try:
                style = edge_style(edge, component_map, profile)
                route_points = edge_route_points(edge, style, nodes_by_id)
            except Exception as exc:
                contract_issue(f"Arrow plan `{plan_id}` edge `{edge_id}` route could not be checked: {exc}")
                continue

            axes = route_axes(route_points)
            has_diagonal = "diagonal" in axes
            if must_axis and has_diagonal and not edge.get("allow_diagonal"):
                contract_issue(
                    f"Arrow plan `{plan_id}` requires an axis-aligned route but edge `{edge_id}` has diagonal segment(s)."
                )
            if route_shape in {"straight_horizontal", "horizontal"} and axes - {"horizontal"}:
                contract_issue(f"Arrow plan `{plan_id}` expects a horizontal arrow but edge `{edge_id}` has {sorted(axes)} segment(s).")
            if route_shape in {"straight_vertical", "vertical"} and axes - {"vertical"}:
                contract_issue(f"Arrow plan `{plan_id}` expects a vertical arrow but edge `{edge_id}` has {sorted(axes)} segment(s).")
            if geometry_horizontal and axes - {"horizontal"}:
                contract_issue(f"Arrow plan `{plan_id}` geometry_contract expects horizontal geometry but edge `{edge_id}` has {sorted(axes)} segment(s).")
            if geometry_vertical and axes - {"vertical"}:
                contract_issue(f"Arrow plan `{plan_id}` geometry_contract expects vertical geometry but edge `{edge_id}` has {sorted(axes)} segment(s).")
            if route_shape in {"curved", "smooth_curve", "loop"}:
                if edge_type not in CURVED_EDGE_TYPES:
                    contract_issue(f"Arrow plan `{plan_id}` expects a curved/loop arrow but edge `{edge_id}` uses `{edge_type}`.")
                if len(route_points) < 4:
                    contract_issue(f"Arrow plan `{plan_id}` expects a smooth curve but edge `{edge_id}` has too few route points.")
                curve_mode = str(edge.get("curve_mode", edge.get("curve", style.get("curve_mode", "")))).lower()
                if route_shape in {"smooth_curve", "loop"} and curve_mode not in {"smooth", "bezier", "catmull_rom"}:
                    contract_issue(
                        f"Arrow plan `{plan_id}` expects a smooth curve but edge `{edge_id}` uses curve_mode `{curve_mode or 'polyline'}`."
                    )
            if route_shape == "rounded_orthogonal":
                route_name = str(edge.get("route", edge.get("style", {}).get("route", style.get("route", "")))).lower()
                if edge_type != "rounded_orthogonal_connector" and route_name != "rounded_orthogonal":
                    contract_issue(
                        f"Arrow plan `{plan_id}` expects a rounded orthogonal connector but edge `{edge_id}` uses `{edge_type}` with route `{route_name or 'auto'}`."
                    )
                if len(route_points) < 3:
                    contract_issue(f"Arrow plan `{plan_id}` expects a rounded orthogonal bend but edge `{edge_id}` has fewer than three route points.")
                edge_style_payload = edge.get("style", {}) if isinstance(edge.get("style"), dict) else {}
                radius = edge.get(
                    "corner_radius_in",
                    edge.get(
                        "corner_radius_px",
                        edge_style_payload.get("corner_radius_in", edge_style_payload.get("corner_radius_px")),
                    ),
                )
                if radius is None:
                    contract_issue(f"Arrow plan `{plan_id}` expects rounded corners but edge `{edge_id}` does not set corner_radius_in/corner_radius_px.")


def validate_local_motif_contract(
    scene: dict[str, Any],
    nodes_by_id: dict[str, dict],
    warnings: list[str],
    errors: list[str],
    strict_contract: bool = False,
) -> None:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    exact_mode = exact_mode_from_metadata(metadata)
    if not exact_mode:
        return

    def contract_issue(message: str) -> None:
        if strict_contract:
            errors.append(message)
        else:
            warnings.append(message)

    local_motifs = metadata.get("local_motifs")
    if local_motifs is not None and not isinstance(local_motifs, list):
        contract_issue("metadata.local_motifs should be an array of local motif grammar contracts.")
    if isinstance(local_motifs, list):
        for index, motif in enumerate(local_motifs):
            if not isinstance(motif, dict):
                contract_issue(f"metadata.local_motifs[{index}] should be an object.")
                continue
            motif_id = str(motif.get("id", motif.get("name", f"motif_{index}"))).strip()
            motif_type = str(motif.get("motif_type", motif.get("type", ""))).strip()
            if not motif_type:
                contract_issue(f"metadata.local_motifs `{motif_id}` should declare motif_type.")
            if not motif.get("source_bbox_px"):
                contract_issue(f"metadata.local_motifs `{motif_id}` should record source_bbox_px for local crop review.")
            if motif_type == "attention_score_motif" and not motif.get("required_arrow_plan_ids"):
                contract_issue(f"metadata.local_motifs `{motif_id}` should list required_arrow_plan_ids for Q/K-score/value connectors.")

    for node_id, node in nodes_by_id.items():
        node_type = str(node.get("type", ""))
        if not node_type.endswith("_motif"):
            continue
        motif_edges = node_motif_edges(node)
        if node_type == "attention_score_motif" and not motif_edges:
            contract_issue(
                f"Motif node `{node_id}` is attention_score_motif but has no motif_edges; expose internal operator/grid connectors with arrow_plan_id."
            )
        for motif_edge in motif_edges:
            motif_edge_id = str(motif_edge.get("id", f"{node_id}.motif_edge"))
            if not edge_arrow_plan_id(motif_edge):
                contract_issue(f"Motif node `{node_id}` motif_edge `{motif_edge_id}` is missing arrow_plan_id.")


NON_RENDERED_OR_TINY_TYPES = {
    "page_background",
    "audit_region",
    "junction_point",
    "boundary_port",
    "bracket",
    "dimension_brace",
    "merge_bus",
    "multi_port_junction",
    "boundary_fanout",
}

TEXT_OVERFLOW_SKIP_TYPES = {
    "page_background",
    "audit_region",
    "group_container",
    "loss_region",
    "image_tile",
    "feature_map_banded",
    "feature_map_grid",
    "grid_matrix",
    "bracket",
    "dimension_brace",
    "merge_bus",
    "multi_port_junction",
    "boundary_fanout",
    "classifier_head",
    "wave_signal",
    "modality_spine",
    "math_vector",
    "math_text",
    "caption_block",
    "tfr_panel",
}


def visible_semantic_nodes(nodes_by_id: dict[str, dict], node_types_by_id: dict[str, str]) -> list[str]:
    return [
        node_id
        for node_id, node_type in node_types_by_id.items()
        if node_type not in CONTAINER_TYPES
        and node_type not in NON_RENDERED_OR_TINY_TYPES
        and not is_background_node(nodes_by_id[node_id])
    ]


def has_valid_box(node: dict[str, Any]) -> bool:
    return (
        all(isinstance(node.get(key), (int, float)) for key in ("x", "y", "w", "h"))
        and float(node.get("w", 0)) > 0
        and float(node.get("h", 0)) > 0
    )


def intersection_area(box_a: tuple[float, float, float, float], box_b: tuple[float, float, float, float]) -> float:
    left = max(box_a[0], box_b[0])
    top = max(box_a[1], box_b[1])
    right = min(box_a[2], box_b[2])
    bottom = min(box_a[3], box_b[3])
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def text_width_factor(char: str) -> float:
    if char.isspace():
        return 0.32
    if ord(char) > 255:
        return 0.92
    if char in "ilI.,'`|":
        return 0.28
    if char in "MW@#%&":
        return 0.78
    return 0.54


def estimate_text_box(text: str, font_size_pt: float) -> tuple[float, float]:
    lines = str(text).splitlines() or [str(text)]
    line_widths = [
        sum(text_width_factor(char) for char in line) * font_size_pt / 72.0
        for line in lines
    ]
    width = max(line_widths) if line_widths else 0.0
    height = max(1, len(lines)) * font_size_pt / 72.0 * 1.18
    return width, height


def tfr_panel_layout_issues(nodes_by_id: dict[str, dict], node_types_by_id: dict[str, str]) -> list[str]:
    issues: list[str] = []
    panels = [
        node
        for node_id, node in nodes_by_id.items()
        if node_types_by_id.get(node_id) in {"rounded_process", "process_box"}
        and has_valid_box(node)
        and any(token in node_semantic_text(node) for token in {"real", "generated", "tfr"})
    ]
    grids = [
        node
        for node_id, node in nodes_by_id.items()
        if node_types_by_id.get(node_id) == "grid_matrix"
        and has_valid_box(node)
        and ("tfr" in node_semantic_text(node) or any(point_in_box(node_center(node), node_box(panel), 0.02) for panel in panels))
    ]
    input_labels = [
        node
        for node_id, node in nodes_by_id.items()
        if node_types_by_id.get(node_id) == "text_block"
        and has_valid_box(node)
        and str(node.get("text", "")).strip().lower() == "input"
    ]

    for grid in grids:
        gx1, gy1, gx2, gy2 = node_box(grid)
        gcx, _ = node_center(grid)
        below_labels = [
            label
            for label in input_labels
            if node_box(label)[1] >= gy2
            and abs(node_center(label)[0] - gcx) <= max(float(grid["w"]), float(label["w"])) * 0.75
        ]
        if below_labels:
            label = min(below_labels, key=lambda item: node_box(item)[1] - gy2)
            gap = node_box(label)[1] - gy2
            if gap < 0.08:
                issues.append(
                    f"TFR grid `{grid.get('id')}` is only {gap:.3f} in above `Input`; "
                    "reserve a clear label gap or use a `tfr_panel`/container-local layout before final assembly."
                )

    role_grids: dict[str, dict] = {}
    for grid in grids:
        text = node_semantic_text(grid)
        if "real" in text:
            role_grids["real"] = grid
        if "generated" in text or "reconstructed" in text:
            role_grids["generated"] = grid
    if {"real", "generated"} <= set(role_grids):
        real = role_grids["real"]
        generated = role_grids["generated"]
        rw, rh = float(real["w"]), float(real["h"])
        gw, gh = float(generated["w"]), float(generated["h"])
        if max(abs(rw - gw), abs(rh - gh)) > 0.04 or abs(float(real["y"]) - float(generated["y"])) > 0.04:
            issues.append(
                f"Real/Generated TFR grids are not visually paired (`{real.get('id')}` vs `{generated.get('id')}`); "
                "match grid size, y-position, row/column count, and cell palette before tuning arrows."
            )

    return issues


def exact_text_route_overlap_warnings(
    route_points: list[tuple[float, float]],
    edge_id: str,
    edge: dict,
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
) -> list[str]:
    if edge.get("allow_text_overlap"):
        return []
    warnings: list[str] = []
    edge_endpoint_ids = {
        base_node_id(value)
        for value in (edge.get("from"), edge.get("to"))
        if isinstance(value, str) and base_node_id(value) in nodes_by_id
    }
    for text_node_id, text_node in nodes_by_id.items():
        if text_node_id in edge_endpoint_ids:
            continue
        if node_types_by_id.get(text_node_id) not in TEXT_ROUTE_OVERLAP_NODE_TYPES:
            continue
        if is_background_node(text_node) or not has_valid_box(text_node):
            continue
        text_value = str(text_node.get("text", text_node.get("label", text_node.get("lines", "")))).strip()
        if not text_value:
            continue
        text_box = expanded_box(node_box(text_node), 0.015)
        if any(segment_crosses_box(start, end, text_box, clearance=0.0) for start, end in zip(route_points, route_points[1:])):
            warnings.append(
                f"Edge `{edge_id}` crosses text/formula node `{text_node_id}`. Exact replicas should route around labels or move the label anchor; "
                "visual review treats line-through-text as a blocking/important defect."
            )
            break
    return warnings


def safe_node_style(
    node: dict[str, Any],
    component_map: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    try:
        _, style, _ = node_style(node, component_map, profile)
        return style
    except Exception:
        return node.get("style", {}) if isinstance(node.get("style"), dict) else {}


def validate_large_figure_discipline(
    scene: dict,
    nodes_by_id: dict[str, dict],
    node_types_by_id: dict[str, str],
    containers_by_node: dict[str, str | None],
    component_map: dict[str, Any],
    profile: dict[str, Any],
    warnings: list[str],
) -> None:
    nodes = list(nodes_by_id.values())
    edges = scene.get("edges", [])
    page = scene.get("page", {}) if isinstance(scene.get("page"), dict) else {}
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    visible_ids = visible_semantic_nodes(nodes_by_id, node_types_by_id)
    containers = [
        node
        for node in nodes
        if node_types_by_id.get(node.get("id")) in CONTAINER_TYPES
    ]
    page_width = float(page.get("width", 0) or 0)
    page_height = float(page.get("height", 0) or 0)
    aspect_ratio = page_width / page_height if page_height > 0 else 0
    complex_scene = (
        len(visible_ids) >= 32
        or len(edges) >= 35
        or (aspect_ratio >= 2.2 and len(visible_ids) >= 20)
    )

    if complex_scene:
        region_strategy = str(
            metadata.get("region_strategy", metadata.get("large_figure_strategy", ""))
        ).lower()
        if region_strategy not in {"region_first", "tiled_subscenes", "module_first", "section_first"}:
            warnings.append(
                f"Complex scene has {len(visible_ids)} visible nodes and {len(edges)} edges; "
                "set metadata.region_strategy to `region_first`, `tiled_subscenes`, or `module_first`, "
                "then build/review the figure module-by-module before whole-page assembly."
            )

        expected_regions = max(2, min(12, round(len(visible_ids) / 12)))
        if len(containers) < expected_regions:
            warnings.append(
                f"Complex scene has only {len(containers)} group/audit regions; "
                f"add roughly {expected_regions} logical `audit_region`/`group_container` areas so large figures "
                "are reviewed as smaller subscenes instead of one global layout."
            )

        covered_visible_ids = [
            node_id
            for node_id in visible_ids
            if containers_by_node.get(node_id)
        ]
        if visible_ids and len(covered_visible_ids) / len(visible_ids) < 0.75:
            warnings.append(
                f"Only {len(covered_visible_ids)}/{len(visible_ids)} visible nodes are assigned to a region. "
                "For large diagrams, bind nodes with explicit `container_id` or add invisible `audit_region` boxes."
            )

    children_by_container: dict[str, list[str]] = {}
    for node_id, container_id in containers_by_node.items():
        if container_id and node_id in visible_ids:
            children_by_container.setdefault(container_id, []).append(node_id)
    containers_by_id = {str(node.get("id")): node for node in containers if node.get("id")}
    for container_id, child_ids in sorted(children_by_container.items()):
        if len(child_ids) > 18:
            warnings.append(
                f"Region `{container_id}` contains {len(child_ids)} visible nodes; split it into smaller "
                "`audit_region` subregions or create a local subscene first, then assemble it into the full page."
            )
        container = containers_by_id.get(container_id)
        if container and has_valid_box(container):
            area = max(0.001, float(container["w"]) * float(container["h"]))
            density = len(child_ids) / area
            expected = container.get("expected_node_density", container.get("source_node_density"))
            if expected is not None:
                try:
                    expected_f = float(expected)
                    if expected_f > 0:
                        ratio = density / expected_f
                        if ratio < 0.55 or ratio > 1.85:
                            warnings.append(
                                f"Region `{container_id}` density {density:.2f} nodes/sq in differs from expected {expected_f:.2f}; "
                                "check source bbox/target bbox scale before tuning individual nodes."
                            )
                except (TypeError, ValueError):
                    warnings.append(f"Region `{container_id}` expected_node_density/source_node_density must be numeric.")
            if float(container["w"]) > 0 and float(container["h"]) > 0:
                container_ratio = float(container["w"]) / float(container["h"])
                source_ratio = container.get("source_aspect_ratio")
                source_bbox = container.get("source_bbox_px", container.get("source_bbox"))
                if source_ratio is None and isinstance(source_bbox, list) and len(source_bbox) == 4:
                    try:
                        bbox_w = abs(float(source_bbox[2]) - float(source_bbox[0]))
                        bbox_h = abs(float(source_bbox[3]) - float(source_bbox[1]))
                        if bbox_h > 0:
                            source_ratio = bbox_w / bbox_h
                    except (TypeError, ValueError):
                        source_ratio = None
                if source_ratio is not None:
                    try:
                        source_ratio_f = float(source_ratio)
                        if source_ratio_f > 0 and abs(container_ratio - source_ratio_f) / source_ratio_f > 0.22:
                            warnings.append(
                                f"Region `{container_id}` aspect {container_ratio:.2f} differs from source region {source_ratio_f:.2f}; "
                                "fix region bbox before local visual polishing."
                            )
                    except (TypeError, ValueError):
                        warnings.append(f"Region `{container_id}` source_aspect_ratio must be numeric.")
                elif complex_scene and container.get("type") != "audit_region":
                    warnings.append(
                        f"Region `{container_id}` has no source_bbox_px/source_aspect_ratio; visual review cannot distinguish source scale drift from renderer issues."
                    )

    font_sizes_by_type: dict[str, list[tuple[str, float]]] = {}
    for node_id in visible_ids:
        node = nodes_by_id[node_id]
        node_type = node_types_by_id.get(node_id, "")
        style = safe_node_style(node, component_map, profile)
        font_size = style.get("font_size_pt")
        if isinstance(font_size, (int, float)) and font_size > 0:
            font_sizes_by_type.setdefault(node_type, []).append((node_id, float(font_size)))
    for node_type, values in sorted(font_sizes_by_type.items()):
        if len(values) < 4:
            continue
        sizes = [size for _, size in values]
        if max(sizes) - min(sizes) > 3.0:
            smallest = [node_id for node_id, size in values if size == min(sizes)][:3]
            largest = [node_id for node_id, size in values if size == max(sizes)][:3]
            warnings.append(
                f"Font sizes for `{node_type}` vary from {min(sizes):.1f}pt to {max(sizes):.1f}pt "
                f"(small: {', '.join(smallest)}; large: {', '.join(largest)}). "
                "Large figures should keep each component family on a small role-based font scale."
            )

    overflow_warnings = 0
    for node_id in visible_ids:
        node = nodes_by_id[node_id]
        if not has_valid_box(node):
            continue
        node_type = node_types_by_id.get(node_id, "")
        if node_type in TEXT_OVERFLOW_SKIP_TYPES:
            continue
        text = str(node.get("text", node.get("symbol", ""))).strip()
        if not text:
            continue
        style = safe_node_style(node, component_map, profile)
        font_size = float(style.get("font_size_pt", 12) or 12)
        estimated_w, estimated_h = estimate_text_box(text, font_size)
        padding = float(style.get("text_padding_in", 0.05) or 0.05)
        available_w = max(0.0, float(node.get("w", 0)) - 2 * padding)
        available_h = max(0.0, float(node.get("h", 0)) - 2 * padding)
        if available_w and available_h and (estimated_w > available_w * 1.18 or estimated_h > available_h * 1.15):
            warnings.append(
                f"Text in node `{node_id}` may not fit ({estimated_w:.2f}x{estimated_h:.2f} in estimated "
                f"vs {available_w:.2f}x{available_h:.2f} in available). "
                "Wrap text, enlarge the node, or assign a smaller role font before rendering."
            )
            overflow_warnings += 1
            if overflow_warnings >= 8:
                warnings.append("Additional text-fit warnings suppressed; fix the listed nodes and rerun validation.")
                break

    overlap_warnings = 0
    overlap_ids = [
        node_id
        for node_id in visible_ids
        if has_valid_box(nodes_by_id[node_id])
        if node_types_by_id.get(node_id) not in {"text_block", "wave_signal"}
        and not nodes_by_id[node_id].get("allow_overlap")
    ]
    for index, node_id in enumerate(overlap_ids):
        node = nodes_by_id[node_id]
        box_a = node_box(node)
        area_a = max(0.0, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]))
        for other_id in overlap_ids[index + 1:]:
            other = nodes_by_id[other_id]
            if node.get("stack_id") and node.get("stack_id") == other.get("stack_id"):
                continue
            box_b = node_box(other)
            area_b = max(0.0, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]))
            overlap = intersection_area(box_a, box_b)
            if overlap <= 0:
                continue
            if min(area_a, area_b) > 0 and overlap / min(area_a, area_b) > 0.20:
                warnings.append(
                    f"Nodes `{node_id}` and `{other_id}` overlap by {overlap:.3f} sq in. "
                    "For intended overlays set `allow_overlap: true`; otherwise fix region-local coordinates."
                )
                overlap_warnings += 1
                if overlap_warnings >= 8:
                    warnings.append("Additional overlap warnings suppressed; fix the listed overlaps and rerun validation.")
                    return


def validate_scene(scene: dict, strict: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        scene = normalize_scene_coordinates(scene)
    except Exception as exc:
        errors.append(f"Coordinate normalization failed: {exc}")
    component_map = load_component_map()
    node_types = set(component_map["node_types"])
    edge_types = set(component_map["edge_types"])
    validate_fidelity_metadata(scene, warnings, errors=errors, strict_contract=strict)
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    exact_mode = exact_mode_from_metadata(metadata)

    required_top = ["version", "page", "nodes", "edges", "assets"]
    for key in required_top:
        if key not in scene:
            errors.append(f"Missing top-level key: {key}")

    page = scene.get("page", {})
    if not isinstance(page, dict):
        errors.append("`page` must be an object.")
    else:
        for dim in ("width", "height"):
            value = page.get(dim)
            if not isinstance(value, (int, float)) or value <= 0:
                errors.append(f"`page.{dim}` must be a positive number.")
        if page.get("origin") != "top-left":
            warnings.append("Recommended `page.origin` is `top-left`.")
        if page.get("units") != "in":
            warnings.append("Recommended `page.units` is `in`.")

    nodes = scene.get("nodes", [])
    edges = scene.get("edges", [])
    assets = scene.get("assets", [])

    if not isinstance(nodes, list):
        errors.append("`nodes` must be an array.")
        nodes = []
    if not isinstance(edges, list):
        errors.append("`edges` must be an array.")
        edges = []
    if not isinstance(assets, list):
        errors.append("`assets` must be an array.")
        assets = []

    node_ids: set[str] = set()
    node_types_by_id: dict[str, str] = {}
    nodes_by_id: dict[str, dict] = {}
    asset_ids: set[str] = set()
    edge_ids: set[str] = set()

    for asset in assets:
        asset_id = asset.get("id")
        if not asset_id:
            errors.append("Every asset must have an `id`.")
            continue
        if asset_id in asset_ids:
            errors.append(f"Duplicate asset id: {asset_id}")
        asset_ids.add(asset_id)
        if "path" not in asset:
            warnings.append(f"Asset `{asset_id}` has no `path`.")

    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            errors.append("Every node must have an `id`.")
            continue
        if node_id in node_ids:
            errors.append(f"Duplicate node id: {node_id}")
        node_ids.add(node_id)
        nodes_by_id[node_id] = node

        node_type = node.get("type")
        if node_type not in node_types:
            errors.append(f"Unsupported node type `{node_type}` for node `{node_id}`.")
        else:
            node_types_by_id[node_id] = node_type

        dimensions: dict[str, float] = {}
        for key in ("x", "y", "w", "h"):
            value = node.get(key)
            if not isinstance(value, (int, float)):
                errors.append(f"Node `{node_id}` is missing numeric `{key}`.")
            elif key in {"w", "h"} and value <= 0:
                errors.append(f"Node `{node_id}` has non-positive `{key}`.")
            elif isinstance(value, (int, float)):
                dimensions[key] = float(value)

        asset_ref = node.get("asset_ref")
        if asset_ref and asset_ref not in asset_ids:
            errors.append(f"Node `{node_id}` references missing asset `{asset_ref}`.")

        has_text = bool(str(node.get("text", node.get("symbol", ""))).strip())
        if node_type == "math_formula_group" and any(node.get(key) for key in ("left_text", "operator", "numerator", "denominator", "right_text", "fraction")):
            has_text = True
        if (
            node_type in {"process_box", "rounded_process"}
            and not has_text
            and (0 < dimensions.get("w", 1) < 0.06 or 0 < dimensions.get("h", 1) < 0.06)
        ):
            warnings.append(
                f"Node `{node_id}` is an ultra-thin `{node_type}` with no text; "
                "use `bracket` or an edge/connector instead of a fake line box."
            )
        if node_type == "process_box" and not has_text:
            style = node.get("style", {}) if isinstance(node.get("style"), dict) else {}
            if style.get("line_dash") in {"dash", "dot", "long_dash"}:
                warnings.append(
                    f"Node `{node_id}` is an empty dashed `process_box`; use `dashed_region` or `group_container` for visible annotation frames."
                )
        if node_type == "ellipse_node" and not has_text:
            lower_id = str(node_id).lower()
            if any(token in lower_id for token in {"outer", "loop", "cycle"}):
                warnings.append(
                    f"Node `{node_id}` looks like a visible cycle/outer loop frame. "
                    "If it encodes flow direction, rebuild it as `loop_arrow`/`curved_arrow`; "
                    "do not combine a passive ellipse with detached arrowheads."
                )

        if node_type in {"bracket", "dimension_brace"}:
            orientation = str(node.get("orientation", "right")).lower()
            if orientation not in {"left", "right", "up", "down"}:
                errors.append(
                    f"{node_type} `{node_id}` has unsupported orientation `{orientation}`."
                )
            tick_positions = node.get("tick_positions")
            if tick_positions is not None:
                if not isinstance(tick_positions, list):
                    errors.append(f"{node_type} `{node_id}` tick_positions must be an array.")
                else:
                    for index, tick in enumerate(tick_positions):
                        if not isinstance(tick, (int, float)) or not 0 <= float(tick) <= 1:
                            errors.append(
                                f"{node_type} `{node_id}` tick_positions[{index}] must be a number in [0, 1]."
                            )
            ratio_keys = ("waist_ratio", "curl_ratio", "neck_ratio")
            if node_type == "dimension_brace":
                ratio_keys = (
                    "terminal_indent_ratio",
                    "outer_bulge_ratio",
                    "waist_indent_ratio",
                    "neck_ratio",
                    "lobe_ratio",
                )
            for key in ratio_keys:
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or not 0 <= float(value) <= 1):
                    errors.append(f"{node_type} `{node_id}` {key} must be a number in [0, 1].")

        if node_type == "brace_merge":
            orientation = str(node.get("orientation", "right")).lower()
            if orientation not in {"left", "right", "up", "down"}:
                errors.append(f"Brace merge `{node_id}` has unsupported orientation `{orientation}`.")
            for key in ("waist_ratio", "curl_ratio", "neck_ratio", "curve_tightness"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or not 0 <= float(value) <= 1):
                    errors.append(f"Brace merge `{node_id}` {key} must be a number in [0, 1].")
            for key in ("waist_width_in", "tick_length_in"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or float(value) < 0):
                    errors.append(f"Brace merge `{node_id}` {key} must be a non-negative number.")
            tick_positions = node.get("tick_positions", node.get("port_positions"))
            if tick_positions is not None:
                if not isinstance(tick_positions, list):
                    errors.append(f"Brace merge `{node_id}` tick_positions/port_positions must be an array.")
                elif not all(isinstance(item, (int, float)) and 0 <= float(item) <= 1 for item in tick_positions):
                    errors.append(f"Brace merge `{node_id}` tick positions must be numbers in [0, 1].")

        if node_type == "concat_operator":
            orientation = str(node.get("orientation", "vertical")).lower()
            if orientation not in {"vertical", "v", "horizontal", "h"}:
                errors.append(f"Concat operator `{node_id}` orientation must be vertical or horizontal.")
            for key in ("tick_in", "gap_ratio"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or float(value) < 0):
                    errors.append(f"Concat operator `{node_id}` {key} must be a non-negative number.")
            glyph_mode = str(node.get("glyph_mode", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("glyph_mode", "bracket_pair"))).lower()
            if glyph_mode not in {
                "bracket_pair",
                "brackets",
                "stroke",
                "strokes",
                "boxed",
                "box",
                "square_box",
                "rect",
                "glyph",
                "text",
                "literal",
                "solid_bracket",
                "bold_bracket",
                "source_bracket",
                "paper_bracket",
            }:
                warnings.append(
                    f"Concat operator `{node_id}` uses unknown glyph_mode `{glyph_mode}`; expected bracket_pair, boxed, or glyph."
                )
            concat_size_tier = node.get("concat_size_tier", node.get("style", {}).get("concat_size_tier") if isinstance(node.get("style"), dict) else None)
            if concat_size_tier is not None and str(concat_size_tier).lower() not in CONCAT_SIZE_TIERS:
                errors.append(f"Concat operator `{node_id}` has unsupported concat_size_tier `{concat_size_tier}`.")
            if exact_mode and not node_or_style_has_key(node, "glyph_mode"):
                warnings.append(
                    f"Concat operator `{node_id}` has no explicit glyph_mode. "
                    "Use `source_bracket`, bracket_pair, or text glyph explicitly so concat does not fall back to a generic box-like mark."
                )
            if exact_mode and not any(node_or_style_has_key(node, key) for key in ("concat_size_tier", "tick_in", "gap_ratio")):
                warnings.append(
                    f"Concat operator `{node_id}` has no explicit bracket sizing contract. "
                    "Set `concat_size_tier` or explicit tick/gap values before coordinate polishing."
                )

        if node_type == "junction_point":
            if dimensions.get("w", 0.0) > 0.2 or dimensions.get("h", 0.0) > 0.2:
                warnings.append(
                    f"Junction point `{node_id}` is larger than usual; keep merge/fan points tiny."
                )

        if node_type == "multi_port_junction":
            orientation = str(node.get("orientation", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("orientation", "vertical"))).lower()
            if orientation not in {"vertical", "v", "horizontal", "h", "row"}:
                errors.append(f"Multi-port junction `{node_id}` orientation must be vertical or horizontal.")
            ports = node.get("ports")
            if ports is not None:
                if not isinstance(ports, list):
                    errors.append(f"Multi-port junction `{node_id}` ports must be an array.")
                else:
                    for index, port in enumerate(ports):
                        if not isinstance(port, dict):
                            errors.append(f"Multi-port junction `{node_id}` ports[{index}] must be an object.")
                            continue
                        position = port.get("position", 0.5)
                        if not isinstance(position, (int, float)):
                            errors.append(f"Multi-port junction `{node_id}` ports[{index}].position must be numeric.")
                        side = str(port.get("side", "")).lower()
                        if side and side not in {"left", "right", "top", "bottom"}:
                            errors.append(f"Multi-port junction `{node_id}` ports[{index}].side is unsupported.")
                        length = port.get("length_in", port.get("port_length_in"))
                        if length is not None and (not isinstance(length, (int, float)) or float(length) < 0):
                            errors.append(f"Multi-port junction `{node_id}` ports[{index}].length_in must be non-negative.")
            positions = node.get("port_positions", node.get("positions"))
            if positions is not None:
                if not isinstance(positions, list):
                    errors.append(f"Multi-port junction `{node_id}` port_positions/positions must be an array.")
                elif not all(isinstance(item, (int, float)) for item in positions):
                    errors.append(f"Multi-port junction `{node_id}` port_positions/positions must contain only numbers.")
            for key in ("port_length_in", "marker_size_in"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or float(value) < 0):
                    errors.append(f"Multi-port junction `{node_id}` {key} must be a non-negative number.")

        if node_type == "group_container":
            shape = str(node.get("shape", node.get("container_shape", "rectangle"))).lower()
            if shape not in {"rectangle", "rect", "rounded", "round_rect", "round-rect", "capsule", "pill"}:
                errors.append(f"Group container `{node_id}` has unsupported shape `{shape}`.")
            for key in ("corner_radius_in", "max_rounding_in"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Group container `{node_id}` {key} must be a non-negative number.")

        if node_type == "dashed_region":
            shape = str(node.get("shape", node.get("container_shape", "rectangle"))).lower()
            if shape not in {"rectangle", "rect", "rounded", "round_rect", "round-rect", "capsule", "pill"}:
                errors.append(f"Dashed region `{node_id}` has unsupported shape `{shape}`.")
            if node.get("text"):
                warnings.append(
                    f"Dashed region `{node_id}` should usually keep labels as separate `text_block` nodes "
                    "so the frame does not compete with internal arrows."
                )
            for key in ("corner_radius_in", "max_rounding_in"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Dashed region `{node_id}` {key} must be a non-negative number.")

        if node_type == "loss_region":
            shape = str(node.get("shape", node.get("container_shape", "rectangle"))).lower()
            if shape not in {"rectangle", "rect", "rounded", "round_rect", "round-rect", "capsule", "pill"}:
                errors.append(f"Loss region `{node_id}` has unsupported shape `{shape}`.")
            formulas = node.get("formulas", node.get("lines"))
            if formulas is not None and not isinstance(formulas, (list, str)):
                errors.append(f"Loss region `{node_id}` formulas/lines must be an array or string.")
            formula_lines = formulas if isinstance(formulas, list) else str(formulas or "").splitlines()
            if any(text_has_compact_loss_notation(str(line)) for line in formula_lines):
                warnings.append(
                    f"Loss region `{node_id}` uses compact loss notation such as `Ladv`/`Lrec`; normalize formulas to `L_adv`/`L_rec` before rendering."
                )
            title = str(node.get("title", "")).strip()
            if title and has_valid_box(node):
                title_position = str(
                    node.get(
                        "title_position",
                        (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("title_position", "header_cutout"),
                    )
                ).lower()
                title_font = float(
                    (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get(
                        "title_font_size_pt",
                        node.get("title_font_size_pt", 15),
                    )
                )
                title_width, _ = estimate_text_box(title.replace("\n", " "), title_font)
                if title_position not in {"header_cutout", "inside", "top_inside", "inner"}:
                    warnings.append(
                        f"Loss region `{node_id}` title is not protected by a header/inside layout; use `title_position: \"header_cutout\"` "
                        "or `inside` so the dashed frame does not cross the title."
                    )
                if title_width > float(node["w"]) * 1.85:
                    warnings.append(
                        f"Loss region `{node_id}` title is much wider than its frame; enlarge the frame or split the title line before rendering."
                    )
            if node.get("text") and not node.get("title"):
                warnings.append(
                    f"Loss region `{node_id}` should use `title` and `formulas` fields instead of generic text."
                )
            for key in ("title_h_in", "formula_pad_x_in", "formula_pad_y_in"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Loss region `{node_id}` {key} must be a non-negative number.")

        if node_type == "text_block" and has_text:
            text = str(node.get("text", ""))
            if text_has_raw_loss_subscript(text):
                warnings.append(
                    f"Text block `{node_id}` contains raw underscore loss notation. "
                    "Use `math_text` or explicit text runs so `L_adv`/`L_rec` render with subscript-like formatting."
                )
            elif text_has_hat_notation(text):
                warnings.append(
                    f"Text block `{node_id}` contains hat notation. Use `math_text` so the hat is rendered as a stable editable accent, "
                    "not lost by font substitution or Visio text fitting."
                )
            elif text_has_generic_subscript_label(text):
                fit = str((node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("text_fit", node.get("text_fit", ""))).lower()
                if fit not in {"math_label", "single_line", "no_wrap", "nowrap"}:
                    warnings.append(
                        f"Text block `{node_id}` contains underscore subscript-like notation. "
                        "Use `math_text` with `text_fit: \"math_label\"`, or explicitly set single-line text fitting for compact labels."
                    )

        if node_type == "math_label_box":
            text = str(node.get("text", node.get("label", ""))).strip()
            if not text:
                errors.append(f"Math label box `{node_id}` needs `text` or `label`.")
            shape = str(node.get("shape", "rect")).lower()
            if shape not in {"rect", "rectangle", "round_rect", "rounded", "oval", "ellipse", "circle"}:
                errors.append(f"Math label box `{node_id}` has unsupported shape `{shape}`.")
            for key in (
                "label_inset_in",
                "label_font_size_pt",
                "label_min_font_size_pt",
                "subscript_scale",
                "subscript_offset_in",
                "fragment_pad_in",
                "subscript_pad_in",
                "subscript_box_pad_in",
            ):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Math label box `{node_id}` {key} must be a non-negative number.")

        if node_type == "math_text":
            text = str(node.get("text", "")).strip()
            lines = node.get("lines")
            if not text and not lines:
                errors.append(f"Math text `{node_id}` needs `text` or `lines`.")
            if lines is not None and not isinstance(lines, list):
                errors.append(f"Math text `{node_id}` lines must be an array.")
            style_math_render_mode = (
                node.get("style", {}).get("math_render_mode")
                if isinstance(node.get("style"), dict)
                else None
            )
            math_render_mode_value = node.get("math_render_mode") or node.get("render_mode") or style_math_render_mode
            math_render_mode = str(math_render_mode_value).lower() if math_render_mode_value is not None else ""
            if math_render_mode and math_render_mode not in {"fragments", "compact_unicode", "unicode", "single_box", "single_text", "plain_compact"}:
                errors.append(f"Math text `{node_id}` has unsupported math_render_mode `{math_render_mode}`.")
            math_lines = lines if isinstance(lines, list) else text.splitlines()
            if any(text_has_compact_loss_notation(str(line)) for line in math_lines):
                warnings.append(
                    f"Math text `{node_id}` uses compact loss notation such as `Ladv`/`Lrec`; normalize to `L_adv`/`L_rec`."
                )
            if any(text_has_hat_notation(str(line)) for line in math_lines):
                style_render_mode_value = (
                    (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("math_render_mode")
                )
                render_mode = math_render_mode or (str(style_render_mode_value).lower() if style_render_mode_value is not None else "")
                if render_mode in {"compact_unicode", "unicode", "single_box", "single_text", "plain_compact"}:
                    warnings.append(
                        f"Math text `{node_id}` contains hat notation; renderer will force fragment mode so the hat accent is not dropped."
                    )
            if math_render_mode in {"compact_unicode", "unicode", "single_box", "single_text", "plain_compact"} and any(
                re.search(r"[A-Za-z]_([A-Za-z]{2,}|[A-Z0-9_]{2,})", str(line))
                for line in math_lines
            ):
                warnings.append(
                    f"Math text `{node_id}` uses compact/unicode math mode for a word-like subscript. "
                    "Prefer fragment rendering for labels such as `P_RGB`, `q_hrrp`, or `f_fused` so the subscript stays attached and legible."
                )
            for key in (
                "line_gap_in",
                "subscript_scale",
                "subscript_offset_in",
                "segment_gap_in",
                "fragment_pad_in",
                "subscript_pad_in",
                "subscript_box_pad_in",
                "padding_in",
                "prime_scale",
                "prime_tuck_in",
                "prime_box_pad_in",
                "prime_offset_y_in",
            ):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Math text `{node_id}` {key} must be a non-negative number.")
            for key in ("auto_compact_math",):
                value = node.get(key)
                if value is not None and not isinstance(value, bool):
                    warnings.append(f"Math text `{node_id}` {key} should be boolean.")
            if text and re.search(r"\b[A-Za-z][A-Za-z0-9]+_[A-Za-z0-9_]+", text):
                warnings.append(
                    f"Math text `{node_id}` starts an underscored label with a multi-letter base. "
                    "For labels such as `f_tf`, `g_hrrp`, and `f_fused`, keep only the visible variable as the base "
                    "and the rest as subscript; otherwise Visio exports can look like superscript fragments."
                )

        if node_type == "tfr_panel":
            for key in ("rows", "cols"):
                value = node.get(key, 4 if key == "rows" else 5)
                if not isinstance(value, int) or value <= 0:
                    errors.append(f"TFR panel `{node_id}` {key} must be a positive integer.")
            if not (node.get("title") or node.get("text")):
                warnings.append(f"TFR panel `{node_id}` should set a visible title such as `Real\\nTFR` or `Generated`.")
            cells = node.get("colored_cells", node.get("cells"))
            if cells is not None and not isinstance(cells, list):
                errors.append(f"TFR panel `{node_id}` colored_cells/cells must be an array.")
            for key in ("grid_w", "grid_h", "grid_x", "grid_y", "input_y", "input_gap_in"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"TFR panel `{node_id}` {key} must be a non-negative number.")

        if node_type == "audit_region":
            if node.get("style") and isinstance(node.get("style"), dict):
                line = node["style"].get("line")
                fill = node["style"].get("fill")
                if line not in {None, "none"} or fill not in {None, "none"}:
                    warnings.append(
                        f"Audit region `{node_id}` is intended to be invisible; use `group_container` for visible frames."
                    )

        if node_type == "operator_node" and not has_text:
            warnings.append(
                f"Operator node `{node_id}` has no text; use symbols such as +, x, or tensor product to preserve paper topology."
            )
        if node_type == "operator_node":
            if dimensions.get("w") and dimensions.get("h") and abs(dimensions["w"] - dimensions["h"]) > 0.04:
                warnings.append(
                    f"Operator node `{node_id}` is not square; renderer will center a circle inside the box, but exact replicas should use w ~= h."
                )
            operator_shape = str(node.get("operator_shape", node.get("shape", ""))).lower()
            if operator_shape and operator_shape not in {"circle", "oval", "ellipse", "none", "text", "label", "rect", "rectangle", "box"}:
                errors.append(f"Operator node `{node_id}` has unsupported operator_shape/shape `{operator_shape}`.")
            symbol_text = str(node.get("symbol", node.get("text", ""))).strip()
            if len(symbol_text) > 1 and not (node.get("symbol_text_fit") or (isinstance(node.get("style"), dict) and node["style"].get("symbol_text_fit"))):
                warnings.append(
                    f"Operator node `{node_id}` has a multi-character symbol; set `symbol_text_fit: \"single_line\"` and tune symbol_box_* if the source shows a compact operator."
                )
            for key in (
                "symbol_font_size_pt",
                "symbol_inset_in",
                "symbol_offset_x_in",
                "symbol_offset_y_in",
                "symbol_box_w_in",
                "symbol_box_width_in",
                "symbol_box_h_in",
                "symbol_box_height_in",
                "symbol_min_font_size_pt",
                "symbol_text_margin_in",
            ):
                value = node.get(key)
                if value is not None and not isinstance(value, (int, float)):
                    errors.append(f"Operator node `{node_id}` {key} must be numeric.")
            operator_size_tier = node.get("operator_size_tier", node.get("style", {}).get("operator_size_tier") if isinstance(node.get("style"), dict) else None)
            if operator_size_tier is not None and str(operator_size_tier).lower() not in OPERATOR_SIZE_TIERS:
                errors.append(f"Operator node `{node_id}` has unsupported operator_size_tier `{operator_size_tier}`.")
            if exact_mode and not any(
                node_or_style_has_key(node, key)
                for key in ("operator_size_tier", "symbol_font_size_pt", "symbol_box_w_in", "symbol_box_h_in")
            ):
                warnings.append(
                    f"Operator node `{node_id}` has no explicit paper-operator sizing contract. "
                    "Set `operator_size_tier` or explicit symbol box/font size so plus/minus/multiply glyphs do not drift."
                )

        if node_type == "boundary_port":
            if dimensions.get("w", 0.0) > 0.22 or dimensions.get("h", 0.0) > 0.22:
                warnings.append(
                    f"Boundary port `{node_id}` is larger than usual; keep ports small and use labels separately."
                )

        if node_type == "wave_signal":
            samples = node.get("samples")
            if samples is not None:
                if not isinstance(samples, list) or not samples:
                    errors.append(f"Wave signal `{node_id}` samples must be a non-empty numeric array.")
                elif not all(isinstance(item, (int, float)) for item in samples):
                    errors.append(f"Wave signal `{node_id}` samples must contain only numbers.")
            cycles = node.get("cycles")
            if cycles is not None and (not isinstance(cycles, (int, float)) or cycles <= 0):
                errors.append(f"Wave signal `{node_id}` cycles must be a positive number.")

        if node_type == "classifier_head":
            orientation = str(node.get("orientation", "horizontal")).lower()
            if orientation not in {"horizontal", "h", "vertical", "v"}:
                errors.append(f"Classifier head `{node_id}` orientation must be horizontal or vertical.")
            blocks = node.get("blocks", node.get("labels", ["AvgPool", "Linear"]))
            if not isinstance(blocks, list) or not blocks:
                errors.append(f"Classifier head `{node_id}` blocks/labels must be a non-empty array.")
            fanout_count = node.get("fanout_count")
            if fanout_count is not None and (not isinstance(fanout_count, int) or fanout_count < 0):
                errors.append(f"Classifier head `{node_id}` fanout_count must be a non-negative integer.")
            for key in ("block_gap_in", "vertical_block_gap_in", "block_width_in", "block_height_in"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Classifier head `{node_id}` {key} must be a non-negative number.")
            output_mode = str(node.get("output_mode", "")).lower()
            if output_mode and output_mode not in {"none", "internal_fanout", "boundary", "boundary_fanout", "container_boundary", "external"}:
                errors.append(f"Classifier head `{node_id}` has unsupported output_mode `{output_mode}`.")
            if output_mode in {"boundary", "boundary_fanout", "container_boundary", "external"} and fanout_count:
                warnings.append(
                    f"Classifier head `{node_id}` uses boundary output mode; draw output branches with `boundary_fanout`, not internal fanout_count."
                )

        if node_type == "layer_sequence":
            orientation = str(node.get("orientation", "horizontal")).lower()
            if orientation not in LAYER_SEQUENCE_ORIENTATIONS:
                errors.append(
                    f"Layer sequence `{node_id}` orientation must be horizontal/horizontal_bars or vertical/vertical_stack."
                )
            blocks = node.get("blocks", node.get("labels"))
            if not isinstance(blocks, list) or not blocks:
                errors.append(f"Layer sequence `{node_id}` blocks/labels must be a non-empty array.")
            elif len(blocks) > 10:
                warnings.append(
                    f"Layer sequence `{node_id}` has {len(blocks)} blocks; verify the source really shows this many visible internal layers."
                )
            block_style_raw = node.get("block_style_mode")
            if block_style_raw is None and isinstance(node.get("style"), dict):
                block_style_raw = node.get("style", {}).get("block_style_mode")
            block_style_mode = str(block_style_raw or "").lower()
            if block_style_mode in {"none", "default", "auto"}:
                block_style_mode = ""
            if block_style_mode and block_style_mode not in {
                "flat_colored",
                "colored_flat",
                "simple_colored",
                "white_capsule",
                "capsule_white",
                "white",
                "paper_capsule",
                "paper_vertical_strip",
                "vertical_strip",
                "rounded_strip",
                "paper_strip",
                "tall_rounded",
                "colored_paper_strip",
                "colored_vertical_strip",
                "paper_colored_strip",
                "white_cuboid",
                "paper_cuboid",
                "paper_vertical_cuboid",
                "white_3d",
                "paper_3d_vertical_strip",
                "source_3d_strip",
                "cuboid",
                "cuboid_layers",
                "3d",
            }:
                errors.append(f"Layer sequence `{node_id}` has unsupported block_style_mode `{block_style_mode}`.")
            for key in (
                "padding_in",
                "padding_x_in",
                "padding_y_in",
                "padding_left_in",
                "padding_right_in",
                "padding_top_in",
                "padding_bottom_in",
                "content_padding_left_in",
                "content_padding_right_in",
                "content_padding_top_in",
                "content_padding_bottom_in",
                "title_h_in",
                "title_area_ratio",
                "title_gap_in",
                "block_gap_in",
                "block_width_in",
                "block_height_in",
                "block_rounding_in",
                "block_text_angle_deg",
                "block_depth_x_in",
                "block_depth_y_in",
                "title_baseline_offset_in",
            ):
                value = node.get(key)
                if value is not None and not isinstance(value, (int, float)):
                    errors.append(f"Layer sequence `{node_id}` {key} must be numeric.")
            title_align = node.get("title_align")
            if title_align is not None and not isinstance(title_align, (int, float)):
                errors.append(f"Layer sequence `{node_id}` title_align must be numeric/alignment-like.")
            for key in ("content_align_x", "content_align_y"):
                value = node.get(key)
                if value is not None and not isinstance(value, str):
                    errors.append(f"Layer sequence `{node_id}` {key} must be a string such as left/center/right or top/center/bottom.")
            block_fills = node.get("block_fills", node.get("style", {}).get("block_fills") if isinstance(node.get("style"), dict) else None)
            if block_fills is not None and (not isinstance(block_fills, list) or not block_fills):
                errors.append(f"Layer sequence `{node_id}` block_fills must be a non-empty array when provided.")
            if isinstance(block_fills, list) and block_fills and block_style_mode in {
                "paper_vertical_strip",
                "vertical_strip",
                "rounded_strip",
                "paper_strip",
                "tall_rounded",
                "white_cuboid",
                "paper_cuboid",
                "paper_vertical_cuboid",
                "white_3d",
                "paper_3d_vertical_strip",
                "source_3d_strip",
            }:
                block_fill_policy = str(node.get("block_fill_policy", node.get("style", {}).get("block_fill_policy") if isinstance(node.get("style"), dict) else "")).lower()
                if block_fill_policy not in {"white", "ignore", "block_fill", "fixed"} and not node.get("ignore_block_fills"):
                    warnings.append(
                        f"Layer sequence `{node_id}` provides block_fills but uses white layer mode `{block_style_mode}`; set `block_fill_policy: \"white\"` if source bars are white, or use `colored_paper_strip` if source bars are colored."
                    )
            orientation = str(node.get("orientation", "horizontal")).lower()
            style_dict = node.get("style", {}) if isinstance(node.get("style"), dict) else {}
            block_angle = node.get("block_text_angle_deg", style_dict.get("block_text_angle_deg"))
            if block_angle is not None and isinstance(block_angle, (int, float)):
                if orientation in LAYER_SEQUENCE_VERTICAL_ORIENTATIONS and abs((float(block_angle) % 180) - 90) <= 1e-3:
                    warnings.append(
                        f"Layer sequence `{node_id}` is a vertical/row stack but uses 90-degree block text. "
                        "If the source shows stacked horizontal rows, set `block_text_angle_deg: 0` so labels stay readable."
                    )
            if block_style_mode in {"colored_paper_strip", "colored_vertical_strip", "paper_colored_strip", "flat_colored", "colored_flat", "simple_colored"}:
                if not isinstance(block_fills, list) or not block_fills:
                    warnings.append(
                        f"Layer sequence `{node_id}` uses colored block mode but has no block_fills; visual review may see white/blank strips instead of source-colored layer bars."
                    )
                if node.get("ignore_block_fills") and str(node.get("block_fill_policy", "")).lower() not in {"preserve", "source", "source_colors", "colored", "block_fills", "fills"}:
                    warnings.append(
                        f"Layer sequence `{node_id}` uses colored block mode with ignore_block_fills; renderer preserves colors, but remove ignore_block_fills or set `block_fill_policy: \"preserve\"` to document source-colored bars."
                    )
            title = str(node.get("title", node.get("text", ""))).strip()
            if title and has_valid_box(node):
                title_font = float(node.get("title_font_size_pt", style_dict.get("title_font_size_pt", style_dict.get("font_size_pt", 15))) or 15)
                title_h_value = node.get("title_h_in", style_dict.get("title_h_in"))
                title_area_ratio = node.get("title_area_ratio", style_dict.get("title_area_ratio"))
                if isinstance(title_h_value, (int, float)):
                    title_h = float(title_h_value)
                elif isinstance(title_area_ratio, (int, float)):
                    title_h = float(node["h"]) * max(0.0, min(0.5, float(title_area_ratio)))
                else:
                    title_h = min(float(node["h"]) * 0.26, 0.42)
                _, estimated_title_h = estimate_text_box(title.replace("\n", " "), title_font)
                if title_h < estimated_title_h * 0.90:
                    warnings.append(
                        f"Layer sequence `{node_id}` title area is likely too short for its title font. Increase title_h_in/title_area_ratio or reduce title font before polishing block geometry."
                    )
            if exact_mode and isinstance(blocks, list) and len(blocks) >= 4:
                if not any(
                    node_or_style_has_key(node, key)
                    for key in ("block_gap_in", "padding_in", "padding_left_in", "padding_right_in", "content_padding_left_in", "content_padding_right_in")
                ):
                    warnings.append(
                        f"Layer sequence `{node_id}` has repeated strips but no explicit density spacing contract. "
                        "Write block gap and padding explicitly instead of inheriting generic defaults."
                    )
                if title and not any(node_or_style_has_key(node, key) for key in ("title_h_in", "title_area_ratio")):
                    warnings.append(
                        f"Layer sequence `{node_id}` has a title but no explicit title-band height contract. "
                        "Lock the title area before adjusting inner strip geometry."
                    )
                if not any(node_or_style_has_key(node, key) for key in ("density_mode", "dense")):
                    warnings.append(
                        f"Layer sequence `{node_id}` has repeated strips but no explicit density_mode/dense flag. "
                        "Document whether the source region is compact or loose."
                    )
                if not any(node_or_style_has_key(node, key) for key in ("block_rounding_in", "block_shadow")):
                    warnings.append(
                        f"Layer sequence `{node_id}` has no explicit strip rounding/shadow contract. "
                        "Repeated strip modules should not rely only on profile defaults in strict replica mode."
                    )

        if node_type == "boundary_fanout":
            side = str(node.get("side", "right")).lower()
            if side not in {"left", "right", "top", "bottom"}:
                errors.append(f"Boundary fanout `{node_id}` has unsupported side `{side}`.")
            branch_count = node.get("branch_count")
            positions = node.get("branch_positions", node.get("positions"))
            if branch_count is not None and (not isinstance(branch_count, int) or branch_count <= 0):
                errors.append(f"Boundary fanout `{node_id}` branch_count must be a positive integer.")
            if positions is not None:
                if not isinstance(positions, list) or not positions:
                    errors.append(f"Boundary fanout `{node_id}` branch_positions must be a non-empty numeric array.")
                elif not all(isinstance(item, (int, float)) for item in positions):
                    errors.append(f"Boundary fanout `{node_id}` branch_positions must contain only numbers.")
            if not node.get("container_id"):
                warnings.append(
                    f"Boundary fanout `{node_id}` has no container_id; bind it to the source group_container for faithful frame-edge arrows."
                )

        if node_type in {"stacked_process", "stacked_token"}:
            layers = node.get("layers", node.get("style", {}).get("layers", 4))
            if not isinstance(layers, int) or layers <= 0:
                errors.append(f"Stacked node `{node_id}` must have positive integer `layers`.")

        if node_type == "tensor_stack":
            layers = node.get("layers", node.get("style", {}).get("layers", 5) if isinstance(node.get("style"), dict) else 5)
            if not isinstance(layers, int) or layers <= 0:
                errors.append(f"Tensor stack `{node_id}` must have positive integer `layers`.")
            stack_render_mode = str(node.get("stack_render_mode", node.get("render_mode", node.get("style", {}).get("stack_render_mode") if isinstance(node.get("style"), dict) else ""))).lower()
            if stack_render_mode and stack_render_mode not in {
                "cuboids",
                "thin_sheets",
                "sheets",
                "front_sheets",
                "flat_sheets",
                "slanted_sheets",
                "thin_slabs",
                "paper_sheets",
                "parallelogram_sheets",
                "oblique_slabs",
                "slabs",
                "perspective_slabs",
                "paper_3d",
                "feature_cuboids",
                "thick_cuboids",
                "feature_stack",
                "paper_feature_stack",
                "thick_feature_map",
                "thin_feature_slabs",
                "thin_feature_stack",
                "layered_slabs",
                "source_thin_slabs",
                "paper_thin_feature",
            }:
                errors.append(f"Tensor stack `{node_id}` has unsupported stack_render_mode `{stack_render_mode}`.")
            for key in ("depth_x_in", "depth_y_in", "layer_dx_in", "layer_dy_in", "layer_fill_delta", "sheet_line_weight_pt", "skew_x_in", "sheet_scale", "depth_scale", "min_layer_shift_in"):
                value = node.get(key, node.get("style", {}).get(key) if isinstance(node.get("style"), dict) else None)
                if value is not None and not isinstance(value, (int, float)):
                    errors.append(f"Tensor stack `{node_id}` {key} must be numeric.")
            for key in ("depth_is_relative", "depth_x_in_relative", "depth_y_in_relative"):
                value = node.get(key, node.get("style", {}).get(key) if isinstance(node.get("style"), dict) else None)
                if value is not None and not isinstance(value, bool):
                    warnings.append(f"Tensor stack `{node_id}` {key} should be boolean.")
            perspective_raw = node.get("perspective_mode", node.get("style", {}).get("perspective_mode") if isinstance(node.get("style"), dict) else "")
            perspective_mode = "" if perspective_raw in {None, ""} else str(perspective_raw).lower()
            if perspective_mode and perspective_mode not in TENSOR_PERSPECTIVE_MODES:
                errors.append(f"Tensor stack `{node_id}` has unsupported perspective_mode `{perspective_mode}`.")
            if has_valid_box(node):
                width = float(node["w"])
                height = float(node["h"])
                depth_x = node.get("depth_x_in", node.get("style", {}).get("depth_x_in") if isinstance(node.get("style"), dict) else None)
                depth_y = node.get("depth_y_in", node.get("style", {}).get("depth_y_in") if isinstance(node.get("style"), dict) else None)
                if isinstance(depth_x, (int, float)) and width > 0 and abs(float(depth_x)) / width > 0.42:
                    warnings.append(
                        f"Tensor stack `{node_id}` depth_x_in is large relative to width ({abs(float(depth_x)) / width:.2f}); check perspective or source bbox before tuning colors."
                    )
                if isinstance(depth_y, (int, float)) and height > 0 and abs(float(depth_y)) / height > 0.42:
                    warnings.append(
                        f"Tensor stack `{node_id}` depth_y_in is large relative to height ({abs(float(depth_y)) / height:.2f}); check perspective or source bbox before tuning colors."
                    )
                if perspective_mode in {"flat", "front"} and stack_render_mode in {"feature_cuboids", "thick_cuboids", "feature_stack", "paper_feature_stack", "thick_feature_map"}:
                    warnings.append(
                        f"Tensor stack `{node_id}` asks for flat/front perspective but uses thick cuboid render mode. If the source looks nearly front-on, switch to thin slabs/sheets."
                    )
            if exact_mode and not any(node_or_style_has_key(node, key) for key in ("stack_render_mode", "render_mode")):
                warnings.append(
                    f"Tensor stack `{node_id}` has no explicit shape-family contract. "
                    "Choose thin slabs, thick cuboids, slanted sheets, or flat sheets explicitly before tweaking depth."
                )
            if exact_mode and not node_or_style_has_key(node, "perspective_mode") and not node.get("source_bbox_px", node.get("source_bbox")):
                warnings.append(
                    f"Tensor stack `{node_id}` has no explicit perspective_mode/source bbox contract. "
                    "3D thickness should not drift as a hidden default in strict replica mode."
                )

        if node_type == "grid_matrix":
            for key in ("rows", "cols"):
                value = node.get(key)
                if not isinstance(value, int) or value <= 0:
                    errors.append(f"Grid matrix `{node_id}` must have positive integer `{key}`.")

            rows = node.get("rows")
            cols = node.get("cols")
            index_base = int(node.get("index_base", 0))
            cells = node.get("colored_cells", node.get("cells", []))
            if not isinstance(cells, list):
                errors.append(f"Grid matrix `{node_id}` `colored_cells` must be an array.")
            else:
                for index, cell in enumerate(cells):
                    if isinstance(cell, dict):
                        row = cell.get("row")
                        col = cell.get("col")
                    elif isinstance(cell, list) and len(cell) >= 2:
                        row = cell[0]
                        col = cell[1]
                    else:
                        errors.append(f"Grid matrix `{node_id}` cell {index} is invalid.")
                        continue

                    if not isinstance(row, int) or not isinstance(col, int):
                        errors.append(f"Grid matrix `{node_id}` cell {index} row/col must be integers.")
                        continue
                    zero_row = row - index_base
                    zero_col = col - index_base
                    if isinstance(rows, int) and not 0 <= zero_row < rows:
                        errors.append(f"Grid matrix `{node_id}` cell {index} row is out of range.")
                    if isinstance(cols, int) and not 0 <= zero_col < cols:
                        errors.append(f"Grid matrix `{node_id}` cell {index} col is out of range.")

        if node_type == "token_grid":
            for key in ("rows", "cols"):
                value = node.get(key)
                if not isinstance(value, int) or value <= 0:
                    errors.append(f"Token grid `{node_id}` must have positive integer `{key}`.")
            rows = node.get("rows")
            cols = node.get("cols")
            index_base = int(node.get("index_base", 0))
            cells = node.get("cells", node.get("tokens", []))
            if cells is not None and not isinstance(cells, list):
                errors.append(f"Token grid `{node_id}` cells/tokens must be an array.")
            elif isinstance(cells, list):
                for index, cell in enumerate(cells):
                    if isinstance(cell, dict) and ("row" in cell or "col" in cell):
                        row = cell.get("row")
                        col = cell.get("col")
                        if not isinstance(row, int) or not isinstance(col, int):
                            errors.append(f"Token grid `{node_id}` cell {index} row/col must be integers.")
                            continue
                        zero_row = row - index_base
                        zero_col = col - index_base
                        if isinstance(rows, int) and not 0 <= zero_row < rows:
                            errors.append(f"Token grid `{node_id}` cell {index} row is out of range.")
                        if isinstance(cols, int) and not 0 <= zero_col < cols:
                            errors.append(f"Token grid `{node_id}` cell {index} col is out of range.")
            for key in ("cell_gap_in", "cell_rounding_in", "cell_font_size_pt"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Token grid `{node_id}` {key} must be a non-negative number.")
            for key in ("square_cells",):
                value = node.get(key)
                if value is not None and not isinstance(value, bool):
                    warnings.append(f"Token grid `{node_id}` {key} should be boolean.")

        if node_type == "feature_vector_stack":
            count = node.get("count", node.get("cells_count", node.get("length")))
            if count is not None and (not isinstance(count, int) or count <= 0):
                errors.append(f"Feature vector stack `{node_id}` count/cells_count/length must be a positive integer.")
            entries = node.get("entries", node.get("cells", node.get("tokens")))
            if entries is not None and not isinstance(entries, list):
                errors.append(f"Feature vector stack `{node_id}` entries/cells/tokens must be an array.")
            orientation = str(node.get("orientation", (node.get("style", {}) if isinstance(node.get("style"), dict) else {}).get("orientation", "vertical"))).lower()
            if orientation not in {"vertical", "v", "horizontal", "h", "row"}:
                errors.append(f"Feature vector stack `{node_id}` orientation must be vertical or horizontal.")
            for key in ("cell_gap_in", "cell_rounding_in", "cell_font_size_pt", "bracket_w_in", "bracket_line_weight_pt"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or float(value) < 0):
                    errors.append(f"Feature vector stack `{node_id}` {key} must be a non-negative number.")
            for key in ("label_gap_in", "label_w_in", "label_h_in", "label_font_size_pt"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or float(value) < 0):
                    errors.append(f"Feature vector stack `{node_id}` {key} must be a non-negative number.")

        if node_type in RUN_TEXT_NODE_TYPES:
            validate_text_runs_payload(
                node,
                node_id,
                "Caption block" if node_type == "caption_block" else "Text node",
                errors,
                warnings,
                exact_mode=exact_mode,
            )

        if node_type == "caption_block":
            runs = node.get("runs")
            text = str(node.get("text", "")).strip()
            if not text and not runs:
                warnings.append(f"Caption block `{node_id}` has no text/runs.")
            if node.get("strict_mode") and runs and len(runs) < 2:
                warnings.append(
                    f"Caption block `{node_id}` uses strict_mode but has fewer than two runs; paper captions usually need a bold prefix run plus a body run."
                )
            baseline_offset = node.get("baseline_offset_in")
            if baseline_offset is not None and not isinstance(baseline_offset, (int, float)):
                errors.append(f"Caption block `{node_id}` baseline_offset_in must be numeric.")
            if node.get("strict_mode") and not node.get("source_bbox_px", node.get("source_bbox")):
                warnings.append(
                    f"Caption block `{node_id}` uses strict_mode without source_bbox_px/source_bbox; caption centering and baseline drift are hard to review."
                )

        if node_type == "annotation_block" and isinstance(node.get("runs"), list):
            text_role = str(node.get("text_role", node.get("semantic_role", ""))).lower()
            if exact_mode and text_role not in {"annotation", "note", "callout", "caption", "formula"}:
                warnings.append(
                    f"Annotation block `{node_id}` uses runs but has no explicit text_role/semantic_role. Mark it as annotation/note/callout/formula so visual review can apply the right typography standard."
                )

        if node_type in {"annotation_block", "formula_text_block", "branch_trunk", "merge_trunk", "paper_bus", "collector_bar", "junction_bus", "vector_label_group"}:
            if exact_mode and not node.get("source_bbox_px", node.get("source_bbox")):
                warnings.append(
                    f"Exact-scene node `{node_id}` (`{node_type}`) should include source_bbox_px/source_bbox so local visual drift can be reviewed."
                )

        for key in ("semantic_role", "text_role", "source_bbox_px", "source_font_family", "font_role", "label_anchor", "layout_motif", "topology_motif"):
            if key in node:
                value = node.get(key)
                if key in {"semantic_role", "text_role", "source_font_family", "font_role", "label_anchor", "layout_motif", "topology_motif"} and value is not None and not isinstance(value, str):
                    errors.append(f"Node `{node_id}` {key} must be a string.")
                if key == "source_bbox_px" and value is not None:
                    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(item, (int, float)) for item in value):
                        errors.append(f"Node `{node_id}` source_bbox_px must be [left, top, right, bottom].")

        visual_warnings, visual_errors = visual_grammar_node_findings(
            node,
            str(node_id),
            node_type if isinstance(node_type, str) else None,
            exact_mode=exact_mode,
            strict_contract=strict,
        )
        warnings.extend(visual_warnings)
        errors.extend(visual_errors)

        if node_type == "probability_bar_list":
            items = node.get("items", node.get("rows", []))
            if items is not None and not isinstance(items, list):
                errors.append(f"Probability bar list `{node_id}` items/rows must be an array.")
            elif isinstance(items, list):
                for index, item in enumerate(items):
                    if isinstance(item, dict):
                        value = item.get("value", item.get("probability", item.get("score")))
                        if value is not None and not isinstance(value, (int, float, str)):
                            errors.append(f"Probability bar list `{node_id}` item {index} value must be numeric or text.")
                    elif not isinstance(item, (list, str, int, float)):
                        errors.append(f"Probability bar list `{node_id}` item {index} is invalid.")
            for key in (
                "padding_in",
                "row_gap_in",
                "row_height_in",
                "bar_gap_in",
                "bar_height_in",
                "label_w_in",
                "pre_value_w_in",
                "value_w_in",
                "axis_w_in",
                "axis_line_weight_pt",
                "bar_value_text_gap_in",
                "panel_inner_padding_left_in",
                "panel_inner_padding_right_in",
                "panel_inner_padding_top_in",
                "panel_inner_padding_bottom_in",
                "axis_offset_x_in",
                "bar_start_offset_x_in",
                "bar_end_padding_in",
                "bar_w_in",
                "label_offset_x_in",
                "label_offset_y_in",
                "pre_value_offset_x_in",
                "pre_value_offset_y_in",
                "value_offset_x_in",
                "value_offset_y_in",
                "bar_value_offset_x_in",
                "bar_value_offset_y_in",
                "label_baseline_offset_in",
                "pre_value_baseline_offset_in",
                "value_baseline_offset_in",
                "bar_value_baseline_offset_in",
            ):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Probability bar list `{node_id}` {key} must be a non-negative number.")
            for key in ("label_align", "pre_value_align", "value_align", "bar_value_align", "row_vertical_align"):
                value = node.get(key)
                if value is not None and not isinstance(value, (int, float)):
                    errors.append(f"Probability bar list `{node_id}` {key} must be numeric/alignment-like.")
            value = node.get("bar_max_fraction")
            if value is not None and (not isinstance(value, (int, float)) or not 0 < float(value) <= 1):
                errors.append(f"Probability bar list `{node_id}` bar_max_fraction must be a number in (0, 1].")
            if exact_mode:
                missing_exact_keys = [
                    key
                    for key in ("label_w_in", "row_gap_in", "bar_max_fraction")
                    if not node_or_style_has_key(node, key)
                ]
                if missing_exact_keys:
                    warnings.append(
                        f"Exact probability bar list `{node_id}` should explicitly record {', '.join(missing_exact_keys)}; "
                        "panel micro-layout should not rely only on profile defaults."
                    )
                if not (
                    node_or_style_has_key(node, "axis_w_in")
                    or node_or_style_has_key(node, "axis_offset_x_in")
                ):
                    warnings.append(
                        f"Exact probability bar list `{node_id}` should explicitly record the axis position with `axis_w_in` or `axis_offset_x_in`."
                    )
                if not node_or_style_has_key(node, "bar_value_anchor"):
                    warnings.append(
                        f"Exact probability bar list `{node_id}` should explicitly record `bar_value_anchor`; row text placement is a major visual fidelity control."
                    )
                if not any(node_or_style_has_key(node, key) for key in ("shadow", "panel_shadow")):
                    warnings.append(
                        f"Exact probability bar list `{node_id}` should explicitly set panel shadow, even if it is `null`, so paper-style softness is not left implicit."
                    )

        if node_type == "feature_map_grid":
            rows = node.get("rows")
            cols = node.get("cols", node.get("columns"))
            if rows is not None and (not isinstance(rows, int) or rows <= 0):
                errors.append(f"Feature map grid `{node_id}` rows must be a positive integer.")
            if cols is not None and (not isinstance(cols, int) or cols <= 0):
                errors.append(f"Feature map grid `{node_id}` cols/columns must be a positive integer.")
            for key in ("row_colors", "bands", "column_shades", "row_weights", "row_heights", "column_weights", "column_widths"):
                value = node.get(key)
                if value is not None and not isinstance(value, list):
                    errors.append(f"Feature map grid `{node_id}` {key} must be an array.")
            column_shades = node.get("column_shades")
            if isinstance(column_shades, list):
                for index, value in enumerate(column_shades):
                    if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                        errors.append(f"Feature map grid `{node_id}` column_shades[{index}] must be a number in [0, 1].")
            max_shade = node.get("max_shade")
            if max_shade is not None and (not isinstance(max_shade, (int, float)) or not 0 <= float(max_shade) <= 1):
                errors.append(f"Feature map grid `{node_id}` max_shade must be a number in [0, 1].")
            for key in ("show_column_lines", "show_row_lines"):
                value = node.get(key)
                if value is not None and not isinstance(value, bool):
                    errors.append(f"Feature map grid `{node_id}` {key} must be a boolean.")

        if node_type == "feature_map_banded":
            separator_count = node.get("separator_count", node.get("vertical_separator_count"))
            if separator_count is not None and (not isinstance(separator_count, int) or separator_count < 0):
                errors.append(f"Feature map banded `{node_id}` separator_count must be a non-negative integer.")
            separator_positions = node.get("separator_positions", node.get("vertical_separator_positions"))
            if separator_positions is not None:
                if not isinstance(separator_positions, list):
                    errors.append(f"Feature map banded `{node_id}` separator_positions must be an array.")
                elif not all(isinstance(item, (int, float)) for item in separator_positions):
                    errors.append(f"Feature map banded `{node_id}` separator_positions must contain only numbers.")

        if node_type == "polygon_node":
            points = node.get("points")
            if not isinstance(points, list) or len(points) < 3:
                errors.append(f"Polygon node `{node_id}` needs at least three `points`.")
            else:
                for index, point in enumerate(points):
                    if (
                        not isinstance(point, list)
                        or len(point) != 2
                        or not all(isinstance(item, (int, float)) for item in point)
                    ):
                        errors.append(f"Polygon node `{node_id}` points[{index}] must be [x, y] numbers.")

        if node_type == "trapezoid_node":
            orientation = str(node.get("orientation", "right")).lower()
            if orientation not in {"left", "right", "up", "down"}:
                errors.append(f"Trapezoid node `{node_id}` has unsupported orientation `{orientation}`.")
            taper = node.get("taper_ratio", node.get("taper"))
            if taper is not None and (not isinstance(taper, (int, float)) or not 0 <= float(taper) < 0.5):
                errors.append(f"Trapezoid node `{node_id}` taper_ratio must be in [0, 0.5).")

        if node_type == "modality_spine":
            ports = node.get("ports")
            if ports is not None and not isinstance(ports, list):
                errors.append(f"Modality spine `{node_id}` ports must be a list.")
            if isinstance(ports, list):
                for index, port in enumerate(ports):
                    if not isinstance(port, dict):
                        errors.append(f"Modality spine `{node_id}` ports[{index}] must be an object.")
                        continue
                    position = port.get("position", 0.5)
                    if not isinstance(position, (int, float)):
                        errors.append(f"Modality spine `{node_id}` ports[{index}].position must be numeric.")

        if node_type == "math_vector":
            entries = node.get("entries", node.get("rows"))
            text = str(node.get("text", "")).strip()
            if entries is None and not text:
                errors.append(f"Math vector `{node_id}` needs `entries`, `rows`, or text lines.")
            if entries is not None:
                if not isinstance(entries, list) or not entries:
                    errors.append(f"Math vector `{node_id}` entries/rows must be a non-empty array.")
                elif not all(isinstance(item, (str, int, float)) for item in entries):
                    errors.append(f"Math vector `{node_id}` entries must be strings or numbers.")
            for key in ("prefix_w", "gap_in", "bracket_w", "bracket_tick_in", "entry_font_size_pt"):
                value = node.get(key)
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"Math vector `{node_id}` {key} must be a non-negative number.")

        no_text_ok_types = {
            "image_tile",
            "grid_matrix",
            "bracket",
            "dimension_brace",
            "brace_merge",
            "concat_operator",
            "junction_point",
            "boundary_port",
            "audit_region",
            "dashed_region",
            "loss_region",
            "page_background",
            "merge_bus",
            "multi_port_junction",
            "boundary_fanout",
            "feature_map_banded",
            "feature_map_grid",
            "wave_signal",
            "classifier_head",
            "layer_sequence",
            "token_grid",
            "feature_vector_stack",
            "caption_block",
            "probability_bar_list",
            "polygon_node",
            "trapezoid_node",
            "dual_wing_encoder",
            "cuboid_node",
            "tensor_stack",
            "modality_spine",
            "math_vector",
            "math_label_box",
            "math_text",
            "math_formula_group",
            "tfr_panel",
            *RIBBON_ARROW_NODE_TYPES,
        }
        if strict and "text" not in node and "symbol" not in node and node_type not in no_text_ok_types:
            warnings.append(f"Node `{node_id}` has no `text`.")

    incoming_by_endpoint: dict[str, list[str]] = {}
    outgoing_by_endpoint: dict[str, list[str]] = {}
    profiles = load_style_profiles()
    _, profile = resolve_profile(scene, profiles, None)
    containers_by_node = infer_containers(nodes_by_id, node_types_by_id, warnings)
    for node in nodes:
        if not node.get("id") or node.get("type") not in node_types:
            continue
        try:
            _, style, _ = node_style(node, component_map, profile)
        except Exception as exc:
            warnings.append(f"Could not resolve style for node `{node.get('id')}` during font validation: {exc}")
            continue
        warnings.extend(font_validation_warnings(node, style, exact_mode))
        warnings.extend(text_fit_warnings(node, style, exact_mode))
        text_shrink_warnings, text_shrink_errors = strict_text_shrink_findings(node, style, exact_mode, strict_contract=strict)
        warnings.extend(text_shrink_warnings)
        errors.extend(text_shrink_errors)
    validate_alignment(nodes_by_id, node_types_by_id, containers_by_node, warnings)
    validate_boundary_ports(nodes_by_id, node_types_by_id, warnings, errors)
    validate_large_figure_discipline(
        scene,
        nodes_by_id,
        node_types_by_id,
        containers_by_node,
        component_map,
        profile,
        warnings,
    )
    for issue in tfr_panel_layout_issues(nodes_by_id, node_types_by_id):
        warnings.append(issue)

    gan_tfr_context = scene_looks_like_gan_tfr(scene, nodes_by_id)
    for edge in edges:
        edge_id = edge.get("id")
        if not edge_id:
            errors.append("Every edge must have an `id`.")
            continue
        if edge_id in edge_ids:
            errors.append(f"Duplicate edge id: {edge_id}")
        edge_ids.add(edge_id)

        edge_type = edge.get("type")
        if edge_type not in edge_types:
            errors.append(f"Unsupported edge type `{edge_type}` for edge `{edge_id}`.")

        role = edge.get("edge_role")
        if role is not None:
            if not isinstance(role, str):
                errors.append(f"Edge `{edge_id}` edge_role must be a string.")
            elif role not in EDGE_ROLES:
                errors.append(
                    f"Edge `{edge_id}` edge_role `{role}` is unsupported; use data_flow, context_flow, feedback_flow, decorative_internal, symbol_internal, or icon_internal."
                )

        source = edge.get("from")
        target = edge.get("to")
        source_point = edge_point(edge, "from")
        target_point = edge_point(edge, "to")
        if not source and source_point is None:
            errors.append(f"Edge `{edge_id}` must have `from` or `from_point`.")
            continue
        if not target and target_point is None:
            errors.append(f"Edge `{edge_id}` must have `to` or `to_point`.")
            continue

        for endpoint_name, endpoint_value in (("from", source), ("to", target)):
            if endpoint_value is None:
                point_value = edge.get(f"{endpoint_name}_point")
                if edge_point(edge, endpoint_name) is None:
                    errors.append(
                        f"Edge `{edge_id}` {endpoint_name}_point must be [x, y] numbers."
                    )
                elif point_value is None:
                    errors.append(f"Edge `{edge_id}` must have `{endpoint_name}` or `{endpoint_name}_point`.")
                continue
            if not isinstance(endpoint_value, str):
                errors.append(f"Edge `{edge_id}` {endpoint_name} must be a node endpoint string.")
                continue
            node_id = base_node_id(endpoint_value)
            if node_id not in node_ids:
                errors.append(
                    f"Edge `{edge_id}` {endpoint_name} references missing node `{node_id}`."
                )
            elif node_types_by_id.get(node_id) in CONTAINER_TYPES:
                warnings.append(
                    f"Edge `{edge_id}` {endpoint_name} connects to container `{node_id}`; "
                    "containers/audit regions should frame regions, not act as flow endpoints. Use a `junction_point` or explicit border anchor."
                )
            side = endpoint_side(endpoint_value)
            endpoint_node_type = node_types_by_id.get(node_id)
            if side and side not in allowed_endpoint_sides_for_node(endpoint_node_type):
                errors.append(
                    f"Edge `{edge_id}` {endpoint_name} has unsupported side `{side}`."
                )
            if "@" in endpoint_value:
                position = endpoint_position(endpoint_value)
                if position is None or not 0 <= position <= 1:
                    errors.append(
                        f"Edge `{edge_id}` {endpoint_name} endpoint position must use @ratio in [0, 1], for example node:left@0.62."
                    )
                elif side == "center":
                    warnings.append(
                        f"Edge `{edge_id}` {endpoint_name} uses @ratio on center; ratio anchors only affect left/right/top/bottom sides."
                    )

        if isinstance(source, str):
            outgoing_by_endpoint.setdefault(source, []).append(edge_id)
        if isinstance(target, str):
            incoming_by_endpoint.setdefault(target, []).append(edge_id)

        route = edge.get("route") or edge.get("style", {}).get("route")
        if route and route not in {
            "auto",
            "straight",
            "orthogonal",
            "elbow",
            "right_angle",
            "rounded_orthogonal",
            "horizontal",
            "vertical",
            "hline",
            "vline",
            "axis_horizontal",
            "axis_vertical",
            "hv",
            "vh",
            "horizontal_then_vertical",
            "vertical_then_horizontal",
        }:
            errors.append(f"Edge `{edge_id}` has unsupported route `{route}`.")

        points = edge.get("points", [])
        if points:
            if not isinstance(points, list):
                errors.append(f"Edge `{edge_id}` `points` must be an array.")
            else:
                for index, point in enumerate(points):
                    if (
                        not isinstance(point, list)
                        or len(point) != 2
                        or not all(isinstance(value, (int, float)) for value in point)
                    ):
                        errors.append(
                            f"Edge `{edge_id}` point {index} must be [x, y] numbers."
                        )
        for tangent_key in ("start_tangent_point", "end_tangent_point"):
            tangent_point = edge.get(tangent_key)
            if tangent_point is not None and (
                not isinstance(tangent_point, list)
                or len(tangent_point) != 2
                or not all(isinstance(value, (int, float)) for value in tangent_point)
            ):
                errors.append(f"Edge `{edge_id}` `{tangent_key}` must be [x, y] numbers.")
        if edge_type in CURVED_EDGE_TYPES and len(points) < 2:
            warnings.append(
                f"Curved edge `{edge_id}` should include several intermediate `points` so it renders as one smooth path. "
                "Do not split a visible loop into separate line and arrowhead edges."
            )

        if (
            edge_type in edge_types
            and (not isinstance(source, str) or base_node_id(source) in nodes_by_id)
            and (not isinstance(target, str) or base_node_id(target) in nodes_by_id)
        ):
            try:
                style = edge_style(edge, component_map, profile)
                route_points = edge_route_points(edge, style, nodes_by_id)
            except Exception as exc:
                warnings.append(f"Edge `{edge_id}` route could not be linted: {exc}")
                continue
            if is_internal_edge(edge):
                continue

            route_name = edge.get("route") or edge.get("style", {}).get("route") or style.get("route") or "auto"
            diagonal_segments = [
                (start, end)
                for start, end in zip(route_points, route_points[1:])
                if segment_has_diagonal(start, end)
            ]
            if diagonal_segments and not edge.get("allow_diagonal") and edge_type not in CURVED_EDGE_TYPES:
                warnings.append(
                    f"Edge `{edge_id}` contains diagonal segment(s); use `hv`/`vh`, aligned explicit points, "
                    "or set `allow_diagonal: true` only for intentional callout lines."
                )
            if exact_mode:
                warnings.extend(exact_text_route_overlap_warnings(route_points, str(edge_id), edge, nodes_by_id, node_types_by_id))
            orthogonalized = bool(edge.get("orthogonalize_points"))
            if route_name in {
                "orthogonal",
                "elbow",
                "right_angle",
                "rounded_orthogonal",
                "horizontal",
                "vertical",
                "hline",
                "vline",
                "axis_horizontal",
                "axis_vertical",
                "hv",
                "vh",
                "horizontal_then_vertical",
                "vertical_then_horizontal",
            } and diagonal_segments and edge_type not in CURVED_EDGE_TYPES:
                warnings.append(
                    f"Edge `{edge_id}` is marked `{route_name}` but its computed path is not axis-aligned. "
                    "Align the first/last explicit point with the endpoint or set `orthogonalize_points: true` for right-angle explicit routes."
                )
            if points and diagonal_segments and not orthogonalized and edge_type not in CURVED_EDGE_TYPES and route_name in {"auto", "orthogonal", "elbow", "right_angle"}:
                warnings.append(
                    f"Edge `{edge_id}` has explicit points that still create diagonal segment(s). "
                    "Set `orthogonalize_points: true`, provide exact axis-aligned points, or mark intentional diagonals with `allow_diagonal: true`."
                )

            axes = route_axes(route_points)
            if gan_tfr_context:
                from_role = edge_endpoint_role(edge, "from", nodes_by_id, node_types_by_id)
                to_role = edge_endpoint_role(edge, "to", nodes_by_id, node_types_by_id)
                if from_role == "discriminator" and to_role == "generated":
                    warnings.append(
                        f"GAN/TFR edge `{edge_id}` appears reversed: it goes from Discriminator to Generated. "
                        "For this reconstruction grammar, Generated/Reconstructed TFR should feed into the Discriminator, not the other way around."
                    )

            if edge_type == "lane_arrow":
                if "diagonal" in axes:
                    warnings.append(
                        f"Lane arrow `{edge_id}` contains diagonal segment(s). "
                        "Use `route: \"horizontal\"`/`vertical` or align explicit `from_point`/`to_point`; "
                        "do not use `straight` on slightly mismatched lane y/x values."
                    )
                lane_axis = str(edge.get("lane_axis", edge.get("axis", ""))).lower()
                if lane_axis == "horizontal" and axes - {"horizontal"}:
                    warnings.append(f"Lane arrow `{edge_id}` is declared horizontal but has {sorted(axes)} segment(s).")
                if lane_axis == "vertical" and axes - {"vertical"}:
                    warnings.append(f"Lane arrow `{edge_id}` is declared vertical but has {sorted(axes)} segment(s).")

            if edge_type == "rounded_orthogonal_connector":
                if "diagonal" in axes:
                    warnings.append(
                        f"Rounded orthogonal connector `{edge_id}` contains diagonal segment(s). "
                        "Provide axis-aligned points or set `orthogonalize_points: true`; rounded corners should not be produced by smoothing a diagonal path."
                    )
                if len(route_points) < 3:
                    warnings.append(
                        f"Rounded orthogonal connector `{edge_id}` has fewer than three route points; use it for 90-degree bends, not a plain straight lane."
                    )
                edge_style_payload = edge.get("style", {}) if isinstance(edge.get("style"), dict) else {}
                radius = edge.get(
                    "corner_radius_in",
                    edge.get(
                        "corner_radius_px",
                        edge_style_payload.get("corner_radius_in", edge_style_payload.get("corner_radius_px")),
                    ),
                )
                if radius is None:
                    warnings.append(
                        f"Rounded orthogonal connector `{edge_id}` should set `corner_radius_in` or `corner_radius_px` so corner rounding is intentional."
                    )

            if diagonal_segments and edge.get("allow_diagonal") and edge_type in {"arrow_connector", "dynamic_connector"}:
                source_text = str(source or source_point or "")
                target_text = str(target or target_point or "")
                edge_name = str(edge_id).lower()
                likely_lane = any(
                    token in edge_name or token in source_text.lower() or token in target_text.lower()
                    for token in {"gap", "gmp", "extractor", "quality", "aggregation", "projection", "environment", "spine"}
                )
                if likely_lane:
                    warnings.append(
                        f"Edge `{edge_id}` has `allow_diagonal: true` but looks like a paper-flow lane. "
                        "Use `lane_arrow`, forced `horizontal`/`vertical`, side-ratio endpoints, or explicit axis-aligned points instead of accepting a diagonal."
                    )
                likely_feedback = any(
                    token in edge_name or token in source_text.lower() or token in target_text.lower()
                    for token in {"loss", "backprop", "feedback", "gradient", "penalty", "adv", "rec"}
                )
                if likely_feedback:
                    warnings.append(
                        f"Edge `{edge_id}` has `allow_diagonal: true` but looks like a dashed training/feedback path. "
                        "Use `dashed_feedback_path` with explicit orthogonal points, or mark it as an intentional diagonal callout only when the source really is diagonal."
                    )

            if edge_type == "dashed_feedback_path":
                if "diagonal" in axes:
                    warnings.append(
                        f"Dashed feedback path `{edge_id}` contains diagonal segment(s). "
                        "Use explicit orthogonal points for loss/backprop paths."
                    )
                if edge.get("allow_diagonal"):
                    warnings.append(
                        f"Dashed feedback path `{edge_id}` should not rely on `allow_diagonal`; preserve the source path with explicit axis-aligned points."
                    )
                if str(style.get("line_dash", "")).lower() not in {"dash", "dot", "long_dash"}:
                    warnings.append(f"Dashed feedback path `{edge_id}` should use a dashed line style.")
                if not edge.get("allow_region_interior_path"):
                    for region_id, region_node in nodes_by_id.items():
                        if node_types_by_id.get(region_id) not in {"dashed_region", "loss_region"}:
                            continue
                        region_box = node_box(region_node)
                        if any(
                            segment_intersects_box_interior(start, end, region_box, clearance=0.01)
                            for start, end in zip(route_points, route_points[1:])
                        ):
                            warnings.append(
                                f"Dashed feedback path `{edge_id}` draws through dashed region `{region_id}`. "
                                "Keep annotation frames clean: exit through a boundary point/port, then route outside the frame."
                            )
                            break
                stub_issue = loss_feedback_stub_issue(edge, route_points, nodes_by_id, node_types_by_id)
                if stub_issue:
                    warnings.append(stub_issue)

            if edge_type in CURVED_EDGE_TYPES and len(route_points) < 4:
                warnings.append(
                    f"Curved edge `{edge_id}` has too few points for a smooth loop; add sampled curve points or Bezier controls."
                )
            if edge_type == "loop_arrow" and any(token in str(edge_id).lower() for token in {"outer", "loop", "cycle"}):
                curve_mode = str(edge.get("curve_mode", edge.get("curve", style.get("curve_mode", "polyline")))).lower()
                if curve_mode in {"", "polyline", "straight"}:
                    warnings.append(
                        f"Outer loop `{edge_id}` is rendered as `{curve_mode or 'polyline'}`. "
                        "Use `curve_mode: \"smooth\"` and evenly sampled points so the update loop does not look like a decorative polygon border."
                    )
                if not (edge.get("semantic_role") or edge.get("loop_role") or edge.get("label_id")):
                    warnings.append(
                        f"Outer loop `{edge_id}` has no semantic role or label binding. "
                        "Set `semantic_role: \"outer_update_loop\"` and bind the bottom label with `label_id`/`loop_label_id` so it reads as process flow."
                    )
                tangent_issue = terminal_tangent_issue(edge, route_points)
                if tangent_issue:
                    warnings.append(tangent_issue)
                bounds = path_bounds(route_points)
                if bounds and isinstance(page.get("width"), (int, float)) and isinstance(page.get("height"), (int, float)):
                    x1, y1, x2, y2 = bounds
                    page_w = float(page["width"])
                    page_h = float(page["height"])
                    margin = float(edge.get("page_margin_in", style.get("page_margin_in", 0.0)))
                    if x1 < margin or y1 < margin or x2 > page_w - margin or y2 > page_h - margin:
                        warnings.append(
                            f"Outer loop `{edge_id}` reaches page bounds ({x1:.2f},{y1:.2f},{x2:.2f},{y2:.2f}); "
                            "keep the full loop inside the page/background so export does not crop the curve."
                        )
                label_id = edge.get("label_id") or edge.get("loop_label_id")
                if isinstance(label_id, str) and label_id in nodes_by_id and has_valid_box(nodes_by_id[label_id]):
                    label_box = expanded_box(node_box(nodes_by_id[label_id]), 0.025)
                    if polyline_intersects_box_bbox(route_points, label_box, clearance=0.0):
                        warnings.append(
                            f"Outer loop `{edge_id}` overlaps its label `{label_id}`. Move the label away from the curve "
                            "or reshape the bottom arc before rendering."
                        )
            if edge_type in {"line_segment", "arrow_connector"} and any(token in str(edge_id).lower() for token in {"outer", "loop", "cycle"}):
                if edge_type == "line_segment" and len(route_points) >= 4:
                    warnings.append(
                        f"Edge `{edge_id}` looks like part of a visible loop drawn as a plain line segment. "
                        "Use one `loop_arrow`/`curved_arrow` path so the curve is continuous and arrowheads stay tangent."
                    )
                elif edge_type == "arrow_connector":
                    warnings.append(
                        f"Edge `{edge_id}` looks like a detached loop arrowhead. "
                        "Put the arrowhead on the `loop_arrow`/`curved_arrow` path instead."
                    )

            line_dash = str(style.get("line_dash", "")).lower()
            edge_name = str(edge_id).lower()
            feedback_like = (
                edge_type == "dashed_feedback_path"
                or line_dash in {"dash", "dot", "long_dash"}
                or any(token in edge_name for token in {"loss", "backprop", "feedback", "gradient", "penalty", "adv", "rec"})
            )
            if feedback_like and edge_type not in {"dashed_feedback_path", "line_segment"}:
                warnings.append(
                    f"Edge `{edge_id}` looks like a dashed/loss/backprop feedback route but uses `{edge_type}`. "
                    "Use `dashed_feedback_path` so the path is audited as one continuous feedback route."
                )
            if feedback_like and edge_type == "line_segment" and str(style.get("end_arrow", "")).lower() not in {"", "none"}:
                warnings.append(
                    f"Edge `{edge_id}` is a dashed feedback-like `line_segment` with an arrowhead. "
                    "Use one `dashed_feedback_path` tied to the loss/backprop subsystem; short dashed arrow fragments often become false extra boxes."
                )
            if feedback_like and gan_tfr_context:
                target_role = edge_endpoint_role(edge, "to", nodes_by_id, node_types_by_id)
                source_role = edge_endpoint_role(edge, "from", nodes_by_id, node_types_by_id)
                end_arrow = str(style.get("end_arrow", "")).lower()
                if target_role in {"real_tfr", "generated"} and end_arrow not in {"", "none"}:
                    warnings.append(
                        f"GAN/TFR feedback edge `{edge_id}` points into `{target_role}`. Backprop/loss paths should leave TFR panels "
                        "toward a bus or discriminator, not terminate with an arrowhead at the panel input area."
                    )
                if source_role in {"real_tfr", "generated"} and end_arrow not in {"", "none"} and any(token in edge_name for token in {"backprop", "loss", "rec", "adv"}):
                    warnings.append(
                        f"GAN/TFR feedback edge `{edge_id}` starts at a TFR panel but still has an arrowhead on the far end. "
                        "Panel-to-backprop-bus legs should usually set `end_arrow: none` and let the discriminator stubs carry arrowheads."
                    )
            if feedback_like and not edge.get("allow_text_overlap"):
                for text_node_id, text_node in nodes_by_id.items():
                    if node_types_by_id.get(text_node_id) not in {"text_block", "math_text"}:
                        continue
                    if not str(text_node.get("text", text_node.get("lines", ""))).strip():
                        continue
                    if is_background_node(text_node):
                        continue
                    text_box = expanded_box(node_box(text_node), 0.025)
                    if any(
                        segment_intersects_box_interior(start, end, text_box, clearance=0.0)
                        for start, end in zip(route_points, route_points[1:])
                    ):
                        warnings.append(
                            f"Edge `{edge_id}` crosses text node `{text_node_id}`. "
                            "For exact replicas, reroute dashed/loss/backprop paths around labels instead of nudging text after render."
                        )
                        break

            if edge_type == "boundary_arrow":
                source_node_id = base_node_id(source) if isinstance(source, str) else None
                target_node_id = base_node_id(target) if isinstance(target, str) else None
                source_type = node_types_by_id.get(source_node_id) if source_node_id else None
                target_type = node_types_by_id.get(target_node_id) if target_node_id else None
                if source_type != "boundary_port" and target_type != "boundary_port":
                    warnings.append(
                        f"Boundary arrow `{edge_id}` should start or end at a `boundary_port`; "
                        "use it for frame-edge output, not ordinary component-to-component flow."
                    )
                if route_name not in {"horizontal", "vertical", "hline", "vline", "axis_horizontal", "axis_vertical"}:
                    warnings.append(
                        f"Boundary arrow `{edge_id}` should use a forced axis route such as `horizontal` or `vertical`."
                    )

            source_node_id = base_node_id(source) if isinstance(source, str) else None
            target_node_id = base_node_id(target) if isinstance(target, str) else None
            source_container = (
                containers_by_node.get(source_node_id)
                if source_node_id
                else container_for_point(source_point, nodes_by_id, node_types_by_id)
            )
            target_container = (
                containers_by_node.get(target_node_id)
                if target_node_id
                else container_for_point(target_point, nodes_by_id, node_types_by_id)
            )
            if source_container and target_container and source_container == target_container:
                container_box = node_box(nodes_by_id[source_container])
                if any(
                    not point_in_box(point, container_box, tolerance=CONTAINER_TOLERANCE)
                    for point in route_points
                ):
                    warnings.append(
                        f"Edge `{edge_id}` connects nodes inside `{source_container}` but leaves that container. "
                        "Keep intra-module connectors inside the dashed frame."
                    )
            elif source_container != target_container and edge_type != "line_segment" and not edge.get("allow_cross_container"):
                warnings.append(
                    f"Edge `{edge_id}` crosses container boundary ({source_container} -> {target_container}). "
                    "Split cross-module routes through `junction_point` nodes with `role: boundary_anchor`, "
                    "or mark `allow_cross_container: true` for deliberate callouts."
                )
            if exact_mode and source_container != target_container:
                source_type = node_types_by_id.get(source_node_id) if source_node_id else None
                target_type = node_types_by_id.get(target_node_id) if target_node_id else None
                if isinstance(source, str) and source_type != "boundary_port" and not endpoint_has_explicit_side_anchor(source) and not edge.get("allow_direct_cross_container"):
                    warnings.append(
                        f"Edge `{edge_id}` leaves `{source_node_id}` across a module boundary without an explicit side anchor. "
                        "Do not rely on center-to-center flow; use a boundary port, side anchor, bus, or explicit junction."
                    )
                if isinstance(target, str) and target_type != "boundary_port" and not endpoint_has_explicit_side_anchor(target) and not edge.get("allow_direct_cross_container"):
                    warnings.append(
                        f"Edge `{edge_id}` enters `{target_node_id}` across a module boundary without an explicit side anchor. "
                        "Bind long cross-module edges to a side/port instead of default center landing."
                    )
                if line_length(route_points) > 0.75 and edge_type in {"arrow_connector", "dynamic_connector", "line_segment"}:
                    route_name_lower = str(route_name).lower()
                    if route_name_lower in {"", "auto", "straight"} and not points and not edge.get("force_axis"):
                        warnings.append(
                            f"Edge `{edge_id}` is a long cross-module route but leaves routing grammar implicit. "
                            "Set an axis-aligned route, force_axis, or explicit orthogonal points before visual polishing."
                        )
            if source_container != target_container and edge_type not in {"line_segment", "boundary_arrow"}:
                source_type = node_types_by_id.get(source_node_id) if source_node_id else None
                target_type = node_types_by_id.get(target_node_id) if target_node_id else None
                if (
                    source_type != "boundary_port"
                    and target_type != "boundary_port"
                    and not edge.get("allow_direct_cross_container")
                ):
                    warnings.append(
                        f"Edge `{edge_id}` directly connects components across module boundary "
                        f"({source_container} -> {target_container}). For exact replicas, route through "
                        "`boundary_port`/`boundary_arrow` unless the source visibly connects component-to-component."
                    )

            endpoint_node_ids = {node_id for node_id in (source_node_id, target_node_id) if node_id}
            endpoint_stack_ids = {
                nodes_by_id[node_id].get("stack_id")
                for node_id in endpoint_node_ids
                if nodes_by_id.get(node_id, {}).get("stack_id")
            }
            for other_id, other_node in nodes_by_id.items():
                if other_id in endpoint_node_ids:
                    continue
                if is_background_node(other_node):
                    continue
                if is_passive_loop_frame(other_node):
                    continue
                if other_node.get("stack_id") in endpoint_stack_ids:
                    continue
                if node_types_by_id.get(other_id) in {
                    "group_container",
                    "dashed_region",
                    "loss_region",
                    "audit_region",
                    "junction_point",
                    "boundary_port",
                    "bracket",
                    "text_block",
                    "merge_bus",
                    "boundary_fanout",
                }:
                    continue
                other_box = node_box(other_node)
                if any(
                    segment_intersects_box_interior(start, end, other_box)
                    for start, end in zip(route_points, route_points[1:])
                ):
                    warnings.append(
                        f"Edge `{edge_id}` intersects non-endpoint node `{other_id}`. "
                        "Move it to a bus lane, add a junction/boundary anchor, or add explicit points around the node."
                    )
                    break

    if gan_tfr_context:
        parallel_backprop: list[tuple[str, float, float]] = []
        for edge in edges:
            edge_id = str(edge.get("id", ""))
            if edge.get("type") != "dashed_feedback_path":
                continue
            if not any(token in edge_id.lower() for token in {"backprop", "bottom", "disc", "loss"}):
                continue
            try:
                style = edge_style(edge, component_map, profile)
                route_points = edge_route_points(edge, style, nodes_by_id)
            except Exception:
                continue
            if len(route_points) < 2:
                continue
            start, end = route_points[0], route_points[-1]
            if abs(start[0] - end[0]) <= POINT_TOLERANCE and abs(start[1] - end[1]) > 0.35:
                target_role = edge_endpoint_role(edge, "to", nodes_by_id, node_types_by_id)
                if target_role == "discriminator" or "disc" in edge_id.lower():
                    parallel_backprop.append((edge_id, start[0], start[1]))
        if len(parallel_backprop) >= 3:
            xs = sorted(item[1] for item in parallel_backprop)
            min_spacing = min((b - a for a, b in zip(xs, xs[1:])), default=999)
            unbundled = [edge_id for edge_id, _, _ in parallel_backprop if not any(edge.get("id") == edge_id and edge.get("bundle_id") for edge in edges)]
            if min_spacing < 0.18 or unbundled:
                warnings.append(
                    "GAN/TFR backprop arrows contain three or more parallel dashed vertical paths into the discriminator. "
                    "Use a shared `merge_bus`/`junction_point` with `bundle_id` and controlled spacing so the bottom loss system reads as one clean feedback bus."
                )

    validate_arrow_plan_contract(
        scene,
        edges,
        nodes_by_id,
        node_types_by_id,
        component_map,
        profile,
        warnings,
        errors,
        strict_contract=strict,
    )
    validate_local_motif_contract(
        scene,
        nodes_by_id,
        warnings,
        errors,
        strict_contract=strict,
    )

    for endpoint, edge_list in incoming_by_endpoint.items():
        node_type = node_types_by_id.get(base_node_id(endpoint))
        if node_type not in {None, "junction_point", "merge_bus"} and len(edge_list) >= 2:
            warnings.append(
                f"Endpoint `{endpoint}` has {len(edge_list)} incoming edges "
                f"({', '.join(edge_list)}); use a tiny `junction_point` when the source figure shows a merged 2-to-1 or many-to-one connector."
            )

    for endpoint, edge_list in outgoing_by_endpoint.items():
        node_type = node_types_by_id.get(base_node_id(endpoint))
        if node_type not in {None, "junction_point", "merge_bus"} and len(edge_list) >= 2:
            warnings.append(
                f"Endpoint `{endpoint}` has {len(edge_list)} outgoing edges "
                f"({', '.join(edge_list)}); use a tiny `junction_point` when the source figure shows a one-to-many fan-out connector."
            )

    return errors, warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a visiomaster scene.json file.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scene_path = Path(args.scene).resolve()
    scene = json.loads(scene_path.read_text(encoding="utf-8"))

    errors, warnings = validate_scene(scene, strict=args.strict)

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")

    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Scene is valid: {scene_path}")
    print(
        f"Nodes: {len(scene.get('nodes', []))}, "
        f"Edges: {len(scene.get('edges', []))}, "
        f"Assets: {len(scene.get('assets', []))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
