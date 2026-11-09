"""Create TASK-009-only dilated roadway masks and representative overlays."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MASK_DIR = ROOT / "data/calibration/by_video"
VIDEO_DIR = ROOT / "data/raw/before"
BASE_OUT_DIR = ROOT / "outputs/task009/polygons"
RADIUS_PX = 200
REPRESENTATIVE_FRAMES = {
    "DJI_0481": 2848,
    "DJI_0482": 2500,
    "DJI_0483": 2500,
    "DJI_0484": 400,
    "DJI_0485": 4000,
    "DJI_0486": None,  # Test clip: no source frame is opened.
    "DJI_0487": 4000,
    "DJI_0488": 1900,
}
MASK_IDS = {"DJI_0483": "DJI_0483_Cut"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--radius", type=int, default=RADIUS_PX)
    args = parser.parse_args()
    if args.radius < 0:
        raise SystemExit("--radius must be non-negative")
    out_dir = BASE_OUT_DIR if args.radius == RADIUS_PX else BASE_OUT_DIR / f"r{args.radius}px"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "task_scope": "TASK-009 only",
        "radius_px": args.radius,
        "kernel": "elliptical (2r+1 square; Euclidean raster approximation)",
        "source_masks_unchanged": True,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "clips": {},
    }
    for clip, frame_index in REPRESENTATIVE_FRAMES.items():
        mask_id = MASK_IDS.get(clip, clip)
        source_path = MASK_DIR / f"{mask_id}_roadway_mask.png"
        mask_gray = cv2.imread(str(source_path), cv2.IMREAD_GRAYSCALE)
        if mask_gray is None:
            raise FileNotFoundError(source_path)
        original = (mask_gray > 0).astype(np.uint8) * 255
        kernel_size = 2 * args.radius + 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
        )
        dilated = cv2.dilate(original, kernel)
        analysis_path = out_dir / f"{clip}_analysis_mask.png"
        cv2.imwrite(str(analysis_path), dilated)

        frame = None
        if frame_index is not None:
            video_path = VIDEO_DIR / f"{clip}.MP4"
            capture = cv2.VideoCapture(str(video_path))
            if not capture.isOpened():
                raise OSError(f"could not open {video_path}")
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            capture.release()
            if not ok or frame is None:
                raise OSError(f"could not read {clip} frame {frame_index}")
        else:
            # Mask-only overlay keeps the test clip's video pixels unread.
            frame = np.zeros((*original.shape, 3), dtype=np.uint8)
            frame[original > 0] = (24, 24, 24)

        overlay = frame.copy()
        # Original mask boundary: cyan. Dilated outer boundary: amber.
        original_contours, _ = cv2.findContours(
            original, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        dilated_contours, _ = cv2.findContours(
            dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(overlay, dilated_contours, -1, (0, 165, 255), 3)
        cv2.drawContours(overlay, original_contours, -1, (255, 255, 0), 3)
        label = (f"{clip} mask only (test pixels not read)" if frame_index is None
                 else f"{clip} frame {frame_index}")
        cv2.putText(overlay, label, (30, 55), cv2.FONT_HERSHEY_SIMPLEX,
                    1.2, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(overlay, f"original: cyan | dilation: amber | {args.radius} px",
                    (30, 105), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255, 255, 255), 2, cv2.LINE_AA)
        overlay_path = out_dir / f"{clip}_frame_overlay.png"
        cv2.imwrite(str(overlay_path), overlay)
        source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True
        ).stdout.strip()
        for artifact in (analysis_path, overlay_path):
            sidecar = {
                "code_commit": commit,
                "generator": str(Path(__file__).relative_to(ROOT)),
                "source_mask": str(source_path.relative_to(ROOT)),
                "source_mask_sha256": source_sha,
                "output_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "radius_px": args.radius,
                "scope": "TASK-009 only",
                "coordinate_system": "source_pixel",
                "unit": "pixels",
                "review_status": "representative geometry overlay",
                "representative_frame": frame_index,
                "test_video_pixels_opened": False,
            }
            Path(str(artifact) + ".meta.json").write_text(
                json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8"
            )
        manifest["clips"][clip] = {
            "source_mask": source_path.relative_to(ROOT).as_posix(),
            "mask_sha256": __import__("hashlib").sha256(source_path.read_bytes()).hexdigest(),
            "representative_frame": frame_index,
            "video_opened": frame_index is not None,
            "analysis_mask": f"{clip}_analysis_mask.png",
            "overlay": overlay_path.name,
            "original_pixels": int(np.count_nonzero(original)),
            "dilated_pixels": int(np.count_nonzero(dilated)),
        }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    Path(str(manifest_path) + ".meta.json").write_text(
        json.dumps({
            "code_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                capture_output=True, text=True
            ).stdout.strip(),
            "generator": str(Path(__file__).relative_to(ROOT)),
            "radius_px": args.radius,
            "scope": "TASK-009 only",
            "output_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "review_status": "polygon proposal; checkpoint approval pending",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    print(json.dumps({
        "clips": len(manifest["clips"]),
        "radius_px": args.radius,
        "output": str(out_dir.relative_to(ROOT)),
        "test_video_pixels_opened": False,
        "pixel_counts": {
            k: {"original": v["original_pixels"], "dilated": v["dilated_pixels"]}
            for k, v in manifest["clips"].items()
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
