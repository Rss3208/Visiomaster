#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def prompt_reference_text(skill_root: Path, rel_path: str | None) -> str:
    if not rel_path:
        return ""
    ref_path = (skill_root / rel_path).resolve()
    if not ref_path.exists():
        return ""
    return ref_path.read_text(encoding="utf-8").strip()


def recover_reviewer_inputs(rebuild_brief: dict[str, Any], rebuild_brief_path: Path) -> dict[str, str | None]:
    reviewer_inputs = rebuild_brief.get("reviewer_inputs", {})
    if not isinstance(reviewer_inputs, dict):
        reviewer_inputs = {}
    original_path = reviewer_inputs.get("original_path")
    replica_path = reviewer_inputs.get("replica_path")
    if original_path or replica_path:
        return {
            "original_path": str(original_path) if original_path else None,
            "replica_path": str(replica_path) if replica_path else None,
        }

    candidate_paths = [
        rebuild_brief.get("source_findings_path"),
        rebuild_brief.get("source_manifest_path"),
        rebuild_brief.get("review_manifest_path"),
    ]
    for candidate in candidate_paths:
        if not candidate:
            continue
        candidate_path = Path(str(candidate))
        if not candidate_path.is_absolute():
            candidate_path = (rebuild_brief_path.parent / candidate_path).resolve()
        if not candidate_path.exists():
            continue
        try:
            candidate_doc = load_json(candidate_path)
        except Exception:
            continue
        nested_inputs = candidate_doc.get("reviewer_inputs")
        if isinstance(nested_inputs, dict):
            nested_original = nested_inputs.get("original_path")
            nested_replica = nested_inputs.get("replica_path")
            if nested_original or nested_replica:
                return {
                    "original_path": str(nested_original) if nested_original else None,
                    "replica_path": str(nested_replica) if nested_replica else None,
                }
        root_original = candidate_doc.get("original_path")
        root_replica = candidate_doc.get("replica_path")
        if root_original or root_replica:
            return {
                "original_path": str(root_original) if root_original else None,
                "replica_path": str(root_replica) if root_replica else None,
            }
    return {
        "original_path": None,
        "replica_path": None,
    }


