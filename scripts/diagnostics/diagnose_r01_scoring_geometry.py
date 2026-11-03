"""Non-official localization and merge-link diagnostics for the frozen R01 sample."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from roundabout.evaluate_object_track import box_iou, read_csv


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "outputs/evaluation_runs/r01_baseline_yolo11m_full_20261103_02"
GT_DIR = ROOT / "data/ground_truth/object_track_v1"
VIDEO = ROOT / "data/raw/before/DJI_0482.MP4"
START, END = 4196, 5994
DISPLAY_FRAMES = (4196, 4706, 5306, 5816)
STAGES = {
    "raw_tracker": RUN_DIR / "raw_tracker/tracks.csv",
    "filtered": RUN_DIR / "filtered/filtered_tracks.csv",
    "merged": RUN_DIR / "merged/filtered_tracks_merged.csv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def box(row: dict[str, str]) -> tuple[float, float, float, float]:
    return tuple(float(row[key]) for key in ("x1", "y1", "x2", "y2"))


def center_distance(first, second) -> float:
    acx, acy = (first[0] + first[2]) / 2, (first[1] + first[3]) / 2
    bcx, bcy = (second[0] + second[2]) / 2, (second[1] + second[3]) / 2
    return float(np.hypot(acx - bcx, acy - bcy))


def category(iou: float) -> str:
    if iou == 0:
        return "0"
    if iou < 0.1:
        return "0-0.1"
    if iou < 0.3:
        return "0.1-0.3"
    if iou < 0.5:
        return "0.3-0.5"
    return ">=0.5"


def write_json(path: Path, value: object, common_meta: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.with_name(path.name + ".meta.json").write_text(
        json.dumps(common_meta | {"output_path": path.relative_to(ROOT).as_posix()},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]],
              common_meta: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    path.with_name(path.name + ".meta.json").write_text(
        json.dumps(common_meta | {"output_path": path.relative_to(ROOT).as_posix()},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def draw_boxes(image, gt_rows, auto_rows, crop=None):
    canvas = image.copy()
    for rows, color, prefix, id_key in (
        (gt_rows, (0, 255, 0), "GT", "gt_object_id"),
        (auto_rows, (0, 0, 255), "AI", "track_id"),
    ):
        for row in rows:
            x1, y1, x2, y2 = map(round, box(row))
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 3)
            label = f"{prefix}:{row[id_key]}"
            cv2.putText(canvas, label, (x1, max(20, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    if crop:
        x1, y1, x2, y2 = crop
        canvas = canvas[max(0, y1):min(canvas.shape[0], y2),
                        max(0, x1):min(canvas.shape[1], x2)]
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="r01_iou_diagnostics_20261103_01")
    args = parser.parse_args()
    output_dir = ROOT / "outputs/diagnostics" / args.run_id
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite diagnostics: {output_dir}")
    output_dir.mkdir(parents=True)
    lineage = json.loads((RUN_DIR / "run_lineage.json").read_text(encoding="utf-8"))
    manifest = json.loads((GT_DIR / "ground_truth_manifest.json").read_text(encoding="utf-8"))
    gt_rows = [row for row in read_csv(GT_DIR / "gt_observations.csv")
               if START <= int(row["frame_index"]) <= END and row["in_scope"] == "true"]
    gt_by_frame = defaultdict(list)
    for row in gt_rows:
        gt_by_frame[int(row["frame_index"])].append(row)
    auto_rows_by_stage = {}
    auto_by_stage_frame = {}
    for stage, path in STAGES.items():
        rows = [row for row in read_csv(path) if START <= int(row["frame_index"]) <= END]
        auto_rows_by_stage[stage] = rows
        per_frame = defaultdict(list)
        for row in rows:
            per_frame[int(row["frame_index"])].append(row)
        auto_by_stage_frame[stage] = per_frame

    common_meta = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "diagnostic_status": "non_official_diagnostic",
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                                text=True).strip(),
        "worktree_clean": not subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip(),
        "automatic_run_id": lineage["evaluation_run_id"],
        "input_sha256": {
            "gt_observations.csv": sha256(GT_DIR / "gt_observations.csv"),
            "video": sha256(VIDEO),
            **{stage: sha256(path) for stage, path in STAGES.items()},
        },
        "frozen_gt_sha256": {
            key: manifest["frozen_files"][key]["sha256"]
            for key in ("objects", "visibility_intervals", "observations")
        },
        "coordinate_system": "source_pixel",
        "unit": "px",
        "review_status": "diagnostic_only",
    }

    detailed = []
    geometry_summary = {}
    pedestrian_nearby = {}
    for stage, per_frame in auto_by_stage_frame.items():
        grouped = defaultdict(list)
        near_count = Counter()
        for gt in gt_rows:
            frame = int(gt["frame_index"])
            gt_box = box(gt)
            candidates = per_frame.get(frame, [])
            scored = [(box_iou(gt_box, box(candidate)), candidate) for candidate in candidates]
            best_iou, best_row = max(scored, key=lambda item: item[0]) if scored else (0.0, None)
            item = {"stage": stage, "frame_index": frame,
                    "gt_object_id": gt["gt_object_id"], "gt_class": gt["object_class"],
                    "best_iou": best_iou, "iou_bin": category(best_iou),
                    "best_auto_track_id": best_row["track_id"] if best_row else "",
                    "best_auto_class": best_row["object_class"] if best_row else ""}
            if best_row:
                ai_box = box(best_row)
                gt_area = max(0, gt_box[2]-gt_box[0]) * max(0, gt_box[3]-gt_box[1])
                ai_area = max(0, ai_box[2]-ai_box[0]) * max(0, ai_box[3]-ai_box[1])
                ratios = {
                    "area_ratio": ai_area / gt_area if gt_area else None,
                    "width_ratio": (ai_box[2]-ai_box[0]) / (gt_box[2]-gt_box[0]),
                    "height_ratio": (ai_box[3]-ai_box[1]) / (gt_box[3]-gt_box[1]),
                    "center_distance_px": center_distance(gt_box, ai_box),
                }
                item.update(ratios)
            else:
                item.update({"area_ratio": None, "width_ratio": None,
                             "height_ratio": None, "center_distance_px": None})
            detailed.append(item)
            grouped[gt["object_class"]].append(item)
            if gt["object_class"] == "person":
                nearby = [candidate for candidate in candidates
                          if candidate["object_class"] == "person"
                          and box_iou(gt_box, box(candidate)) < 0.3
                          and center_distance(gt_box, box(candidate)) <= 60]
                if nearby:
                    near_count["count"] += 1
        geometry_summary[stage] = {}
        for class_name, items in sorted(grouped.items()):
            bins = Counter(item["iou_bin"] for item in items)
            geometry_summary[stage][class_name] = {
                "gt_anchor_count": len(items),
                "best_iou_bins": {name: bins[name] for name in
                                   ("0", "0-0.1", "0.1-0.3", "0.3-0.5", ">=0.5")},
                "best_ai_box_pair_count": sum(item["area_ratio"] is not None for item in items),
                "positive_iou_pair_count": sum(item["best_iou"] > 0 for item in items),
                "median_ai_to_gt_area_ratio_best_ai_box": float(np.median(
                    [item["area_ratio"] for item in items if item["area_ratio"] is not None]
                )) if any(item["best_iou"] > 0 and item["area_ratio"] is not None for item in items) else None,
                "median_ai_to_gt_width_ratio_best_ai_box": float(np.median(
                    [item["width_ratio"] for item in items if item["width_ratio"] is not None]
                )) if any(item["best_iou"] > 0 and item["width_ratio"] is not None for item in items) else None,
                "median_ai_to_gt_height_ratio_best_ai_box": float(np.median(
                    [item["height_ratio"] for item in items if item["height_ratio"] is not None]
                )) if any(item["best_iou"] > 0 and item["height_ratio"] is not None for item in items) else None,
                "median_center_distance_px_best_ai_box": float(np.median(
                    [item["center_distance_px"] for item in items
                     if item["center_distance_px"] is not None]
                )) if any(item["best_iou"] > 0 and item["center_distance_px"] is not None for item in items) else None,
                "median_ai_to_gt_area_ratio_positive_iou_only": float(np.median(
                    [item["area_ratio"] for item in items
                     if item["best_iou"] > 0 and item["area_ratio"] is not None]
                )) if any(item["area_ratio"] is not None for item in items) else None,
                "median_ai_to_gt_width_ratio_positive_iou_only": float(np.median(
                    [item["width_ratio"] for item in items
                     if item["best_iou"] > 0 and item["width_ratio"] is not None]
                )) if any(item["width_ratio"] is not None for item in items) else None,
                "median_ai_to_gt_height_ratio_positive_iou_only": float(np.median(
                    [item["height_ratio"] for item in items
                     if item["best_iou"] > 0 and item["height_ratio"] is not None]
                )) if any(item["height_ratio"] is not None for item in items) else None,
                "median_center_distance_px_positive_iou_only": float(np.median(
                    [item["center_distance_px"] for item in items
                     if item["best_iou"] > 0 and item["center_distance_px"] is not None]
                )) if any(item["center_distance_px"] is not None for item in items) else None,
            }
        pedestrian_nearby[stage] = {
            "gt_person_anchor_count": sum(row["object_class"] == "person" for row in gt_rows),
            "iou_below_0_3_and_center_within_60px_count": near_count["count"],
        }

    write_csv(output_dir / "gt_anchor_geometry.csv", [
        "stage", "frame_index", "gt_object_id", "gt_class", "best_iou", "iou_bin",
        "best_auto_track_id", "best_auto_class", "area_ratio", "width_ratio",
        "height_ratio", "center_distance_px",
    ], detailed, common_meta | {"metric_definition":
        "Best IoU among all AI boxes at the same GT anchor; best-box ratios include zero-IoU ties if any AI box is present, with positive-IoU-only medians also supplied."})
    write_json(output_dir / "geometry_summary.json", geometry_summary, common_meta)
    write_json(output_dir / "pedestrian_nearby_low_iou.json", pedestrian_nearby,
               common_meta | {"criterion": "Any same-frame AI person box with IoU < 0.3 and center distance <= 60 px; count GT person anchors once."})

    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        raise FileNotFoundError(VIDEO)
    rendered = {}
    for frame in DISPLAY_FRAMES:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, image = cap.read()
        if not ok:
            raise RuntimeError(f"Could not read source frame {frame}")
        dest = output_dir / f"frame_{frame}_gt_ai_raw.jpg"
        overlay = draw_boxes(image, gt_by_frame[frame], auto_by_stage_frame["raw_tracker"].get(frame, []))
        if not cv2.imwrite(str(dest), overlay, [cv2.IMWRITE_JPEG_QUALITY, 94]):
            raise RuntimeError(f"Could not write {dest}")
        rendered[frame] = image
        dest.with_name(dest.name + ".meta.json").write_text(
            json.dumps(common_meta | {"output_path": dest.relative_to(ROOT).as_posix(),
                                      "frame_index": frame, "overlay":
                                      {"GT": "green", "AI_raw_tracker": "red"}},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    cap.release()

    crop_candidates = []
    for frame in DISPLAY_FRAMES:
        autos = [row for row in auto_by_stage_frame["raw_tracker"].get(frame, [])
                 if row["object_class"] == "person"]
        for gt in gt_by_frame[frame]:
            if gt["object_class"] != "person":
                continue
            gt_box = box(gt)
            qualifies = [(center_distance(gt_box, box(row)), row)
                         for row in autos
                         if box_iou(gt_box, box(row)) < 0.3
                         and center_distance(gt_box, box(row)) <= 60]
            if qualifies:
                distance, row = min(qualifies, key=lambda item: item[0])
                crop_candidates.append((distance, frame, gt, row))
    crop_candidates.sort(key=lambda item: item[0])
    crop_meta = []
    for index, (distance, frame, gt, auto_row) in enumerate(crop_candidates[:6], start=1):
        gb, ab = box(gt), box(auto_row)
        pad = 60
        rect = (int(min(gb[0], ab[0])-pad), int(min(gb[1], ab[1])-pad),
                int(max(gb[2], ab[2])+pad), int(max(gb[3], ab[3])+pad))
        crop_image = draw_boxes(rendered[frame], [gt], [auto_row], rect)
        dest = output_dir / f"pedestrian_crop_{index:02d}_frame_{frame}.jpg"
        if not cv2.imwrite(str(dest), crop_image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
            raise RuntimeError(f"Could not write {dest}")
        meta = common_meta | {"output_path": dest.relative_to(ROOT).as_posix(),
                              "frame_index": frame, "gt_object_id": gt["gt_object_id"],
                              "auto_track_id": auto_row["track_id"],
                              "iou": box_iou(gb, ab), "center_distance_px": distance,
                              "overlay": {"GT": "green", "AI_raw_tracker": "red"}}
        dest.with_name(dest.name + ".meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        crop_meta.append({key: meta[key] for key in
                          ("frame_index", "gt_object_id", "auto_track_id", "iou", "center_distance_px", "output_path")})
    write_json(output_dir / "pedestrian_crops_index.json", crop_meta, common_meta)

    report_path = RUN_DIR / "merged/continuation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    filtered_rows = read_csv(RUN_DIR / "filtered/filtered_tracks.csv")
    spans = defaultdict(lambda: [None, None])
    for row in filtered_rows:
        track_id, frame = str(row["track_id"]), int(row["frame_index"])
        low, high = spans[track_id]
        spans[track_id] = [frame if low is None else min(low, frame),
                           frame if high is None else max(high, frame)]
    link_rows = []
    both_inside_ids = []
    any_inside_ids = []
    link_interval_ids = []
    for link in report["links"]:
        source, target = str(link["from_track_id"]), str(link["to_track_id"])
        source_span, target_span = spans[source], spans[target]
        source_inside = source_span[0] is not None and source_span[1] >= START and source_span[0] <= END
        target_inside = target_span[0] is not None and target_span[1] >= START and target_span[0] <= END
        endpoints_both_inside = source_inside and target_inside
        if endpoints_both_inside:
            both_inside_ids.append([source, target])
        if source_inside or target_inside:
            any_inside_ids.append([source, target])
        source_end = source_span[1]
        target_start = target_span[0]
        connection_inside = source_end is not None and target_start is not None and max(source_end, target_start) >= START and min(source_end, target_start) <= END
        if connection_inside:
            link_interval_ids.append([source, target])
        link_rows.append({"from_track_id": source, "to_track_id": target,
                          "source_span": source_span, "target_span": target_span,
                          "both_track_fragments_intersect_evaluation_range": endpoints_both_inside,
                          "either_fragment_intersects_evaluation_range": source_inside or target_inside,
                          "connection_interval_intersects_evaluation_range": connection_inside})
    write_json(output_dir / "merge_links_in_evaluation_range.json", {
        "range_inclusive": [START, END], "accepted_link_count": len(report["links"]),
        "links": link_rows,
        "count_both_fragments_intersecting_range": len(both_inside_ids),
        "track_id_pairs_both_fragments_intersecting_range": both_inside_ids,
        "count_either_fragment_intersecting_range": len(any_inside_ids),
        "track_id_pairs_either_fragment_intersecting_range": any_inside_ids,
        "count_connection_interval_intersecting_range": len(link_interval_ids),
        "track_id_pairs_connection_interval_intersecting_range": link_interval_ids,
    }, common_meta | {"input_path": report_path.relative_to(ROOT).as_posix(),
                      "input_sha256": sha256(report_path),
                      "definition": "Reports endpoint-fragment span and link interval separately to make 'link spans the evaluation range' auditable."})
    print(json.dumps({"output_dir": output_dir.relative_to(ROOT).as_posix(),
                      "geometry_summary": geometry_summary,
                      "pedestrian_nearby_low_iou": pedestrian_nearby,
                      "crops": crop_meta,
                      "merge_links": {"both_fragments": both_inside_ids,
                                      "either_fragment": any_inside_ids,
                                      "connection_interval": link_interval_ids}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
