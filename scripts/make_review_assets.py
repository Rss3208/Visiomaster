#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from scene_validate import STRICT_REQUIRED_REGION_CATEGORIES, arrow_plan_items, exact_mode_from_metadata, region_categories


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "msyh.ttc", "simhei.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def fit_image(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    fitted = image.copy().convert("RGB")
    fitted.thumbnail(box, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", box, "white")
    canvas.paste(fitted, ((box[0] - fitted.width) // 2, (box[1] - fitted.height) // 2))
    return canvas


def crop_box(width: int, height: int, spec: str) -> tuple[int, int, int, int]:
    named = {
        "global": (0.0, 0.0, 1.0, 1.0),
        "input": (0.0, 0.0, 0.36, 1.0),
        "core": (0.28, 0.0, 0.72, 1.0),
        "output": (0.64, 0.0, 1.0, 1.0),
        "left": (0.0, 0.0, 0.36, 1.0),
        "center": (0.28, 0.0, 0.72, 1.0),
        "right": (0.64, 0.0, 1.0, 1.0),
        "top": (0.0, 0.0, 1.0, 0.42),
        "middle": (0.0, 0.28, 1.0, 0.72),
        "bottom": (0.0, 0.58, 1.0, 1.0),
        "arrow_dense": (0.25, 0.15, 0.82, 0.86),
        "small_text": (0.35, 0.0, 1.0, 1.0),
        "caption": (0.0, 0.78, 1.0, 1.0),
        "ports_boundary": (0.0, 0.08, 1.0, 0.92),
        "formula_ports": (0.18, 0.10, 1.0, 0.96),
    }
    if spec in named:
        left, top, right, bottom = named[spec]
    else:
        parts = [float(part) for part in spec.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Crop spec must be a named crop or l,t,r,b ratios: {spec}")
        left, top, right, bottom = parts
    return (
        max(0, min(width, round(left * width))),
        max(0, min(height, round(top * height))),
        max(0, min(width, round(right * width))),
        max(0, min(height, round(bottom * height))),
    )


def bbox_to_box(width: int, height: int, value: object, *, default_pixels: bool = False) -> tuple[int, int, int, int] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        left, top, right, bottom = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not default_pixels and all(0.0 <= item <= 1.0 for item in (left, top, right, bottom)):
        return crop_box(width, height, f"{left},{top},{right},{bottom}")
    return (
        max(0, min(width, round(left))),
        max(0, min(height, round(top))),
        max(0, min(width, round(right))),
        max(0, min(height, round(bottom))),
    )


def slug(value: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", str(value).strip())
    return safe.strip("_")[:48] or "region"


def scene_region_pairs(
    scene_path: Path,
    original: Image.Image,
    replica: Image.Image,
) -> tuple[dict[str, object], list[tuple[str, set[str], tuple[int, int, int, int], tuple[int, int, int, int]]]]:
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    page = scene.get("page", {}) if isinstance(scene.get("page"), dict) else {}
    plan = metadata.get("region_plan", metadata.get("source_region_plan", metadata.get("source_regions")))
    if not isinstance(plan, list):
        return scene, []
    page_w = float(page.get("width", original.width) or original.width)
    page_h = float(page.get("height", original.height) or original.height)
    nodes = {node.get("id"): node for node in scene.get("nodes", []) if isinstance(node, dict) and node.get("id")}

    pairs: list[tuple[str, set[str], tuple[int, int, int, int], tuple[int, int, int, int]]] = []
    for index, region in enumerate(plan, 1):
        if not isinstance(region, dict):
            continue
        name = str(region.get("id", region.get("name", f"region_{index}")))
        categories = region_categories(region)
        source_box = bbox_to_box(
            original.width,
            original.height,
            region.get("source_bbox_px", region.get("source_bbox", region.get("bbox_px"))),
            default_pixels=True,
        )
        target_value = region.get("target_bbox_px", region.get("replica_bbox_px"))
        target_box = bbox_to_box(replica.width, replica.height, target_value, default_pixels=True)
        if target_box is None:
            target_scene = region.get("target_bbox", region.get("target_bbox_in", region.get("scene_bbox")))
            if isinstance(target_scene, list) and len(target_scene) == 4:
                try:
                    scale_x = replica.width / page_w if page_w else 1.0
                    scale_y = replica.height / page_h if page_h else 1.0
                    target_box = (
                        max(0, min(replica.width, round(float(target_scene[0]) * scale_x))),
                        max(0, min(replica.height, round(float(target_scene[1]) * scale_y))),
                        max(0, min(replica.width, round(float(target_scene[2]) * scale_x))),
                        max(0, min(replica.height, round(float(target_scene[3]) * scale_y))),
                    )
                except (TypeError, ValueError):
                    target_box = None
        if target_box is None:
            node_id = region.get("container_id", region.get("node_id"))
            node = nodes.get(node_id)
            if isinstance(node, dict) and all(isinstance(node.get(key), (int, float)) for key in ("x", "y", "w", "h")):
                scale_x = replica.width / page_w if page_w else 1.0
                scale_y = replica.height / page_h if page_h else 1.0
                target_box = (
                    max(0, min(replica.width, round(float(node["x"]) * scale_x))),
                    max(0, min(replica.height, round(float(node["y"]) * scale_y))),
                    max(0, min(replica.width, round((float(node["x"]) + float(node["w"])) * scale_x))),
                    max(0, min(replica.height, round((float(node["y"]) + float(node["h"])) * scale_y))),
                )
        if source_box and target_box and source_box[2] > source_box[0] and source_box[3] > source_box[1] and target_box[2] > target_box[0] and target_box[3] > target_box[1]:
            pairs.append((slug(name), categories, source_box, target_box))
    return scene, pairs


def make_pair(
    original: Image.Image,
    replica: Image.Image,
    output: Path,
    title: str,
    max_side_width: int,
) -> None:
    font = load_font(22)
    small = load_font(16)
    side_h = max(original.height, replica.height)
    scale = min(1.0, max_side_width / max(original.width, replica.width))
    box = (round(max(original.width, replica.width) * scale), round(side_h * scale))
    left = fit_image(original, box)
    right = fit_image(replica, box)
    pad = 18
    header = 54
    canvas = Image.new("RGB", (box[0] * 2 + pad * 3, box[1] + header + pad), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 10), f"{title} | original", fill="black", font=font)
    draw.text((pad * 2 + box[0], 10), "replica", fill="black", font=font)
    draw.text((pad, 34), f"{original.width}x{original.height}", fill="#555555", font=small)
    draw.text((pad * 2 + box[0], 34), f"{replica.width}x{replica.height}", fill="#555555", font=small)
    canvas.paste(left, (pad, header))
    canvas.paste(right, (pad * 2 + box[0], header))
    draw.line((pad + box[0] + pad // 2, header, pad + box[0] + pad // 2, header + box[1]), fill="#999999", width=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def make_overlay(
    original: Image.Image,
    replica: Image.Image,
    output: Path,
    title: str,
    max_side_width: int,
    alpha: float,
) -> None:
    font = load_font(22)
    small = load_font(16)
    source = original.convert("RGB")
    aligned_replica = replica.convert("RGB").resize(source.size, Image.Resampling.LANCZOS)
    overlay = Image.blend(source, aligned_replica, max(0.0, min(1.0, alpha)))

    scale = min(1.0, max_side_width / max(overlay.width, 1))
    box = (round(overlay.width * scale), round(overlay.height * scale))
    fitted = fit_image(overlay, box)

    pad = 18
    header = 54
    canvas = Image.new("RGB", (box[0] + pad * 2, box[1] + header + pad), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 10), f"{title} | overlay", fill="black", font=font)
    draw.text((pad, 34), f"source {1.0 - alpha:.2f} + replica {alpha:.2f}", fill="#555555", font=small)
    canvas.paste(fitted, (pad, header))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def arrow_plan_topology_checklist(scene: dict[str, object] | None) -> list[dict[str, object]]:
    if not isinstance(scene, dict):
        return []
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    plans = arrow_plan_items(metadata)
    if not isinstance(plans, list):
        return []
    items: list[dict[str, object]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        plan_id = str(plan.get("id", "")).strip()
        if not plan_id:
            continue
        status = str(plan.get("status", "")).lower()
        certainty = str(plan.get("certainty", "certain")).lower()
        if status in {"optional", "skipped", "not_visible"} or certainty in {"uncertain", "unknown"}:
            default_status = "uncertain"
        else:
            default_status = "uncertain"
        source_fact = str(plan.get("source_fact", "")).strip()
        if not source_fact:
            source = plan.get("from_visual_object", plan.get("from", plan.get("source", "source")))
            target = plan.get("to_visual_object", plan.get("to", plan.get("target", "target")))
            route = plan.get("route_shape", "route")
            arrowhead = plan.get("arrowhead", "arrowhead")
            source_fact = f"{plan_id}: {source} -> {target}, route={route}, arrowhead={arrowhead}"
        focus_region = str(plan.get("source_region", plan.get("focus_region", plan.get("region", "arrow_dense")))).strip() or "arrow_dense"
        items.append(
            {
                "id": plan_id,
                "kind": "arrow_plan",
                "arrow_plan_id": plan_id,
                "focus_region": focus_region,
                "source_fact": source_fact,
                "expected_from": plan.get("from_visual_object", plan.get("from")),
                "expected_from_anchor": plan.get("from_anchor_description", plan.get("from_anchor")),
                "expected_to": plan.get("to_visual_object", plan.get("to")),
                "expected_to_anchor": plan.get("to_anchor_description", plan.get("to_anchor")),
                "expected_route_shape": plan.get("route_shape"),
                "expected_line_style": plan.get("line_style"),
                "expected_arrowhead": plan.get("arrowhead"),
                "semantic_intent": plan.get("semantic_intent"),
                "source_bbox_px": plan.get("source_bbox_px"),
                "status": default_status,
                "certainty": certainty if certainty in {"certain", "inferred", "uncertain"} else "certain",
                "replica_status": "not_reviewed",
            }
        )
    return items


def visual_grammar_checklist(scene: dict[str, object] | None) -> list[dict[str, object]]:
    if not isinstance(scene, dict):
        return []
    metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
    inventory = metadata.get("visual_grammar_inventory")
    items: list[dict[str, object]] = []
    counter = 1
    if isinstance(inventory, dict):
        for category in ("shape_facts", "cell_facts", "line_facts", "symbol_facts", "wave_facts", "text_facts"):
            facts = inventory.get(category)
            if not isinstance(facts, list):
                continue
            for fact in facts:
                if not str(fact).strip():
                    continue
                items.append(
                    {
                        "id": f"V{counter:03d}",
                        "kind": "visual_grammar",
                        "category": category,
                        "focus_region": "source_visual_grammar",
                        "source_fact": str(fact),
                        "source_expectation": str(fact),
                        "replica_status": "not_reviewed",
                        "repair_hint": "Preserve this source visual fact through component parameters, not by normalizing to a default template.",
                        "status": "uncertain",
                        "certainty": "certain",
                    }
                )
                counter += 1
    nodes = scene.get("nodes", []) if isinstance(scene.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type", ""))
        if node_type not in {"primitive_group", "shape_cluster", "symbol_group", "cell_strip", "micro_grid", "polyline_wave"}:
            continue
        facts = node.get("must_match_facts")
        if not isinstance(facts, list) or not facts:
            facts = [f"{node.get('id', '<node>')} should preserve its source visual facts"]
        for fact in facts:
            items.append(
                {
                    "id": f"V{counter:03d}",
                    "kind": "primitive_node",
                    "node_id": node.get("id"),
                    "node_type": node_type,
                    "focus_region": node.get("source_region_id", node.get("container_id", "local_primitive")),
                    "source_bbox_px": node.get("source_bbox_px", node.get("source_bbox")),
                    "source_fact": str(fact),
                    "source_expectation": str(fact),
                    "replica_status": "not_reviewed",
                    "repair_hint": "If mismatched, change the primitive parameters or renderer capability before touching final-scene coordinates.",
                    "status": "uncertain",
                    "certainty": "certain",
                }
            )
            counter += 1
    return items


def review_bundle_payload(
    *,
    figure_id: str,
    round_index: int,
    scene_path: str | None,
    scene: dict[str, object] | None,
    original_path: str,
    replica_path: str,
    pair_paths: list[str],
    overlay_paths: list[str],
    regions: list[tuple[str, set[str], tuple[int, int, int, int], tuple[int, int, int, int]]],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    region_rows = [
        {
            "region": name,
            "categories": sorted(categories),
            "source_bbox_px": list(source_box),
            "target_bbox_px": list(target_box),
        }
        for name, categories, source_box, target_box in regions
    ]
    topology_checklist = arrow_plan_topology_checklist(scene)
    visual_checklist = visual_grammar_checklist(scene)
    manifest = {
        "schema_version": "0.1",
        "figure_id": figure_id,
        "round": round_index,
        "scene_path": scene_path,
        "original_path": original_path,
        "replica_path": replica_path,
        "reviewer_inputs": {
            "original_path": original_path,
            "replica_path": replica_path,
        },
        "debug_pair_paths": pair_paths,
        "debug_overlay_paths": overlay_paths,
        "regions": region_rows,
        "arrow_plan_checklist": topology_checklist,
        "visual_checklist": visual_checklist,
        "debug_asset_policy": {
            "global_pair": "off_by_default; generate only with --include-global-pair for human navigation or audit records",
            "crops": "targeted_only; generate named crops with --crops or scene regions with --region-crops all",
            "overlays": "off_by_default; generate only with --include-overlays when checking alignment drift",
            "reviewer_prompt": "send original_path and replica_path only; optionally send a small number of targeted local crops when a specific detail is under review",
        },
        "review_only_inputs": [
            "original_path",
            "replica_path",
        ],
        "review_prompt_reference": "references/reviewer-two-image-prompt.md",
        "required_finding_fields": [
            "id",
            "severity",
            "summary",
            "visible_diff",
            "source_appearance",
            "replica_appearance",
            "impact_on_fidelity",
            "focus_regions",
            "expected_visible_change",
        ],
        "post_review_action": "rebuild_full_scene",
        "review_rule": "The reviewer should compare only original_path and replica_path. Pair/crop/overlay files are debug aids for the author and should not be given to the reviewer.",
    }
    findings_template = {
        "schema_version": "0.1",
        "figure_id": figure_id,
        "round": round_index,
        "overall_verdict": "needs_rebuild",
        "rebuild_required": True,
        "review_prompt_reference": "references/reviewer-two-image-prompt.md",
        "scene_path": scene_path,
        "review_manifest_path": None,
        "reviewer_inputs": {
            "original_path": original_path,
            "replica_path": replica_path,
        },
        "findings": [],
        "topology_checklist": topology_checklist,
        "visual_checklist": visual_checklist,
    }
    rebuild_template = {
        "schema_version": "0.1",
        "figure_id": figure_id,
        "round": round_index,
        "source_findings_path": None,
        "mode": "rebuild_full_scene",
        "authoring_policy": "fresh_full_scene_from_source_and_review",
        "prior_scene_policy": "do_not_patch_or_copy_prior_scene_geometry",
        "review_prompt_reference": "references/reviewer-two-image-prompt.md",
        "regeneration_prompt_reference": "references/full-scene-regeneration-prompt.md",
        "next_step_script": "scripts/prepare_regeneration_packet.py",
        "reviewer_inputs": {
            "original_path": original_path,
            "replica_path": replica_path,
        },
        "findings_digest": [],
        "arrow_plan_repair_targets": [],
        "visual_grammar_repair_targets": [],
    }
    return manifest, findings_template, rebuild_template


def main() -> int:
    parser = argparse.ArgumentParser(description="Create review manifests and optional debug pairs/crops for visual QA.")
    parser.add_argument("--original", required=True)
    parser.add_argument("--replica", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--round", type=int, default=1, help="Review round number recorded in the optional review bundle.")
    parser.add_argument("--scene", help="Optional scene.json; when provided, metadata.region_plan generates source-bound review crops.")
    parser.add_argument(
        "--crops",
        nargs="*",
        default=[],
        help="Optional named/ratio crops to generate as side-by-side debug pairs. Default: none.",
    )
    parser.add_argument(
        "--region-crops",
        choices=("none", "all"),
        default="none",
        help="Generate side-by-side crop pairs from scene metadata.region_plan. Default: none.",
    )
    parser.add_argument(
        "--include-global-pair",
        action="store_true",
        help="Generate a global side-by-side pair for human navigation. Default: off; reviewers should use original+replica.",
    )
    parser.add_argument(
        "--include-overlays",
        action="store_true",
        help="Generate overlay debug images for alignment drift checks. Default: off.",
    )
    parser.add_argument("--max-side-width", type=int, default=1100)
    parser.add_argument("--overlay-alpha", type=float, default=0.50)
    parser.add_argument(
        "--write-review-bundle",
        action="store_true",
        help="Write review manifest and blank findings/repair templates alongside the generated assets.",
    )
    args = parser.parse_args()

    original = Image.open(args.original).convert("RGB")
    replica = Image.open(args.replica).convert("RGB")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pair_paths: list[str] = []
    overlay_paths: list[str] = []
    scene: dict[str, object] | None = None
    region_pairs: list[tuple[str, set[str], tuple[int, int, int, int], tuple[int, int, int, int]]] = []
    if args.scene:
        scene, region_pairs = scene_region_pairs(Path(args.scene), original, replica)
        metadata = scene.get("metadata", {}) if isinstance(scene.get("metadata"), dict) else {}
        if exact_mode_from_metadata(metadata):
            required_categories = list(STRICT_REQUIRED_REGION_CATEGORIES)
            nodes = scene.get("nodes", []) if isinstance(scene.get("nodes"), list) else []
            caption_required = any(
                (
                    isinstance(node, dict)
                    and (
                        node.get("type") == "caption_block"
                        or (
                            isinstance(node.get("text"), str)
                            and len(str(node.get("text", "")).strip()) >= 8
                            and any(token in str(node.get("text", "")) for token in ("Fig.", "Figure", "图"))
                        )
                    )
                )
                for node in nodes
            )
            if caption_required:
                required_categories.append("caption")
            coverage: set[str] = set()
            for _, categories, _, _ in region_pairs:
                coverage.update(categories)
            missing = [category for category in required_categories if category not in coverage]
            if missing:
                raise ValueError(
                    "Exact review assets require source-bound region_plan coverage for "
                    + ", ".join(missing)
                    + ". Provide scene metadata.region_plan with source and target bboxes before QA."
                )

    if args.include_global_pair:
        pair_output = out_dir / f"{args.id}_pair_global.png"
        make_pair(original, replica, pair_output, args.id, args.max_side_width)
        pair_paths.append(str(pair_output.resolve()))
        if args.include_overlays:
            overlay_output = out_dir / f"{args.id}_overlay_global.png"
            make_overlay(original, replica, overlay_output, args.id, args.max_side_width, args.overlay_alpha)
            overlay_paths.append(str(overlay_output.resolve()))
    crop_index = 1
    for spec in args.crops:
        box_o = crop_box(original.width, original.height, spec)
        box_r = crop_box(replica.width, replica.height, spec)
        crop_o = original.crop(box_o)
        crop_r = replica.crop(box_r)
        pair_output = out_dir / f"{args.id}_crop_{crop_index:02d}_{spec.replace(',', '_')}.png"
        make_pair(crop_o, crop_r, pair_output, f"{args.id} {spec}", args.max_side_width)
        pair_paths.append(str(pair_output.resolve()))
        if args.include_overlays:
            overlay_output = out_dir / f"{args.id}_overlay_{crop_index:02d}_{spec.replace(',', '_')}.png"
            make_overlay(
                crop_o,
                crop_r,
                overlay_output,
                f"{args.id} {spec}",
                args.max_side_width,
                args.overlay_alpha,
            )
            overlay_paths.append(str(overlay_output.resolve()))
        crop_index += 1
    if args.scene and args.region_crops == "all":
        for name, _, box_o, box_r in region_pairs:
            crop_o = original.crop(box_o)
            crop_r = replica.crop(box_r)
            pair_output = out_dir / f"{args.id}_crop_{crop_index:02d}_region_{name}.png"
            make_pair(crop_o, crop_r, pair_output, f"{args.id} region {name}", args.max_side_width)
            pair_paths.append(str(pair_output.resolve()))
            if args.include_overlays:
                overlay_output = out_dir / f"{args.id}_overlay_{crop_index:02d}_region_{name}.png"
                make_overlay(
                    crop_o,
                    crop_r,
                    overlay_output,
                    f"{args.id} region {name}",
                    args.max_side_width,
                    args.overlay_alpha,
                )
                overlay_paths.append(str(overlay_output.resolve()))
            crop_index += 1
    if args.write_review_bundle:
        manifest, findings_template, rebuild_template = review_bundle_payload(
            figure_id=args.id,
            round_index=args.round,
            scene_path=str(Path(args.scene).resolve()) if args.scene else None,
            scene=scene,
            original_path=str(Path(args.original).resolve()),
            replica_path=str(Path(args.replica).resolve()),
            pair_paths=pair_paths,
            overlay_paths=overlay_paths,
            regions=region_pairs,
        )
        manifest_path = out_dir / f"{args.id}_review_manifest.json"
        findings_path = out_dir / f"{args.id}_review_findings.template.json"
        rebuild_path = out_dir / f"{args.id}_scene_rebuild_brief.template.json"
        findings_template["review_manifest_path"] = str(manifest_path.resolve())
        rebuild_template["source_findings_path"] = str(findings_path.resolve())
        write_json(manifest_path, manifest)
        write_json(findings_path, findings_template)
        write_json(rebuild_path, rebuild_template)
    print(f"Wrote review assets to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
