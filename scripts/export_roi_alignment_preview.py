"""Overlay reference-coordinate ROIs on a source-video frame."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "data/raw/before/DJI_0482.MP4"
ZONES = ROOT / "data/calibration/legacy/rois_split.json"
HOMOGRAPHIES = ROOT / "data/calibration/legacy/alignment_homographies.json"
OUTPUT = ROOT / "outputs/validation/DJI_0482_250s_roi_alignment.jpg"


def main() -> None:
    zones = json.loads(ZONES.read_text(encoding="utf-8"))["zones"]
    data = json.loads(HOMOGRAPHIES.read_text(encoding="utf-8"))
    source_to_reference = np.asarray(data["videos"]["DJI_0482"]["h"], dtype=float)
    reference_to_source = np.linalg.inv(source_to_reference)

    capture = cv2.VideoCapture(str(VIDEO))
    capture.set(cv2.CAP_PROP_POS_MSEC, 250_000)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError("Could not read 250-second frame")

    for index, zone in enumerate(zones):
        points = np.asarray(zone["polygon"], dtype=np.float32).reshape(1, -1, 2)
        transformed = cv2.perspectiveTransform(
            points, reference_to_source
        ).round().astype(np.int32)[0]
        color = (0, 255, 255) if "crosswalk" in zone["id"] else (255, 0, 255)
        cv2.polylines(frame, [transformed], True, color, 6, cv2.LINE_AA)
        center = transformed.mean(axis=0).round().astype(int)
        cv2.putText(
            frame,
            str(index + 1),
            tuple(center),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.3,
            color,
            4,
            cv2.LINE_AA,
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUTPUT), frame)
    print(OUTPUT)


if __name__ == "__main__":
    main()
