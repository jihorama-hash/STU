"""SAHI 슬라이스 검출 + ByteTrack 추적 결합 파이프라인 (Phase B 7장 (1)(2) 대응).

기존 03(SAHI 검출, 그리디 NMS 병합)의 슬라이싱 로직을 재사용하고,
기존 04(그리디 IoU 추적, Phase A에서 궤적 분절의 주범으로 지목된 P5)를
supervision.ByteTrack으로 대체한다.

    python src/29_sahi_bytetrack_pipeline.py --video record/before/DJI_0481.MP4

산출: <output-dir>/detections_pixel.csv, <output-dir>/tracks_pixel.csv
"""

from __future__ import annotations

from _paths import BASE

import argparse
import csv
import math
import time
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

DEFAULT_VIDEO = BASE / "record" / "before" / "DJI_0481.MP4"
DEFAULT_MODEL = BASE / "models" / "yolo11m.pt"

TARGET_CLASSES = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

CLASS_COLORS = {
    0: (60, 220, 60),
    1: (255, 190, 40),
    2: (60, 140, 255),
    3: (255, 80, 80),
    5: (220, 80, 255),
    7: (80, 220, 220),
}

DETECTION_FIELDS = [
    "frame_id",
    "time_sec",
    "slice_id",
    "class_id",
    "class_name",
    "confidence",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "foot_x",
    "foot_y",
]

TRACK_FIELDS = [
    "frame_id",
    "time_sec",
    "track_id",
    "class_id",
    "class_name",
    "confidence",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "foot_x",
    "foot_y",
    "anchor_x",
    "anchor_y",
    "anchor_type",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SAHI slice detection + ByteTrack tracking on a full video."
    )
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--slice-width", type=int, default=1024)
    parser.add_argument("--slice-height", type=int, default=1024)
    parser.add_argument("--overlap", type=float, default=0.20)
    parser.add_argument("--conf", type=float, default=0.15)
    parser.add_argument("--iou", type=float, default=0.50)
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument(
        "--frame-step",
        type=int,
        default=2,
        help="Process every Nth source frame. 2 is ~15fps for the 29.97fps source "
        "(Phase A: 3fps loses 65%% of pedestrian-vehicle conflicts).",
    )
    parser.add_argument(
        "--occlusion-sec",
        type=float,
        default=3.0,
        help="Seconds a lost track is kept alive through occlusion (Kalman-predicted).",
    )
    parser.add_argument("--max-frames", type=int, default=0, help="0 = process the whole video.")
    parser.add_argument(
        "--matching-threshold",
        type=float,
        default=0.8,
        help="ByteTrack minimum_matching_threshold (IoU). Lower = more lenient re-association "
        "across low-confidence/jittery detections, at the cost of more ID switches.",
    )
    parser.add_argument(
        "--save-video",
        action="store_true",
        help="Write an annotated (box + track_id) mp4 alongside the CSVs.",
    )
    return parser.parse_args()


def get_video_info(video_path: Path) -> tuple[int, int, float, int]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if width <= 0 or height <= 0 or fps <= 0 or frame_count <= 0:
        raise ValueError(f"Invalid video metadata: {video_path}")
    return width, height, fps, frame_count


def make_slices(
    image_width: int,
    image_height: int,
    slice_width: int,
    slice_height: int,
    overlap: float,
) -> list[tuple[int, int, int, int]]:
    if not 0 <= overlap < 1:
        raise ValueError("--overlap must be in the range [0, 1).")
    step_x = max(1, int(slice_width * (1 - overlap)))
    step_y = max(1, int(slice_height * (1 - overlap)))
    x_starts = list(range(0, max(1, image_width - slice_width + 1), step_x))
    y_starts = list(range(0, max(1, image_height - slice_height + 1), step_y))
    if x_starts[-1] + slice_width < image_width:
        x_starts.append(max(0, image_width - slice_width))
    if y_starts[-1] + slice_height < image_height:
        y_starts.append(max(0, image_height - slice_height))
    return [
        (x1, y1, min(image_width, x1 + slice_width), min(image_height, y1 + slice_height))
        for y1 in y_starts
        for x1 in x_starts
    ]


def box_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    intersection = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    box_area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
    boxes_area = np.maximum(0, boxes[:, 2] - boxes[:, 0]) * np.maximum(
        0, boxes[:, 3] - boxes[:, 1]
    )
    union = box_area + boxes_area - intersection
    return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)


