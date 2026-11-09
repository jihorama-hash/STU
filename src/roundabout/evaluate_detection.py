"""Score raw detections against the frozen R01 object annotations."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from typing import Iterable

import numpy as np
import yaml
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval

from .evaluate_object_track import (
    box_iou, class_compatible, match_frame, select_complete_frames,
)


class DetectionEvaluationError(ValueError):
    """Raised when detection outputs disagree with the approved evaluation config."""


def normalized_box_row(row: dict[str, object]) -> dict[str, object]:
    """Return a row in the box schema shared with the trajectory scorer."""
    if "box" in row:
        return row
    return {**row, "box": [row[key] for key in ("x1", "y1", "x2", "y2")]}


def validate_inference_metadata(
    evaluation_config: dict[str, object], detection_meta: dict[str, object]
) -> None:
    """Stop before scoring when inference settings differ from the evaluation YAML."""
    expected = evaluation_config["inference"]
    actual = detection_meta.get("detector_settings")
    if not isinstance(actual, dict):
        raise DetectionEvaluationError("Detection metadata lacks detector_settings")
    comparisons = {
        "model": expected["model"],
        "weights": expected["weights"],
        "class_profile": expected["class_profile"],
        "slice_width": expected["slice_width"],
        "slice_height": expected["slice_height"],
        "slice_overlap": expected["slice_overlap"],
        "image_size": expected["image_size"],
        "nms_iou": expected["nms_iou"],
        "pass_id": expected["pass_id"],
        "max_det_per_tile": evaluation_config["frames"]["max_detections_per_tile"],
    }
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in comparisons.items() if actual.get(key) != value
    }
    ground_truth_config = evaluation_config["ground_truth"]
    expected_confidence = ground_truth_config["confidence_floor"]
    if detection_meta.get("confidence_threshold") != expected_confidence:
        mismatches["confidence_threshold"] = {
            "expected": expected_confidence,
            "actual": detection_meta.get("confidence_threshold"),
        }
    if mismatches:
        raise DetectionEvaluationError(
            f"Detection output does not match evaluation YAML inference settings: {mismatches}"
        )


def load_evaluation_config(path) -> dict[str, object]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise DetectionEvaluationError("Evaluation config must be a YAML mapping")
    return config


def load_validated_detection_artifact(
    evaluation_config_path, detection_csv_path, detection_meta_path,
    expected_frame_indices: list[int] | None = None,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, str]]]:
    """Validate inference settings before any detection scoring begins."""
    config = load_evaluation_config(evaluation_config_path)
    meta = json.loads(detection_meta_path.read_text(encoding="utf-8"))
    validate_inference_metadata(config, meta)
    if expected_frame_indices is not None:
        actual_frames = meta.get("frames", {}).get("indices")
        if actual_frames != expected_frame_indices:
            raise DetectionEvaluationError(
                "Detection metadata frame list does not match the GT/grid union"
            )
    with detection_csv_path.open(encoding="utf-8-sig", newline="") as stream:
        detections = list(csv.DictReader(stream))
    return config, meta, detections


def complete_detection_frames(
    grid_frames: list[int],
    visibility_rows: list[dict[str, object]],
    observation_rows: list[dict[str, object]],
) -> list[int]:
    """Use the trajectory evaluator's definition of complete GT frames."""
    eligible: dict[int, set[str]] = defaultdict(set)
    observed: dict[int, set[str]] = defaultdict(set)
    ignored_anchors = {
        (str(row["gt_object_id"]), int(row["frame_index"]))
        for row in observation_rows
        if str(row.get("ignore", "false")).lower() == "true"
    }
    for row in visibility_rows:
        if str(row.get("in_scope", "true")).lower() != "true":
            continue
        if str(row.get("denominator_eligible", "true")).lower() != "true":
            continue
        start = int(row["start_frame_index"])
        end = int(row["end_frame_index"])
        for frame in grid_frames:
            if start <= frame <= end and (
                str(row["gt_object_id"]), frame
            ) not in ignored_anchors:
                eligible[frame].add(str(row["gt_object_id"]))
    for row in observation_rows:
        if (
            str(row.get("in_scope", "true")).lower() == "true"
            and str(row.get("ignore", "false")).lower() != "true"
        ):
            observed[int(row["frame_index"])].add(str(row["gt_object_id"]))
    return select_complete_frames(grid_frames, eligible, observed)


