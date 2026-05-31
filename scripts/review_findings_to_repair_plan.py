#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scene_validate import arrow_plan_items, edge_arrow_plan_id


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def normalize_string_list(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def finding_digest(finding: dict[str, Any]) -> dict[str, Any]:
    focus_regions = normalize_string_list(finding.get("focus_regions"))
    if not focus_regions:
        focus_regions = normalize_string_list(finding.get("region"))
    likely_scene_ids = normalize_string_list(finding.get("likely_scene_ids"))
    if not likely_scene_ids:
        likely_scene_ids = normalize_string_list(finding.get("target_ids"))
    return {
        "id": str(finding.get("id", "")).strip() or "UNNAMED",
        "severity": finding.get("severity"),
        "summary": finding.get("summary"),
        "visible_diff": finding.get("visible_diff"),
        "source_appearance": finding.get("source_appearance"),
        "replica_appearance": finding.get("replica_appearance"),
        "impact_on_fidelity": finding.get("impact_on_fidelity"),
        "focus_regions": focus_regions,
        "likely_scene_ids": likely_scene_ids,
        "checklist_refs": normalize_string_list(finding.get("checklist_refs")),
        "expected_visible_change": finding.get("expected_visible_change"),
        "legacy_patch_fields": {
            "region": finding.get("region"),
            "target_ids": normalize_string_list(finding.get("target_ids")),
            "patch_kind": finding.get("patch_kind"),
        },
    }


def node_motif_edges(node: dict[str, Any]) -> list[dict[str, Any]]:
    value = node.get("motif_edges")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def collect_arrow_repair_targets(
    scene: dict[str, Any] | None,
    checklist_report: dict[str, Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(scene, dict):
        return []
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    plans = arrow_plan_items(metadata)
    if not isinstance(plans, list):
        return []

    plan_by_id = {
        str(plan.get("id", "")).strip(): plan
        for plan in plans
        if isinstance(plan, dict) and str(plan.get("id", "")).strip()
    }
    edges = scene.get("edges", []) if isinstance(scene.get("edges"), list) else []
    scene_edges_by_plan: dict[str, list[str]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        plan_id = edge_arrow_plan_id(edge)
        if plan_id:
            scene_edges_by_plan.setdefault(plan_id, []).append(str(edge.get("id", "<missing-id>")))

    motif_edges_by_plan: dict[str, list[dict[str, Any]]] = {}
    nodes = scene.get("nodes", []) if isinstance(scene.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "<missing-node>"))
        node_type = str(node.get("type", ""))
        for motif_edge in node_motif_edges(node):
            plan_id = edge_arrow_plan_id(motif_edge)
            if not plan_id:
                continue
            motif_edges_by_plan.setdefault(plan_id, []).append(
                {
                    "node_id": node_id,
                    "node_type": node_type,
                    "motif_edge_id": motif_edge.get("id"),
                    "editable_fields": [
                        "motif_edges",
                        "operator_x_ratio",
                        "operator_y_ratio",
                        "grid_x_ratio",
                        "grid_y_ratio",
                        "grid_w_ratio",
                        "grid_h_ratio",
                        "label",
                        "label_position",
                        "label_offset_x_in",
                        "label_offset_y_in",
                    ],
                }
            )

    referenced_ids: set[str] = set()
    for item in checklist_report.get("topology_checklist", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        arrow_id = str(item.get("arrow_plan_id", "")).strip() or (item_id if item_id in plan_by_id else "")
        status = str(item.get("status", "")).lower()
        if arrow_id and status in {"fail", "uncertain"}:
            referenced_ids.add(arrow_id)
    for finding in findings:
        for ref in normalize_string_list(finding.get("checklist_refs")):
            if ref in plan_by_id:
                referenced_ids.add(ref)

    targets: list[dict[str, Any]] = []
    for plan_id in sorted(referenced_ids):
        plan = plan_by_id.get(plan_id)
        if not plan:
            continue
        targets.append(
            {
                "arrow_plan_id": plan_id,
                "plan": plan,
                "scene_edge_ids": scene_edges_by_plan.get(plan_id, []),
                "motif_bindings": motif_edges_by_plan.get(plan_id, []),
                "editable_scene_fields": [
                    "from",
                    "to",
                    "from_point",
                    "to_point",
                    "points",
                    "route",
                    "curve_mode",
                    "style.line",
                    "style.end_arrow",
                    "allow_diagonal",
                    "allow_cross_container",
                ],
                "repair_hint": "Use this mapping as the concrete scene entry point for the cited checklist failure; do not rely only on natural-language arrow comments.",
            }
        )
    return targets


def extract_reviewer_inputs(findings_doc: dict[str, Any], manifest_doc: dict[str, Any] | None) -> dict[str, str | None]:
    findings_inputs = findings_doc.get("reviewer_inputs")
    if isinstance(findings_inputs, dict):
        original = findings_inputs.get("original_path")
        replica = findings_inputs.get("replica_path")
        if original or replica:
            return {
                "original_path": str(original) if original else None,
                "replica_path": str(replica) if replica else None,
            }
    if manifest_doc:
        reviewer_inputs = manifest_doc.get("reviewer_inputs")
        if isinstance(reviewer_inputs, dict):
            original = reviewer_inputs.get("original_path")
            replica = reviewer_inputs.get("replica_path")
            if original or replica:
                return {
                    "original_path": str(original) if original else None,
                    "replica_path": str(replica) if replica else None,
                }
        original = manifest_doc.get("original_path")
        replica = manifest_doc.get("replica_path")
        if original or replica:
            return {
                "original_path": str(original) if original else None,
                "replica_path": str(replica) if replica else None,
            }
    return {
        "original_path": None,
        "replica_path": None,
    }


def derive_focus_regions(findings: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for finding in findings:
        regions = normalize_string_list(finding.get("focus_regions"))
        if not regions:
            regions = normalize_string_list(finding.get("region"))
        for region in regions:
            if region not in seen:
                ordered.append(region)
                seen.add(region)
    return ordered


def legacy_schema_warnings(findings: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_id = str(finding.get("id", "")).strip() or "UNNAMED"
        if finding.get("patch_kind") is not None:
            warnings.append(
                f"{finding_id}: legacy patch-oriented finding detected; patch_kind is ignored because post-review flow now always rebuilds the full scene."
            )
        if finding.get("target_ids") is not None:
            warnings.append(
                f"{finding_id}: legacy target_ids were preserved only as likely_scene_ids failure evidence. They are not patch targets anymore."
            )
        if finding.get("region") is not None and not finding.get("focus_regions"):
            warnings.append(
                f"{finding_id}: legacy region field was mapped into focus_regions for the rebuild brief."
            )
    return warnings


def normalize_checklist(value: object, name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"review_findings.json `{name}` must be an array when present.")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"`{name}` item {index} must be an object.")
        result.append(item)
    return result


def checklist_ids(items: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for item in items:
        item_id = str(item.get("id", "")).strip()
        if item_id:
            ids.add(item_id)
    return ids


def validate_checklists(findings_doc: dict[str, Any], findings: list[dict[str, Any]], require: bool) -> dict[str, Any]:
    topology = normalize_checklist(findings_doc.get("topology_checklist"), "topology_checklist")
    visual = normalize_checklist(findings_doc.get("visual_checklist"), "visual_checklist")
    fidelity = normalize_checklist(findings_doc.get("fidelity_checklist"), "fidelity_checklist")
    errors: list[str] = []
    warnings: list[str] = []

    if require and not topology:
        errors.append("Missing required `topology_checklist` array.")
    if require and not visual:
        errors.append("Missing required `visual_checklist` array.")

    valid_status = {"pass", "fail", "uncertain"}
    valid_certainty = {"certain", "inferred", "uncertain"}
    all_ids = checklist_ids(topology) | checklist_ids(visual) | checklist_ids(fidelity)
    failed_ids: set[str] = set()

    for name, items in (("topology_checklist", topology), ("visual_checklist", visual), ("fidelity_checklist", fidelity)):
        seen: set[str] = set()
        for index, item in enumerate(items):
            item_id = str(item.get("id", "")).strip()
            if not item_id:
                errors.append(f"`{name}` item {index} is missing `id`.")
            elif item_id in seen:
                errors.append(f"`{name}` duplicate id `{item_id}`.")
            seen.add(item_id)

            status = str(item.get("status", "")).strip().lower()
            certainty = str(item.get("certainty", "")).strip().lower()
            if status not in valid_status:
                errors.append(f"`{name}` item `{item_id or index}` has invalid status `{item.get('status')}`.")
            if certainty and certainty not in valid_certainty:
                errors.append(f"`{name}` item `{item_id or index}` has invalid certainty `{item.get('certainty')}`.")
            if status == "fail" and item_id:
                failed_ids.add(item_id)

            if name == "topology_checklist":
                if not item.get("source_fact"):
                    errors.append(f"`{name}` item `{item_id or index}` is missing `source_fact`.")
            else:
                if not item.get("source_expectation"):
                    errors.append(f"`{name}` item `{item_id or index}` is missing `source_expectation`.")
            if not item.get("focus_region"):
                warnings.append(f"`{name}` item `{item_id or index}` has no focus_region.")
            if not item.get("replica_status"):
                warnings.append(f"`{name}` item `{item_id or index}` has no replica_status.")

    for finding in findings:
        finding_id = str(finding.get("id", "")).strip() or "UNNAMED"
        refs = normalize_string_list(finding.get("checklist_refs"))
        for ref in refs:
            if ref not in all_ids:
                errors.append(f"Finding `{finding_id}` references unknown checklist id `{ref}`.")
        severity = str(finding.get("severity", "")).strip().lower()
        if require and severity in {"blocking", "important", "general"} and failed_ids and not refs:
            warnings.append(f"Finding `{finding_id}` does not cite checklist_refs.")

    if require and errors:
        raise ValueError("Checklist validation failed:\n- " + "\n- ".join(errors))

    return {
        "topology_checklist": topology,
        "visual_checklist": visual,
        "fidelity_checklist": fidelity,
        "region_scores": findings_doc.get("region_scores") if isinstance(findings_doc.get("region_scores"), list) else [],
        "checklist_validation": {
            "required": require,
            "errors": errors,
            "warnings": warnings,
            "failed_ids": sorted(failed_ids),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert review findings into a full-scene rebuild brief. "
        "This script keeps the historical filename for compatibility, but it no longer produces patch tasks."
    )
    parser.add_argument("findings", help="Path to review_findings.json")
    parser.add_argument("--scene", help="Optional prior scene.json path; recorded as failure evidence only.")
    parser.add_argument("--manifest", help="Optional review_manifest.json to recover reviewer input paths.")
    parser.add_argument(
        "--require-checklists",
        action="store_true",
        help="Fail unless topology_checklist and visual_checklist are present and all checklist arrays are well-formed.",
    )
    parser.add_argument("--output", required=True, help="Output scene_rebuild_brief.json path")
    args = parser.parse_args()

    findings_path = Path(args.findings).resolve()
    findings_doc = load_json(findings_path)
    manifest_doc = load_json(Path(args.manifest).resolve()) if args.manifest else None

    findings_raw = findings_doc.get("findings", [])
    if not isinstance(findings_raw, list):
        raise ValueError("review_findings.json must contain a `findings` array.")
    findings = [finding for finding in findings_raw if isinstance(finding, dict)]
    reviewer_inputs = extract_reviewer_inputs(findings_doc, manifest_doc)
    focus_regions = derive_focus_regions(findings)
    schema_warnings = legacy_schema_warnings(findings)
    checklist_report = validate_checklists(findings_doc, findings, args.require_checklists)
    prior_scene = load_json(Path(args.scene).resolve()) if args.scene else None
    arrow_repair_targets = collect_arrow_repair_targets(prior_scene, checklist_report, findings)

    rebuild_brief = {
        "schema_version": "0.2",
        "figure_id": findings_doc.get("figure_id"),
        "round": findings_doc.get("round"),
        "mode": "rebuild_full_scene",
        "source_findings_path": str(findings_path),
        "source_manifest_path": str(Path(args.manifest).resolve()) if args.manifest else None,
        "prior_scene_path": str(Path(args.scene).resolve()) if args.scene else None,
        "reviewer_inputs": reviewer_inputs,
        "authoring_policy": "fresh_full_scene_from_source_and_review",
        "prior_scene_policy": "do_not_patch_or_copy_prior_scene_geometry",
        "review_prompt_reference": "references/reviewer-two-image-prompt.md",
        "regeneration_prompt_reference": "references/full-scene-regeneration-prompt.md",
        "next_step_script": "scripts/prepare_regeneration_packet.py",
        "overall_verdict": findings_doc.get("overall_verdict", "needs_rebuild"),
        "rebuild_required": bool(findings_doc.get("rebuild_required", True)),
        "prior_scene_usage": [
            "failure_evidence_only",
            "component_vocabulary_reference_only",
            "do_not_copy_coordinates_or_routes",
        ],
        "required_rebuild_rules": [
            "Author a brand-new full scene from the source image and review findings.",
            "Do not patch or incrementally edit the prior scene geometry.",
            "Use the prior scene only as negative evidence about what looked wrong.",
            "Preserve source language and visible formulas exactly.",
            "Rebuild the whole page even when the visible defect looks local.",
        ],
        "rebuild_focus_regions": focus_regions,
        "topology_checklist": checklist_report["topology_checklist"],
        "visual_checklist": checklist_report["visual_checklist"],
        "fidelity_checklist": checklist_report["fidelity_checklist"],
        "region_scores": checklist_report["region_scores"],
        "checklist_validation": checklist_report["checklist_validation"],
        "findings_digest": [finding_digest(finding) for finding in findings],
        "arrow_plan_repair_targets": arrow_repair_targets,
        "llm_regeneration_inputs": [
            "original source image",
            "current replica image",
            "structured review findings",
            "scene schema and supported component vocabulary",
        ],
        "next_step": {
            "description": "Prepare a round-specific full-scene regeneration packet for the next LLM authoring pass.",
            "command_hint": "python scripts\\prepare_regeneration_packet.py <scene_rebuild_brief.json> --output-dir <round_dir>",
        },
        "success_criteria": [
            "The new scene is authored fresh rather than patched from the previous round.",
            "The rerendered PNG visibly changes in the reported defect areas.",
            "The rerender survives no-op gate checks.",
        ],
    }
    if schema_warnings:
        rebuild_brief["schema_warnings"] = schema_warnings

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rebuild_brief, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote scene rebuild brief: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
