from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scene_to_visio import edge_route_points, edge_style, load_component_map, normalize_scene_coordinates, rounded_orthogonal_points  # noqa: E402


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def test_public_release_files_are_present() -> None:
    for rel in [
        "SKILL.md",
        "README.md",
        "LICENSE",
        "requirements.txt",
        "sync_to_skill.py",
        "references/review-contract.md",
        "references/reviewer-two-image-prompt.md",
        "references/full-scene-regeneration-prompt.md",
        "references/renderer-effective-fields.json",
        "scripts/make_review_assets.py",
        "scripts/review_checklist_gate.py",
        "scripts/review_findings_to_repair_plan.py",
        "scripts/prepare_regeneration_packet.py",
        "scripts/round_noop_gate.py",
    ]:
        assert (ROOT / rel).exists(), rel


def test_basic_scene_validates() -> None:
    result = run_script("scene_validate.py", str(ROOT / "templates" / "examples" / "basic_flow.scene.json"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Scene is valid" in result.stdout


def test_rounded_orthogonal_points_rounds_only_the_corner() -> None:
    points = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)]
    rounded = rounded_orthogonal_points(points, corner_radius=0.5, samples_per_corner=4)

    assert rounded[0] == points[0]
    assert rounded[-1] == points[-1]
    assert (2.0, 0.0) not in rounded
    assert any(abs(x - 1.5) < 1e-9 and abs(y - 0.0) < 1e-9 for x, y in rounded)
    assert any(abs(x - 2.0) < 1e-9 and abs(y - 0.5) < 1e-9 for x, y in rounded)
    assert all(
        0.0 <= x <= 2.0 and 0.0 <= y <= 2.0
        for x, y in rounded
    )


def test_pixel_corner_radius_is_scaled_to_inches() -> None:
    scene = {
        "version": "0.1",
        "page": {"width": 1000, "height": 500, "units": "px", "target_width_in": 10},
        "nodes": [
            {"id": "a", "type": "rounded_process", "x": 100, "y": 100, "w": 100, "h": 50, "text": "A"},
            {"id": "b", "type": "rounded_process", "x": 800, "y": 300, "w": 100, "h": 50, "text": "B"},
        ],
        "edges": [
            {
                "id": "a_to_b",
                "type": "rounded_orthogonal_connector",
                "from": "a:right@0.50",
                "points": [[400, 125], [400, 325]],
                "to": "b:left@0.50",
                "route": "rounded_orthogonal",
                "corner_radius_px": 12,
            }
        ],
        "assets": [],
    }

    normalized = normalize_scene_coordinates(scene)
    edge = normalized["edges"][0]
    assert edge["corner_radius_in"] == 0.12


def test_rounded_orthogonal_connector_validates_and_routes() -> None:
    scene = {
        "version": "0.1",
        "page": {"width": 8, "height": 4.5, "units": "in"},
        "nodes": [
            {"id": "a", "type": "rounded_process", "x": 1, "y": 1, "w": 1, "h": 0.5, "text": "A"},
            {"id": "b", "type": "rounded_process", "x": 5, "y": 2, "w": 1, "h": 0.5, "text": "B"},
        ],
        "edges": [
            {
                "id": "a_to_b",
                "type": "rounded_orthogonal_connector",
                "from": "a:right@0.50",
                "points": [[3, 1.25], [3, 2.25]],
                "to": "b:left@0.50",
                "route": "rounded_orthogonal",
                "corner_radius_in": 0.12,
            }
        ],
        "assets": [],
    }
    scene_path = Path.cwd() / "__tmp_rounded_orthogonal.scene.json"
    scene_path.write_text(json.dumps(scene), encoding="utf-8")
    try:
        result = run_script("scene_validate.py", str(scene_path))
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        scene_path.unlink(missing_ok=True)

    component_map = load_component_map()
    edge = scene["edges"][0]
    style = edge_style(edge, component_map, {})
    nodes = {node["id"]: node for node in scene["nodes"]}
    route = edge_route_points(edge, style, nodes)
    assert route == [(2.0, 1.25), (3.0, 1.25), (3.0, 2.25), (5.0, 2.25)]


