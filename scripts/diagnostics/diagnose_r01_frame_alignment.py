"""Read-only frame-index alignment diagnostic for R01 GT and raw tracker boxes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from roundabout.evaluate_object_track import box_iou, read_csv
from scripts.blind_gt_review_viewer import FrameReader


ROOT = Path(__file__).resolve().parents[2]
VIDEO = ROOT / "data/raw/before/DJI_0482.MP4"
GT_CSV = ROOT / "data/ground_truth/object_track_v1/gt_observations.csv"
RAW_CSV = ROOT / "outputs/evaluation_runs/r01_baseline_yolo11m_full_20261103_02/raw_tracker/tracks.csv"
FRAME_INDEX = 4196
OFFSETS = tuple(range(-20, 21, 2))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def xyxy(row: dict[str, str]) -> tuple[float, float, float, float]:
    return tuple(float(row[name]) for name in ("x1", "y1", "x2", "y2"))


def write_json(path: Path, payload: object, meta: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.with_name(path.name + ".meta.json").write_text(
        json.dumps(meta | {"output_path": path.relative_to(ROOT).as_posix()},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_image(path: Path, image: np.ndarray, meta: dict[str, object]) -> None:
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Could not write diagnostic image: {path}")
    path.with_name(path.name + ".meta.json").write_text(
        json.dumps(meta | {"output_path": path.relative_to(ROOT).as_posix(),
                           "image_shape": list(image.shape),
                           "pixel_dtype": str(image.dtype)},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sequential_frame(path: Path, requested: int) -> tuple[np.ndarray, dict[str, object]]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise FileNotFoundError(path)
    first_position = capture.get(cv2.CAP_PROP_POS_FRAMES)
    frame = None
    decoded = -1
    for decoded in range(requested + 1):
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            raise RuntimeError(f"Sequential decode failed at source frame {decoded}")
    next_position = capture.get(cv2.CAP_PROP_POS_FRAMES)
    capture.release()
    return frame, {"method": "open from start and call read() through requested index",
                   "initial_position_frames": first_position,
                   "last_decoded_frame_index": decoded,
                   "next_position_frames": next_position}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="r01_frame_alignment_20261103_01")
    args = parser.parse_args()
    output_dir = ROOT / "outputs/diagnostics" / args.run_id
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite diagnostics: {output_dir}")
    output_dir.mkdir(parents=True)

    gt_rows = [row for row in read_csv(GT_CSV)
               if row["in_scope"].lower() == "true"]
    raw_rows = read_csv(RAW_CSV)
    gt_by_frame: dict[int, list[dict[str, str]]] = defaultdict(list)
    auto_by_frame: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in gt_rows:
        gt_by_frame[int(row["frame_index"])].append(row)
    for row in raw_rows:
        auto_by_frame[int(row["frame_index"])].append(row)

    class_names = sorted({row["object_class"] for row in gt_rows})
    offset_rows = []
    offset_summary = {}
    for class_name in class_names:
        anchors = [row for row in gt_rows if row["object_class"] == class_name]
        class_result = []
        for offset in OFFSETS:
            best_ious = []
            for anchor in anchors:
                target_frame = int(anchor["frame_index"]) + offset
                ai_rows = auto_by_frame.get(target_frame, [])
                anchor_box = xyxy(anchor)
                best_iou = max(
                    (box_iou(anchor_box, xyxy(ai)) for ai in ai_rows),
                    default=0.0,
                )
                best_ious.append(best_iou)
            mean_best_iou = float(np.mean(best_ious)) if best_ious else 0.0
            matched_count = sum(value >= 0.5 for value in best_ious)
            record = {
                "gt_class": class_name,
                "offset_k_frames": offset,
                "gt_anchor_count": len(anchors),
                "mean_best_iou": mean_best_iou,
                "best_iou_ge_0_5_anchor_count": matched_count,
            }
            offset_rows.append(record)
            class_result.append(record)
        maximum_mean = max(row["mean_best_iou"] for row in class_result)
        maximum_match_count = max(row["best_iou_ge_0_5_anchor_count"] for row in class_result)
        offset_summary[class_name] = {
            "mean_best_iou_max_offsets": [row["offset_k_frames"] for row in class_result
                                           if np.isclose(row["mean_best_iou"], maximum_mean)],
            "maximum_mean_best_iou": maximum_mean,
            "iou_ge_0_5_max_offsets": [row["offset_k_frames"] for row in class_result
                                        if row["best_iou_ge_0_5_anchor_count"] == maximum_match_count],
            "maximum_iou_ge_0_5_anchor_count": maximum_match_count,
        }

    meta = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "diagnostic_status": "read_only_non_official_diagnostic",
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                text=True).strip(),
        "worktree_status": subprocess.check_output(
            ["git", "status", "--short"], cwd=ROOT, text=True
        ).splitlines(),
        "video_path": VIDEO.relative_to(ROOT).as_posix(),
        "video_sha256": sha256(VIDEO),
        "gt_observations_path": GT_CSV.relative_to(ROOT).as_posix(),
        "gt_observations_sha256": sha256(GT_CSV),
        "raw_tracker_path": RAW_CSV.relative_to(ROOT).as_posix(),
        "raw_tracker_sha256": sha256(RAW_CSV),
        "gt_modified": False,
        "evaluation_outputs_modified": False,
        "official_metrics_changed": False,
    }
    csv_path = output_dir / "offset_scan_by_class.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "gt_class", "offset_k_frames", "gt_anchor_count", "mean_best_iou",
            "best_iou_ge_0_5_anchor_count",
        ])
        writer.writeheader()
        writer.writerows(offset_rows)
    csv_path.with_name(csv_path.name + ".meta.json").write_text(
        json.dumps(meta | {"output_path": csv_path.relative_to(ROOT).as_posix(),
                           "matching_rule": "per GT anchor, maximum IoU over all raw AI boxes at frame_index + k; no one-to-one assignment"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_json(output_dir / "offset_scan_summary.json", offset_summary, meta)

    sequential, sequential_info = sequential_frame(VIDEO, FRAME_INDEX)
    reader = FrameReader(VIDEO, cache_size=1)
    tool_frame = reader.read(FRAME_INDEX)
    tool_info = {
        "method": "FrameReader.read(frame_index); first request uses CAP_PROP_POS_FRAMES seek, then read()",
        "last_index_before_request": None,
        "decoded_index_check": round(reader.capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1,
        "next_position_frames": reader.capture.get(cv2.CAP_PROP_POS_FRAMES),
    }
    reader.close()
    if sequential.shape != tool_frame.shape:
        raise RuntimeError(f"Decoded frame shape differs: {sequential.shape} vs {tool_frame.shape}")
    absdiff = cv2.absdiff(sequential, tool_frame)
    equal = bool(np.array_equal(sequential, tool_frame))
    frame_comparison = {
        "frame_index": FRAME_INDEX,
        "sequential_read": sequential_info,
        "gt_tool_read": tool_info,
        "shape": list(sequential.shape),
        "pixel_identical": equal,
        "different_channel_values": int(np.count_nonzero(absdiff)),
        "total_channel_values": int(absdiff.size),
        "different_pixel_locations": int(np.count_nonzero(np.any(absdiff != 0, axis=2))),
        "maximum_absolute_channel_difference": int(absdiff.max(initial=0)),
        "mean_absolute_channel_difference": float(absdiff.mean()),
        "sequential_frame_sha256": hashlib.sha256(sequential.tobytes()).hexdigest(),
        "gt_tool_frame_sha256": hashlib.sha256(tool_frame.tobytes()).hexdigest(),
    }
    write_json(output_dir / "frame_4196_pixel_comparison.json", frame_comparison, meta)
    write_image(output_dir / "frame_4196_sequential.png", sequential,
                meta | {"decode_method": sequential_info})
    write_image(output_dir / "frame_4196_gt_tool_seek.png", tool_frame,
                meta | {"decode_method": tool_info})
    amplified = np.minimum(absdiff.astype(np.uint16) * 8, 255).astype(np.uint8)
    write_image(output_dir / "frame_4196_absdiff_x8.png", amplified,
                meta | {"decode_comparison": "absolute difference multiplied by 8 for display"})

    print(json.dumps({
        "output_dir": output_dir.relative_to(ROOT).as_posix(),
        "offset_scan_summary": offset_summary,
        "frame_4196_pixel_comparison": frame_comparison,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
