#!/usr/bin/env python3
"""Deterministic audit for text rendering defects in a scene.json.

Checks (see docs/updates/2026-08-30-review-taxonomy-gates.md):
- R1 raw underscore/caret: no literal `_` or `^` may reach rendered text unless the
  node declares `source_underscore_ok: true` (source visibly shows an underscore glyph).
- R2 math-like label on a non-math component: `g_tf`-style labels must use
  math_text / math_vector / formula components, not plain text blocks.
- R3 likely wrap on single-line labels: estimated text width must fit the box when
  the node declares single_line / no_wrap / nowrap / text_fit single_line.
- R4 text node outside its declared container.

Usage:
    python text_render_audit.py <scene.json> [--strict] [--output-report report.json]
Exit code 1 when any fail-level defect is present (R2 only fails under --strict).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TEXT_KEYS = {
    "text", "label", "title", "caption", "subtitle", "sub_text", "note",
    "annotation", "value", "prefix", "suffix", "content", "row_label",
    "entries", "rows", "labels", "legend_text", "legend_items", "items",
}
MATH_TYPES = {"math_text", "math_vector", "math_formula_group", "formula_text_block"}
TEXT_BOX_TYPES = {"text_block", "caption_block", "text_pill", "math_text", "math_vector"}
SUBSUP_RE = re.compile(r"[_^]")
MATH_LIKE_RE = re.compile(r"[A-Za-z]_[A-Za-z0-9]")
CJK_RE = re.compile(r"[\u2e80-\u9fff\uff00-\uffef]")


def is_math_entity(node: dict) -> bool:
    """math_text-style nodes encode subscripts as `L_adv`; the renderer splits them
    into editable fragments, so a literal underscore there is legal encoding."""
    if str(node.get("type", "")) in MATH_TYPES:
        return True
    if node.get("source_underscore_ok"):
        return True
    if node.get("math_render_mode") or str(node.get("text_fit", "")) == "math_label":
        return True
    style = node.get("style")
    return isinstance(style, dict) and bool(style.get("math"))


def collect_text(entity: object, key_path: list[str] | None = None) -> list[tuple[str, str]]:
    """Collect (key_path, text) pairs for strings stored under text-bearing keys."""
    key_path = key_path or []
    found: list[tuple[str, str]] = []
    if isinstance(entity, dict):
        for key, value in entity.items():
            child_path = key_path + [str(key)]
            if str(key) in TEXT_KEYS and isinstance(value, str):
                found.append((".".join(child_path[-3:]), value))
            else:
                found.extend(collect_text(value, child_path))
    elif isinstance(entity, list):
        for index, value in enumerate(entity):
            found.extend(collect_text(value, key_path))
    return found


def estimated_width_pt(text: str, font_size_pt: float) -> float:
    width = 0.0
    for char in text:
        if CJK_RE.match(char):
            width += 1.0 * font_size_pt
        elif char in " .,:;'|!":
            width += 0.34 * font_size_pt
        else:
            width += 0.56 * font_size_pt
    return width


def font_size_of(node: dict) -> float | None:
    for source in (node.get("style") or {}, node):
        if isinstance(source, dict):
            for key in ("font_size_pt", "font_size", "font_pt"):
                value = source.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    return float(value)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit raw subscripts, math labels, wrapping, and container overflow.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--strict", action="store_true", help="Fail on math-like labels on non-math components.")
    parser.add_argument("--output-report", help="Optional JSON report path.")
    args = parser.parse_args()

    scene_path = Path(args.scene)
    try:
        doc = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"TEXT RENDER AUDIT ERROR: cannot read {scene_path}: {exc}")
        return 2

    defects: list[dict] = []

    def add(rule: str, severity: str, entity_id: str, detail: str, evidence: str) -> None:
        defects.append({
            "rule": rule,
            "severity": severity,
            "entity_id": entity_id,
            "detail": detail,
            "evidence": evidence[:160],
        })

    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    node_by_id = {str(n.get("id")): n for n in nodes if isinstance(n, dict) and n.get("id")}

    edges = doc.get("edges") if isinstance(doc.get("edges"), list) else []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_id = f"edge:{edge.get('id', '?')}"
        for key in ("label", "text"):
            value = edge.get(key)
            if isinstance(value, str) and SUBSUP_RE.search(value) and not edge.get("source_underscore_ok"):
                add("R1_raw_subsup", "fail", edge_id,
                    f"edge label contains raw `_`/`^` ({key})", value)

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "?"))
        math_entity = is_math_entity(node)
        for path, text in collect_text(node):
            if SUBSUP_RE.search(text) and not math_entity:
                add("R1_raw_subsup", "fail", node_id,
                    f"rendered text contains raw `_`/`^` ({path})", text)
            if (not args.strict):
                continue
            node_type = str(node.get("type", ""))
            if math_entity:
                continue
            if MATH_LIKE_RE.search(text):
                add("R2_math_label_on_plain_text", "fail", node_id,
                    f"math-like label should use math_text/fragments, found on `{node_type}` ({path})", text)

    # R3 likely wrap on single-line labels
    for node in nodes:
        if not isinstance(node, dict):
            continue
        declares_single = any(bool(node.get(key)) for key in ("single_line", "no_wrap", "nowrap")) or \
            str(node.get("text_fit", "")).lower() == "single_line"
        if not declares_single:
            continue
        width = node.get("w")
        font = font_size_of(node)
        if not isinstance(width, (int, float)) or width <= 0 or font is None:
            continue
        page = doc.get("page") or {}
        units = str(page.get("units", "px"))
        box_pt = float(width) * (72.0 if units == "in" else 0.75)
        # px-mode boxes are authoring px; treat 1 px ≈ 0.75 pt for estimation
        for path, text in collect_text(node):
            for line in text.split("\n"):
                estimate = estimated_width_pt(line, font)
                if estimate > box_pt * 1.05:
                    add("R3_likely_wrap", "fail", str(node.get("id", "?")),
                        f"single-line label likely wraps: est {estimate:.0f}pt > box {box_pt:.0f}pt ({path})", line)

    # R4 text node outside declared container
    for node in nodes:
        if not isinstance(node, dict):
            continue
        container_id = node.get("container_id")
        if not container_id or str(node.get("type", "")) not in TEXT_BOX_TYPES:
            continue
        parent = node_by_id.get(str(container_id))
        if not isinstance(parent, dict):
            add("R4_unknown_container", "fail", str(node.get("id", "?")),
                f"container_id `{container_id}` does not resolve to a node", "")
            continue
        try:
            nx, ny = float(node["x"]), float(node["y"])
            nw, nh = float(node["w"]), float(node["h"])
            px_, py, pw, ph = float(parent["x"]), float(parent["y"]), float(parent["w"]), float(parent["h"])
        except (KeyError, TypeError, ValueError):
            continue
        if nx < px_ - 1 or ny < py - 1 or nx + nw > px_ + pw + 1 or ny + nh > py + ph + 1:
            # labels legitimately ride on container edges often enough that only
            # strict mode treats this as a blocking defect
            add("R4_text_outside_container", "warn" if not args.strict else "fail", str(node.get("id", "?")),
                f"text node bbox escapes container `{container_id}`", "")

    failures = [d for d in defects if d["severity"] == "fail"]
    report = {
        "scene": str(scene_path),
        "strict": bool(args.strict),
        "status": "fail" if failures else "pass",
        "defects": defects,
        "defect_count": len(defects),
        "fail_count": len(failures),
    }
    if args.output_report:
        report_path = Path(args.output_report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if failures:
        print("TEXT RENDER AUDIT FAILED")
        for defect in failures:
            print(f"- [{defect['rule']}] {defect['entity_id']}: {defect['detail']} | {defect['evidence']}")
        return 1
    print(f"TEXT RENDER AUDIT PASSED ({len(defects)} non-fatal findings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
