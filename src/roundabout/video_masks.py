"""Create source-coordinate masks from reference-video calibration masks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .paths import resolve_project_path


def reference_to_source_matrix(source_to_reference: list[list[float]]) -> np.ndarray:
    return np.linalg.inv(np.asarray(source_to_reference, dtype=np.float64))


def source_to_source_matrix(
    origin_to_reference: list[list[float]],
    target_to_reference: list[list[float]],
) -> np.ndarray:
    return (
        reference_to_source_matrix(target_to_reference)
        @ np.asarray(origin_to_reference, dtype=np.float64)
    )


def warp_binary_mask(mask: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    warped = cv2.warpPerspective(
        mask,
        matrix,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return np.where(warped > 127, 255, 0).astype(np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--homographies",
        default="data/calibration/legacy/alignment_homographies.json",
    )
    parser.add_argument(
        "--roadway-mask", default="data/calibration/legacy/roadway_mask.png"
    )
    parser.add_argument(
        "--exclusion-mask",
        default="data/calibration/vehicle_false_positive_exclusion_mask.png",
    )
    parser.add_argument("--exclusion-origin", default="DJI_0482")
    parser.add_argument("--output-dir", default="data/calibration/by_video")
    args = parser.parse_args()

    homographies = json.loads(
        resolve_project_path(args.homographies).read_text(encoding="utf-8")
    )
    roadway = cv2.imread(
        str(resolve_project_path(args.roadway_mask)), cv2.IMREAD_GRAYSCALE
    )
    exclusion = cv2.imread(
        str(resolve_project_path(args.exclusion_mask)), cv2.IMREAD_GRAYSCALE
    )
    if roadway is None or exclusion is None:
        raise FileNotFoundError("Calibration mask is missing")
    output = resolve_project_path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    origin_h = homographies["videos"][args.exclusion_origin]["h"]
    manifest = {
        "reference": homographies["reference"],
        "exclusion_origin": args.exclusion_origin,
        "videos": {},
    }
    for video_id, calibration in homographies["videos"].items():
        target_h = calibration["h"]
        roadway_warped = warp_binary_mask(
            roadway, reference_to_source_matrix(target_h)
        )
        exclusion_warped = warp_binary_mask(
            exclusion, source_to_source_matrix(origin_h, target_h)
        )
        roadway_name = f"{video_id}_roadway_mask.png"
        exclusion_name = f"{video_id}_vehicle_exclusion_mask.png"
        cv2.imwrite(str(output / roadway_name), roadway_warped)
        cv2.imwrite(str(output / exclusion_name), exclusion_warped)
        manifest["videos"][video_id] = {
            "roadway_mask": roadway_name,
            "vehicle_exclusion_mask": exclusion_name,
            "roadway_pixels": int(np.count_nonzero(roadway_warped)),
            "vehicle_exclusion_pixels": int(np.count_nonzero(exclusion_warped)),
        }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "videos": len(manifest["videos"]),
        "output_dir": str(output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
