"""Write supplemental, threshold-explicit R01 checkpoint-3 diagnostics."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from roundabout.evaluate_detection import decompose_tracker_loss, normalized_box_row
from roundabout.evaluate_object_track import box_iou

RUN = ROOT / "outputs/evaluation/r01_detection_only_20261104_02/A"
OUT = RUN / "checkpoint3_supplement.json"
FILES = {
    "observations": ROOT / "data/ground_truth/object_track_v1/gt_observations.csv",
    "detections": RUN / "detections.csv",
    "tracks": ROOT / "outputs/evaluation_runs/r01_baseline_yolo11m_full_20261103_02/raw_tracker/tracks.csv",
    "task006_objects": ROOT / "outputs/evaluation/r01_gtv1_scoring_20261103_02/per_object.csv",
    "unresolved_ignores": RUN / "unresolved_ignore_ground_truth.csv",
    "unmatched_detections": RUN / "unmatched_detections.csv",
    "boundary_anchors": RUN / "tile_boundary_anchors.csv",
    "loss_decomposition": RUN / "loss_decomposition.csv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    if OUT.exists() or Path(f"{OUT}.meta.json").exists():
        raise FileExistsError(f"Refusing to overwrite {OUT}")
    gt = [normalized_box_row(row) for row in rows(FILES["observations"])]
    detections = [normalized_box_row(row) for row in rows(FILES["detections"])]
    tracks = [normalized_box_row(row) for row in rows(FILES["tracks"])]
    frames = {int(row["frame_index"]) for row in gt}

    iou_bins = {}
    for threshold in (0.01, 0.15):
        by_frame = defaultdict(list)
        for detection in detections:
            if float(detection["confidence"]) >= threshold:
                by_frame[int(detection["frame_index"])].append(detection)
        counts = Counter()
        for anchor in gt:
            best = max((box_iou(anchor["box"], det["box"])
                        for det in by_frame[int(anchor["frame_index"])]), default=0.0)
            band = ("no_overlap" if best <= 0 else "0_to_0.3" if best < 0.3
                    else "0.3_to_0.5" if best < 0.5 else "at_least_0.5")
            counts[band] += 1
        iou_bins[str(threshold)] = dict(counts)

    loss_by_iou = {}
    for threshold in (0.5, 0.3):
        loss = decompose_tracker_loss(
            gt, detections, tracks, frames, 0.15, 0.25, threshold
        )
        loss_by_iou[str(threshold)] = {
            cls: dict(Counter(row["category"] for row in loss
                              if row["object_class"] == cls))
            for cls in ("person", "car", "motorcycle")
        }

    task006_rows = rows(FILES["task006_objects"])
    raw_tracker_class_match = {}
    for threshold in ("0.5", "0.3"):
        raw_tracker_class_match[threshold] = {}
        for cls in ("person", "car", "motorcycle"):
            selected = [row for row in task006_rows
                        if row["stage"] == "raw_tracker"
                        and row["iou_threshold"] == threshold
                        and row["object_class"] == cls]
            raw_tracker_class_match[threshold][cls] = {
                "matched_anchors_class_compatible": sum(
                    int(row["class_match_count"]) for row in selected
                ),
                "anchors": sum(int(row["anchors"]) for row in selected),
            }

    unresolved = rows(FILES["unresolved_ignores"])
    unresolved_frames = {int(row["frame_index"]) for row in unresolved}
    unmatched = rows(FILES["unmatched_detections"])
    unmatched_in_unresolved_frames = [row for row in unmatched
                                      if int(row["frame_index"]) in unresolved_frames]
    boundary = rows(FILES["boundary_anchors"])
    boundary_vehicle_keys = {
        (row["gt_object_id"], row["frame_index"])
        for row in boundary if row["vehicle_anchor"] == "True"
    }
    loss_rows = rows(FILES["loss_decomposition"])
    boundary_loss_counts = dict(Counter(
        row["category"] for row in loss_rows
        if (row["gt_object_id"], row["frame_index"]) in boundary_vehicle_keys
    ))

    payload = {
        "schema_version": "r01_checkpoint3_supplement_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "confidence_iou_anchor_distribution": {
            "definition": "Best IoU over any-class detections per GT anchor; no class filtering.",
            "counts": iou_bins,
        },
        "tracker_loss_by_iou_class": loss_by_iou,
        "task006_raw_tracker_class_compatible_matches": raw_tracker_class_match,
        "tile_boundary_vehicle_loss_categories_iou_0_5": boundary_loss_counts,
        "unresolved_ignore": {
            "count": len(unresolved),
            "included_in_interpolated_ignore_ground_truth": False,
            "unmatched_detections_on_same_frames": len(unmatched_in_unresolved_frames),
            "same_frame_unmatched_by_class": dict(Counter(
                row["object_class"] for row in unmatched_in_unresolved_frames
            )),
            "spatial_attribution_possible": False,
            "interpretation": (
                "No interpolated crowd box exists for unresolved rows; detections are not "
                "ignored by an ignore region. Same-frame unmatched records are FP in "
                "complete-frame precision, but cannot be spatially attributed to the "
                "unresolved object location."
            ),
        },
        "unmatched_detections": {
            "count": len(unmatched), "confidence_threshold": 0.15,
            "iou_threshold": 0.5, "frame_scope": "54 complete frames",
            "by_class": dict(Counter(row["object_class"] for row in unmatched)),
        },
        "inputs": {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
                   for name, path in FILES.items()},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=ROOT
    )
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "worktree_clean": not status,
        "git_diff_sha256": hashlib.sha256(diff).hexdigest() if status else None,
        "analysis_script": str(Path(__file__).relative_to(ROOT)),
        "analysis_script_sha256": sha256(Path(__file__)),
        "inputs": payload["inputs"],
        "coordinate_system": "source_pixel",
        "unit": "count_and_ratio",
        "review_status": "provisional_automatic",
        "artifact_sha256": sha256(OUT),
    }
    Path(f"{OUT}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "ok", "output": str(OUT.relative_to(ROOT)),
                      "anchor_bins": iou_bins, "tracker_loss": loss_by_iou,
                      "unmatched_on_unresolved_frames": len(unmatched_in_unresolved_frames)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
