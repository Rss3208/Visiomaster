#!/usr/bin/env python3
"""Unit tests for the v0.4 deterministic gates.

Builds synthetic scenes / findings with planted defects in a temp dir and asserts
each gate flags exactly the planted classes. Run directly:

    python tests/test_gates_v04.py

No third-party dependencies; gates run via subprocess so exit codes are the contract.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

PASS = 0
FAIL = 0


def run_gate(script: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *argv],
        capture_output=True,
        text=True,
        timeout=60,
    )


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name} {detail}")


def write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def base_scene() -> dict:
    return {
        "version": "1",
        "page": {"width": 1000, "height": 800, "units": "px", "origin": "top-left"},
        "metadata": {"style_calibration": {"forward_arrow": {"head_length_px": 20}}},
        "nodes": [],
        "edges": [],
    }


def test_text_render(tmp: Path) -> None:
    print("text_render_audit")
    gate = "text_render_audit.py"

    bad = base_scene() | {"nodes": [
        {"id": "lbl1", "type": "text_block", "x": 10, "y": 10, "w": 200, "h": 30, "text": "Loss L_SPAN value"},
    ]}
    result = run_gate(gate, str(write_json(tmp / "tr_bad.json", bad)))
    check("R1 flags raw `_` on plain text_block", result.returncode == 1 and "R1_raw_subsup" in result.stdout, result.stdout + result.stderr)

    ok_math = base_scene() | {"nodes": [
        {"id": "m1", "type": "math_text", "x": 10, "y": 10, "w": 200, "h": 30, "text": "Loss L_SPAN value"},
    ]}
    result = run_gate(gate, str(write_json(tmp / "tr_math.json", ok_math)))
    check("R1 exempts math_text fragment encoding", result.returncode == 0, result.stdout + result.stderr)

    result = run_gate(gate, str(write_json(tmp / "tr_math_strict.json", ok_math), ), "--strict")
    check("R2 silent for math_text under --strict", result.returncode == 0, result.stdout + result.stderr)

    result = run_gate(gate, str(write_json(tmp / "tr_bad_strict.json", bad)), "--strict")
    check("R2 flags math-like label on plain text_block under --strict",
          result.returncode == 1 and "R2_math_label_on_plain_text" in result.stdout, result.stdout)

    wide = base_scene() | {"nodes": [
        {"id": "lbl2", "type": "text_block", "x": 10, "y": 10, "w": 60, "h": 20,
         "text": "Multi-head Cross Attention Long Label", "single_line": True,
         "style": {"font_size_pt": 14}},
    ]}
    result = run_gate(gate, str(write_json(tmp / "tr_wrap.json", wide)))
    check("R3 flags likely wrap on single-line label", result.returncode == 1 and "R3_likely_wrap" in result.stdout, result.stdout)

    overflow = base_scene() | {"nodes": [
        {"id": "box", "type": "group_container", "x": 0, "y": 0, "w": 300, "h": 200},
        {"id": "txt", "type": "text_block", "x": 250, "y": 150, "w": 120, "h": 80,
         "text": "outside", "container_id": "box"},
    ]}
    result = run_gate(gate, str(write_json(tmp / "tr_overflow.json", overflow)), "--strict")
    check("R4 flags text escaping its container under --strict",
          result.returncode == 1 and "R4_text_outside_container" in result.stdout, result.stdout)
    result = run_gate(gate, str(write_json(tmp / "tr_overflow_warn.json", overflow)))
    check("R4 only warns without --strict", result.returncode == 0, result.stdout + result.stderr)

    edge_bad = base_scene() | {"nodes": [
        {"id": "a", "type": "process_box", "x": 0, "y": 0, "w": 50, "h": 30, "text": "A"},
        {"id": "b", "type": "process_box", "x": 200, "y": 0, "w": 50, "h": 30, "text": "B"},
    ], "edges": [
        {"id": "e1", "type": "arrow_connector", "from": "a", "to": "b", "label": "q_hrrp=[0.5,0.2]"},
    ]}
    result = run_gate(gate, str(write_json(tmp / "tr_edge.json", edge_bad)))
    check("R1 flags raw `_` on edge label", result.returncode == 1 and "edge:e1" in result.stdout, result.stdout)


def test_raster_policy(tmp: Path) -> None:
    print("raster_policy_audit")
    gate = "raster_policy_audit.py"

    bad = base_scene() | {"nodes": [
        {"id": "tile_grid_1", "type": "image_tile", "x": 0, "y": 0, "w": 300, "h": 200},
    ]}
    result = run_gate(gate, str(write_json(tmp / "rp_bad.json", bad)))
    check("R1+R2 flag unregistered grid-class raster",
          result.returncode == 1 and "R1_missing_or_invalid_justification" in result.stdout and "R2_redrawable_class_raster" in result.stdout,
          result.stdout + result.stderr)

    justified_grid = base_scene() | {"nodes": [
        {"id": "grid_tile_2", "type": "image_tile", "x": 0, "y": 0, "w": 300, "h": 200,
         "justification": "photographic", "source_bbox_px": [0, 0, 300, 200]},
    ]}
    result = run_gate(gate, str(write_json(tmp / "rp_grid.json", justified_grid)))
    check("R2 still fails justified grid-class tile",
          result.returncode == 1 and "R2_redrawable_class_raster" in result.stdout, result.stdout)

    photo = base_scene() | {"nodes": [
        {"id": "photo_input", "type": "image_tile", "x": 0, "y": 0, "w": 120, "h": 80,
         "justification": "photographic", "source_bbox_px": [0, 0, 120, 80]},
    ]}
    result = run_gate(gate, str(write_json(tmp / "rp_photo.json", photo)))
    check("photographic tile passes", result.returncode == 0, result.stdout + result.stderr)

    huge = base_scene() | {"nodes": [
        {"id": "big_photo", "type": "image_tile", "x": 0, "y": 0, "w": 600, "h": 500,
         "justification": "complex_bitmap", "source_bbox_px": [0, 0, 600, 500]},
    ]}
    result = run_gate(gate, str(write_json(tmp / "rp_huge.json", huge)), "--strict")
    check("37.5% raster share fails under --strict",
          result.returncode == 1 and "R3_raster_area_share" in result.stdout, result.stdout)
    result = run_gate(gate, str(write_json(tmp / "rp_huge2.json", huge)))
    check("37.5% raster share only warns without --strict", result.returncode == 0, result.stdout)


def test_arrow_micro(tmp: Path) -> None:
    print("arrow_micro_geometry_gate")
    gate = "arrow_micro_geometry_gate.py"

    head_only = base_scene() | {"nodes": [
        {"id": "src", "type": "process_box", "x": 0, "y": 0, "w": 100, "h": 60, "text": "S"},
        {"id": "dst", "type": "process_box", "x": 400, "y": 0, "w": 100, "h": 60, "text": "T"},
    ], "edges": [
        {"id": "e1", "type": "arrow_connector", "from": "src", "to": "dst",
         "points": [[100, 30], [360, 30], [364, 30]]},
    ]}
    result = run_gate(gate, str(write_json(tmp / "am_head.json", head_only)))
    check("R6 flags head-only terminal fragment",
          result.returncode == 1 and "R6_head_only_fragment" in result.stdout, result.stdout + result.stderr)

    overshoot = base_scene() | {"nodes": [
        {"id": "dst2", "type": "process_box", "x": 400, "y": 0, "w": 100, "h": 60, "text": "T"},
    ], "edges": [
        {"id": "e2", "type": "arrow_connector", "from": "src2", "to": "dst2",
         "points": [[200, 30], [440, 30]]},
    ]}
    result = run_gate(gate, str(write_json(tmp / "am_over.json", overshoot)))
    check("R5 flags endpoint overshooting 40px into target",
          result.returncode == 1 and "R5_endpoint_overshoot" in result.stdout, result.stdout + result.stderr)

    spur = base_scene() | {"nodes": [
        {"id": "n1", "type": "process_box", "x": 0, "y": 0, "w": 100, "h": 60, "text": "S"},
        {"id": "n2", "type": "process_box", "x": 400, "y": 300, "w": 100, "h": 60, "text": "T"},
    ], "edges": [
        {"id": "e3", "type": "arrow_connector", "from": "n1", "to": "n2", "route": "orthogonal",
         "points": [[50, 60], [50, 200], [51, 206], [450, 206], [450, 300]]},
    ]}
    result = run_gate(gate, str(write_json(tmp / "am_spur.json", spur)), "--strict")
    check("R7 flags tiny backtracking jog under --strict",
          result.returncode == 1 and "R7_corner_spur" in result.stdout, result.stdout + result.stderr)

    clean = base_scene() | {"nodes": [
        {"id": "c1", "type": "process_box", "x": 0, "y": 0, "w": 100, "h": 60, "text": "S"},
        {"id": "c2", "type": "process_box", "x": 400, "y": 300, "w": 100, "h": 60, "text": "T"},
    ], "edges": [
        {"id": "e4", "type": "arrow_connector", "from": "c1", "to": "c2", "route": "orthogonal",
         "points": [[50, 60], [50, 330], [400, 330]]},
    ]}
    result = run_gate(gate, str(write_json(tmp / "am_clean.json", clean)))
    check("clean orthogonal arrow passes", result.returncode == 0, result.stdout + result.stderr)

    inch = base_scene() | {"page": {"width": 13.333, "height": 7.5, "units": "in"}}
    result = run_gate(gate, str(write_json(tmp / "am_inch.json", inch)))
    check("non-px scene skipped gracefully", result.returncode == 0 and "SKIPPED" in result.stdout, result.stdout)


def test_sweep_gate(tmp: Path) -> None:
    print("review_checklist_gate --require-sweep")
    gate = "review_checklist_gate.py"

    def findings_doc(findings: list[dict]) -> dict:
        return {
            "topology_checklist": [
                {"id": "T001", "focus_region": "core", "source_fact": "A -> B",
                 "replica_status": "matches", "status": "pass", "certainty": "certain"},
            ],
            "visual_checklist": [
                {"id": "V001", "focus_region": "core", "source_expectation": "no overlap",
                 "replica_status": "ok", "status": "pass", "certainty": "certain"},
            ],
            "region_scores": [],
            "reviewer_inputs": {"original_path": str(tmp / "original.png")},
            "findings": findings,
        }

    (tmp / "original.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    bad = findings_doc([
        {"id": "F001", "severity": "important", "summary": "broken arrow"},
    ])
    result = run_gate(gate, str(write_json(tmp / "sw_bad.json", bad)), "--require-sweep", "--allow-missing-local-original")
    check("sweep gate fails finding without class_id/count",
          result.returncode == 1 and "class_id" in result.stdout,
          result.stdout + result.stderr)

    good = findings_doc([
        {"id": "F001", "severity": "important", "summary": "wrapped labels", "class_id": "C",
         "similar_instance_count": 3, "similar_locations": ["left panel", "mid panel", "bottom panel"],
         "checklist_refs": ["V001"]},
    ])
    result = run_gate(gate, str(write_json(tmp / "sw_good.json", good)), "--require-sweep", "--allow-missing-local-original")
    check("sweep gate passes complete finding", result.returncode == 0, result.stdout + result.stderr)

    bad_count = findings_doc([
        {"id": "F001", "severity": "important", "summary": "pasted grids", "class_id": "E",
         "similar_instance_count": 4, "similar_locations": []},
    ])
    result = run_gate(gate, str(write_json(tmp / "sw_count.json", bad_count)), "--require-sweep", "--allow-missing-local-original")
    check("sweep gate fails count>1 with empty locations",
          result.returncode == 1 and "similar_locations" in result.stdout, result.stdout)

    result = run_gate(gate, str(write_json(tmp / "sw_off.json", findings_doc([{"id": "F001", "severity": "general", "summary": "x"}]))),
                      "--allow-missing-local-original")
    check("sweep check off by default", result.returncode == 0, result.stdout + result.stderr)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="visiomaster_gates_") as tmp_name:
        tmp = Path(tmp_name)
        test_text_render(tmp)
        test_raster_policy(tmp)
        test_arrow_micro(tmp)
        test_sweep_gate(tmp)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
