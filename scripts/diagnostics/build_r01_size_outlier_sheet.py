from __future__ import annotations

import csv
import hashlib
import json
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "data/ground_truth/object_track_v1/review"
VIDEO_PATH = ROOT / "data/raw/before/DJI_0482.MP4"
OUTPUT_DIRECTORY = ROOT / "outputs/diagnostics"
SIZE_RATIO_THRESHOLD = 1.4
PANEL_WIDTH = 480
PANEL_HEIGHT = 270
LABEL_HEIGHT = 42
HEADER_HEIGHT = 54
COLORS = {
    "previous": (40, 210, 255),
    "current": (40, 70, 255),
    "next": (80, 235, 70),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def find_outliers(observations: list[dict[str, str]]) -> list[dict[str, object]]:
    by_object: dict[str, list[dict[str, str]]] = {}
    for row in observations:
        by_object.setdefault(row["gt_object_id"], []).append(row)
    result: list[dict[str, object]] = []
    for object_id in sorted(by_object):
        rows = sorted(by_object[object_id], key=lambda row: int(row["frame_index"]))
        widths = [float(row["x2"]) - float(row["x1"]) for row in rows]
        heights = [float(row["y2"]) - float(row["y1"]) for row in rows]
        median_width = statistics.median(widths)
        median_height = statistics.median(heights)
        for index, row in enumerate(rows):
            width = float(row["x2"]) - float(row["x1"])
            height = float(row["y2"]) - float(row["y1"])
            width_ratio = width / median_width
            height_ratio = height / median_height
            if width >= median_width * SIZE_RATIO_THRESHOLD or height >= median_height * SIZE_RATIO_THRESHOLD:
                result.append(
                    {
                        "row": row,
                        "previous": rows[index - 1] if index else None,
                        "next": rows[index + 1] if index + 1 < len(rows) else None,
                        "width": width,
                        "height": height,
                        "median_width": median_width,
                        "median_height": median_height,
                        "width_ratio": width_ratio,
                        "height_ratio": height_ratio,
                    }
                )
    return result


def crop_for_box(frame: np.ndarray, row: dict[str, str]) -> tuple[np.ndarray, float]:
    x1, y1, x2, y2 = (float(row[key]) for key in ("x1", "y1", "x2", "y2"))
    box_width, box_height = x2 - x1, y2 - y1
    crop_width = max(280.0, box_width * 2.8, box_height * 2.8 * 16 / 9)
    crop_height = crop_width * 9 / 16
    center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
    left = round(center_x - crop_width / 2)
    top = round(center_y - crop_height / 2)
    left = min(max(0, left), frame.shape[1] - round(crop_width))
    top = min(max(0, top), frame.shape[0] - round(crop_height))
    crop_width_i, crop_height_i = round(crop_width), round(crop_height)
    crop = frame[top : top + crop_height_i, left : left + crop_width_i]
    scale = min(PANEL_WIDTH / crop.shape[1], PANEL_HEIGHT / crop.shape[0])
    resized_width = max(1, round(crop.shape[1] * scale))
    resized_height = max(1, round(crop.shape[0] * scale))
    image = cv2.resize(crop, (resized_width, resized_height), interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    panel = np.full((PANEL_HEIGHT, PANEL_WIDTH, 3), 245, dtype=np.uint8)
    x_offset, y_offset = (PANEL_WIDTH - resized_width) // 2, (PANEL_HEIGHT - resized_height) // 2
    panel[y_offset : y_offset + resized_height, x_offset : x_offset + resized_width] = image

    bx1 = round((x1 - left) * scale) + x_offset
    by1 = round((y1 - top) * scale) + y_offset
    bx2 = round((x2 - left) * scale) + x_offset
    by2 = round((y2 - top) * scale) + y_offset
    return panel, scale, (bx1, by1, bx2, by2)


def read_frame(capture: cv2.VideoCapture, row: dict[str, str] | None) -> tuple[np.ndarray | None, float, tuple[int, int, int, int] | None]:
    if row is None:
        return None, 0.0, None
    frame_index = int(row["frame_index"])
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"cannot read source frame {frame_index}")
    return (*crop_for_box(frame, row),)


def make_sheet(outliers: list[dict[str, object]]) -> np.ndarray:
    row_height = HEADER_HEIGHT + LABEL_HEIGHT + PANEL_HEIGHT
    sheet = np.full((len(outliers) * row_height, PANEL_WIDTH * 3, 3), 250, dtype=np.uint8)
    capture = cv2.VideoCapture(str(VIDEO_PATH))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {VIDEO_PATH}")
    try:
        for row_index, item in enumerate(outliers):
            row = item["row"]
            assert isinstance(row, dict)
            y = row_index * row_height
            header = (
                f"{row['gt_object_id']}  frame {row['frame_index']}  "
                f"box {item['width']:g}x{item['height']:g}px  "
                f"median {item['median_width']:g}x{item['median_height']:g}px  "
                f"W {item['width_ratio']:.2f}x / H {item['height_ratio']:.2f}x"
            )
            cv2.rectangle(sheet, (0, y), (PANEL_WIDTH * 3, y + HEADER_HEIGHT), (28, 35, 44), -1)
            cv2.putText(sheet, header, (12, y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (245, 248, 252), 1, cv2.LINE_AA)
            for panel_index, (name, neighbor) in enumerate(
                (("PREVIOUS", item["previous"]), ("CURRENT", row), ("NEXT", item["next"]))
            ):
                px = panel_index * PANEL_WIDTH
                color = COLORS["current" if name == "CURRENT" else "previous" if name == "PREVIOUS" else "next"]
                if neighbor is None:
                    crop = np.full((PANEL_HEIGHT, PANEL_WIDTH, 3), 235, dtype=np.uint8)
                    zoom_scale = 0.0
                    rect = None
                    frame_text = "none"
                else:
                    crop, zoom_scale, rect = read_frame(capture, neighbor)
                    frame_text = f"f{neighbor['frame_index']}"
                label_y = y + HEADER_HEIGHT
                cv2.rectangle(sheet, (px, label_y), (px + PANEL_WIDTH, label_y + LABEL_HEIGHT), (225, 230, 236), -1)
                cv2.putText(sheet, f"{name}  {frame_text}  crop scale {zoom_scale:.2f}x", (px + 10, label_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (25, 31, 38), 1, cv2.LINE_AA)
                image_y = label_y + LABEL_HEIGHT
                sheet[image_y : image_y + PANEL_HEIGHT, px : px + PANEL_WIDTH] = crop
                if rect is not None:
                    x1, y1, x2, y2 = rect
                    cv2.rectangle(sheet, (px + x1, image_y + y1), (px + x2, image_y + y2), color, 2, cv2.LINE_AA)
            cv2.line(sheet, (0, y + row_height - 1), (PANEL_WIDTH * 3, y + row_height - 1), (160, 166, 174), 1)
    finally:
        capture.release()
    return sheet


def main() -> None:
    observation_path = REVIEW / "gt_observations_R01.csv"
    observations = read_csv(observation_path)
    outliers = find_outliers(observations)
    OUTPUT = OUTPUT_DIRECTORY / f"R01_size_outliers_{len(outliers)}_20261102.jpg"
    sheet = make_sheet(outliers)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite existing output: {OUTPUT}")
    if not cv2.imwrite(str(OUTPUT), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise RuntimeError(f"cannot write {OUTPUT}")
    with (ROOT / "manifests/raw_videos.csv").open(encoding="utf-8", newline="") as stream:
        video_sha = next(row["sha256"] for row in csv.DictReader(stream) if row["video_id"] == "DJI_0482")
    try:
        code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except subprocess.CalledProcessError:
        code_commit = "unknown"
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": code_commit,
        "source_video": "data/raw/before/DJI_0482.MP4",
        "source_video_sha256": video_sha,
        "observations_sha256": sha256(observation_path),
        "frame_indices": [int(item["row"]["frame_index"]) for item in outliers],
        "size_outlier_threshold": "width or height >= 1.40x object median",
        "displayed_annotations": "manual GT boxes only; no automatic detections or tracks",
        "panel_order": "previous manual GT, flagged manual GT, next manual GT",
        "coordinate_system": "source_pixel",
        "unit": "px",
        "review_status": "visual_review_aid_only",
        "gt_modified": False,
    }
    OUTPUT.with_suffix(".meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{OUTPUT}\nrows={len(outliers)} width={sheet.shape[1]} height={sheet.shape[0]}")


if __name__ == "__main__":
    main()