def finding_section(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "- No structured findings were provided.\n"
    rows: list[str] = []
    for finding in findings:
        finding_id = str(finding.get("id", "UNNAMED")).strip() or "UNNAMED"
        severity = str(finding.get("severity", "unspecified"))
        summary = str(finding.get("summary", "")).strip()
        visible_diff = str(finding.get("visible_diff", "")).strip()
        expected_visible_change = str(finding.get("expected_visible_change", "")).strip()
        focus_regions = normalize_string_list(finding.get("focus_regions"))
        likely_scene_ids = normalize_string_list(finding.get("likely_scene_ids"))
        checklist_refs = normalize_string_list(finding.get("checklist_refs"))
        rows.append(f"- `{finding_id}` [{severity}] {summary}")
        if focus_regions:
            rows.append(f"  - focus_regions: {', '.join(focus_regions)}")
        if likely_scene_ids:
            rows.append(f"  - likely_scene_ids: {', '.join(likely_scene_ids)}")
        if checklist_refs:
            rows.append(f"  - checklist_refs: {', '.join(checklist_refs)}")
        if visible_diff:
            rows.append(f"  - visible_diff: {visible_diff}")
        if expected_visible_change:
            rows.append(f"  - expected_visible_change: {expected_visible_change}")
    return "\n".join(rows) + "\n"


def checklist_section(title: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return f"## {title}\n\n- none recorded\n"
    rows = [f"## {title}", ""]
    for item in items:
        item_id = str(item.get("id", "UNNAMED")).strip() or "UNNAMED"
        status = str(item.get("status", "unspecified"))
        focus_region = str(item.get("focus_region", "")).strip()
        source_fact = str(item.get("source_fact", item.get("source_expectation", ""))).strip()
        replica_status = str(item.get("replica_status", "")).strip()
        arrow_plan_id = str(item.get("arrow_plan_id", "")).strip()
        rows.append(f"- `{item_id}` [{status}] {source_fact}")
        if arrow_plan_id:
            rows.append(f"  - arrow_plan_id: `{arrow_plan_id}`")
        if focus_region:
            rows.append(f"  - focus_region: {focus_region}")
        if replica_status:
            rows.append(f"  - replica_status: {replica_status}")
    return "\n".join(rows) + "\n"


def arrow_repair_targets_section(targets: list[dict[str, Any]]) -> str:
    if not targets:
        return "## Arrow Plan Repair Targets\n\n- none recorded\n"
    rows = ["## Arrow Plan Repair Targets", ""]
    for target in targets:
        arrow_id = str(target.get("arrow_plan_id", "UNNAMED")).strip() or "UNNAMED"
        scene_edges = normalize_string_list(target.get("scene_edge_ids"))
        motif_bindings = target.get("motif_bindings", [])
        editable_fields = normalize_string_list(target.get("editable_scene_fields"))
        rows.append(f"- `{arrow_id}`")
        if scene_edges:
            rows.append(f"  - scene_edge_ids: {', '.join(scene_edges)}")
        if isinstance(motif_bindings, list) and motif_bindings:
            binding_labels = []
            for binding in motif_bindings:
                if isinstance(binding, dict):
                    node_id = binding.get("node_id", "<node>")
                    motif_edge_id = binding.get("motif_edge_id", "<motif_edge>")
                    binding_labels.append(f"{node_id}.{motif_edge_id}")
            if binding_labels:
                rows.append(f"  - motif_bindings: {', '.join(binding_labels)}")
        if editable_fields:
            rows.append(f"  - editable_fields: {', '.join(editable_fields)}")
        plan = target.get("plan")
        if isinstance(plan, dict):
            expected = plan.get("source_fact") or f"{plan.get('from_visual_object', plan.get('from'))} -> {plan.get('to_visual_object', plan.get('to'))}"
            rows.append(f"  - expected_source_arrow: {expected}")
    return "\n".join(rows) + "\n"


def region_scores_section(region_scores: list[dict[str, Any]]) -> str:
    if not region_scores:
        return "## Region Scores\n\n- none recorded\n"
    rows = ["## Region Scores", ""]
    for item in region_scores:
        if not isinstance(item, dict):
            continue
        region_id = str(item.get("region_id", "region")).strip() or "region"
        scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        blocking = normalize_string_list(item.get("blocking_findings"))
        focus = str(item.get("review_focus", "")).strip()
        rows.append(f"- `{region_id}`")
        if focus:
            rows.append(f"  - review_focus: {focus}")
        if scores:
            compact_scores = ", ".join(f"{key}={value}" for key, value in scores.items())
            rows.append(f"  - scores: {compact_scores}")
        if blocking:
            rows.append(f"  - blocking_findings: {', '.join(blocking)}")
    return "\n".join(rows) + "\n"


def checklist_validation_section(validation: dict[str, Any]) -> str:
    if not validation:
        return "## Checklist Validation\n\n- none recorded\n"
    rows = ["## Checklist Validation", ""]
    failed_ids = normalize_string_list(validation.get("failed_ids"))
    errors = normalize_string_list(validation.get("errors"))
    warnings = normalize_string_list(validation.get("warnings"))
    required = validation.get("required")
    rows.append(f"- required: {required}" if required is not None else "- required: not recorded")
    rows.append(f"- failed_ids: {', '.join(failed_ids)}" if failed_ids else "- failed_ids: none")
    if errors:
        rows.append("- errors:")
        rows.extend(f"  - {item}" for item in errors[:12])
    if warnings:
        rows.append("- warnings:")
        rows.extend(f"  - {item}" for item in warnings[:12])
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a round-specific packet for full-scene LLM regeneration from a scene_rebuild_brief.json."
    )
    parser.add_argument("rebuild_brief", help="Path to scene_rebuild_brief.json")
    parser.add_argument("--output-dir", help="Output directory. Defaults to the rebuild brief directory.")
    parser.add_argument("--packet-output", help="Optional explicit JSON packet output path.")
    parser.add_argument("--prompt-output", help="Optional explicit Markdown prompt output path.")
    parser.add_argument(
        "--allow-missing-reviewer-inputs",
        action="store_true",
        help="Allow packet generation even when original/replica paths cannot be recovered. Intended only for legacy artifact inspection.",
    )
    args = parser.parse_args()

    rebuild_brief_path = Path(args.rebuild_brief).resolve()
    rebuild_brief = load_json(rebuild_brief_path)
    skill_root = Path(__file__).resolve().parents[1]

    figure_id = str(rebuild_brief.get("figure_id") or rebuild_brief_path.stem.replace("_scene_rebuild_brief", "")).strip() or "figure"
    round_index = rebuild_brief.get("round")
    output_dir = Path(args.output_dir).resolve() if args.output_dir else rebuild_brief_path.parent
    packet_path = Path(args.packet_output).resolve() if args.packet_output else output_dir / f"{figure_id}_scene_regeneration_packet.json"
    prompt_path = Path(args.prompt_output).resolve() if args.prompt_output else output_dir / f"{figure_id}_full_scene_regeneration_prompt.md"

    reviewer_inputs = recover_reviewer_inputs(rebuild_brief, rebuild_brief_path)
    original_path = reviewer_inputs.get("original_path")
    replica_path = reviewer_inputs.get("replica_path")
    if (not original_path or not replica_path) and not args.allow_missing_reviewer_inputs:
        raise ValueError(
            "Could not recover both reviewer input paths from the rebuild brief, findings, or manifest. "
            "Generate the rebuild brief from the current review bundle, or use --allow-missing-reviewer-inputs only for legacy inspection."
        )

    regeneration_prompt_reference = rebuild_brief.get("regeneration_prompt_reference")
    review_prompt_reference = rebuild_brief.get("review_prompt_reference")
    findings_digest = rebuild_brief.get("findings_digest", [])
    if not isinstance(findings_digest, list):
        findings_digest = []
    topology_checklist = rebuild_brief.get("topology_checklist", [])
    if not isinstance(topology_checklist, list):
        topology_checklist = []
    visual_checklist = rebuild_brief.get("visual_checklist", [])
    if not isinstance(visual_checklist, list):
        visual_checklist = []
    fidelity_checklist = rebuild_brief.get("fidelity_checklist", [])
    if not isinstance(fidelity_checklist, list):
        fidelity_checklist = []
    region_scores = rebuild_brief.get("region_scores", [])
    if not isinstance(region_scores, list):
        region_scores = []
    checklist_validation = rebuild_brief.get("checklist_validation", {})
    if not isinstance(checklist_validation, dict):
        checklist_validation = {}
    arrow_plan_repair_targets = rebuild_brief.get("arrow_plan_repair_targets", [])
    if not isinstance(arrow_plan_repair_targets, list):
        arrow_plan_repair_targets = []

    packet = {
        "schema_version": "0.2",
        "figure_id": figure_id,
        "round": round_index,
        "mode": "rebuild_full_scene",
        "rebuild_brief_path": str(rebuild_brief_path),
        "source_findings_path": rebuild_brief.get("source_findings_path"),
        "prior_scene_path": rebuild_brief.get("prior_scene_path"),
        "reviewer_inputs": {
            "original_path": original_path,
            "replica_path": replica_path,
        },
        "authoring_policy": rebuild_brief.get("authoring_policy"),
        "prior_scene_policy": rebuild_brief.get("prior_scene_policy"),
        "required_rebuild_rules": rebuild_brief.get("required_rebuild_rules", []),
        "rebuild_focus_regions": rebuild_brief.get("rebuild_focus_regions", []),
        "topology_checklist": topology_checklist,
        "visual_checklist": visual_checklist,
        "fidelity_checklist": fidelity_checklist,
        "region_scores": region_scores,
        "checklist_validation": checklist_validation,
        "findings_digest": findings_digest,
        "arrow_plan_repair_targets": arrow_plan_repair_targets,
        "fixed_prompt_references": {
            "review_prompt_reference": review_prompt_reference,
            "regeneration_prompt_reference": regeneration_prompt_reference,
        },
        "supporting_references": {
            "scene_schema": str((skill_root / "references" / "scene-schema.md").resolve()),
            "review_contract": str((skill_root / "references" / "review-contract.md").resolve()),
            "renderer_effective_fields": str((skill_root / "references" / "renderer-effective-fields.json").resolve()),
            "skill_file": str((skill_root / "SKILL.md").resolve()),
        },
        "execution_contract": [
            "Use the original image and current replica image as the primary visual evidence.",
            "Use structured review findings to author a brand-new full scene.",
            "Use topology_checklist, visual_checklist, fidelity_checklist, region_scores, and arrow_plan_repair_targets as explicit regeneration inputs.",
            "For cited arrow ids, repair the mapped scene_edge_ids or motif_bindings rather than relying on broad natural-language arrow notes.",
            "Do not patch or copy prior-scene geometry.",
            "Render the new scene and pass it through the no-op gate before claiming a new round.",
        ],
    }
    write_json(packet_path, packet)

    prompt_lines = [
        f"# Full-Scene Regeneration Packet: {figure_id}",
        "",
        f"- rebuild_brief: `{rebuild_brief_path}`",
        f"- original image: `{original_path}`" if original_path else "- original image: `MISSING`",
        f"- current replica: `{replica_path}`" if replica_path else "- current replica: `MISSING`",
        (
            f"- prior scene (failure evidence only): `{rebuild_brief.get('prior_scene_path')}`"
            if rebuild_brief.get("prior_scene_path")
            else "- prior scene (failure evidence only): `none`"
        ),
        f"- findings source: `{rebuild_brief.get('source_findings_path')}`",
        "",
        "## Round-Specific Constraints",
        "",
    ]

    required_rules = rebuild_brief.get("required_rebuild_rules", [])
    if isinstance(required_rules, list) and required_rules:
        for rule in required_rules:
            prompt_lines.append(f"- {rule}")
    else:
        prompt_lines.append("- Rebuild the full scene from source plus review findings.")

    focus_regions = normalize_string_list(rebuild_brief.get("rebuild_focus_regions"))
    prompt_lines.extend(
        [
            "",
            "## Focus Regions",
            "",
            f"- {', '.join(focus_regions)}" if focus_regions else "- none recorded",
            "",
            "## Findings Digest",
            "",
            finding_section([item for item in findings_digest if isinstance(item, dict)]).rstrip(),
            "",
            checklist_section("Topology Checklist", [item for item in topology_checklist if isinstance(item, dict)]).rstrip(),
            "",
            checklist_section("Visual Checklist", [item for item in visual_checklist if isinstance(item, dict)]).rstrip(),
            "",
            checklist_section("Fidelity Checklist", [item for item in fidelity_checklist if isinstance(item, dict)]).rstrip(),
            "",
            region_scores_section([item for item in region_scores if isinstance(item, dict)]).rstrip(),
            "",
            checklist_validation_section(checklist_validation).rstrip(),
            "",
            arrow_repair_targets_section([item for item in arrow_plan_repair_targets if isinstance(item, dict)]).rstrip(),
            "",
            "## Supporting References",
            "",
            f"- scene schema: `{packet['supporting_references']['scene_schema']}`",
            f"- review contract: `{packet['supporting_references']['review_contract']}`",
            f"- renderer effective fields: `{packet['supporting_references']['renderer_effective_fields']}`",
            "",
            "## Fixed Regeneration Prompt",
            "",
        ]
    )

    fixed_prompt_text = prompt_reference_text(skill_root, str(regeneration_prompt_reference) if regeneration_prompt_reference else None)
    if fixed_prompt_text:
        prompt_lines.append(fixed_prompt_text)
    else:
        prompt_lines.append("Missing regeneration prompt reference.")

    prompt_lines.extend(
        [
            "",
            "## Output Requirement",
            "",
            "Return a brand-new `scene.json` for the next round. Do not return patch instructions, repair notes, or metadata-only edits.",
            "",
        ]
    )
    write_text(prompt_path, "\n".join(prompt_lines))

    print(f"Wrote regeneration packet: {packet_path}")
    print(f"Wrote regeneration prompt: {prompt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
