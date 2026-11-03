"""Compare the current per-video and legacy roadway masks on one source frame."""

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
DEFAULT_OUTPUT = (
    ROOT / "outputs/diagnostics/roadway_mask_comparison_DJI_0482_4196_20261103"
)
FRAME_INDEX = 4196


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_source_frame(video_path: Path, frame_index: int) -> tuple[np.ndarray, float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise FileNotFoundError(f"Could not open source video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        capture.release()
        raise ValueError(f"Invalid source FPS: {fps}")
    if not capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index):
        capture.release()
        raise RuntimeError(f"Could not seek to source frame {frame_index}")
    ok, frame = capture.read()
    actual_next_frame = int(round(capture.get(cv2.CAP_PROP_POS_FRAMES)))
    capture.release()
    if not ok:
        raise RuntimeError(f"Could not decode source frame {frame_index}")
    if actual_next_frame != frame_index + 1:
        raise RuntimeError(
            f"Seek mismatch: requested {frame_index}, next frame is {actual_next_frame}"
        )
    return frame, fps


def blend_mask(
    frame: np.ndarray, mask: np.ndarray, color_bgr: tuple[int, int, int], alpha: float
) -> np.ndarray:
    result = frame.copy()
    color = np.asarray(color_bgr, dtype=np.float32)
    selected = mask
    result[selected] = np.clip(
        frame[selected].astype(np.float32) * (1 - alpha) + color * alpha,
        0,
        255,
    ).astype(np.uint8)
    return result


def add_header(image: np.ndarray, lines: list[str]) -> np.ndarray:
    result = image.copy()
    height, width = result.shape[:2]
    header_height = 104
    result[:header_height] = (20, 20, 20)
    scale = max(0.8, width / 2400)
    thickness = max(2, round(scale * 2))
    for index, line in enumerate(lines):
        cv2.putText(
            result,
            line,
            (36, round(40 + index * 42)),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (245, 245, 245),
            thickness,
            cv2.LINE_AA,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite output directory: {output_dir}")

    video = ROOT / "data/raw/before/DJI_0482.MP4"
    by_video_path = ROOT / "data/calibration/by_video/DJI_0482_roadway_mask.png"
    legacy_path = ROOT / "data/calibration/legacy/roadway_mask.png"
    by_video_gray = cv2.imread(str(by_video_path), cv2.IMREAD_GRAYSCALE)
    legacy_gray = cv2.imread(str(legacy_path), cv2.IMREAD_GRAYSCALE)
    if by_video_gray is None or legacy_gray is None:
        raise FileNotFoundError("Could not read one or both roadway masks")
    if by_video_gray.shape != legacy_gray.shape:
        raise ValueError(
            f"Mask shape mismatch: by_video={by_video_gray.shape}, "
            f"legacy={legacy_gray.shape}"
        )

    frame, fps = read_source_frame(video, FRAME_INDEX)
    if frame.shape[:2] != by_video_gray.shape:
        raise ValueError(
            f"Frame/mask shape mismatch: frame={frame.shape[:2]}, "
            f"masks={by_video_gray.shape}"
        )

    by_video = by_video_gray > 0
    legacy = legacy_gray > 0
    total_pixels = int(by_video.size)
    by_video_only = by_video & ~legacy
    legacy_only = legacy & ~by_video
    different = by_video ^ legacy

    by_overlay = blend_mask(frame, by_video, (40, 210, 70), 0.36)
    legacy_overlay = blend_mask(frame, legacy, (40, 210, 70), 0.36)
    difference_base = np.clip(frame.astype(np.float32) * 0.48, 0, 255).astype(
        np.uint8
    )
    difference_overlay = blend_mask(
        difference_base, by_video_only, (255, 0, 220), 0.92
    )
    difference_overlay = blend_mask(
        difference_overlay, legacy_only, (0, 220, 255), 0.92
    )

    images = {
        "roadway_by_video_overlay.png": add_header(
            by_overlay,
            [
                "DJI_0482 source frame 4196 | by_video roadway mask",
                "Green overlay = mask pixels (grayscale > 0)",
            ],
        ),
        "roadway_legacy_overlay.png": add_header(
            legacy_overlay,
            [
                "DJI_0482 source frame 4196 | legacy roadway mask",
                "Green overlay = mask pixels (grayscale > 0)",
            ],
        ),
        "roadway_mask_difference.png": add_header(
            difference_overlay,
            [
                "DJI_0482 source frame 4196 | roadway mask differences only",
                "Magenta = by_video only | Yellow = legacy only | background dimmed",
            ],
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    for name, image in images.items():
        if not cv2.imwrite(str(output_dir / name), image):
            raise OSError(f"Could not write image: {output_dir / name}")

    metrics = {
        "video_id": "DJI_0482",
        "frame_index": FRAME_INDEX,
        "timestamp_seconds": FRAME_INDEX / fps,
        "source_fps": fps,
        "width_pixels": int(frame.shape[1]),
        "height_pixels": int(frame.shape[0]),
        "total_pixels": total_pixels,
        "mask_membership_rule": "grayscale pixel value > 0",
        "by_video": {
            "path": str(by_video_path.relative_to(ROOT)),
            "sha256": sha256(by_video_path),
            "roadway_pixels": int(np.count_nonzero(by_video)),
            "roadway_area_ratio": float(np.count_nonzero(by_video) / total_pixels),
        },
        "legacy": {
            "path": str(legacy_path.relative_to(ROOT)),
            "sha256": sha256(legacy_path),
            "roadway_pixels": int(np.count_nonzero(legacy)),
            "roadway_area_ratio": float(np.count_nonzero(legacy) / total_pixels),
        },
        "difference": {
            "different_pixels": int(np.count_nonzero(different)),
            "different_pixel_ratio": float(np.count_nonzero(different) / total_pixels),
            "by_video_only_pixels": int(np.count_nonzero(by_video_only)),
            "by_video_only_ratio": float(np.count_nonzero(by_video_only) / total_pixels),
            "legacy_only_pixels": int(np.count_nonzero(legacy_only)),
            "legacy_only_ratio": float(np.count_nonzero(legacy_only) / total_pixels),
        },
        "interpretation_limit": (
            "Pixel geometry comparison only; no GT boxes, associations, or scores used."
        ),
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty_status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    script_path = Path(__file__).resolve()
    input_metadata = [
        {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
        for path in (video, by_video_path, legacy_path)
    ]
    base_meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "working_tree_clean": not dirty_status,
        "working_tree_status": dirty_status,
        "script_path": str(script_path.relative_to(ROOT)),
        "script_sha256": sha256(script_path),
        "inputs": input_metadata,
        "video_id": "DJI_0482",
        "frame_index": FRAME_INDEX,
        "coordinate_system": "source_pixel",
        "units": "pixel and dimensionless ratio",
        "review_status": "diagnostic_mask_comparison_no_GT_used",
    }
    for name in images:
        meta = {**base_meta, "artifact_path": name, "artifact_sha256": sha256(output_dir / name)}
        (output_dir / f"{name}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary_meta = {
        **base_meta,
        "artifact_path": "summary.json",
        "artifact_sha256": sha256(summary_path),
    }
    (output_dir / "summary.json.meta.json").write_text(
        json.dumps(summary_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps({"output_dir": str(output_dir), **metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
