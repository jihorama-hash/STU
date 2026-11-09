"""GPU-free TASK-009 crossing-person baseline supplementary subsets."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from roundabout.evaluate_detection import (  # noqa: E402
    detection_metrics,
    load_validated_detection_artifact,
)

GT_PATH = ROOT / "data/ground_truth/object_track_v2/canonical/gt_observations.csv"
MASK_PATH = ROOT / "data/calibration/by_video/DJI_0482_roadway_mask.png"
CONFIG_PATH = ROOT / "configs/evaluation_detection_v2.yaml"
DET_PATH = ROOT / "outputs/evaluation/r01_detection_only_20261104_02/A/detections.csv"
DET_META = Path(str(DET_PATH) + ".meta.json")
OUT_PATH = ROOT / "outputs/task009/crossing_baseline_supplement.json"
BOUNDARY_IDS = {"P006", "P033", "P007", "P004"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    mask = cv2.imread(str(MASK_PATH), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(MASK_PATH)
    gt_all: list[dict[str, str]]
    with GT_PATH.open(encoding="utf-8-sig", newline="") as stream:
        gt_all = list(csv.DictReader(stream))
    gt = [row for row in gt_all if row["object_class"] == "person"
          and row["ignore"].lower() != "true" and row["in_scope"].lower() == "true"]
    in_mask: list[dict[str, str]] = []
    by_object: dict[str, list[dict[str, str]]] = {}
    for row in gt:
        x = min(mask.shape[1] - 1, max(0, round(float(row["foot_x"]))) )
        y = min(mask.shape[0] - 1, max(0, round(float(row["foot_y"]))) )
        if mask[y, x] > 0:
            in_mask.append(row)
            by_object.setdefault(row["gt_object_id"], []).append(row)
    cohort_ids = set(by_object)
    d1 = [row for row in gt if row["gt_object_id"] in cohort_ids]
    d1_without_boundary = [
        row for row in d1 if row["gt_object_id"] not in BOUNDARY_IDS
    ]
    config, det_meta, detections = load_validated_detection_artifact(
        CONFIG_PATH, DET_PATH, DET_META
    )
    rows = []
    subsets = [
        ("foot_in_mask_anchor", in_mask),
        ("D1_any_mask_hit_object_all_anchors", d1),
        ("D1_without_four_boundary_objects", d1_without_boundary),
    ]
    for subset_name, subset in subsets:
        frames = {int(row["frame_index"]) for row in subset}
        counts = {
            "object_count": len({row["gt_object_id"] for row in subset}),
            "anchor_count": len(subset),
        }
        for confidence in (0.15, 0.25):
            for iou in (0.5, 0.3):
                result = detection_metrics(
                    subset, detections, frames, confidence, iou, classes=("person",)
                )["person"]
                rows.append({
                    "subset": subset_name, **counts,
                    "confidence": confidence, "iou": iou,
                    "tp": result["tp"], "fn": result["fn"],
                    "recall": result["recall"],
                })
    output = {
        "schema_version": "task009_crossing_baseline_supplement_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "selection": {
            "mask": str(MASK_PATH.relative_to(ROOT)),
            "mask_pixel_rule": "clip(round(foot_x/y), bounds); mask > 0",
            "eligible_gt": "person; ignore=false; in_scope=true",
            "D1_object_count": len(cohort_ids),
            "D1_anchor_count": len(d1),
            "anchor_inside_mask_count": len(in_mask),
            "boundary_excluded_object_ids": sorted(BOUNDARY_IDS),
            "D1_without_boundary_object_count": len({r['gt_object_id'] for r in d1_without_boundary}),
            "D1_without_boundary_anchor_count": len(d1_without_boundary),
        },
        "metrics": rows,
        "inputs_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (GT_PATH, MASK_PATH, DET_PATH, DET_META, CONFIG_PATH)
        },
        "detection_run_id": det_meta.get("evaluation_run_id"),
        "matching": config["matching"],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {
        "generated_utc": output["created_utc"],
        "code_commit": __import__("subprocess").run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True
        ).stdout.strip(),
        "script": str(Path(__file__).relative_to(ROOT)),
        "output_sha256": sha256(OUT_PATH),
        "inputs_sha256": output["inputs_sha256"],
        "coordinate_system": "source_pixel",
        "unit": "anchors, recall proportion",
        "review_status": "computed, not manually audited",
    }
    Path(str(OUT_PATH) + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"selection": output["selection"], "metrics": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
