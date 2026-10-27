from __future__ import annotations

from _paths import BASE

import argparse
import json
from pathlib import Path


DEFAULT_OUTPUT = BASE / "runs" / "DJI_0481_sahi_step10" / "conflict_zones.json"
DEFAULT_PREVIEW_OUTPUT = BASE / "runs" / "DJI_0481_sahi_step10" / "conflict_zones_preview.jpg"


DEFAULT_ZONES = {
    "video": "record/DJI_0481.MP4",
    "coordinate_system": "pixel",
    "notes": [
        "Initial hand-drawn ROI polygons for PET logic validation.",
        "Edit these polygons after visual inspection before final reporting.",
    ],
    "zones": [
        {
            "id": "crosswalk_northwest",
            "name": "Northwest diagonal crosswalk",
            "polygon": [
                [1617, 215],
                [1890, 241],
                [729, 977],
                [712, 798],
            ],
        },
        {
            "id": "crosswalk_southwest",
            "name": "Southwest diagonal crosswalk",
            "polygon": [
                [732, 965],
                [1536, 1694],
                [1356, 1771],
                [679, 1142],
            ],
        },
        {
            "id": "crosswalk_east",
            "name": "East crosswalk",
            "polygon": [
                [3158, 1438],
                [3307, 1510],
                [3094, 1726],
                [2935, 1668],
            ],
        },
        {
            "id": "roundabout_entry_west",
            "name": "West roundabout entry conflict area",
            "polygon": [
                [1145, 746],
                [1562, 1159],
                [1181, 1368],
                [809, 1037],
            ],
        },
        {
            "id": "roundabout_entry_south",
            "name": "South roundabout entry conflict area",
            "polygon": [
                [1608, 1210],
                [2071, 1546],
                [1536, 1694],
                [1234, 1418],
            ],
        },
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write initial PET conflict ROI polygons.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--video", type=Path, default=None, help="Video path used for ROI preview.")
    parser.add_argument("--preview-output", type=Path, default=None, help="Write a frame image with ROI polygons overlaid.")
    parser.add_argument("--preview-frame", type=int, default=0, help="Video frame index for ROI preview.")
    return parser.parse_args()


def write_preview(video_path: Path, output_path: Path, frame_index: int) -> None:
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    if frame_index > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Could not read frame {frame_index} from: {video_path}")

    overlay = frame.copy()
    colors = [
        (0, 128, 255),
        (0, 200, 0),
        (255, 80, 80),
        (255, 0, 255),
        (0, 255, 255),
    ]

    for index, zone in enumerate(DEFAULT_ZONES["zones"]):
        color = colors[index % len(colors)]
        pts = np.array(zone["polygon"], dtype=np.int32)
        cv2.fillPoly(overlay, [pts], color)

    frame = cv2.addWeighted(overlay, 0.25, frame, 0.75, 0)

    for index, zone in enumerate(DEFAULT_ZONES["zones"]):
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), frame):
        raise RuntimeError(f"Could not write preview: {output_path}")


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(DEFAULT_ZONES, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"Saved: {args.output}")
    print("Review and adjust polygons before final PET reporting.")

    if args.preview_output is not None:
        video_path = args.video or Path(DEFAULT_ZONES["video"])
        if not video_path.is_absolute():
            video_path = Path.cwd() / video_path
        write_preview(video_path, args.preview_output, args.preview_frame)
        print(f"Preview saved: {args.preview_output}")


if __name__ == "__main__":
    main()
