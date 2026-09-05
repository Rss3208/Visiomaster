#!/usr/bin/env python3
"""Deterministic audit for the raster-paste policy in a scene.json.

Policy (SKILL.md rule 91): only photographic / complex-bitmap / otherwise-unreadable
source content may be delivered as raster tiles, and every tile must be registered.
Grid, matrix, cell-stack, legend-sample and simple-icon content is always redrawable
and must never ship as a raster tile.

Checks:
- R1 every raster node carries a valid `justification` and `source_bbox_px`.
- R2 redrawable-class raster tiles (grid/matrix/cell/token/legend/icon in id/role/type)
  fail regardless of justification.
- R3 raster area share over 8% warns; over 15% fails (strict mode).

Usage:
    python raster_policy_audit.py <scene.json> [--strict] [--output-report report.json]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

VALID_JUSTIFICATIONS = {"photographic", "complex_bitmap", "source_unreadable_otherwise"}
REDRAWABLE_RE = re.compile(r"grid|matrix|cell|token|legend|icon|strip|checker", re.IGNORECASE)
RASTER_TYPE_HINTS = ("image", "raster", "photo", "bitmap")


def is_raster(node: dict) -> bool:
    node_type = str(node.get("type", "")).lower()
    if node.get("raster") is True:
        return True
    return any(hint in node_type for hint in RASTER_TYPE_HINTS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit raster tile registration and area share.")
    parser.add_argument("scene", help="Path to scene.json")
    parser.add_argument("--strict", action="store_true", help="Fail when raster area share exceeds 15%.")
    parser.add_argument("--output-report", help="Optional JSON report path.")
    args = parser.parse_args()

    scene_path = Path(args.scene)
    try:
        doc = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"RASTER POLICY AUDIT ERROR: cannot read {scene_path}: {exc}")
        return 2

    defects: list[dict] = []

    def add(rule: str, severity: str, entity_id: str, detail: str) -> None:
        defects.append({"rule": rule, "severity": severity, "entity_id": entity_id, "detail": detail})

    page = doc.get("page") or {}
    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    raster_nodes = [n for n in nodes if isinstance(n, dict) and is_raster(n)]

    for node in raster_nodes:
        node_id = str(node.get("id", "?"))
        justification = node.get("justification")
        if justification not in VALID_JUSTIFICATIONS:
            add("R1_missing_or_invalid_justification", "fail", node_id,
                f"raster tile needs justification in {sorted(VALID_JUSTIFICATIONS)}, got `{justification}`")
        if not node.get("source_bbox_px"):
            add("R1_missing_source_bbox", "fail", node_id,
                "raster tile must record source_bbox_px for review pairing")
        searchable = " ".join([
            str(node.get("id", "")), str(node.get("role", "")), str(node.get("type", "")),
            str((node.get("style") or {}).get("role", "")) if isinstance(node.get("style"), dict) else "",
        ])
        if REDRAWABLE_RE.search(searchable):
            add("R2_redrawable_class_raster", "fail", node_id,
                f"grid/matrix/cell/token/legend/icon-class content must be redrawn as editable components (`{searchable.strip()}`)")

    page_area = None
    try:
        width = float(page["width"])
        height = float(page["height"])
        if width > 0 and height > 0:
            page_area = width * height
    except (KeyError, TypeError, ValueError):
        page_area = None

    raster_area = 0.0
    measured = 0
    for node in raster_nodes:
        try:
            raster_area += float(node["w"]) * float(node["h"])
            measured += 1
        except (KeyError, TypeError, ValueError):
            continue

    share = None
    if page_area and page_area > 0 and measured == len(raster_nodes) and len(raster_nodes) > 0:
        share = raster_area / page_area
        if share > 0.15:
            add("R3_raster_area_share", "fail" if args.strict else "warn", "<page>",
                f"raster area share {share:.1%} exceeds 15% budget")
        elif share > 0.08:
            add("R3_raster_area_share", "warn", "<page>",
                f"raster area share {share:.1%} exceeds 8% budget; delivery notes must justify")

    failures = [d for d in defects if d["severity"] == "fail"]
    report = {
        "scene": str(scene_path),
        "strict": bool(args.strict),
        "status": "fail" if failures else "pass",
        "raster_node_count": len(raster_nodes),
        "raster_area_share": share,
        "defects": defects,
        "fail_count": len(failures),
    }
    if args.output_report:
        report_path = Path(args.output_report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if failures:
        print("RASTER POLICY AUDIT FAILED")
        for defect in failures:
            print(f"- [{defect['rule']}] {defect['entity_id']}: {defect['detail']}")
        return 1
    share_text = f"{share:.1%}" if share is not None else "n/a"
    print(f"RASTER POLICY AUDIT PASSED ({len(raster_nodes)} raster nodes, area share {share_text}, {len(defects)} warnings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
