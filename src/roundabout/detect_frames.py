"""Run the configured sliced detector on a sparse set of exact video frames."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

from .detect_track import CLASS_PROFILES, detect_sliced, make_slices
from .paths import display_project_path, resolve_project_path


DETECTION_FIELDS = [
    "video_id", "frame_index", "timestamp_seconds", "class_id", "object_class",
    "source_class_id", "source_class_name", "confidence", "x1", "y1", "x2",
    "y2", "pass_id", "tile_center_candidate_ids",
]
TILE_DIAGNOSTIC_FIELDS = [
    "frame_index", "tile_id", "confidence_threshold", "detection_count",
    "max_det", "max_det_reached",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def detection_frame_indices(
    observations_path: Path,
    start_frame: int,
    end_frame: int,
    grid_start: int,
    grid_step: int,
    grid_count: int,
) -> list[int]:
    """Union the fixed 60-frame grid with every GT observation frame."""
    with observations_path.open(encoding="utf-8-sig", newline="") as stream:
        observation_frames = {
            int(row["frame_index"])
            for row in csv.DictReader(stream)
            if start_frame <= int(row["frame_index"]) <= end_frame
        }
    grid = {grid_start + offset * grid_step for offset in range(grid_count)}
    frames = sorted(frame for frame in grid | observation_frames
                    if start_frame <= frame <= end_frame)
    if any(frame % 2 for frame in frames):
        raise ValueError("Detection frame set contains an odd frame index")
    return frames


def write_output_metadata(output_path: Path, metadata: dict[str, object]) -> Path:
    """Write a sidecar for one output file, including the output's own hash."""
    sidecar = Path(f"{output_path}.meta.json")
    payload = {
        **metadata,
        "artifact_path": output_path.as_posix(),
        "artifact_sha256": sha256_file(output_path),
    }
    sidecar.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return sidecar


def git_provenance(project_root: Path) -> dict[str, object]:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_root, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=project_root,
    )
    diff = subprocess.check_output(
        ["git", "diff", "--binary", "HEAD"], cwd=project_root,
    )
    clean = not status
    snapshot = hashlib.sha256()
    snapshot.update(diff)
    snapshot.update(status)
    if not clean:
        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=project_root,
        ).split(b"\0")
        for raw_path in sorted(item for item in untracked if item):
            path = project_root / raw_path.decode("utf-8")
            snapshot.update(raw_path)
            if path.is_file():
                snapshot.update(bytes.fromhex(sha256_file(path)))
    return {
        "git_commit": commit,
        "worktree_clean": clean,
        "git_diff_sha256": hashlib.sha256(diff).hexdigest() if not clean else None,
        "worktree_snapshot_sha256": snapshot.hexdigest() if not clean else None,
    }


def detection_tile_ids(
    box: list[float], slices: list[tuple[int, int, int, int]]
) -> list[int]:
    """Return slices containing the detected box center (1-based slice IDs)."""
    center_x = (box[0] + box[2]) / 2
    center_y = (box[1] + box[3]) / 2
    return [
        index for index, (x1, y1, x2, y2) in enumerate(slices, start=1)
        if x1 <= center_x < x2 and y1 <= center_y < y2
    ]


