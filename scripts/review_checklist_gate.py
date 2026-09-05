#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


VALID_STATUS = {"pass", "fail", "uncertain"}
VALID_REGION_SCORE = {"pass", "fail", "uncertain", "not_reviewed", "not_applicable"}
VALID_CERTAINTY = {"certain", "inferred", "uncertain"}
REGION_SCORE_KEYS = {
    "arrow_direction",
    "endpoint_connection",
    "line_geometry",
    "formula_fidelity",
    "text_overlap",
    "unexpected_grid_or_dash",
}
STRICT_DENSE_REQUIRED_CROP_TYPES = {
    "arrow_dense",
    "formula_dense",
    "rotated_text",
    "small_text",
    "legend",
    "paper_3d",
    "output_label",
}
DEFECT_CLASSES = {"A", "B", "C", "D", "E", "F", "G"}


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


def crop_tokens_from_text(value: object) -> set[str]:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return set()
    tokens = {token for token in text.split("_") if token}
    joined = text
    result: set[str] = set()
    if "arrow_dense" in joined or ("arrow" in tokens and "dense" in tokens):
        result.add("arrow_dense")
    if "formula_dense" in joined or ("formula" in tokens and "dense" in tokens):
        result.add("formula_dense")
    if "rotated_text" in joined or ("rotated" in tokens and "text" in tokens):
        result.add("rotated_text")
    if "small_text" in joined or ("small" in tokens and "text" in tokens):
        result.add("small_text")
    if "legend" in tokens or "legend" in joined:
        result.add("legend")
    if "paper_3d" in joined or "3d" in tokens or "cuboid" in tokens or "slab" in tokens:
        result.add("paper_3d")
    if "output_label" in joined or ("output" in tokens and "label" in tokens):
        result.add("output_label")
    return result


