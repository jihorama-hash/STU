"""Sliced YOLO detection and class-aware ByteTrack tracking."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
import torch
from ultralytics import YOLO

from .paths import resolve_project_path


CLASS_PROFILES = {
    "coco": {
        0: (0, "person", "person"),
        1: (1, "bicycle", "bicycle"),
        2: (2, "car", "car"),
        3: (3, "motorcycle", "motorcycle"),
        5: (5, "bus", "bus"),
        7: (7, "truck", "truck"),
    },
    "visdrone": {
        0: (0, "person", "pedestrian"),
        1: (0, "person", "people"),
        2: (1, "bicycle", "bicycle"),
        3: (2, "car", "car"),
        4: (2, "car", "van"),
        5: (7, "truck", "truck"),
        6: (10, "tricycle", "tricycle"),
        7: (10, "tricycle", "awning-tricycle"),
        8: (5, "bus", "bus"),
        9: (3, "motorcycle", "motor"),
    },
}

OUTPUT_FIELDS = [
    "video_id", "frame_index", "timestamp_seconds", "track_id",
    "class_id", "object_class", "source_class_id", "source_class_name",
    "confidence", "x1", "y1", "x2", "y2",
    "center_x", "center_y", "foot_x", "foot_y", "coordinate_system",
]


def make_slices(
    width: int, height: int, slice_width: int, slice_height: int, overlap: float
) -> list[tuple[int, int, int, int]]:
    if not 0 <= overlap < 1:
        raise ValueError("overlap must be in [0, 1)")
    step_x = max(1, int(slice_width * (1 - overlap)))
    step_y = max(1, int(slice_height * (1 - overlap)))
    xs = list(range(0, max(1, width - slice_width + 1), step_x))
    ys = list(range(0, max(1, height - slice_height + 1), step_y))
    if xs[-1] + slice_width < width:
        xs.append(max(0, width - slice_width))
    if ys[-1] + slice_height < height:
        ys.append(max(0, height - slice_height))
    return [
        (x, y, min(width, x + slice_width), min(height, y + slice_height))
        for y in ys for x in xs
    ]


def box_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    intersection = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
    other_area = np.maximum(0, boxes[:, 2] - boxes[:, 0]) * np.maximum(
        0, boxes[:, 3] - boxes[:, 1]
    )
    union = area + other_area - intersection
    return np.divide(
        intersection, union, out=np.zeros_like(intersection), where=union > 0
    )


def classwise_nms(
    boxes: np.ndarray, scores: np.ndarray, classes: np.ndarray, threshold: float
) -> np.ndarray:
    keep: list[int] = []
    for class_id in sorted(set(classes.tolist())):
        indices = np.flatnonzero(classes == class_id)
        order = indices[np.argsort(scores[indices])[::-1]]
        while order.size:
            current = int(order[0])
            keep.append(current)
            if order.size == 1:
                break
            ious = box_iou(boxes[current], boxes[order[1:]])
            order = order[1:][ious <= threshold]
    return np.asarray(keep, dtype=np.int64)


def match_source_details(
    tracked_boxes: np.ndarray,
    detection_boxes: np.ndarray,
    source_classes: np.ndarray,
    source_names: np.ndarray,
) -> list[tuple[int, str]]:
    """Recover source labels after ByteTrack drops custom detection data."""
    if len(tracked_boxes) and not len(detection_boxes):
        raise ValueError("Cannot match tracked boxes without source detections")
    matched: list[tuple[int, str]] = []
    for tracked_box in tracked_boxes:
        index = int(np.argmax(box_iou(tracked_box, detection_boxes)))
        matched.append((int(source_classes[index]), str(source_names[index])))
    return matched


def detect_sliced(
    model: YOLO,
    frame: np.ndarray,
    slices: list[tuple[int, int, int, int]],
    confidence: float,
    nms_iou: float,
    image_size: int,
    device: int | str,
    class_profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    profile = CLASS_PROFILES[class_profile]
    tiles = [frame[y1:y2, x1:x2] for x1, y1, x2, y2 in slices]
    results = model.predict(
        tiles,
        conf=confidence,
        iou=nms_iou,
        classes=list(profile),
        imgsz=image_size,
        device=device,
        verbose=False,
    )
    boxes: list[list[float]] = []
    scores: list[float] = []
    classes: list[int] = []
    source_classes: list[int] = []
    source_names: list[str] = []
    for result, (origin_x, origin_y, _, _) in zip(results, slices):
        if result.boxes is None:
            continue
        for box, score, class_id in zip(
            result.boxes.xyxy.cpu().numpy(),
            result.boxes.conf.cpu().numpy(),
            result.boxes.cls.cpu().numpy().astype(int),
        ):
            boxes.append([
                float(box[0] + origin_x), float(box[1] + origin_y),
                float(box[2] + origin_x), float(box[3] + origin_y),
            ])
            scores.append(float(score))
            mapped_class_id, _, source_name = profile[int(class_id)]
            classes.append(mapped_class_id)
            source_classes.append(int(class_id))
            source_names.append(source_name)
    if not boxes:
        return (
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=int),
            np.empty((0,), dtype=int),
            np.empty((0,), dtype=object),
        )
    box_array = np.asarray(boxes, dtype=np.float32)
    score_array = np.asarray(scores, dtype=np.float32)
    class_array = np.asarray(classes, dtype=int)
    source_class_array = np.asarray(source_classes, dtype=int)
    source_name_array = np.asarray(source_names, dtype=object)
    keep = classwise_nms(box_array, score_array, class_array, nms_iou)
    return (
        box_array[keep],
        score_array[keep],
        class_array[keep],
        source_class_array[keep],
        source_name_array[keep],
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    video_path = resolve_project_path(args.video)
    model_path = resolve_project_path(args.model)
    output_dir = resolve_project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise FileNotFoundError(video_path)
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_frame = math.floor(args.start_seconds * fps)
    end_frame = math.ceil(args.end_seconds * fps)
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    device: int | str = 0 if torch.cuda.is_available() else "cpu"
    model = YOLO(str(model_path))
    profile = CLASS_PROFILES[args.class_profile]
    target_classes = {
        mapped_id: mapped_name
        for mapped_id, mapped_name, _ in profile.values()
    }
    slices = make_slices(
        width, height, args.slice_width, args.slice_height, args.overlap
    )
    trackers = {
        class_id: sv.ByteTrack(
            track_activation_threshold=args.confidence,
            lost_track_buffer=round(args.lost_seconds * fps / args.frame_step),
            minimum_matching_threshold=args.matching_threshold,
            frame_rate=fps / args.frame_step,
            minimum_consecutive_frames=1,
        )
        for class_id in target_classes
    }
    id_map: dict[tuple[int, int], int] = {}
    next_id = 1
    rows: list[dict[str, object]] = []
    class_counts: Counter[str] = Counter()
    processed = 0
    started = time.perf_counter()
    frame_index = start_frame

    while frame_index < end_frame:
        ok, frame = capture.read()
        if not ok:
            break
        if (frame_index - start_frame) % args.frame_step:
            frame_index += 1
            continue
        boxes, scores, classes, source_classes, source_names = detect_sliced(
            model, frame, slices, args.confidence, args.nms_iou, args.image_size,
            device, args.class_profile
        )
        for class_id, class_name in target_classes.items():
            mask = classes == class_id
            detections = sv.Detections(
                xyxy=boxes[mask],
                confidence=scores[mask],
                class_id=classes[mask],
            )
            tracked = trackers[class_id].update_with_detections(detections)
            if tracked.tracker_id is None:
                continue
            source_details = match_source_details(
                tracked.xyxy,
                boxes[mask],
                source_classes[mask],
                source_names[mask],
            )
            for box, score, local_id, source_class_id, source_class_name in zip(
                tracked.xyxy,
                tracked.confidence,
                tracked.tracker_id,
                (item[0] for item in source_details),
                (item[1] for item in source_details),
            ):
                key = (class_id, int(local_id))
                if key not in id_map:
                    id_map[key] = next_id
                    next_id += 1
                x1, y1, x2, y2 = (float(value) for value in box)
                rows.append({
                    "video_id": video_path.stem,
                    "frame_index": frame_index,
                    "timestamp_seconds": frame_index / fps,
                    "track_id": id_map[key],
                    "class_id": class_id,
                    "object_class": class_name,
                    "source_class_id": int(source_class_id),
                    "source_class_name": str(source_class_name),
                    "confidence": float(score),
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "center_x": (x1 + x2) / 2,
                    "center_y": (y1 + y2) / 2,
                    "foot_x": (x1 + x2) / 2,
                    "foot_y": y2,
                    "coordinate_system": "source_pixel",
                })
                class_counts[class_name] += 1
        processed += 1
        frame_index += 1

    capture.release()
    elapsed = time.perf_counter() - started
    csv_path = output_dir / "tracks.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "video": str(video_path.relative_to(resolve_project_path("."))),
        "model": str(model_path.relative_to(resolve_project_path("."))),
        "device": str(device),
        "source_fps": fps,
        "effective_fps": fps / args.frame_step,
        "start_seconds": args.start_seconds,
        "end_seconds": args.end_seconds,
        "processed_frames": processed,
        "slice_count": len(slices),
        "track_rows": len(rows),
        "tracks": len(set(row["track_id"] for row in rows)),
        "class_rows": dict(class_counts),
        "elapsed_seconds": elapsed,
        "seconds_per_processed_frame": elapsed / processed if processed else None,
        "parameters": vars(args),
        "class_profile": args.class_profile,
        "class_mapping": {
            source_id: {
                "class_id": mapped_id,
                "object_class": mapped_name,
                "source_class_name": source_name,
            }
            for source_id, (mapped_id, mapped_name, source_name) in profile.items()
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", default="data/raw/before/DJI_0482.MP4")
    parser.add_argument("--model", default="models/yolo11m.pt")
    parser.add_argument("--output-dir", default="outputs/analysis/baseline/DJI_0482")
    parser.add_argument("--start-seconds", type=float, default=150.0)
    parser.add_argument("--end-seconds", type=float, default=210.0)
    parser.add_argument("--frame-step", type=int, default=2)
    parser.add_argument("--slice-width", type=int, default=1024)
    parser.add_argument("--slice-height", type=int, default=1024)
    parser.add_argument("--overlap", type=float, default=0.2)
    parser.add_argument("--image-size", type=int, default=1024)
    parser.add_argument("--confidence", type=float, default=0.15)
    parser.add_argument("--nms-iou", type=float, default=0.5)
    parser.add_argument("--lost-seconds", type=float, default=3.0)
    parser.add_argument("--matching-threshold", type=float, default=0.8)
    parser.add_argument(
        "--class-profile", choices=sorted(CLASS_PROFILES), default="coco"
    )
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
