#!/usr/bin/env python3
"""Authoring-time schema hint scanner for strict scenes.

Read-only companion to scene_validate.py. Where the validator says "X is invalid",
this tool says "X is invalid, here is the exact correct spelling / structure" so the
authoring agent fixes grammar in one pass instead of discovering the vocabulary by
trial and error. It never suggests content or layout; observability stays with the
visual analysis step, only syntax is pre-checked.

Usage:
    python schema_hints.py <scene.json> [--output-report hints.json]
Prints one HINT block per finding. Exit code 0 even when hints exist (advisory),
2 only on unreadable input.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ARROW_PLAN_DIRECTIONS = ["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top", "bidirectional", "none", "unknown"]
SEMANTIC_INTENTS = ["data_flow", "control_flow", "feedback", "loss_backprop", "boundary_handoff", "frame_output", "merge", "fan_in", "fork", "fan_out", "loop_update", "annotation", "callout"]
ROUTE_SHAPES = ["straight", "straight_horizontal", "straight_vertical", "horizontal", "vertical", "orthogonal", "rounded_orthogonal", "hv", "vh", "curved", "smooth_curve", "loop", "freeform"]
ARROW_TEMPLATES = ["straight_flow", "vertical_flow", "orthogonal_flow", "rounded_orthogonal_flow", "bezier_arc", "fanout_arc", "branch_arc", "skip_arc_no_arrow", "orthogonal_bus_no_arrow", "feedback_path", "feedback_loop", "boundary_flow"]
JUNCTION_TYPES = {"junction_point", "merge_bus", "multi_port_junction"}
SVI_REQUIRED_TOP = ["analysis_basis", "language_profile", "unknown_text_policy"]
STRICT_METADATA = ["replica_review_mode", "replica_stage", "region_strategy"]
ANCHOR_HINT = "use semantic side-ratio anchors like `node_id:right@0.50` instead of raw points"


def font_size_of(node: dict) -> float | None:
    for source in (node.get("style") or {}, node):
        if isinstance(source, dict):
            for key in ("font_size_pt", "font_size", "font_pt"):
                value = source.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    return float(value)
    return None


def estimated_width_pt(text: str, font_size_pt: float) -> float:
    width = 0.0
    for char in text:
        if ord(char) > 0x2E7F:  # CJK and fullwidth
            width += 1.0 * font_size_pt
        elif char in " .,:;'|!":
            width += 0.34 * font_size_pt
        else:
            width += 0.56 * font_size_pt
    return width

TEXT_FIT_HINT = (
    'single-line labels need `"single_line": true` (or text_fit "single_line") '
    "and a style font_size_pt that fits the box; math labels with word-like "
    'subscripts need type math_text with math_render_mode "fragments"'
)


def add(hints: list[dict], entity: str, wrong: str, fix: str) -> None:
    hints.append({"entity": entity, "wrong": wrong, "fix": fix})


def scan(doc: dict) -> list[dict]:
    hints: list[dict] = []
    metadata = doc.get("metadata") or {}

    arrow_plans = metadata.get("arrow_plan")
    if isinstance(arrow_plans, list):
        for plan in arrow_plans:
            if not isinstance(plan, dict):
                continue
            pid = str(plan.get("id", "?"))
            direction = str(plan.get("direction", "")).lower()
            if direction and direction not in ARROW_PLAN_DIRECTIONS:
                add(hints, f"arrow_plan[{pid}].direction",
                    f"`{direction}` is not in the validator vocabulary",
                    f"use one of {ARROW_PLAN_DIRECTIONS}")
            if direction in {"", "none", "unknown"} and not plan.get("certainty") == "uncertain":
                anchors = " ".join(str(plan.get(k, "")) for k in ("from_anchor", "to_anchor", "route_shape"))
                # geometric anchors already encode the direction; only flag when
                # neither vocabulary nor anchors express it
                if "@" not in anchors and not any(
                    word in anchors for word in ("horizontal", "vertical", "straight", "orthogonal", "loop", "curved")
                ):
                    add(hints, f"arrow_plan[{pid}].direction",
                        "missing/empty direction",
                        "record the visible flow direction explicitly, or express it via from_anchor/to_anchor side ratios plus route_shape; keep `unknown` only with certainty: uncertain")
            intent = str(plan.get("semantic_intent", "")).lower()
            if not intent:
                add(hints, f"arrow_plan[{pid}].semantic_intent",
                    "missing semantic_intent",
                    f"strict arrow plans require one of {SEMANTIC_INTENTS}")
            for key in ("from_anchor", "to_anchor"):
                anchor = str(plan.get(key, ""))
                if anchor and "@" not in anchor and not anchor.startswith(("boundary", "port")):
                    add(hints, f"arrow_plan[{pid}].{key}",
                        f"raw anchor `{anchor}`",
                        ANCHOR_HINT + " unless the source line is visibly free-floating (declare allow_free_endpoint)")
            gc = plan.get("geometry_contract")
            if gc is not None and not isinstance(gc, dict):
                add(hints, f"arrow_plan[{pid}].geometry_contract",
                    "not an object",
                    'use booleans such as "must_be_horizontal": true, "endpoint_must_touch": true, "tolerance_px": 3')

    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    node_types = {}
    for node in nodes:
        if isinstance(node, dict):
            node_types[str(node.get("id"))] = str(node.get("type", ""))

    edges = doc.get("edges") if isinstance(doc.get("edges"), list) else []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        eid = str(edge.get("id", "?"))
        edge_type = str(edge.get("type", ""))
        route = str(edge.get("route", "")).lower()
        if route and route not in ROUTE_SHAPES:
            add(hints, f"edge[{eid}].route",
                f"`{route}` is not in the validator vocabulary",
                f"use one of {ROUTE_SHAPES}")
        template = str(edge.get("arrow_template", "")).lower()
        if template and template not in ARROW_TEMPLATES:
            add(hints, f"edge[{eid}].arrow_template",
                f"`{template}` is not in the strict template vocabulary",
                f"use one of {ARROW_TEMPLATES}")
        for endpoint_key, node_key in (("from", "from"), ("to", "to")):
            target = str(edge.get(endpoint_key, ""))
            base = target.split("@")[0].strip()
            # "node_id:side" anchor spelling is legal; strip the side suffix too
            if ":" in base:
                base = base.split(":")[0].strip()
            if base and base not in node_types:
                add(hints, f"edge[{eid}].{endpoint_key}",
                    f"`{target}` does not resolve to a node id",
                    "bind to an existing node (optionally with side-ratio anchor `node:side@ratio`) or use from_point/to_point with allow_free_endpoint")
        if edge_type == "fork_connector":
            src = str(edge.get("from", "")).split("@")[0].split(":")[0].strip()
            if src and src in node_types and node_types.get(src) not in JUNCTION_TYPES:
                add(hints, f"edge[{eid}] (fork_connector)",
                    f"fans out from `{src}` ({node_types.get(src)})",
                    "fork/fan-out must originate from a junction_point / merge_bus / multi_port_junction; connect source -> junction first, then junction -> targets")
        if edge_type == "join_connector":
            dst = str(edge.get("to", "")).split("@")[0].split(":")[0].strip()
            if dst and dst in node_types and node_types.get(dst) not in JUNCTION_TYPES:
                add(hints, f"edge[{eid}] (join_connector)",
                    f"joins into `{dst}` ({node_types.get(dst)})",
                    "merge/fan-in must terminate at a junction_point / merge_bus / multi_port_junction; connect sources -> junction first, then junction -> destination")
        label = edge.get("label")
        if isinstance(label, str) and ("_" in label or "^" in label):
            add(hints, f"edge[{eid}].label",
                f"raw `_`/`^` in `{label}`",
                "edge labels must not carry literal sub/superscript markers; move math to a math_text node or reword")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id", "?"))
        text = node.get("text")
        if isinstance(text, str) and ("_" in text or "^" in text):
            ntype = str(node.get("type", ""))
            if ntype not in {"math_text", "math_vector", "math_formula_group", "formula_text_block"}:
                add(hints, f"node[{nid}] ({ntype})",
                    f"text contains `_`/`^` in `{text[:60]}`",
                    "use type math_text with math_render_mode fragments (underscore is legal fragment encoding only inside math components)")
        # strict validate treats an undeclared min_font as 55% of font size and fails
        style = node.get("style") if isinstance(node.get("style"), dict) else {}
        fs = style.get("font_size_pt") or node.get("font_size_pt")
        if isinstance(fs, (int, float)) and not style.get("min_font_size_pt"):
            add(hints, f"node[{nid}]",
                "no explicit min_font_size_pt (validator defaults to 55% of font size and fails strict)",
                f'set style min_font_size_pt to about {round(max(6.0, fs * 0.7), 1)} (>= 60% of font)')
        if str(node.get("type", "")) in {"text_block", "caption_block"}:
            # only single-line-prolonged text is a wrap risk; multi-line labels
            # (with \n or short text) legitimately omit a wrap policy
            if isinstance(text, str) and text and "\n" not in text and len(text) > 14 and node.get("w") and not (
                node.get("single_line") or node.get("no_wrap") or str(node.get("text_fit", "")) == "single_line"
            ):
                # shrink_to_fit boxes are allowed to auto-scale instead of wrapping
                style = node.get("style") if isinstance(node.get("style"), dict) else {}
                fit = str(node.get("text_fit", "") or style.get("text_fit", "")).lower()
                if fit != "shrink_to_fit":
                    font = font_size_of(node)
                    est = estimated_width_pt(text, font) if font else None
                    if est is None or est > float(node["w"]) * 0.75:
                        add(hints, f"node[{nid}]",
                            f"single-line text `{text[:40]}` in a {node.get('w')}w box without a wrap policy",
                            TEXT_FIT_HINT)

    return hints


def strict_contract_hints(doc: dict) -> list[dict]:
    hints: list[dict] = []
    metadata = doc.get("metadata") or {}
    svi = metadata.get("source_visual_inventory")
    if svi is None:
        add(hints, "metadata.source_visual_inventory", "missing",
            "strict mode requires it before first render: {analysis_basis, language_profile, do_not_translate, unknown_text_policy, per-region facts}")
    elif isinstance(svi, dict):
        for key in SVI_REQUIRED_TOP:
            if key not in svi:
                add(hints, f"source_visual_inventory.{key}", "missing", f"add `{key}` to the inventory root")
    if not metadata.get("region_plan"):
        add(hints, "metadata.region_plan", "missing",
            'strict region-first scenes need region_plan entries with source_bbox_px, review_focus, local_acceptance_checklist')
    for key in STRICT_METADATA:
        if not metadata.get(key):
            add(hints, f"metadata.{key}", "missing",
                f"strict replicas set {key} (e.g. {STRICT_METADATA})")
    return hints


def main() -> int:
    parser = argparse.ArgumentParser(description="Advisory schema hints with exact correct spellings.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--output-report", help="Optional JSON report path.")
    args = parser.parse_args()

    scene_path = Path(args.scene)
    try:
        doc = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"SCHEMA HINTS ERROR: cannot read {scene_path}: {exc}")
        return 2

    hints = scan(doc) + strict_contract_hints(doc)
    report = {"scene": str(scene_path), "hint_count": len(hints), "hints": hints}
    if args.output_report:
        out = Path(args.output_report).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if not hints:
        print("SCHEMA HINTS: no grammar issues found")
        return 0
    print(f"SCHEMA HINTS: {len(hints)} finding(s); each lists the exact correct spelling")
    for hint in hints:
        print(f"- {hint['entity']}: {hint['wrong']}\n    FIX: {hint['fix']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