def build_ignore_ground_truth(
    observations: list[dict[str, object]],
    objects: list[dict[str, object]],
    visibility_rows: list[dict[str, object]],
    skip_rows: list[dict[str, object]],
    frame_indices: set[int],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Interpolate manual boxes for excluded/occluded GT and mark them crowd GT."""
    object_classes = {str(row["gt_object_id"]): str(row["object_class"])
                      for row in objects}
    observations_by_object: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw_row in observations:
        row = normalized_box_row(raw_row)
        if str(row.get("observation_method", "manual")) == "manual":
            observations_by_object[str(row["gt_object_id"])].append(row)
    for rows in observations_by_object.values():
        rows.sort(key=lambda row: int(row["frame_index"]))

    requests: set[tuple[str, int, str]] = set()
    for row in visibility_rows:
        excluded = str(row.get("in_scope", "true")).lower() != "true"
        fully_hidden = str(row.get("visibility_status", "")) == "fully_occluded"
        if not (excluded or fully_hidden):
            continue
        object_id = str(row["gt_object_id"])
        reason = "in_scope_false" if excluded else "fully_occluded"
        start, end = int(row["start_frame_index"]), int(row["end_frame_index"])
        requests.update(
            (object_id, frame, reason) for frame in frame_indices if start <= frame <= end
        )
    requests.update(
        (str(row["gt_object_id"]), int(row["frame_index"]), "reviewed_skip")
        for row in skip_rows if int(row["frame_index"]) in frame_indices
    )

    ignore_rows: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    for object_id, frame, reason in sorted(requests):
        anchors = observations_by_object.get(object_id, [])
        before = [row for row in anchors if int(row["frame_index"]) < frame]
        after = [row for row in anchors if int(row["frame_index"]) > frame]
        if not before or not after:
            unresolved.append({
                "gt_object_id": object_id, "frame_index": frame,
                "ignore_reason": reason, "status": "missing_bracketing_manual_boxes",
            })
            continue
        left, right = before[-1], after[0]
        left_frame, right_frame = int(left["frame_index"]), int(right["frame_index"])
        ratio = (frame - left_frame) / (right_frame - left_frame)
        left_box = [float(left[key]) for key in ("x1", "y1", "x2", "y2")]
        right_box = [float(right[key]) for key in ("x1", "y1", "x2", "y2")]
        box = [a + ratio * (b - a) for a, b in zip(left_box, right_box)]
        ignore_rows.append({
            "frame_index": frame, "gt_object_id": object_id,
            "object_class": object_classes[object_id], "box": box,
            "iscrowd": 1, "ignore_reason": reason,
            "interpolation_method": "linear_between_bracketing_manual_observations",
        })
    return ignore_rows, unresolved


def detection_metrics(
    ground_truth: list[dict[str, object]],
    detections: list[dict[str, object]],
    frames: set[int],
    confidence: float,
    iou_threshold: float,
    classes: Iterable[str] = ("person", "car", "motorcycle"),
    ignore_ground_truth: list[dict[str, object]] | None = None,
) -> dict[str, dict[str, float | int]]:
    """Compute per-class P/R/F1 and ignore unmatched detections overlapping crowd GT."""
    selected_gt = [normalized_box_row(g) for g in ground_truth
                   if int(g["frame_index"]) in frames]
    selected_detections = [
        normalized_box_row(d) for d in detections
        if int(d["frame_index"]) in frames and float(d["confidence"]) >= confidence
    ]
    result: dict[str, dict[str, float | int]] = {}
    for object_class in [*classes, "all"]:
        gt_rows = selected_gt if object_class == "all" else [
            g for g in selected_gt if str(g["object_class"]) == object_class
        ]
        det_rows = selected_detections if object_class == "all" else [
            d for d in selected_detections
            if class_compatible(object_class, str(d["object_class"]))
        ]
        gt_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
        det_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in gt_rows:
            gt_by_frame[int(row["frame_index"])].append(row)
        for row in det_rows:
            det_by_frame[int(row["frame_index"])].append(row)
        ignore_rows = [
            row for row in (ignore_ground_truth or [])
            if object_class == "all" or class_compatible(
                object_class, str(row["object_class"])
            )
        ]
        ignore_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in ignore_rows:
            ignore_by_frame[int(row["frame_index"])].append(row)
        tp = ignored_count = 0
        for frame in frames:
            gt = gt_by_frame.get(frame, [])
            det = det_by_frame.get(frame, [])
            pairs = match_frame(gt, det, iou_threshold)
            valid_pairs = [
                (gi, di) for gi, di, _ in pairs
                if class_compatible(
                    str(gt[gi]["object_class"]), str(det[di]["object_class"])
                )
            ]
            tp += len(valid_pairs)
            matched_detections = {di for _, di in valid_pairs}
            for index, row in enumerate(det):
                if index in matched_detections:
                    continue
                if any(
                    class_compatible(
                        str(ignore_row["object_class"]), str(row["object_class"])
                    )
                    and _intersection_over_detection(
                        row["box"], normalized_box_row(ignore_row)["box"]
                    )
                    >= iou_threshold
                    for ignore_row in ignore_by_frame.get(frame, [])
                ):
                    ignored_count += 1
        fp = len(det_rows) - tp - ignored_count
        fn = len(gt_rows) - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        result[object_class] = {
            "tp": tp, "fp": fp, "fn": fn,
            "ignored_detections": ignored_count,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall)
            if precision + recall else 0.0,
        }
    return result


def average_precision(
    ground_truth: list[dict[str, object]],
    detections: list[dict[str, object]],
    iou_threshold: float,
    object_class: str,
    max_detections: int,
    ignore_ground_truth: list[dict[str, object]] | None = None,
) -> float:
    """Use COCOeval with one all-area range and one configured maxDets value."""
    gt_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for raw_row in ground_truth:
        row = normalized_box_row(raw_row)
        if str(row["object_class"]) == object_class:
            gt_by_frame[int(row["frame_index"])].append(row)
    crowd_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for raw_row in ignore_ground_truth or []:
        row = normalized_box_row(raw_row)
        if class_compatible(object_class, str(row["object_class"])):
            crowd_by_frame[int(row["frame_index"])].append(row)
    gt_count = sum(map(len, gt_by_frame.values()))
    if gt_count == 0:
        return 0.0
    frame_ids = sorted(
        set(gt_by_frame) | set(crowd_by_frame) | {int(d["frame_index"]) for d in detections}
    )
    coco_gt = COCO()
    annotations = []
    annotation_id = 1
    for frame, rows in gt_by_frame.items():
        for row in rows:
            box = [float(value) for value in row["box"]]
            annotations.append({
                "id": annotation_id, "image_id": frame, "category_id": 1,
                "bbox": [box[0], box[1], box[2] - box[0], box[3] - box[1]],
                "area": max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1]),
                "iscrowd": 0,
            })
            annotation_id += 1
    for frame, rows in crowd_by_frame.items():
        for row in rows:
            box = [float(value) for value in row["box"]]
            annotations.append({
                "id": annotation_id, "image_id": frame, "category_id": 1,
                "bbox": [box[0], box[1], box[2] - box[0], box[3] - box[1]],
                "area": max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1]),
                "iscrowd": 1,
            })
            annotation_id += 1
    coco_gt.dataset = {
        "images": [{"id": frame, "width": 3840, "height": 2160} for frame in frame_ids],
        "annotations": annotations,
        "categories": [{"id": 1, "name": object_class}],
    }
    coco_gt.createIndex()
    result_rows = []
    for raw_row in detections:
        row = normalized_box_row(raw_row)
        if not class_compatible(object_class, str(row["object_class"])):
            continue
        box = row["box"]
        x1, y1, x2, y2 = map(float, box)
        result_rows.append({
            "image_id": int(row["frame_index"]), "category_id": 1,
            "bbox": [x1, y1, x2 - x1, y2 - y1],
            "score": float(row["confidence"]),
        })
    if not result_rows:
        return 0.0
    coco_dt = coco_gt.loadRes(result_rows)
    evaluator = COCOeval(coco_gt, coco_dt, "bbox")
    evaluator.params.imgIds = frame_ids
    evaluator.params.catIds = [1]
    evaluator.params.iouThrs = np.asarray([iou_threshold])
    evaluator.params.areaRng = [[0.0, 1e10]]
    evaluator.params.areaRngLbl = ["all"]
    evaluator.params.maxDets = [max_detections]
    evaluator.evaluate()
    evaluator.accumulate()
    precision = evaluator.eval["precision"][:, :, :, 0, 0]
    valid = precision[precision > -1]
    return float(valid.mean()) if valid.size else 0.0


def configured_average_precision(
    evaluation_config: dict[str, object],
    ground_truth: list[dict[str, object]],
    detections: list[dict[str, object]],
    iou_threshold: float,
    object_class: str,
    ignore_ground_truth: list[dict[str, object]] | None = None,
) -> float:
    """Call COCOeval using the single maxDets value recorded in the YAML."""
    maximum = int(evaluation_config["matching"]["coco"]["max_detections"])
    return average_precision(
        ground_truth, detections, iou_threshold, object_class,
        max_detections=maximum, ignore_ground_truth=ignore_ground_truth,
    )


def _intersection_over_detection(detection_box, ignore_box) -> float:
    dx1, dy1, dx2, dy2 = map(float, detection_box)
    ix1, iy1, ix2, iy2 = map(float, ignore_box)
    intersection = max(0.0, min(dx2, ix2) - max(dx1, ix1)) * max(
        0.0, min(dy2, iy2) - max(dy1, iy1)
    )
    area = max(0.0, dx2 - dx1) * max(0.0, dy2 - dy1)
    return intersection / area if area else 0.0


def rider_inside_vehicle_sensitivity(
    detections: list[dict[str, object]],
    matched_detection_indices: set[int],
    vehicle_ground_truth: list[dict[str, object]],
    evaluation_config: dict[str, object],
) -> dict[float, int]:
    """Count unmatched person detections contained by same-frame two-wheeler GT.

    The caller supplies detections from one matching scope (confidence and IoU
    threshold). Matched detections are excluded before the containment rule.
    """
    rule = evaluation_config["matching"]["rider_inside_vehicle"]
    configured = [float(value) for value in rule["sensitivity_thresholds"]]
    primary = float(rule["containment_threshold"])
    if primary not in configured:
        raise DetectionEvaluationError(
            "rider containment threshold must appear in sensitivity_thresholds"
        )
    allowed_classes = {"bicycle", "motorcycle"}
    vehicles_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for raw_row in vehicle_ground_truth:
        row = normalized_box_row(raw_row)
        if str(row["object_class"]) in allowed_classes:
            vehicles_by_frame[int(row["frame_index"])].append(row)

    ratios: list[float] = []
    for index, raw_row in enumerate(detections):
        row = normalized_box_row(raw_row)
        if index in matched_detection_indices or str(row["object_class"]) != "person":
            continue
        same_frame = vehicles_by_frame.get(int(row["frame_index"]), [])
        if not same_frame:
            continue
        ratios.append(max(
            _intersection_over_detection(row["box"], vehicle["box"])
            for vehicle in same_frame
        ))
    return {threshold: sum(ratio >= threshold for ratio in ratios) for threshold in configured}


def decompose_tracker_loss(
    ground_truth: list[dict[str, object]],
    detections: list[dict[str, object]],
    tracks: list[dict[str, object]],
    frame_indices: set[int],
    detection_confidence: float,
    track_start_confidence: float,
    iou_threshold: float,
) -> list[dict[str, object]]:
    """Class-agnostic Hungarian matches followed by TASK-006 class compatibility."""
    gt_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    detection_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    tracks_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in ground_truth:
        if int(row["frame_index"]) in frame_indices:
            gt_by_frame[int(row["frame_index"])].append(normalized_box_row(row))
    for row in detections:
        if int(row["frame_index"]) in frame_indices:
            detection_by_frame[int(row["frame_index"])].append(normalized_box_row(row))
    for row in tracks:
        if int(row["frame_index"]) in frame_indices:
            tracks_by_frame[int(row["frame_index"])].append(normalized_box_row(row))

    output: list[dict[str, object]] = []
    for frame in sorted(frame_indices):
        gt_rows = gt_by_frame.get(frame, [])
        detections_frame = detection_by_frame.get(frame, [])
        tracks_frame = tracks_by_frame.get(frame, [])
        detections_at_015 = [
            row for row in detections_frame
            if float(row["confidence"]) >= detection_confidence
        ]
        detections_at_025 = [
            row for row in detections_frame
            if float(row["confidence"]) >= track_start_confidence
        ]
        pairs_015 = match_frame(gt_rows, detections_at_015, iou_threshold)
        pairs_025 = match_frame(gt_rows, detections_at_025, iou_threshold)
        track_pairs = match_frame(gt_rows, tracks_frame, iou_threshold)

        def compatible_gt_indices(pairs, automatic_rows):
            return {
                gt_index for gt_index, auto_index, _ in pairs
                if class_compatible(
                    str(gt_rows[gt_index]["object_class"]),
                    str(automatic_rows[auto_index]["object_class"]),
                )
            }

        matched_015 = compatible_gt_indices(pairs_015, detections_at_015)
        matched_025 = compatible_gt_indices(pairs_025, detections_at_025)
        matched_tracks = compatible_gt_indices(track_pairs, tracks_frame)
        for index, gt in enumerate(gt_rows):
            if index in matched_tracks:
                if index in matched_015:
                    category = "④_tracker_match"
                else:
                    category = "reproducibility_anomaly_tracker_without_conf_ge_0_15_match"
            elif index in matched_025:
                category = "③_conf_ge_0_25_missing_from_tracks"
            elif index in matched_015:
                category = "②_conf_0_15_to_0_25_only"
            else:
                category = "①_no_conf_ge_0_15_detection"
            output.append({
                "frame_index": frame,
                "gt_object_id": gt.get("gt_object_id", ""),
                "object_class": gt["object_class"],
                "category": category,
            })
    return output
