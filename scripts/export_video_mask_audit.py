"""Render video-specific roadway and exclusion masks on representative frames."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    videos = sorted(
        path for path in (ROOT / "data/raw/before").iterdir()
        if path.is_file() and path.suffix.lower() == ".mp4"
    )
    masks = ROOT / "data/calibration/by_video"
    output = ROOT / "outputs/validation/video_mask_audit"
    output.mkdir(parents=True, exist_ok=True)
    panels = []
    for video in videos:
        video_id = video.stem
        capture = cv2.VideoCapture(str(video))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
        ok, frame = capture.read()
        capture.release()
        if not ok:
            raise RuntimeError(f"Could not read representative frame: {video}")
        roadway = cv2.imread(
            str(masks / f"{video_id}_roadway_mask.png"), cv2.IMREAD_GRAYSCALE
        )
        exclusion = cv2.imread(
            str(masks / f"{video_id}_vehicle_exclusion_mask.png"),
            cv2.IMREAD_GRAYSCALE,
        )
        if roadway is None or exclusion is None:
            raise FileNotFoundError(f"Missing masks for {video_id}")
        color = np.zeros_like(frame)
        color[roadway > 0] = (0, 170, 0)
        color[exclusion > 0] = (0, 0, 255)
        alpha = np.zeros(roadway.shape, dtype=np.float32)
        alpha[roadway > 0] = 0.22
        alpha[exclusion > 0] = 0.75
        overlay = (
            frame.astype(np.float32) * (1 - alpha[..., None])
            + color.astype(np.float32) * alpha[..., None]
        ).astype(np.uint8)
        cv2.putText(
            overlay,
            f"{video_id} | green=roadway red=exclusion",
            (35, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.4,
            (0, 255, 255),
            4,
            cv2.LINE_AA,
        )
        panel = cv2.resize(overlay, (960, 540))
        cv2.imwrite(str(output / f"{video_id}_mask_overlay.jpg"), panel)
        panels.append(panel)
    contact = cv2.vconcat([
        cv2.hconcat(panels[start:start + 2])
        for start in range(0, len(panels), 2)
    ])
    cv2.imwrite(str(output / "all_video_masks_contact_sheet.jpg"), contact)
    print(f"Exported {len(panels)} video mask overlays to {output}")


if __name__ == "__main__":
    main()
