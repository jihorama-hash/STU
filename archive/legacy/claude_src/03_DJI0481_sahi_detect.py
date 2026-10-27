from __future__ import annotations

from _paths import BASE

import argparse
import csv
import math
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


BASE_DIR = BASE
DEFAULT_VIDEO = BASE_DIR / "record" / "DJI_0481.MP4"
DEFAULT_MODEL = BASE_DIR / "yolo11m.pt"
DEFAULT_SAMPLE_OUTPUT_DIR = BASE_DIR / "runs" / "DJI_0481_sahi_sample"
DEFAULT_FULL_OUTPUT_DIR = BASE_DIR / "runs" / "DJI_0481_sahi"

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

CSV_FIELDS = [
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SAHI-style sliced YOLO detection on DJI_0481.MP4."
    )
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--slice-width", type=int, default=1024)
    parser.add_argument("--slice-height", type=int, default=1024)
    parser.add_argument("--overlap", type=float, default=0.20)
    parser.add_argument("--conf", type=float, default=0.20)
    parser.add_argument("--iou", type=float, default=0.50)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--frames", type=str, default="")
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument(
        "--frame-step",
        type=int,
        default=1,
        help="Process every Nth frame when --all-frames is used. 3 is about 10 fps for DJI_0481.",
    )
    parser.add_argument("--all-frames", action="store_true")
    parser.add_argument("--save-video", action="store_true")
    parser.add_argument("--no-save-images", action="store_true")
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


def evenly_spaced_frames(frame_count: int, samples: int) -> list[int]:
    samples = max(1, min(samples, frame_count))
    if samples == 1:
        return [0]
    return sorted({round(i * (frame_count - 1) / (samples - 1)) for i in range(samples)})


def selected_frame_ids(args: argparse.Namespace, frame_count: int) -> list[int]:
    if args.all_frames:
        frame_step = max(1, args.frame_step)
        return list(range(0, frame_count, frame_step))
    if not args.frames.strip():
        return evenly_spaced_frames(frame_count, args.samples)
    frame_ids = []
    for item in args.frames.split(","):
        item = item.strip()
        if not item:
            continue
        frame_id = int(item)
        if 0 <= frame_id < frame_count:
            frame_ids.append(frame_id)
    if not frame_ids:
        raise ValueError("No valid frame ids were provided.")
    return sorted(set(frame_ids))


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
    tiles = []
    origins = []
    for slice_id, (sx1, sy1, sx2, sy2) in enumerate(slices):
        tiles.append(frame[sy1:sy2, sx1:sx2])
        origins.append((slice_id, sx1, sy1))

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


def annotate_frame(frame: np.ndarray, detections: list[dict]) -> np.ndarray:
    annotated = frame.copy()
    for det in detections:
        color = CLASS_COLORS.get(int(det["class_id"]), (255, 255, 255))
        x1, y1, x2, y2 = [int(round(det[key])) for key in ("x1", "y1", "x2", "y2")]
        label = f"{det['class_name']} {det['confidence']:.2f}"
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
    return annotated


def seek_frame(cap: cv2.VideoCapture, frame_id: int) -> np.ndarray:
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame {frame_id}")
    return frame


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    if args.output_dir is None:
        args.output_dir = DEFAULT_FULL_OUTPUT_DIR if args.all_frames else DEFAULT_SAMPLE_OUTPUT_DIR
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = args.output_dir / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)

    width, height, fps, frame_count = get_video_info(args.video)
    frame_ids = selected_frame_ids(args, frame_count)
    slices = make_slices(width, height, args.slice_width, args.slice_height, args.overlap)

    print(f"Video: {args.video}")
    print(f"Size/FPS/frames: {width}x{height}, {fps:.3f}, {frame_count}")
    print(f"Duration: {frame_count / fps:.2f}s")
    print(f"Frame mode: {'all frames' if args.all_frames else 'sample frames'} ({len(frame_ids)})")
    print(f"Frame ids: {frame_ids[:20]}{' ...' if len(frame_ids) > 20 else ''}")
    print(f"Slices per frame: {len(slices)}")

    model = YOLO(str(args.model))
    cap = cv2.VideoCapture(str(args.video))
    rows = []
    writer = None
    if args.save_video:
        output_video = args.output_dir / "DJI_0481_sahi_annotated.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_video), fourcc, fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError(f"Could not open video writer: {output_video}")

    started = time.perf_counter()
    try:
        for index, frame_id in enumerate(frame_ids, start=1):
            frame_started = time.perf_counter()
            frame = seek_frame(cap, frame_id)
            time_sec = frame_id / fps if fps > 0 else math.nan
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
            rows.extend(detections)

            annotated = annotate_frame(frame, detections)
            if writer is not None:
                writer.write(annotated)
            if not args.no_save_images:
                output_image = sample_dir / f"frame_{frame_id:06d}.jpg"
                cv2.imwrite(str(output_image), annotated, [cv2.IMWRITE_JPEG_QUALITY, 92])

            elapsed = time.perf_counter() - frame_started
            print(
                f"[{index}/{len(frame_ids)}] frame={frame_id} "
                f"time={time_sec:.2f}s detections={len(detections)} elapsed={elapsed:.1f}s"
            )
    finally:
        cap.release()
        if writer is not None:
            writer.release()

    output_csv = args.output_dir / (
        "detections_pixel.csv" if args.all_frames else "detections_pixel_sample.csv"
    )
    write_csv(output_csv, rows, CSV_FIELDS)

    summary_rows = []
    counts = Counter((row["frame_id"], row["class_name"]) for row in rows)
    for (frame_id, class_name), detections in sorted(counts.items()):
        summary_rows.append(
            {"frame_id": frame_id, "class_name": class_name, "detections": detections}
        )
    summary_csv = args.output_dir / "summary_by_frame_class.csv"
    write_csv(summary_csv, summary_rows, ["frame_id", "class_name", "detections"])

    print(f"Total elapsed: {time.perf_counter() - started:.1f}s")
    print(f"Saved detections: {output_csv}")
    print(f"Saved summary: {summary_csv}")
    print(f"Saved annotated samples: {sample_dir}")


if __name__ == "__main__":
    main()
