#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from font_utils import font_resolution_for_style


def truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pixel_coordinate_scale(scene: dict[str, Any]) -> tuple[float, float, float, float] | None:
    page = scene.get("page", {})
    metadata = scene.get("metadata", {})
    units = str(page.get("units", metadata.get("coordinate_units", ""))).lower()
    coordinate_space = str(metadata.get("coordinate_space", "")).lower()
    pixel_mode = units in {"px", "pixel", "pixels"} or coordinate_space in {"px", "pixel", "pixels"}
    if not pixel_mode:
        return None

    if units in {"px", "pixel", "pixels"}:
        source_w = page.get("width")
        source_h = page.get("height")
        target_w = page.get("target_width_in", metadata.get("target_width_in", 13.333))
        target_h = page.get("target_height_in", metadata.get("target_height_in"))
    else:
        source_w = page.get("source_width_px", metadata.get("source_width_px"))
        source_h = page.get("source_height_px", metadata.get("source_height_px"))
        target_w = page.get("width")
        target_h = page.get("height")

    if not isinstance(source_w, (int, float)) or not isinstance(source_h, (int, float)):
        raise ValueError("Pixel coordinate scenes require source width/height in pixels.")
    if source_w <= 0 or source_h <= 0:
        raise ValueError("Pixel coordinate source width/height must be positive.")
    if not isinstance(target_w, (int, float)) or target_w <= 0:
        raise ValueError("Pixel coordinate scenes require positive target page width in inches.")
    if target_h is None:
        target_h = float(target_w) * float(source_h) / float(source_w)
    if not isinstance(target_h, (int, float)) or target_h <= 0:
        raise ValueError("Pixel coordinate scenes require positive target page height in inches.")

    return float(target_w) / float(source_w), float(target_h) / float(source_h), float(target_w), float(target_h)


def scale_point(point: list[Any], sx: float, sy: float) -> list[float]:
    return [float(point[0]) * sx, float(point[1]) * sy]


def scale_nested_relative_or_absolute(value: Any, scale: float) -> Any:
    if not isinstance(value, (int, float)):
        return value
    numeric = float(value)
    if -1.0 <= numeric <= 1.0:
        return numeric
    return numeric * scale


def scale_for_inch_key(key: str, sx: float, sy: float) -> float:
    name = key.lower()
    if name.endswith(("_y_in", "_dy_in", "_h_in", "_height_in")) or any(
        token in name
        for token in (
            "top_",
            "bottom_",
            "row_height",
            "bar_height",
            "value_height",
            "line_gap",
            "input_gap",
            "subtitle_h",
            "title_h",
            "formula_pad_y",
            "scale_y",
            "amplitude",
        )
    ):
        return sy
    if name.endswith(("_x_in", "_dx_in", "_w_in", "_width_in")) or any(
        token in name
        for token in (
            "left_",
            "right_",
            "prefix_w",
            "label_w",
            "value_w",
            "axis_w",
            "pre_value_w",
            "bar_value_w",
            "bar_value_offset_x",
            "bar_value_text_gap",
            "bar_value_gap",
            "grid_w",
            "formula_pad_x",
            "title_pad_x",
            "scale_x",
            "center_w",
            "waist_width",
            "edge_notch",
        )
    ):
        return sx
    return min(sx, sy)


def scale_in_fields_recursive(value: Any, sx: float, sy: float) -> None:
    legacy_x_fields = {
        "prefix_w",
        "gap",
        "gap_in",
        "bracket_w",
        "bracket_tick",
        "port_length",
        "label_w",
        "value_w",
        "pre_value_w",
        "axis_w",
        "bar_value_w",
        "bar_value_offset_x",
        "bar_value_text_gap",
        "bar_value_gap",
        "bar_gap",
        "row_gap",
        "block_gap",
        "cell_gap",
        "tick",
        "tick_length",
        "label_inset",
        "symbol_inset",
        "symbol_box_w",
        "symbol_box_width",
        "center_w",
        "waist_width",
        "edge_notch",
    }
    legacy_y_fields = {
        "row_height",
        "bar_height",
        "bar_h",
        "line_gap",
        "segment_gap",
        "subscript_offset",
        "symbol_box_h",
        "symbol_box_height",
    }
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if isinstance(item, (dict, list)):
                scale_in_fields_recursive(item, sx, sy)
            elif isinstance(key, str) and key.endswith("_in"):
                value[key] = scale_nested_relative_or_absolute(item, scale_for_inch_key(key, sx, sy))
            elif isinstance(key, str) and key in legacy_x_fields:
                value[key] = scale_nested_relative_or_absolute(item, sx)
            elif isinstance(key, str) and key in legacy_y_fields:
                value[key] = scale_nested_relative_or_absolute(item, sy)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                scale_in_fields_recursive(item, sx, sy)


def scale_local_box_fields(item: dict[str, Any], sx: float, sy: float) -> None:
    for key in ("x", "left", "offset_x", "dx"):
        if key in item:
            item[key] = scale_nested_relative_or_absolute(item[key], sx)
    for key in ("y", "top", "offset_y", "dy"):
        if key in item:
            item[key] = scale_nested_relative_or_absolute(item[key], sy)
    for key in ("w", "width"):
        if key in item:
            item[key] = scale_nested_relative_or_absolute(item[key], sx)
    for key in ("h", "height"):
        if key in item:
            item[key] = scale_nested_relative_or_absolute(item[key], sy)


def scale_component_local_geometry(node: dict[str, Any], sx: float, sy: float) -> None:
    node_type = str(node.get("type", ""))
    if node_type in {"layer_sequence", "classifier_head"}:
        for collection_key in ("blocks", "labels"):
            items = node.get(collection_key)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    scale_local_box_fields(item, sx, sy)

    if node_type in {"caption_block", "annotation_block", "text_block"}:
        runs = node.get("runs")
        if isinstance(runs, list):
            for run in runs:
                if not isinstance(run, dict):
                    continue
                for key in ("w", "width"):
                    if key in run:
                        run[key] = scale_nested_relative_or_absolute(run[key], sx)

    if node_type == "attention_score_motif":
        x_keys = ["operator_x_in", "operator_size_in", "grid_x_in", "grid_w_in", "label_offset_x_in"]
        y_keys = ["operator_y_in", "grid_y_in", "grid_h_in", "label_offset_y_in"]
        ratio_keys = [
            "operator_x_ratio",
            "operator_y_ratio",
            "operator_size_ratio",
            "grid_x_ratio",
            "grid_y_ratio",
            "grid_w_ratio",
            "grid_h_ratio",
        ]
        for key in x_keys:
            if key in node:
                node[key] = scale_nested_relative_or_absolute(node[key], sx)
        for key in y_keys:
            if key in node:
                node[key] = scale_nested_relative_or_absolute(node[key], sy)
        for key in ratio_keys:
            if key in node:
                node[key] = scale_nested_relative_or_absolute(node[key], 1.0)
        input_ports = node.get("input_ports")
        if isinstance(input_ports, list):
            for port in input_ports:
                if not isinstance(port, dict):
                    continue
                for point_key in ("from_point", "point"):
                    point = port.get(point_key)
                    if isinstance(point, list) and len(point) == 2:
                        port[point_key] = scale_point(point, sx, sy)

    points = node.get("points")
    if isinstance(points, list) and points and all(isinstance(point, list) and len(point) == 2 for point in points):
        node["points"] = [
            [
                scale_nested_relative_or_absolute(point[0], sx),
                scale_nested_relative_or_absolute(point[1], sy),
            ]
            for point in points
        ]


def normalize_scene_coordinates(scene: dict[str, Any]) -> dict[str, Any]:
    scale = pixel_coordinate_scale(scene)
    if scale is None:
        return scene

    sx, sy, page_width, page_height = scale
    normalized = copy.deepcopy(scene)
    page = normalized.setdefault("page", {})
    page["width"] = page_width
    page["height"] = page_height
    page["units"] = "in"
    page["origin"] = "top-left"

    for node in normalized.get("nodes", []):
        if all(key in node for key in ("x", "y", "w", "h")):
            node["x"] = float(node["x"]) * sx
            node["y"] = float(node["y"]) * sy
            node["w"] = float(node["w"]) * sx
            node["h"] = float(node["h"]) * sy
        for key in ("grid_x",):
            if key in node:
                node[key] = scale_nested_relative_or_absolute(node[key], sx)
        for key in ("grid_y", "input_y"):
            if key in node:
                node[key] = scale_nested_relative_or_absolute(node[key], sy)
        for key in ("grid_w",):
            if key in node:
                node[key] = scale_nested_relative_or_absolute(node[key], sx)
        for key in ("grid_h",):
            if key in node:
                node[key] = scale_nested_relative_or_absolute(node[key], sy)
        scale_in_fields_recursive(node, sx, sy)
        for px_key, inch_key, scale_value in (
            ("body_width_px", "body_width_in", min(sx, sy)),
            ("head_width_px", "head_width_in", min(sx, sy)),
            ("head_length_px", "head_length_in", sx),
            ("ribbon_width_px", "body_width_in", min(sx, sy)),
            ("corner_radius_px", "corner_radius_in", min(sx, sy)),
        ):
            if isinstance(node.get(px_key), (int, float)) and inch_key not in node:
                node[inch_key] = float(node[px_key]) * scale_value
        scale_component_local_geometry(node, sx, sy)
        for collection_key in ("notches", "overlays", "vertical_bands"):
            for item in node.get(collection_key, []) or []:
                if not isinstance(item, dict):
                    continue
                for key in ("x", "w"):
                    if key in item:
                        item[key] = scale_nested_relative_or_absolute(item[key], sx)
                for key in ("y", "h"):
                    if key in item:
                        item[key] = scale_nested_relative_or_absolute(item[key], sy)

    for edge in normalized.get("edges", []):
        scale_in_fields_recursive(edge, sx, sy)
        if isinstance(edge.get("corner_radius_px"), (int, float)):
            edge["corner_radius_in"] = float(edge["corner_radius_px"]) * min(sx, sy)
        for key in ("from_point", "to_point", "start_tangent_point", "end_tangent_point"):
            if key in edge:
                edge[key] = scale_point(edge[key], sx, sy)
        if edge.get("points"):
            edge["points"] = [scale_point(point, sx, sy) for point in edge["points"]]
        if isinstance(edge.get("bbox"), list) and len(edge["bbox"]) == 4:
            edge["bbox"] = [
                float(edge["bbox"][0]) * sx,
                float(edge["bbox"][1]) * sy,
                float(edge["bbox"][2]) * sx,
                float(edge["bbox"][3]) * sy,
            ]

    metadata = normalized.setdefault("metadata", {})
    metadata["normalized_from_units"] = "px"
    metadata["scale_x_in_per_px"] = sx
    metadata["scale_y_in_per_px"] = sy
    return normalized


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_component_map() -> dict[str, Any]:
    return load_json(skill_root() / "templates" / "visio_components.json")


def load_style_profiles() -> dict[str, Any]:
    path = skill_root() / "templates" / "style_profiles.json"
    if not path.exists():
        return {"profiles": {}}
    return load_json(path)


def rgb_formula(hex_color: str) -> str:
    color = hex_color.lstrip("#")
    if len(color) != 6:
        raise ValueError(f"Unsupported color value: {hex_color}")
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return f"RGB({r},{g},{b})"


def hex_rgb(hex_color: str) -> tuple[int, int, int]:
    color = hex_color.lstrip("#")
    if len(color) != 6:
        raise ValueError(f"Unsupported color value: {hex_color}")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def rgb_hex(red: int, green: int, blue: int) -> str:
    return f"#{max(0, min(255, red)):02X}{max(0, min(255, green)):02X}{max(0, min(255, blue)):02X}"


def blend_hex_colors(base: str, overlay: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    br, bg, bb = hex_rgb(base)
    or_, og, ob = hex_rgb(overlay)
    return rgb_hex(
        round(br * (1 - amount) + or_ * amount),
        round(bg * (1 - amount) + og * amount),
        round(bb * (1 - amount) + ob * amount),
    )


def merge_style(*styles: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for style in styles:
        if style:
            merged.update(style)
    return merged


def style_bool(style: dict[str, Any], key: str, default: bool = False) -> bool:
    value = style.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"", "0", "false", "no", "off", "none"}


def side_of(endpoint: str, node: dict[str, Any], peer: dict[str, Any]) -> str:
    if ":" in endpoint:
        side = endpoint.split(":", 1)[1]
        return side.split("@", 1)[0]

    node_cx = float(node["x"]) + float(node["w"]) / 2
    node_cy = float(node["y"]) + float(node["h"]) / 2
    peer_cx = float(peer["x"]) + float(peer["w"]) / 2
    peer_cy = float(peer["y"]) + float(peer["h"]) / 2
    dx = peer_cx - node_cx
    dy = peer_cy - node_cy
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "bottom" if dy >= 0 else "top"


def endpoint_position(endpoint: str) -> float | None:
    if "@" not in endpoint:
        return None
    raw_value = endpoint.rsplit("@", 1)[1]
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"Unsupported endpoint position: {raw_value}") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"Endpoint position must be in [0, 1]: {raw_value}")
    return value


def resolve_endpoint(endpoint: str, node: dict[str, Any], peer: dict[str, Any]) -> tuple[float, float]:
    page_x = float(node["x"])
    page_y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    side = side_of(endpoint, node, peer)
    position = endpoint_position(endpoint)

    if node.get("type") == "attention_score_motif":
        motif_point = attention_score_motif_endpoint(node, side, position)
        if motif_point is not None:
            return motif_point

    if side == "left":
        return page_x, page_y + height * (0.5 if position is None else position)
    if side == "right":
        return page_x + width, page_y + height * (0.5 if position is None else position)
    if side == "top":
        return page_x + width * (0.5 if position is None else position), page_y
    if side == "bottom":
        return page_x + width * (0.5 if position is None else position), page_y + height
    if side == "center":
        return page_x + width / 2, page_y + height / 2
    raise ValueError(f"Unsupported endpoint side: {side}")


def node_id_from_endpoint(endpoint: str) -> str:
    return endpoint.split(":", 1)[0]


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


def is_attention_score_motif_endpoint_side(side: str | None) -> bool:
    return bool(side) and str(side).lower() in ATTENTION_SCORE_MOTIF_ENDPOINT_SIDES


def attention_score_motif_geometry(
    node: dict[str, Any],
    style: dict[str, Any] | None = None,
) -> dict[str, float]:
    style = style or {}
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])

    def local_x(name: str, fallback_ratio: float) -> float:
        absolute = node.get(f"{name}_in", style.get(f"{name}_in"))
        if absolute is not None:
            return float(absolute)
        ratio = node.get(f"{name}_ratio", style.get(f"{name}_ratio", fallback_ratio))
        return width * float(ratio)

    def local_y(name: str, fallback_ratio: float) -> float:
        absolute = node.get(f"{name}_in", style.get(f"{name}_in"))
        if absolute is not None:
            return float(absolute)
        ratio = node.get(f"{name}_ratio", style.get(f"{name}_ratio", fallback_ratio))
        return height * float(ratio)

    def local_size(name: str, axis: str, fallback_ratio: float, fallback_value: float | None = None) -> float:
        absolute = node.get(f"{name}_in", style.get(f"{name}_in"))
        if absolute is not None:
            return float(absolute)
        ratio = node.get(f"{name}_ratio", style.get(f"{name}_ratio"))
        if ratio is not None:
            return (width if axis == "x" else height) * float(ratio)
        return float(fallback_value if fallback_value is not None else (width if axis == "x" else height) * fallback_ratio)

    op_size = local_size("operator_size", "y", 0.28, min(width, height) * 0.28)
    op_x = x + local_x("operator_x", 0.08)
    op_y = y + local_y("operator_y", 0.42) - op_size / 2
    grid_w = local_size("grid_w", "x", 0.44)
    grid_h = local_size("grid_h", "y", 0.50)
    grid_x = x + local_x("grid_x", max(0.0, 1.0 - (grid_w / max(width, 1e-9))))
    grid_y = y + local_y("grid_y", max(0.0, (1.0 - (grid_h / max(height, 1e-9))) / 2))

    return {
        "op_x": op_x,
        "op_y": op_y,
        "op_size": op_size,
        "grid_x": grid_x,
        "grid_y": grid_y,
        "grid_w": grid_w,
        "grid_h": grid_h,
    }


def attention_score_motif_endpoint(
    node: dict[str, Any],
    side: str,
    position: float | None = None,
    style: dict[str, Any] | None = None,
) -> tuple[float, float] | None:
    raw_side = str(side).lower()
    if not is_attention_score_motif_endpoint_side(raw_side):
        return None
    normalized = raw_side
    for prefix in ("operator_", "op_", "mul_"):
        if normalized.startswith(prefix):
            normalized = "operator_" + normalized[len(prefix) :]
            break

    geom = attention_score_motif_geometry(node, style)
    if normalized.startswith("operator_"):
        box = (geom["op_x"], geom["op_y"], geom["op_size"], geom["op_size"])
        anchor = normalized.removeprefix("operator_")
    else:
        box = (geom["grid_x"], geom["grid_y"], geom["grid_w"], geom["grid_h"])
        anchor = normalized.removeprefix("grid_")

    x, y, width, height = box
    ratio = 0.5 if position is None else max(0.0, min(1.0, float(position)))
    if anchor == "left":
        return x, y + height * ratio
    if anchor == "right":
        return x + width, y + height * ratio
    if anchor == "top":
        return x + width * ratio, y
    if anchor == "bottom":
        return x + width * ratio, y + height
    if anchor == "center":
        return x + width / 2, y + height / 2
    return None


def route_side_for_endpoint_side(side: str) -> str:
    raw_side = str(side).lower()
    if raw_side in {"left", "right", "top", "bottom", "center", "point"}:
        return raw_side
    for suffix in ("left", "right", "top", "bottom", "center"):
        if raw_side.endswith(f"_{suffix}"):
            return suffix
    return raw_side


def point_from_value(value: Any, description: str) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{description} must be [x, y].")
    return float(value[0]), float(value[1])


def edge_point(edge: dict[str, Any], endpoint_name: str) -> tuple[float, float] | None:
    return point_from_value(
        edge.get(f"{endpoint_name}_point"),
        f"Edge `{edge.get('id', '<unknown>')}` {endpoint_name}_point",
    )


def edge_named_point(edge: dict[str, Any], key: str) -> tuple[float, float] | None:
    return point_from_value(edge.get(key), f"Edge `{edge.get('id', '<unknown>')}` {key}")


def append_distinct_point(points: list[tuple[float, float]], point: tuple[float, float] | None) -> None:
    if point is None:
        return
    if points and math.hypot(points[-1][0] - point[0], points[-1][1] - point[1]) <= 1e-9:
        return
    points.append(point)


def fake_node_at(point: tuple[float, float]) -> dict[str, float]:
    return {"x": point[0], "y": point[1], "w": 0.0, "h": 0.0}


def node_center_point(node: dict[str, Any]) -> tuple[float, float]:
    return float(node["x"]) + float(node["w"]) / 2, float(node["y"]) + float(node["h"]) / 2


def resolve_edge_endpoint(
    edge: dict[str, Any],
    endpoint_name: str,
    peer_point: tuple[float, float],
    nodes_by_id: dict[str, dict[str, Any]],
) -> tuple[float, float]:
    point = edge_point(edge, endpoint_name)
    if point is not None:
        return point

    endpoint = edge.get(endpoint_name)
    if not isinstance(endpoint, str):
        raise ValueError(f"Edge `{edge.get('id', '<unknown>')}` requires `{endpoint_name}` or `{endpoint_name}_point`.")
    node = nodes_by_id[node_id_from_endpoint(endpoint)]
    return resolve_endpoint(endpoint, node, fake_node_at(peer_point))


def to_visio_y(page_height: float, scene_y: float) -> float:
    return page_height - scene_y


def try_set_formula(shape: Any, cell_name: str, formula: str) -> None:
    try:
        shape.CellsU(cell_name).FormulaU = formula
    except Exception:
        return


def try_set_result(shape: Any, cell_name: str, value: float | int) -> None:
    try:
        shape.CellsU(cell_name).ResultIU = value
    except Exception:
        return


def try_set_text(shape: Any, text: str) -> None:
    try:
        shape.Text = text
    except Exception:
        return


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


def approximate_text_width(text: str, font_size_pt: float) -> float:
    return sum(text_width_factor(char) for char in str(text)) * font_size_pt / 72.0


def approximate_text_height(text: str, font_size_pt: float) -> float:
    lines = str(text).splitlines() or [""]
    return max(1, len(lines)) * font_size_pt / 72.0 * 1.18


def single_line_text_style(style: dict[str, Any], min_font_size_pt: float | None = None) -> dict[str, Any]:
    merged = dict(style)
    merged.setdefault("text_fit", "single_line")
    if min_font_size_pt is not None:
        merged.setdefault("min_font_size_pt", min_font_size_pt)
    merged.setdefault("text_box_policy", "fit_inside")
    merged.setdefault("constrain_text_box", True)
    merged.setdefault("expand_text_box_for_single_line", False)
    return merged


TEXT_FIT_OFF = {"", "none", "off", "false", "0", "no"}
TEXT_FIT_WIDTH_MODES = {"shrink", "shrink_to_fit", "fit", "single_line", "no_wrap", "nowrap", "math_label"}
TEXT_FIT_HEIGHT_MODES = {"shrink", "shrink_to_fit", "fit", "multi_line"}
TEXT_FIT_SINGLE_LINE_MODES = {"single_line", "no_wrap", "nowrap", "math_label"}
COMPACT_SUBSCRIPT_CHARS = {
    "0": "₀",
    "1": "₁",
    "2": "₂",
    "3": "₃",
    "4": "₄",
    "5": "₅",
    "6": "₆",
    "7": "₇",
    "8": "₈",
    "9": "₉",
    "+": "₊",
    "-": "₋",
    "=": "₌",
    "(": "₍",
    ")": "₎",
    "a": "ₐ",
    "e": "ₑ",
    "h": "ₕ",
    "i": "ᵢ",
    "j": "ⱼ",
    "k": "ₖ",
    "l": "ₗ",
    "m": "ₘ",
    "n": "ₙ",
    "o": "ₒ",
    "p": "ₚ",
    "r": "ᵣ",
    "s": "ₛ",
    "t": "ₜ",
    "u": "ᵤ",
    "v": "ᵥ",
    "x": "ₓ",
    "A": "ᴬ",
    "B": "ᴮ",
    "D": "ᴰ",
    "E": "ᴱ",
    "G": "ᴳ",
    "H": "ᴴ",
    "I": "ᴵ",
    "J": "ᴶ",
    "K": "ᴷ",
    "L": "ᴸ",
    "M": "ᴹ",
    "N": "ᴺ",
    "O": "ᴼ",
    "P": "ᴾ",
    "R": "ᴿ",
    "S": "ˢ",
    "T": "ᵀ",
    "U": "ᵁ",
    "V": "ⱽ",
    "W": "ᵂ",
    "w": "ʷ",
}
COMPACT_SUBSCRIPT_SAFE_CHARS = set("0123456789+-=()_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
COMPACT_SUBSCRIPT_TRUE_CHARS = set("0123456789+-=()_aehijklmnoprstuvx")
COMBINING_CIRCUMFLEX = "\u0302"


def explicit_text_fit_mode(style: dict[str, Any]) -> str:
    value = style.get("text_fit", style.get("fit_text"))
    if value is None:
        return ""
    return str(value).lower()


def auto_text_fit_mode(text: Any, style: dict[str, Any]) -> str:
    mode = explicit_text_fit_mode(style)
    if mode:
        return mode
    auto_value = style.get("auto_text_fit", True)
    if auto_value is False or str(auto_value).lower() in {"false", "0", "no", "off"}:
        return "none"

    raw_text = str(text or "").strip()
    if not raw_text:
        return "none"
    if "\n" in raw_text or "\r" in raw_text:
        return "shrink_to_fit"

    compact = re.sub(r"\s+", " ", raw_text)
    if len(compact) <= 14:
        return "single_line"
    if any(ord(char) > 255 for char in compact) and len(compact) <= 18:
        return "single_line"
    if re.search(r"[_=×+\-*/(){}\[\]^]", compact) and len(compact) <= 28:
        return "single_line"
    if re.fullmatch(r"[A-Za-z0-9 .:+/#-]{1,24}", compact):
        return "single_line"
    return "none"


def text_lines_for_fit(text: Any, mode: str) -> list[str]:
    raw_text = str(text or "")
    if mode in TEXT_FIT_SINGLE_LINE_MODES:
        return [raw_text.replace("\r", " ").replace("\n", " ")]
    return raw_text.splitlines() or [raw_text]


def fit_text_font_size(
    text: Any,
    style: dict[str, Any],
    box_width: float | None,
    box_height: float | None,
) -> float | None:
    font_size = style.get("font_size_pt")
    if font_size is None:
        return None
    try:
        current = float(font_size)
    except (TypeError, ValueError):
        return None

    mode = auto_text_fit_mode(text, style)
    if mode in TEXT_FIT_OFF:
        return current

    min_font = float(style.get("min_font_size_pt", style.get("text_min_font_size_pt", max(6.0, current * 0.55))))
    max_font = float(style.get("max_font_size_pt", current))
    fitted = min(current, max_font)
    text_angle = float(style.get("text_angle_deg", 0) or 0)
    rotated = abs((text_angle % 180) - 90) <= 1e-3
    raw_text = str(text or "")
    if not raw_text:
        return fitted

    margin = float(style.get("text_fit_margin_in", style.get("text_margin_in", 0.02)) or 0.0)
    width_safety = float(style.get("text_width_safety_factor", style.get("single_line_width_safety_factor", 1.10)) or 1.0)
    if any(ord(char) > 255 for char in raw_text):
        width_safety = max(width_safety, float(style.get("cjk_text_width_safety_factor", 1.18) or 1.18))
    available_w = None if box_width is None else max(0.01, box_width - margin * 2)
    available_h = None if box_height is None else max(0.01, box_height - margin * 2)
    if rotated:
        available_w, available_h = available_h, available_w

    if mode in TEXT_FIT_WIDTH_MODES:
        widest = max(approximate_text_width(line, fitted) * width_safety for line in text_lines_for_fit(raw_text, mode))
        if available_w is not None and widest > available_w:
            fitted *= available_w / widest
    if mode in TEXT_FIT_HEIGHT_MODES:
        text_h = approximate_text_height(raw_text, fitted)
        if available_h is not None and text_h > available_h:
            fitted *= available_h / text_h
    elif mode in TEXT_FIT_SINGLE_LINE_MODES:
        text_h = fitted / 72.0 * 1.18
        if available_h is not None and text_h > available_h:
            fitted *= available_h / text_h

    return max(min_font, min(current, fitted))


def normalize_loss_formula_text(text: str) -> str:
    text = str(text)

    def replace_loss(match: re.Match[str]) -> str:
        return f"L_{match.group(1).lower()}"

    return re.sub(r"\bL\s*_?\s*(adv|rec)\b", replace_loss, text, flags=re.IGNORECASE)


def compact_subscript_text(value: str) -> str:
    return "".join(COMPACT_SUBSCRIPT_CHARS.get(char, char) for char in value if char != "_")


def readable_subscript_text(value: str) -> str:
    return "".join(char for char in str(value) if char != "_")


def supports_compact_subscript(value: str) -> bool:
    return all(char in COMPACT_SUBSCRIPT_SAFE_CHARS for char in value)


def supports_true_compact_subscript(value: str) -> bool:
    return all(char == "_" or char in COMPACT_SUBSCRIPT_TRUE_CHARS for char in value)


def lines_support_compact_subscripts(lines: list[list[dict[str, Any]]]) -> bool:
    for line in lines:
        for fragment in line:
            if fragment.get("subscript") and not supports_true_compact_subscript(str(fragment.get("text", ""))):
                return False
    return True


def lines_have_word_subscripts(lines: list[list[dict[str, Any]]]) -> bool:
    return any(
        bool(fragment.get("subscript")) and len(str(fragment.get("text", "")).replace("_", "")) > 1
        for line in lines
        for fragment in line
    )


def compact_math_display_text(text: str) -> str:
    text = normalize_loss_formula_text(str(text))

    def replace_subscript(match: re.Match[str]) -> str:
        base = match.group(1)
        subscript = compact_subscript_text(match.group(2))
        prime = match.group(3) or ""
        return f"{base}{subscript}{prime}"

    return re.sub(r"([A-Za-zα-ωΑ-Ω])_([A-Za-z0-9_]+)([′']*)", replace_subscript, text)


def fragments_to_compact_math_text(line: list[dict[str, Any]]) -> str:
    output: list[str] = []
    for fragment in line:
        text = str(fragment.get("text", ""))
        if fragment.get("subscript"):
            output.append(compact_subscript_text(text))
        else:
            output.append(text)
        if fragment.get("hat"):
            output.append(COMBINING_CIRCUMFLEX)
    return "".join(output)


def fragments_to_plain_math_text(line: list[dict[str, Any]]) -> str:
    output: list[str] = []
    for fragment in line:
        text = str(fragment.get("text", ""))
        if fragment.get("subscript"):
            output.append("_")
            output.append(readable_subscript_text(text))
        else:
            output.append(text)
        if fragment.get("hat"):
            output.append("^")
    return "".join(output)


def requires_plain_math_fallback(lines: list[list[dict[str, Any]]], width: float, height: float, base_font: float, style: dict[str, Any]) -> bool:
    min_fragment_w = float(style.get("min_fragment_box_width_in", 0.05) or 0.05)
    fragment_pad = float(style.get("fragment_pad_in", 0.006) or 0.006)
    subscript_pad = float(style.get("subscript_pad_in", 0.002) or 0.002)
    subscript_box_pad = float(style.get("subscript_box_pad_in", 0.045) or 0.045)
    subscript_scale = float(style.get("subscript_scale", 0.72) or 0.72)
    width_safety = float(style.get("math_fragment_width_safety_factor", style.get("single_line_width_safety_factor", 1.35)) or 1.35)
    subscript_width_safety = float(style.get("subscript_width_safety_factor", max(width_safety, 2.20)) or max(width_safety, 2.20))
    subscript_font = max(1.0, base_font * subscript_scale)
    widest = 0.0
    for line in lines:
        line_w = 0.0
        for index, fragment in enumerate(line):
            text = str(fragment.get("text", ""))
            is_subscript = bool(fragment.get("subscript"))
            next_is_subscript = index + 1 < len(line) and bool(line[index + 1].get("subscript"))
            if is_subscript:
                line_w += max(min_fragment_w, approximate_text_width(text, subscript_font) * subscript_width_safety + subscript_box_pad) + subscript_pad
            elif next_is_subscript and len(text.strip()) == 1:
                line_w += max(min_fragment_w, approximate_text_width(text, base_font) * width_safety + min(fragment_pad, 0.004))
            else:
                line_w += max(min_fragment_w, approximate_text_width(text, base_font) * width_safety + fragment_pad)
        widest = max(widest, line_w)
    line_h = base_font / 72.0 * 1.18
    total_h = len(lines) * line_h + max(0, len(lines) - 1) * float(style.get("line_gap_in", 0.035) or 0.035)
    return widest > width * 1.35 or total_h > height * 1.35


def is_probable_math_base(token: str) -> bool:
    return token in {"L", "q", "k", "v", "Q", "K", "V", "f", "g", "h", "x", "y", "z", "s", "p", "P", "w", "W", "b", "B"}


def parse_plain_math_segment(segment: str) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    buffer: list[str] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if index + 1 < len(segment) and segment[index + 1] == COMBINING_CIRCUMFLEX and re.match(r"[A-Za-z]", char):
            if buffer:
                fragments.append({"text": "".join(buffer), "subscript": False})
                buffer = []
            fragments.append({"text": char, "subscript": False, "hat": True})
            index += 2
            continue
        buffer.append(char)
        index += 1
    if buffer:
        fragments.append({"text": "".join(buffer), "subscript": False})
    return fragments


def line_has_hat_fragment(lines: list[list[dict[str, Any]]]) -> bool:
    return any(bool(fragment.get("hat")) for line in lines for fragment in line)


def parse_math_text_line(line: str) -> list[dict[str, Any]]:
    line = normalize_loss_formula_text(line)
    fragments: list[dict[str, Any]] = []
    cursor = 0
    for match in re.finditer(r"([A-Za-zα-ωΑ-Ω])_([A-Za-z0-9_]+)([′']*)", line):
        if match.start() > cursor:
            fragments.extend(parse_plain_math_segment(line[cursor : match.start()]))
        base = match.group(1)
        fragments.append({"text": base, "subscript": False})
        fragments.append({"text": match.group(2), "subscript": True})
        if match.group(3):
            fragments.append({"text": match.group(3), "subscript": False})
        cursor = match.end()
    if cursor < len(line):
        fragments.extend(parse_plain_math_segment(line[cursor:]))
    return [fragment for fragment in fragments if fragment.get("text")]


def arrow_size_value(value: Any, segment_length: float | None = None) -> int:
    if isinstance(value, (int, float)):
        return max(0, min(6, int(value)))
    if isinstance(value, str):
        mapped = {
            "tiny": 0,
            "xsmall": 0,
            "small": 1,
            "medium": 2,
            "normal": 2,
            "large": 3,
            "xlarge": 4,
        }.get(value.lower())
        if mapped is not None:
            return mapped
    if segment_length is not None:
        if segment_length < 0.16:
            return 0
        if segment_length < 0.30:
            return 1
    return 2


def nonzero_extent(value: Any) -> bool:
    try:
        return float(value) > 1e-6
    except (TypeError, ValueError):
        return False


def font_style_value(style: dict[str, Any]) -> int:
    value = 0
    weight = style.get("font_weight")
    if isinstance(weight, str) and weight.lower() in {"bold", "semibold", "heavy"}:
        value |= 1
    if isinstance(weight, (int, float)) and weight >= 600:
        value |= 1
    if style.get("font_italic"):
        value |= 2
    return value


def apply_shadow(shape: Any, shadow: dict[str, Any] | bool | None) -> None:
    if not shadow:
        return
    if shadow is True:
        shadow = {}

    try_set_formula(shape, "ShdwPattern", "1")
    try_set_formula(shape, "ShdwForegnd", rgb_formula(str(shadow.get("color", "#000000"))))
    try_set_formula(shape, "ShdwOffsetX", f"{float(shadow.get('offset_x_in', 0.04))} in")
    try_set_formula(shape, "ShdwOffsetY", f"{float(shadow.get('offset_y_in', -0.04))} in")
    transparency = shadow.get("transparency_pct", 78)
    try_set_formula(shape, "ShdwForegndTrans", f"{float(transparency)}%")


def apply_style(
    shape: Any,
    style: dict[str, Any],
    text: Any = "",
    box_width: float | None = None,
    box_height: float | None = None,
) -> None:
    fill = style.get("fill")
    if fill == "none":
        try_set_result(shape, "FillPattern", 0)
    elif fill:
        try_set_result(shape, "FillPattern", 1)
        try_set_formula(shape, "FillForegnd", rgb_formula(str(fill)))

    fill_transparency = style.get("fill_transparency_pct")
    if fill_transparency is not None:
        try_set_formula(shape, "FillForegndTrans", f"{float(fill_transparency)}%")

    line = style.get("line")
    if line == "none":
        try_set_result(shape, "LinePattern", 0)
    elif line:
        try_set_result(shape, "LinePattern", 1)
        try_set_formula(shape, "LineColor", rgb_formula(str(line)))

    line_transparency = style.get("line_transparency_pct")
    if line_transparency is not None:
        try_set_formula(shape, "LineColorTrans", f"{float(line_transparency)}%")

    line_weight = style.get("line_weight_pt")
    if line_weight is not None:
        try_set_formula(shape, "LineWeight", f"{float(line_weight)} pt")

    line_dash = str(style.get("line_dash", "")).lower()
    if line != "none":
        if line_dash in {"dash", "short_dash", "short-dash", "tight_dash", "tiny_dash"}:
            try_set_result(shape, "LinePattern", 2)
        elif line_dash == "dot":
            try_set_result(shape, "LinePattern", 3)
        elif line_dash == "long_dash":
            try_set_result(shape, "LinePattern", 7)
        elif line_dash in {"dash_dot", "dash-dot"}:
            try_set_result(shape, "LinePattern", 5)

    rounding = style.get("rounding_in")
    if rounding is not None:
        try_set_formula(shape, "Rounding", f"{float(rounding)} in")

    text_color = style.get("text_color")
    if text_color:
        try_set_formula(shape, "Char.Color", rgb_formula(str(text_color)))

    font_size = fit_text_font_size(text, style, box_width, box_height)
    if font_size is not None:
        try_set_formula(shape, "Char.Size", f"{float(font_size)} pt")

    font_resolution = font_resolution_for_style(style, text)
    font_family = font_resolution.resolved or style.get("font_family")
    if font_family:
        try_set_formula(shape, "Char.Font", f'FONT("{font_family}")')

    char_style = font_style_value(style)
    if char_style:
        try_set_result(shape, "Char.Style", char_style)
    elif "font_weight" in style or "font_italic" in style:
        try_set_result(shape, "Char.Style", 0)

    text_angle = style.get("text_angle_deg")
    rotated_text_box = False
    if text_angle is not None:
        rotated_text_box = abs((float(text_angle) % 180) - 90) <= 1e-3
        try_set_formula(shape, "TxtAngle", f"{float(text_angle)} deg")
    text_box_width = style.get("text_box_width_in")
    if text_box_width is not None:
        try_set_formula(shape, "TxtWidth", f"{float(text_box_width)} in")
    text_box_height = style.get("text_box_height_in")
    if text_box_height is not None:
        try_set_formula(shape, "TxtHeight", f"{float(text_box_height)} in")
    if auto_text_fit_mode(text, style) in TEXT_FIT_SINGLE_LINE_MODES:
        display_text = str(text or "").replace("\r", " ").replace("\n", " ")
        if display_text != str(text or ""):
            try_set_text(shape, display_text)
        if rotated_text_box and text_box_width is None and text_box_height is None:
            fitted_txt_width = box_height
            fitted_txt_height = box_width
        else:
            fitted_txt_width = text_box_width or box_width
            fitted_txt_height = text_box_height or box_height
        if str(text or "").strip():
            width_safety = float(style.get("text_width_safety_factor", style.get("single_line_width_safety_factor", 1.10)) or 1.0)
            if any(ord(char) > 255 for char in str(text)):
                width_safety = max(width_safety, float(style.get("cjk_text_width_safety_factor", 1.18) or 1.18))
            estimated_width = approximate_text_width(str(text), float(font_size or style.get("font_size_pt", 10) or 10)) * width_safety
            text_margin = float(style.get("text_margin_in", style.get("text_fit_margin_in", 0.02)) or 0.0)
            min_single_line_width = estimated_width + text_margin * 2 + 0.02
            expand_text_box = style_bool(style, "expand_text_box_for_single_line", True)
            if style_bool(style, "constrain_text_box", False) or str(style.get("text_box_policy", "")).lower() in {
                "fit_inside",
                "inside",
                "constrain",
                "fixed",
            }:
                expand_text_box = False
            if expand_text_box:
                fitted_txt_width = max(float(fitted_txt_width or 0.01), min_single_line_width)
        try_set_formula(shape, "TxtWidth", f"{float(fitted_txt_width or 0.01)} in")
        try_set_formula(shape, "TxtHeight", f"{float(fitted_txt_height or 0.01)} in")

    angle = style.get("angle_deg")
    if angle is not None:
        try_set_formula(shape, "Angle", f"{float(angle)} deg")

    try_set_result(shape, "Para.HorzAlign", int(style.get("text_align", 1)))
    try_set_result(shape, "VerticalAlign", int(style.get("vertical_align", 1)))
    margin_cells = {
        "TxtMarginLeft": style.get("text_margin_left_in", style.get("text_margin_in")),
        "TxtMarginRight": style.get("text_margin_right_in", style.get("text_margin_in")),
        "TxtMarginTop": style.get("text_margin_top_in", style.get("text_margin_in")),
        "TxtMarginBottom": style.get("text_margin_bottom_in", style.get("text_margin_in")),
    }
    for cell_name, margin in margin_cells.items():
        if margin is not None:
            try_set_formula(shape, cell_name, f"{float(margin)} in")
    apply_shadow(shape, style.get("shadow"))


def draw_rectangle(page: Any, page_height: float, node: dict[str, Any]) -> Any:
    x1 = float(node["x"])
    y1 = to_visio_y(page_height, float(node["y"]) + float(node["h"]))
    x2 = float(node["x"]) + float(node["w"])
    y2 = to_visio_y(page_height, float(node["y"]))
    return page.DrawRectangle(x1, y1, x2, y2)


def draw_visio_polyline(page: Any, values: list[float], tolerance: float = 0.0) -> Any:
    last_error: Exception | None = None
    for args in ((values, tolerance, 0), (values, tolerance), (values,)):
        try:
            return page.DrawPolyline(*args)
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("DrawPolyline failed without an exception.")


def draw_visio_bezier(page: Any, values: list[float], tolerance: float = 0.0) -> Any:
    last_error: Exception | None = None
    for args in ((values, tolerance, 0), (values, tolerance), (values,)):
        try:
            return page.DrawBezier(*args)
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("DrawBezier failed without an exception.")


def catmull_rom_points(points: list[tuple[float, float]], samples_per_segment: int = 10) -> list[tuple[float, float]]:
    if len(points) < 4:
        return points
    smoothed: list[tuple[float, float]] = []
    for index in range(len(points) - 1):
        p0 = points[max(0, index - 1)]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[min(len(points) - 1, index + 2)]
        if index == 0:
            smoothed.append(p1)
        for step in range(1, samples_per_segment + 1):
            t = step / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                (2 * p1[0])
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                (2 * p1[1])
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            smoothed.append((x, y))
    return smoothed


def cubic_bezier_sample_points(points: list[tuple[float, float]], samples_per_curve: int = 12) -> list[tuple[float, float]]:
    if len(points) < 4 or (len(points) - 1) % 3 != 0:
        return points
    samples = max(3, int(samples_per_curve))
    sampled: list[tuple[float, float]] = [points[0]]
    for index in range(1, len(points), 3):
        if index + 2 >= len(points):
            break
        p0 = sampled[-1]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[index + 2]
        for step in range(1, samples + 1):
            t = step / samples
            mt = 1.0 - t
            x = (
                mt * mt * mt * p0[0]
                + 3 * mt * mt * t * p1[0]
                + 3 * mt * t * t * p2[0]
                + t * t * t * p3[0]
            )
            y = (
                mt * mt * mt * p0[1]
                + 3 * mt * mt * t * p1[1]
                + 3 * mt * t * t * p2[1]
                + t * t * t * p3[1]
            )
            sampled.append((x, y))
    return sampled


def rounded_orthogonal_points(
    points: list[tuple[float, float]],
    corner_radius: float,
    samples_per_corner: int = 5,
) -> list[tuple[float, float]]:
    if len(points) < 3 or corner_radius <= 0:
        return points

    def unit_vector(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float] | None:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return None
        return dx / length, dy / length

    def append_unique(target: list[tuple[float, float]], point: tuple[float, float]) -> None:
        if target and math.hypot(target[-1][0] - point[0], target[-1][1] - point[1]) <= 1e-9:
            return
        target.append(point)

    rounded: list[tuple[float, float]] = [points[0]]
    for index in range(1, len(points) - 1):
        prev_point = points[index - 1]
        corner = points[index]
        next_point = points[index + 1]
        in_dir = unit_vector(prev_point, corner)
        out_dir = unit_vector(corner, next_point)
        if in_dir is None or out_dir is None:
            append_unique(rounded, corner)
            continue

        dot = in_dir[0] * out_dir[0] + in_dir[1] * out_dir[1]
        cross = in_dir[0] * out_dir[1] - in_dir[1] * out_dir[0]
        incoming_axis = abs(in_dir[0]) <= 1e-6 or abs(in_dir[1]) <= 1e-6
        outgoing_axis = abs(out_dir[0]) <= 1e-6 or abs(out_dir[1]) <= 1e-6
        is_right_angle = incoming_axis and outgoing_axis and abs(dot) <= 1e-6 and abs(cross) > 1e-6
        if not is_right_angle:
            append_unique(rounded, corner)
            continue

        incoming_len = math.hypot(corner[0] - prev_point[0], corner[1] - prev_point[1])
        outgoing_len = math.hypot(next_point[0] - corner[0], next_point[1] - corner[1])
        radius = min(corner_radius, incoming_len / 2.0, outgoing_len / 2.0)
        if radius <= 1e-9:
            append_unique(rounded, corner)
            continue

        entry = (corner[0] - in_dir[0] * radius, corner[1] - in_dir[1] * radius)
        exit_point = (corner[0] + out_dir[0] * radius, corner[1] + out_dir[1] * radius)
        center = (corner[0] - in_dir[0] * radius + out_dir[0] * radius, corner[1] - in_dir[1] * radius + out_dir[1] * radius)
        append_unique(rounded, entry)

        start_angle = math.atan2(entry[1] - center[1], entry[0] - center[0])
        end_angle = math.atan2(exit_point[1] - center[1], exit_point[0] - center[0])
        if cross > 0 and end_angle <= start_angle:
            end_angle += math.tau
        elif cross < 0 and end_angle >= start_angle:
            end_angle -= math.tau

        steps = max(2, int(samples_per_corner))
        for step in range(1, steps + 1):
            t = step / steps
            angle = start_angle + (end_angle - start_angle) * t
            append_unique(rounded, (center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius))

    append_unique(rounded, points[-1])
    return rounded


def draw_polygon_from_points(page: Any, page_height: float, points: list[tuple[float, float]]) -> Any:
    if len(points) < 3:
        raise ValueError("polygon nodes require at least three points.")

    closed_points = [*points]
    if closed_points[0] != closed_points[-1]:
        closed_points.append(closed_points[0])

    values: list[float] = []
    for x, y in closed_points:
        values.extend([float(x), to_visio_y(page_height, float(y))])

    try:
        return draw_visio_polyline(page, values, 0.0)
    except Exception:
        first_shape = None
        line_style = {"fill": "none", "line": "#111111", "line_weight_pt": 1.0, "end_arrow": "none"}
        for start, end in zip(closed_points, closed_points[1:]):
            first_shape = draw_line_segment(page, page_height, start, end, line_style)
        return first_shape


def node_polygon_points(node: dict[str, Any]) -> list[tuple[float, float]]:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    raw_points = node.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError(f"polygon node `{node.get('id', '<unknown>')}` requires `points`.")

    points: list[tuple[float, float]] = []
    for point in raw_points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"polygon node `{node.get('id', '<unknown>')}` has invalid point `{point}`.")
        px = x + relative_or_absolute(point[0], width)
        py = y + relative_or_absolute(point[1], height)
        points.append((px, py))
    return points