def classwise_nms(detections: list[dict], iou_threshold: float) -> list[dict]:
    kept = []
    for class_id in sorted({det["class_id"] for det in detections}):
        class_dets = [det for det in detections if det["class_id"] == class_id]
        boxes = np.array(
            [[det["x1"], det["y1"], det["x2"], det["y2"]] for det in class_dets],
            dtype=np.float32,
        )
        scores = np.array([det["confidence"] for det in class_dets], dtype=np.float32)
        order = scores.argsort()[::-1]
        while order.size > 0:
            current_idx = int(order[0])
            kept.append(class_dets[current_idx])
            if order.size == 1:
                break
            ious = box_iou(boxes[current_idx], boxes[order[1:]])
            order = order[1:][ious <= iou_threshold]
    return kept


def detect_frame_sliced(
    model: YOLO,
    frame: np.ndarray,
    frame_id: int,
    time_sec: float,
    slices: list[tuple[int, int, int, int]],
    conf: float,
    iou: float,
    imgsz: int,
) -> list[dict]:
    tiles = [frame[sy1:sy2, sx1:sx2] for (sx1, sy1, sx2, sy2) in slices]
    origins = [(slice_id, sx1, sy1) for slice_id, (sx1, sy1, _, _) in enumerate(slices)]

    raw_detections = []
    results = model.predict(
        tiles,
        conf=conf,
        iou=iou,
        classes=list(TARGET_CLASSES.keys()),
        imgsz=imgsz,
        verbose=False,
    )
    for result, (slice_id, sx1, sy1) in zip(results, origins):
        if result.boxes is None or len(result.boxes) == 0:
            continue
        xyxy = result.boxes.xyxy.cpu().numpy()
        cls = result.boxes.cls.cpu().numpy().astype(int)
        confs = result.boxes.conf.cpu().numpy()
        for box, class_id, score in zip(xyxy, cls, confs):
            if class_id not in TARGET_CLASSES:
                continue
            x1, y1, x2, y2 = box
            raw_detections.append(
                {
                    "frame_id": frame_id,
                    "time_sec": time_sec,
                    "slice_id": slice_id,
                    "class_id": int(class_id),
                    "class_name": TARGET_CLASSES[int(class_id)],
                    "confidence": float(score),
                    "x1": float(x1 + sx1),
                    "y1": float(y1 + sy1),
                    "x2": float(x2 + sx1),
                    "y2": float(y2 + sy1),
                }
            )

    detections = classwise_nms(raw_detections, iou)
    for det in detections:
        det["cx"] = (det["x1"] + det["x2"]) / 2
        det["cy"] = (det["y1"] + det["y2"]) / 2
        det["foot_x"] = det["cx"]
        det["foot_y"] = det["y2"]
    return detections


def to_sv_detections(detections: list[dict]) -> sv.Detections:
    if not detections:
        return sv.Detections.empty()
    xyxy = np.array([[d["x1"], d["y1"], d["x2"], d["y2"]] for d in detections], dtype=np.float32)
    confidence = np.array([d["confidence"] for d in detections], dtype=np.float32)
    class_id = np.array([d["class_id"] for d in detections], dtype=int)
    return sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)