def region_score_crop_types(item: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    categories = item.get("categories")
    if isinstance(categories, list):
        for category in categories:
            found |= crop_tokens_from_text(category)
    for key in ("region_id", "review_focus", "focus_region", "crop_type", "review_crop_type"):
        found |= crop_tokens_from_text(item.get(key))
    return found


def manifest_required_crop_types(manifest: dict[str, Any] | None, required: set[str]) -> set[str]:
    if not manifest:
        return set()
    found: set[str] = set()
    for list_key in ("region_scores", "regions"):
        rows = manifest.get(list_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            found |= region_score_crop_types(row)
            if "region" in row:
                found |= crop_tokens_from_text(row.get("region"))
    return found & required


def validate_required_crop_reviews(
    findings_doc: dict[str, Any],
    manifest_doc: dict[str, Any] | None,
    required: set[str],
    failures: list[str],
    warnings: list[str],
) -> None:
    if not required:
        return
    rows = findings_doc.get("region_scores")
    if not isinstance(rows, list):
        failures.append("Required crop review cannot be checked because `region_scores` is missing.")
        return

    expected = manifest_required_crop_types(manifest_doc, required) if manifest_doc else set()
    if not expected:
        expected = required
        if not manifest_doc:
            warnings.append("No manifest was provided; enforcing all requested crop types against findings region_scores.")

    covered: set[str] = set()
    for item in rows:
        if isinstance(item, dict):
            covered |= region_score_crop_types(item)
    missing = sorted(expected - covered)
    if missing:
        failures.append(
            "Final strict dense review is missing region_scores coverage for required crop type(s): "
            + ", ".join(missing)
            + "."
        )


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


def validate_sweep(
    findings: list[dict[str, Any]],
    failures: list[str],
    warnings: list[str],
) -> None:
    """Class-sweep completeness: every finding must name its defect class and sweep the page.

    SKILL.md rule 94: a reviewer who finds one instance must answer "how many more of
    the same class exist page-wide". Findings without `similar_instance_count` leave
    the repair stage unable to run a class-wide fix.
    """
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            continue
        finding_id = str(finding.get("id", "")).strip() or f"findings[{index}]"
        class_id = str(finding.get("class_id", "")).strip().upper()
        if not class_id:
            failures.append(f"{finding_id} is missing class_id (A-G defect taxonomy).")
            continue
        if class_id not in DEFECT_CLASSES:
            failures.append(f"{finding_id} has invalid class_id `{class_id}` (expected one of {sorted(DEFECT_CLASSES)}).")
        count = finding.get("similar_instance_count")
        if count is None or isinstance(count, bool) or not isinstance(count, int):
            failures.append(
                f"{finding_id} is missing integer `similar_instance_count`; the reviewer must sweep the page for the same class."
            )
            continue
        locations = finding.get("similar_locations")
        if count > 1 and (not isinstance(locations, list) or not locations):
            failures.append(
                f"{finding_id} reports {count} same-class instances but `similar_locations` is empty."
            )


def validate_region_scores(
    value: object,
    failures: list[str],
    warnings: list[str],
    *,
    final: bool = False,
) -> tuple[int, list[str]]:
    if value is None:
        if final:
            failures.append("Final review requires `region_scores`.")
        return 0, []
    if not isinstance(value, list):
        failures.append("`region_scores` must be an array when provided.")
        return 0, []
    failed_regions: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            failures.append(f"region_scores[{index}] must be an object.")
            continue
        region_id = str(item.get("region_id", "")).strip()
        label = region_id or f"region_scores[{index}]"
        if not region_id:
            failures.append(f"region_scores[{index}] is missing region_id.")
        elif region_id in seen:
            failures.append(f"region_scores duplicate region_id `{region_id}`.")
        seen.add(region_id)

        scores = item.get("scores")
        if not isinstance(scores, dict):
            failures.append(f"{label} scores must be an object.")
            continue
        region_failed = False
        for key in REGION_SCORE_KEYS:
            if key not in scores:
                warnings.append(f"{label} scores has no `{key}` entry.")
                continue
            status = str(scores.get(key, "")).strip().lower()
            if status not in VALID_REGION_SCORE:
                failures.append(f"{label} scores.{key} has invalid value `{scores.get(key)}`.")
            if status == "fail":
                region_failed = True
            if final and status == "not_reviewed":
                failures.append(f"{label} scores.{key} is not_reviewed in final mode.")
        blocking = item.get("blocking_findings", [])
        if blocking is None:
            blocking = []
        if not isinstance(blocking, list):
            failures.append(f"{label} blocking_findings must be an array.")
            blocking = []
        if region_failed and not blocking:
            failures.append(f"{label} has a fail score but no blocking_findings.")
        if final and region_failed:
            failures.append(f"{label} has a fail score in final mode.")
        if region_failed and region_id:
            failed_regions.append(region_id)
    return len(value), sorted(set(failed_regions))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate review checklist coverage and finding references.")
    parser.add_argument("findings", help="Path to review_findings.json")
    parser.add_argument("--manifest", help="Optional review_manifest.json; used to verify local original path.")
    parser.add_argument("--require-failed-refs", action="store_true", help="Require non-acceptable findings to cite checklist_refs.")
    parser.add_argument(
        "--require-sweep",
        action="store_true",
        help="Require every finding to carry class_id (A-G) and a page-wide same-class sweep (similar_instance_count / similar_locations).",
    )
    parser.add_argument("--final", action="store_true", help="Require region_scores and fail if any critical region score is fail or not_reviewed.")
    parser.add_argument(
        "--strict-dense",
        action="store_true",
        help="In final mode, require strict/dense crop type coverage for arrow/formula/text/legend/3D/output details.",
    )
    parser.add_argument(
        "--require-crop-types",
        nargs="*",
        help="Explicit crop types that must appear in final region_scores, for example arrow_dense formula_dense legend.",
    )
    parser.add_argument("--allow-missing-local-original", action="store_true", help="Do not fail when original_path is missing or non-local.")
    parser.add_argument("--output-report", help="Optional JSON report path.")
    args = parser.parse_args()

    findings_path = Path(args.findings).resolve()
    doc = load_json(findings_path)
    manifest_doc = load_json(Path(args.manifest).resolve()) if args.manifest else None
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
    region_score_count, failed_regions = validate_region_scores(doc.get("region_scores"), failures, warnings, final=args.final)
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

    if args.require_sweep:
        validate_sweep(findings, failures, warnings)

    required_crop_types: set[str] = set()
    if args.strict_dense and args.final:
        required_crop_types |= STRICT_DENSE_REQUIRED_CROP_TYPES
    if args.require_crop_types is not None:
        required_crop_types |= {str(item).strip().lower().replace("-", "_") for item in args.require_crop_types if str(item).strip()}
    if required_crop_types:
        validate_required_crop_reviews(doc, manifest_doc, required_crop_types, failures, warnings)

    reviewer_inputs = doc.get("reviewer_inputs") if isinstance(doc.get("reviewer_inputs"), dict) else {}
    original_path = reviewer_inputs.get("original_path") if isinstance(reviewer_inputs, dict) else None
    if not original_path and args.manifest:
        manifest = manifest_doc or {}
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
        "region_score_count": region_score_count,
        "failed_checklist_ids": sorted(failed_ids),
        "failed_regions": failed_regions,
        "required_crop_types": sorted(required_crop_types),
        "sweep_required": bool(args.require_sweep),
        "finding_count": len(findings),
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
    print(f"- region score items: {region_score_count}")
    print(f"- failed checklist ids: {len(failed_ids)}")
    print(f"- failed regions: {len(failed_regions)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
