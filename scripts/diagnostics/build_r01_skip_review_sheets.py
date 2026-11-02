from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timezone
import subprocess

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
GT_ROOT = ROOT / "data/ground_truth/object_track_v1"
REVIEW_ROOT = GT_ROOT / "review"
VIDEO_PATH = ROOT / "data/raw/before/DJI_0482.MP4"
OUTPUT_ROOT = ROOT / "outputs/diagnostics/R01_skip_review_final_20261102"
PANEL_WIDTH = 640
PANEL_HEIGHT = 480
CROP_WIDTH = 720
CROP_HEIGHT = 540
COLS = 3


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def crop_center(observations: list[dict[str, str]], object_id: str, frame: int) -> tuple[int, int]:
    rows = [row for row in observations if row["gt_object_id"] == object_id]
    if not rows:
        return 1920, 1080
    prior = [row for row in rows if int(row["frame_index"]) < frame]
    later = [row for row in rows if int(row["frame_index"]) > frame]
    if prior and later:
        left = max(prior, key=lambda row: int(row["frame_index"]))
        right = min(later, key=lambda row: int(row["frame_index"]))
        f0, f1 = int(left["frame_index"]), int(right["frame_index"])
        ratio = (frame - f0) / (f1 - f0)
        centers = []
        for key in ("x1", "y1", "x2", "y2"):
            centers.append(float(left[key]) + ratio * (float(right[key]) - float(left[key])))
        return round((centers[0] + centers[2]) / 2), round((centers[1] + centers[3]) / 2)
    nearest = min(rows, key=lambda row: abs(int(row["frame_index"]) - frame))
    return round((float(nearest["x1"]) + float(nearest["x2"])) / 2), round(
        (float(nearest["y1"]) + float(nearest["y2"])) / 2
    )


def render_panel(capture: cv2.VideoCapture, observations: list[dict[str, str]], row: dict[str, str]):
    frame_index = int(row["frame_index"])
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"cannot read source frame {frame_index}")
    cx, cy = crop_center(observations, row["gt_object_id"], frame_index)
    x0 = min(max(0, cx - CROP_WIDTH // 2), frame.shape[1] - CROP_WIDTH)
    y0 = min(max(0, cy - CROP_HEIGHT // 2), frame.shape[0] - CROP_HEIGHT)
    crop = frame[y0 : y0 + CROP_HEIGHT, x0 : x0 + CROP_WIDTH]
    crop = cv2.resize(crop, (PANEL_WIDTH, PANEL_HEIGHT))
    label = f"{row['gt_object_id']}  f{frame_index}  {row['reason']}"
    cv2.rectangle(crop, (0, 0), (PANEL_WIDTH, 32), (20, 20, 20), -1)
    cv2.putText(crop, label, (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (70, 240, 255), 1, cv2.LINE_AA)
    return crop


def main() -> None:
    observations = read_csv(REVIEW_ROOT / "gt_observations_R01.csv")
    skips = read_csv(REVIEW_ROOT / "gt_observation_skips_R01.csv")
    capture = cv2.VideoCapture(str(VIDEO_PATH))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {VIDEO_PATH}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "manifests/raw_videos.csv").open(encoding="utf-8", newline="") as stream:
        video_sha256 = next(row["sha256"] for row in csv.DictReader(stream) if row["video_id"] == "DJI_0482")
    input_hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            REVIEW_ROOT / "gt_observations_R01.csv",
            REVIEW_ROOT / "gt_observation_skips_R01.csv",
        )
    }
    try:
        code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except subprocess.CalledProcessError:
        code_commit = "unknown"
    try:
        for reason in sorted({row["reason"] for row in skips}):
            rows = [row for row in skips if row["reason"] == reason]
            panels = [render_panel(capture, observations, row) for row in rows]
            height = math.ceil(len(panels) / COLS) * PANEL_HEIGHT
            sheet = np.full((height, COLS * PANEL_WIDTH, 3), 255, dtype=np.uint8)
            for index, panel in enumerate(panels):
                y, x = divmod(index, COLS)
                sheet[y * PANEL_HEIGHT : (y + 1) * PANEL_HEIGHT, x * PANEL_WIDTH : (x + 1) * PANEL_WIDTH] = panel
            out = OUTPUT_ROOT / f"{reason}.jpg"
            cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
            metadata = {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "code_commit": code_commit,
                "source_video": "data/raw/before/DJI_0482.MP4",
                "source_video_sha256": video_sha256,
                "input_file_hashes_sha256": input_hashes,
                "frame_indices": [int(row["frame_index"]) for row in rows],
                "crop": "720x540 source_px centered on nearest/interpolated manual GT box",
                "review_status": "visual_review_aid_only",
                "gt_modified": False,
            }
            out.with_suffix(".meta.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(out)
    finally:
        capture.release()


if __name__ == "__main__":
    main()
