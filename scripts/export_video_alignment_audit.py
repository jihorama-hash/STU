"""Export start/middle/end ROI overlays for every raw video."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    video_dir = ROOT / "data/raw/before"
    calibration = ROOT / "data/calibration/legacy"
    output = ROOT / "outputs/validation/video_audit"
    output.mkdir(parents=True, exist_ok=True)
    homographies = json.loads(
        (calibration / "alignment_homographies.json").read_text(encoding="utf-8")
    )
    zones = json.loads(
        (calibration / "rois_split.json").read_text(encoding="utf-8")
    )["zones"]
    videos = sorted(
        path for path in video_dir.iterdir() if path.suffix.lower() == ".mp4"
    )
    rows = []
    for video in videos:
        capture = cv2.VideoCapture(str(video))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        video_id = video.stem
        reference_to_source = np.linalg.inv(
            np.asarray(homographies["videos"][video_id]["h"], dtype=float)
        )
        panels = []
        for fraction, position in ((0.05, "start"), (0.5, "middle"), (0.95, "end")):
            frame_index = min(frame_count - 1, round((frame_count - 1) * fraction))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Could not read {video.name} frame {frame_index}")
            for zone in zones:
                points = np.asarray(
                    zone["polygon"], dtype=np.float32
                ).reshape(1, -1, 2)
                polygon = cv2.perspectiveTransform(
                    points, reference_to_source
                ).round().astype(np.int32)[0]
                color = (0, 255, 255) if zone.get("parent") else (0, 180, 255)
                cv2.polylines(frame, [polygon], True, color, 5, cv2.LINE_AA)
            cv2.putText(
                frame,
                f"{video_id} | {position} | t={frame_index / fps:.1f}s",
                (35, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.5,
                (0, 255, 0),
                4,
                cv2.LINE_AA,
            )
            panels.append(cv2.resize(frame, (768, 432)))
        capture.release()
        row = cv2.hconcat(panels)
        cv2.imwrite(str(output / f"{video_id}_alignment_triptych.jpg"), row)
        rows.append(row)
        if video_id == "DJI_0488":
            capture = cv2.VideoCapture(str(video))
            timeline_panels = []
            for index, fraction in enumerate(np.linspace(0.0, 1.0, 16)):
                frame_index = min(frame_count - 1, round((frame_count - 1) * fraction))
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError(
                        f"Could not read {video.name} timeline frame {frame_index}"
                    )
                cv2.putText(
                    frame,
                    f"t={frame_index / fps:.1f}s",
                    (35, 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.5,
                    (0, 255, 0),
                    4,
                    cv2.LINE_AA,
                )
                timeline_panels.append(cv2.resize(frame, (480, 270)))
            capture.release()
            timeline_rows = [
                cv2.hconcat(timeline_panels[start:start + 4])
                for start in range(0, len(timeline_panels), 4)
            ]
            cv2.imwrite(
                str(output / "DJI_0488_timeline.jpg"),
                cv2.vconcat(timeline_rows),
            )
    cv2.imwrite(str(output / "all_videos_alignment_contact_sheet.jpg"), cv2.vconcat(rows))
    print(f"Exported {len(videos)} video alignment triptychs to {output}")


if __name__ == "__main__":
    main()
