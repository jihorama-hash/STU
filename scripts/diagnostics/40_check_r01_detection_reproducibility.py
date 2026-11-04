"""Validate A-run lineage and detector/raw-tracker box parity before scoring."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from roundabout.detect_frames import detection_frame_indices
from roundabout.evaluate_detection import load_evaluation_config, validate_inference_metadata
from roundabout.evaluate_object_track import box_iou, match_frame


RUN_DIR = PROJECT_ROOT / "outputs/evaluation/r01_detection_only_20261104_02/A"
DETECTION_PATH = RUN_DIR / "detections.csv"
DETECTION_META_PATH = Path(f"{DETECTION_PATH}.meta.json")
TILE_PATH = RUN_DIR / "tile_diagnostics.csv"
TILE_META_PATH = Path(f"{TILE_PATH}.meta.json")
LINEAGE_PATH = PROJECT_ROOT / (
    "outputs/evaluation_runs/r01_baseline_yolo11m_full_20261103_02/run_lineage.json"
)
TRACKS_PATH = PROJECT_ROOT / (
    "outputs/evaluation_runs/r01_baseline_yolo11m_full_20261103_02/raw_tracker/tracks.csv"
)
OBSERVATIONS_PATH = PROJECT_ROOT / "data/ground_truth/object_track_v1/gt_observations.csv"
OUTPUT_PATH = RUN_DIR / "reproducibility_check.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def as_box(row: dict[str, object]) -> dict[str, object]:
    return {
        **row,
        "box": [float(row[key]) for key in ("x1", "y1", "x2", "y2")],
    }


def main() -> int:
    detection_meta = json.loads(DETECTION_META_PATH.read_text(encoding="utf-8"))
    tile_meta = json.loads(TILE_META_PATH.read_text(encoding="utf-8"))
    lineage = json.loads(LINEAGE_PATH.read_text(encoding="utf-8"))
    evaluation_config = load_evaluation_config(
        PROJECT_ROOT / "configs/evaluation_detection_v1.yaml"
    )
    validate_inference_metadata(evaluation_config, detection_meta)
    checks = {
        "commit_is_7661721": detection_meta["git_commit"].startswith("7661721"),
        "worktree_clean": detection_meta["worktree_clean"] is True,
        "device_cuda_0": detection_meta["device"] == "cuda:0",
        "gpu_name": detection_meta["gpu_name"] == "NVIDIA GeForce RTX 5060 Ti",
        "video_sha_matches_TASK006": (
            detection_meta["video"]["sha256"] == lineage["video"]["sha256"]
        ),
        "config_sha_matches_TASK006": (
            detection_meta["configuration"]["sha256"] == lineage["config"]["sha256"]
        ),
        "weights_sha_matches_TASK006": (
            detection_meta["weights"]["sha256"] == lineage["weights"]["sha256"]
        ),
        "gt_observations_sha_matches_TASK006": (
            detection_meta["frame_selection_ground_truth"]["sha256"]
            == lineage["ground_truth"]["frozen_files"]["observations"]["sha256"]
        ),
        "detections_meta_sha_matches_csv": (
            detection_meta["artifact_sha256"] == sha256(DETECTION_PATH)
        ),
        "tile_meta_sha_matches_csv": tile_meta["artifact_sha256"] == sha256(TILE_PATH),
        "tile_meta_commit_matches": tile_meta["git_commit"] == detection_meta["git_commit"],
        "tile_confidence_is_0_01": (
            detection_meta["confidence_threshold"] == 0.01
            and tile_meta["confidence_threshold"] == 0.01
        ),
    }
    expected_frames = detection_frame_indices(
        OBSERVATIONS_PATH, 4196, 5994, 4196, 30, 60
    )
    detections = read_csv(DETECTION_PATH)
    tile_rows = read_csv(TILE_PATH)
    tracks = read_csv(TRACKS_PATH)
    detections_frames = detection_meta["frames"]["indices"]
    checks["frame_list_matches_GT_union"] = detections_frames == expected_frames
    checks["frame_count_is_236"] = len(detections_frames) == 236
    checks["tile_row_count_matches_frames_times_15"] = (
        len(tile_rows) == 236 * 15
    )
    checks["tile_csv_confidence_is_0_01"] = (
        bool(tile_rows)
        and {float(row["confidence_threshold"]) for row in tile_rows} == {0.01}
    )
    checks["raw_tracker_sha_matches_TASK006"] = (
        sha256(TRACKS_PATH)
        == lineage["artifacts"]["raw_tracker"]["tracks_csv_sha256"]
    )
    checks["output_files_hashes_match_TSK006_inputs"] = all(
        checks[key] for key in (
            "video_sha_matches_TASK006", "config_sha_matches_TASK006",
            "weights_sha_matches_TASK006", "gt_observations_sha_matches_TASK006",
        )
    )
    failed_preconditions = [name for name, passed in checks.items() if not passed]
    if failed_preconditions:
        report = {
            "status": "stopped_precondition_failure",
            "failed_checks": failed_preconditions,
            "checks": checks,
            "expected_frame_count": len(expected_frames),
        }
        write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    frame_set = set(expected_frames)
    detection_by_frame: dict[int, list[dict[str, object]]] = {}
    tracks_by_frame: dict[int, list[dict[str, object]]] = {}
    for row in detections:
        if int(row["frame_index"]) in frame_set and float(row["confidence"]) >= 0.15:
            detection_by_frame.setdefault(int(row["frame_index"]), []).append(as_box(row))
    for row in tracks:
        if int(row["frame_index"]) in frame_set:
            tracks_by_frame.setdefault(int(row["frame_index"]), []).append(as_box(row))

    track_count = matched_count = 0
    mismatches: list[dict[str, object]] = []
    for frame in expected_frames:
        track_rows = tracks_by_frame.get(frame, [])
        detection_rows = detection_by_frame.get(frame, [])
        pairs = match_frame(track_rows, detection_rows, 0.99)
        matched_tracks = {track_index for track_index, _, _ in pairs}
        track_count += len(track_rows)
        matched_count += len(matched_tracks)
        for track_index, row in enumerate(track_rows):
            if track_index not in matched_tracks:
                best_iou = max(
                    (box_iou(row["box"], candidate["box"])
                     for candidate in detection_rows),
                    default=0.0,
                )
                mismatches.append({
                    "frame_index": frame,
                    "track_id": row.get("track_id", ""),
                    "track_class": row.get("object_class", ""),
                    "best_detection_iou": best_iou,
                    "detections_at_or_above_0_15": len(detection_rows),
                })
    checks["all_RAW_tracker_boxes_match_conf_ge_0_15_iou_0_99"] = not mismatches
    report = {
        "status": "passed" if not mismatches else "stopped_reproducibility_mismatch",
        "checks": checks,
        "evaluation_run_id": detection_meta["execution_arguments"]["output"],
        "frame_count": len(expected_frames),
        "frame_indices": expected_frames,
        "track_boxes_checked": track_count,
        "matched_track_boxes": matched_count,
        "unmatched_track_boxes": len(mismatches),
        "mismatches": mismatches,
        "iou_threshold": 0.99,
        "confidence_minimum": 0.15,
        "matching": "class-agnostic one-to-one Hungarian per frame",
    }
    write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not mismatches else 3


def write_report(report: dict[str, object]) -> None:
    OUTPUT_PATH.write_text(json.dumps({
        **report,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": "766172146caa5570a8014863f9eb67a6f8e570f7",
        "coordinate_system": "source_pixel",
        "unit": "px",
        "review_status": "automatic_reproducibility_check",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": "766172146caa5570a8014863f9eb67a6f8e570f7",
        "worktree_clean_at_A_run": True,
        "detection_meta_path": str(DETECTION_META_PATH.relative_to(PROJECT_ROOT)),
        "detection_meta_sha256": sha256(DETECTION_META_PATH),
        "tracks_path": str(TRACKS_PATH.relative_to(PROJECT_ROOT)),
        "tracks_sha256": sha256(TRACKS_PATH),
        "coordinate_system": "source_pixel",
        "unit": "px",
        "review_status": "automatic_reproducibility_check",
        "artifact_path": str(OUTPUT_PATH.relative_to(PROJECT_ROOT)),
        "artifact_sha256": sha256(OUTPUT_PATH),
    }
    Path(f"{OUTPUT_PATH}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
