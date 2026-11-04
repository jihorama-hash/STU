"""Score the validated R01 raw detections and write checkpoint-2 evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from roundabout.detect_track import make_slices
from roundabout.evaluate_detection import (
    average_precision,
    build_ignore_ground_truth,
    complete_detection_frames,
    decompose_tracker_loss,
    detection_metrics,
    load_validated_detection_artifact,
    normalized_box_row,
)
from roundabout.evaluate_object_track import box_iou, match_frame


RUN_DIR = PROJECT_ROOT / "outputs/evaluation/r01_detection_only_20261104_02/A"
DETECTION_PATH = RUN_DIR / "detections.csv"
DETECTION_META_PATH = Path(f"{DETECTION_PATH}.meta.json")
TILE_PATH = RUN_DIR / "tile_diagnostics.csv"
OBSERVATIONS_PATH = PROJECT_ROOT / "data/ground_truth/object_track_v1/gt_observations.csv"
OBJECTS_PATH = PROJECT_ROOT / "data/ground_truth/object_track_v1/gt_objects.csv"
VISIBILITY_PATH = PROJECT_ROOT / "data/ground_truth/object_track_v1/gt_visibility_intervals.csv"
SKIPS_PATH = PROJECT_ROOT / "data/ground_truth/object_track_v1/review/gt_observation_skips_R01.csv"
GT_MANIFEST_PATH = PROJECT_ROOT / "data/ground_truth/object_track_v1/ground_truth_manifest.json"
BASELINE_TRACKS_PATH = PROJECT_ROOT / (
    "outputs/evaluation_runs/r01_baseline_yolo11m_full_20261103_02/raw_tracker/tracks.csv"
)
TASK006_METRICS_PATH = PROJECT_ROOT / "outputs/evaluation/r01_gtv1_scoring_20261103_02/metrics_summary.json"
EVALUATION_CONFIG_PATH = PROJECT_ROOT / "configs/evaluation_detection_v1.yaml"
SUMMARY_PATH = RUN_DIR / "metrics_summary.json"
OUTPUTS = [
    SUMMARY_PATH,
    RUN_DIR / "pr_metrics.csv",
    RUN_DIR / "ap_metrics.csv",
    RUN_DIR / "confusion_matrix.csv",
    RUN_DIR / "anchor_iou_diagnostics.csv",
    RUN_DIR / "size_recall.csv",
    RUN_DIR / "tile_boundary_anchors.csv",
    RUN_DIR / "loss_decomposition.csv",
    RUN_DIR / "loss_summary.csv",
    RUN_DIR / "ignore_ground_truth.csv",
    RUN_DIR / "unresolved_ignore_ground_truth.csv",
    RUN_DIR / "ignored_detections_summary.csv",
    RUN_DIR / "unmatched_detections.csv",
    RUN_DIR / "precision_recall_curve.png",
    *[RUN_DIR / f"overlay_frame_{frame}.png" for frame in (4196, 4706, 5306, 5816)],
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def box(row: dict[str, object]) -> list[float]:
    if "box" in row:
        return [float(value) for value in row["box"]]
    return [float(row[key]) for key in ("x1", "y1", "x2", "y2")]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_meta(path: Path, inputs: list[Path], review_status: str = "draft") -> None:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=PROJECT_ROOT,
    )
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=PROJECT_ROOT)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "worktree_clean": not status,
        "git_diff_sha256": hashlib.sha256(diff).hexdigest() if status else None,
        "analysis_script": "scripts/diagnostics/41_score_r01_detection_only.py",
        "analysis_script_sha256": sha256(Path(__file__)),
        "input_files": {
            str(path.relative_to(PROJECT_ROOT)): sha256(path) for path in inputs
        },
        "coordinate_system": "source_pixel",
        "unit": "px",
        "review_status": review_status,
        "artifact_path": str(path.relative_to(PROJECT_ROOT)),
        "artifact_sha256": sha256(path),
    }
    Path(f"{path}.meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def is_ignored_detection(
    detection: dict[str, object],
    ignore_rows: list[dict[str, object]],
    threshold: float,
) -> bool:
    for ignore in ignore_rows:
        if int(ignore["frame_index"]) != int(detection["frame_index"]):
            continue
        if not compatible(str(ignore["object_class"]), str(detection["object_class"])):
            continue
        db, ib = box(detection), box(ignore)
        intersection = max(0.0, min(db[2], ib[2]) - max(db[0], ib[0])) * max(
            0.0, min(db[3], ib[3]) - max(db[1], ib[1])
        )
        det_area = max(0.0, db[2] - db[0]) * max(0.0, db[3] - db[1])
        if det_area and intersection / det_area >= threshold:
            return True
    return False


def compatible(gt_class: str, auto_class: str) -> bool:
    return auto_class in {
        "person": {"person"},
        "car": {"car", "bus", "truck"},
        "motorcycle": {"motorcycle"},
    }.get(gt_class, set())


def main() -> int:
    occupied = [path for output in OUTPUTS
                for path in (output, Path(f"{output}.meta.json")) if path.exists()]
    if occupied:
        raise FileExistsError(f"Refusing to overwrite analysis outputs: {occupied}")

    config, detection_meta, detection_rows = load_validated_detection_artifact(
        EVALUATION_CONFIG_PATH, DETECTION_PATH, DETECTION_META_PATH
    )
    gt_manifest = json.loads(GT_MANIFEST_PATH.read_text(encoding="utf-8"))
    frozen_gt = {
        "objects": (OBJECTS_PATH, gt_manifest["frozen_files"]["objects"]["sha256"]),
        "visibility_intervals": (
            VISIBILITY_PATH, gt_manifest["frozen_files"]["visibility_intervals"]["sha256"]
        ),
        "observations": (
            OBSERVATIONS_PATH, gt_manifest["frozen_files"]["observations"]["sha256"]
        ),
    }
    for name, (path, expected_sha) in frozen_gt.items():
        if sha256(path) != expected_sha:
            raise RuntimeError(f"Frozen GT SHA-256 mismatch ({name}): {path}")

    observations = [normalized_box_row(row) for row in read_csv(OBSERVATIONS_PATH)]
    objects = read_csv(OBJECTS_PATH)
    visibility = read_csv(VISIBILITY_PATH)
    skips = read_csv(SKIPS_PATH)
    baseline_rows = [normalized_box_row(row) for row in read_csv(BASELINE_TRACKS_PATH)]
    detections = [normalized_box_row(row) for row in detection_rows]
    task006 = json.loads(TASK006_METRICS_PATH.read_text(encoding="utf-8"))
    gt_config = config["ground_truth"]
    grid = list(range(
        int(gt_config["start_frame_index"]),
        int(gt_config["end_frame_index"]) + 1,
        int(gt_config["frame_step"]),
    ))
    complete_frames = complete_detection_frames(grid, visibility, observations)
    expected_complete_frames = task006["complete_frames"]
    if complete_frames != expected_complete_frames:
        raise RuntimeError(
            "Complete-frame list differs from TASK-006; stop before metric scoring."
        )
    recall_frames = {int(row["frame_index"]) for row in observations}
    detector_frames = set(detection_meta["frames"]["indices"])
    if not recall_frames <= detector_frames:
        raise RuntimeError("Detection outputs omit one or more GT observation frames.")

    ignore_rows, unresolved_ignore = build_ignore_ground_truth(
        observations, objects, visibility, skips, detector_frames
    )
    conf_points = [float(x) for x in config["matching"]["confidence_operating_points"]]
    iou_thresholds = [0.5, 0.3]
    class_names = ["person", "car", "motorcycle"]
    pr_rows: list[dict[str, object]] = []
    ignore_summary: list[dict[str, object]] = []
    for confidence in conf_points:
        for iou_threshold in iou_thresholds:
            p_metrics = detection_metrics(
                observations, detections, set(complete_frames), confidence,
                iou_threshold, ignore_ground_truth=ignore_rows,
            )
            r_metrics = detection_metrics(
                observations, detections, recall_frames, confidence,
                iou_threshold, ignore_ground_truth=ignore_rows,
            )
            for class_name in [*class_names, "all"]:
                precision = float(p_metrics[class_name]["precision"])
                recall = float(r_metrics[class_name]["recall"])
                pr_rows.append({
                    "confidence": confidence,
                    "iou_threshold": iou_threshold,
                    "class": class_name,
                    "tp_precision_scope": p_metrics[class_name]["tp"],
                    "fp_precision_scope": p_metrics[class_name]["fp"],
                    "precision_complete_frames": precision,
                    "tp_recall_scope": r_metrics[class_name]["tp"],
                    "fn_recall_scope": r_metrics[class_name]["fn"],
                    "recall_all_eligible_observations": recall,
                    "f1": 2 * precision * recall / (precision + recall)
                    if precision + recall else 0.0,
                    "ignored_detections_precision_scope": p_metrics[class_name]["ignored_detections"],
                    "ignored_detections_recall_scope": r_metrics[class_name]["ignored_detections"],
                })
                ignore_summary.append({
                    "confidence": confidence, "iou_threshold": iou_threshold,
                    "class": class_name,
                    "ignored_detections_complete_frames": p_metrics[class_name]["ignored_detections"],
                    "ignored_detections_all_GT_frames": r_metrics[class_name]["ignored_detections"],
                })

    complete_gt = [row for row in observations if int(row["frame_index"]) in complete_frames]
    complete_detections = [row for row in detections
                           if int(row["frame_index"]) in set(complete_frames)]
    complete_ignore = [row for row in ignore_rows
                       if int(row["frame_index"]) in set(complete_frames)]
    ap_rows: list[dict[str, object]] = []
    ap_iou_thresholds = [float(value) for value in config["matching"]["ap_iou_thresholds"]]
    max_detections = int(config["matching"]["coco"]["max_detections"])
    for class_name in class_names:
        values = {}
        for threshold in ap_iou_thresholds:
            value = average_precision(
                complete_gt, complete_detections, threshold, class_name,
                max_detections=max_detections,
                ignore_ground_truth=complete_ignore,
            )
            values[threshold] = value
            ap_rows.append({
                "class": class_name, "iou_threshold": threshold,
                "AP": value, "area_range": "all", "max_detections": max_detections,
            })
        ap_rows.append({
            "class": class_name, "iou_threshold": "0.50:0.95",
            "AP": float(np.mean(list(values.values()))),
            "area_range": "all", "max_detections": max_detections,
        })

    confusion, unmatched_rows = build_confusion_and_unmatched(
        complete_gt, complete_detections, complete_ignore, 0.5
    )
    anchor_iou_rows, anchor_iou_summary = build_iou_diagnostics(
        observations, detections, recall_frames, 0.01
    )
    size_rows = build_size_recall(observations, detections, recall_frames, 0.15, 0.5)

    baseline_detection = json.loads((PROJECT_ROOT / "configs/baseline.json").read_text())[
        "detection"
    ]
    slices = make_slices(
        3840, 2160, int(baseline_detection["slice_width"]),
        int(baseline_detection["slice_height"]), float(baseline_detection["slice_overlap"]),
    )
    boundary_rows, boundary_summary = build_tile_boundary_diagnostics(
        observations, detections, recall_frames, slices
    )
    loss_rows = decompose_tracker_loss(
        observations, detections, baseline_rows, detector_frames,
        detection_confidence=0.15, track_start_confidence=0.25, iou_threshold=0.5,
    )
    loss_summary = summarize_loss(loss_rows, boundary_rows)
    draw_precision_recall(
        observations, detections, set(complete_frames), ignore_rows,
        conf_points=np.linspace(0.01, 0.95, 40),
    )
    overlay_paths = draw_overlays(
        (4196, 4706, 5306, 5816), observations, detections, slices
    )

    summary = {
        "schema_version": "r01_detection_only_metrics_v1",
        "evaluation_run_id": config["evaluation_run_id"],
        "a_run_git_commit": detection_meta["git_commit"],
        "device": detection_meta["device"], "gpu_name": detection_meta["gpu_name"],
        "video_sha256": detection_meta["video"]["sha256"],
        "config_sha256": detection_meta["configuration"]["sha256"],
        "weights_sha256": detection_meta["weights"]["sha256"],
        "gt_observations_sha256": detection_meta["frame_selection_ground_truth"]["sha256"],
        "frame_read_method": detection_meta["frame_read_method"],
        "detection_frame_count": len(detector_frames),
        "detection_frame_indices": sorted(detector_frames),
        "complete_frames": complete_frames,
        "complete_frame_count": len(complete_frames),
        "gt_observation_count": len(observations),
        "pr_metrics": pr_rows,
        "ap_metrics": ap_rows,
        "ignored_ground_truth_count": len(ignore_rows),
        "ignored_ground_truth_by_reason": dict(Counter(
            str(row["ignore_reason"]) for row in ignore_rows
        )),
        "ignored_detection_counts": ignore_summary,
        "unresolved_ignore_ground_truth_count": len(unresolved_ignore),
        "tile_diagnostics": {
            "rows": len(read_csv(TILE_PATH)),
            "confidence_thresholds": sorted({
                float(row["confidence_threshold"]) for row in read_csv(TILE_PATH)
            }),
            "max_detections_per_tile": max(
                int(row["detection_count"]) for row in read_csv(TILE_PATH)
            ),
            "configured_max_det": max(int(row["max_det"]) for row in read_csv(TILE_PATH)),
            "max_det_reached_tiles": sum(
                row["max_det_reached"].lower() == "true" for row in read_csv(TILE_PATH)
            ),
        },
        "unmatched_detection_count": len(unmatched_rows),
        "anchor_iou_summary": anchor_iou_summary,
        "size_recall": size_rows,
        "tile_boundary_summary": boundary_summary,
        "loss_summary": loss_summary,
        "b_execution_guidance": vehicle_guidance(loss_rows, boundary_rows),
        "confusion_matrix": confusion,
        "limitations": [
            "A single 60-second GT segment; motorcycle GT covers 3 objects.",
            "Precision is provisional until unmatched detections are adjudicated.",
            "Do not select operational confidence or detector settings using this GT segment.",
        ],
        "review_status": "provisional_automatic",
    }

    write_csv(RUN_DIR / "pr_metrics.csv", pr_rows)
    write_csv(RUN_DIR / "ap_metrics.csv", ap_rows)
    write_csv(RUN_DIR / "confusion_matrix.csv", confusion_rows(confusion))
    write_csv(RUN_DIR / "anchor_iou_diagnostics.csv", anchor_iou_rows)
    write_csv(RUN_DIR / "size_recall.csv", size_rows)
    write_csv(RUN_DIR / "tile_boundary_anchors.csv", boundary_rows)
    write_csv(RUN_DIR / "loss_decomposition.csv", loss_rows)
    write_csv(RUN_DIR / "loss_summary.csv", loss_summary)
    write_csv(RUN_DIR / "ignore_ground_truth.csv", ignore_rows)
    write_csv(RUN_DIR / "unresolved_ignore_ground_truth.csv", unresolved_ignore)
    write_csv(RUN_DIR / "ignored_detections_summary.csv", ignore_summary)
    write_csv(RUN_DIR / "unmatched_detections.csv", unmatched_rows)
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    common_inputs = [
        DETECTION_PATH, DETECTION_META_PATH, TILE_PATH, BASELINE_TRACKS_PATH,
        OBSERVATIONS_PATH, OBJECTS_PATH, VISIBILITY_PATH, SKIPS_PATH,
        GT_MANIFEST_PATH, TASK006_METRICS_PATH, EVALUATION_CONFIG_PATH,
    ]
    for output in OUTPUTS:
        if output.exists():
            write_meta(output, common_inputs, "provisional_automatic")
    print(json.dumps({
        "status": "checkpoint_2_ready",
        "summary_path": str(SUMMARY_PATH.relative_to(PROJECT_ROOT)),
        "complete_frames": len(complete_frames),
        "unmatched_detections": len(unmatched_rows),
        "overlays": [str(path.relative_to(PROJECT_ROOT)) for path in overlay_paths],
        "b_execution_guidance": summary["b_execution_guidance"],
    }, ensure_ascii=False, indent=2))
    return 0


def build_confusion_and_unmatched(gt_rows, detections, ignore_rows, threshold):
    gt_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    det_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in gt_rows:
        gt_by_frame[int(row["frame_index"])].append(row)
    for row in detections:
        if float(row["confidence"]) >= 0.15:
            det_by_frame[int(row["frame_index"])].append(row)
    auto_classes = sorted({str(row["object_class"]) for row in detections})
    matrix = {
        gt_class: {**{auto_class: 0 for auto_class in auto_classes}, "miss": 0}
        for gt_class in ("person", "car", "motorcycle")
    }
    matrix["FP"] = {**{auto_class: 0 for auto_class in auto_classes}, "miss": 0}
    matrix["ignored"] = {**{auto_class: 0 for auto_class in auto_classes}, "miss": 0}
    unmatched = []
    for frame in sorted(set(gt_by_frame) | set(det_by_frame)):
        frame_gt, frame_det = gt_by_frame.get(frame, []), det_by_frame.get(frame, [])
        matches = match_frame(frame_gt, frame_det, threshold)
        gt_matched = {i for i, _, _ in matches}
        det_matched = {j for _, j, _ in matches}
        for gi, di, iou in matches:
            gt_class = str(frame_gt[gi]["object_class"])
            det_class = str(frame_det[di]["object_class"])
            matrix.setdefault(gt_class, {}).setdefault(det_class, 0)
            matrix[gt_class][det_class] += 1
        for gi, gt in enumerate(frame_gt):
            if gi not in gt_matched:
                matrix[str(gt["object_class"])]["miss"] += 1
        for di, row in enumerate(frame_det):
            if di in det_matched:
                continue
            ignored = is_ignored_detection(row, ignore_rows, threshold)
            class_name = str(row["object_class"])
            destination = "ignored" if ignored else "FP"
            matrix[destination].setdefault(class_name, 0)
            matrix[destination][class_name] += 1
            unmatched.append({
                "frame_index": frame,
                "object_class": class_name,
                "confidence": float(row["confidence"]),
                "x1": float(row["x1"]), "y1": float(row["y1"]),
                "x2": float(row["x2"]), "y2": float(row["y2"]),
                "tile_center_candidate_ids": row.get("tile_center_candidate_ids", ""),
                "audit_status": "ignore_candidate" if ignored else "uncertain",
                "review_status": "draft",
            })
    return matrix, unmatched


def confusion_rows(matrix):
    rows = []
    for gt_class, predictions in matrix.items():
        for predicted_class, count in predictions.items():
            rows.append({
                "ground_truth_class": gt_class,
                "prediction_class": predicted_class,
                "count": count,
            })
    return rows


def build_iou_diagnostics(observations, detections, frames, confidence_floor):
    detections_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in detections:
        if int(row["frame_index"]) in frames and float(row["confidence"]) >= confidence_floor:
            detections_by_frame[int(row["frame_index"])].append(row)
    rows = []
    counts: dict[str, Counter] = defaultdict(Counter)
    for gt in observations:
        frame = int(gt["frame_index"])
        candidates = detections_by_frame.get(frame, [])
        overlaps = [(row, box_iou(box(gt), box(row))) for row in candidates]
        best_row, best_iou = max(overlaps, key=lambda item: item[1], default=(None, 0.0))
        if best_iou <= 0:
            band = "no_overlap"
        elif best_iou < 0.3:
            band = "0_to_0.3"
        elif best_iou < 0.5:
            band = "0.3_to_0.5"
        else:
            band = "at_least_0.5"
        cls = str(gt["object_class"])
        counts[cls][band] += 1
        rows.append({
            "gt_object_id": gt["gt_object_id"], "frame_index": frame,
            "object_class": cls, "best_iou_conf_ge_0_01": best_iou,
            "iou_band": band,
            "best_detection_class": best_row["object_class"] if best_row else "",
            "best_detection_confidence": best_row["confidence"] if best_row else "",
        })
    return rows, {cls: dict(counter) for cls, counter in counts.items()}


def build_size_recall(observations, detections, frames, confidence, iou_threshold):
    output = []
    gt_by_class_frame: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    detections_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in observations:
        gt_by_class_frame[(str(row["object_class"]), int(row["frame_index"]))].append(row)
    for row in detections:
        if int(row["frame_index"]) in frames and float(row["confidence"]) >= confidence:
            detections_by_frame[int(row["frame_index"])].append(row)
    for class_name in ("person", "car", "motorcycle"):
        class_rows = [row for row in observations if row["object_class"] == class_name]
        areas = np.asarray([
            max(0.0, float(row["x2"]) - float(row["x1"]))
            * max(0.0, float(row["y2"]) - float(row["y1"]))
            for row in class_rows
        ])
        q1, q2 = np.quantile(areas, [1 / 3, 2 / 3])
        bucket_counts = Counter()
        bucket_matches = Counter()
        by_frame_gt: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in class_rows:
            by_frame_gt[int(row["frame_index"])].append(row)
        for frame, gt_frame in by_frame_gt.items():
            preds = [row for row in detections_by_frame.get(frame, [])
                     if compatible(class_name, str(row["object_class"]))]
            pairs = match_frame(gt_frame, preds, iou_threshold)
            matched = {gi for gi, _, _ in pairs}
            for index, row in enumerate(gt_frame):
                width = float(row["x2"]) - float(row["x1"])
                height = float(row["y2"]) - float(row["y1"])
                area = max(0.0, width * height)
                bucket = "small" if area <= q1 else "medium" if area <= q2 else "large"
                bucket_counts[bucket] += 1
                bucket_matches[bucket] += index in matched
        for bucket in ("small", "medium", "large"):
            denominator = bucket_counts[bucket]
            output.append({
                "class": class_name, "size_tertile": bucket,
                "area_q1_pixels2": float(q1), "area_q2_pixels2": float(q2),
                "matched": bucket_matches[bucket], "anchors": denominator,
                "recall": bucket_matches[bucket] / denominator if denominator else 0.0,
                "confidence": confidence, "iou_threshold": iou_threshold,
            })
    return output


def build_tile_boundary_diagnostics(observations, detections, frames, slices):
    detections_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in detections:
        if int(row["frame_index"]) in frames:
            detections_by_frame[int(row["frame_index"])].append(row)
    matched_gt_keys: set[tuple[str, int]] = set()
    for class_name in ("person", "car", "motorcycle"):
        gt_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
        for gt in observations:
            if str(gt["object_class"]) == class_name:
                gt_by_frame[int(gt["frame_index"])].append(gt)
        for frame, gt_frame in gt_by_frame.items():
            preds = [
                row for row in detections_by_frame.get(frame, [])
                if float(row["confidence"]) >= 0.15
                and compatible(class_name, str(row["object_class"]))
            ]
            for gt_index, _, _ in match_frame(gt_frame, preds, 0.5):
                gt = gt_frame[gt_index]
                matched_gt_keys.add((str(gt["gt_object_id"]), int(gt["frame_index"])))

    rows = []
    boundary_vehicle = matched_boundary_vehicle = missed_boundary_vehicle = 0
    for gt in observations:
        gt_box = box(gt)
        contained = any(
            gt_box[0] >= x1 and gt_box[1] >= y1 and gt_box[2] <= x2 and gt_box[3] <= y2
            for x1, y1, x2, y2 in slices
        )
        if contained:
            continue
        frame = int(gt["frame_index"])
        cls = str(gt["object_class"])
        candidates = [row for row in detections_by_frame.get(frame, [])
                      if float(row["confidence"]) >= 0.01
                      and compatible(cls, str(row["object_class"]))]
        overlaps = [row for row in candidates if box_iou(gt_box, box(row)) > 0]
        official = (
            (str(gt["gt_object_id"]), frame) in matched_gt_keys
        )
        vehicle = cls in {"car", "motorcycle"}
        if vehicle:
            boundary_vehicle += 1
            matched_boundary_vehicle += official
            missed_boundary_vehicle += not official
        rows.append({
            "gt_object_id": gt["gt_object_id"], "frame_index": frame,
            "object_class": cls, "box_fully_contained_in_any_tile": False,
            "positive_overlap_candidates_conf_ge_0_01": len(overlaps),
            "multiple_overlap_candidates": len(overlaps) > 1,
            "matched_conf_ge_0_15_iou_ge_0_5": official,
            "vehicle_anchor": vehicle,
        })
    summary = {
        "boundary_anchor_count": len(rows),
        "boundary_vehicle_anchor_count": boundary_vehicle,
        "boundary_vehicle_matched_at_conf_0_15_iou_0_5": matched_boundary_vehicle,
        "boundary_vehicle_missed_at_conf_0_15_iou_0_5": missed_boundary_vehicle,
        "boundary_vehicle_recall": (
            matched_boundary_vehicle / boundary_vehicle if boundary_vehicle else 0.0
        ),
        "boundary_anchors_with_multiple_overlap_candidates": sum(
            bool(row["multiple_overlap_candidates"]) for row in rows
        ),
    }
    return rows, summary


def summarize_loss(loss_rows, boundary_rows):
    summaries = []
    boundary = {
        (str(row["gt_object_id"]), int(row["frame_index"])): bool(row["vehicle_anchor"])
        for row in boundary_rows
    }
    classes = sorted({str(row["object_class"]) for row in loss_rows})
    categories = sorted({str(row["category"]) for row in loss_rows})
    for cls in classes:
        for category in categories:
            selected = [row for row in loss_rows
                        if row["object_class"] == cls and row["category"] == category]
            if not selected:
                continue
            summaries.append({"object_class": cls, "category": category, "anchors": len(selected)})
    return summaries


def vehicle_guidance(loss_rows, boundary_rows):
    boundary_keys = {
        (str(row["gt_object_id"]), int(row["frame_index"]))
        for row in boundary_rows if row["vehicle_anchor"]
    }
    vehicle_rows = [row for row in loss_rows if row["object_class"] in {"car", "motorcycle"}]
    vehicle_misses = [row for row in vehicle_rows if row["category"] != "④_tracker_match"]
    boundary_misses = [row for row in vehicle_misses
                       if (str(row["gt_object_id"]), int(row["frame_index"])) in boundary_keys]
    category_counts = Counter(str(row["category"]) for row in vehicle_misses)
    return {
        "vehicle_gt_anchors": len(vehicle_rows),
        "vehicle_missed_or_untracked_anchors": len(vehicle_misses),
        "vehicle_misses_on_tile_boundary": len(boundary_misses),
        "vehicle_miss_tile_boundary_share": (
            len(boundary_misses) / len(vehicle_misses) if vehicle_misses else 0.0
        ),
        "vehicle_misses_by_category": dict(category_counts),
        "detector_miss_category_1": category_counts.get("①_no_conf_ge_0_15_detection", 0),
        "tracker_loss_categories_2_3": (
            category_counts.get("②_conf_0_15_to_0_25_only", 0)
            + category_counts.get("③_conf_ge_0_25_missing_from_tracks", 0)
        ),
        "reproducibility_anomalies": category_counts.get(
            "reproducibility_anomaly_tracker_without_conf_ge_0_15_match", 0
        ),
    }


def draw_precision_recall(observations, detections, frames, ignore_rows, conf_points):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for axis, cls in zip(axes, ("person", "car", "motorcycle")):
        points = []
        for confidence in conf_points:
            metrics = detection_metrics(
                observations, detections, frames, float(confidence), 0.5,
                classes=(cls,), ignore_ground_truth=ignore_rows,
            )[cls]
            points.append((float(metrics["recall"]), float(metrics["precision"])))
        points.sort(key=lambda item: item[0])
        axis.plot([p[0] for p in points], [p[1] for p in points], marker=".")
        axis.set(title=cls, xlabel="Recall", ylabel="Precision", xlim=(0, 1), ylim=(0, 1))
        axis.grid(True, alpha=0.3)
    fig.savefig(RUN_DIR / "precision_recall_curve.png", dpi=160)
    plt.close(fig)


def draw_overlays(frame_indices, observations, detections, slices):
    video_path = PROJECT_ROOT / "data/raw/before/DJI_0482.MP4"
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise OSError(f"Cannot open source video: {video_path}")
    paths = []
    try:
        for frame_index in frame_indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            decoded = int(round(capture.get(cv2.CAP_PROP_POS_FRAMES))) - 1
            if not ok or decoded != frame_index:
                raise RuntimeError(f"Overlay frame seek mismatch at {frame_index}")
            canvas = frame.copy()
            gt_rows = [row for row in observations if int(row["frame_index"]) == frame_index]
            det_rows = [row for row in detections
                        if int(row["frame_index"]) == frame_index
                        and float(row["confidence"]) >= 0.15]
            for row in gt_rows:
                x1, y1, x2, y2 = map(int, box(row))
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(canvas, f"GT {row['gt_object_id']}", (x1, max(18, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
            for row in det_rows:
                x1, y1, x2, y2 = map(int, box(row))
                label = f"{row['object_class']} {float(row['confidence']):.2f}"
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(canvas, label, (x1, min(canvas.shape[0] - 4, y2 + 16)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 255), 1, cv2.LINE_AA)
            path = RUN_DIR / f"overlay_frame_{frame_index}.png"
            if not cv2.imwrite(str(path), canvas):
                raise OSError(f"Could not write overlay: {path}")
            paths.append(path)
    finally:
        capture.release()
    return paths


if __name__ == "__main__":
    raise SystemExit(main())
