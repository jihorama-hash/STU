from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Draw conflict zone polygons from JSON.")
    parser.add_argument("--zones", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.zones.open("r", encoding="utf-8") as file:
        data = json.load(file)

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {args.video}")
    if args.frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame {args.frame}: {args.video}")

    overlay = frame.copy()
    colors = [
        (0, 128, 255),
        (0, 200, 0),
        (255, 80, 80),
        (255, 0, 255),
        (0, 255, 255),
    ]

    for index, zone in enumerate(data["zones"]):
        color = colors[index % len(colors)]
        pts = np.array(zone["polygon"], dtype=np.int32)
        cv2.fillPoly(overlay, [pts], color)

    frame = cv2.addWeighted(overlay, 0.25, frame, 0.75, 0)

    for index, zone in enumerate(data["zones"]):
        color = colors[index % len(colors)]
        pts = np.array(zone["polygon"], dtype=np.int32)
        cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=6, lineType=cv2.LINE_AA)
        label_xy = tuple(pts.mean(axis=0).astype(int))
        label = f"{index + 1}. {zone['id']}"
        (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)
        x, y = label_xy
        cv2.rectangle(
            frame,
            (x - 8, y - text_h - baseline - 8),
            (x + text_w + 8, y + baseline + 8),
            (0, 0, 0),
            -1,
        )
        cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3, cv2.LINE_AA)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), frame):
        raise RuntimeError(f"Could not write preview: {args.output}")
    print(f"Preview saved: {args.output}")


if __name__ == "__main__":
    main()
