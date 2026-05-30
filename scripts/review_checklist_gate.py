#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


VALID_STATUS = {"pass", "fail", "uncertain"}
VALID_CERTAINTY = {"certain", "inferred", "uncertain"}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def as_list(value: object, name: str, failures: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        failures.append(f"`{name}` must be an array.")
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            failures.append(f"`{name}` item {index} must be an object.")
        else:
            result.append(item)
    return result


def string_list(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def validate_items(items: list[dict[str, Any]], kind: str, failures: list[str], warnings: list[str]) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(items):
        item_id = str(item.get("id", "")).strip()
        label = item_id or f"{kind}[{index}]"
        if not item_id:
            failures.append(f"{kind}[{index}] is missing id.")
        elif item_id in ids:
            failures.append(f"{kind} duplicate id `{item_id}`.")
        ids.add(item_id)

        status = str(item.get("status", "")).strip().lower()
        certainty = str(item.get("certainty", "")).strip().lower()
        if status not in VALID_STATUS:
            failures.append(f"{label} has invalid status `{item.get('status')}`.")
        if certainty and certainty not in VALID_CERTAINTY:
            failures.append(f"{label} has invalid certainty `{item.get('certainty')}`.")
        if not item.get("focus_region"):
            warnings.append(f"{label} has no focus_region.")
        if not item.get("replica_status"):
            warnings.append(f"{label} has no replica_status.")
        if kind == "topology_checklist" and not item.get("source_fact"):
            failures.append(f"{label} is missing source_fact.")
        if kind in {"visual_checklist", "fidelity_checklist"} and not item.get("source_expectation"):
            failures.append(f"{label} is missing source_expectation.")
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate review checklist coverage and finding references.")
    parser.add_argument("findings", help="Path to review_findings.json")
    parser.add_argument("--manifest", help="Optional review_manifest.json; used to verify local original path.")
    parser.add_argument("--require-failed-refs", action="store_true", help="Require non-acceptable findings to cite checklist_refs.")
    parser.add_argument("--allow-missing-local-original", action="store_true", help="Do not fail when original_path is missing or non-local.")
    parser.add_argument("--output-report", help="Optional JSON report path.")
    args = parser.parse_args()

    findings_path = Path(args.findings).resolve()
    doc = load_json(findings_path)
    failures: list[str] = []
    warnings: list[str] = []

    topology = as_list(doc.get("topology_checklist"), "topology_checklist", failures)
    visual = as_list(doc.get("visual_checklist"), "visual_checklist", failures)
    fidelity_raw = doc.get("fidelity_checklist", [])
    fidelity = as_list(fidelity_raw, "fidelity_checklist", failures) if fidelity_raw is not None else []
    if not topology:
        failures.append("topology_checklist is empty.")
    if not visual:
        failures.append("visual_checklist is empty.")

    ids = validate_items(topology, "topology_checklist", failures, warnings)
    ids |= validate_items(visual, "visual_checklist", failures, warnings)
    ids |= validate_items(fidelity, "fidelity_checklist", failures, warnings)
    failed_ids = {
        str(item.get("id", "")).strip()
        for item in topology + visual + fidelity
        if str(item.get("status", "")).strip().lower() == "fail" and str(item.get("id", "")).strip()
    }

    findings = doc.get("findings")
    if not isinstance(findings, list):
        failures.append("findings must be an array.")
        findings = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            failures.append(f"findings[{index}] must be an object.")
            continue
        finding_id = str(finding.get("id", "")).strip() or f"findings[{index}]"
        refs = string_list(finding.get("checklist_refs"))
        for ref in refs:
            if ref not in ids:
                failures.append(f"{finding_id} references unknown checklist id `{ref}`.")
        severity = str(finding.get("severity", "")).strip().lower()
        if args.require_failed_refs and severity in {"blocking", "important", "general"} and failed_ids and not refs:
            failures.append(f"{finding_id} must cite checklist_refs.")

    reviewer_inputs = doc.get("reviewer_inputs") if isinstance(doc.get("reviewer_inputs"), dict) else {}
    original_path = reviewer_inputs.get("original_path") if isinstance(reviewer_inputs, dict) else None
    if not original_path and args.manifest:
        manifest = load_json(Path(args.manifest).resolve())
        manifest_inputs = manifest.get("reviewer_inputs")
        if isinstance(manifest_inputs, dict):
            original_path = manifest_inputs.get("original_path") or manifest_inputs.get("original")
        original_path = original_path or manifest.get("original_path")
    if not args.allow_missing_local_original:
        if not original_path:
            failures.append("Missing reviewer original_path; strict review requires a local source image path.")
        elif str(original_path).startswith("conversation_attachment:"):
            failures.append("original_path points to a chat attachment, not a staged local source image.")
        elif not Path(str(original_path)).exists():
            failures.append(f"original_path does not exist locally: {original_path}")

    report = {
        "findings_path": str(findings_path),
        "status": "fail" if failures else "pass",
        "failures": failures,
        "warnings": warnings,
        "topology_count": len(topology),
        "visual_count": len(visual),
        "fidelity_count": len(fidelity),
        "failed_checklist_ids": sorted(failed_ids),
    }
    if args.output_report:
        output_path = Path(args.output_report).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if failures:
        print("REVIEW CHECKLIST GATE FAILED")
        for failure in failures:
            print(f"- {failure}")
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"- {warning}")
        return 1

    print("REVIEW CHECKLIST GATE PASSED")
    print(f"- topology checklist items: {len(topology)}")
    print(f"- visual checklist items: {len(visual)}")
    print(f"- fidelity checklist items: {len(fidelity)}")
    print(f"- failed checklist ids: {len(failed_ids)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