def test_rounded_orthogonal_example_passes_strict_contract() -> None:
    example = ROOT / "templates" / "examples" / "rounded_orthogonal_connector.scene.json"
    result = run_script("scene_validate.py", str(example), "--strict")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Scene is valid" in result.stdout


def test_visual_grammar_primitives_example_passes_strict_contract() -> None:
    example = ROOT / "templates" / "examples" / "visual_grammar_primitives.scene.json"
    result = run_script("scene_validate.py", str(example), "--strict")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Scene is valid" in result.stdout


def test_polyline_wave_requires_explicit_shape_in_strict_mode(tmp_path: Path) -> None:
    source = ROOT / "templates" / "examples" / "visual_grammar_primitives.scene.json"
    scene_doc = json.loads(source.read_text(encoding="utf-8"))
    for node in scene_doc["nodes"]:
        if node.get("id") == "output_wave":
            node.pop("samples", None)
            node.pop("points", None)
    scene = tmp_path / "bad_wave.scene.json"
    scene.write_text(json.dumps(scene_doc, ensure_ascii=False), encoding="utf-8")

    result = run_script("scene_validate.py", str(scene), "--strict")
    assert result.returncode != 0
    assert "polyline_wave `output_wave`" in (result.stdout + result.stderr)


def test_review_bundle_and_checklist_gate(tmp_path: Path) -> None:
    original = tmp_path / "original.png"
    replica = tmp_path / "replica.png"
    scene = tmp_path / "scene.json"
    review_dir = tmp_path / "review"

    Image.new("RGB", (320, 180), "white").save(original)
    Image.new("RGB", (320, 180), (245, 248, 255)).save(replica)
    scene.write_text(
        json.dumps(
            {
                "version": "0.1",
                "page": {"width": 8, "height": 4.5, "units": "in"},
                "nodes": [],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )

    bundle = run_script(
        "make_review_assets.py",
        "--original",
        str(original),
        "--replica",
        str(replica),
        "--scene",
        str(scene),
        "--id",
        "smoke",
        "--round",
        "1",
        "--write-review-bundle",
        "--output-dir",
        str(review_dir),
    )
    assert bundle.returncode == 0, bundle.stdout + bundle.stderr

    findings = review_dir / "smoke_review_findings.json"
    manifest = review_dir / "smoke_review_manifest.json"
    findings.write_text(
        json.dumps(
            {
                "figure_id": "smoke",
                "round": 1,
                "overall_verdict": "needs_rebuild",
                "rebuild_required": True,
                "topology_checklist": [
                    {
                        "id": "T001",
                        "focus_region": "main",
                        "source_fact": "A visible arrow should connect A to B.",
                        "replica_status": "The arrow is missing.",
                        "status": "fail",
                        "certainty": "certain",
                    }
                ],
                "visual_checklist": [
                    {
                        "id": "V001",
                        "focus_region": "main",
                        "source_expectation": "The two boxes are horizontally aligned.",
                        "replica_status": "The boxes are vertically offset.",
                        "status": "fail",
                        "certainty": "certain",
                    }
                ],
                "findings": [
                    {
                        "id": "F001",
                        "severity": "blocking",
                        "summary": "Main arrow is missing",
                        "visible_diff": "The source has a connector but the replica does not.",
                        "source_appearance": "Two boxes joined by one arrow.",
                        "replica_appearance": "Two unconnected boxes.",
                        "impact_on_fidelity": "The diagram topology is wrong.",
                        "focus_regions": ["main"],
                        "checklist_refs": ["T001", "V001"],
                        "expected_visible_change": "Restore the connector from A to B.",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    gate = run_script(
        "review_checklist_gate.py",
        str(findings),
        "--manifest",
        str(manifest),
        "--require-failed-refs",
    )
    assert gate.returncode == 0, gate.stdout + gate.stderr


def test_arrow_plan_gate_accepts_bound_horizontal_arrow(tmp_path: Path) -> None:
    scene = tmp_path / "arrow_plan_ok.scene.json"
    scene.write_text(
        json.dumps(
            {
                "version": "0.1",
                "metadata": {
                    "arrow_plan": [
                        {
                            "id": "A001",
                            "from": "left box right boundary",
                            "from_visual_object": "left box",
                            "to": "right box left boundary",
                            "to_visual_object": "right box",
                            "from_anchor": "right@0.50",
                            "from_anchor_description": "right edge midpoint",
                            "to_anchor": "left@0.50",
                            "to_anchor_description": "left edge midpoint",
                            "semantic_intent": "data_flow",
                            "route_shape": "straight_horizontal",
                            "line_style": "solid",
                            "direction": "left_to_right",
                            "arrowhead": "end",
                            "must_be_axis_aligned": True,
                            "source_bbox_px": [100, 100, 260, 120],
                            "must_not_cross": ["a", "b"],
                            "relative_position_facts": ["left box is left of right box", "arrow is horizontal"],
                            "certainty": "certain",
                        }
                    ]
                },
                "page": {"width": 8, "height": 4.5, "units": "in"},
                "nodes": [
                    {"id": "a", "type": "rounded_process", "x": 1, "y": 2, "w": 1, "h": 0.5, "text": "A"},
                    {"id": "b", "type": "rounded_process", "x": 4, "y": 2, "w": 1, "h": 0.5, "text": "B"},
                ],
                "edges": [
                    {
                        "id": "a_to_b",
                        "type": "lane_arrow",
                        "arrow_plan_id": "A001",
                        "from": "a:right@0.50",
                        "to": "b:left@0.50",
                        "route": "horizontal",
                    }
                ],
                "assets": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_script("scene_validate.py", str(scene), "--strict")
    assert result.returncode == 0, result.stdout + result.stderr


def test_arrow_plan_gate_rejects_diagonal_horizontal_arrow(tmp_path: Path) -> None:
    scene = tmp_path / "arrow_plan_bad.scene.json"
    scene.write_text(
        json.dumps(
            {
                "version": "0.1",
                "metadata": {
                    "arrow_plan": [
                        {
                            "id": "A001",
                            "from": "left box right boundary",
                            "from_visual_object": "left box",
                            "to": "right box left boundary",
                            "to_visual_object": "right box",
                            "from_anchor_description": "right edge midpoint",
                            "to_anchor_description": "left edge midpoint",
                            "semantic_intent": "data_flow",
                            "route_shape": "straight_horizontal",
                            "line_style": "solid",
                            "direction": "left_to_right",
                            "arrowhead": "end",
                            "must_be_axis_aligned": True,
                            "source_bbox_px": [100, 100, 260, 120],
                            "must_not_cross": ["a", "b"],
                            "relative_position_facts": ["left box is left of right box", "arrow is horizontal"],
                            "certainty": "certain",
                        }
                    ]
                },
                "page": {"width": 8, "height": 4.5, "units": "in"},
                "nodes": [
                    {"id": "a", "type": "rounded_process", "x": 1, "y": 1, "w": 1, "h": 0.5, "text": "A"},
                    {"id": "b", "type": "rounded_process", "x": 4, "y": 2, "w": 1, "h": 0.5, "text": "B"},
                ],
                "edges": [
                    {
                        "id": "a_to_b",
                        "type": "lane_arrow",
                        "arrow_plan_id": "A001",
                        "from": "a:right@0.50",
                        "to": "b:left@0.50",
                        "route": "straight",
                    }
                ],
                "assets": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_script("scene_validate.py", str(scene), "--strict")
    assert result.returncode != 0
    assert "expects a horizontal arrow" in (result.stdout + result.stderr)
