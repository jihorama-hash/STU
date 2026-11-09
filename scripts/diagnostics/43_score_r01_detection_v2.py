"""Rescore the existing TASK-007 A detections against R01 GT v2 without inference."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from roundabout.evaluate_detection import (
    average_precision,
    build_ignore_ground_truth,
    complete_detection_frames,
    detection_metrics,
    load_validated_detection_artifact,
    normalized_box_row,
    rider_inside_vehicle_sensitivity,
)
from roundabout.evaluate_object_track import match_frame
from roundabout.evaluate_object_track import class_compatible


CONFIG_PATH = ROOT / "configs/evaluation_detection_v2.yaml"
GT_DIR = ROOT / "data/ground_truth/object_track_v2/canonical"
DETECTION_DIR = ROOT / "outputs/evaluation/r01_detection_only_20261104_02/A"
DETECTION_PATH = DETECTION_DIR / "detections.csv"
DETECTION_META_PATH = Path(f"{DETECTION_PATH}.meta.json")
OUTPUT_DIR = ROOT / "outputs/evaluation/r01_detection_only_v2_rescore_20261109_ignorefix/A"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def detection_overlaps_ignore(
    detection: dict[str, object], ignore_rows: list[dict[str, object]], threshold: float,
) -> bool:
    frame = int(detection["frame_index"])
    det = normalized_box_row(detection)["box"]
    width = max(0.0, float(det[2]) - float(det[0]))
    height = max(0.0, float(det[3]) - float(det[1]))
    area = width * height
    if not area:
        return False
    for raw_ignore in ignore_rows:
        ignore = normalized_box_row(raw_ignore)
        if frame != int(ignore["frame_index"]):
            continue
        if not class_compatible(str(ignore["object_class"]), str(detection["object_class"])):
            continue
        box = ignore["box"]
        intersection = max(0.0, min(float(det[2]), float(box[2])) - max(float(det[0]), float(box[0]))) * max(
            0.0, min(float(det[3]), float(box[3])) - max(float(det[1]), float(box[1]))
        )
        if intersection / area >= threshold:
            return True
    return False


def confusion_rows(
    ground_truth: list[dict[str, object]], detections: list[dict[str, object]],
    frames: set[int], ignore_rows: list[dict[str, object]],
    confidence: float, iou_threshold: float,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    gt_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    det_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in ground_truth:
        if int(row["frame_index"]) in frames:
            gt_by_frame[int(row["frame_index"])].append(row)
    for row in detections:
        if int(row["frame_index"]) in frames and float(row["confidence"]) >= confidence:
            det_by_frame[int(row["frame_index"])].append(row)

    counts: Counter[tuple[str, str]] = Counter()
    ignored: Counter[str] = Counter()
    for frame in frames:
        gt_rows = gt_by_frame.get(frame, [])
        det_rows = det_by_frame.get(frame, [])
        pairs = match_frame(gt_rows, det_rows, iou_threshold)
        matched_gt = {gi for gi, _, _ in pairs}
        matched_det = {di for _, di, _ in pairs}
        for gi, di, _ in pairs:
            gt_class = str(gt_rows[gi]["object_class"])
            det_class = str(det_rows[di]["object_class"])
            counts[(gt_class, det_class)] += 1
        for gi, row in enumerate(gt_rows):
            if gi not in matched_gt:
                counts[(str(row["object_class"]), "miss")] += 1
        for di, row in enumerate(det_rows):
            if di in matched_det:
                continue
            if detection_overlaps_ignore(row, ignore_rows, iou_threshold):
                ignored[str(row["object_class"])] += 1
            else:
                counts[("FP", str(row["object_class"]))] += 1
    matrix = [
        {"gt_class": gt_class, "detection_class": det_class, "count": count}
        for (gt_class, det_class), count in sorted(counts.items())
    ]
    ignored_rows = [
        {"detection_class": cls, "ignored_detection_count": count}
        for cls, count in sorted(ignored.items())
    ]
    return matrix, ignored_rows


def write_meta(path: Path, inputs: list[Path], config: dict[str, object]) -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "analysis_script": "scripts/diagnostics/43_score_r01_detection_v2.py",
        "analysis_script_sha256": sha256(Path(__file__)),
        "evaluation_config": "configs/evaluation_detection_v2.yaml",
        "evaluation_config_sha256": sha256(CONFIG_PATH),
        "input_files": {p.relative_to(ROOT).as_posix(): sha256(p) for p in inputs},
        "coordinate_system": "source_pixel",
        "unit": "px",
        "review_status": "draft",
        "artifact_path": path.relative_to(ROOT).as_posix(),
        "artifact_sha256": sha256(path),
    }
    Path(f"{path}.meta.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise FileExistsError(f"Refusing to overwrite v2 detection outputs: {OUTPUT_DIR}")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    observations_all = [normalized_box_row(row) for row in read_csv(GT_DIR / "gt_observations.csv")]
    observations = [row for row in observations_all if str(row["ignore"]).lower() != "true"]
    ignore_annotations = [
        {**row, "iscrowd": 1, "ignore_reason": "reviewed_ignore_box"}
        for row in observations_all if str(row["ignore"]).lower() == "true"
    ]
    objects = read_csv(GT_DIR / "gt_objects.csv")
    visibility = read_csv(GT_DIR / "gt_visibility_intervals.csv")
    skips = read_csv(GT_DIR / "gt_observation_skips.csv")
    v2_manifest_path = GT_DIR / "ground_truth_manifest.json"
    manifest = json.loads(v2_manifest_path.read_text(encoding="utf-8"))
    for name in ("objects", "visibility_intervals", "observations", "observation_skips"):
        path = GT_DIR / manifest["frozen_files"][name]["path"].split("/", 1)[-1]
        expected = manifest["frozen_files"][name]["sha256"]
        if sha256(path) != expected:
            raise RuntimeError(f"GT v2 SHA-256 mismatch for {name}: {path}")
    gt_config = config["ground_truth"]
    grid = list(range(
        int(gt_config["start_frame_index"]),
        int(gt_config["end_frame_index"]) + 1,
        int(gt_config["frame_step"]),
    ))
    expected_frames = sorted(set(grid) | {int(row["frame_index"]) for row in observations})
    config, detection_meta, raw_detections = load_validated_detection_artifact(
        CONFIG_PATH, DETECTION_PATH, DETECTION_META_PATH
    )
    detections = [normalized_box_row(row) for row in raw_detections]
    detector_frames = set(int(frame) for frame in detection_meta["frames"]["indices"])
    missing_detection_frames = sorted(set(expected_frames) - detector_frames)
    if missing_detection_frames:
        raise RuntimeError(
            f"Detection artifact omits v2 eligible/grid frames: {missing_detection_frames}"
        )
    generated_ignore, unresolved_ignore = build_ignore_ground_truth(
        observations_all, objects, visibility, skips, detector_frames
    )
    ignore_rows = [*ignore_annotations, *generated_ignore]
    complete_frames = complete_detection_frames(grid, visibility, observations_all)
    recall_frames = {int(row["frame_index"]) for row in observations}
    conf_points = [float(value) for value in config["matching"]["confidence_operating_points"]]
    iou_thresholds = [
        float(config["matching"]["iou_thresholds"]["official"]),
        float(config["matching"]["iou_thresholds"]["sensitivity"]),
    ]
    classes = ["person", "car", "motorcycle"]
    pr_rows: list[dict[str, object]] = []
    ignored_rows: list[dict[str, object]] = []
    for confidence in conf_points:
        for threshold in iou_thresholds:
            p = detection_metrics(
                observations, detections, set(complete_frames), confidence, threshold,
                ignore_ground_truth=ignore_rows,
            )
            r = detection_metrics(
                observations, detections, recall_frames, confidence, threshold,
                ignore_ground_truth=ignore_rows,
            )
            for cls in [*classes, "all"]:
                pm, rm = p[cls], r[cls]
                pr_rows.append({
                    "confidence": confidence, "iou_threshold": threshold, "class": cls,
                    "tp_precision_scope": pm["tp"], "fp_precision_scope": pm["fp"],
                    "precision": pm["precision"], "tp_recall_scope": rm["tp"],
                    "fn_recall_scope": rm["fn"], "recall": rm["recall"],
                    "f1": rm["f1"],
                    "ignored_detections_precision_scope": pm["ignored_detections"],
                    "ignored_detections_recall_scope": rm["ignored_detections"],
                })
                ignored_rows.append({
                    "confidence": confidence, "iou_threshold": threshold, "class": cls,
                    "complete_frame_count": pm["ignored_detections"],
                    "eligible_gt_frame_count": rm["ignored_detections"],
                })

    complete_set = set(complete_frames)
    complete_gt = [row for row in observations if int(row["frame_index"]) in complete_set]
    complete_detections = [row for row in detections if int(row["frame_index"]) in complete_set]
    complete_ignore = [row for row in ignore_rows if int(row["frame_index"]) in complete_set]
    iou_values = [float(value) for value in config["matching"]["ap_iou_thresholds"]]
    max_detections = int(config["matching"]["coco"]["max_detections"])
    ap_rows: list[dict[str, object]] = []
    for cls in classes:
        values = []
        for threshold in iou_values:
            value = average_precision(
                complete_gt, complete_detections, threshold, cls,
                max_detections=max_detections, ignore_ground_truth=complete_ignore,
            )
            values.append(value)
            ap_rows.append({"class": cls, "iou_threshold": threshold, "AP": value})
        ap_rows.append({"class": cls, "iou_threshold": "0.50:0.95", "AP": sum(values) / len(values)})

    vehicle_gt = [row for row in observations if str(row["object_class"]) in {"bicycle", "motorcycle"}]
    rider_rows: list[dict[str, object]] = []
    for confidence in conf_points:
        for threshold in iou_thresholds:
            person_gt: dict[int, list[dict[str, object]]] = defaultdict(list)
            person_dets: dict[int, list[dict[str, object]]] = defaultdict(list)
            for row in observations:
                if row["object_class"] == "person":
                    person_gt[int(row["frame_index"])].append(row)
            for row in detections:
                if row["object_class"] == "person" and float(row["confidence"]) >= confidence:
                    person_dets[int(row["frame_index"])].append(row)
            unmatched: list[dict[str, object]] = []
            for frame, det_rows in person_dets.items():
                pairs = match_frame(person_gt.get(frame, []), det_rows, threshold)
                matched = {di for _, di, _ in pairs}
                for index, row in enumerate(det_rows):
                    if index not in matched and not detection_overlaps_ignore(row, ignore_rows, threshold):
                        unmatched.append(row)
            counts = rider_inside_vehicle_sensitivity(unmatched, set(), vehicle_gt, config)
            for containment_threshold, count in sorted(counts.items()):
                rider_rows.append({
                    "confidence": confidence, "iou_threshold": threshold,
                    "containment_threshold": containment_threshold,
                    "rider_inside_vehicle_count": count,
                    "primary_threshold": containment_threshold == float(config["matching"]["rider_inside_vehicle"]["containment_threshold"]),
                })

    matrix, ignored_confusion = confusion_rows(
        complete_gt, complete_detections, complete_set, complete_ignore,
        confidence=conf_points[0], iou_threshold=iou_thresholds[0],
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "metrics_summary.json": {
            "schema_version": "detection_evaluation_v2_rescore",
            "evaluation_run_id": "r01_detection_only_v2_rescore_20261109_ignorefix",
            "source_detection_run": "r01_detection_only_20261104_02/A",
            "source_detection_sha256": sha256(DETECTION_PATH),
            "gt_dataset_id": manifest["gt_dataset_id"],
            "ground_truth_observations": len(observations),
            "excluded_ignore_observations": len(ignore_annotations),
            "ignore_by_class": dict(Counter(str(row["object_class"]) for row in ignore_annotations)),
            "eligible_by_class": dict(Counter(str(row["object_class"]) for row in observations)),
            "reviewed_skips": len(skips),
            "detection_frames": len(detector_frames),
            "unused_detection_frames_from_v1_union": len(detector_frames - set(expected_frames)),
            "excluded_ignore_anchor_frames_without_detections": sorted(
                {int(row["frame_index"]) for row in ignore_annotations} - detector_frames
            ),
            "complete_frames": complete_frames,
            "precision_recall": pr_rows,
            "average_precision": ap_rows,
            "rider_inside_vehicle": rider_rows,
            "unresolved_ignore_ground_truth_count": len(unresolved_ignore),
            "matching_rules": config["matching"],
        },
        "pr_metrics.csv": pr_rows,
        "ap_metrics.csv": ap_rows,
        "rider_inside_vehicle.csv": rider_rows,
        "confusion_matrix_conf_0.15_iou_0.50.csv": matrix,
        "ignored_detections_summary.csv": ignored_rows,
        "confusion_ignored_detections.csv": ignored_confusion,
        "unresolved_ignore_ground_truth.csv": unresolved_ignore,
    }
    fields = {
        "pr_metrics.csv": ["confidence", "iou_threshold", "class", "tp_precision_scope", "fp_precision_scope", "precision", "tp_recall_scope", "fn_recall_scope", "recall", "f1", "ignored_detections_precision_scope", "ignored_detections_recall_scope"],
        "ap_metrics.csv": ["class", "iou_threshold", "AP"],
        "rider_inside_vehicle.csv": ["confidence", "iou_threshold", "containment_threshold", "rider_inside_vehicle_count", "primary_threshold"],
        "confusion_matrix_conf_0.15_iou_0.50.csv": ["gt_class", "detection_class", "count"],
        "ignored_detections_summary.csv": ["confidence", "iou_threshold", "class", "complete_frame_count", "eligible_gt_frame_count"],
        "confusion_ignored_detections.csv": ["detection_class", "ignored_detection_count"],
        "unresolved_ignore_ground_truth.csv": ["gt_object_id", "frame_index", "ignore_reason", "status"],
    }
    for name, value in outputs.items():
        target = OUTPUT_DIR / name
        if name.endswith(".json"):
            target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            write_csv(target, fields[name], value)
    inputs = [
        CONFIG_PATH, DETECTION_PATH, DETECTION_META_PATH, v2_manifest_path,
        GT_DIR / "gt_objects.csv", GT_DIR / "gt_visibility_intervals.csv",
        GT_DIR / "gt_observations.csv", GT_DIR / "gt_observation_skips.csv",
    ]
    for target in (OUTPUT_DIR / name for name in outputs):
        write_meta(target, inputs, config)
    print(json.dumps({"output_dir": str(OUTPUT_DIR), "eligible_observations": len(observations),
                      "ignore_observations": len(ignore_annotations), "complete_frames": len(complete_frames),
                      "unresolved_ignore_ground_truth": len(unresolved_ignore)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