def run_detection_frames(
    video_path: Path,
    output_path: Path,
    config_path: Path,
    frame_indices: list[int],
    confidence: float | None = None,
    pass_id: str = "A",
    allow_cpu: bool = False,
    execution_arguments: dict[str, object] | None = None,
    frame_source_path: Path | None = None,
) -> dict[str, object]:
    """Write detections for requested frames, without creating tracker state."""
    started = time.perf_counter()
    cuda_available = torch.cuda.is_available()
    if not cuda_available and not allow_cpu:
        raise RuntimeError(
            "CUDA is unavailable. Pass --allow-cpu only to explicitly permit CPU inference."
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    detection = config["detection"]
    threshold = float(detection["confidence"] if confidence is None else confidence)
    weight_path = resolve_project_path(detection["weights"])
    project_root = resolve_project_path(".")
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    if not config_path.is_file():
        raise FileNotFoundError(config_path)
    if not weight_path.is_file():
        raise FileNotFoundError(weight_path)
    tile_diagnostics_path = output_path.with_name("tile_diagnostics.csv")
    expected_outputs = [
        output_path, tile_diagnostics_path,
        Path(f"{output_path}.meta.json"),
        Path(f"{tile_diagnostics_path}.meta.json"),
    ]
    existing = [path for path in expected_outputs if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite detection outputs: {existing}")
    device: int | str = 0 if cuda_available else "cpu"
    device_name = torch.cuda.get_device_name(0) if cuda_available else "CPU"
    git_info = git_provenance(project_root)
    input_evidence = {
        "configuration": {
            "path": config_path.as_posix(), "sha256": sha256_file(config_path),
        },
        "weights": {
            "path": weight_path.as_posix(), "sha256": sha256_file(weight_path),
        },
        "video": {
            "path": video_path.as_posix(), "sha256": sha256_file(video_path),
        },
    }
    if frame_source_path is not None:
        input_evidence["frame_selection_ground_truth"] = {
            "path": frame_source_path.as_posix(),
            "sha256": sha256_file(frame_source_path),
        }
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    slices = make_slices(
        width, height, int(detection["slice_width"]),
        int(detection["slice_height"]), float(detection["slice_overlap"]),
    )
    model = YOLO(str(resolve_project_path(detection["weights"])))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    tile_row_count = 0
    try:
        with output_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=DETECTION_FIELDS)
            writer.writeheader()
            with tile_diagnostics_path.open(
                "w", encoding="utf-8", newline=""
            ) as tile_stream:
                tile_writer = csv.DictWriter(
                    tile_stream, fieldnames=TILE_DIAGNOSTIC_FIELDS
                )
                tile_writer.writeheader()
                profile_name = str(detection["class_profile"])
                mapped_names = {
                    mapped_id: mapped_name
                    for mapped_id, mapped_name, _ in CLASS_PROFILES[profile_name].values()
                }
                for frame_index in frame_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                    ok, frame = cap.read()
                    decoded_index = int(round(cap.get(cv2.CAP_PROP_POS_FRAMES))) - 1
                    if not ok or decoded_index != frame_index:
                        raise RuntimeError(
                            f"Frame seek mismatch: requested={frame_index}, decoded={decoded_index}"
                        )
                    boxes, scores, classes, source_classes, source_names = detect_sliced(
                        model, frame, slices, threshold, float(detection["nms_iou"]),
                        int(detection["image_size"]), device, profile_name,
                    )
                    max_det = int(model.predictor.args.max_det)
                    crops = [frame[y1:y2, x1:x2] for x1, y1, x2, y2 in slices]
                    for tile_id, crop in enumerate(crops, start=1):
                        result = model.predict(
                            crop,
                            conf=threshold,
                            iou=float(detection["nms_iou"]),
                            classes=list(CLASS_PROFILES[profile_name]),
                            imgsz=int(detection["image_size"]),
                            device=device,
                            verbose=False,
                        )[0]
                        detection_count = 0 if result.boxes is None else len(result.boxes)
                        tile_writer.writerow({
                            "frame_index": frame_index,
                            "tile_id": tile_id,
                            "confidence_threshold": threshold,
                            "detection_count": detection_count,
                            "max_det": max_det,
                            "max_det_reached": detection_count >= max_det,
                        })
                        tile_row_count += 1
                    for box, score, class_id, source_class, source_name in zip(
                        boxes, scores, classes, source_classes, source_names
                    ):
                        box_values = [float(value) for value in box]
                        tile_ids = detection_tile_ids(box_values, slices)
                        writer.writerow({
                            "video_id": video_path.stem,
                            "frame_index": frame_index,
                            "timestamp_seconds": frame_index / fps,
                            "class_id": int(class_id),
                            "object_class": mapped_names[int(class_id)],
                            "source_class_id": int(source_class),
                            "source_class_name": str(source_name),
                            "confidence": float(score),
                            "x1": box_values[0], "y1": box_values[1],
                            "x2": box_values[2], "y2": box_values[3],
                            "pass_id": pass_id,
                            "tile_center_candidate_ids": ";".join(map(str, tile_ids)),
                        })
                        count += 1
    finally:
        cap.release()
    elapsed_seconds = time.perf_counter() - started
    metadata = {
        "schema_version": "raw_detection_output_meta_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **git_info,
        **input_evidence,
        "execution_arguments": execution_arguments or {
            "video": video_path.as_posix(),
            "output": output_path.as_posix(),
            "config": config_path.as_posix(),
            "frame_indices": frame_indices,
            "confidence": threshold,
            "pass_id": pass_id,
            "allow_cpu": allow_cpu,
        },
        "device": "cuda:0" if cuda_available else "cpu",
        "torch_version": torch.__version__,
        "cuda_available": cuda_available,
        "gpu_name": device_name,
        "ultralytics_version": importlib.metadata.version("ultralytics"),
        "supervision_version": importlib.metadata.version("supervision"),
        "confidence_threshold": threshold,
        "detector_settings": {
            "model": str(detection["model"]),
            "weights": str(detection["weights"]),
            "class_profile": str(detection["class_profile"]),
            "slice_width": int(detection["slice_width"]),
            "slice_height": int(detection["slice_height"]),
            "slice_overlap": float(detection["slice_overlap"]),
            "image_size": int(detection["image_size"]),
            "nms_iou": float(detection["nms_iou"]),
            "pass_id": pass_id,
            "max_det_per_tile": int(model.predictor.args.max_det),
        },
        "frames": {
            "indices": frame_indices,
            "count": len(frame_indices),
            "selection_rule": "common_grid_union_all_gt_observation_frames",
        },
        "detection_count": count,
        "tile_diagnostic_row_count": tile_row_count,
        "elapsed_seconds": elapsed_seconds,
        "frame_read_method": "seek_per_requested_frame",
        "coordinate_system": "source_pixel",
        "unit": "px",
        "review_status": "draft",
    }
    detections_meta = write_output_metadata(output_path, metadata)
    tile_meta = write_output_metadata(tile_diagnostics_path, metadata)
    return {
        "output": output_path.as_posix(),
        "tile_diagnostics": tile_diagnostics_path.as_posix(),
        "detections_meta": detections_meta.as_posix(),
        "tile_diagnostics_meta": tile_meta.as_posix(),
        "frame_count": len(frame_indices),
        "detection_count": count,
        "confidence_threshold": threshold,
        "device": metadata["device"],
        "cuda_available": cuda_available,
        "gpu_name": device_name,
        "elapsed_seconds": elapsed_seconds,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default="data/raw/before/DJI_0482.MP4")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="configs/baseline.json")
    parser.add_argument("--first-frame", type=int, default=4196)
    parser.add_argument("--frame-step", type=int, default=30)
    parser.add_argument("--frame-count", type=int, default=60)
    parser.add_argument(
        "--gt-observations",
        default="data/ground_truth/object_track_v1/gt_observations.csv",
    )
    parser.add_argument("--start-frame", type=int, default=4196)
    parser.add_argument("--end-frame", type=int, default=5994)
    parser.add_argument("--confidence", type=float, default=0.01)
    parser.add_argument("--pass-id", default="A")
    parser.add_argument(
        "--allow-cpu", action="store_true",
        help="Allow CPU inference if CUDA is unavailable (default: fail instead).",
    )
    args = parser.parse_args()
    frame_source_path = resolve_project_path(args.gt_observations)
    indices = detection_frame_indices(
        frame_source_path, args.start_frame, args.end_frame,
        args.first_frame, args.frame_step, args.frame_count,
    )
    result = run_detection_frames(
        resolve_project_path(args.video), resolve_project_path(args.output),
        resolve_project_path(args.config), indices, args.confidence, args.pass_id,
        allow_cpu=args.allow_cpu,
        execution_arguments={
            "argv": sys.argv,
            "video": args.video,
            "output": args.output,
            "config": args.config,
            "first_frame": args.first_frame,
            "frame_step": args.frame_step,
            "frame_count": args.frame_count,
            "gt_observations": args.gt_observations,
            "start_frame": args.start_frame,
            "end_frame": args.end_frame,
            "confidence": args.confidence,
            "pass_id": args.pass_id,
            "allow_cpu": args.allow_cpu,
            "frame_indices": indices,
        },
        frame_source_path=frame_source_path,
    )
    result["output"] = display_project_path(args.output)
    result["tile_diagnostics"] = display_project_path(
        resolve_project_path(args.output).with_name("tile_diagnostics.csv")
    )
    result["detections_meta"] = display_project_path(f"{args.output}.meta.json")
    result["tile_diagnostics_meta"] = display_project_path(
        resolve_project_path(args.output).with_name("tile_diagnostics.csv.meta.json")
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
