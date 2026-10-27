"""Render review frames from track CSV without modifying source video."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import cv2

from .paths import resolve_project_path


COLORS = {
    "person": (70, 230, 70),
    "bicycle": (255, 180, 40),
    "car": (50, 140, 255),
    "motorcycle": (255, 70, 70),
    "bus": (220, 80, 255),
    "truck": (80, 220, 220),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--times", default="155,165,175,185,195,205")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    video = resolve_project_path(args.video)
    tracks_path = resolve_project_path(args.tracks)
    output_dir = resolve_project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    by_frame: dict[int, list[dict[str, str]]] = defaultdict(list)
    with tracks_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            by_frame[int(row["frame_index"])].append(row)

    capture = cv2.VideoCapture(str(video))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    for timestamp in (float(item) for item in args.times.split(",")):
        target_frame = round(timestamp * fps)
        available_frame = min(by_frame, key=lambda value: abs(value - target_frame))
        capture.set(cv2.CAP_PROP_POS_FRAMES, available_frame)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Could not read frame {available_frame}")
        for row in by_frame[available_frame]:
            x1, y1, x2, y2 = (
                round(float(row[key])) for key in ("x1", "y1", "x2", "y2")
            )
            object_class = row["object_class"]
            color = COLORS.get(object_class, (255, 255, 255))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            cv2.putText(
                frame,
                f"{object_class} #{row['track_id']}",
                (x1, max(30, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                color,
                2,
                cv2.LINE_AA,
            )
        destination = output_dir / f"frame_{available_frame}_t{timestamp:.0f}.jpg"
        cv2.imwrite(str(destination), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    capture.release()


if __name__ == "__main__":
    main()