def annotate_tracked_frame(
    frame: np.ndarray,
    tracked: sv.Detections,
    corner_label: str,
) -> np.ndarray:
    annotated = frame.copy()
    for i in range(len(tracked)):
        x1, y1, x2, y2 = [int(round(v)) for v in tracked.xyxy[i]]
        class_id = int(tracked.class_id[i])
        track_id = int(tracked.tracker_id[i])
        color = CLASS_COLORS.get(class_id, (255, 255, 255))
        label = f"{TARGET_CLASSES.get(class_id, class_id)} #{track_id}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        label_y1 = max(0, y1 - text_size[1] - 8)
        cv2.rectangle(
            annotated,
            (x1, label_y1),
            (x1 + text_size[0] + 8, label_y1 + text_size[1] + 8),
            color,
            -1,
        )
        cv2.putText(
            annotated,
            label,
            (x1 + 4, label_y1 + text_size[1] + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )

    (tw, th), _ = cv2.getTextSize(corner_label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    cv2.rectangle(annotated, (10, 10), (20 + tw, 26 + th), (0, 0, 0), -1)
    cv2.putText(
        annotated,
        corner_label,
        (15, 20 + th),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return annotated


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    if args.output_dir is None:
        args.output_dir = BASE / "runs" / "before" / args.video.stem
    args.output_dir.mkdir(parents=True, exist_ok=True)

    width, height, source_fps, frame_count = get_video_info(args.video)
    effective_fps = source_fps / args.frame_step
    slices = make_slices(width, height, args.slice_width, args.slice_height, args.overlap)

    # ByteTrack normalizes lost_track_buffer against a 30fps baseline internally
    # (max_time_lost = frame_rate/30 * lost_track_buffer), so this constant holds
    # regardless of effective_fps.
    lost_track_buffer = round(args.occlusion_sec * 30)

    print(f"Video: {args.video}")
    print(f"Size/FPS/frames: {width}x{height}, {source_fps:.3f}, {frame_count}")
    print(f"Frame step: {args.frame_step} -> effective fps: {effective_fps:.2f}")
    print(f"Slices per frame: {len(slices)}")
    print(f"Occlusion tolerance: {args.occlusion_sec}s (lost_track_buffer={lost_track_buffer})")
    print(f"Matching threshold: {args.matching_threshold}")

    model = YOLO(str(args.model))
    tracker = sv.ByteTrack(
        track_activation_threshold=args.conf,
        lost_track_buffer=lost_track_buffer,
        minimum_matching_threshold=args.matching_threshold,
        frame_rate=effective_fps,
    )

    detection_rows: list[dict] = []
    track_rows: list[dict] = []

    video_writer = None
    if args.save_video:
        annotated_path = args.output_dir / f"{args.video.stem}_annotated.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_writer = cv2.VideoWriter(str(annotated_path), fourcc, effective_fps, (width, height))
        if not video_writer.isOpened():
            raise RuntimeError(f"Could not open video writer: {annotated_path}")

    cap = cv2.VideoCapture(str(args.video))
    limit = args.max_frames if args.max_frames > 0 else frame_count
    started = time.perf_counter()
    processed = 0
    try:
        for frame_id in range(min(frame_count, limit)):
            ok = cap.grab()
            if not ok:
                break
            if frame_id % args.frame_step != 0:
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                break

            time_sec = frame_id / source_fps
            detections = detect_frame_sliced(
                model=model,
                frame=frame,
                frame_id=frame_id,
                time_sec=time_sec,
                slices=slices,
                conf=args.conf,
                iou=args.iou,
                imgsz=args.imgsz,
            )
            detection_rows.extend(detections)

            sv_dets = to_sv_detections(detections)
            tracked = tracker.update_with_detections(sv_dets)
            for i in range(len(tracked)):
                x1, y1, x2, y2 = [float(v) for v in tracked.xyxy[i]]
                class_id = int(tracked.class_id[i])
                foot_x = (x1 + x2) / 2
                foot_y = y2
                track_rows.append(
                    {
                        "frame_id": frame_id,
                        "time_sec": time_sec,
                        "track_id": int(tracked.tracker_id[i]),
                        "class_id": class_id,
                        "class_name": TARGET_CLASSES.get(class_id, str(class_id)),
                        "confidence": float(tracked.confidence[i]),
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "cx": (x1 + x2) / 2,
                        "cy": (y1 + y2) / 2,
                        "foot_x": foot_x,
                        "foot_y": foot_y,
                        "anchor_x": foot_x,
                        "anchor_y": foot_y,
                        "anchor_type": "foot_point",
                    }
                )

            if video_writer is not None:
                corner_label = f"{args.video.stem}  t={time_sec:.1f}s"
                video_writer.write(annotate_tracked_frame(frame, tracked, corner_label))

            processed += 1
            if processed % 50 == 0:
                elapsed = time.perf_counter() - started
                print(
                    f"frame={frame_id}/{frame_count} time={time_sec:.1f}s "
                    f"processed={processed} elapsed={elapsed:.1f}s "
                    f"({elapsed / processed:.2f}s/frame)"
                )
    finally:
        cap.release()
        if video_writer is not None:
            video_writer.release()

    detections_csv = args.output_dir / "detections_pixel.csv"
    tracks_csv = args.output_dir / "tracks_pixel.csv"
    write_csv(detections_csv, detection_rows, DETECTION_FIELDS)
    write_csv(tracks_csv, track_rows, TRACK_FIELDS)

    total_elapsed = time.perf_counter() - started
    n_tracks = len({row["track_id"] for row in track_rows})
    print(f"Total elapsed: {total_elapsed:.1f}s ({total_elapsed / max(1, processed):.2f}s/frame)")
    print(f"Frames processed: {processed}, detections: {len(detection_rows)}, "
          f"track rows: {len(track_rows)}, unique tracks: {n_tracks}")
    print(f"Saved: {detections_csv}")
    print(f"Saved: {tracks_csv}")
    if args.save_video:
        print(f"Saved: {args.output_dir / (args.video.stem + '_annotated.mp4')}")


if __name__ == "__main__":
    main()