def draw_polygon_node(page: Any, page_height: float, node: dict[str, Any]) -> Any:
    return draw_polygon_from_points(page, page_height, node_polygon_points(node))


def draw_trapezoid_node(page: Any, page_height: float, node: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", "right")).lower()
    taper = max(0.0, min(0.49, float(node.get("taper_ratio", node.get("taper", 0.22)))))
    pointed = bool(node.get("pointed", False))

    if orientation == "right":
        points = [(x, y), (x + width, y + height / 2), (x, y + height)] if pointed else [
            (x, y),
            (x + width, y + height * taper),
            (x + width, y + height * (1 - taper)),
            (x, y + height),
        ]
    elif orientation == "left":
        points = [(x + width, y), (x, y + height / 2), (x + width, y + height)] if pointed else [
            (x + width, y),
            (x, y + height * taper),
            (x, y + height * (1 - taper)),
            (x + width, y + height),
        ]
    elif orientation == "down":
        points = [(x, y), (x + width, y), (x + width / 2, y + height)] if pointed else [
            (x, y),
            (x + width, y),
            (x + width * (1 - taper), y + height),
            (x + width * taper, y + height),
        ]
    elif orientation == "up":
        points = [(x, y + height), (x + width, y + height), (x + width / 2, y)] if pointed else [
            (x + width * taper, y),
            (x + width * (1 - taper), y),
            (x + width, y + height),
            (x, y + height),
        ]
    else:
        raise ValueError(f"Unsupported trapezoid orientation: {orientation}")
    return draw_polygon_from_points(page, page_height, points)


def draw_dual_wing_encoder(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    shape_mode = str(node.get("shape_mode", node.get("mode", style.get("shape_mode", "three_part")))).lower()
    center_ratio = max(0.05, min(0.65, float(node.get("center_ratio", style.get("center_ratio", 0.18)))))
    center_w = float(node.get("center_w_in", style.get("center_w_in", width * center_ratio)))
    center_w = max(0.01, min(width * 0.8, center_w))
    wing_w = max(0.01, (width - center_w) / 2)
    taper = max(0.0, min(0.45, float(node.get("taper_ratio", style.get("taper_ratio", 0.18)))))
    center_x = x + wing_w

    line = node.get("line", style.get("line", "#111111"))
    line_weight = node.get("line_weight_pt", style.get("line_weight_pt", 1.0))
    left_style = merge_style(
        style,
        {
            "fill": node.get("left_fill", style.get("left_fill", style.get("fill", "#7DB7E6"))),
            "line": line,
            "line_weight_pt": line_weight,
        },
        node.get("left_style") if isinstance(node.get("left_style"), dict) else None,
    )
    center_style = merge_style(
        style,
        {
            "fill": node.get("center_fill", style.get("center_fill", "#F4D35E")),
            "line": line,
            "line_weight_pt": line_weight,
        },
        node.get("center_style") if isinstance(node.get("center_style"), dict) else None,
    )
    right_style = merge_style(
        style,
        {
            "fill": node.get("right_fill", style.get("right_fill", style.get("fill", "#7DB7E6"))),
            "line": line,
            "line_weight_pt": line_weight,
        },
        node.get("right_style") if isinstance(node.get("right_style"), dict) else None,
    )

    raw_points = node.get("points")
    use_custom_points = isinstance(raw_points, list) and bool(raw_points) and style_bool(
        merge_style(style, node.get("style") if isinstance(node.get("style"), dict) else None, node),
        "use_points",
        True,
    )
    shape = None
    if use_custom_points:
        local_points: list[tuple[float, float]] = []
        for point in raw_points:
            if not isinstance(point, list) or len(point) != 2:
                continue
            px = float(point[0])
            py = float(point[1])
            local_points.append(
                (
                    x + (px * width if -1.0 <= px <= 1.0 else px),
                    y + (py * height if -1.0 <= py <= 1.0 else py),
                )
            )
        if len(local_points) >= 3:
            split_axis = str(node.get("split_axis", style.get("split_axis", ""))).lower()
            if split_axis in {"vertical", "x", "left_right"}:
                split_ratio = max(0.02, min(0.98, float(node.get("split_ratio", style.get("split_ratio", 0.58)))))
                center_strip_w = float(node.get("center_strip_w_in", style.get("center_strip_w_in", 0.0)) or 0.0)
                split_x = x + width * split_ratio
                left_points = [point for point in local_points if point[0] <= split_x + 1e-6]
                left_points.extend([(split_x, y + height), (split_x, y)])
                left_points = sorted(left_points, key=lambda point: math.atan2(point[1] - (y + height / 2), point[0] - (x + width * 0.25)))
                right_points = [point for point in local_points if point[0] >= split_x - 1e-6]
                right_points.extend([(split_x, y), (split_x, y + height)])
                right_points = sorted(right_points, key=lambda point: math.atan2(point[1] - (y + height / 2), point[0] - (x + width * 0.75)))
                if len(left_points) >= 3:
                    left_shape = draw_polygon_from_points(page, page_height, left_points)
                    apply_style(left_shape, left_style)
                if len(right_points) >= 3:
                    right_shape = draw_polygon_from_points(page, page_height, right_points)
                    apply_style(right_shape, right_style)
                if center_strip_w > 0:
                    strip_x = x + width * split_ratio - center_strip_w / 2
                    center = draw_rectangle(page, page_height, {"x": strip_x, "y": y, "w": center_strip_w, "h": height})
                    apply_style(center, center_style)
                    shape = center
                else:
                    shape = draw_polygon_from_points(page, page_height, local_points)
            else:
                shape = draw_polygon_from_points(page, page_height, local_points)
                apply_style(shape, merge_style(style, {"fill": node.get("fill", style.get("fill", "#B9C9E8")), "line": line, "line_weight_pt": line_weight}))
            if truthy(node.get("draw_center_strip", style.get("draw_center_strip")), False):
                strip_x = x + width * float(node.get("center_strip_x", style.get("center_strip_x", 0.46)))
                strip_w = float(node.get("center_strip_w_in", style.get("center_strip_w_in", center_w)))
                strip_y = y + height * float(node.get("center_strip_y", style.get("center_strip_y", 0.0)))
                strip_h = height * float(node.get("center_strip_h", style.get("center_strip_h", 1.0)))
                center = draw_rectangle(page, page_height, {"x": strip_x, "y": strip_y, "w": strip_w, "h": strip_h})
                apply_style(center, center_style)
                shape = center

    if shape is None and shape_mode in {"opposing_trapezoids", "opposing", "hourglass", "bow_tie", "bowtie", "pinched"}:
        waist_h_ratio = max(0.04, min(0.90, float(node.get("waist_height_ratio", style.get("waist_height_ratio", 0.24)))))
        waist_top = y + height * (0.5 - waist_h_ratio / 2)
        waist_bottom = y + height * (0.5 + waist_h_ratio / 2)
        center_y = float(node.get("center_y_in", style.get("center_y_in", waist_top)))
        center_h = float(node.get("center_h_in", style.get("center_h_in", waist_bottom - waist_top)))
        center_h = max(0.01, min(height, center_h))
        center_y = max(y, min(y + height - center_h, center_y))
        center_node = {"x": center_x, "y": center_y, "w": center_w, "h": center_h}
        edge_notch = float(node.get("edge_notch_in", style.get("edge_notch_in", 0.0)) or 0.0)
        left_points = [
            (x + edge_notch, y + height * taper),
            (center_x, center_y),
            (center_x, center_y + center_h),
            (x + edge_notch, y + height * (1 - taper)),
        ]
        right_points = [
            (center_x + center_w, center_y),
            (x + width - edge_notch, y + height * taper),
            (x + width - edge_notch, y + height * (1 - taper)),
            (center_x + center_w, center_y + center_h),
        ]
        left = draw_polygon_from_points(page, page_height, left_points)
        apply_style(left, left_style)
        center = draw_rectangle(page, page_height, center_node)
        apply_style(center, center_style)
        right = draw_polygon_from_points(page, page_height, right_points)
        apply_style(right, right_style)
        shape = right

    if shape is None:
        left_points = [
            (x, y + height * taper),
            (center_x, y),
            (center_x, y + height),
            (x, y + height * (1 - taper)),
        ]
        right_points = [
            (center_x + center_w, y),
            (x + width, y + height * taper),
            (x + width, y + height * (1 - taper)),
            (center_x + center_w, y + height),
        ]
        center_node = {"x": center_x, "y": y, "w": center_w, "h": height}
        left = draw_polygon_from_points(page, page_height, left_points)
        apply_style(left, left_style)
        center = draw_rectangle(page, page_height, center_node)
        apply_style(center, center_style)
        right = draw_polygon_from_points(page, page_height, right_points)
        apply_style(right, right_style)
        shape = right

    text = str(node.get("text", "")).strip()
    if text:
        draw_text_box(
            page,
            page_height,
            x + float(node.get("text_pad_x_in", style.get("text_pad_x_in", 0.02))),
            y + float(node.get("text_pad_y_in", style.get("text_pad_y_in", 0.02))),
            max(0.01, width - float(node.get("text_pad_x_in", style.get("text_pad_x_in", 0.02))) * 2),
            max(0.01, height - float(node.get("text_pad_y_in", style.get("text_pad_y_in", 0.02))) * 2),
            text,
            merge_style(
                style,
                {
                    "fill": "none",
                    "line": "none",
                    "text_fit": node.get("text_fit", style.get("text_fit", "shrink_to_fit")),
                    "constrain_text_box": True,
                },
            ),
        )
    return shape


def darker_fill(color: str, amount: float = 0.18) -> str:
    try:
        return blend_hex_colors(color, "#000000", max(0.0, min(1.0, amount)))
    except Exception:
        return color


def lighter_fill(color: str, amount: float = 0.16) -> str:
    try:
        return blend_hex_colors(color, "#FFFFFF", max(0.0, min(1.0, amount)))
    except Exception:
        return color


def scaled_depth(value: Any, reference: float, fallback_ratio: float) -> float:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if -1.0 <= numeric <= 1.0:
            return numeric * reference
        return numeric
    return reference * fallback_ratio


def tensor_scaled_depth(node: dict[str, Any], style: dict[str, Any], key: str, reference: float, fallback_ratio: float) -> float:
    value = node.get(key, style.get(key))
    if not isinstance(value, (int, float)):
        return reference * fallback_ratio
    numeric = float(value)
    relative_flag = node.get(f"{key}_relative", node.get("depth_is_relative", style.get("depth_is_relative")))
    if relative_flag is False or str(relative_flag).lower() in {"false", "0", "no", "off", "absolute", "in"}:
        return numeric
    if relative_flag is True or str(relative_flag).lower() in {"true", "1", "yes", "on", "relative", "ratio"}:
        return numeric * reference
    if str(node.get("depth_units", style.get("depth_units", ""))).lower() in {"absolute", "inch", "in", "inches"}:
        return numeric
    return scaled_depth(numeric, reference, fallback_ratio)


def tensor_perspective_defaults(
    node: dict[str, Any],
    style: dict[str, Any],
    width: float,
    height: float,
    render_mode: str,
) -> dict[str, float]:
    raw_mode = node.get("perspective_mode", style.get("perspective_mode", ""))
    mode = "" if raw_mode in {None, ""} else str(raw_mode).lower()
    if not mode:
        return {}

    presets: dict[str, dict[str, float]] = {
        "flat": {"depth_x_ratio": 0.02, "depth_y_ratio": -0.015, "layer_dx_scale": -0.08, "layer_dy_scale": 0.08, "skew_scale": 0.05, "sheet_scale": 0.0},
        "front": {"depth_x_ratio": 0.02, "depth_y_ratio": -0.015, "layer_dx_scale": -0.08, "layer_dy_scale": 0.08, "skew_scale": 0.05, "sheet_scale": 0.0},
        "light": {"depth_x_ratio": 0.07, "depth_y_ratio": -0.05, "layer_dx_scale": -0.18, "layer_dy_scale": 0.14, "skew_scale": 0.12, "sheet_scale": 0.0},
        "paper_light": {"depth_x_ratio": 0.07, "depth_y_ratio": -0.05, "layer_dx_scale": -0.18, "layer_dy_scale": 0.14, "skew_scale": 0.12, "sheet_scale": 0.0},
        "medium": {"depth_x_ratio": 0.11, "depth_y_ratio": -0.08, "layer_dx_scale": -0.18, "layer_dy_scale": 0.16, "skew_scale": 0.18, "sheet_scale": 0.0},
        "paper_medium": {"depth_x_ratio": 0.11, "depth_y_ratio": -0.08, "layer_dx_scale": -0.18, "layer_dy_scale": 0.16, "skew_scale": 0.18, "sheet_scale": 0.0},
        "strong": {"depth_x_ratio": 0.18, "depth_y_ratio": -0.13, "layer_dx_scale": -0.22, "layer_dy_scale": 0.18, "skew_scale": 0.22, "sheet_scale": 0.0},
        "heavy": {"depth_x_ratio": 0.18, "depth_y_ratio": -0.13, "layer_dx_scale": -0.22, "layer_dy_scale": 0.18, "skew_scale": 0.22, "sheet_scale": 0.0},
        "source_thin": {"depth_x_ratio": 0.08, "depth_y_ratio": -0.06, "layer_dx_scale": -0.18, "layer_dy_scale": 0.15, "skew_scale": 0.15, "sheet_scale": 0.0},
        "source_thick": {"depth_x_ratio": 0.18, "depth_y_ratio": -0.14, "layer_dx_scale": -0.24, "layer_dy_scale": 0.18, "skew_scale": 0.24, "sheet_scale": 0.0},
    }
    preset = presets.get(mode)
    if not preset:
        return {}

    if render_mode in {"feature_cuboids", "thick_cuboids", "feature_stack", "paper_feature_stack", "thick_feature_map"}:
        preset = dict(preset)
        preset["depth_x_ratio"] *= 1.15
        preset["depth_y_ratio"] *= 1.15
    elif render_mode in {"thin_sheets", "sheets", "front_sheets", "flat_sheets"} and mode in {"flat", "front"}:
        preset = dict(preset)
        preset["depth_x_ratio"] = 0.0
        preset["depth_y_ratio"] = 0.0
        preset["skew_scale"] = 0.0

    depth_x = width * preset["depth_x_ratio"]
    depth_y = height * preset["depth_y_ratio"]
    return {
        "depth_x_in": depth_x,
        "depth_y_in": depth_y,
        "layer_dx_in": abs(depth_x) * preset["layer_dx_scale"],
        "layer_dy_in": abs(depth_y) * preset["layer_dy_scale"],
        "skew_x_in": abs(depth_x) * preset["skew_scale"],
        "sheet_scale": preset["sheet_scale"],
    }


def is_prime_fragment(text: str) -> bool:
    stripped = str(text).strip()
    return bool(stripped) and all(char in {"'", "′"} for char in stripped)


def draw_cuboid_node(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    depth_x = float(node.get("depth_x_in", style.get("depth_x_in", 0.18)))
    depth_y = float(node.get("depth_y_in", style.get("depth_y_in", -0.16)))
    fill = str(node.get("fill", style.get("fill", "#FFFFFF")))
    line = str(node.get("line", style.get("line", "#111111")))
    line_weight = float(node.get("line_weight_pt", style.get("line_weight_pt", 1.0)))
    side_fill = str(node.get("side_fill", style.get("side_fill", darker_fill(fill, 0.18))))
    top_fill = str(node.get("top_fill", style.get("top_fill", lighter_fill(fill, 0.14))))

    top = draw_polygon_from_points(
        page,
        page_height,
        [(x, y), (x + depth_x, y + depth_y), (x + width + depth_x, y + depth_y), (x + width, y)],
    )
    apply_style(top, {"fill": top_fill, "line": line, "line_weight_pt": line_weight})

    side = draw_polygon_from_points(
        page,
        page_height,
        [
            (x + width, y),
            (x + width + depth_x, y + depth_y),
            (x + width + depth_x, y + height + depth_y),
            (x + width, y + height),
        ],
    )
    apply_style(side, {"fill": side_fill, "line": line, "line_weight_pt": line_weight})

    front = draw_rectangle(page, page_height, node)
    return front


def draw_oblique_slab(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    depth_x = float(node.get("depth_x_in", style.get("depth_x_in", 0.18)))
    depth_y = float(node.get("depth_y_in", style.get("depth_y_in", -0.16)))
    skew_x = float(node.get("skew_x_in", style.get("skew_x_in", depth_x * 0.20)))
    fill = str(node.get("fill", style.get("fill", "#FFFFFF")))
    line = str(node.get("line", style.get("line", "#111111")))
    line_weight = float(node.get("line_weight_pt", style.get("line_weight_pt", 1.0)))
    side_fill = str(node.get("side_fill", style.get("side_fill", darker_fill(fill, 0.18))))
    top_fill = str(node.get("top_fill", style.get("top_fill", lighter_fill(fill, 0.14))))

    front_points = [
        (x + skew_x, y),
        (x + width, y + max(0.0, -depth_y * 0.05)),
        (x + width - skew_x, y + height),
        (x, y + height - max(0.0, -depth_y * 0.05)),
    ]
    top_points = [
        front_points[0],
        (front_points[0][0] + depth_x, front_points[0][1] + depth_y),
        (front_points[1][0] + depth_x, front_points[1][1] + depth_y),
        front_points[1],
    ]
    side_points = [
        front_points[1],
        top_points[2],
        (front_points[2][0] + depth_x, front_points[2][1] + depth_y),
        front_points[2],
    ]
    top = draw_polygon_from_points(page, page_height, top_points)
    apply_style(top, {"fill": top_fill, "line": line, "line_weight_pt": line_weight})
    side = draw_polygon_from_points(page, page_height, side_points)
    apply_style(side, {"fill": side_fill, "line": line, "line_weight_pt": line_weight})
    front = draw_polygon_from_points(page, page_height, front_points)
    apply_style(front, merge_style(style, {"fill": fill, "line": line, "line_weight_pt": line_weight}), node.get("text", ""), width, height)
    if node.get("text"):
        try_set_text(front, str(node.get("text", "")))
    return front


def draw_tensor_stack(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    layers = max(1, int(node.get("layers", style.get("layers", 5))))
    layer_dx = float(node.get("layer_dx_in", style.get("layer_dx_in", -0.055)))
    layer_dy = float(node.get("layer_dy_in", style.get("layer_dy_in", 0.025)))
    layer_fill_delta = float(node.get("layer_fill_delta", style.get("layer_fill_delta", 0.0)) or 0.0)
    base_fill = str(node.get("fill", style.get("fill", "#B9D3E8")))
    render_mode = str(node.get("stack_render_mode", node.get("render_mode", style.get("stack_render_mode", "cuboids")))).lower()
    perspective_defaults = tensor_perspective_defaults(node, style, float(node["w"]), float(node["h"]), render_mode)
    if "layer_dx_in" not in node and "layer_dx_in" in perspective_defaults:
        layer_dx = float(perspective_defaults["layer_dx_in"])
    if "layer_dy_in" not in node and "layer_dy_in" in perspective_defaults:
        layer_dy = float(perspective_defaults["layer_dy_in"])
    shape = None

    if render_mode in {"feature_cuboids", "thick_cuboids", "feature_stack", "paper_feature_stack", "thick_feature_map"}:
        width = float(node["w"])
        height = float(node["h"])
        depth_x = float(perspective_defaults.get("depth_x_in", tensor_scaled_depth(node, style, "depth_x_in", width, 0.18)))
        depth_y = float(perspective_defaults.get("depth_y_in", tensor_scaled_depth(node, style, "depth_y_in", height, -0.18)))
        layer_dx = float(node.get("layer_dx_in", perspective_defaults.get("layer_dx_in", style.get("layer_dx_in", -abs(depth_x) * 0.22))))
        layer_dy = float(node.get("layer_dy_in", perspective_defaults.get("layer_dy_in", style.get("layer_dy_in", abs(depth_y) * 0.16))))
        min_layer_shift = float(node.get("min_layer_shift_in", style.get("min_layer_shift_in", 0.0)) or 0.0)
        if min_layer_shift > 0:
            layer_dx = math.copysign(max(abs(layer_dx), min_layer_shift), layer_dx or -1)
            layer_dy = math.copysign(max(abs(layer_dy), min_layer_shift), layer_dy or 1)
        line_weight = float(node.get("line_weight_pt", style.get("line_weight_pt", 1.15)) or 1.15)
        for index in reversed(range(layers)):
            layer_node = dict(node)
            layer_node["x"] = float(node["x"]) + layer_dx * index
            layer_node["y"] = float(node["y"]) + layer_dy * index
            layer_node["depth_x_in"] = depth_x
            layer_node["depth_y_in"] = depth_y
            layer_style = merge_style(
                style,
                {
                    "fill": darker_fill(base_fill, layer_fill_delta * index / max(1, layers - 1)) if layer_fill_delta else base_fill,
                    "line_weight_pt": line_weight,
                    "depth_x_in": depth_x,
                    "depth_y_in": depth_y,
                    "side_fill": node.get("side_fill", style.get("side_fill", darker_fill(base_fill, 0.24))),
                    "top_fill": node.get("top_fill", style.get("top_fill", lighter_fill(base_fill, 0.16))),
                    "text_fit": node.get("text_fit", style.get("text_fit", "single_line")),
                    "constrain_text_box": node.get("constrain_text_box", style.get("constrain_text_box", True)),
                },
            )
            shape = draw_cuboid_node(page, page_height, layer_node, layer_style)
            apply_style(shape, layer_style, "" if index else node.get("text", ""), width, height)
        return shape

    if render_mode in {"thin_feature_slabs", "thin_feature_stack", "layered_slabs", "source_thin_slabs", "paper_thin_feature"}:
        width = float(node["w"])
        height = float(node["h"])
        depth_x = float(perspective_defaults.get("depth_x_in", tensor_scaled_depth(node, style, "depth_x_in", width, 0.11)))
        depth_y = float(perspective_defaults.get("depth_y_in", tensor_scaled_depth(node, style, "depth_y_in", height, -0.08)))
        layer_dx = float(node.get("layer_dx_in", perspective_defaults.get("layer_dx_in", style.get("layer_dx_in", -abs(depth_x) * 0.18))))
        layer_dy = float(node.get("layer_dy_in", perspective_defaults.get("layer_dy_in", style.get("layer_dy_in", abs(depth_y) * 0.16))))
        sheet_scale = float(node.get("sheet_scale", style.get("sheet_scale", 0.0)) or 0.0)
        if "sheet_scale" not in node and "sheet_scale" in perspective_defaults:
            sheet_scale = float(perspective_defaults["sheet_scale"])
        skew_x = float(node.get("skew_x_in", perspective_defaults.get("skew_x_in", style.get("skew_x_in", max(0.0, abs(depth_x) * 0.18)))) or 0.0)
        sheet_line = str(node.get("sheet_line", style.get("sheet_line", style.get("line", "#111827"))))
        sheet_weight = float(node.get("sheet_line_weight_pt", style.get("sheet_line_weight_pt", style.get("line_weight_pt", 0.95))))
        for index in reversed(range(layers)):
            layer_node = dict(node)
            layer_node["x"] = float(node["x"]) + layer_dx * index
            layer_node["y"] = float(node["y"]) + layer_dy * index
            if sheet_scale > 0:
                layer_node["w"] = width * (1.0 + sheet_scale * index)
                layer_node["h"] = height * (1.0 + sheet_scale * index)
            layer_node["depth_x_in"] = depth_x
            layer_node["depth_y_in"] = depth_y
            layer_node["skew_x_in"] = skew_x
            layer_style = merge_style(
                style,
                {
                    "fill": darker_fill(base_fill, layer_fill_delta * index / max(1, layers - 1)) if layer_fill_delta else base_fill,
                    "line": sheet_line,
                    "line_weight_pt": sheet_weight,
                    "depth_x_in": depth_x,
                    "depth_y_in": depth_y,
                    "skew_x_in": skew_x,
                    "side_fill": node.get("side_fill", style.get("side_fill", darker_fill(base_fill, 0.16))),
                    "top_fill": node.get("top_fill", style.get("top_fill", lighter_fill(base_fill, 0.12))),
                },
            )
            shape = draw_oblique_slab(page, page_height, layer_node, layer_style)
        return shape

    if render_mode in {"oblique_slabs", "slabs", "perspective_slabs", "paper_3d"}:
        sheet_scale = float(node.get("sheet_scale", perspective_defaults.get("sheet_scale", style.get("sheet_scale", 0.0))) or 0.0)
        depth_scale = float(node.get("depth_scale", style.get("depth_scale", 1.0)) or 1.0)
        for index in reversed(range(layers)):
            layer_node = dict(node)
            layer_node["x"] = float(node["x"]) + layer_dx * index
            layer_node["y"] = float(node["y"]) + layer_dy * index
            if sheet_scale > 0:
                layer_node["w"] = float(node["w"]) * (1.0 + sheet_scale * index)
                layer_node["h"] = float(node["h"]) * (1.0 + sheet_scale * index)
            layer_style = dict(style)
            if "depth_x_in" in perspective_defaults and "depth_x_in" not in node:
                layer_style["depth_x_in"] = float(perspective_defaults["depth_x_in"])
            if "depth_y_in" in perspective_defaults and "depth_y_in" not in node:
                layer_style["depth_y_in"] = float(perspective_defaults["depth_y_in"])
            if depth_scale != 1.0:
                base_depth_x = float(perspective_defaults.get("depth_x_in", layer_style.get("depth_x_in", node.get("depth_x_in", 0.18))) or 0.18)
                base_depth_y = float(perspective_defaults.get("depth_y_in", layer_style.get("depth_y_in", node.get("depth_y_in", -0.16))) or -0.16)
                layer_style["depth_x_in"] = base_depth_x * depth_scale
                layer_style["depth_y_in"] = base_depth_y * depth_scale
            if layer_fill_delta:
                layer_style["fill"] = darker_fill(base_fill, layer_fill_delta * index / max(1, layers - 1))
                layer_style.setdefault("side_fill", darker_fill(layer_style["fill"], 0.18))
                layer_style.setdefault("top_fill", lighter_fill(layer_style["fill"], 0.14))
            shape = draw_oblique_slab(page, page_height, layer_node, layer_style)
        return shape

    if render_mode in {"thin_sheets", "sheets", "front_sheets", "flat_sheets"}:
        sheet_line = str(node.get("sheet_line", style.get("sheet_line", style.get("line", "#111827"))))
        sheet_weight = float(node.get("sheet_line_weight_pt", style.get("sheet_line_weight_pt", style.get("line_weight_pt", 0.8))))
        for index in reversed(range(layers)):
            layer_node = dict(node)
            layer_node["x"] = float(node["x"]) + layer_dx * index
            layer_node["y"] = float(node["y"]) + layer_dy * index
            layer_style = merge_style(
                style,
                {
                    "fill": darker_fill(base_fill, layer_fill_delta * index / max(1, layers - 1)) if layer_fill_delta else base_fill,
                    "line": sheet_line,
                    "line_weight_pt": sheet_weight,
                },
            )
            shape = draw_rectangle(page, page_height, layer_node)
            apply_style(shape, layer_style, "" if index else node.get("text", ""), float(layer_node["w"]), float(layer_node["h"]))
        return shape

    if render_mode in {"slanted_sheets", "thin_slabs", "paper_sheets", "parallelogram_sheets"}:
        sheet_line = str(node.get("sheet_line", style.get("sheet_line", style.get("line", "#111827"))))
        sheet_weight = float(node.get("sheet_line_weight_pt", style.get("sheet_line_weight_pt", style.get("line_weight_pt", 0.8))))
        skew_x = float(node.get("skew_x_in", perspective_defaults.get("skew_x_in", style.get("skew_x_in", min(abs(layer_dx) * 0.75, float(node["w"]) * 0.18)))) or 0.0)
        for index in reversed(range(layers)):
            lx = float(node["x"]) + layer_dx * index
            ly = float(node["y"]) + layer_dy * index
            points = [
                (lx + skew_x, ly),
                (lx + float(node["w"]), ly),
                (lx + float(node["w"]) - skew_x, ly + float(node["h"])),
                (lx, ly + float(node["h"])),
            ]
            layer_style = merge_style(
                style,
                {
                    "fill": darker_fill(base_fill, layer_fill_delta * index / max(1, layers - 1)) if layer_fill_delta else base_fill,
                    "line": sheet_line,
                    "line_weight_pt": sheet_weight,
                },
            )
            shape = draw_polygon_from_points(page, page_height, points)
            apply_style(shape, layer_style, "" if index else node.get("text", ""), float(node["w"]), float(node["h"]))
        return shape

    for index in reversed(range(layers)):
        layer_node = dict(node)
        layer_node["x"] = float(node["x"]) + layer_dx * index
        layer_node["y"] = float(node["y"]) + layer_dy * index
        layer_style = dict(style)
        if layer_fill_delta:
            layer_style["fill"] = darker_fill(base_fill, layer_fill_delta * index / max(1, layers - 1))
            layer_style.setdefault("side_fill", darker_fill(layer_style["fill"], 0.18))
            layer_style.setdefault("top_fill", lighter_fill(layer_style["fill"], 0.14))
        shape = draw_cuboid_node(page, page_height, layer_node, layer_style)
        apply_style(shape, layer_style, node.get("text", ""))

    return shape


def draw_modality_spine(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    spine = draw_rectangle(page, page_height, node)
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    ports = node.get("ports", [])
    port_style = merge_style(
        {
            "fill": style.get("port_fill", "#CFE8BE"),
            "line": style.get("port_line", style.get("line", "#111111")),
            "line_weight_pt": style.get("port_line_weight_pt", 0.8),
            "font_family": style.get("font_family", "Times New Roman"),
            "font_size_pt": style.get("port_font_size_pt", 10),
            "text_color": style.get("text_color", "#111111"),
        },
        node.get("port_style") if isinstance(node.get("port_style"), dict) else None,
    )

    if isinstance(ports, list):
        for port in ports:
            if not isinstance(port, dict):
                continue
            pos = float(port.get("position", 0.5))
            py = y + (height * pos if 0 <= pos <= 1 else pos)
            pw = float(port.get("w", port.get("width", width * 1.35)))
            ph = float(port.get("h", port.get("height", min(height * 0.08, 0.34))))
            side = str(port.get("side", "center")).lower()
            if side == "left":
                px = x - pw * 0.72
            elif side == "right":
                px = x + width - pw * 0.28
            else:
                px = x + width / 2 - pw / 2
            port_node = {"x": px, "y": py - ph / 2, "w": pw, "h": ph}
            port_shape = draw_rectangle(page, page_height, port_node)
            port_text = str(port.get("text", port.get("label", "")))
            current_port_style = merge_style(port_style, port.get("style") if isinstance(port.get("style"), dict) else None)
            use_math_port = bool(port.get("math", port.get("math_label", False))) or any(marker in port_text for marker in ("_", "′", "'"))
            apply_style(port_shape, current_port_style, "" if use_math_port else port_text)
            if port_text and use_math_port:
                draw_math_text(
                    page,
                    page_height,
                    {
                        "x": px,
                        "y": py - ph / 2,
                        "w": pw,
                        "h": ph,
                        "text": port_text,
                        "font_size_pt": port.get("font_size_pt", current_port_style.get("port_font_size_pt", current_port_style.get("font_size_pt", 10))),
                        "text_fit": port.get("text_fit", current_port_style.get("text_fit", "math_label")),
                        "min_font_size_pt": port.get("min_font_size_pt", current_port_style.get("min_font_size_pt", 4.5)),
                        "subscript_scale": port.get("subscript_scale", current_port_style.get("subscript_scale", 0.58)),
                        "subscript_offset_in": port.get("subscript_offset_in", current_port_style.get("subscript_offset_in", 0.028)),
                        "fragment_pad_in": port.get("fragment_pad_in", current_port_style.get("fragment_pad_in", 0.002)),
                        "subscript_pad_in": port.get("subscript_pad_in", current_port_style.get("subscript_pad_in", 0.0)),
                        "subscript_box_pad_in": port.get("subscript_box_pad_in", current_port_style.get("subscript_box_pad_in", 0.025)),
                    },
                    merge_style(
                        current_port_style,
                        {
                            "fill": "none",
                            "line": "none",
                            "font_family": port.get("font_family", current_port_style.get("math_font_family", "Cambria Math")),
                            "font_family_candidates": port.get(
                                "font_family_candidates",
                                current_port_style.get("math_font_family_candidates", ["Cambria Math", "Times New Roman", "Microsoft YaHei UI"]),
                            ),
                            "font_role": "math",
                            "font_italic": port.get("font_italic", current_port_style.get("font_italic", True)),
                            "text_align": 1,
                            "vertical_align": 1,
                            "text_margin_in": 0.0,
                        },
                    ),
                )
            elif port_text:
                try_set_text(port_shape, port_text)
    return spine


def draw_oval(page: Any, page_height: float, node: dict[str, Any]) -> Any:
    x1 = float(node["x"])
    y1 = to_visio_y(page_height, float(node["y"]) + float(node["h"]))
    x2 = float(node["x"]) + float(node["w"])
    y2 = to_visio_y(page_height, float(node["y"]))
    return page.DrawOval(x1, y1, x2, y2)


def draw_text_box(
    page: Any,
    page_height: float,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    style: dict[str, Any],
) -> Any:
    shape = draw_rectangle(page, page_height, {"x": x, "y": y, "w": width, "h": height})
    try_set_text(shape, text)
    apply_style(shape, merge_style(style, {"fill": "none", "line": "none"}), text, width, height)
    return shape


def draw_rotated_text_box(
    page: Any,
    page_height: float,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    style: dict[str, Any],
) -> Any:
    angle = float(style.get("text_angle_deg", 0) or 0)
    if abs((angle % 180) - 90) > 1e-3:
        return draw_text_box(page, page_height, x, y, width, height, text, style)

    text_style = merge_style(
        style,
        {
            "text_angle_deg": 0,
            "text_fit": style.get("text_fit", "single_line"),
            "text_box_policy": "fit_inside",
            "constrain_text_box": True,
            "expand_text_box_for_single_line": False,
        },
    )
    base_font = float(text_style.get("font_size_pt", 10) or 10)
    inset = float(text_style.get("rotated_text_inset_in", text_style.get("text_margin_in", text_style.get("text_fit_margin_in", 0.0))) or 0.0)
    content_w = max(0.01, height - 2 * inset)
    content_h = max(0.01, width - 2 * inset)
    width_budget = text_style.get("rotated_text_width_budget_in")
    height_budget = text_style.get("rotated_text_height_budget_in")
    if isinstance(width_budget, (int, float)) and float(width_budget) > 0:
        content_w = min(content_w, max(0.01, float(width_budget)))
    if isinstance(height_budget, (int, float)) and float(height_budget) > 0:
        content_h = min(content_h, max(0.01, float(height_budget)))
    safety = float(text_style.get("rotated_text_box_safety_factor", text_style.get("single_line_width_safety_factor", 1.16)) or 1.0)
    if any(ord(char) > 255 for char in str(text)):
        safety = max(safety, float(text_style.get("cjk_text_width_safety_factor", 1.22) or 1.22))
    fitted_font = fit_text_font_size(text, text_style, content_w, content_h) or base_font
    text_w = min(content_w, max(0.02, approximate_text_width(str(text), fitted_font) * safety + 0.03))
    text_h = min(content_h, max(0.02, fitted_font / 72.0 * float(text_style.get("rotated_text_height_factor", 1.35) or 1.35)))
    offset_x = float(text_style.get("rotated_text_offset_x_in", 0.0) or 0.0)
    offset_y = float(text_style.get("rotated_text_offset_y_in", 0.0) or 0.0)
    box = draw_text_box(
        page,
        page_height,
        x + width / 2 - text_w / 2 + offset_x,
        y + height / 2 - text_h / 2 + offset_y,
        text_w,
        text_h,
        text,
        merge_style(text_style, {"font_size_pt": fitted_font, "text_align": 1, "vertical_align": 1}),
    )
    try_set_formula(shape=box, cell_name="Angle", formula=f"{angle} deg")
    return box


def operator_size_tier_defaults(tier: str, width: float, height: float, multi_symbol: bool) -> dict[str, float]:
    size = max(0.01, min(width, height))
    presets: dict[str, dict[str, float]] = {
        "tiny": {"ratio": 0.40, "font_scale": 0.34 if multi_symbol else 0.48},
        "small": {"ratio": 0.48, "font_scale": 0.38 if multi_symbol else 0.54},
        "medium": {"ratio": 0.56, "font_scale": 0.42 if multi_symbol else 0.58},
        "large": {"ratio": 0.64, "font_scale": 0.46 if multi_symbol else 0.62},
        "source_small": {"ratio": 0.45, "font_scale": 0.36 if multi_symbol else 0.52},
        "source_medium": {"ratio": 0.52, "font_scale": 0.40 if multi_symbol else 0.56},
    }
    preset = presets.get(tier.lower(), presets["medium"])
    box_size = size * preset["ratio"]
    return {
        "symbol_box_w_in": box_size,
        "symbol_box_h_in": box_size,
        "symbol_font_size_pt": max(6.0, size * 72.0 * preset["font_scale"]),
    }


def concat_size_tier_defaults(tier: str, width: float, height: float) -> dict[str, float]:
    size = max(0.01, min(width, height))
    presets: dict[str, dict[str, float]] = {
        "tiny": {"tick_in": size * 0.18, "gap_ratio": 0.14, "source_weight_pt": 1.35},
        "small": {"tick_in": size * 0.22, "gap_ratio": 0.18, "source_weight_pt": 1.45},
        "medium": {"tick_in": size * 0.26, "gap_ratio": 0.22, "source_weight_pt": 1.55},
        "large": {"tick_in": size * 0.30, "gap_ratio": 0.26, "source_weight_pt": 1.65},
        "source_small": {"tick_in": size * 0.24, "gap_ratio": 0.14, "source_weight_pt": 1.55},
        "source_medium": {"tick_in": size * 0.28, "gap_ratio": 0.16, "source_weight_pt": 1.65},
    }
    return presets.get(tier.lower(), presets["small"])


def draw_math_vector(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    entries = node.get("entries", node.get("rows"))
    if entries is None:
        text = str(node.get("text", "")).strip()
        entries = [line.strip() for line in text.splitlines() if line.strip()]
    if not isinstance(entries, list) or not entries:
        entries = [""]
    entries = [str(entry) for entry in entries]

    prefix = str(node.get("prefix", "")).strip()
    prefix_width = float(node.get("prefix_w", style.get("prefix_w_in", 0.36 if prefix else 0.0)))
    gap = float(node.get("gap_in", style.get("gap_in", 0.04)))
    bracket_width = float(node.get("bracket_w", style.get("bracket_w_in", 0.08)))
    tick = float(node.get("bracket_tick_in", style.get("bracket_tick_in", 0.06)))
    tick_len = min(bracket_width, tick)
    bracket_style = merge_style(
        style,
        {
            "fill": "none",
            "line": node.get("bracket_line", style.get("bracket_line", style.get("line", "#111111"))),
            "line_weight_pt": node.get("bracket_line_weight_pt", style.get("bracket_line_weight_pt", 0.8)),
            "end_arrow": "none",
        },
    )
    text_style = merge_style(style, {"fill": "none", "line": "none"})
    shape = None

    if prefix:
        shape = draw_text_box(
            page,
            page_height,
            x,
            y,
            prefix_width,
            height,
            prefix,
            merge_style(text_style, {"text_align": 2, "vertical_align": 1}),
        )

    left_x = x + prefix_width + (gap if prefix else 0.0)
    right_x = x + width
    content_x = left_x + bracket_width
    content_w = max(0.05, right_x - left_x - 2 * bracket_width)
    row_h = height / max(1, len(entries))

    draw_left = bool(node.get("left_bracket", True))
    draw_right = bool(node.get("right_bracket", True))
    if draw_left:
        shape = draw_line_segment(page, page_height, (left_x + tick_len, y), (left_x, y), bracket_style)
        shape = draw_line_segment(page, page_height, (left_x, y), (left_x, y + height), bracket_style)
        shape = draw_line_segment(page, page_height, (left_x, y + height), (left_x + tick_len, y + height), bracket_style)
    if draw_right:
        rx = right_x - bracket_width
        shape = draw_line_segment(page, page_height, (right_x - tick_len, y), (right_x, y), bracket_style)
        shape = draw_line_segment(page, page_height, (right_x, y), (right_x, y + height), bracket_style)
        shape = draw_line_segment(page, page_height, (right_x, y + height), (right_x - tick_len, y + height), bracket_style)

    for index, entry in enumerate(entries):
        entry_style = merge_style(
            text_style,
            {
                "font_size_pt": node.get("entry_font_size_pt", style.get("entry_font_size_pt", style.get("font_size_pt", 10))),
                "text_align": 1,
                "vertical_align": 1,
                "text_fit": node.get("entry_text_fit", style.get("entry_text_fit", style.get("text_fit", "math_label"))),
            },
        )
        if "_" in entry or isinstance(node.get("entry_lines"), list):
            shape = draw_math_text(
                page,
                page_height,
                {
                    "x": content_x,
                    "y": y + index * row_h,
                    "w": content_w,
                    "h": row_h,
                    "text": entry,
                    "font_size_pt": entry_style.get("font_size_pt"),
                    "text_fit": entry_style.get("text_fit"),
                    "min_font_size_pt": node.get("entry_min_font_size_pt", style.get("entry_min_font_size_pt", style.get("min_font_size_pt", 5.5))),
                    "subscript_scale": node.get("subscript_scale", style.get("subscript_scale", 0.72)),
                    "subscript_offset_in": node.get("subscript_offset_in", style.get("subscript_offset_in", 0.035)),
                },
                entry_style,
            )
            continue
        shape = draw_text_box(
            page,
            page_height,
            content_x,
            y + index * row_h,
            content_w,
            row_h,
            entry,
            entry_style,
        )

    return shape or draw_text_box(page, page_height, x, y, width, height, "", text_style)


def draw_math_label_box(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    shape_kind = str(node.get("shape", style.get("shape", "rect"))).lower()
    if shape_kind in {"oval", "ellipse", "circle"}:
        shape = draw_oval(page, page_height, node)
    else:
        shape = draw_rectangle(page, page_height, node)
    apply_style(shape, style)

    inset = float(node.get("label_inset_in", style.get("label_inset_in", 0.015)))
    math_node = {
        "x": float(node["x"]) + inset,
        "y": float(node["y"]) + inset,
        "w": max(0.01, float(node["w"]) - inset * 2),
        "h": max(0.01, float(node["h"]) - inset * 2),
        "text": str(node.get("text", node.get("label", ""))),
        "font_size_pt": node.get("label_font_size_pt", style.get("label_font_size_pt", style.get("font_size_pt", 10))),
        "text_fit": node.get("label_text_fit", style.get("label_text_fit", "math_label")),
        "min_font_size_pt": node.get("label_min_font_size_pt", style.get("label_min_font_size_pt", style.get("min_font_size_pt", 4.5))),
        "subscript_scale": node.get("subscript_scale", style.get("subscript_scale", 0.68)),
        "subscript_offset_in": node.get("subscript_offset_in", style.get("subscript_offset_in", 0.03)),
        "fragment_pad_in": node.get("fragment_pad_in", style.get("fragment_pad_in", 0.006)),
        "subscript_pad_in": node.get("subscript_pad_in", style.get("subscript_pad_in", 0.002)),
        "subscript_box_pad_in": node.get("subscript_box_pad_in", style.get("subscript_box_pad_in", 0.05)),
    }
    math_style = merge_style(
        style,
        {
            "fill": "none",
            "line": "none",
            "font_family": node.get("label_font_family", style.get("label_font_family", style.get("font_family", "Cambria Math"))),
            "font_family_candidates": node.get(
                "label_font_family_candidates",
                style.get("label_font_family_candidates", style.get("font_family_candidates", ["Cambria Math", "Times New Roman"])),
            ),
            "font_role": node.get("label_font_role", style.get("label_font_role", "math")),
            "font_size_pt": math_node["font_size_pt"],
            "font_italic": node.get("label_font_italic", style.get("label_font_italic", True)),
            "text_align": 1,
            "vertical_align": 1,
            "text_margin_in": 0.0,
        },
    )
    draw_math_text(page, page_height, math_node, math_style)
    return shape


def draw_math_text(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    base_font = float(node.get("font_size_pt", style.get("font_size_pt", 12)) or 12)
    subscript_scale = float(node.get("subscript_scale", style.get("subscript_scale", 0.72)) or 0.72)
    subscript_font = max(1.0, base_font * subscript_scale)
    subscript_offset = float(node.get("subscript_offset_in", style.get("subscript_offset_in", base_font / 72.0 * 0.22)))
    line_gap = float(node.get("line_gap_in", style.get("line_gap_in", base_font / 72.0 * 0.28)))
    segment_gap = float(node.get("segment_gap_in", style.get("segment_gap_in", 0.0)))
    padding = float(node.get("padding_in", style.get("text_padding_in", 0.0)) or 0.0)
    fragment_pad = float(node.get("fragment_pad_in", style.get("fragment_pad_in", 0.006)) or 0.0)
    subscript_pad = float(node.get("subscript_pad_in", style.get("subscript_pad_in", 0.002)) or 0.0)
    subscript_box_pad = float(node.get("subscript_box_pad_in", style.get("subscript_box_pad_in", 0.045)) or 0.0)
    fragment_width_safety = float(node.get("math_fragment_width_safety_factor", style.get("math_fragment_width_safety_factor", style.get("single_line_width_safety_factor", 1.35))) or 1.35)
    subscript_width_safety = float(node.get("subscript_width_safety_factor", style.get("subscript_width_safety_factor", max(fragment_width_safety, 2.20))) or max(fragment_width_safety, 2.20))
    prime_scale = float(node.get("prime_scale", style.get("prime_scale", 0.82)) or 0.82)
    prime_font = max(1.0, base_font * prime_scale)
    prime_tuck_in = float(node.get("prime_tuck_in", style.get("prime_tuck_in", 0.01)) or 0.0)
    prime_box_pad = float(node.get("prime_box_pad_in", style.get("prime_box_pad_in", 0.01)) or 0.0)
    prime_offset_y = float(node.get("prime_offset_y_in", style.get("prime_offset_y_in", -base_font / 72.0 * 0.18)) or 0.0)
    auto_compact_math = truthy(node.get("auto_compact_math", style.get("auto_compact_math")), False)

    raw_lines = node.get("lines")
    parsed_lines: list[list[dict[str, Any]]] = []
    if isinstance(raw_lines, list) and raw_lines:
        for raw_line in raw_lines:
            if isinstance(raw_line, list):
                parsed_lines.append([
                    {"text": str(fragment.get("text", "")), "subscript": bool(fragment.get("subscript"))}
                    for fragment in raw_line
                    if isinstance(fragment, dict) and str(fragment.get("text", ""))
                ])
            else:
                parsed_lines.append(parse_math_text_line(str(raw_line)))
    else:
        text = str(node.get("text", ""))
        parsed_lines = [parse_math_text_line(line) for line in text.splitlines()]

    parsed_lines = [line for line in parsed_lines if line]
    if not parsed_lines:
        return draw_text_box(page, page_height, x, y, width, height, "", merge_style(style, {"fill": "none", "line": "none"}))

    render_mode = str(node.get("math_render_mode", node.get("render_mode", style.get("math_render_mode", "fragments")))).lower()
    if line_has_hat_fragment(parsed_lines) and render_mode in {"compact_unicode", "unicode", "single_box", "single_text", "plain_compact"}:
        render_mode = "fragments"
    compact_allowed = lines_support_compact_subscripts(parsed_lines)
    word_subscripts = lines_have_word_subscripts(parsed_lines)
    if render_mode == "fragments" and auto_compact_math and compact_allowed and not word_subscripts:
        render_mode = "compact_unicode"
    if render_mode in {"compact_unicode", "unicode", "single_box", "single_text", "plain_compact"} and compact_allowed:
        compact_lines = [fragments_to_compact_math_text(line) for line in parsed_lines]
        compact_text = "\n".join(compact_lines)
        compact_style = merge_style(
            style,
            {
                "fill": "none",
                "line": "none",
                "font_size_pt": node.get("font_size_pt", style.get("font_size_pt", base_font)),
                "text_fit": node.get("text_fit", style.get("text_fit", "math_label")),
                "min_font_size_pt": node.get("min_font_size_pt", style.get("min_font_size_pt", max(5.0, base_font * 0.55))),
                "text_margin_in": node.get("text_margin_in", style.get("text_margin_in", 0.0)),
                "font_italic": node.get("font_italic", style.get("font_italic", True)),
            },
        )
        return draw_text_box(page, page_height, x, y, width, height, compact_text, compact_style)
    if word_subscripts and bool(node.get("plain_fallback", style.get("plain_fallback", True))) and requires_plain_math_fallback(
        parsed_lines,
        width,
        height,
        base_font,
        merge_style(
            style,
            {
                "fragment_pad_in": fragment_pad,
                "subscript_pad_in": subscript_pad,
                "subscript_box_pad_in": subscript_box_pad,
                "subscript_scale": subscript_scale,
                "line_gap_in": line_gap,
                "math_fragment_width_safety_factor": fragment_width_safety,
                "subscript_width_safety_factor": subscript_width_safety,
            },
            node,
        ),
    ):
        plain_lines = [fragments_to_plain_math_text(line) for line in parsed_lines]
        plain_text = "\n".join(plain_lines)
        plain_style = merge_style(
            style,
            single_line_text_style(
                {
                    "fill": "none",
                    "line": "none",
                    "font_size_pt": node.get("font_size_pt", style.get("font_size_pt", base_font)),
                    "text_fit": node.get("text_fit", style.get("text_fit", "math_label")),
                    "text_margin_in": node.get("text_margin_in", style.get("text_margin_in", 0.0)),
                    "font_italic": node.get("font_italic", style.get("font_italic", True)),
                    "single_line_width_safety_factor": node.get(
                        "single_line_width_safety_factor",
                        style.get("single_line_width_safety_factor", 1.18),
                    ),
                },
                float(node.get("min_font_size_pt", style.get("min_font_size_pt", max(4.8, base_font * 0.48)))),
            ),
        )
        return draw_text_box(page, page_height, x, y, width, height, plain_text, plain_style)

    fit_mode = str(node.get("text_fit", auto_text_fit_mode(node.get("text", node.get("lines", "")), style))).lower()
    if fit_mode in TEXT_FIT_WIDTH_MODES:
        min_font = float(node.get("min_font_size_pt", style.get("min_font_size_pt", max(5.0, base_font * 0.55))))
        available_w = max(0.01, width - padding * 2)
        available_h = max(0.01, height - padding * 2)
        widest = 0.0
        for line in parsed_lines:
            line_width = 0.0
            for index, fragment in enumerate(line):
                is_subscript = bool(fragment.get("subscript"))
                fragment_font = subscript_font if is_subscript else base_font
                if is_prime_fragment(str(fragment["text"])):
                    fragment_font = prime_font
                    raw_width = approximate_text_width(str(fragment["text"]), fragment_font)
                else:
                    raw_width = approximate_text_width(str(fragment["text"]), fragment_font) * (subscript_width_safety if is_subscript else fragment_width_safety)
                next_is_subscript = index + 1 < len(line) and bool(line[index + 1].get("subscript"))
                if is_subscript:
                    line_width += raw_width + subscript_pad
                elif is_prime_fragment(str(fragment["text"])):
                    line_width += raw_width + prime_box_pad - prime_tuck_in
                elif next_is_subscript and len(str(fragment["text"]).strip()) == 1:
                    line_width += raw_width + min(fragment_pad, 0.004)
                else:
                    line_width += raw_width + fragment_pad
                if index:
                    line_width += segment_gap
            widest = max(widest, line_width)
        total_h = len(parsed_lines) * (base_font / 72.0 * 1.18) + max(0, len(parsed_lines) - 1) * line_gap
        scale = 1.0
        if widest > available_w:
            scale = min(scale, available_w / widest)
        if total_h > available_h:
            scale = min(scale, available_h / total_h)
        if scale < 1.0:
            base_font = max(min_font, base_font * scale)
            subscript_font = max(1.0, base_font * subscript_scale)
            prime_font = max(1.0, base_font * prime_scale)
            subscript_offset = float(node.get("subscript_offset_in", style.get("subscript_offset_in", base_font / 72.0 * 0.22)))
            prime_offset_y = float(node.get("prime_offset_y_in", style.get("prime_offset_y_in", -base_font / 72.0 * 0.18)) or 0.0)
            line_gap = float(node.get("line_gap_in", style.get("line_gap_in", base_font / 72.0 * 0.28)))

    line_height = base_font / 72.0 * 1.18
    total_height = len(parsed_lines) * line_height + max(0, len(parsed_lines) - 1) * line_gap
    vertical_align = int(style.get("vertical_align", 1))
    if vertical_align == 0:
        cursor_y = y + padding
    elif vertical_align == 2:
        cursor_y = y + max(padding, height - total_height - padding)
    else:
        cursor_y = y + max(padding, (height - total_height) / 2)

    text_align = int(style.get("text_align", 1))
    text_style = merge_style(style, {"fill": "none", "line": "none", "vertical_align": 1})
    shape = None
    for line in parsed_lines:
        metrics: list[tuple[float, float]] = []
        for index, fragment in enumerate(line):
            is_subscript = bool(fragment.get("subscript"))
            text = str(fragment["text"])
            is_prime = is_prime_fragment(text)
            font_size = prime_font if is_prime else (subscript_font if is_subscript else base_font)
            raw_width = approximate_text_width(text, font_size)
            next_is_subscript = index + 1 < len(line) and bool(line[index + 1].get("subscript"))
            if is_subscript:
                box_width = raw_width * subscript_width_safety + subscript_box_pad
                advance_width = raw_width * subscript_width_safety + subscript_pad
            elif is_prime:
                box_width = raw_width + prime_box_pad
                advance_width = max(0.02, box_width - prime_tuck_in)
            elif next_is_subscript and len(text.strip()) == 1:
                box_width = raw_width * fragment_width_safety + fragment_pad
                advance_width = raw_width * fragment_width_safety + min(fragment_pad, 0.004)
            else:
                box_width = raw_width * fragment_width_safety + fragment_pad
                advance_width = box_width
            metrics.append((max(0.02, box_width), max(0.02, advance_width)))
        line_width = sum(advance for _, advance in metrics) + max(0, len(metrics) - 1) * segment_gap
        if text_align == 0:
            cursor_x = x + padding
        elif text_align == 2:
            cursor_x = x + max(padding, width - line_width - padding)
        else:
            cursor_x = x + max(padding, (width - line_width) / 2)

        for fragment, (fragment_box_width, fragment_advance_width) in zip(line, metrics):
            is_subscript = bool(fragment.get("subscript"))
            is_prime = is_prime_fragment(str(fragment["text"]))
            fragment_font = prime_font if is_prime else (subscript_font if is_subscript else base_font)
            fragment_y = cursor_y + (prime_offset_y if is_prime else (subscript_offset if is_subscript else 0.0))
            fragment_x = cursor_x
            fragment_h = line_height
            shape = draw_text_box(
                page,
                page_height,
                fragment_x,
                fragment_y,
                fragment_box_width,
                fragment_h,
                str(fragment["text"]),
                merge_style(
                    text_style,
                    {
                        "font_size_pt": fragment_font,
                        "text_align": 0,
                        "vertical_align": 1,
                        "text_margin_in": 0.0,
                    },
                ),
            )
            if fragment.get("hat"):
                hat_font = max(1.0, base_font * float(node.get("hat_scale", style.get("hat_scale", 0.60)) or 0.60))
                hat_w = max(0.02, approximate_text_width("^", hat_font) + float(node.get("hat_box_pad_in", style.get("hat_box_pad_in", 0.015)) or 0.015))
                hat_h = max(0.02, hat_font / 72.0 * 0.85)
                hat_offset_y = float(node.get("hat_offset_in", style.get("hat_offset_in", -base_font / 72.0 * 0.23)))
                draw_text_box(
                    page,
                    page_height,
                    fragment_x + max(0.0, (fragment_box_width - hat_w) / 2),
                    fragment_y + hat_offset_y,
                    hat_w,
                    hat_h,
                    "^",
                    merge_style(
                        text_style,
                        {
                            "font_size_pt": hat_font,
                            "font_italic": False,
                            "text_align": 1,
                            "vertical_align": 1,
                            "text_margin_in": 0.0,
                        },
                    ),
                )
            cursor_x += fragment_advance_width + segment_gap
        cursor_y += line_height + line_gap

    return shape


def fraction_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text", value.get("value", "")))
    return str(value or "")


def draw_compact_formula_text(
    page: Any,
    page_height: float,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    style: dict[str, Any],
) -> Any:
    compact_text = compact_math_display_text(text)
    return draw_text_box(
        page,
        page_height,
        x,
        y,
        width,
        height,
        compact_text,
        single_line_text_style(
            merge_style(
                style,
                {
                    "fill": "none",
                    "line": "none",
                    "text_margin_in": 0.0,
                    "text_fit": "math_label",
                    "font_italic": style.get("font_italic", True),
                },
            ),
            min_font_size_pt=float(style.get("min_font_size_pt", 4.5) or 4.5),
        ),
    )


def draw_tight_formula_text(
    page: Any,
    page_height: float,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    style: dict[str, Any],
) -> Any:
    fragments, widths, advances, total_w = tight_formula_text_metrics(text, style)
    if not fragments:
        return draw_text_box(page, page_height, x, y, width, height, "", merge_style(style, {"fill": "none", "line": "none"}))
    base_font = float(style.get("font_size_pt", 8.5) or 8.5)
    subscript_scale = float(style.get("subscript_scale", 0.68) or 0.68)
    subscript_font = max(1.0, base_font * subscript_scale)
    line_h = max(0.04, base_font / 72.0 * 1.25)
    base_y = y + max(0.0, (height - line_h) / 2)
    subscript_offset = float(style.get("subscript_offset_in", base_font / 72.0 * 0.18) or 0.0)
    prime_offset_y = float(style.get("prime_offset_y_in", -base_font / 72.0 * 0.14) or 0.0)
    segment_gap = float(style.get("tight_segment_gap_in", 0.001) or 0.0)
    cursor_x = x + max(0.0, (width - total_w) / 2)
    text_style = merge_style(
        style,
        {
            "fill": "none",
            "line": "none",
            "text_align": 0,
            "vertical_align": 1,
            "text_margin_in": 0.0,
            "text_fit": "math_label",
        },
    )
    shape = None
    for fragment, box_w, advance in zip(fragments, widths, advances):
        raw = str(fragment.get("text", ""))
        is_subscript = bool(fragment.get("subscript"))
        is_prime = is_prime_fragment(raw)
        font_size = subscript_font if is_subscript else (max(1.0, base_font * 0.72) if is_prime else base_font)
        fragment_y = base_y + (subscript_offset if is_subscript else (prime_offset_y if is_prime else 0.0))
        shape = draw_text_box(
            page,
            page_height,
            cursor_x,
            fragment_y,
            box_w,
            line_h,
            raw,
            merge_style(text_style, {"font_size_pt": font_size}),
        )
        cursor_x += advance + segment_gap
    return shape


def tight_formula_text_metrics(text: str, style: dict[str, Any]) -> tuple[list[dict[str, Any]], list[float], list[float], float]:
    fragments = parse_math_text_line(text)
    if not fragments:
        return [], [], [], 0.0
    base_font = float(style.get("font_size_pt", 8.5) or 8.5)
    subscript_scale = float(style.get("subscript_scale", 0.68) or 0.68)
    subscript_font = max(1.0, base_font * subscript_scale)
    segment_gap = float(style.get("tight_segment_gap_in", 0.001) or 0.0)
    min_w = float(style.get("tight_min_fragment_w_in", 0.014) or 0.014)
    widths: list[float] = []
    advances: list[float] = []
    for index, fragment in enumerate(fragments):
        raw = str(fragment.get("text", ""))
        is_subscript = bool(fragment.get("subscript"))
        is_prime = is_prime_fragment(raw)
        font_size = base_font
        if is_subscript:
            font_size = subscript_font
        elif is_prime:
            font_size = max(1.0, base_font * 0.72)
        text_w = approximate_text_width(raw, font_size)
        next_is_subscript = index + 1 < len(fragments) and bool(fragments[index + 1].get("subscript"))
        if is_subscript:
            box_w = max(min_w, text_w * 1.45 + 0.012)
            advance = max(min_w, text_w * 0.78 + 0.001)
        elif is_prime:
            box_w = max(min_w, text_w + 0.006)
            advance = max(min_w, text_w * 0.70)
        elif next_is_subscript and len(raw.strip()) == 1:
            box_w = max(min_w, text_w * 1.24 + 0.008)
            advance = max(min_w, text_w * 0.68)
        else:
            box_w = max(min_w, text_w * 1.45 + 0.018)
            advance = max(min_w, text_w * 1.06 + 0.004)
        widths.append(box_w)
        advances.append(advance)
    cursor = 0.0
    max_right = 0.0
    for box_w, advance in zip(widths, advances):
        max_right = max(max_right, cursor + box_w)
        cursor += advance + segment_gap
    return fragments, widths, advances, max_right


def formula_fraction_width(numerator: str, denominator: str, small_style: dict[str, Any]) -> float:
    mode = str(small_style.get("fraction_text_mode", "tight_fragments")).lower()
    if mode in {"compact", "unicode", "single_box", "single_text"}:
        return max(
            approximate_text_width(compact_math_display_text(numerator), float(small_style.get("font_size_pt", 8.5) or 8.5)),
            approximate_text_width(compact_math_display_text(denominator), float(small_style.get("font_size_pt", 8.5) or 8.5)),
        )
    if mode in {"fragment", "fragments", "editable_fragments", "tight", "tight_fragment", "tight_fragments"}:
        return max(
            tight_formula_text_metrics(numerator, small_style)[3],
            tight_formula_text_metrics(denominator, small_style)[3],
        )
    return max(
        approximate_text_width(numerator, float(small_style.get("font_size_pt", 8.5) or 8.5)),
        approximate_text_width(denominator, float(small_style.get("font_size_pt", 8.5) or 8.5)),
    )


def draw_math_formula_group(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    base_font = float(node.get("font_size_pt", style.get("font_size_pt", 12)) or 12)
    small_font = float(node.get("fraction_font_size_pt", style.get("fraction_font_size_pt", max(5.5, base_font * 0.72))) or max(5.5, base_font * 0.72))
    line_weight = float(node.get("fraction_bar_weight_pt", style.get("fraction_bar_weight_pt", 0.8)) or 0.8)
    left_text = str(node.get("left_text", node.get("prefix", "")))
    operator = str(node.get("operator", "=" if left_text else node.get("equation_operator", "")))
    right_text = str(node.get("right_text", node.get("suffix", "")))
    fraction = node.get("fraction") if isinstance(node.get("fraction"), dict) else {}
    numerator = fraction_text(node.get("numerator", fraction.get("numerator")))
    denominator = fraction_text(node.get("denominator", fraction.get("denominator")))
    baseline_ratio = float(node.get("baseline_y_ratio", style.get("baseline_y_ratio", 0.52)) or 0.52)
    baseline_y = y + height * baseline_ratio
    padding_x = float(node.get("padding_x_in", style.get("padding_x_in", 0.01)) or 0.0)
    gap = float(node.get("gap_in", style.get("gap_in", 0.035)) or 0.035)
    left_w = float(node.get("left_w_in", 0) or 0)
    if left_text and left_w <= 0:
        left_w = min(width * 0.28, max(0.08, approximate_text_width(left_text, base_font) * 1.18))
    op_w = float(node.get("operator_w_in", 0) or 0)
    if operator and op_w <= 0:
        op_w = min(width * 0.16, max(0.07, approximate_text_width(operator, base_font) * 1.22))
    right_w = float(node.get("right_w_in", 0) or 0)
    if right_text and right_w <= 0:
        right_w = min(width * 0.24, max(0.08, approximate_text_width(right_text, base_font) * 1.18))
    text_style = merge_style(
        style,
        {
            "fill": "none",
            "line": "none",
            "font_size_pt": base_font,
            "font_role": node.get("font_role", style.get("font_role", "math")),
            "font_family": node.get("font_family", style.get("font_family", "Cambria Math")),
            "font_family_candidates": node.get("font_family_candidates", style.get("font_family_candidates", ["Cambria Math", "Times New Roman", "Cambria"])),
            "text_fit": "math_label",
            "text_margin_in": 0.0,
            "font_italic": node.get("font_italic", style.get("font_italic", True)),
            "text_align": 1,
            "vertical_align": 1,
        },
    )
    small_style = merge_style(text_style, {"font_size_pt": small_font, "min_font_size_pt": node.get("min_font_size_pt", style.get("min_font_size_pt", 4.5))})
    fraction_text_mode = str(node.get("fraction_text_mode", style.get("fraction_text_mode", "tight_fragments"))).lower()
    small_style = merge_style(small_style, {"fraction_text_mode": fraction_text_mode})
    reserved = padding_x * 2 + (left_w if left_text else 0) + (op_w if operator else 0) + (right_w if right_text else 0)
    gaps = sum(1 for value in (left_text, operator, numerator or denominator, right_text) if value)
    reserved += max(0, gaps - 1) * gap
    available_frac_w = max(0.08, width - reserved)
    frac_w = float(node.get("fraction_w_in", node.get("fraction_width_in", 0)) or 0)
    width_policy = str(node.get("fraction_width_policy", style.get("fraction_width_policy", "fit_content"))).lower()
    if frac_w <= 0 and width_policy in {"fill", "fill_available", "remaining"}:
        frac_w = max(0.12, available_frac_w)
    elif frac_w <= 0:
        content_w = formula_fraction_width(numerator, denominator, small_style)
        fraction_padding = float(node.get("fraction_padding_in", style.get("fraction_padding_in", 0.045)) or 0.0)
        min_frac_w = float(node.get("fraction_min_w_in", style.get("fraction_min_w_in", 0.28)) or 0.28)
        frac_w = max(min_frac_w, content_w + fraction_padding * 2)
    frac_w = min(max(0.08, frac_w), available_frac_w)
    cursor_x = x + padding_x
    first_shape = None

    def keep(shape: Any) -> None:
        nonlocal first_shape
        if first_shape is None:
            first_shape = shape

    center_line_h = max(0.04, base_font / 72.0 * 1.35)
    if left_text:
        keep(draw_math_text(page, page_height, {"x": cursor_x, "y": baseline_y - center_line_h / 2, "w": left_w, "h": center_line_h, "text": left_text, "font_size_pt": base_font, "text_fit": "math_label"}, text_style))
        cursor_x += left_w + gap
    if operator:
        keep(draw_text_box(page, page_height, cursor_x, baseline_y - center_line_h / 2, op_w, center_line_h, operator, merge_style(text_style, {"font_italic": False})))
        cursor_x += op_w + gap

    frac_x = cursor_x
    bar_y = baseline_y
    numerator_h = max(0.04, small_font / 72.0 * 1.25)
    denominator_h = max(0.04, small_font / 72.0 * 1.25)
    numerator_gap = float(node.get("numerator_gap_in", style.get("numerator_gap_in", 0.018)) or 0.018)
    denominator_gap = float(node.get("denominator_gap_in", style.get("denominator_gap_in", 0.016)) or 0.016)
    if numerator:
        if fraction_text_mode in {"fragment", "fragments", "editable_fragments"}:
            keep(draw_math_text(page, page_height, {"x": frac_x, "y": bar_y - numerator_gap - numerator_h, "w": frac_w, "h": numerator_h, "text": numerator, "font_size_pt": small_font, "text_fit": "math_label"}, small_style))
        elif fraction_text_mode in {"tight", "tight_fragment", "tight_fragments"}:
            keep(draw_tight_formula_text(page, page_height, frac_x, bar_y - numerator_gap - numerator_h, frac_w, numerator_h, numerator, small_style))
        else:
            keep(draw_compact_formula_text(page, page_height, frac_x, bar_y - numerator_gap - numerator_h, frac_w, numerator_h, numerator, small_style))
    bar_style = merge_style(style, {"line": node.get("fraction_bar_color", style.get("line", "#111827")), "line_weight_pt": line_weight, "end_arrow": "none"})
    keep(draw_line_segment(page, page_height, (frac_x, bar_y), (frac_x + frac_w, bar_y), bar_style))
    if denominator:
        if fraction_text_mode in {"fragment", "fragments", "editable_fragments"}:
            keep(draw_math_text(page, page_height, {"x": frac_x, "y": bar_y + denominator_gap, "w": frac_w, "h": denominator_h, "text": denominator, "font_size_pt": small_font, "text_fit": "math_label"}, small_style))
        elif fraction_text_mode in {"tight", "tight_fragment", "tight_fragments"}:
            keep(draw_tight_formula_text(page, page_height, frac_x, bar_y + denominator_gap, frac_w, denominator_h, denominator, small_style))
        else:
            keep(draw_compact_formula_text(page, page_height, frac_x, bar_y + denominator_gap, frac_w, denominator_h, denominator, small_style))
    cursor_x = frac_x + frac_w + gap
    if right_text:
        keep(draw_math_text(page, page_height, {"x": cursor_x, "y": baseline_y - center_line_h / 2, "w": right_w, "h": center_line_h, "text": right_text, "font_size_pt": base_font, "text_fit": "math_label"}, text_style))

    return first_shape or draw_text_box(page, page_height, x, y, width, height, "", merge_style(style, {"fill": "none", "line": "none"}))


def default_tfr_cells(rows: int, cols: int) -> list[list[Any]]:
    palette = ["#B9D4F1", "#F39FC6", "#F6CBD7", "#B9D4F1", "#F6CBD7"]
    cells: list[list[Any]] = []
    for row in range(rows):
        for col in range(cols):
            color = palette[(row * 2 + col) % len(palette)]
            if row == rows // 2 and col == cols // 2:
                color = "#8EB8E6"
            cells.append([row, col, color])
    return cells


def draw_tfr_panel(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    panel_style = merge_style(style, {"text_align": 1, "vertical_align": 1})
    base = draw_rectangle(page, page_height, node)
    apply_style(base, panel_style)

    title = str(node.get("title", node.get("text", "TFR"))).strip()
    subtitle = str(node.get("subtitle", "")).strip()
    input_label = str(node.get("input_label", "Input")).strip()
    title_h = float(node.get("title_h_in", max(0.22, height * 0.23)))
    subtitle_h = float(node.get("subtitle_h_in", max(0.14, height * 0.10))) if subtitle else 0.0
    top_pad = float(node.get("top_pad_in", height * 0.07))
    input_h = float(node.get("input_h_in", max(0.20, height * 0.14)))
    input_gap = float(node.get("input_gap_in", max(0.08, height * 0.045)))

    if title:
        draw_text_box(
            page,
            page_height,
            x + width * 0.08,
            y + top_pad,
            width * 0.84,
            title_h,
            title,
            merge_style(panel_style, {"fill": "none", "line": "none", "font_size_pt": style.get("title_font_size_pt", 18)}),
        )
    if subtitle:
        draw_text_box(
            page,
            page_height,
            x + width * 0.06,
            y + top_pad + title_h * 0.78,
            width * 0.88,
            subtitle_h,
            subtitle,
            merge_style(panel_style, {"fill": "none", "line": "none", "font_size_pt": style.get("subtitle_font_size_pt", 12)}),
        )

    rows = int(node.get("rows", 4))
    cols = int(node.get("cols", 5))
    grid_w = float(node.get("grid_w", node.get("grid_w_in", min(width * 0.58, height * 0.44 * cols / max(1, rows)))))
    grid_h = float(node.get("grid_h", node.get("grid_h_in", grid_w * rows / max(1, cols))))
    max_grid_h = max(0.1, height - top_pad - title_h - subtitle_h - input_h - input_gap - height * 0.08)
    if grid_h > max_grid_h:
        grid_h = max_grid_h
        grid_w = grid_h * cols / max(1, rows)
    grid_x = float(node.get("grid_x", x + (width - grid_w) / 2))
    grid_y_default = y + top_pad + title_h + subtitle_h + float(node.get("grid_top_gap_in", height * 0.02))
    grid_y = float(node.get("grid_y", grid_y_default))
    input_y = float(node.get("input_y", grid_y + grid_h + input_gap))
    if input_y + input_h > y + height - height * 0.04:
        input_y = y + height - height * 0.04 - input_h

    grid_node = {
        "x": grid_x,
        "y": grid_y,
        "w": grid_w,
        "h": grid_h,
        "rows": rows,
        "cols": cols,
        "colored_cells": node.get("colored_cells", node.get("cells", default_tfr_cells(rows, cols))),
    }
    grid_style = merge_style(
        {
            "cell_fill": node.get("cell_fill", "#FFFFFF"),
            "grid_line": style.get("grid_line", "#777777"),
            "grid_line_weight_pt": style.get("grid_line_weight_pt", 0.75),
            "line": style.get("grid_outline", style.get("line", "#666666")),
            "line_weight_pt": style.get("grid_outline_weight_pt", 0.8),
        },
        node.get("grid_style") if isinstance(node.get("grid_style"), dict) else None,
    )
    shape = draw_grid_matrix(page, page_height, grid_node, grid_style)

    if node.get("input_arrow"):
        arrow_x = x + width * float(node.get("input_arrow_x", 0.5))
        arrow_gap = float(node.get("input_arrow_gap_in", max(0.03, height * 0.02)))
        start_y = max(grid_y + grid_h + arrow_gap, input_y - arrow_gap)
        end_y = min(input_y - arrow_gap, grid_y + grid_h + arrow_gap)
        if start_y - end_y > 0.04:
            shape = draw_line_segment(
                page,
                page_height,
                (arrow_x, start_y),
                (arrow_x, end_y),
                merge_style(
                    {
                        "line": style.get("line", "#6F6F6F"),
                        "line_weight_pt": style.get("line_weight_pt", 1.0),
                        "end_arrow": "triangle",
                        "arrow_size": style.get("input_arrow_size", "small"),
                    },
                    node.get("input_arrow_style") if isinstance(node.get("input_arrow_style"), dict) else None,
                ),
            )

    if input_label:
        shape = draw_text_box(
            page,
            page_height,
            x + width * 0.15,
            input_y,
            width * 0.70,
            input_h,
            input_label,
            merge_style(panel_style, {"fill": "none", "line": "none", "font_size_pt": style.get("input_font_size_pt", 16)}),
        )
    return shape or base


def draw_loss_region(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    frame = draw_group_container(page, page_height, node, merge_style(style, {"fill": "none"}))
    title = str(node.get("title", node.get("caption", ""))).strip()
    formulas = node.get("formulas", node.get("lines", []))
    if isinstance(formulas, str):
        formulas = [line for line in formulas.splitlines() if line.strip()]
    if not isinstance(formulas, list):
        formulas = []
    formulas = [normalize_loss_formula_text(str(item)) for item in formulas]

    title_font = float(node.get("title_font_size_pt", style.get("title_font_size_pt", 15)))
    title_position = str(node.get("title_position", style.get("title_position", "header_cutout"))).lower()
    title_pad_x = float(node.get("title_pad_x_in", style.get("title_pad_x_in", 0.10)))
    title_h = float(node.get("title_h_in", min(0.36, max(0.22, height * 0.28))))
    title_y = y + float(node.get("title_inside_y_in", max(0.04, height * 0.05)))
    formula_y = y + float(node.get("formula_pad_y_in", height * 0.14))
    if title:
        title_lines = title.splitlines()
        title_h = max(title_h, max(1, len([line for line in title_lines if line])) * title_font / 72.0 * 1.16)
        title_width_estimate = max(approximate_text_width(line, title_font) for line in title_lines if line)
        title_box_w = float(
            node.get(
                "title_w_in",
                max(min(width * 1.65, title_width_estimate + title_pad_x * 2), min(width * 0.92, title_width_estimate + title_pad_x)),
            )
        )
        title_box_w = max(min(width * 1.75, title_box_w), min(width, title_width_estimate + title_pad_x))
        title_x = x + (width - title_box_w) / 2
        title_style = merge_style(
            style,
            {
                "fill": node.get("title_fill", style.get("title_fill", "#FFFFFF")),
                "line": "none",
                "font_size_pt": title_font,
                "text_align": 1,
                "vertical_align": 1,
                "text_margin_left_in": 0.02,
                "text_margin_right_in": 0.02,
                "text_margin_top_in": 0.0,
                "text_margin_bottom_in": 0.0,
            },
        )
        if title_position in {"inside", "top_inside", "inner"}:
            title_y = y + float(node.get("title_inside_y_in", max(0.04, height * 0.05)))
            formula_y = max(formula_y, title_y + title_h + float(node.get("title_formula_gap_in", max(0.03, height * 0.04))))
        elif title_position in {"outside", "above"}:
            title_y = y - title_h - float(node.get("title_gap_in", max(0.02, height * 0.02)))
        else:
            title_y = y - title_h * float(node.get("title_overlap_ratio", style.get("title_overlap_ratio", 0.45)))
            formula_y = max(formula_y, y + title_h * float(node.get("header_formula_clearance_ratio", 0.72)))
        draw_text_box(
            page,
            page_height,
            title_x,
            title_y,
            title_box_w,
            title_h,
            title,
            title_style,
        )

    if formulas:
        formula_pad_x = float(node.get("formula_pad_x_in", width * 0.10))
        formula_bottom_pad = float(node.get("formula_bottom_pad_in", height * 0.10))
        math_node = {
            "x": x + formula_pad_x,
            "y": formula_y,
            "w": width - 2 * formula_pad_x,
            "h": max(0.08, y + height - formula_y - formula_bottom_pad),
            "lines": [str(item) for item in formulas],
        }
        draw_math_text(page, page_height, math_node, merge_style(style, {"fill": "none", "line": "none", "text_align": 1, "vertical_align": 1}))
    return frame


def draw_boundary_port(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    visible_value = node.get("visible", True)
    visible = not (visible_value is False or str(visible_value).lower() in {"false", "0", "no"})
    shape_kind = str(node.get("shape", "circle")).lower()
    if shape_kind == "none":
        visible = False
    port_style = dict(style)
    if not visible:
        port_style = merge_style(port_style, {"fill": "none", "line": "none", "line_weight_pt": 0})

    if shape_kind in {"tick", "line"}:
        x = float(node["x"])
        y = float(node["y"])
        width = float(node["w"])
        height = float(node["h"])
        side = str(node.get("side", "right")).lower()
        if side in {"top", "bottom"}:
            start = (x + width / 2, y)
            end = (x + width / 2, y + height)
        else:
            start = (x, y + height / 2)
            end = (x + width, y + height / 2)
        return draw_line_segment(page, page_height, start, end, merge_style(port_style, {"end_arrow": "none"}))

    if shape_kind in {"square", "rectangle", "rect"}:
        shape = draw_rectangle(page, page_height, node)
    else:
        shape = draw_oval(page, page_height, node)
    apply_style(shape, port_style)
    return shape


def draw_operator_node(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    if node.get("enforce_circle", style.get("enforce_circle", True)):
        size = min(width, height)
        x += (width - size) / 2
        y += (height - size) / 2
        width = size
        height = size
    operator_shape = str(node.get("operator_shape", node.get("shape", style.get("operator_shape", "circle")))).lower()
    circle_node = dict(node)
    circle_node.update({"x": x, "y": y, "w": width, "h": height})
    if operator_shape in {"none", "text", "label"}:
        shape = draw_rectangle(page, page_height, circle_node)
        apply_style(shape, merge_style(style, {"fill": "none", "line": "none", "line_weight_pt": 0}))
    elif operator_shape in {"rect", "rectangle", "box"}:
        shape = draw_rectangle(page, page_height, circle_node)
        apply_style(shape, style)
    else:
        shape = draw_oval(page, page_height, circle_node)
        apply_style(shape, style)

    symbol = str(node.get("symbol", node.get("text", "")))
    if symbol:
        multi_symbol = len(symbol.strip()) > 1
        size_tier = str(node.get("operator_size_tier", style.get("operator_size_tier", "medium")) or "medium")
        tier_defaults = operator_size_tier_defaults(size_tier, width, height, multi_symbol)
        symbol_style = merge_style(
            style,
            {
                "fill": "none",
                "line": "none",
                "font_family": node.get("symbol_font_family", style.get("symbol_font_family", "Cambria Math")),
                "font_family_candidates": node.get(
                    "symbol_font_family_candidates",
                    style.get("symbol_font_family_candidates", style.get("font_family_candidates")),
                ),
                "font_role": node.get("symbol_font_role", style.get("symbol_font_role", "math")),
                "font_size_pt": node.get(
                    "symbol_font_size_pt",
                    style.get("symbol_font_size_pt", tier_defaults["symbol_font_size_pt"]),
                ),
                "font_weight": node.get("symbol_font_weight", style.get("symbol_font_weight", "regular")),
                "text_align": 1,
                "vertical_align": 1,
                "text_fit": node.get("symbol_text_fit", style.get("symbol_text_fit", "single_line")),
                "min_font_size_pt": node.get("symbol_min_font_size_pt", style.get("symbol_min_font_size_pt", 4.5)),
                "text_margin_in": node.get("symbol_text_margin_in", style.get("symbol_text_margin_in", 0.0)),
                "constrain_text_box": node.get("symbol_constrain_text_box", style.get("symbol_constrain_text_box", True)),
                "text_box_policy": node.get("symbol_text_box_policy", style.get("symbol_text_box_policy", "fit_inside")),
                "expand_text_box_for_single_line": False,
            },
        )
        inset = float(node.get("symbol_inset_in", style.get("symbol_inset_in", 0.0)))
        offset_x = float(node.get("symbol_offset_x_in", style.get("symbol_offset_x_in", 0.0)))
        offset_y = float(node.get("symbol_offset_y_in", style.get("symbol_offset_y_in", 0.0)))
        symbol_w = float(node.get("symbol_box_w_in", node.get("symbol_box_width_in", style.get("symbol_box_w_in", tier_defaults["symbol_box_w_in"]))))
        symbol_h = float(node.get("symbol_box_h_in", node.get("symbol_box_height_in", style.get("symbol_box_h_in", tier_defaults["symbol_box_h_in"]))))
        symbol_x = x + (width - symbol_w) / 2 + offset_x
        symbol_y = y + (height - symbol_h) / 2 + offset_y
        draw_text_box(
            page,
            page_height,
            symbol_x,
            symbol_y,
            max(0.01, symbol_w),
            max(0.01, symbol_h),
            symbol,
            symbol_style,
        )
    return shape


def draw_resizable_text(
    page: Any,
    page_height: float,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    style: dict[str, Any],
) -> Any:
    shape = draw_rectangle(page, page_height, {"x": x, "y": y, "w": width, "h": height})
    apply_style(shape, style, text, width, height)
    if text:
        try_set_text(shape, text)
    return shape


def draw_group_container(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    style = dict(style)
    shape_kind = str(node.get("shape", node.get("container_shape", "rectangle"))).lower()
    width = float(node["w"])
    height = float(node["h"])
    if shape_kind in {"rounded", "round_rect", "round-rect", "capsule", "pill"} and not float(style.get("rounding_in", 0) or 0):
        if node.get("corner_radius_in") is not None:
            style["rounding_in"] = float(node["corner_radius_in"])
        elif shape_kind in {"capsule", "pill"}:
            style["rounding_in"] = min(min(width, height) / 2, float(node.get("max_rounding_in", 0.45)))
        else:
            style["rounding_in"] = min(width, height) * 0.18

    shape = draw_rectangle(page, page_height, node)
    apply_style(shape, style)

    text = node.get("text")
    if text:
        x = float(node["x"])
        y = float(node["y"])
        title_h = float(node.get("title_h_in", min(0.24, max(0.14, float(node["h"]) * 0.10))))
        title_x = x + float(node.get("title_pad_x_in", 0.08))
        title_y = y + float(node.get("title_pad_y_in", 0.02))
        title_w = max(0.1, width - float(node.get("title_pad_x_in", 0.08)) * 2)
        title_style = merge_style(
            style,
            {
                "fill": "none",
                "line": "none",
                "font_size_pt": node.get("title_font_size_pt", style.get("font_size_pt", 15)),
                "text_align": node.get("title_align", 0),
            },
        )
        draw_text_box(page, page_height, title_x, title_y, title_w, title_h, str(text), title_style)
    return shape


def branch_offsets(node: dict[str, Any], style: dict[str, Any], total: float) -> list[float]:
    raw_positions = node.get("branch_positions", node.get("positions"))
    if isinstance(raw_positions, list) and raw_positions:
        offsets: list[float] = []
        for value in raw_positions:
            if not isinstance(value, (int, float)):
                continue
            numeric = float(value)
            offsets.append(numeric * total if 0.0 <= numeric <= 1.0 else numeric)
        if offsets:
            return offsets

    count = max(1, int(node.get("branch_count", style.get("branch_count", 4))))
    if count == 1:
        return [total / 2]
    return [total * index / (count - 1) for index in range(count)]


def draw_boundary_fanout(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    side = str(node.get("side", "right")).lower()
    line_style = merge_style(style, {"fill": "none", "end_arrow": style.get("end_arrow", "triangle")})
    branch_labels = [str(item) for item in node.get("labels", [])] if isinstance(node.get("labels"), list) else []
    label_gap = float(node.get("label_gap_in", style.get("label_gap_in", 0.04)))
    label_w = float(node.get("label_width_in", style.get("label_width_in", 0.32)))
    label_h = float(node.get("label_height_in", style.get("label_height_in", 0.18)))
    label_style = merge_style(style, {"fill": "none", "line": "none", "font_size_pt": node.get("label_font_size_pt", 11)})

    shape = None
    if side in {"right", "left"}:
        for index, offset in enumerate(branch_offsets(node, style, height)):
            line_y = y + offset
            if side == "right":
                start = (x, line_y)
                end = (x + width, line_y)
                label_x = end[0] + label_gap
            else:
                start = (x + width, line_y)
                end = (x, line_y)
                label_x = end[0] - label_gap - label_w
            shape = draw_line_segment(page, page_height, start, end, line_style)
            if index < len(branch_labels):
                draw_text_box(page, page_height, label_x, line_y - label_h / 2, label_w, label_h, branch_labels[index], label_style)
    elif side in {"top", "bottom"}:
        for index, offset in enumerate(branch_offsets(node, style, width)):
            line_x = x + offset
            if side == "bottom":
                start = (line_x, y)
                end = (line_x, y + height)
                label_y = end[1] + label_gap
            else:
                start = (line_x, y + height)
                end = (line_x, y)
                label_y = end[1] - label_gap - label_h
            shape = draw_line_segment(page, page_height, start, end, line_style)
            if index < len(branch_labels):
                draw_text_box(page, page_height, line_x - label_w / 2, label_y, label_w, label_h, branch_labels[index], label_style)
    else:
        raise ValueError(f"Unsupported boundary_fanout side: {side}")
    return shape


def draw_rotated_diamond(page: Any, page_height: float, node: dict[str, Any]) -> Any:
    width = float(node["w"]) / math.sqrt(2)
    height = float(node["h"]) / math.sqrt(2)
    cx = float(node["x"]) + float(node["w"]) / 2
    cy = to_visio_y(page_height, float(node["y"]) + float(node["h"]) / 2)
    shape = page.DrawRectangle(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)
    try_set_formula(shape, "Angle", "45 deg")
    try_set_formula(shape, "TxtAngle", "-45 deg")
    return shape


def draw_image_tile(page: Any, page_height: float, node: dict[str, Any], asset_path: Path) -> Any:
    shape = page.Import(str(asset_path))
    cx = float(node["x"]) + float(node["w"]) / 2
    cy = to_visio_y(page_height, float(node["y"]) + float(node["h"]) / 2)
    try_set_result(shape, "PinX", cx)
    try_set_result(shape, "PinY", cy)
    try_set_result(shape, "Width", float(node["w"]))
    try_set_result(shape, "Height", float(node["h"]))
    return shape


def draw_wave_signal(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    baseline = y + height * float(node.get("baseline_ratio", 0.5))
    amplitude = float(node.get("amplitude_in", height * float(style.get("amplitude_ratio", 0.38))))
    samples = node.get("samples")

    values: list[float] = []
    if isinstance(samples, list) and samples:
        for item in samples:
            if isinstance(item, (int, float)):
                values.append(float(item))
    if not values:
        point_count = max(8, int(node.get("point_count", 48)))
        cycles = float(node.get("cycles", style.get("cycles", 2.5)))
        values = [
            math.sin(2 * math.pi * cycles * index / (point_count - 1))
            for index in range(point_count)
        ]

    if len(values) == 1:
        values = [values[0], values[0]]

    line_style = merge_style(style, {"fill": "none", "end_arrow": "none"})
    shape = None
    if node.get("show_baseline"):
        shape = draw_line_segment(page, page_height, (x, baseline), (x + width, baseline), line_style)

    points = []
    for index, value in enumerate(values):
        px = x + width * index / (len(values) - 1)
        py = baseline - max(-1.0, min(1.0, float(value))) * amplitude
        points.append((px, py))

    for start, end in zip(points, points[1:]):
        shape = draw_line_segment(page, page_height, start, end, line_style)
    return shape


def primitive_style(base_style: dict[str, Any], item: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    item_style = item.get("style") if isinstance(item.get("style"), dict) else None
    merged = merge_style(base_style, extra, item_style)
    for key in (
        "fill",
        "line",
        "line_weight_pt",
        "line_dash",
        "text_color",
        "font_family",
        "font_family_candidates",
        "font_role",
        "font_size_pt",
        "font_weight",
        "font_italic",
        "text_fit",
        "text_align",
        "vertical_align",
        "text_margin_in",
        "rounding_in",
        "end_arrow",
        "begin_arrow",
        "arrow_size",
    ):
        if key in item:
            merged[key] = item[key]
    return merged


def primitive_local_box(node: dict[str, Any], item: dict[str, Any]) -> dict[str, float]:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    bbox = item.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return {
            "x": x + relative_or_absolute(bbox[0], width),
            "y": y + relative_or_absolute(bbox[1], height),
            "w": relative_or_absolute(bbox[2], width),
            "h": relative_or_absolute(bbox[3], height),
        }
    item_w = relative_or_absolute(item.get("w", item.get("width", width)), width)
    item_h = relative_or_absolute(item.get("h", item.get("height", height)), height)
    anchor = str(item.get("anchor", "top_left")).lower()
    local_x = relative_or_absolute(item.get("x", item.get("cx", 0.0)), width)
    local_y = relative_or_absolute(item.get("y", item.get("cy", 0.0)), height)
    if "cx" in item or anchor in {"center", "centre", "middle"}:
        item_x = x + local_x - item_w / 2
        item_y = y + local_y - item_h / 2
    else:
        item_x = x + local_x
        item_y = y + local_y
    return {"x": item_x, "y": item_y, "w": item_w, "h": item_h}


def primitive_local_point(node: dict[str, Any], raw: Any) -> tuple[float, float] | None:
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    try:
        x = float(node["x"]) + relative_or_absolute(raw[0], float(node["w"]))
        y = float(node["y"]) + relative_or_absolute(raw[1], float(node["h"]))
        return x, y
    except (TypeError, ValueError):
        return None


def primitive_points(node: dict[str, Any], raw_points: Any) -> list[tuple[float, float]]:
    if not isinstance(raw_points, list):
        return []
    points: list[tuple[float, float]] = []
    for raw_point in raw_points:
        point = primitive_local_point(node, raw_point)
        if point is not None:
            points.append(point)
    return points


def draw_polyline_wave(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    points = primitive_points(node, node.get("points"))
    if not points:
        samples = node.get("samples")
        if isinstance(samples, list) and samples:
            values = [float(item) for item in samples if isinstance(item, (int, float))]
            if len(values) == 1:
                values = [values[0], values[0]]
            baseline = y + height * float(node.get("baseline_ratio", 0.5))
            amplitude = float(node.get("amplitude_in", height * float(node.get("amplitude_ratio", style.get("amplitude_ratio", 0.38)))))
            points = [
                (x + width * index / max(1, len(values) - 1), baseline - max(-1.0, min(1.0, value)) * amplitude)
                for index, value in enumerate(values)
            ]
    if not points:
        # Non-strict fallback only. Strict validation requires samples/points so exact replicas do not silently become sine waves.
        baseline = y + height * float(node.get("baseline_ratio", 0.5))
        points = [(x, baseline), (x + width, baseline)]
    line_style = merge_style(style, {"fill": "none", "end_arrow": node.get("end_arrow", style.get("end_arrow", "none"))})
    return draw_single_path(page, page_height, points, line_style, "polyline")


def ribbon_box_points(node: dict[str, Any], style: dict[str, Any]) -> list[tuple[float, float]]:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    direction = str(node.get("direction", style.get("direction", "right"))).lower()
    cx = x + width / 2
    cy = y + height / 2

    if direction in {"up", "top", "north", "n", "down", "bottom", "south", "s"}:
        body_width = min(max(float(node.get("body_width_in", style.get("body_width_in", width * 0.42)) or width * 0.42), 0.01), width)
        head_width = min(max(float(node.get("head_width_in", style.get("head_width_in", width * 0.92)) or width * 0.92), body_width), width)
        head_length = min(max(float(node.get("head_length_in", style.get("head_length_in", min(height * 0.34, width * 0.92))) or min(height * 0.34, width * 0.92)), 0.01), height * 0.85)
        if direction in {"up", "top", "north", "n"}:
            return [
                (cx - body_width / 2, y + height),
                (cx - body_width / 2, y + head_length),
                (cx - head_width / 2, y + head_length),
                (cx, y),
                (cx + head_width / 2, y + head_length),
                (cx + body_width / 2, y + head_length),
                (cx + body_width / 2, y + height),
            ]
        return [
            (cx - body_width / 2, y),
            (cx - body_width / 2, y + height - head_length),
            (cx - head_width / 2, y + height - head_length),
            (cx, y + height),
            (cx + head_width / 2, y + height - head_length),
            (cx + body_width / 2, y + height - head_length),
            (cx + body_width / 2, y),
        ]

    body_width = min(max(float(node.get("body_width_in", style.get("body_width_in", height * 0.42)) or height * 0.42), 0.01), height)
    head_width = min(max(float(node.get("head_width_in", style.get("head_width_in", height * 0.92)) or height * 0.92), body_width), height)
    head_length = min(max(float(node.get("head_length_in", style.get("head_length_in", min(width * 0.34, height * 0.92))) or min(width * 0.34, height * 0.92)), 0.01), width * 0.85)
    if direction in {"left", "west", "w"}:
        return [
            (x + width, cy - body_width / 2),
            (x + head_length, cy - body_width / 2),
            (x + head_length, cy - head_width / 2),
            (x, cy),
            (x + head_length, cy + head_width / 2),
            (x + head_length, cy + body_width / 2),
            (x + width, cy + body_width / 2),
        ]
    return [
        (x, cy - body_width / 2),
        (x + width - head_length, cy - body_width / 2),
        (x + width - head_length, cy - head_width / 2),
        (x + width, cy),
        (x + width - head_length, cy + head_width / 2),
        (x + width - head_length, cy + body_width / 2),
        (x, cy + body_width / 2),
    ]


def node_path_points(node: dict[str, Any]) -> list[tuple[float, float]]:
    raw_points = node.get("points")
    if isinstance(raw_points, list) and len(raw_points) >= 2:
        points: list[tuple[float, float]] = []
        for point in raw_points:
            if isinstance(point, list) and len(point) == 2:
                points.append((float(point[0]), float(point[1])))
        if len(points) >= 2:
            return points
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    return [(x, y + height / 2), (x + width, y + height / 2)]


def loop_ribbon_points(node: dict[str, Any]) -> list[tuple[float, float]]:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    cx = x + width / 2
    cy = y + height / 2
    start_deg = float(node.get("start_angle_deg", 205))
    sweep_deg = float(node.get("sweep_angle_deg", 300))
    samples = max(8, int(node.get("smooth_samples", node.get("samples", 28)) or 28))
    return [
        (
            cx + math.cos(math.radians(start_deg + sweep_deg * index / samples)) * width / 2,
            cy + math.sin(math.radians(start_deg + sweep_deg * index / samples)) * height / 2,
        )
        for index in range(samples + 1)
    ]


def draw_ribbon_arrow(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any], mode: str) -> Any:
    if mode == "ribbon_arrow":
        shape = draw_polygon_from_points(page, page_height, ribbon_box_points(node, style))
        fill = node.get("fill", style.get("fill", "#2E88B5"))
        ribbon_style = merge_style(style, {"fill": fill, "line": node.get("line", style.get("line", fill))})
        apply_style(shape, ribbon_style)
        return shape

    points = loop_ribbon_points(node) if mode == "loop_ribbon_arrow" else node_path_points(node)
    if len(points) < 2:
        raise ValueError(f"{mode} node `{node.get('id', '<unknown>')}` requires at least two points.")
    body_width = float(node.get("body_width_in", node.get("ribbon_width_in", style.get("body_width_in", style.get("ribbon_width_in", 0.16)))) or 0.16)
    line_style = merge_style(
        style,
        {
            "fill": "none",
            "line": node.get("fill", node.get("line", style.get("fill", style.get("line", "#2E88B5")))),
            "line_weight_pt": body_width * 72.0,
            "end_arrow": node.get("end_arrow", style.get("end_arrow", "triangle")),
            "arrow_size": node.get("arrow_size", style.get("arrow_size", "xlarge")),
        },
    )
    curve_mode = str(node.get("curve_mode", style.get("curve_mode", "smooth"))).lower()
    if curve_mode in {"", "auto"}:
        curve_mode = "smooth"
    return draw_single_path(page, page_height, points, line_style, curve_mode)


def draw_cell_strip(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", style.get("orientation", "horizontal"))).lower()
    if orientation in {"vertical", "v", "column", "col"}:
        cols = int(node.get("cols", node.get("columns", 1)))
        rows = int(node.get("rows", node.get("cell_count", node.get("count", node.get("cells_count", 1)))))
    else:
        rows = int(node.get("rows", 1))
        cols = int(node.get("cols", node.get("columns", node.get("cell_count", node.get("count", node.get("cells_count", 1))))))
    rows = max(1, rows)
    cols = max(1, cols)
    gap = float(node.get("cell_gap_in", node.get("gap_in", style.get("cell_gap_in", 0.0))) or 0.0)
    cell_w = max(0.01, (width - gap * (cols - 1)) / cols)
    cell_h = max(0.01, (height - gap * (rows - 1)) / rows)
    raw_cells = node.get("cells", [])
    cells = raw_cells if isinstance(raw_cells, list) else []
    labels = node.get("labels")
    label_list = labels if isinstance(labels, list) else []
    default_cell_style = {
        "fill": style.get("cell_fill", style.get("fill", "#FFFFFF")),
        "line": style.get("cell_line", style.get("line", "#111827")),
        "line_weight_pt": style.get("cell_line_weight_pt", style.get("line_weight_pt", 0.55)),
        "line_dash": style.get("line_dash", "solid"),
        "rounding_in": node.get("cell_rounding_in", node.get("rounding_in", style.get("cell_rounding_in", 0.0))),
        "text_fit": "single_line",
        "min_font_size_pt": node.get("cell_min_font_size_pt", style.get("cell_min_font_size_pt", 4.5)),
        "text_margin_in": node.get("cell_text_margin_in", style.get("text_margin_in", 0.0)),
    }
    first_shape = None
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col
            raw_cell = cells[index] if index < len(cells) else {}
            cell = raw_cell if isinstance(raw_cell, dict) else {"text": raw_cell} if raw_cell not in {None, ""} else {}
            cell_node = {
                "x": x + col * (cell_w + gap),
                "y": y + row * (cell_h + gap),
                "w": cell_w,
                "h": cell_h,
            }
            shape = draw_rectangle(page, page_height, cell_node)
            cell_style = primitive_style(style, cell, default_cell_style)
            apply_style(shape, cell_style, str(cell.get("text", label_list[index] if index < len(label_list) else "")))
            first_shape = shape if first_shape is None else first_shape
    return first_shape


def draw_micro_grid(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    grid_node = dict(node)
    if "rows" not in grid_node:
        grid_node["rows"] = int(node.get("grid_rows", 2))
    if "cols" not in grid_node and "columns" not in grid_node:
        grid_node["cols"] = int(node.get("grid_cols", 2))
    return draw_cell_strip(page, page_height, grid_node, style)


def draw_primitive_subshape(page: Any, page_height: float, node: dict[str, Any], item: dict[str, Any], style: dict[str, Any]) -> Any | None:
    shape_kind = str(item.get("shape", item.get("kind", item.get("type", "rect")))).lower()
    item_style = primitive_style(style, item)
    if shape_kind in {"rect", "rectangle", "rounded_rect", "rounded_rectangle", "square"}:
        box = primitive_local_box(node, item)
        shape = draw_rectangle(page, page_height, box)
        if shape_kind in {"rounded_rect", "rounded_rectangle"} and "rounding_in" not in item_style:
            item_style["rounding_in"] = min(float(box["w"]), float(box["h"])) * 0.10
        apply_style(shape, item_style, str(item.get("text", "")))
        return shape
    if shape_kind in {"circle", "ellipse", "oval", "dot"}:
        box = primitive_local_box(node, item)
        shape = draw_oval(page, page_height, box)
        apply_style(shape, item_style, str(item.get("text", "")))
        return shape
    if shape_kind in {"triangle", "polygon"}:
        points = primitive_points(node, item.get("points"))
        if not points:
            box = primitive_local_box(node, item)
            points = [
                (box["x"] + box["w"] / 2, box["y"]),
                (box["x"] + box["w"], box["y"] + box["h"]),
                (box["x"], box["y"] + box["h"]),
            ]
        shape = draw_polygon_from_points(page, page_height, points)
        apply_style(shape, item_style)
        return shape
    if shape_kind in {"line", "segment"}:
        start = primitive_local_point(node, item.get("from", item.get("start")))
        end = primitive_local_point(node, item.get("to", item.get("end")))
        if start is None or end is None:
            box = primitive_local_box(node, item)
            start = (box["x"], box["y"] + box["h"] / 2)
            end = (box["x"] + box["w"], box["y"] + box["h"] / 2)
        return draw_line_segment(page, page_height, start, end, item_style)
    if shape_kind in {"polyline", "path", "arc"}:
        points = primitive_points(node, item.get("points"))
        if len(points) < 2:
            return None
        curve_mode = str(item.get("curve_mode", item.get("curve", "polyline"))).lower()
        return draw_single_path(page, page_height, points, item_style, curve_mode)
    if shape_kind in {"text", "label"}:
        box = primitive_local_box(node, item)
        return draw_text_box(page, page_height, box["x"], box["y"], box["w"], box["h"], str(item.get("text", "")), item_style)
    if shape_kind in {"plus", "cross_plus"}:
        box = primitive_local_box(node, item)
        horizontal = draw_line_segment(page, page_height, (box["x"], box["y"] + box["h"] / 2), (box["x"] + box["w"], box["y"] + box["h"] / 2), item_style)
        draw_line_segment(page, page_height, (box["x"] + box["w"] / 2, box["y"]), (box["x"] + box["w"] / 2, box["y"] + box["h"]), item_style)
        return horizontal
    if shape_kind in {"x", "cross", "times"}:
        box = primitive_local_box(node, item)
        first = draw_line_segment(page, page_height, (box["x"], box["y"]), (box["x"] + box["w"], box["y"] + box["h"]), item_style)
        draw_line_segment(page, page_height, (box["x"] + box["w"], box["y"]), (box["x"], box["y"] + box["h"]), item_style)
        return first
    return None


def symbol_kind_subshapes(kind: str) -> list[dict[str, Any]]:
    if kind in {"circle_plus", "plus_circle", "add_circle"}:
        return [
            {"shape": "circle", "bbox": [0.05, 0.05, 0.90, 0.90], "fill": "none"},
            {"shape": "plus", "bbox": [0.30, 0.30, 0.40, 0.40]},
        ]
    if kind in {"triangle_gate", "triangle_in_circle"}:
        return [
            {"shape": "circle", "bbox": [0.04, 0.04, 0.92, 0.92], "fill": "none"},
            {"shape": "triangle", "points": [[0.38, 0.28], [0.72, 0.50], [0.38, 0.72]], "fill": "none"},
        ]
    if kind in {"x_circle", "cross_circle"}:
        return [
            {"shape": "circle", "bbox": [0.05, 0.05, 0.90, 0.90], "fill": "none"},
            {"shape": "x", "bbox": [0.32, 0.32, 0.36, 0.36]},
        ]
    if kind in {"refresh_arrow", "loop_arrow"}:
        return [
            {
                "shape": "polyline",
                "points": [[0.72, 0.26], [0.86, 0.42], [0.80, 0.63], [0.58, 0.78], [0.34, 0.70], [0.22, 0.50], [0.30, 0.30], [0.52, 0.22]],
                "curve_mode": "smooth",
                "end_arrow": "triangle",
                "fill": "none",
            }
        ]
    return []


def draw_primitive_group(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    subshapes = node.get("subshapes", node.get("parts", node.get("primitives", [])))
    if not isinstance(subshapes, list) or not subshapes:
        subshapes = [{"shape": node.get("shape", "rect"), "bbox": [0, 0, 1, 1], "fill": style.get("fill", "none")}]
    first_shape = None
    for raw_item in subshapes:
        if not isinstance(raw_item, dict):
            continue
        shape = draw_primitive_subshape(page, page_height, node, raw_item, style)
        first_shape = shape if first_shape is None and shape is not None else first_shape
    if first_shape is None:
        first_shape = draw_rectangle(page, page_height, node)
        apply_style(first_shape, merge_style(style, {"fill": "none", "line": "none"}))
    return first_shape


def draw_symbol_group(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    if isinstance(node.get("subshapes"), list) and node.get("subshapes"):
        return draw_primitive_group(page, page_height, node, style)
    kind = str(node.get("symbol_kind", node.get("motif", node.get("shape", "")))).lower()
    symbol_node = dict(node)
    symbol_node["subshapes"] = symbol_kind_subshapes(kind)
    if not symbol_node["subshapes"]:
        symbol_node["subshapes"] = [{"shape": "text", "bbox": [0, 0, 1, 1], "text": node.get("symbol", node.get("text", ""))}]
    return draw_primitive_group(page, page_height, symbol_node, style)


def classifier_blocks(node: dict[str, Any]) -> list[dict[str, Any]]:
    raw_blocks = node.get("blocks", node.get("labels", ["AvgPool", "Linear"]))
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raw_blocks = ["AvgPool", "Linear"]

    blocks: list[dict[str, Any]] = []
    for item in raw_blocks:
        if isinstance(item, dict):
            blocks.append(item)
        else:
            blocks.append({"text": str(item)})
    return blocks


def sequence_blocks(node: dict[str, Any]) -> list[dict[str, Any]]:
    raw_blocks = node.get("blocks", node.get("labels", []))
    if not isinstance(raw_blocks, list):
        raw_blocks = []

    blocks: list[dict[str, Any]] = []
    for item in raw_blocks:
        if isinstance(item, dict):
            blocks.append(item)
        else:
            blocks.append({"text": str(item)})
    return blocks


def draw_layer_sequence(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    frame_visible = truthy(node.get("frame_visible", style.get("frame_visible")), True)
    shape = None
    if frame_visible:
        shape = draw_rectangle(page, page_height, node)
        apply_style(shape, style, node.get("title", node.get("text", "")))

    padding = float(node.get("padding_in", style.get("padding_in", 0.10)))
    padding_x = float(node.get("padding_x_in", style.get("padding_x_in", padding)) or padding)
    padding_y = float(node.get("padding_y_in", style.get("padding_y_in", padding)) or padding)
    padding_left = float(node.get("padding_left_in", style.get("padding_left_in", padding_x)) or padding_x)
    padding_right = float(node.get("padding_right_in", style.get("padding_right_in", padding_x)) or padding_x)
    padding_top = float(node.get("padding_top_in", style.get("padding_top_in", padding_y)) or padding_y)
    padding_bottom = float(node.get("padding_bottom_in", style.get("padding_bottom_in", padding_y)) or padding_y)
    title = str(node.get("title", node.get("text", ""))).strip()
    title_area_ratio = float(node.get("title_area_ratio", style.get("title_area_ratio", 0.22)) or 0.22)
    title_h_default = min(height * max(0.12, min(0.40, title_area_ratio)), 0.42)
    title_h = float(node.get("title_h_in", style.get("title_h_in", title_h_default))) if title else 0.0
    title_gap = float(node.get("title_gap_in", style.get("title_gap_in", 0.04))) if title else 0.0
    title_align = int(node.get("title_align", style.get("title_align", 1)))
    title_baseline_offset = float(node.get("title_baseline_offset_in", style.get("title_baseline_offset_in", 0.0)) or 0.0)
    if title:
        title_style = merge_style(
            style,
            {
                "fill": "none",
                "line": "none",
                "font_size_pt": node.get("title_font_size_pt", style.get("title_font_size_pt", style.get("font_size_pt", 15))),
                "font_weight": node.get("title_font_weight", style.get("title_font_weight", "bold")),
                "text_angle_deg": 0,
                "text_align": title_align,
                "vertical_align": 1,
                "baseline_offset_in": title_baseline_offset,
            },
        )
        draw_text_box(
            page,
            page_height,
            x + padding_left,
            y + padding_top * 0.55,
            max(0.05, width - padding_left - padding_right),
            title_h,
            title,
            title_style,
        )

    content_padding_left = float(node.get("content_padding_left_in", style.get("content_padding_left_in", 0.0)) or 0.0)
    content_padding_right = float(node.get("content_padding_right_in", style.get("content_padding_right_in", 0.0)) or 0.0)
    content_padding_top = float(node.get("content_padding_top_in", style.get("content_padding_top_in", 0.0)) or 0.0)
    content_padding_bottom = float(node.get("content_padding_bottom_in", style.get("content_padding_bottom_in", 0.0)) or 0.0)
    content_x = x + padding_left + content_padding_left
    content_y = y + padding_top + title_h + title_gap + content_padding_top
    content_w = max(0.05, width - padding_left - padding_right - content_padding_left - content_padding_right)
    content_h = max(0.05, y + height - padding_bottom - content_padding_bottom - content_y)
    blocks = sequence_blocks(node)
    if not blocks:
        if shape is not None:
            return shape
        return draw_rectangle(page, page_height, merge_style(node, {"w": 0.01, "h": 0.01}))

    orientation = str(node.get("orientation", style.get("orientation", "horizontal"))).lower()
    gap = float(node.get("block_gap_in", style.get("block_gap_in", 0.08)))
    block_style_mode = str(node.get("block_style_mode", style.get("block_style_mode", ""))).lower()
    block_count = max(1, len(blocks))
    dense_mode = truthy(node.get("dense", style.get("dense")), False) or str(node.get("density_mode", style.get("density_mode", ""))).lower() in {
        "dense",
        "source_dense",
        "paper_dense",
        "compact",
    }
    if dense_mode and "block_gap_in" not in node:
        gap = min(gap, max(0.015, content_w * 0.018 / block_count))
    if dense_mode and "title_h_in" not in node and title:
        title_h = min(title_h, height * 0.20)
        content_y = y + padding_top + title_h + title_gap + content_padding_top
        content_h = max(0.05, y + height - padding_bottom - content_padding_bottom - content_y)
    if block_style_mode in {"white_capsule", "capsule_white", "white", "paper_capsule"}:
        style = merge_style(
            style,
            {
                "block_fill": node.get("block_fill", style.get("block_fill", "#FFFFFF")),
                "block_line": node.get("block_line", style.get("block_line", "#111111")),
                "block_line_weight_pt": node.get("block_line_weight_pt", style.get("block_line_weight_pt", 1.0)),
                "block_rounding_in": node.get("block_rounding_in", style.get("block_rounding_in", 0.14)),
                "block_depth_x_in": node.get("block_depth_x_in", style.get("block_depth_x_in", 0.0)),
                "block_depth_y_in": node.get("block_depth_y_in", style.get("block_depth_y_in", 0.0)),
            },
        )
    elif block_style_mode in {
        "paper_vertical_strip",
        "vertical_strip",
        "rounded_strip",
        "paper_strip",
        "tall_rounded",
        "colored_paper_strip",
        "colored_vertical_strip",
        "paper_colored_strip",
    }:
        style = merge_style(
            style,
            {
                "block_fill": node.get("block_fill", style.get("block_fill", "#FFFFFF")),
                "block_line": node.get("block_line", style.get("block_line", "#111111")),
                "block_line_weight_pt": node.get("block_line_weight_pt", style.get("block_line_weight_pt", 1.25)),
                "block_rounding_in": node.get("block_rounding_in", style.get("block_rounding_in", 0.18)),
                "block_depth_x_in": 0.0,
                "block_depth_y_in": 0.0,
                "block_shadow": node.get("block_shadow", style.get("block_shadow")),
                "block_constrain_text_box": node.get("block_constrain_text_box", style.get("block_constrain_text_box", True)),
            },
        )
    elif block_style_mode in {"white_cuboid", "paper_cuboid", "paper_vertical_cuboid", "white_3d", "paper_3d_vertical_strip", "source_3d_strip"}:
        style = merge_style(
            style,
            {
                "block_fill": node.get("block_fill", style.get("block_fill", "#FFFFFF")),
                "block_line": node.get("block_line", style.get("block_line", "#111111")),
                "block_line_weight_pt": node.get("block_line_weight_pt", style.get("block_line_weight_pt", 1.25 if dense_mode else 1.0)),
                "block_rounding_in": node.get("block_rounding_in", style.get("block_rounding_in", 0.02)),
                "block_depth_x_in": node.get("block_depth_x_in", style.get("block_depth_x_in", 0.07 if dense_mode else 0.04)),
                "block_depth_y_in": node.get("block_depth_y_in", style.get("block_depth_y_in", -0.055 if dense_mode else -0.035)),
                "side_fill": node.get("block_side_fill", style.get("block_side_fill", "#E6E6E6")),
                "top_fill": node.get("block_top_fill", style.get("block_top_fill", "#F6F6F6")),
                "block_constrain_text_box": node.get("block_constrain_text_box", style.get("block_constrain_text_box", True)),
            },
        )
    elif block_style_mode in {"flat_colored", "colored_flat", "simple_colored"}:
        style = merge_style(
            style,
            {
                "block_depth_x_in": node.get("block_depth_x_in", style.get("block_depth_x_in", 0.0)),
                "block_depth_y_in": node.get("block_depth_y_in", style.get("block_depth_y_in", 0.0)),
            },
        )
    block_style_base = merge_style(
        style,
        {
            "fill": node.get("block_fill", style.get("block_fill", "#FFFFFF")),
            "line": node.get("block_line", style.get("block_line", style.get("line", "#111111"))),
            "line_weight_pt": node.get("block_line_weight_pt", style.get("block_line_weight_pt", 1.0)),
            "line_dash": node.get("block_line_dash", style.get("block_line_dash", "solid")),
            "rounding_in": node.get("block_rounding_in", style.get("block_rounding_in", 0.04)),
            "font_size_pt": node.get("block_font_size_pt", style.get("block_font_size_pt", max(8, float(style.get("font_size_pt", 12)) - 1))),
            "font_weight": node.get("block_font_weight", style.get("block_font_weight", "regular")),
            "text_align": 1,
            "vertical_align": 1,
        },
    )

    if orientation in {"horizontal", "h", "horizontal_bars", "bars", "side_by_side"}:
        extra_gaps = sum(float(block.get("gap_after_in", 0) or 0) for block in blocks[:-1] if isinstance(block, dict))
        fixed_width = 0.0
        ratio_width = 0.0
        flex_count = 0
        for block in blocks:
            if not isinstance(block, dict):
                flex_count += 1
                continue
            width_value = block.get("w", block.get("width"))
            width_ratio = block.get("w_ratio", block.get("width_ratio"))
            if isinstance(width_value, (int, float)):
                fixed_width += float(width_value)
            elif isinstance(width_ratio, (int, float)) and float(width_ratio) > 0:
                ratio_width += float(width_ratio)
            else:
                flex_count += 1
        remaining_width = max(0.02 * len(blocks), content_w - gap * max(0, len(blocks) - 1) - extra_gaps - fixed_width)
        width_unit = remaining_width / max(1.0, ratio_width + flex_count)
        default_block_w = max(0.02, width_unit)
        default_block_h = content_h * (0.96 if dense_mode else 0.82)
        block_h = min(content_h, float(node.get("block_height_in", style.get("block_height_in", default_block_h))))
        content_align_y = str(node.get("content_align_y", style.get("content_align_y", "center"))).lower()
        if content_align_y in {"top", "start"}:
            block_y = content_y
        elif content_align_y in {"bottom", "end"}:
            block_y = content_y + max(0.0, content_h - block_h)
        else:
            block_y = content_y + max(0.0, (content_h - block_h) / 2)
        cursor_x = content_x
        previous_right_center: tuple[float, float] | None = None
        block_connector_style = merge_style(
            {
                "line": node.get("block_connector_line", style.get("block_connector_line", style.get("line", "#111111"))),
                "line_weight_pt": node.get("block_connector_line_weight_pt", style.get("block_connector_line_weight_pt", style.get("line_weight_pt", 1.0))),
                "line_dash": node.get("block_connector_line_dash", style.get("block_connector_line_dash", "solid")),
                "end_arrow": node.get("block_connector_end_arrow", style.get("block_connector_end_arrow", "triangle")),
                "arrow_size": node.get("block_connector_arrow_size", style.get("block_connector_arrow_size", "tiny")),
            },
            node.get("block_connector_style") if isinstance(node.get("block_connector_style"), dict) else None,
        )
        draw_internal_arrows = truthy(node.get("draw_internal_arrows", style.get("draw_internal_arrows")), False)
        for index, block in enumerate(blocks):
            width_ratio = block.get("w_ratio", block.get("width_ratio")) if isinstance(block, dict) else None
            if isinstance(block.get("w", block.get("width")), (int, float)):
                block_w = float(block.get("w", block.get("width", default_block_w)))
            elif isinstance(width_ratio, (int, float)) and float(width_ratio) > 0:
                block_w = max(0.02, width_unit * float(width_ratio))
            else:
                block_w = default_block_w
            text = str(block.get("text", block.get("label", "")))
            text_angle_default = 90
            if dense_mode and any(ord(char) > 255 for char in text):
                text_angle_default = 0
            block_style = merge_style(
                block_style_base,
                {"fill": block_fill_for_index(node, style, index)} if block_fill_for_index(node, style, index) else None,
                {
                    "text_angle_deg": node.get("block_text_angle_deg", style.get("block_text_angle_deg", text_angle_default)),
                    "text_box_width_in": block_h,
                    "text_box_height_in": block_w,
                    "text_fit": node.get("block_text_fit", style.get("block_text_fit", "single_line")),
                    "min_font_size_pt": node.get("block_min_font_size_pt", style.get("block_min_font_size_pt", 6)),
                    "constrain_text_box": node.get("block_constrain_text_box", style.get("block_constrain_text_box", True if dense_mode else False)),
                    "expand_text_box_for_single_line": False,
                },
                block.get("style") if isinstance(block.get("style"), dict) else None,
            )
            block_shape = draw_layer_block(
                page,
                page_height,
                {"x": cursor_x, "y": block_y, "w": block_w, "h": block_h},
                block_style,
                text,
            )
            if shape is None:
                shape = block_shape
            center_y = block_y + block_h / 2
            if draw_internal_arrows and previous_right_center is not None and cursor_x > previous_right_center[0] + 0.01:
                draw_line_segment(page, page_height, previous_right_center, (cursor_x, center_y), block_connector_style)
            previous_right_center = (cursor_x + block_w, center_y)
            cursor_x += block_w + gap + float(block.get("gap_after_in", 0) or 0)
    elif orientation in {"vertical", "v", "vertical_stack", "stack", "rows", "row_stack"}:
        extra_gaps = sum(float(block.get("gap_after_in", 0) or 0) for block in blocks[:-1] if isinstance(block, dict))
        fixed_height = 0.0
        ratio_height = 0.0
        flex_count = 0
        for block in blocks:
            if not isinstance(block, dict):
                flex_count += 1
                continue
            height_value = block.get("h", block.get("height"))
            height_ratio = block.get("h_ratio", block.get("height_ratio"))
            if isinstance(height_value, (int, float)):
                fixed_height += float(height_value)
            elif isinstance(height_ratio, (int, float)) and float(height_ratio) > 0:
                ratio_height += float(height_ratio)
            else:
                flex_count += 1
        remaining_height = max(0.02 * len(blocks), content_h - gap * max(0, len(blocks) - 1) - extra_gaps - fixed_height)
        height_unit = remaining_height / max(1.0, ratio_height + flex_count)
        default_block_h = max(0.02, height_unit)
        block_w = min(content_w, float(node.get("block_width_in", style.get("block_width_in", content_w * (0.96 if dense_mode else 0.88)))))
        content_align_x = str(node.get("content_align_x", style.get("content_align_x", "center"))).lower()
        if content_align_x in {"left", "start"}:
            block_x = content_x
        elif content_align_x in {"right", "end"}:
            block_x = content_x + max(0.0, content_w - block_w)
        else:
            block_x = content_x + max(0.0, (content_w - block_w) / 2)
        cursor_y = content_y
        for index, block in enumerate(blocks):
            height_ratio = block.get("h_ratio", block.get("height_ratio")) if isinstance(block, dict) else None
            if isinstance(block.get("h", block.get("height")), (int, float)):
                block_h = float(block.get("h", block.get("height", default_block_h)))
            elif isinstance(height_ratio, (int, float)) and float(height_ratio) > 0:
                block_h = max(0.02, height_unit * float(height_ratio))
            else:
                block_h = default_block_h
            text = str(block.get("text", block.get("label", "")))
            block_style = merge_style(
                block_style_base,
                {"fill": block_fill_for_index(node, style, index)} if block_fill_for_index(node, style, index) else None,
                {
                    "text_angle_deg": node.get("block_text_angle_deg", style.get("block_text_angle_deg", 0)),
                    "text_fit": node.get("block_text_fit", style.get("block_text_fit", "shrink_to_fit")),
                    "min_font_size_pt": node.get("block_min_font_size_pt", style.get("block_min_font_size_pt", 6)),
                    "constrain_text_box": node.get("block_constrain_text_box", style.get("block_constrain_text_box", True if dense_mode else False)),
                    "expand_text_box_for_single_line": False,
                },
                block.get("style") if isinstance(block.get("style"), dict) else None,
            )
            block_shape = draw_layer_block(
                page,
                page_height,
                {"x": block_x, "y": cursor_y, "w": block_w, "h": block_h},
                block_style,
                text,
            )
            if shape is None:
                shape = block_shape
            cursor_y += block_h + gap + float(block.get("gap_after_in", 0) or 0)
    else:
        raise ValueError("layer_sequence orientation must be horizontal/horizontal_bars or vertical/vertical_stack.")

    return shape


def block_fill_for_index(node: dict[str, Any], style: dict[str, Any], index: int) -> str | None:
    block_mode = str(node.get("block_style_mode", style.get("block_style_mode", ""))).lower()
    fill_policy = str(node.get("block_fill_policy", style.get("block_fill_policy", ""))).lower()
    colored_modes = {
        "colored_paper_strip",
        "colored_vertical_strip",
        "paper_colored_strip",
        "flat_colored",
        "colored_flat",
        "simple_colored",
    }
    fills = node.get("block_fills", style.get("block_fills"))
    preserve_colors = (
        block_mode in colored_modes
        or fill_policy in {"preserve", "source", "source_colors", "colored", "block_fills", "fills"}
        or truthy(node.get("preserve_block_fills", style.get("preserve_block_fills")), False)
    )
    if preserve_colors and isinstance(fills, list) and fills:
        return str(fills[index % len(fills)])
    if (node.get("ignore_block_fills") or fill_policy in {"ignore", "white", "block_fill", "fixed"}) and not preserve_colors:
        return str(node.get("block_fill", style.get("block_fill", "#FFFFFF"))) if fill_policy in {"white", "block_fill", "fixed"} else None
    if block_mode in {
        "white_capsule",
        "capsule_white",
        "white",
        "paper_capsule",
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
        return str(node.get("block_fill", style.get("block_fill", "#FFFFFF")))
    if isinstance(fills, list) and fills:
        return str(fills[index % len(fills)])
    return None


def draw_layer_block(page: Any, page_height: float, block_node: dict[str, Any], block_style: dict[str, Any], text: str) -> Any:
    depth_x = float(block_style.get("block_depth_x_in", block_style.get("depth_x_in", 0.0)) or 0.0)
    depth_y = float(block_style.get("block_depth_y_in", block_style.get("depth_y_in", 0.0)) or 0.0)
    as_cuboid = bool(block_style.get("block_3d", block_style.get("as_cuboid", False))) or abs(depth_x) > 1e-9 or abs(depth_y) > 1e-9
    if as_cuboid:
        shape = draw_cuboid_node(
            page,
            page_height,
            merge_style(block_node, {"depth_x_in": depth_x, "depth_y_in": depth_y}),
            merge_style(
                block_style,
                {
                    "depth_x_in": depth_x,
                    "depth_y_in": depth_y,
                    "side_fill": block_style.get("side_fill", darker_fill(str(block_style.get("fill", "#FFFFFF")), 0.16)),
                    "top_fill": block_style.get("top_fill", lighter_fill(str(block_style.get("fill", "#FFFFFF")), 0.12)),
                },
            ),
        )
        if text and abs((float(block_style.get("text_angle_deg", 0) or 0) % 180) - 90) <= 1e-3:
            apply_style(shape, block_style, "", float(block_node["w"]), float(block_node["h"]))
            text_style = merge_style(block_style, {"shadow": None, "block_shadow": None})
            draw_rotated_text_box(
                page,
                page_height,
                float(block_node["x"]),
                float(block_node["y"]),
                float(block_node["w"]),
                float(block_node["h"]),
                text,
                text_style,
            )
        else:
            apply_style(shape, block_style, text, float(block_node["w"]), float(block_node["h"]))
            if text:
                try_set_text(shape, text)
        return shape
    if block_style.get("block_shadow") and "shadow" not in block_style:
        block_style = merge_style(block_style, {"shadow": block_style.get("block_shadow")})
    if text and abs((float(block_style.get("text_angle_deg", 0) or 0) % 180) - 90) <= 1e-3:
        shape = draw_rectangle(page, page_height, block_node)
        apply_style(shape, block_style, "", float(block_node["w"]), float(block_node["h"]))
        text_style = merge_style(block_style, {"shadow": None, "block_shadow": None})
        draw_rotated_text_box(
            page,
            page_height,
            float(block_node["x"]),
            float(block_node["y"]),
            float(block_node["w"]),
            float(block_node["h"]),
            text,
            text_style,
        )
        return shape
    return draw_resizable_text(
        page,
        page_height,
        float(block_node["x"]),
        float(block_node["y"]),
        float(block_node["w"]),
        float(block_node["h"]),
        text,
        block_style,
    )


def draw_classifier_head(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    orientation = str(node.get("orientation", "horizontal")).lower()
    if orientation in {"vertical", "v"}:
        return draw_classifier_head_vertical(page, page_height, node, style)
    if orientation not in {"horizontal", "h"}:
        raise ValueError("classifier_head orientation must be horizontal or vertical.")

    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    padding = float(node.get("padding_in", style.get("padding_in", 0.04)))
    gap = float(node.get("block_gap_in", style.get("block_gap_in", 0.08)))
    inner_w = max(0.01, width - padding * 2)
    inner_h = max(0.01, height - padding * 2)
    blocks = classifier_blocks(node)
    output_labels = [str(item) for item in node.get("output_labels", [])] if isinstance(node.get("output_labels"), list) else []
    fanout_count = int(node.get("fanout_count", len(output_labels) or 0))
    if output_labels:
        fanout_count = max(fanout_count, len(output_labels))
    output_mode = str(node.get("output_mode", "internal_fanout" if fanout_count else "none")).lower()
    if output_mode in {"none", "boundary", "boundary_fanout", "container_boundary", "external"}:
        fanout_count = 0

    label_w = min(0.42, max(0.18, width * 0.12)) if output_labels else 0.0
    fan_zone_w = min(inner_w * 0.24, max(0.22, float(node.get("fanout_width_in", inner_w * 0.16)))) if fanout_count else 0.0
    block_area_w = max(0.01, inner_w - fan_zone_w - (gap if fanout_count else 0.0) - label_w)
    block_w = max(0.01, (block_area_w - gap * (len(blocks) - 1)) / len(blocks))
    block_h = min(inner_h, float(node.get("block_height_in", inner_h * 0.56)))
    block_y = y + padding + (inner_h - block_h) / 2
    block_style = merge_style(style, {"fill": style.get("fill", "#FFFFFF"), "line": style.get("line", "#111827")})
    connector_style = merge_style(
        {
            "line": style.get("line", "#111827"),
            "line_weight_pt": style.get("line_weight_pt", 1.0),
            "line_dash": style.get("line_dash", "solid"),
            "end_arrow": "triangle",
        },
        node.get("connector_style") if isinstance(node.get("connector_style"), dict) else None,
    )

    shape = None
    previous_center: tuple[float, float] | None = None
    last_right = x + padding
    last_center_y = y + height / 2
    for index, block in enumerate(blocks):
        block_x = x + padding + index * (block_w + gap)
        text = str(block.get("text", block.get("label", "")))
        shape = draw_resizable_text(
            page,
            page_height,
            block_x,
            block_y,
            block_w,
            block_h,
            text,
            merge_style(
                block_style,
                {"text_fit": node.get("block_text_fit", style.get("block_text_fit", "single_line")), "min_font_size_pt": node.get("block_min_font_size_pt", style.get("block_min_font_size_pt", 6))},
                block.get("style") if isinstance(block.get("style"), dict) else None,
            ),
        )

        center = (block_x + block_w / 2, block_y + block_h / 2)
        if previous_center is not None:
            draw_line_segment(
                page,
                page_height,
                (previous_center[0] + block_w / 2, previous_center[1]),
                (block_x, center[1]),
                connector_style,
            )
        previous_center = center
        last_right = block_x + block_w
        last_center_y = center[1]

    if fanout_count:
        trunk_x = min(x + width - padding - label_w - 0.12, last_right + gap + fan_zone_w * 0.35)
        trunk_x = max(trunk_x, last_right + gap)
        fan_end_x = x + width - padding - label_w
        fan_top = y + padding
        fan_bottom = y + height - padding
        if fanout_count == 1:
            branch_ys = [last_center_y]
        else:
            branch_ys = [
                fan_top + (fan_bottom - fan_top) * index / (fanout_count - 1)
                for index in range(fanout_count)
            ]

        draw_line_segment(page, page_height, (last_right, last_center_y), (trunk_x, last_center_y), merge_style(connector_style, {"end_arrow": "none"}))
        if len(branch_ys) > 1:
            draw_line_segment(page, page_height, (trunk_x, min(branch_ys)), (trunk_x, max(branch_ys)), merge_style(connector_style, {"end_arrow": "none"}))
        for index, branch_y in enumerate(branch_ys):
            shape = draw_line_segment(page, page_height, (trunk_x, branch_y), (fan_end_x, branch_y), connector_style)
            if index < len(output_labels):
                draw_text_box(
                    page,
                    page_height,
                    fan_end_x + 0.02,
                    branch_y - min(0.12, height / 8),
                    max(0.12, label_w - 0.02),
                    min(0.24, height / 4),
                    output_labels[index],
                    merge_style(style, {"font_size_pt": max(6, float(style.get("font_size_pt", 10)) - 1)}),
                )

    return shape


def draw_classifier_head_vertical(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    padding = float(node.get("padding_in", style.get("padding_in", 0.04)))
    gap = float(node.get("block_gap_in", style.get("vertical_block_gap_in", style.get("block_gap_in", 0.14))))
    inner_w = max(0.01, width - padding * 2)
    inner_h = max(0.01, height - padding * 2)
    blocks = classifier_blocks(node)
    block_w = min(inner_w, float(node.get("block_width_in", inner_w * 0.88)))
    requested_block_h = node.get("block_height_in")
    if requested_block_h is not None:
        block_h = min(inner_h, float(requested_block_h))
    else:
        block_h = max(0.01, (inner_h - gap * (len(blocks) - 1)) / len(blocks))
    block_x = x + padding + (inner_w - block_w) / 2
    total_h = block_h * len(blocks) + gap * (len(blocks) - 1)
    block_y = y + padding + max(0.0, (inner_h - total_h) / 2)
    block_style = merge_style(style, {"fill": style.get("fill", "#FFFFFF"), "line": style.get("line", "#111827")})
    connector_style = merge_style(
        {
            "line": style.get("line", "#111827"),
            "line_weight_pt": style.get("line_weight_pt", 1.0),
            "line_dash": style.get("line_dash", "solid"),
            "end_arrow": "triangle",
            "arrow_size": node.get("internal_arrow_size", style.get("internal_arrow_size", "small")),
        },
        node.get("connector_style") if isinstance(node.get("connector_style"), dict) else None,
    )

    shape = None
    previous_bottom: tuple[float, float] | None = None
    for index, block in enumerate(blocks):
        current_y = block_y + index * (block_h + gap)
        text = str(block.get("text", block.get("label", "")))
        shape = draw_resizable_text(
            page,
            page_height,
            block_x,
            current_y,
            block_w,
            block_h,
            text,
            merge_style(
                block_style,
                {"text_fit": node.get("block_text_fit", style.get("block_text_fit", "single_line")), "min_font_size_pt": node.get("block_min_font_size_pt", style.get("block_min_font_size_pt", 6))},
                block.get("style") if isinstance(block.get("style"), dict) else None,
            ),
        )

        current_top = (block_x + block_w / 2, current_y)
        if previous_bottom is not None:
            draw_line_segment(page, page_height, previous_bottom, current_top, connector_style)
        previous_bottom = (block_x + block_w / 2, current_y + block_h)

    return shape


def matrix_cell_styles(node: dict[str, Any], style: dict[str, Any]) -> dict[tuple[int, int], str]:
    index_base = int(node.get("index_base", 0))
    default_fill = str(style.get("active_fill", "#2B7C8E"))
    cells: dict[tuple[int, int], str] = {}

    for item in node.get("colored_cells", node.get("cells", [])):
        if isinstance(item, dict):
            row = int(item["row"]) - index_base
            col = int(item["col"]) - index_base
            fill = str(item.get("fill", default_fill))
        elif isinstance(item, list) and len(item) >= 2:
            row = int(item[0]) - index_base
            col = int(item[1]) - index_base
            fill = str(item[2]) if len(item) >= 3 else default_fill
        else:
            continue
        cells[(row, col)] = fill
    return cells


def draw_grid_matrix(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    rows = int(node["rows"])
    cols = int(node["cols"])
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    cell_w = width / cols
    cell_h = height / rows
    base_fill = str(style.get("cell_fill", style.get("fill", "#FFFFFF")))
    colored = matrix_cell_styles(node, style)
    first_shape = None

    for row in range(rows):
        for col in range(cols):
            cell_node = {
                "x": x + col * cell_w,
                "y": y + row * cell_h,
                "w": cell_w,
                "h": cell_h,
            }
            cell_shape = draw_rectangle(page, page_height, cell_node)
            apply_style(
                cell_shape,
                {
                    "fill": colored.get((row, col), base_fill),
                    "line": "none",
                },
            )
            if first_shape is None:
                first_shape = cell_shape

    grid_line_style = {
        "line": style.get("grid_line", style.get("line", "#000000")),
        "line_weight_pt": style.get("grid_line_weight_pt", style.get("line_weight_pt", 1.0)),
        "line_dash": style.get("line_dash", "solid"),
        "end_arrow": "none",
    }

    for col in range(cols + 1):
        gx = x + col * cell_w
        first_shape = draw_line_segment(page, page_height, (gx, y), (gx, y + height), grid_line_style)

    for row in range(rows + 1):
        gy = y + row * cell_h
        first_shape = draw_line_segment(page, page_height, (x, gy), (x + width, gy), grid_line_style)

    return first_shape


def draw_attention_score_motif(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    geom = attention_score_motif_geometry(node, style)
    op_size = geom["op_size"]
    op_x = geom["op_x"]
    op_y = geom["op_y"]
    grid_w = geom["grid_w"]
    grid_h = geom["grid_h"]
    grid_x = geom["grid_x"]
    grid_y = geom["grid_y"]

    line_style = merge_style(
        style,
        {
            "line": node.get("line", style.get("line", "#6E6E6E")),
            "line_weight_pt": node.get("line_weight_pt", style.get("line_weight_pt", 1.15)),
            "end_arrow": node.get("end_arrow", style.get("end_arrow", "triangle")),
            "arrow_size": node.get("arrow_size", style.get("arrow_size", "small")),
            "fill": "none",
        },
    )

    first_shape = None
    input_ports = node.get("input_ports")
    if isinstance(input_ports, list):
        for port in input_ports:
            if not isinstance(port, dict):
                continue
            start = port.get("from_point", port.get("point"))
            if isinstance(start, list) and len(start) == 2:
                start_point = (float(start[0]), float(start[1]))
            else:
                side = str(port.get("side", "left")).lower()
                offset = float(port.get("offset", port.get("position", 0.5)))
                if side in {"left", "right"}:
                    start_point = (x if side == "left" else x + width, y + height * offset)
                else:
                    start_point = (x + width * offset, y if side == "top" else y + height)
            target_ratio = float(port.get("operator_position", port.get("operator_ratio", 0.5)))
            side = str(port.get("operator_side", "left")).lower()
            target_point = attention_score_motif_endpoint(node, f"operator_{side}", target_ratio, style)
            if target_point is None:
                target_point = (op_x, op_y + op_size * max(0.0, min(1.0, target_ratio)))
            port_style = merge_style(line_style, {"end_arrow": "none"})
            first_shape = draw_line_segment(page, page_height, start_point, target_point, port_style)

    operator_node = {
        "id": f"{node.get('id', 'attention_score')}_operator",
        "type": "operator_node",
        "x": op_x,
        "y": op_y,
        "w": op_size,
        "h": op_size,
        "symbol": node.get("operator_symbol", style.get("operator_symbol", "×")),
        "symbol_font_size_pt": node.get("operator_font_size_pt", style.get("operator_font_size_pt", 10)),
    }
    operator_style = merge_style(
        style,
        {
            "fill": node.get("operator_fill", style.get("operator_fill", "#FFFFFF")),
            "line": node.get("operator_line", style.get("operator_line", "#6E6E6E")),
            "line_weight_pt": node.get("operator_line_weight_pt", style.get("operator_line_weight_pt", 1.1)),
            "font_family": style.get("symbol_font_family", style.get("font_family", "Cambria Math")),
            "font_role": "math",
            "symbol_text_fit": "single_line",
            "symbol_text_margin_in": 0.0,
            "symbol_constrain_text_box": True,
        },
    )
    first_shape = draw_operator_node(page, page_height, operator_node, operator_style)

    grid_cells: list[list[Any]] = []
    rows = int(node.get("grid_rows", style.get("grid_rows", 4)))
    cols = int(node.get("grid_cols", style.get("grid_cols", 5)))
    fill_a = str(node.get("grid_cell_fill_a", style.get("grid_cell_fill_a", "#FFD4EA")))
    fill_b = str(node.get("grid_cell_fill_b", style.get("grid_cell_fill_b", "#BFD2F7")))
    raw_cells = node.get("colored_cells")
    if isinstance(raw_cells, list) and raw_cells:
        grid_cells = raw_cells
    else:
        for row in range(rows):
            for col in range(cols):
                grid_cells.append([row, col, fill_a if (row + col) % 2 == 0 else fill_b])

    grid_node = {
        "id": f"{node.get('id', 'attention_score')}_grid",
        "type": "grid_matrix",
        "x": grid_x,
        "y": grid_y,
        "w": grid_w,
        "h": grid_h,
        "rows": rows,
        "cols": cols,
        "colored_cells": grid_cells,
    }
    grid_style = merge_style(
        style,
        {
            "fill": "none",
            "cell_fill": "#FFFFFF",
            "line": node.get("grid_line", style.get("grid_line", "#777777")),
            "grid_line": node.get("grid_line", style.get("grid_line", "#777777")),
            "line_weight_pt": node.get("grid_line_weight_pt", style.get("grid_line_weight_pt", 0.55)),
            "grid_line_weight_pt": node.get("grid_line_weight_pt", style.get("grid_line_weight_pt", 0.55)),
        },
    )
    draw_grid_matrix(page, page_height, grid_node, grid_style)

    op_right = (op_x + op_size, op_y + op_size / 2)
    grid_left = (grid_x, grid_y + grid_h / 2)
    first_shape = draw_line_segment(page, page_height, op_right, grid_left, line_style)

    label = str(node.get("label", style.get("label", "")))
    if label:
        label_ratio = float(node.get("label_position", style.get("label_position", 0.45)))
        label_x, label_y = point_along_polyline([op_right, grid_left], label_ratio)
        label_x += float(node.get("label_offset_x_in", style.get("label_offset_x_in", 0.0)) or 0.0)
        label_y += float(node.get("label_offset_y_in", style.get("label_offset_y_in", -0.07)) or 0.0)
        draw_edge_label(page, page_height, label, label_x, label_y, {"global_text": merge_style(style, {"font_size_pt": node.get("label_font_size_pt", style.get("label_font_size_pt", 9.5))})})

    return first_shape


def draw_token_grid(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    rows = int(node["rows"])
    cols = int(node["cols"])
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    gap = float(node.get("cell_gap_in", style.get("cell_gap_in", 0.04)))
    if truthy(node.get("square_cells", style.get("square_cells")), False):
        max_cell = min(
            max(0.01, (width - gap * (cols - 1)) / cols),
            max(0.01, (height - gap * (rows - 1)) / rows),
        )
        used_w = max_cell * cols + gap * (cols - 1)
        used_h = max_cell * rows + gap * (rows - 1)
        align_x = str(node.get("grid_align_x", style.get("grid_align_x", "center"))).lower()
        align_y = str(node.get("grid_align_y", style.get("grid_align_y", "center"))).lower()
        if align_x in {"right", "end"}:
            x += max(0.0, width - used_w)
        elif align_x not in {"left", "start"}:
            x += max(0.0, (width - used_w) / 2)
        if align_y in {"bottom", "end"}:
            y += max(0.0, height - used_h)
        elif align_y not in {"top", "start"}:
            y += max(0.0, (height - used_h) / 2)
        width = used_w
        height = used_h
    cell_w = max(0.01, (width - gap * (cols - 1)) / cols)
    cell_h = max(0.01, (height - gap * (rows - 1)) / rows)
    default_fill = str(style.get("cell_fill", style.get("fill", "#FFFFFF")))
    default_line = str(style.get("cell_line", style.get("line", "#111111")))
    default_text = {
        "text_color": style.get("text_color", "#111111"),
        "font_family": style.get("font_family", "Times New Roman"),
        "font_family_candidates": style.get("font_family_candidates"),
        "font_role": style.get("font_role", "paper_serif"),
        "font_size_pt": node.get("cell_font_size_pt", style.get("cell_font_size_pt", style.get("font_size_pt", 12))),
        "font_weight": node.get("cell_font_weight", style.get("cell_font_weight", "bold")),
        "text_align": 1,
        "vertical_align": 1,
    }
    cells_by_pos: dict[tuple[int, int], dict[str, Any]] = {}
    index_base = int(node.get("index_base", 0))
    raw_cells = node.get("cells", node.get("tokens", []))
    if isinstance(raw_cells, list):
        auto_index = 0
        for item in raw_cells:
            if isinstance(item, dict):
                row = int(item.get("row", auto_index // cols + index_base)) - index_base
                col = int(item.get("col", auto_index % cols + index_base)) - index_base
                cells_by_pos[(row, col)] = item
            elif isinstance(item, list):
                if len(item) >= 4:
                    row = int(item[0]) - index_base
                    col = int(item[1]) - index_base
                    cells_by_pos[(row, col)] = {"text": str(item[2]), "fill": str(item[3])}
                elif len(item) >= 2:
                    row = auto_index // cols
                    col = auto_index % cols
                    cells_by_pos[(row, col)] = {"text": str(item[0]), "fill": str(item[1])}
            else:
                row = auto_index // cols
                col = auto_index % cols
                cells_by_pos[(row, col)] = {"text": str(item)}
            auto_index += 1

    shape = None
    for row in range(rows):
        for col in range(cols):
            cell = cells_by_pos.get((row, col), {})
            cell_node = {
                "x": x + col * (cell_w + gap),
                "y": y + row * (cell_h + gap),
                "w": cell_w,
                "h": cell_h,
            }
            shape = draw_rectangle(page, page_height, cell_node)
            text = str(cell.get("text", cell.get("label", ""))) if isinstance(cell, dict) else ""
            cell_style = merge_style(
                style,
                {
                    "fill": cell.get("fill", default_fill) if isinstance(cell, dict) else default_fill,
                    "line": cell.get("line", default_line) if isinstance(cell, dict) else default_line,
                    "line_weight_pt": cell.get("line_weight_pt", style.get("cell_line_weight_pt", style.get("line_weight_pt", 1.0))) if isinstance(cell, dict) else style.get("cell_line_weight_pt", style.get("line_weight_pt", 1.0)),
                    "rounding_in": node.get("cell_rounding_in", style.get("cell_rounding_in", 0.03)),
                    "text_fit": node.get("cell_text_fit", style.get("cell_text_fit", "single_line")),
                    "min_font_size_pt": node.get("cell_min_font_size_pt", style.get("cell_min_font_size_pt", 6)),
                    "text_margin_in": node.get("cell_text_margin_in", style.get("cell_text_margin_in", 0.0)),
                },
                default_text,
                cell.get("style") if isinstance(cell, dict) and isinstance(cell.get("style"), dict) else None,
            )
            apply_style(shape, cell_style, text, cell_w, cell_h)
            if text:
                try_set_text(shape, text)

    return shape


def feature_entries(node: dict[str, Any], count: int) -> list[dict[str, Any]]:
    raw_entries = node.get("entries", node.get("cells", node.get("tokens", [])))
    if not isinstance(raw_entries, list):
        raw_entries = []
    entries: list[dict[str, Any]] = []
    for item in raw_entries:
        if isinstance(item, dict):
            entries.append(item)
        else:
            entries.append({"text": str(item)})
    while len(entries) < count:
        entries.append({})
    return entries[:count]


def draw_feature_vector_stack(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", style.get("orientation", "vertical"))).lower()
    count = int(node.get("count", node.get("cells_count", node.get("length", 4))) or 4)
    count = max(1, count)
    gap = float(node.get("cell_gap_in", style.get("cell_gap_in", 0.015)))
    entries = feature_entries(node, count)
    fills = node.get("cell_fills", style.get("cell_fills"))
    if not isinstance(fills, list):
        fills = []
    default_fill = str(node.get("cell_fill", style.get("cell_fill", style.get("fill", "#FFFFFF"))))
    cell_line = str(node.get("cell_line", style.get("cell_line", style.get("line", "#111827"))))
    shape = None

    text_base_style = merge_style(
        style,
        {
            "text_align": 1,
            "vertical_align": 1,
            "text_fit": node.get("cell_text_fit", style.get("cell_text_fit", "single_line")),
            "min_font_size_pt": node.get("cell_min_font_size_pt", style.get("cell_min_font_size_pt", 4.5)),
            "text_margin_in": node.get("cell_text_margin_in", style.get("cell_text_margin_in", 0.0)),
            "font_size_pt": node.get("cell_font_size_pt", style.get("cell_font_size_pt", style.get("font_size_pt", 9))),
        },
    )
    if orientation in {"horizontal", "h", "row"}:
        cell_w = max(0.01, (width - gap * (count - 1)) / count)
        cell_h = height
        for index, entry in enumerate(entries):
            cell_node = {"x": x + index * (cell_w + gap), "y": y, "w": cell_w, "h": cell_h}
            shape = draw_rectangle(page, page_height, cell_node)
            text = str(entry.get("text", entry.get("label", ""))).strip()
            cell_style = merge_style(
                text_base_style,
                {
                    "fill": entry.get("fill", fills[index % len(fills)] if fills else default_fill),
                    "line": entry.get("line", cell_line),
                    "line_weight_pt": entry.get("line_weight_pt", style.get("cell_line_weight_pt", style.get("line_weight_pt", 0.75))),
                    "rounding_in": entry.get("rounding_in", node.get("cell_rounding_in", style.get("cell_rounding_in", 0.015))),
                },
                entry.get("style") if isinstance(entry.get("style"), dict) else None,
            )
            apply_style(shape, cell_style, text, cell_w, cell_h)
            if text:
                try_set_text(shape, text)
    else:
        cell_w = width
        cell_h = max(0.01, (height - gap * (count - 1)) / count)
        for index, entry in enumerate(entries):
            cell_node = {"x": x, "y": y + index * (cell_h + gap), "w": cell_w, "h": cell_h}
            shape = draw_rectangle(page, page_height, cell_node)
            text = str(entry.get("text", entry.get("label", ""))).strip()
            cell_style = merge_style(
                text_base_style,
                {
                    "fill": entry.get("fill", fills[index % len(fills)] if fills else default_fill),
                    "line": entry.get("line", cell_line),
                    "line_weight_pt": entry.get("line_weight_pt", style.get("cell_line_weight_pt", style.get("line_weight_pt", 0.75))),
                    "rounding_in": entry.get("rounding_in", node.get("cell_rounding_in", style.get("cell_rounding_in", 0.015))),
                },
                entry.get("style") if isinstance(entry.get("style"), dict) else None,
            )
            apply_style(shape, cell_style, text, cell_w, cell_h)
            if text:
                try_set_text(shape, text)

    if truthy(node.get("outline", style.get("outline")), False):
        outline = draw_rectangle(page, page_height, node)
        apply_style(
            outline,
            merge_style(
                style,
                {
                    "fill": "none",
                    "line": node.get("outline_line", style.get("outline_line", style.get("line", "#111827"))),
                    "line_weight_pt": node.get("outline_weight_pt", style.get("outline_weight_pt", style.get("line_weight_pt", 0.8))),
                },
            ),
        )
        shape = outline
    if truthy(node.get("brackets", style.get("brackets")), False):
        bracket_w = float(node.get("bracket_w_in", style.get("bracket_w_in", min(0.08, max(0.025, width * 0.12)))))
        bracket_style = merge_style(
            style,
            {
                "fill": "none",
                "line": node.get("bracket_line", style.get("bracket_line", style.get("line", "#111827"))),
                "line_weight_pt": node.get("bracket_line_weight_pt", style.get("bracket_line_weight_pt", style.get("line_weight_pt", 0.8))),
            },
        )
        shape = draw_bracket(page, page_height, {"x": x - bracket_w, "y": y, "w": bracket_w, "h": height, "orientation": "right"}, bracket_style)
        shape = draw_bracket(page, page_height, {"x": x + width, "y": y, "w": bracket_w, "h": height, "orientation": "left"}, bracket_style)
    label_text = str(node.get("label", node.get("label_text", ""))).strip()
    if label_text:
        label_side = str(node.get("label_side", node.get("label_anchor", style.get("label_side", "right")))).lower()
        label_gap = float(node.get("label_gap_in", style.get("label_gap_in", 0.04)))
        label_font_size = float(node.get("label_font_size_pt", style.get("label_font_size_pt", style.get("font_size_pt", 10))) or 10)
        label_w = float(
            node.get(
                "label_w_in",
                style.get("label_w_in", max(0.24, approximate_text_width(label_text, label_font_size) + 0.08)),
            )
        )
        label_h = float(node.get("label_h_in", style.get("label_h_in", max(0.16, label_font_size / 72.0 * 1.30))))
        label_ratio = float(node.get("label_position", node.get("label_ratio", 0.5)) or 0.5)
        label_style = merge_style(
            style,
            {
                "fill": "none",
                "line": "none",
                "font_size_pt": label_font_size,
                "text_fit": node.get("label_text_fit", style.get("label_text_fit", "single_line")),
                "min_font_size_pt": node.get("label_min_font_size_pt", style.get("label_min_font_size_pt", 5.0)),
                "text_margin_in": 0.0,
                "vertical_align": 1,
            },
            node.get("label_style") if isinstance(node.get("label_style"), dict) else None,
        )
        if label_side in {"left", "start"}:
            label_x = x - label_gap - label_w
            label_y = y + height * label_ratio - label_h / 2
            label_style["text_align"] = 2
        elif label_side in {"top", "up"}:
            label_x = x + width / 2 - label_w / 2
            label_y = y - label_gap - label_h
            label_style["text_align"] = 1
        elif label_side in {"bottom", "down"}:
            label_x = x + width / 2 - label_w / 2
            label_y = y + height + label_gap
            label_style["text_align"] = 1
        else:
            label_x = x + width + label_gap
            label_y = y + height * label_ratio - label_h / 2
            label_style["text_align"] = 0

        if truthy(node.get("label_math", style.get("label_math")), False) or "_" in label_text or str(node.get("label_text_role", "")).lower() in {"formula", "math"}:
            draw_math_text(
                page,
                page_height,
                {
                    "x": label_x,
                    "y": label_y,
                    "w": label_w,
                    "h": label_h,
                    "text": label_text,
                    "font_size_pt": label_font_size,
                    "text_fit": label_style.get("text_fit", "math_label"),
                    "min_font_size_pt": label_style.get("min_font_size_pt", 5.0),
                },
                merge_style(label_style, {"font_role": "math", "font_italic": node.get("label_font_italic", style.get("label_font_italic", True))}),
            )
        else:
            draw_text_box(page, page_height, label_x, label_y, label_w, label_h, label_text, label_style)
    return shape


def probability_items(node: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = node.get("items", node.get("rows", []))
    if not isinstance(raw_items, list):
        raw_items = []
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            items.append(item)
        elif isinstance(item, list):
            parsed: dict[str, Any] = {}
            if len(item) >= 1:
                parsed["label"] = str(item[0])
            if len(item) >= 2:
                parsed["value"] = item[1]
            if len(item) >= 3:
                parsed["fill"] = str(item[2])
            items.append(parsed)
        else:
            items.append({"label": str(item)})
    return items


def draw_probability_bar_list(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    shape = draw_rectangle(page, page_height, node)
    panel_style = dict(style)
    if isinstance(node.get("panel_style"), dict):
        panel_style.update(node["panel_style"])
    for field_name, source_key in (
        ("fill", "panel_fill"),
        ("line", "panel_line"),
        ("line_weight_pt", "panel_line_weight_pt"),
        ("fill_transparency_pct", "panel_fill_transparency_pct"),
        ("rounding_in", "panel_rounding_in"),
        ("shadow", "panel_shadow"),
    ):
        if source_key in node:
            panel_style[field_name] = node[source_key]
    apply_style(shape, panel_style)

    items = probability_items(node)
    if not items:
        text = str(node.get("text", "")).strip()
        for line in text.splitlines():
            if line.strip():
                items.append({"label": line.strip()})
    if not items:
        return shape

    padding = float(node.get("padding_in", style.get("padding_in", 0.08)))
    padding_x = float(node.get("panel_inner_padding_x_in", style.get("panel_inner_padding_x_in", padding)) or padding)
    padding_y = float(node.get("panel_inner_padding_y_in", style.get("panel_inner_padding_y_in", padding)) or padding)
    padding_left = float(
        node.get(
            "panel_inner_padding_left_in",
            node.get("padding_left_in", style.get("panel_inner_padding_left_in", style.get("padding_left_in", padding_x))),
        )
        or padding_x
    )
    padding_right = float(
        node.get(
            "panel_inner_padding_right_in",
            node.get("padding_right_in", style.get("panel_inner_padding_right_in", style.get("padding_right_in", padding_x))),
        )
        or padding_x
    )
    padding_top = float(
        node.get(
            "panel_inner_padding_top_in",
            node.get("padding_top_in", style.get("panel_inner_padding_top_in", style.get("padding_top_in", padding_y))),
        )
        or padding_y
    )
    padding_bottom = float(
        node.get(
            "panel_inner_padding_bottom_in",
            node.get("padding_bottom_in", style.get("panel_inner_padding_bottom_in", style.get("padding_bottom_in", padding_y))),
        )
        or padding_y
    )
    row_gap = float(node.get("row_gap_in", style.get("row_gap_in", 0.06)))
    inner_x = x + padding_left
    inner_y = y + padding_top
    inner_w = max(0.05, width - padding_left - padding_right)
    inner_h = max(0.05, height - padding_top - padding_bottom)
    row_h = float(node.get("row_height_in", style.get("row_height_in", (inner_h - row_gap * (len(items) - 1)) / len(items))))
    row_h = min(row_h, max(0.02, (inner_h - row_gap * (len(items) - 1)) / len(items)))
    total_h = row_h * len(items) + row_gap * (len(items) - 1)
    cursor_y = inner_y + max(0.0, (inner_h - total_h) / 2)

    label_w = float(node.get("label_w_in", style.get("label_w_in", inner_w * 0.30)))
    pre_value_w = float(node.get("pre_value_w_in", style.get("pre_value_w_in", 0.0)))
    value_w = float(node.get("value_w_in", style.get("value_w_in", inner_w * 0.24)))
    axis_w = float(node.get("axis_w_in", style.get("axis_w_in", 0.0)))
    bar_gap = float(node.get("bar_gap_in", style.get("bar_gap_in", 0.04)))
    axis_offset_x = float(node.get("axis_offset_x_in", style.get("axis_offset_x_in", 0.0)) or 0.0)
    bar_start_offset_x = float(node.get("bar_start_offset_x_in", style.get("bar_start_offset_x_in", 0.0)) or 0.0)
    bar_end_padding_in = float(node.get("bar_end_padding_in", style.get("bar_end_padding_in", 0.0)) or 0.0)
    active_gaps = 1
    if nonzero_extent(pre_value_w):
        active_gaps += 1
    if nonzero_extent(axis_w):
        active_gaps += 1
    if nonzero_extent(value_w):
        active_gaps += 1
    computed_bar_w = inner_w - pre_value_w - label_w - value_w - axis_w - bar_gap * active_gaps - axis_offset_x - bar_start_offset_x - bar_end_padding_in
    bar_w = float(node.get("bar_w_in", style.get("bar_w_in", computed_bar_w)) or computed_bar_w)
    bar_w = max(0.05, bar_w)
    max_value = node.get("max_value", style.get("max_value"))
    numeric_values: list[float] = []
    for item in items:
        value = item.get("value", item.get("probability", item.get("score")))
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            pass
    if max_value is None:
        max_value = max(numeric_values) if numeric_values else 1.0
    try:
        max_value_f = max(0.0001, float(max_value))
    except (TypeError, ValueError):
        max_value_f = 1.0
    bar_max_fraction = float(node.get("bar_max_fraction", style.get("bar_max_fraction", 1.0)) or 1.0)
    bar_max_fraction = max(0.02, min(1.0, bar_max_fraction))
    label_align = int(node.get("label_align", style.get("label_align", 2)))
    pre_value_align = int(node.get("pre_value_align", style.get("pre_value_align", 2)))
    value_align = int(node.get("value_align", style.get("value_align", 0)))
    bar_value_align = int(node.get("bar_value_align", style.get("bar_value_align", 1)))
    row_vertical_align = int(node.get("row_vertical_align", style.get("row_vertical_align", 1)))

    text_style = merge_style(
        style,
        {
            "fill": "none",
            "line": "none",
            "shadow": None,
            "font_size_pt": node.get("label_font_size_pt", style.get("label_font_size_pt", style.get("font_size_pt", 11))),
            "text_fit": "single_line",
            "min_font_size_pt": node.get("label_min_font_size_pt", style.get("label_min_font_size_pt", 5.5)),
            "text_margin_in": 0.0,
            "vertical_align": row_vertical_align,
        },
    )
    bar_value_style = merge_style(
        text_style,
        {
            "font_size_pt": node.get("bar_value_font_size_pt", style.get("bar_value_font_size_pt", text_style.get("font_size_pt", 11))),
            "min_font_size_pt": node.get("bar_value_min_font_size_pt", style.get("bar_value_min_font_size_pt", text_style.get("min_font_size_pt", 5.5))),
        },
    )
    bar_style_base = {
        "fill": style.get("bar_fill", "#4E9AD1"),
        "line": style.get("bar_line", style.get("bar_fill", "#4E9AD1")),
        "line_weight_pt": style.get("bar_line_weight_pt", 0.0),
        "rounding_in": style.get("bar_rounding_in", 0.03),
    }
    label_bg_style = merge_style(
        bar_value_style,
        {
            "fill": node.get("bar_value_background_fill", style.get("bar_value_background_fill", "none")),
            "line": node.get("bar_value_background_line", style.get("bar_value_background_line", "none")),
            "fill_transparency_pct": node.get(
                "bar_value_background_transparency_pct",
                style.get("bar_value_background_transparency_pct"),
            ),
        },
    )
    axis_style = merge_style(
        {
            "line": style.get("axis_line", "#111111"),
            "line_weight_pt": style.get("axis_line_weight_pt", 1.0),
            "end_arrow": "none",
        },
        node.get("axis_style") if isinstance(node.get("axis_style"), dict) else None,
    )
    if nonzero_extent(axis_w):
        axis_x = inner_x + pre_value_w + label_w + bar_gap + axis_offset_x
        draw_line_segment(page, page_height, (axis_x, cursor_y), (axis_x, cursor_y + total_h), axis_style)

    for index, item in enumerate(items):
        label = str(item.get("label", item.get("text", item.get("name", ""))))
        value = item.get("value", item.get("probability", item.get("score", "")))
        pre_value_label = str(item.get("pre_value_label", item.get("left_value_label", "")))
        if not pre_value_label and pre_value_w > 0 and value != "":
            pre_value_label = str(value)
        value_label = str(item.get("value_label", item.get("right_value_label", value if value != "" else "")))
        try:
            ratio = max(0.0, min(1.0, float(value) / max_value_f))
        except (TypeError, ValueError):
            ratio = 1.0
        ratio *= bar_max_fraction

        row_y = cursor_y + index * (row_h + row_gap) + float(
            item.get("row_offset_y_in", node.get("row_offset_y_in", style.get("row_offset_y_in", 0.0))) or 0.0
        )
        cursor_x = inner_x
        if nonzero_extent(pre_value_w):
            draw_text_box(
                page,
                page_height,
                cursor_x + float(item.get("pre_value_offset_x_in", node.get("pre_value_offset_x_in", style.get("pre_value_offset_x_in", 0.0))) or 0.0),
                row_y + float(item.get("pre_value_offset_y_in", node.get("pre_value_offset_y_in", style.get("pre_value_offset_y_in", 0.0))) or 0.0),
                max(0.02, pre_value_w),
                row_h,
                pre_value_label,
                merge_style(
                    text_style,
                    {
                        "text_align": int(item.get("pre_value_align", pre_value_align)),
                        "baseline_offset_in": item.get(
                            "pre_value_baseline_offset_in",
                            node.get("pre_value_baseline_offset_in", style.get("pre_value_baseline_offset_in", 0.0)),
                        ),
                    },
                ),
            )
            cursor_x += pre_value_w + bar_gap
        draw_text_box(
            page,
            page_height,
            cursor_x + float(item.get("label_offset_x_in", node.get("label_offset_x_in", style.get("label_offset_x_in", 0.0))) or 0.0),
            row_y + float(item.get("label_offset_y_in", node.get("label_offset_y_in", style.get("label_offset_y_in", 0.0))) or 0.0),
            max(0.02, label_w),
            row_h,
            label,
            merge_style(
                text_style,
                {
                    "text_align": int(item.get("label_align", label_align)),
                    "baseline_offset_in": item.get(
                        "label_baseline_offset_in",
                        node.get("label_baseline_offset_in", style.get("label_baseline_offset_in", 0.0)),
                    ),
                },
            ),
        )
        cursor_x += label_w + bar_gap
        if nonzero_extent(axis_w):
            cursor_x += axis_w + axis_offset_x
        bar_x = cursor_x + bar_start_offset_x
        bar_h = float(item.get("bar_h", item.get("bar_height_in", node.get("bar_height_in", style.get("bar_height_in", row_h * 0.58)))))
        bar_y = row_y + max(0.0, (row_h - bar_h) / 2) + float(
            item.get("bar_offset_y_in", node.get("bar_offset_y_in", style.get("bar_offset_y_in", 0.0))) or 0.0
        )
        visible_bar_w = max(0.01, bar_w * ratio)
        bar_shape = draw_rectangle(page, page_height, {"x": bar_x, "y": bar_y, "w": visible_bar_w, "h": bar_h})
        apply_style(
            bar_shape,
            merge_style(
                bar_style_base,
                {"fill": item.get("fill", bar_style_base["fill"]), "line": item.get("line", item.get("fill", bar_style_base["line"]))},
                item.get("style") if isinstance(item.get("style"), dict) else None,
            ),
        )
        inline_value_label = str(item.get("bar_value_label", item.get("inside_value_label", "")))
        if inline_value_label:
            value_anchor = str(
                item.get("bar_value_anchor", node.get("bar_value_anchor", style.get("bar_value_anchor", "bar")))
            ).lower()
            label_gap = float(
                item.get(
                    "bar_value_text_gap_in",
                    item.get("bar_value_gap_in", node.get("bar_value_text_gap_in", style.get("bar_value_text_gap_in", 0.02))),
                )
                or 0.0
            )
            if value_anchor in {"row", "panel", "inner"}:
                default_inline_x = inner_x
                default_inline_w = inner_w
            elif value_anchor in {"after_bar", "bar_end", "bar_right"}:
                default_inline_x = bar_x + visible_bar_w + label_gap
                default_inline_w = max(0.05, bar_x + bar_w - default_inline_x)
            elif value_anchor in {"before_bar", "bar_left"}:
                default_inline_x = bar_x
                default_inline_w = max(0.05, bar_w)
            elif value_anchor in {"after_axis", "bar_area", "plot"}:
                default_inline_x = bar_x
                default_inline_w = max(0.05, bar_w)
            else:
                default_inline_x = bar_x
                default_inline_w = max(0.05, visible_bar_w)
            inline_w = float(item.get("bar_value_w_in", node.get("bar_value_w_in", style.get("bar_value_w_in", default_inline_w))))
            inline_x = float(
                item.get(
                    "bar_value_x_in",
                    default_inline_x
                    + float(item.get("bar_value_offset_x_in", node.get("bar_value_offset_x_in", style.get("bar_value_offset_x_in", 0.0)))),
                )
            )
            inline_align = int(item.get("bar_value_align", bar_value_align))
            draw_text_box(
                page,
                page_height,
                inline_x,
                row_y + float(item.get("bar_value_offset_y_in", node.get("bar_value_offset_y_in", style.get("bar_value_offset_y_in", 0.0))) or 0.0),
                max(0.02, inline_w),
                row_h,
                inline_value_label,
                merge_style(
                    label_bg_style,
                    {
                        "text_align": inline_align,
                        "baseline_offset_in": item.get(
                            "bar_value_baseline_offset_in",
                            node.get("bar_value_baseline_offset_in", style.get("bar_value_baseline_offset_in", 0.0)),
                        ),
                    },
                ),
            )
        if nonzero_extent(value_w) and value_label.strip():
            draw_text_box(
                page,
                page_height,
                bar_x + bar_w + bar_gap + float(item.get("value_offset_x_in", node.get("value_offset_x_in", style.get("value_offset_x_in", 0.0))) or 0.0),
                row_y + float(item.get("value_offset_y_in", node.get("value_offset_y_in", style.get("value_offset_y_in", 0.0))) or 0.0),
                value_w,
                row_h,
                value_label,
                merge_style(
                    text_style,
                    {
                        "text_align": int(item.get("value_align", value_align)),
                        "baseline_offset_in": item.get(
                            "value_baseline_offset_in",
                            node.get("value_baseline_offset_in", style.get("value_baseline_offset_in", 0.0)),
                        ),
                    },
                ),
            )

    return shape


def draw_stacked_process(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    layers = max(1, int(node.get("layers", style.get("layers", 4))))
    dx = float(node.get("stack_dx_in", style.get("stack_dx_in", -0.04)))
    dy = float(node.get("stack_dy_in", style.get("stack_dy_in", 0.035)))
    shape = None

    for index in reversed(range(layers)):
        layer_node = dict(node)
        layer_node["x"] = float(node["x"]) + dx * index
        layer_node["y"] = float(node["y"]) + dy * index
        shape = draw_rectangle(page, page_height, layer_node)
        apply_style(shape, style, node.get("text", node.get("symbol", "")))

    return shape


def relative_or_absolute(value: Any, total: float) -> float:
    numeric = float(value)
    if -1.0 <= numeric <= 1.0:
        return numeric * total
    return numeric


def draw_notched_block(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    base = draw_rectangle(page, page_height, node)
    apply_style(base, style)

    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    notches = node.get("notches") or [
        {"x": 0.50, "y": 0.28, "w": 0.38, "h": 0.16, "shape": "diamond"},
        {"x": 0.50, "y": 0.72, "w": 0.38, "h": 0.16, "shape": "diamond"},
    ]
    notch_fill = str(node.get("notch_fill", style.get("notch_fill", "#FFFFFF")))

    for index, notch in enumerate(notches):
        nw = relative_or_absolute(notch.get("w", 0.25), width)
        nh = relative_or_absolute(notch.get("h", 0.15), height)
        nx = x + relative_or_absolute(notch.get("x", 0.5), width) - nw / 2
        ny = y + relative_or_absolute(notch.get("y", 0.5), height) - nh / 2
        notch_node = {"x": nx, "y": ny, "w": nw, "h": nh}
        if str(notch.get("shape", "diamond")).lower() == "rectangle":
            shape = draw_rectangle(page, page_height, notch_node)
        else:
            shape = draw_rotated_diamond(page, page_height, notch_node)
        apply_style(
            shape,
            {
                "fill": str(notch.get("fill", notch_fill)),
                "line": str(notch.get("line", notch.get("fill", notch_fill))),
                "line_weight_pt": float(notch.get("line_weight_pt", 0)),
            },
        )

    return base


def draw_feature_map_banded(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", "horizontal")).lower()
    bands = node.get("bands") or node.get("stripe_colors") or [
        "#B7DCEB",
        "#F8E49B",
        "#B7DCEB",
        "#C9C0D8",
        "#D7D7D7",
    ]

    parsed_bands: list[dict[str, Any]] = []
    for band in bands:
        if isinstance(band, dict):
            parsed_bands.append(band)
        else:
            parsed_bands.append({"fill": str(band), "size": 1})
    total_size = sum(float(band.get("size", 1)) for band in parsed_bands) or 1.0
    cursor = 0.0
    first_shape = None
    for band in parsed_bands:
        ratio = float(band.get("size", 1)) / total_size
        if orientation == "vertical":
            band_node = {"x": x + cursor * width, "y": y, "w": width * ratio, "h": height}
        else:
            band_node = {"x": x, "y": y + cursor * height, "w": width, "h": height * ratio}
        shape = draw_rectangle(page, page_height, band_node)
        apply_style(shape, {"fill": str(band.get("fill", "#FFFFFF")), "line": "none"})
        first_shape = first_shape or shape
        cursor += ratio

    for overlay in node.get("overlays", node.get("vertical_bands", [])):
        ox = x + relative_or_absolute(overlay.get("x", 0), width)
        oy = y + relative_or_absolute(overlay.get("y", 0), height)
        ow = relative_or_absolute(overlay.get("w", width), width)
        oh = relative_or_absolute(overlay.get("h", height), height)
        shape = draw_rectangle(page, page_height, {"x": ox, "y": oy, "w": ow, "h": oh})
        apply_style(
            shape,
            {
                "fill": str(overlay.get("fill", "#000000")),
                "line": str(overlay.get("line", overlay.get("fill", "#000000"))),
                "line_weight_pt": float(overlay.get("line_weight_pt", 0)),
            },
        )
        first_shape = first_shape or shape

    separator_count = int(node.get("separator_count", node.get("vertical_separator_count", 0)) or 0)
    separator_positions = node.get("separator_positions", node.get("vertical_separator_positions"))
    if isinstance(separator_positions, list) and separator_positions:
        positions = [float(item) for item in separator_positions if isinstance(item, (int, float))]
    elif separator_count > 0:
        positions = [(index + 1) / (separator_count + 1) for index in range(separator_count)]
    else:
        positions = []
    separator_style = merge_style(
        {
            "line": node.get("separator_line", style.get("separator_line", style.get("grid_line", "#111111"))),
            "line_weight_pt": node.get("separator_line_weight_pt", style.get("separator_line_weight_pt", style.get("grid_line_weight_pt", 1.0))),
            "end_arrow": "none",
        },
        node.get("separator_style") if isinstance(node.get("separator_style"), dict) else None,
    )
    for pos in positions:
        sep_x = x + relative_or_absolute(pos, width)
        first_shape = draw_line_segment(page, page_height, (sep_x, y), (sep_x, y + height), separator_style)

    outline = draw_rectangle(page, page_height, node)
    apply_style(outline, merge_style(style, {"fill": "none"}))
    return outline or first_shape


def sequence_from_bands(raw_values: Any, default_values: list[str]) -> list[str]:
    if not isinstance(raw_values, list) or not raw_values:
        return default_values
    values: list[str] = []
    for item in raw_values:
        if isinstance(item, dict):
            values.append(str(item.get("fill", item.get("color", "#FFFFFF"))))
        else:
            values.append(str(item))
    return values or default_values


def numeric_sequence(raw_values: Any, count: int, default_value: float = 0.0) -> list[float]:
    if isinstance(raw_values, list) and raw_values:
        parsed = [float(item) for item in raw_values if isinstance(item, (int, float))]
        if parsed:
            if len(parsed) >= count:
                return parsed[:count]
            return [parsed[index % len(parsed)] for index in range(count)]
    return [default_value for _ in range(count)]


def normalized_weights(raw_values: Any, count: int) -> list[float]:
    if isinstance(raw_values, list) and raw_values:
        parsed = [float(item) for item in raw_values if isinstance(item, (int, float)) and float(item) > 0]
        if parsed:
            if len(parsed) < count:
                parsed.extend([parsed[-1]] * (count - len(parsed)))
            weights = parsed[:count]
            total = sum(weights) or 1.0
            return [value / total for value in weights]
    return [1.0 / count for _ in range(count)]


def draw_feature_map_grid(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    row_palette = sequence_from_bands(
        node.get("row_colors", node.get("bands", style.get("row_colors"))),
        ["#F2A66F", "#A8D7E5", "#C8D9C2", "#F3E889", "#9BC6D9", "#F2A66F"],
    )
    rows = int(node.get("rows", len(row_palette)))
    cols = int(node.get("cols", node.get("columns", 8)))
    if rows <= 0 or cols <= 0:
        raise ValueError(f"feature_map_grid `{node.get('id', '<unknown>')}` needs positive rows/cols.")

    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    row_weights = normalized_weights(node.get("row_weights", node.get("row_heights")), rows)
    col_weights = normalized_weights(node.get("column_weights", node.get("column_widths")), cols)
    column_shades = numeric_sequence(node.get("column_shades", style.get("column_shades")), cols, 0.0)
    shade_color = str(node.get("shade_color", style.get("shade_color", "#111111")))
    max_shade = float(node.get("max_shade", style.get("max_shade", 0.58)))

    first_shape = None
    row_tops: list[float] = [y]
    cursor_y = y
    for row_weight in row_weights:
        cursor_y += height * row_weight
        row_tops.append(cursor_y)
    col_lefts: list[float] = [x]
    cursor_x = x
    for col_weight in col_weights:
        cursor_x += width * col_weight
        col_lefts.append(cursor_x)

    for row in range(rows):
        base_fill = row_palette[row % len(row_palette)]
        for col in range(cols):
            shade_amount = max(0.0, min(1.0, column_shades[col])) * max_shade
            fill = blend_hex_colors(base_fill, shade_color, shade_amount) if shade_amount else base_fill
            cell_node = {
                "x": col_lefts[col],
                "y": row_tops[row],
                "w": col_lefts[col + 1] - col_lefts[col],
                "h": row_tops[row + 1] - row_tops[row],
            }
            cell_shape = draw_rectangle(page, page_height, cell_node)
            apply_style(
                cell_shape,
                {
                    "fill": fill,
                    "line": "none",
                    "fill_transparency_pct": style.get("fill_transparency_pct", 0),
                },
            )
            first_shape = first_shape or cell_shape

    separator_style = {
        "line": node.get("grid_line", style.get("grid_line", "#333333")),
        "line_weight_pt": node.get("grid_line_weight_pt", style.get("grid_line_weight_pt", 0.35)),
        "line_transparency_pct": node.get("grid_line_transparency_pct", style.get("grid_line_transparency_pct", 35)),
        "end_arrow": "none",
    }
    if node.get("show_column_lines", True):
        for col in range(1, cols):
            first_shape = draw_line_segment(page, page_height, (col_lefts[col], y), (col_lefts[col], y + height), separator_style)
    if node.get("show_row_lines", False):
        for row in range(1, rows):
            first_shape = draw_line_segment(page, page_height, (x, row_tops[row]), (x + width, row_tops[row]), separator_style)

    outline = draw_rectangle(page, page_height, node)
    apply_style(
        outline,
        {
            "fill": "none",
            "line": node.get("outline", style.get("outline", style.get("line", "#111111"))),
            "line_weight_pt": node.get("outline_weight_pt", style.get("outline_weight_pt", 0.9)),
            "line_dash": style.get("line_dash", "solid"),
        },
    )
    return outline or first_shape


def draw_merge_bus(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", style.get("orientation", "vertical"))).lower()
    side = str(node.get("side", style.get("side", "left"))).lower()
    port_length = float(node.get("port_length_in", style.get("port_length_in", 0.18)))
    line_style = merge_style(style, {"fill": "none", "end_arrow": "none"})
    branch_end_arrow = str(node.get("branch_end_arrow", style.get("branch_end_arrow", "none")))
    branch_arrow_size = node.get("branch_arrow_size", style.get("branch_arrow_size", style.get("arrow_size", "small")))
    label_gap = float(node.get("label_gap_in", style.get("label_gap_in", 0.04)))
    label_w = float(node.get("label_width_in", style.get("label_width_in", 0.36)))
    label_h = float(node.get("label_height_in", style.get("label_height_in", 0.18)))
    label_style = merge_style(
        style,
        {
            "fill": "none",
            "line": "none",
            "font_size_pt": node.get("label_font_size_pt", style.get("label_font_size_pt", style.get("font_size_pt", 11))),
            "text_fit": "single_line",
            "min_font_size_pt": node.get("label_min_font_size_pt", style.get("label_min_font_size_pt", 5.0)),
            "text_margin_in": 0.0,
            "vertical_align": 1,
        },
    )
    raw_ports = node.get("ports", node.get("port_positions", [0, 0.5, 1]))
    ports: list[dict[str, Any]] = []
    if isinstance(raw_ports, list):
        for item in raw_ports:
            if isinstance(item, dict):
                ports.append(item)
            elif isinstance(item, (int, float)):
                ports.append({"position": float(item)})
    if not ports:
        ports = [{"position": 0.0}, {"position": 0.5}, {"position": 1.0}]

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    branch_specs: list[tuple[tuple[float, float], tuple[float, float], dict[str, Any]]] = []
    if orientation == "horizontal":
        spine_y = y + height / 2
        segments.append(((x, spine_y), (x + width, spine_y)))
        for port in ports:
            try:
                pos = float(port.get("position", port.get("offset", 0.5)))
            except (TypeError, ValueError):
                continue
            px = x + width * max(0.0, min(1.0, pos))
            port_side = str(port.get("side", side)).lower()
            current_port_length = float(port.get("port_length_in", port.get("length_in", port_length)))
            if port_side in {"top", "both"}:
                branch_specs.append(((px, spine_y), (px, spine_y - current_port_length), port))
            if port_side in {"bottom", "both"}:
                branch_specs.append(((px, spine_y), (px, spine_y + current_port_length), port))
    else:
        spine_x = x + width / 2
        segments.append(((spine_x, y), (spine_x, y + height)))
        for port in ports:
            try:
                pos = float(port.get("position", port.get("offset", 0.5)))
            except (TypeError, ValueError):
                continue
            py = y + height * max(0.0, min(1.0, pos))
            port_side = str(port.get("side", side)).lower()
            current_port_length = float(port.get("port_length_in", port.get("length_in", port_length)))
            if port_side in {"left", "both"}:
                branch_specs.append(((spine_x, py), (spine_x - current_port_length, py), port))
            if port_side in {"right", "both"}:
                branch_specs.append(((spine_x, py), (spine_x + current_port_length, py), port))

    shape = None
    for start, end in segments:
        shape = draw_line_segment(page, page_height, start, end, line_style)
    for start, end, port in branch_specs:
        shape = draw_line_segment(
            page,
            page_height,
            start,
            end,
            merge_style(
                line_style,
                {
                    "end_arrow": port.get("end_arrow", branch_end_arrow),
                    "arrow_size": port.get("arrow_size", branch_arrow_size),
                },
            ),
        )
        port_label = str(port.get("label", port.get("text", ""))).strip()
        if not port_label:
            continue
        if orientation == "horizontal":
            text_x = end[0] - label_w / 2
            text_y = end[1] - label_h - label_gap if end[1] < start[1] else end[1] + label_gap
            text_align = 1
        else:
            text_x = end[0] - label_w - label_gap if end[0] < start[0] else end[0] + label_gap
            text_y = end[1] - label_h / 2
            text_align = 2 if end[0] < start[0] else 0
        draw_text_box(
            page,
            page_height,
            text_x,
            text_y,
            label_w,
            label_h,
            port_label,
            merge_style(label_style, {"text_align": port.get("label_align", text_align)}),
        )
    return shape


def brace_points(
    x: float,
    y: float,
    width: float,
    height: float,
    orientation: str,
    waist_ratio: float = 0.50,
    curl_ratio: float = 0.22,
    neck_ratio: float = 0.14,
    shape_mode: str = "smooth",
    waist_width: float | None = None,
    curve_tightness: float | None = None,
) -> list[tuple[float, float]]:
    waist_ratio = max(0.05, min(0.95, waist_ratio))
    curl_ratio = max(0.02, min(0.48, curl_ratio))
    neck_ratio = max(0.02, min(0.48, neck_ratio))
    shape_mode = str(shape_mode or "smooth").lower()
    if curve_tightness is not None:
        tightness = max(0.0, min(1.0, float(curve_tightness)))
        curl_ratio = max(0.02, min(0.48, curl_ratio * (1.0 - tightness * 0.28)))
        neck_ratio = max(0.02, min(0.48, neck_ratio * (1.0 - tightness * 0.20)))
    if orientation in {"right", "left"}:
        spine_x = x + width if orientation == "right" else x
        open_x = x if orientation == "right" else x + width
        mid_y = y + height * waist_ratio
        if shape_mode in {"tight", "tight_curly", "paper", "pinched", "source_like"}:
            waist_width = width * 0.30 if waist_width is None else max(0.0, min(width, waist_width))
            waist_x = spine_x - waist_width if orientation == "right" else spine_x + waist_width
            return [
                (spine_x, y),
                (open_x, y + height * neck_ratio),
                (open_x, y + height * max(neck_ratio, waist_ratio - curl_ratio)),
                (waist_x, mid_y),
                (open_x, y + height * min(1.0 - neck_ratio, waist_ratio + curl_ratio)),
                (open_x, y + height * (1.0 - neck_ratio)),
                (spine_x, y + height),
            ]
        return [
            (spine_x, y),
            (open_x, y + height * neck_ratio),
            (open_x, y + height * max(neck_ratio, waist_ratio - curl_ratio)),
            (spine_x, mid_y),
            (open_x, y + height * min(1.0 - neck_ratio, waist_ratio + curl_ratio)),
            (open_x, y + height * (1.0 - neck_ratio)),
            (spine_x, y + height),
        ]
    if orientation in {"up", "down"}:
        spine_y = y if orientation == "up" else y + height
        open_y = y + height if orientation == "up" else y
        mid_x = x + width * waist_ratio
        if shape_mode in {"tight", "tight_curly", "paper", "pinched", "source_like"}:
            waist_width = height * 0.30 if waist_width is None else max(0.0, min(height, waist_width))
            waist_y = spine_y + waist_width if orientation == "up" else spine_y - waist_width
            return [
                (x, spine_y),
                (x + width * neck_ratio, open_y),
                (x + width * max(neck_ratio, waist_ratio - curl_ratio), open_y),
                (mid_x, waist_y),
                (x + width * min(1.0 - neck_ratio, waist_ratio + curl_ratio), open_y),
                (x + width * (1.0 - neck_ratio), open_y),
                (x + width, spine_y),
            ]
        return [
            (x, spine_y),
            (x + width * neck_ratio, open_y),
            (x + width * max(neck_ratio, waist_ratio - curl_ratio), open_y),
            (mid_x, spine_y),
            (x + width * min(1.0 - neck_ratio, waist_ratio + curl_ratio), open_y),
            (x + width * (1.0 - neck_ratio), open_y),
            (x + width, spine_y),
        ]
    raise ValueError(f"Unsupported bracket orientation: {orientation}")


def paper_curly_brace_points(
    x: float,
    y: float,
    width: float,
    height: float,
    orientation: str,
    terminal_indent_ratio: float = 0.08,
    outer_bulge_ratio: float = 0.46,
    waist_indent_ratio: float = 0.08,
    neck_ratio: float = 0.04,
    lobe_ratio: float = 0.08,
) -> list[tuple[float, float]]:
    """Return a TeX-like stretch brace, not a generic curly aggregation brace.

    The canonical shape is a right brace (`}`): endpoints and waist sit near the
    grouped object, while the long stems stay nearly vertical on the outer side.
    This matches paper dimension/range braces beside matrices and stacks.
    """
    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    g = clamp(terminal_indent_ratio, 0.00, 0.40)
    c = clamp(waist_indent_ratio, 0.00, 0.40)
    o = clamp(max(float(outer_bulge_ratio), max(g, c) + 0.08), 0.16, 1.00)
    n = clamp(neck_ratio, 0.02, 0.18)
    lobe = clamp(lobe_ratio, 0.04, 0.24)
    orientation = str(orientation or "right").lower()

    canonical = [
        (g, 0.00),
        (g, 0.00),
        (o, 0.00),
        (o, n),
        (o, min(0.50 - lobe, n + 0.04)),
        (o, 0.50 - lobe),
        (o, 0.50 - lobe),
        (o, 0.50 - lobe * 0.55),
        (c, 0.50 - lobe * 0.18),
        (c, 0.50),
        (c, 0.50 + lobe * 0.18),
        (o, 0.50 + lobe * 0.35),
        (o, 0.50 + lobe),
        (o, 0.50 + lobe),
        (o, max(0.50 + lobe, 1.00 - n - 0.04)),
        (o, 1.00 - n),
        (o, 1.00),
        (g, 1.00),
        (g, 1.00),
    ]

    def transform(point: tuple[float, float]) -> tuple[float, float]:
        u, v = point
        if orientation == "right":
            return x + u * width, y + v * height
        if orientation == "left":
            return x + (1.0 - u) * width, y + v * height
        if orientation == "down":
            return x + v * width, y + u * height
        if orientation == "up":
            return x + v * width, y + (1.0 - u) * height
        raise ValueError(f"Unsupported bracket orientation: {orientation}")

    return [transform(point) for point in canonical]


def draw_brace_merge(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", style.get("orientation", "right"))).lower()
    line_style = merge_style(style, {"fill": "none", "end_arrow": "none"})
    points = brace_points(
        x,
        y,
        width,
        height,
        orientation,
        float(node.get("waist_ratio", style.get("waist_ratio", 0.5))),
        float(node.get("curl_ratio", style.get("curl_ratio", 0.20))),
        float(node.get("neck_ratio", style.get("neck_ratio", 0.10))),
        str(node.get("brace_shape", node.get("shape", style.get("brace_shape", style.get("shape", "smooth"))))),
        (
            float(node.get("waist_width_in", style.get("waist_width_in")))
            if node.get("waist_width_in", style.get("waist_width_in")) is not None
            else None
        ),
        (
            float(node.get("curve_tightness", style.get("curve_tightness")))
            if node.get("curve_tightness", style.get("curve_tightness")) is not None
            else None
        ),
    )
    shape = draw_single_path(page, page_height, points, line_style, str(node.get("curve_mode", style.get("curve_mode", "smooth"))))

    tick_positions = node.get("tick_positions", node.get("port_positions", []))
    tick_len = float(node.get("tick_length_in", style.get("tick_length_in", 0.0)) or 0.0)
    if tick_len and isinstance(tick_positions, list):
        for tick in tick_positions:
            try:
                pos = max(0.0, min(1.0, float(tick)))
            except (TypeError, ValueError):
                continue
            if orientation == "right":
                start = (x + width, y + height * pos)
                end = (x + width - tick_len, y + height * pos)
            elif orientation == "left":
                start = (x, y + height * pos)
                end = (x + tick_len, y + height * pos)
            elif orientation == "down":
                start = (x + width * pos, y + height)
                end = (x + width * pos, y + height - tick_len)
            else:
                start = (x + width * pos, y)
                end = (x + width * pos, y + tick_len)
            shape = draw_line_segment(page, page_height, start, end, line_style)
    return shape


def draw_concat_operator(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", style.get("orientation", "vertical"))).lower()
    size_tier = str(node.get("concat_size_tier", style.get("concat_size_tier", "small")) or "small")
    tier_defaults = concat_size_tier_defaults(size_tier, width, height)
    tick = float(node.get("tick_in", style.get("tick_in", tier_defaults["tick_in"])))
    gap_ratio = float(node.get("gap_ratio", style.get("gap_ratio", tier_defaults["gap_ratio"])))
    gap_ratio = max(0.0, min(0.45, gap_ratio))
    line_style = merge_style(style, {"fill": "none", "end_arrow": "none"})
    glyph_mode = str(node.get("glyph_mode", node.get("shape_mode", style.get("glyph_mode", "bracket_pair")))).lower()
    if glyph_mode in {"solid_bracket", "bold_bracket", "source_bracket", "paper_bracket"}:
        source_tick = float(node.get("tick_in", style.get("tick_in", tier_defaults["tick_in"])))
        source_gap = max(0.0, min(0.42, float(node.get("gap_ratio", style.get("gap_ratio", min(gap_ratio, 0.16))))))
        source_style = merge_style(line_style, {"line_weight_pt": max(float(line_style.get("line_weight_pt", 1.2) or 1.2), float(tier_defaults["source_weight_pt"]))})
        shape = None
        if orientation in {"vertical", "v"}:
            left_x = x + width * source_gap
            right_x = x + width * (1.0 - source_gap)
            for bx, direction in ((left_x, 1), (right_x, -1)):
                shape = draw_line_segment(page, page_height, (bx, y), (bx, y + height), source_style)
                shape = draw_line_segment(page, page_height, (bx, y), (bx + direction * source_tick, y), source_style)
                shape = draw_line_segment(page, page_height, (bx, y + height), (bx + direction * source_tick, y + height), source_style)
        else:
            top_y = y + height * source_gap
            bottom_y = y + height * (1.0 - source_gap)
            for by, direction in ((top_y, 1), (bottom_y, -1)):
                shape = draw_line_segment(page, page_height, (x, by), (x + width, by), source_style)
                shape = draw_line_segment(page, page_height, (x, by), (x, by + direction * source_tick), source_style)
                shape = draw_line_segment(page, page_height, (x + width, by), (x + width, by + direction * source_tick), source_style)
        return shape
    if glyph_mode in {"boxed", "box", "square_box", "rect"}:
        shape = draw_rectangle(page, page_height, {"x": x, "y": y, "w": width, "h": height})
        apply_style(shape, line_style)
        return shape
    if glyph_mode in {"glyph", "text", "literal"}:
        glyph = str(node.get("symbol", style.get("symbol", "[]")))
        return draw_text_box(
            page,
            page_height,
            x,
            y,
            width,
            height,
            glyph,
            merge_style(
                style,
                {
                    "fill": "none",
                    "line": "none",
                    "font_role": node.get("symbol_font_role", style.get("symbol_font_role", "math")),
                    "font_size_pt": node.get("symbol_font_size_pt", style.get("symbol_font_size_pt", style.get("font_size_pt", 14))),
                    "text_fit": node.get("symbol_text_fit", style.get("symbol_text_fit", "single_line")),
                    "constrain_text_box": True,
                    "text_box_policy": "fit_inside",
                    "expand_text_box_for_single_line": False,
                },
            ),
        )

    shape = None
    port_positions = node.get("port_positions", node.get("ports", []))
    if isinstance(port_positions, list) and port_positions:
        port_len = float(node.get("port_length_in", style.get("port_length_in", 0.0)) or 0.0)
        if port_len > 0:
            for item in port_positions:
                if isinstance(item, dict):
                    pos = item.get("position", item.get("pos", 0.5))
                    side = str(item.get("side", "left")).lower()
                    current_len = float(item.get("length_in", item.get("port_length_in", port_len)) or 0.0)
                else:
                    pos = item
                    side = "left" if orientation in {"vertical", "v"} else "top"
                    current_len = port_len
                try:
                    pos_f = max(0.0, min(1.0, float(pos)))
                except (TypeError, ValueError):
                    continue
                if orientation in {"vertical", "v"}:
                    py = y + height * pos_f
                    if side == "right":
                        start, end = (x + width, py), (x + width + current_len, py)
                    else:
                        start, end = (x, py), (x - current_len, py)
                else:
                    px = x + width * pos_f
                    if side == "bottom":
                        start, end = (px, y + height), (px, y + height + current_len)
                    else:
                        start, end = (px, y), (px, y - current_len)
                shape = draw_line_segment(page, page_height, start, end, line_style)
    if orientation in {"vertical", "v"}:
        left_x = x + width * gap_ratio
        right_x = x + width * (1.0 - gap_ratio)
        shape = draw_line_segment(page, page_height, (left_x + tick, y), (left_x, y), line_style)
        shape = draw_line_segment(page, page_height, (left_x, y), (left_x, y + height), line_style)
        shape = draw_line_segment(page, page_height, (left_x, y + height), (left_x + tick, y + height), line_style)
        shape = draw_line_segment(page, page_height, (right_x - tick, y), (right_x, y), line_style)
        shape = draw_line_segment(page, page_height, (right_x, y), (right_x, y + height), line_style)
        shape = draw_line_segment(page, page_height, (right_x, y + height), (right_x - tick, y + height), line_style)
    else:
        top_y = y + height * gap_ratio
        bottom_y = y + height * (1.0 - gap_ratio)
        shape = draw_line_segment(page, page_height, (x, top_y + tick), (x, top_y), line_style)
        shape = draw_line_segment(page, page_height, (x, top_y), (x + width, top_y), line_style)
        shape = draw_line_segment(page, page_height, (x + width, top_y), (x + width, top_y + tick), line_style)
        shape = draw_line_segment(page, page_height, (x, bottom_y - tick), (x, bottom_y), line_style)
        shape = draw_line_segment(page, page_height, (x, bottom_y), (x + width, bottom_y), line_style)
        shape = draw_line_segment(page, page_height, (x + width, bottom_y), (x + width, bottom_y - tick), line_style)
    return shape


def draw_multi_port_junction(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", style.get("orientation", "vertical"))).lower()
    line_style = merge_style(style, {"fill": "none", "end_arrow": "none"})
    shape = None
    spine_visible = truthy(node.get("spine_visible", style.get("spine_visible")), True)
    if orientation in {"horizontal", "h", "row"}:
        spine_y = y + height / 2
        if spine_visible:
            shape = draw_line_segment(page, page_height, (x, spine_y), (x + width, spine_y), line_style)
    else:
        spine_x = x + width / 2
        if spine_visible:
            shape = draw_line_segment(page, page_height, (spine_x, y), (spine_x, y + height), line_style)

    raw_ports = node.get("ports")
    ports: list[dict[str, Any]] = []
    if isinstance(raw_ports, list) and raw_ports:
        for item in raw_ports:
            if isinstance(item, dict):
                ports.append(item)
            elif isinstance(item, (int, float)):
                ports.append({"position": item})
    else:
        positions = node.get("port_positions", node.get("positions", [0.0, 0.5, 1.0]))
        if not isinstance(positions, list):
            positions = [0.0, 0.5, 1.0]
        if positions and all(isinstance(item, dict) for item in positions):
            ports.extend(item for item in positions if isinstance(item, dict))
            positions = []
        default_sides = ["left", "right"] if orientation not in {"horizontal", "h", "row"} else ["top", "bottom"]
        for position in positions:
            for side in default_sides if str(node.get("side", "both")).lower() == "both" else [str(node.get("side", default_sides[0])).lower()]:
                ports.append({"position": position, "side": side})

    default_len = float(node.get("port_length_in", style.get("port_length_in", 0.16)))
    for port in ports:
        try:
            pos = float(port.get("position", 0.5))
        except (TypeError, ValueError):
            continue
        side = str(port.get("side", "left")).lower()
        length = float(port.get("length_in", port.get("port_length_in", default_len)))
        if length <= 0:
            continue
        if orientation in {"horizontal", "h", "row"}:
            px = x + width * max(0.0, min(1.0, pos))
            py = y + height / 2
            if side == "top":
                start, end = (px, py), (px, py - length)
            elif side == "bottom":
                start, end = (px, py), (px, py + length)
            elif side == "left":
                start, end = (px, py), (px - length, py)
            else:
                start, end = (px, py), (px + length, py)
        else:
            px = x + width / 2
            py = y + height * max(0.0, min(1.0, pos))
            if side == "right":
                start, end = (px, py), (px + length, py)
            elif side == "top":
                start, end = (px, py), (px, py - length)
            elif side == "bottom":
                start, end = (px, py), (px, py + length)
            else:
                start, end = (px, py), (px - length, py)
        port_style = merge_style(line_style, port.get("style") if isinstance(port.get("style"), dict) else None)
        shape = draw_line_segment(page, page_height, start, end, port_style)

    marker = str(node.get("marker", style.get("marker", "none"))).lower()
    if marker not in {"", "none", "false", "0"}:
        marker_size = float(node.get("marker_size_in", style.get("marker_size_in", min(width, height, 0.08))))
        marker_node = {
            "x": x + width / 2 - marker_size / 2,
            "y": y + height / 2 - marker_size / 2,
            "w": marker_size,
            "h": marker_size,
        }
        marker_shape = draw_rectangle(page, page_height, marker_node) if marker in {"square", "rect"} else draw_oval(page, page_height, marker_node)
        apply_style(
            marker_shape,
            merge_style(
                style,
                {
                    "fill": node.get("marker_fill", style.get("marker_fill", style.get("line", "#111827"))),
                    "line": node.get("marker_line", style.get("marker_line", style.get("line", "#111827"))),
                    "line_weight_pt": node.get("marker_line_weight_pt", style.get("marker_line_weight_pt", 0.5)),
                },
            ),
        )
        shape = marker_shape
    return shape


def draw_caption_block(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    runs_raw = node.get("runs")
    if not isinstance(runs_raw, list) or not runs_raw:
        text = str(node.get("text", ""))
        return draw_text_box(page, page_height, x, y, width, height, text, style)

    gap = float(node.get("run_gap_in", style.get("run_gap_in", 0.0)) or 0.0)
    width_factor = float(node.get("run_width_factor", style.get("run_width_factor", 1.0)) or 1.0)
    width_extra = float(node.get("run_width_extra_in", style.get("run_width_extra_in", 0.015)) or 0.0)
    auto_fill_last = truthy(node.get("auto_fill_last_run", style.get("auto_fill_last_run")), True)
    node_type = str(node.get("type", "")).lower()
    strict_mode = truthy(node.get("strict_mode", style.get("strict_mode")), False) or str(
        node.get("caption_mode", style.get("caption_mode", ""))
    ).lower() in {"strict", "strict_single_line", "strict_paper", "paper_caption"}
    baseline_offset = float(node.get("baseline_offset_in", style.get("baseline_offset_in", 0.0)) or 0.0)
    default_align = 0 if node_type == "annotation_block" or str(node.get("text_role", "")).lower() in {"annotation", "note", "callout"} else 1
    align_raw = node.get("caption_align", style.get("caption_align", node.get("text_align", style.get("text_align", default_align))))
    if isinstance(align_raw, str):
        align_value = {"left": 0, "start": 0, "center": 1, "centre": 1, "right": 2, "end": 2}.get(align_raw.lower(), 1)
    elif isinstance(align_raw, (int, float)):
        align_value = int(align_raw)
    else:
        align_value = 1
    vertical_align_raw = node.get("runs_vertical_align", style.get("runs_vertical_align", node.get("vertical_align", style.get("vertical_align", 1))))
    if isinstance(vertical_align_raw, str):
        vertical_align_value = {"top": 0, "start": 0, "center": 1, "centre": 1, "middle": 1, "bottom": 2, "end": 2}.get(vertical_align_raw.lower(), 1)
    elif isinstance(vertical_align_raw, (int, float)):
        vertical_align_value = int(vertical_align_raw)
    else:
        vertical_align_value = 1

    run_specs: list[dict[str, Any]] = []
    total_w = 0.0
    for run in runs_raw:
        if not isinstance(run, dict):
            run = {"text": str(run)}
        text = str(run.get("text", ""))
        if not text:
            continue
        run_style = merge_style(style, run.get("style") if isinstance(run.get("style"), dict) else None)
        for key in (
            "font_weight",
            "font_italic",
            "font_size_pt",
            "text_color",
            "font_family",
            "font_family_candidates",
            "font_role",
            "source_font_family",
            "text_fit",
            "min_font_size_pt",
        ):
            if key in run:
                run_style[key] = run[key]
        run_style = single_line_text_style(run_style, min_font_size_pt=float(run_style.get("min_font_size_pt", 5.5) or 5.5))
        font_size = float(run_style.get("font_size_pt", style.get("font_size_pt", 10)) or 10)
        width_safety = float(run.get("text_width_safety_factor", run_style.get("text_width_safety_factor", run_style.get("single_line_width_safety_factor", 1.12))) or 1.12)
        if len(text.strip()) <= 3:
            width_safety = max(width_safety, float(run.get("short_run_width_safety_factor", run_style.get("short_run_width_safety_factor", 1.35)) or 1.35))
        if any(ord(char) > 255 for char in text):
            width_safety = max(width_safety, float(run.get("cjk_text_width_safety_factor", run_style.get("cjk_text_width_safety_factor", 1.18)) or 1.18))
        render_as = str(run.get("render_as", run.get("renderer", run.get("type", "")))).lower()
        run_math = (
            truthy(run.get("math"), False)
            or truthy(run.get("force_math"), False)
            or render_as in {"math", "math_text", "formula", "formula_text", "inline_math"}
            or str(run_style.get("font_role", "")).lower() == "math"
        )
        default_w = approximate_text_width(text, font_size) * width_factor * width_safety + width_extra
        if run_math:
            default_w *= float(run.get("math_width_factor", style.get("math_run_width_factor", 1.08)) or 1.08)
        if len(text.strip()) <= 3:
            default_w = max(default_w, float(run.get("short_run_min_width_in", style.get("short_run_min_width_in", font_size / 72.0 * 2.20)) or (font_size / 72.0 * 2.20)))
        explicit_w = run.get("w", run.get("width"))
        run_w = max(0.02, float(explicit_w if explicit_w is not None else default_w))
        run_specs.append({"run": run, "text": text, "style": run_style, "width": run_w, "math": run_math})
        total_w += run_w
    if not run_specs:
        text = str(node.get("text", ""))
        return draw_text_box(page, page_height, x, y, width, height, text, style)
    total_w += gap * max(0, len(run_specs) - 1)
    if strict_mode:
        if align_value == 0:
            cursor_x = x
        elif align_value == 2:
            cursor_x = x + max(0.0, width - total_w)
        else:
            cursor_x = x + max(0.0, (width - total_w) / 2)
    else:
        cursor_x = x

    shape = None
    for run_index, item in enumerate(run_specs):
        run = item["run"]
        text = item["text"]
        run_style = item["style"]
        run_math = bool(item.get("math"))
        if strict_mode:
            run_style["text_align"] = 0
        if auto_fill_last and not strict_mode and run_index == len(run_specs) - 1:
            run_w = max(0.02, x + width - cursor_x)
        else:
            run_w = float(item["width"])
        run_w = min(max(0.02, run_w), max(0.02, x + width - cursor_x))
        run_h = min(height, float(run.get("h", run.get("height", height))))
        run_x = cursor_x + float(run.get("offset_x_in", run.get("x_offset_in", 0.0)) or 0.0)
        run_y = y + baseline_offset + float(run.get("baseline_offset_in", 0) or 0)
        if vertical_align_value == 1:
            run_y += max(0.0, (height - run_h) / 2)
        elif vertical_align_value == 2:
            run_y += max(0.0, height - run_h)
        run_y += float(run.get("offset_y_in", run.get("y_offset_in", 0.0)) or 0.0)
        if run_math:
            math_node = {
                "x": run_x,
                "y": run_y,
                "w": run_w,
                "h": run_h,
                "text": text,
                "font_size_pt": run.get("font_size_pt", run_style.get("font_size_pt")),
                "text_fit": run.get("text_fit", run_style.get("text_fit", "math_label")),
                "min_font_size_pt": run.get("min_font_size_pt", run_style.get("min_font_size_pt", 5.5)),
            }
            optional_math_fields = {
                "subscript_scale": run.get("subscript_scale", node.get("subscript_scale", style.get("subscript_scale"))),
                "subscript_offset_in": run.get("subscript_offset_in", node.get("subscript_offset_in", style.get("subscript_offset_in"))),
                "line_gap_in": run.get("line_gap_in", node.get("line_gap_in", style.get("line_gap_in"))),
                "segment_gap_in": run.get("segment_gap_in", node.get("segment_gap_in", style.get("segment_gap_in"))),
                "fragment_pad_in": run.get("fragment_pad_in", node.get("fragment_pad_in", style.get("fragment_pad_in"))),
                "subscript_pad_in": run.get("subscript_pad_in", node.get("subscript_pad_in", style.get("subscript_pad_in"))),
                "subscript_box_pad_in": run.get("subscript_box_pad_in", node.get("subscript_box_pad_in", style.get("subscript_box_pad_in"))),
                "allow_inline_mixed_text": run.get("allow_inline_mixed_text", node.get("allow_inline_mixed_text", style.get("allow_inline_mixed_text"))),
            }
            for key, value in optional_math_fields.items():
                if value is not None:
                    math_node[key] = value
            shape = draw_math_text(
                page,
                page_height,
                math_node,
                merge_style(
                    run_style,
                    {
                        "fill": "none",
                        "line": "none",
                        "text_align": 0 if len(run_specs) > 1 else run_style.get("text_align", align_value),
                        "vertical_align": 1,
                    },
                ),
            )
        else:
            shape = draw_text_box(page, page_height, run_x, run_y, run_w, run_h, text, run_style)
        cursor_x += run_w + gap
        if cursor_x >= x + width:
            break
    return shape


def draw_bracket(page: Any, page_height: float, node: dict[str, Any], style: dict[str, Any]) -> Any:
    x = float(node["x"])
    y = float(node["y"])
    width = float(node["w"])
    height = float(node["h"])
    orientation = str(node.get("orientation", style.get("orientation", "right"))).lower()
    line_style = merge_style(style, {"fill": "none", "end_arrow": "none"})
    shape_kind = str(node.get("shape", node.get("bracket_shape", style.get("shape", "straight")))).lower()
    if shape_kind in {"paper_curly", "dimension_brace", "latex_brace", "thin_curly"}:
        points = paper_curly_brace_points(
            x,
            y,
            width,
            height,
            orientation,
            float(node.get("terminal_indent_ratio", style.get("terminal_indent_ratio", 0.08))),
            float(node.get("outer_bulge_ratio", style.get("outer_bulge_ratio", 0.46))),
            float(node.get("waist_indent_ratio", style.get("waist_indent_ratio", 0.08))),
            float(node.get("neck_ratio", style.get("neck_ratio", 0.04))),
            float(node.get("lobe_ratio", style.get("lobe_ratio", 0.08))),
        )
        curve_mode = str(node.get("curve_mode", style.get("curve_mode", "bezier"))).lower()
        return draw_single_path(page, page_height, points, line_style, curve_mode)
    if shape_kind in {"curly", "brace", "curly_brace"}:
        points = brace_points(
            x,
            y,
            width,
            height,
            orientation,
            float(node.get("waist_ratio", style.get("waist_ratio", 0.5))),
            float(node.get("curl_ratio", style.get("curl_ratio", 0.20))),
            float(node.get("neck_ratio", style.get("neck_ratio", 0.10))),
            shape_kind,
            (
                float(node.get("waist_width_in", style.get("waist_width_in")))
                if node.get("waist_width_in", style.get("waist_width_in")) is not None
                else None
            ),
        )
        return draw_single_path(page, page_height, points, line_style, "smooth")

    ticks = node.get("tick_positions")
    if ticks is None:
        ticks = [0, 0.5, 1] if node.get("middle_tick") else [0, 1]
    tick_positions = [max(0.0, min(1.0, float(tick))) for tick in ticks]

    if orientation == "right":
        spine_x = x + width
        segments = [((spine_x, y), (spine_x, y + height))]
        segments.extend(((x, y + height * tick), (spine_x, y + height * tick)) for tick in tick_positions)
    elif orientation == "left":
        spine_x = x
        segments = [((spine_x, y), (spine_x, y + height))]
        segments.extend(((spine_x, y + height * tick), (x + width, y + height * tick)) for tick in tick_positions)
    elif orientation == "down":
        spine_y = y + height
        segments = [((x, spine_y), (x + width, spine_y))]
        segments.extend(((x + width * tick, y), (x + width * tick, spine_y)) for tick in tick_positions)
    elif orientation == "up":
        spine_y = y
        segments = [((x, spine_y), (x + width, spine_y))]
        segments.extend(((x + width * tick, spine_y), (x + width * tick, y + height)) for tick in tick_positions)
    else:
        raise ValueError(f"Unsupported bracket orientation: {orientation}")

    shape = None
    for start, end in segments:
        shape = draw_line_segment(page, page_height, start, end, line_style)
    return shape


def candidate_stencil_paths() -> list[Path]:
    candidates: list[Path] = []
    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        r"C:\Program Files\Microsoft Office",
    ]
    locales = ["2052", "1033"]
    for root in [item for item in roots if item]:
        for locale in locales:
            candidates.append(
                Path(root) / "Microsoft Office" / "root" / "Office16" / "Visio Content" / locale / "BASFLO_M.VSSX"
            )
            candidates.append(
                Path(root) / "root" / "Office16" / "Visio Content" / locale / "BASFLO_M.VSSX"
            )
    return candidates


def open_basic_flow_stencil(app: Any) -> Any | None:
    for path in candidate_stencil_paths():
        if path.exists():
            try:
                return app.Documents.OpenEx(str(path), 64)
            except Exception:
                continue
    return None


def get_master(stencil: Any | None, names: list[str]) -> Any | None:
    if stencil is None:
        return None
    for name in names:
        for getter in ("ItemU", "Item"):
            try:
                return getattr(stencil.Masters, getter)(name)
            except Exception:
                continue
    return None


def draw_master_shape(
    page: Any,
    page_height: float,
    node: dict[str, Any],
    master: Any | None,
) -> Any | None:
    if master is None:
        return None
    cx = float(node["x"]) + float(node["w"]) / 2
    cy = to_visio_y(page_height, float(node["y"]) + float(node["h"]) / 2)
    try:
        shape = page.Drop(master, cx, cy)
    except Exception:
        return None
    try_set_result(shape, "Width", float(node["w"]))
    try_set_result(shape, "Height", float(node["h"]))
    return shape


def node_style(
    node: dict[str, Any],
    component_map: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    node_type = node["type"]
    definition = component_map["node_types"][node_type]
    profile_nodes = profile.get("node_types", {})
    style = merge_style(
        definition.get("default_style"),
        profile.get("global_text"),
        profile_nodes.get(node_type),
        node.get("style"),
    )
    return definition["renderer"], style, definition


def draw_node(
    page: Any,
    page_height: float,
    node: dict[str, Any],
    asset_paths: dict[str, Path],
    component_map: dict[str, Any],
    profile: dict[str, Any],
    masters: dict[str, Any | None],
) -> Any:
    renderer, style, definition = node_style(node, component_map, profile)
    shape = None
    render_kind = renderer
    if render_kind == "text_block" and isinstance(node.get("runs"), list) and node.get("runs"):
        render_kind = "caption_block"

    if renderer == "visio_master":
        shape = draw_master_shape(page, page_height, node, masters.get(definition.get("master")))
        if shape is None:
            render_kind = definition.get("fallback_renderer", "rectangle")

    if shape is None:
        if render_kind == "group_container":
            shape = draw_group_container(page, page_height, node, style)
        elif render_kind == "audit_region":
            shape = draw_rectangle(page, page_height, node)
        elif render_kind in {"rectangle", "rounded_rectangle", "terminator", "pill", "legend_block", "text_block"}:
            shape = draw_rectangle(page, page_height, node)
        elif render_kind == "oval":
            shape = draw_oval(page, page_height, node)
        elif render_kind == "polygon_node":
            shape = draw_polygon_node(page, page_height, node)
        elif render_kind == "trapezoid_node":
            shape = draw_trapezoid_node(page, page_height, node)
        elif render_kind == "dual_wing_encoder":
            shape = draw_dual_wing_encoder(page, page_height, node, style)
        elif render_kind == "cuboid_node":
            shape = draw_cuboid_node(page, page_height, node, style)
        elif render_kind == "tensor_stack":
            shape = draw_tensor_stack(page, page_height, node, style)
        elif render_kind == "modality_spine":
            shape = draw_modality_spine(page, page_height, node, style)
        elif render_kind == "math_vector":
            shape = draw_math_vector(page, page_height, node, style)
        elif render_kind == "math_label_box":
            shape = draw_math_label_box(page, page_height, node, style)
        elif render_kind == "math_text":
            shape = draw_math_text(page, page_height, node, style)
        elif render_kind == "math_formula_group":
            shape = draw_math_formula_group(page, page_height, node, style)
        elif render_kind == "tfr_panel":
            shape = draw_tfr_panel(page, page_height, node, style)
        elif render_kind == "loss_region":
            shape = draw_loss_region(page, page_height, node, style)
        elif render_kind == "operator_node":
            shape = draw_operator_node(page, page_height, node, style)
        elif render_kind == "attention_score_motif":
            shape = draw_attention_score_motif(page, page_height, node, style)
        elif render_kind == "diamond":
            shape = draw_rotated_diamond(page, page_height, node)
        elif render_kind == "bracket":
            shape = draw_bracket(page, page_height, node, style)
        elif render_kind == "brace_merge":
            shape = draw_brace_merge(page, page_height, node, style)
        elif render_kind == "concat_operator":
            shape = draw_concat_operator(page, page_height, node, style)
        elif render_kind == "junction_point":
            shape = draw_oval(page, page_height, node)
        elif render_kind == "boundary_port":
            shape = draw_boundary_port(page, page_height, node, style)
        elif render_kind == "image_tile":
            asset_ref = node.get("asset_ref")
            if not asset_ref or asset_ref not in asset_paths:
                raise ValueError(f"image_tile node `{node['id']}` requires a valid `asset_ref`.")
            shape = draw_image_tile(page, page_height, node, asset_paths[asset_ref])
        elif render_kind == "grid_matrix":
            shape = draw_grid_matrix(page, page_height, node, style)
        elif render_kind == "token_grid":
            shape = draw_token_grid(page, page_height, node, style)
        elif render_kind == "feature_vector_stack":
            shape = draw_feature_vector_stack(page, page_height, node, style)
        elif render_kind == "probability_bar_list":
            shape = draw_probability_bar_list(page, page_height, node, style)
        elif render_kind == "stacked_process":
            shape = draw_stacked_process(page, page_height, node, style)
        elif render_kind == "notched_block":
            shape = draw_notched_block(page, page_height, node, style)
        elif render_kind == "feature_map_banded":
            shape = draw_feature_map_banded(page, page_height, node, style)
        elif render_kind == "feature_map_grid":
            shape = draw_feature_map_grid(page, page_height, node, style)
        elif render_kind == "merge_bus":
            shape = draw_merge_bus(page, page_height, node, style)
        elif render_kind == "multi_port_junction":
            shape = draw_multi_port_junction(page, page_height, node, style)
        elif render_kind == "caption_block":
            shape = draw_caption_block(page, page_height, node, style)
        elif render_kind == "wave_signal":
            shape = draw_wave_signal(page, page_height, node, style)
        elif render_kind == "cell_strip":
            shape = draw_cell_strip(page, page_height, node, style)
        elif render_kind == "micro_grid":
            shape = draw_micro_grid(page, page_height, node, style)
        elif render_kind == "polyline_wave":
            shape = draw_polyline_wave(page, page_height, node, style)
        elif render_kind in {"ribbon_arrow", "curved_ribbon_arrow", "loop_ribbon_arrow"}:
            shape = draw_ribbon_arrow(page, page_height, node, style, render_kind)
        elif render_kind == "primitive_group":
            shape = draw_primitive_group(page, page_height, node, style)
        elif render_kind == "symbol_group":
            shape = draw_symbol_group(page, page_height, node, style)
        elif render_kind == "classifier_head":
            shape = draw_classifier_head(page, page_height, node, style)
        elif render_kind == "layer_sequence":
            shape = draw_layer_sequence(page, page_height, node, style)
        elif render_kind == "boundary_fanout":
            shape = draw_boundary_fanout(page, page_height, node, style)
        else:
            raise ValueError(f"Unsupported renderer: {render_kind}")

    text = node.get("text")
    text_excluded_renderers = {
        "bracket",
        "brace_merge",
        "concat_operator",
        "wave_signal",
        "cell_strip",
        "micro_grid",
        "polyline_wave",
        "ribbon_arrow",
        "curved_ribbon_arrow",
        "loop_ribbon_arrow",
        "primitive_group",
        "symbol_group",
        "classifier_head",
        "layer_sequence",
        "boundary_fanout",
        "feature_map_grid",
        "group_container",
        "audit_region",
        "operator_node",
        "attention_score_motif",
        "math_vector",
        "math_label_box",
        "math_text",
        "math_formula_group",
        "tfr_panel",
        "loss_region",
        "token_grid",
        "feature_vector_stack",
        "probability_bar_list",
        "multi_port_junction",
        "caption_block",
    }
    style_excluded_renderers = {
        "bracket",
        "brace_merge",
        "concat_operator",
        "feature_map_banded",
        "feature_map_grid",
        "merge_bus",
        "wave_signal",
        "cell_strip",
        "micro_grid",
        "polyline_wave",
        "ribbon_arrow",
        "curved_ribbon_arrow",
        "loop_ribbon_arrow",
        "primitive_group",
        "symbol_group",
        "classifier_head",
        "layer_sequence",
        "boundary_fanout",
        "group_container",
        "operator_node",
        "attention_score_motif",
        "math_vector",
        "math_label_box",
        "math_text",
        "tfr_panel",
        "loss_region",
        "token_grid",
        "feature_vector_stack",
        "probability_bar_list",
        "multi_port_junction",
        "caption_block",
    }
    rotated_overlay_text = False
    if text and render_kind not in text_excluded_renderers:
        try:
            rotated_overlay_text = abs((float(style.get("text_angle_deg", 0) or 0) % 180) - 90) <= 1e-3
        except (TypeError, ValueError):
            rotated_overlay_text = False
        if not rotated_overlay_text:
            try_set_text(shape, str(text))

    if render_kind not in style_excluded_renderers:
        shape_style = merge_style(style, {"text_angle_deg": 0}) if rotated_overlay_text else style
        shape_text = "" if rotated_overlay_text else node.get("text", node.get("symbol", ""))
        apply_style(shape, shape_style, shape_text, float(node.get("w", 0.0)), float(node.get("h", 0.0)))
        if rotated_overlay_text:
            draw_rotated_text_box(
                page,
                page_height,
                float(node.get("x", 0.0)),
                float(node.get("y", 0.0)),
                float(node.get("w", 0.0)),
                float(node.get("h", 0.0)),
                str(text),
                style,
            )
    if render_kind == "terminator" and "rounding_in" not in style:
        try_set_formula(shape, "Rounding", f"{min(float(node['h']) / 2, 0.25)} in")
    return shape


def opposite_axis(side_a: str, side_b: str) -> str | None:
    if {side_a, side_b} <= {"left", "right"}:
        return "horizontal"
    if {side_a, side_b} <= {"top", "bottom"}:
        return "vertical"
    return None


def orthogonal_points(
    start: tuple[float, float],
    end: tuple[float, float],
    axis: str | None,
) -> list[tuple[float, float]]:
    sx, sy = start
    tx, ty = end
    if axis == "horizontal":
        mid_x = (sx + tx) / 2
        return [start, (mid_x, sy), (mid_x, ty), end]
    if axis == "vertical":
        mid_y = (sy + ty) / 2
        return [start, (sx, mid_y), (tx, mid_y), end]
    if abs(tx - sx) >= abs(ty - sy):
        mid_x = (sx + tx) / 2
        return [start, (mid_x, sy), (mid_x, ty), end]
    mid_y = (sy + ty) / 2
    return [start, (sx, mid_y), (tx, mid_y), end]


def snap_axis_segments(
    points: list[tuple[float, float]],
    tolerance: float,
) -> list[tuple[float, float]]:
    if len(points) < 2 or tolerance <= 0:
        return points

    snapped = [points[0]]
    for x, y in points[1:]:
        prev_x, prev_y = snapped[-1]
        if abs(x - prev_x) <= tolerance:
            x = prev_x
        if abs(y - prev_y) <= tolerance:
            y = prev_y
        snapped.append((x, y))
    return snapped


def expand_axis_aligned_points(
    points: list[tuple[float, float]],
    axis: str | None = None,
) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    expanded: list[tuple[float, float]] = [points[0]]
    for target in points[1:]:
        start = expanded[-1]
        if abs(start[0] - target[0]) > 1e-9 and abs(start[1] - target[1]) > 1e-9:
            if axis == "vertical":
                append_distinct_point(expanded, (start[0], target[1]))
            else:
                append_distinct_point(expanded, (target[0], start[1]))
        append_distinct_point(expanded, target)
    return expanded


def standardized_bezier_arc_points(
    start: tuple[float, float],
    end: tuple[float, float],
    template: str,
    edge: dict[str, Any],
    style: dict[str, Any],
) -> list[tuple[float, float]]:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    distance = max(math.hypot(dx, dy), 1e-6)
    lift = float(edge.get("arc_lift_in", style.get("arc_lift_in", max(0.16, min(1.1, distance * 0.28)))) or 0.16)
    template = template.lower().replace("-", "_")

    def endpoint_outward(endpoint: Any, fallback: tuple[float, float]) -> tuple[float, float]:
        if not isinstance(endpoint, str) or ":" not in endpoint:
            return fallback
        side = endpoint.split(":", 1)[1].split("@", 1)[0].lower()
        if side == "left":
            return (-1.0, 0.0)
        if side == "right":
            return (1.0, 0.0)
        if side == "top":
            return (0.0, -1.0)
        if side == "bottom":
            return (0.0, 1.0)
        return fallback

    def with_endpoint_tangents(
        default_c1: tuple[float, float],
        default_c2: tuple[float, float],
    ) -> list[tuple[float, float]]:
        source_tangent = edge.get("source_tangent_in", edge.get("start_tangent_in", style.get("source_tangent_in")))
        target_tangent = edge.get("target_tangent_in", edge.get("end_tangent_in", style.get("target_tangent_in")))
        c1 = default_c1
        c2 = default_c2
        if isinstance(source_tangent, (int, float)) and float(source_tangent) > 0:
            vx, vy = endpoint_outward(edge.get("from"), (1.0 if dx >= 0 else -1.0, 0.0))
            if abs(vx) >= abs(vy):
                c1 = (sx + vx * float(source_tangent), sy)
            else:
                c1 = (sx, sy + vy * float(source_tangent))
        if isinstance(target_tangent, (int, float)) and float(target_tangent) > 0:
            vx, vy = endpoint_outward(edge.get("to"), (-1.0 if dx >= 0 else 1.0, 0.0))
            if abs(vx) >= abs(vy):
                c2 = (ex + vx * float(target_tangent), default_c2[1])
            else:
                c2 = (default_c2[0], ey + vy * float(target_tangent))
        return [start, c1, c2, end]

    if template in {"upper", "up", "top", "above", "over", "upper_arc", "top_arc", "over_arc"}:
        cy = min(sy, ey) - lift
        return with_endpoint_tangents((sx + dx * 0.25, cy), (sx + dx * 0.75, cy))
    if template in {"lower", "down", "bottom", "below", "under", "lower_arc", "bottom_arc", "under_arc"}:
        cy = max(sy, ey) + lift
        return with_endpoint_tangents((sx + dx * 0.25, cy), (sx + dx * 0.75, cy))
    if template in {"left", "left_bulge", "left_arc", "outside_left"}:
        cx = min(sx, ex) - lift
        return with_endpoint_tangents((cx, sy + dy * 0.20), (cx, sy + dy * 0.80))
    if template in {"right", "right_bulge", "right_arc", "outside_right", "right_then_in"}:
        cx = max(sx, ex) + lift
        return with_endpoint_tangents((cx, sy + dy * 0.20), (cx, sy + dy * 0.80))
    if template in {"fanout", "fanout_arc", "fanout_upper", "fanout_lower", "branch_arc", "branch_upper", "branch_lower", "split_arc"}:
        spread = float(edge.get("branch_spread_in", edge.get("fanout_spread_in", style.get("branch_spread_in", lift))) or lift)
        direction = -1.0 if template in {"fanout_upper", "branch_upper"} or (template in {"fanout_arc", "fanout", "branch_arc", "split_arc"} and ey < sy) else 1.0
        c1 = (sx + dx * 0.38, sy + direction * spread * 0.55)
        c2 = (sx + dx * 0.72, ey - direction * spread * 0.18)
        return with_endpoint_tangents(c1, c2)
    if template in {"small_bend_in", "soft_bend_in"}:
        return with_endpoint_tangents((sx + dx * 0.55, sy), (ex - dx * 0.15, ey))

    if abs(dx) >= abs(dy):
        cy = min(sy, ey) - lift
        return with_endpoint_tangents((sx + dx * 0.25, cy), (sx + dx * 0.75, cy))
    cx = max(sx, ex) + lift
    return with_endpoint_tangents((cx, sy + dy * 0.20), (cx, sy + dy * 0.80))


def edge_route_points(
    edge: dict[str, Any],
    style: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[tuple[float, float]]:
    from_ref = edge.get("from")
    to_ref = edge.get("to")
    from_point = edge_point(edge, "from")
    to_point = edge_point(edge, "to")

    from_node = nodes_by_id[node_id_from_endpoint(from_ref)] if isinstance(from_ref, str) else None
    to_node = nodes_by_id[node_id_from_endpoint(to_ref)] if isinstance(to_ref, str) else None
    from_peer_point = to_point or (node_center_point(to_node) if to_node else from_point)
    to_peer_point = from_point or (node_center_point(from_node) if from_node else to_point)
    if from_peer_point is None or to_peer_point is None:
        raise ValueError(f"Edge `{edge.get('id', '<unknown>')}` requires resolvable endpoints.")

    from_side = (
        route_side_for_endpoint_side(side_of(from_ref, from_node, fake_node_at(from_peer_point)))
        if isinstance(from_ref, str) and from_node
        else "point"
    )
    to_side = (
        route_side_for_endpoint_side(side_of(to_ref, to_node, fake_node_at(to_peer_point)))
        if isinstance(to_ref, str) and to_node
        else "point"
    )
    start = resolve_edge_endpoint(edge, "from", from_peer_point, nodes_by_id)
    end = resolve_edge_endpoint(edge, "to", to_peer_point, nodes_by_id)

    explicit_points = edge.get("points") or []
    start_tangent_point = edge_named_point(edge, "start_tangent_point")
    end_tangent_point = edge_named_point(edge, "end_tangent_point")
    axis_snap = float(edge.get("axis_snap_in", style.get("axis_snap_in", 0.03)))
    curve_mode = str(edge.get("curve_mode", edge.get("curve", style.get("curve_mode", "")))).lower()
    arrow_template = str(edge.get("arrow_template", edge.get("template", ""))).lower()
    arc_template = str(
        edge.get("arc_template", edge.get("bezier_template", edge.get("curve_template", "")))
    ).lower()
    if explicit_points or start_tangent_point or end_tangent_point:
        routed: list[tuple[float, float]] = []
        append_distinct_point(routed, start)
        append_distinct_point(routed, start_tangent_point)
        for x, y in explicit_points:
            append_distinct_point(routed, (float(x), float(y)))
        append_distinct_point(routed, end_tangent_point)
        append_distinct_point(routed, end)
        route_name = str(edge.get("route") or style.get("route") or "").lower()
        force_axis = str(edge.get("force_axis", style.get("force_axis", ""))).lower()
        if force_axis not in {"horizontal", "vertical"}:
            force_axis = None
        if edge.get("orthogonalize_points") or route_name in {"orthogonal", "elbow", "right_angle", "rounded_orthogonal", "hv", "vh", "horizontal_then_vertical", "vertical_then_horizontal"}:
            if route_name in {"vh", "vertical_then_horizontal"}:
                force_axis = "vertical"
            elif route_name in {"hv", "horizontal_then_vertical"}:
                force_axis = "horizontal"
            routed = expand_axis_aligned_points(routed, force_axis)
        return snap_axis_segments(routed, axis_snap)

    if curve_mode == "bezier" and (
        arc_template
        or arrow_template in {"bezier_arc", "skip_arc_no_arrow", "feedback_loop", "fanout_arc", "branch_arc"}
        or edge.get("standardize_bezier_arc")
    ):
        return standardized_bezier_arc_points(start, end, arc_template or arrow_template or "auto", edge, style)

    route = edge.get("route") or style.get("route") or "auto"
    if route == "straight":
        return [start, end]
    if route in {"horizontal", "hline", "axis_horizontal"}:
        return [(start[0], start[1]), (end[0], start[1])]
    if route in {"vertical", "vline", "axis_vertical"}:
        return [(start[0], start[1]), (start[0], end[1])]
    if route in {"hv", "horizontal_then_vertical"}:
        return snap_axis_segments([start, (end[0], start[1]), end], axis_snap)
    if route in {"vh", "vertical_then_horizontal"}:
        return snap_axis_segments([start, (start[0], end[1]), end], axis_snap)

    axis = opposite_axis(from_side, to_side)
    snap_tolerance = float(edge.get("snap_tolerance_in", style.get("snap_tolerance_in", 0.18)))

    if route in {"orthogonal", "elbow", "right_angle", "rounded_orthogonal"}:
        return snap_axis_segments(orthogonal_points(start, end, axis), axis_snap)

    if axis == "horizontal" and abs(start[1] - end[1]) <= snap_tolerance:
        y = (start[1] + end[1]) / 2
        return [(start[0], y), (end[0], y)]
    if axis == "vertical" and abs(start[0] - end[0]) <= snap_tolerance:
        x = (start[0] + end[0]) / 2
        return [(x, start[1]), (x, end[1])]
    if axis:
        return snap_axis_segments(orthogonal_points(start, end, axis), axis_snap)
    return [start, end]


def draw_line_segment(
    page: Any,
    page_height: float,
    start: tuple[float, float],
    end: tuple[float, float],
    style: dict[str, Any],
) -> Any:
    segment_length = math.hypot(end[0] - start[0], end[1] - start[1])
    shape = page.DrawLine(start[0], to_visio_y(page_height, start[1]), end[0], to_visio_y(page_height, end[1]))
    apply_style(shape, style)
    apply_arrow_style(shape, style, segment_length)
    return shape


def apply_arrow_style(shape: Any, style: dict[str, Any], path_length: float) -> None:
    if style.get("end_arrow") == "triangle":
        try_set_result(shape, "EndArrow", 13)
        try_set_result(shape, "EndArrowSize", arrow_size_value(style.get("arrow_size", style.get("end_arrow_size")), path_length))
    elif style.get("end_arrow") == "none":
        try_set_result(shape, "EndArrow", 0)
    if style.get("begin_arrow") == "triangle":
        try_set_result(shape, "BeginArrow", 13)
        try_set_result(shape, "BeginArrowSize", arrow_size_value(style.get("begin_arrow_size", style.get("arrow_size")), path_length))


def draw_single_path(
    page: Any,
    page_height: float,
    points: list[tuple[float, float]],
    style: dict[str, Any],
    curve_mode: str = "polyline",
) -> Any:
    if len(points) < 2:
        raise ValueError("Path edges require at least two points.")

    render_points = points
    if curve_mode in {"smooth", "spline"}:
        samples = int(style.get("smooth_samples", style.get("samples_per_segment", 10)) or 10)
        render_points = catmull_rom_points(points, max(3, samples))
    elif curve_mode in {"rounded_orthogonal", "rounded_orthogonal_arc", "orthogonal_round"}:
        radius = float(style.get("corner_radius_in", style.get("corner_radius", 0.08)) or 0.0)
        samples = int(style.get("corner_samples", style.get("samples_per_corner", 5)) or 5)
        render_points = rounded_orthogonal_points(points, radius, samples)

    def path_values(path_points: list[tuple[float, float]]) -> list[float]:
        values: list[float] = []
        for x, y in path_points:
            values.extend([float(x), to_visio_y(page_height, float(y))])
        return values

    values = path_values(render_points)

    tolerance = float(style.get("curve_tolerance", 0.0))
    shape = None
    if curve_mode == "bezier" and len(points) >= 4:
        try:
            shape = draw_visio_bezier(page, values, tolerance)
        except Exception:
            shape = None

    if shape is None:
        if curve_mode == "bezier" and len(points) >= 4:
            render_points = cubic_bezier_sample_points(points, int(style.get("bezier_samples", 12) or 12))
            values = path_values(render_points)
        shape = draw_visio_polyline(page, values, tolerance)

    apply_style(shape, style)
    path_length = sum(math.hypot(end[0] - start[0], end[1] - start[1]) for start, end in zip(render_points, render_points[1:]))
    apply_arrow_style(shape, style, path_length)
    return shape


def edge_style(edge: dict[str, Any], component_map: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    definition = component_map["edge_types"][edge["type"]]
    profile_edges = profile.get("edge_types", {})
    return merge_style(
        definition.get("default_style"),
        profile.get("global_edge"),
        profile_edges.get(edge["type"]),
        edge.get("style"),
    )


def draw_edge(
    page: Any,
    page_height: float,
    edge: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    component_map: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[Any, float, float]:
    style = edge_style(edge, component_map, profile)
    for key in ("corner_radius_in", "corner_radius", "corner_samples", "samples_per_corner"):
        if edge.get(key) is not None:
            style[key] = edge[key]
    definition = component_map["edge_types"][edge["type"]]
    points = edge_route_points(edge, style, nodes_by_id)
    renderer = definition.get("renderer", "straight_line")
    if renderer == "rounded_orthogonal_path":
        shape = draw_single_path(page, page_height, points, style, "rounded_orthogonal")
        mid_x, mid_y = point_along_polyline(points, 0.5)
        return shape, mid_x, mid_y
    if renderer in {"single_path", "curved_path"}:
        curve_mode = str(edge.get("curve_mode", edge.get("curve", style.get("curve_mode", "polyline")))).lower()
        if renderer == "single_path" and curve_mode in {"auto", ""}:
            curve_mode = "polyline"
        shape = draw_single_path(page, page_height, points, style, curve_mode)
        mid_index = len(points) // 2
        mid_x, mid_y = points[mid_index]
        return shape, mid_x, mid_y

    segments = []
    for index in range(len(points) - 1):
        segment_style = dict(style)
        if index != len(points) - 2:
            segment_style["end_arrow"] = "none"
        segments.append(draw_line_segment(page, page_height, points[index], points[index + 1], segment_style))

    mid_index = len(points) // 2
    mid_x, mid_y = points[mid_index]
    return segments[-1], mid_x, mid_y


def draw_edge_label(page: Any, page_height: float, text: str, mid_x: float, mid_y: float, profile: dict[str, Any]) -> Any:
    label_style = merge_style(
        profile.get("global_text"),
        {
            "fill": "none",
            "line": "none",
            "font_size_pt": 10,
            "font_weight": "regular",
            "text_fit": "single_line",
            "min_font_size_pt": 5.5,
            "text_margin_in": 0.0,
        },
    )
    font_size = float(label_style.get("font_size_pt", 10))
    width = max(0.32, min(1.45, approximate_text_width(text, font_size) + 0.10))
    height = max(0.16, min(0.32, font_size / 72.0 * 1.35))
    return draw_text_box(
        page,
        page_height,
        mid_x - width / 2,
        mid_y - height / 2,
        width,
        height,
        text,
        label_style,
    )


def point_along_polyline(points: list[tuple[float, float]], ratio: float) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if len(points) == 1:
        return points[0]
    clamped = max(0.0, min(1.0, float(ratio)))
    lengths: list[float] = []
    total = 0.0
    for start, end in zip(points, points[1:]):
        length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
        lengths.append(length)
        total += length
    if total <= 0:
        return points[len(points) // 2]
    target = total * clamped
    walked = 0.0
    for index, length in enumerate(lengths):
        if walked + length >= target:
            segment_ratio = 0.0 if length <= 0 else (target - walked) / length
            start = points[index]
            end = points[index + 1]
            return (
                start[0] + (end[0] - start[0]) * segment_ratio,
                start[1] + (end[1] - start[1]) * segment_ratio,
            )
        walked += length
    return points[-1]


def draw_edge_label_for_edge(
    page: Any,
    page_height: float,
    edge: dict[str, Any],
    points: list[tuple[float, float]],
    profile: dict[str, Any],
) -> Any:
    text = str(edge.get("label", ""))
    if not text:
        return None
    ratio = edge.get("label_position", edge.get("label_ratio", edge.get("label_t", 0.5)))
    try:
        label_x, label_y = point_along_polyline(points, float(ratio))
    except (TypeError, ValueError):
        label_x, label_y = point_along_polyline(points, 0.5)
    label_x += float(edge.get("label_offset_x_in", 0.0) or 0.0)
    label_y += float(edge.get("label_offset_y_in", 0.0) or 0.0)
    return draw_edge_label(page, page_height, text, label_x, label_y, profile)


def resolve_profile(scene: dict[str, Any], profiles: dict[str, Any], requested: str | None) -> tuple[str, dict[str, Any]]:
    name = (
        requested
        or scene.get("metadata", {}).get("style_profile")
        or scene.get("page", {}).get("style_profile")
        or profiles.get("default_profile")
        or "paper_white"
    )
    profile = profiles.get("profiles", {}).get(name, {})
    return name, profile


def scene_text_corpus(scene: dict[str, Any]) -> str:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    parts = [str(metadata.get("title", "")), str(metadata.get("notes", "")), str(metadata.get("fidelity", ""))]
    for node in scene.get("nodes", []) or []:
        if isinstance(node, dict):
            parts.extend(str(node.get(key, "")) for key in ("id", "type", "text", "title", "subtitle", "semantic_role"))
    return " ".join(parts).lower()


def exact_mode_from_scene(scene: dict[str, Any]) -> bool:
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    fidelity = str(metadata.get("fidelity", metadata.get("reconstruction_mode", ""))).lower()
    review_mode = str(metadata.get("replica_review_mode", metadata.get("review_mode", ""))).lower()
    return fidelity in {"exact", "strict", "replica", "reconstruction", "1:1"} or review_mode in {
        "strict_replica",
        "strict",
        "exact_replica",
        "strict_exact",
    }


def should_run_rebuild_gate(scene: dict[str, Any]) -> bool:
    corpus = scene_text_corpus(scene)
    return (
        exact_mode_from_scene(scene)
        or ("generator" in corpus and "discriminator" in corpus)
        or ("gan" in corpus and "tfr" in corpus)
    )


def should_run_gan_tfr_autofix(scene: dict[str, Any]) -> bool:
    corpus = scene_text_corpus(scene)
    if ("generator" in corpus and "discriminator" in corpus) or ("gan" in corpus and "tfr" in corpus):
        return True
    for node in scene.get("nodes", []) or []:
        if isinstance(node, dict) and node.get("type") in {"tfr_panel", "loss_region"}:
            return True
    return False


def maybe_autofix_gan_tfr_scene(
    scene: dict[str, Any],
    scene_path: Path,
    output_dir: Path,
    basename: str | None,
) -> tuple[dict[str, Any], Path]:
    if not should_run_gan_tfr_autofix(scene):
        return scene, scene_path

    try:
        from scene_autofix import apply_gan_tfr_recipes, record_recipe_application
    except Exception as exc:
        print(f"WARNING: GAN/TFR autofix unavailable before render: {exc}", file=sys.stderr)
        return scene, scene_path

    fixed_scene = copy.deepcopy(scene)
    changes = apply_gan_tfr_recipes(fixed_scene)
    if not changes:
        return scene, scene_path
    record_recipe_application(fixed_scene, "gan-tfr", changes, "visiomaster.scene_to_visio")

    output_name = basename or scene_path.stem
    fixed_path = output_dir / f"{output_name}.autofixed.scene.json"
    fixed_path.write_text(json.dumps(fixed_scene, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Applied pre-render GAN/TFR autofix:")
    for item in changes:
        print(f"- {item}")
    print(f"Wrote autofixed scene: {fixed_path}")
    return fixed_scene, fixed_path


def run_rebuild_gate(scene_path: Path) -> None:
    scripts_dir = skill_root() / "scripts"
    with tempfile.TemporaryDirectory(prefix="visiomaster_gate_") as temp_dir:
        audit_path = Path(temp_dir) / "scene.audit.md"
        commands = [
            [sys.executable, str(scripts_dir / "scene_validate.py"), str(scene_path), "--strict"],
            [sys.executable, str(scripts_dir / "arrow_audit_gate.py"), str(scene_path), "--strict"],
            [sys.executable, str(scripts_dir / "style_calibration_gate.py"), str(scene_path), "--strict"],
            [sys.executable, str(scripts_dir / "scene_geometry_assert.py"), str(scene_path), "--strict"],
            [
                sys.executable,
                str(scripts_dir / "scene_audit.py"),
                str(scene_path),
                "--output",
                str(audit_path),
                "--fail-on-rebuild",
            ],
        ]
        for command in commands:
            result = subprocess.run(command, text=True, capture_output=True)
            if result.returncode:
                if result.stdout:
                    print(result.stdout.rstrip())
                if result.stderr:
                    print(result.stderr.rstrip(), file=sys.stderr)
                raise RuntimeError(
                    "Rebuild gate failed before Visio rendering. Run scene_autofix.py or fix [REBUILD] items before export. "
                    "Use --skip-rebuild-gate only for debugging."
                )


LAYER_Z_DEFAULTS = {
    "background": -1000,
    "panel": -500,
    "arrow_under_text": -100,
    "icon": 0,
    "text": 100,
    "foreground_arrow": 200,
}


def render_layer_z(item: dict[str, Any], default_z: float) -> float:
    if isinstance(item.get("z"), (int, float)):
        return float(item["z"])
    layer = str(item.get("layer", "")).strip().lower()
    if layer in LAYER_Z_DEFAULTS:
        return float(LAYER_Z_DEFAULTS[layer])
    style = item.get("style")
    if isinstance(style, dict):
        style_layer = str(style.get("layer", "")).strip().lower()
        if style_layer in LAYER_Z_DEFAULTS:
            return float(LAYER_Z_DEFAULTS[style_layer])
    return default_z


def node_default_z(node: dict[str, Any]) -> float:
    node_type = str(node.get("type", ""))
    if node_type == "page_background":
        return float(LAYER_Z_DEFAULTS["background"])
    if node_type in {"group_container", "dashed_region", "audit_region"}:
        return float(LAYER_Z_DEFAULTS["panel"])
    if node_type in {"text_block", "annotation_block", "caption_block", "math_text", "formula_text_block"}:
        return float(LAYER_Z_DEFAULTS["text"])
    if node_type in {"ribbon_arrow", "curved_ribbon_arrow", "loop_ribbon_arrow"}:
        return float(LAYER_Z_DEFAULTS["arrow_under_text"])
    return 0.0


def edge_default_z(edge: dict[str, Any]) -> float:
    layer = str(edge.get("layer", "")).strip().lower()
    if layer in LAYER_Z_DEFAULTS:
        return float(LAYER_Z_DEFAULTS[layer])
    return 100.0


def render_queue_entries(scene: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    order = 0
    for node in scene.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        entries.append({"kind": "node", "item": node, "sort_z": render_layer_z(node, node_default_z(node)), "order": order})
        order += 1
    for edge in scene.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        edge_z = render_layer_z(edge, edge_default_z(edge))
        entries.append({"kind": "edge", "item": edge, "sort_z": edge_z, "order": order})
        order += 1
        if edge.get("label"):
            label_entry = {
                "kind": "edge_label",
                "item": edge,
                "sort_z": render_layer_z(
                    {
                        "z": edge.get("label_z"),
                        "layer": edge.get("label_layer", "text"),
                        "style": edge.get("label_style", {}),
                    },
                    float(LAYER_Z_DEFAULTS["text"]),
                ),
                "order": order,
            }
            entries.append(label_entry)
            order += 1
    return sorted(entries, key=lambda entry: (entry["sort_z"], entry["order"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a visiomaster scene.json into Visio.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--output-dir", required=True, help="Directory for rendered outputs")
    parser.add_argument("--visible", action="store_true", help="Show Visio while rendering")
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Leave Visio open after rendering. Implies --visible.",
    )
    parser.add_argument("--basename", help="Optional output basename")
    parser.add_argument("--style-profile", help="Override scene style profile.")
    parser.add_argument(
        "--skip-rebuild-gate",
        action="store_true",
        help="Skip validate/audit rebuild gate before rendering exact or GAN/TFR scenes. Intended for debugging only.",
    )
    parser.add_argument(
        "--autofix-gan-tfr",
        action="store_true",
        help="Explicitly allow the GAN/TFR deterministic autofix pass before rendering. Exact/strict scenes no longer autofix implicitly.",
    )
    parser.add_argument(
        "--no-autofix",
        action="store_true",
        help="Disable the pre-render GAN/TFR deterministic autofix pass for non-exact generation/debug flows.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scene_path = Path(args.scene).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_scene = load_json(scene_path)
    gate_scene_path = scene_path
    if args.autofix_gan_tfr:
        raw_scene, gate_scene_path = maybe_autofix_gan_tfr_scene(raw_scene, scene_path, output_dir, args.basename)
    elif not args.no_autofix and not exact_mode_from_scene(raw_scene):
        raw_scene, gate_scene_path = maybe_autofix_gan_tfr_scene(raw_scene, scene_path, output_dir, args.basename)
    elif not args.no_autofix and exact_mode_from_scene(raw_scene) and should_run_gan_tfr_autofix(raw_scene):
        print(
            "Strict/exact scene detected; skipping implicit GAN/TFR autofix. "
            "Use --autofix-gan-tfr only for an explicit bootstrap helper path.",
            file=sys.stderr,
        )
    if not args.skip_rebuild_gate and should_run_rebuild_gate(raw_scene):
        try:
            run_rebuild_gate(gate_scene_path)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    scene = normalize_scene_coordinates(raw_scene)
    component_map = load_component_map()
    profiles = load_style_profiles()
    profile_name, profile = resolve_profile(scene, profiles, args.style_profile)

    try:
        import win32com.client.gencache as gencache
    except ImportError as exc:
        raise SystemExit("pywin32 is required. Install it in the active Python environment.") from exc

    app = gencache.EnsureDispatch("Visio.Application")
    app.Visible = bool(args.visible or args.keep_open)
    try:
        app.AlertResponse = 7
    except Exception:
        pass

    stencil = open_basic_flow_stencil(app)
    masters = {
        "Process": get_master(stencil, ["Process", "流程"]),
        "Decision": get_master(stencil, ["Decision", "判定"]),
        "Start/End": get_master(stencil, ["Start/End", "开始/结束"]),
    }

    doc = app.Documents.Add("")
    page = doc.Pages.Item(1)

    page_width = float(scene["page"]["width"])
    page_height = float(scene["page"]["height"])
    try_set_formula(page.PageSheet, "PageWidth", f"{page_width} in")
    try_set_formula(page.PageSheet, "PageHeight", f"{page_height} in")

    nodes_by_id = {node["id"]: node for node in scene.get("nodes", [])}
    asset_paths = {
        asset["id"]: Path(asset["path"]).resolve()
        for asset in scene.get("assets", [])
        if asset.get("path")
    }

    for entry in render_queue_entries(scene):
        item = entry["item"]
        if entry["kind"] == "node":
            draw_node(page, page_height, item, asset_paths, component_map, profile, masters)
        elif entry["kind"] == "edge":
            draw_edge(page, page_height, item, nodes_by_id, component_map, profile)
        elif entry["kind"] == "edge_label":
            route_points = edge_route_points(item, edge_style(item, component_map, profile), nodes_by_id)
            draw_edge_label_for_edge(page, page_height, item, route_points, profile)

    basename = args.basename or scene_path.stem
    vsdx_path = output_dir / f"{basename}.vsdx"
    svg_path = output_dir / f"{basename}.svg"
    png_path = output_dir / f"{basename}.png"

    doc.SaveAs(str(vsdx_path))

    export_errors = []
    for export_path in (svg_path, png_path):
        try:
            page.Export(str(export_path))
        except Exception as exc:
            export_errors.append(f"{export_path.name}: {exc}")

    print(f"Style profile: {profile_name}")
    print(f"Wrote: {vsdx_path}")
    if export_errors:
        print("Export warnings:")
        for item in export_errors:
            print(f"- {item}")
    else:
        print(f"Wrote: {svg_path}")
        print(f"Wrote: {png_path}")

    if not args.keep_open:
        try:
            doc.Saved = True
            doc.Close()
        except Exception:
            pass
        if stencil is not None:
            try:
                stencil.Close()
            except Exception:
                pass
        app.Quit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
