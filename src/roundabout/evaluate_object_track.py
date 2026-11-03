"""Evaluate frozen object-track GT against same-run trajectory stages."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import yaml
from scipy.optimize import linear_sum_assignment
from .third_party.hota import HOTA
from .environment import opencv_environment


ASSOCIATION_FIELDS = [
    "schema_version", "gt_dataset_id", "evaluation_run_id", "video_id", "stage",
    "source_artifact_sha256", "gt_object_id", "auto_track_id",
    "match_start_frame_index", "match_end_frame_index",
    "match_start_timestamp_seconds", "match_end_timestamp_seconds",
    "association_status", "coverage_status", "fragmentation_status",
    "identity_status", "class_match", "matching_method", "match_score",
    "reviewer", "review_status", "review_timestamp_utc", "notes",
]
AUDIT_FIELDS = [
    "schema_version", "gt_dataset_id", "evaluation_run_id", "video_id", "stage",
    "source_artifact_sha256", "auto_track_id", "first_frame_index",
    "last_frame_index", "first_timestamp_seconds", "last_timestamp_seconds",
    "object_class_auto", "audit_status", "false_positive_reason",
    "related_gt_object_ids", "reviewer", "review_status",
    "review_timestamp_utc", "notes",
]
STAGES = ("raw_tracker", "filtered", "merged")


class EvaluationError(ValueError):
    """Raised when inputs do not match the approved evaluation contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_frozen_hash(path: Path, expected: str) -> None:
    if sha256(path) != expected:
        raise EvaluationError(f"Frozen GT SHA-256 mismatch: {path}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def box_iou(first: Iterable[float], second: Iterable[float]) -> float:
    ax1, ay1, ax2, ay2 = map(float, first)
    bx1, by1, bx2, by2 = map(float, second)
    width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = width * height
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def match_frame(
    gt_boxes: list[dict[str, object]],
    auto_boxes: list[dict[str, object]],
    threshold: float,
) -> list[tuple[int, int, float]]:
    """Return one-to-one class-agnostic IoU matches for a single frame."""
    if not gt_boxes or not auto_boxes:
        return []
    similarities = np.array([
        [box_iou(g["box"], a["box"]) for a in auto_boxes]
        for g in gt_boxes
    ], dtype=float)
    rows, cols = linear_sum_assignment(1.0 - similarities)
    return [
        (int(row), int(col), float(similarities[row, col]))
        for row, col in zip(rows, cols)
        if similarities[row, col] >= threshold
    ]


def trajectory_labels(coverage: float) -> str:
    if coverage >= 0.8:
        return "MT"
    if coverage < 0.2:
        return "ML"
    return "PT"


def coverage_status(match_count: int, best_single_id_count: int, anchors: int) -> str:
    if anchors and best_single_id_count / anchors >= 0.8:
        return "complete"
    return "partial" if match_count else "missed"


def fragmentation_count(auto_track_ids: Iterable[str]) -> int:
    return max(0, len(set(auto_track_ids)) - 1)


def count_id_switches(ordered_matches: Iterable[tuple[str, str]]) -> int:
    """Count changes in assigned auto ID within each GT identity sequence."""
    last_by_gt: dict[str, str] = {}
    switches = 0
    for gt_id, auto_id in ordered_matches:
        previous = last_by_gt.get(gt_id)
        if previous is not None and previous != auto_id:
            switches += 1
        last_by_gt[gt_id] = auto_id
    return switches


def maximum_missing_anchors(anchor_frames: list[int], matched_frames: set[int]) -> int:
    longest = current = 0
    for frame in anchor_frames:
        if frame in matched_frames:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def class_compatible(gt_class: str, auto_class: str) -> bool:
    compatible = {
        "person": {"person"},
        "car": {"car", "bus", "truck"},
        "motorcycle": {"motorcycle"},
    }
    return auto_class in compatible.get(gt_class, set())


def select_complete_frames(
    grid_frames: list[int],
    eligible_objects_by_frame: dict[int, set[str]],
    observed_objects_by_frame: dict[int, set[str]],
) -> list[int]:
    return [
        frame for frame in grid_frames
        if eligible_objects_by_frame.get(frame)
        and eligible_objects_by_frame[frame]
        <= observed_objects_by_frame.get(frame, set())
    ]


def _load_inputs(config_path: Path) -> dict[str, object]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise EvaluationError("Evaluation config must be a YAML mapping")
    return config


def _validate_inputs(config: dict[str, object], root: Path) -> tuple[
    dict[str, object], dict[str, list[dict[str, str]]], dict[str, Path]
]:
    gt_config = config["ground_truth"]
    run_config = config["automatic_run"]
    gt_dir = root / str(gt_config["directory"])
    skip_path = gt_dir / str(gt_config["skip_file"])
    read_csv(skip_path)
    manifest_path = root / str(config["evidence"]["ground_truth_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gt_files: dict[str, Path] = {}
    gt_rows: dict[str, list[dict[str, str]]] = {}
    for key, name in gt_config["frozen_files"].items():
        path = gt_dir / str(name)
        expected = manifest["frozen_files"][key]["sha256"]
        verify_frozen_hash(path, expected)
        gt_files[key] = path
        gt_rows[key] = read_csv(path)
    lineage_path = root / str(config["evidence"]["execution_lineage"])
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    if lineage["git"]["worktree_clean"] is not True:
        raise EvaluationError("Automatic run was not recorded with a clean worktree")
    if not str(lineage["git"]["commit"]).startswith("e9d7c75"):
        raise EvaluationError("Automatic run commit is not the approved e9d7c75 commit")
    if lineage["evaluation_run_id"] != run_config["evaluation_run_id"]:
        raise EvaluationError("Evaluation run ID mismatch")
    run_dir = root / str(run_config["directory"])
    stages: dict[str, Path] = {}
    for stage, relative in run_config["stages"].items():
        path = run_dir / str(relative)
        artifact = lineage["artifacts"][stage]
        if artifact.get("status") != "complete" or sha256(path) != artifact.get(
            "tracks_csv_sha256", artifact.get("artifact_sha256")
        ):
            raise EvaluationError(f"Artifact lineage mismatch: {stage}")
        if stage == "raw_tracker":
            summary_path = path.parent / "summary.json"
            summary_sha = artifact.get("summary_json_sha256")
        elif stage == "filtered":
            summary_path = path.parent / "filter_summary.json"
            summary_sha = artifact.get("summary_sha256")
        else:
            summary_path = path.parent / "continuation_report.json"
            summary_sha = artifact.get("report_sha256")
        if not summary_sha or sha256(summary_path) != summary_sha:
            raise EvaluationError(f"Stage summary/report lineage mismatch: {stage}")
        if stage in ("filtered", "merged"):
            for mask in artifact["mask_inputs"].values():
                mask_path = root / str(mask["path"])
                if sha256(mask_path) != mask["sha256"]:
                    raise EvaluationError(f"Filter mask lineage mismatch: {mask_path}")
        stages[stage] = path
    return manifest, gt_rows, stages


def _track_rows(path: Path, start: int, end: int) -> list[dict[str, object]]:
    rows = []
    for row in read_csv(path):
        frame = int(row["frame_index"])
        if start <= frame <= end:
            rows.append({
                **row,
                "frame_index": frame,
                "track_id": str(row["track_id"]),
                "object_class": row["object_class"],
                "box": tuple(float(row[key]) for key in ("x1", "y1", "x2", "y2")),
            })
    return rows


def _hota_metrics(
    frames: list[int],
    gt_by_frame: dict[int, list[dict[str, object]]],
    auto_by_frame: dict[int, list[dict[str, object]]],
) -> dict[str, dict[str, float]]:
    gt_ids = sorted({str(row["gt_object_id"]) for f in frames for row in gt_by_frame[f]})
    auto_ids = sorted({str(row["track_id"]) for f in frames for row in auto_by_frame[f]})
    gt_index = {value: index for index, value in enumerate(gt_ids)}
    auto_index = {value: index for index, value in enumerate(auto_ids)}
    data = {
        "num_timesteps": len(frames), "num_gt_dets": sum(len(gt_by_frame[f]) for f in frames),
        "num_tracker_dets": sum(len(auto_by_frame[f]) for f in frames),
        "num_gt_ids": len(gt_ids), "num_tracker_ids": len(auto_ids),
        "gt_ids": [], "tracker_ids": [], "similarity_scores": [],
    }
    for frame in frames:
        gt_rows, auto_rows = gt_by_frame[frame], auto_by_frame[frame]
        data["gt_ids"].append(np.array(
            [gt_index[str(row["gt_object_id"])] for row in gt_rows], dtype=int
        ))
        data["tracker_ids"].append(np.array(
            [auto_index[str(row["track_id"])] for row in auto_rows], dtype=int
        ))
        data["similarity_scores"].append(np.array([
            [box_iou(g["box"], a["box"]) for a in auto_rows] for g in gt_rows
        ], dtype=float).reshape(len(gt_rows), len(auto_rows)))
    result = HOTA().eval_sequence(data)
    labels = np.asarray(HOTA().array_labels)
    alpha_index = int(np.argmin(np.abs(labels - 0.5)))
    return {
        name: {
            "alpha_mean": float(np.mean(result[name])),
            "alpha_0_5": float(result[name][alpha_index]),
        }
        for name in ("HOTA", "DetA", "AssA", "LocA")
    }


def _frame_metrics(
    frames: list[int],
    gt_by_frame: dict[int, list[dict[str, object]]],
    auto_by_frame: dict[int, list[dict[str, object]]],
    threshold: float,
) -> dict[str, object]:
    tp = fp = fn = id_switches = 0
    pair_counts: Counter[tuple[str, str]] = Counter()
    class_matrix: Counter[tuple[str, str]] = Counter()
    ordered_identity_matches: list[tuple[str, str]] = []
    for frame in frames:
        gt_rows, auto_rows = gt_by_frame[frame], auto_by_frame[frame]
        matches = match_frame(gt_rows, auto_rows, threshold)
        tp += len(matches)
        fn += len(gt_rows) - len(matches)
        fp += len(auto_rows) - len(matches)
        for gi, ai, iou in matches:
            gt_row, auto_row = gt_rows[gi], auto_rows[ai]
            gt_id, auto_id = str(gt_row["gt_object_id"]), str(auto_row["track_id"])
            pair_counts[(gt_id, auto_id)] += 1
            ordered_identity_matches.append((gt_id, auto_id))
            class_matrix[(str(gt_row["object_class"]), str(auto_row["object_class"]))] += 1
    id_switches = count_id_switches(ordered_identity_matches)
    gt_dets = tp + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    mota = 1.0 - (fn + fp + id_switches) / gt_dets if gt_dets else 0.0
    gt_totals: Counter[str] = Counter()
    auto_totals: Counter[str] = Counter()
    for (gt_id, auto_id), count in pair_counts.items():
        gt_totals[gt_id] += count
        auto_totals[auto_id] += count
    idtp = 0
    if gt_totals and auto_totals:
        g_ids, a_ids = sorted(gt_totals), sorted(auto_totals)
        matrix = np.zeros((len(g_ids), len(a_ids)), dtype=int)
        gi = {item: i for i, item in enumerate(g_ids)}
        ai = {item: i for i, item in enumerate(a_ids)}
        for (g, a), count in pair_counts.items():
            matrix[gi[g], ai[a]] = count
        rows, cols = linear_sum_assignment(-matrix)
        idtp = int(matrix[rows, cols].sum())
    idfn, idfp = gt_dets - idtp, (tp + fp) - idtp
    idf1 = 2 * idtp / (2 * idtp + idfn + idfp) if 2 * idtp + idfn + idfp else 0.0
    return {
        "gt_detections": gt_dets, "auto_detections": tp + fp, "tp": tp,
        "fp": fp, "fn": fn, "precision_pre_audit": precision,
        "mota": mota, "idf1": idf1, "idsw": id_switches,
        "idtp": idtp,
        "class_confusion_matrix": {
            gt_class: dict(Counter({auto_class: count for (g, auto_class), count
                                    in class_matrix.items() if g == gt_class}))
            for gt_class in sorted({g for g, _ in class_matrix})
        },
    }


def _object_metrics(
    observations: list[dict[str, str]],
    auto_by_frame: dict[int, list[dict[str, object]]],
    threshold: float,
) -> tuple[list[dict[str, object]], dict[str, object], list[dict[str, object]]]:
    gt_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in observations:
        frame = int(row["frame_index"])
        gt_by_frame[frame].append({
            **row, "frame_index": frame, "box": tuple(float(row[key]) for key in
                ("x1", "y1", "x2", "y2")),
        })
    matched: dict[str, list[tuple[int, str, float, dict[str, object]]]] = defaultdict(list)
    for frame, gt_rows in gt_by_frame.items():
        auto_rows = auto_by_frame.get(frame, [])
        for gi, ai, iou in match_frame(gt_rows, auto_rows, threshold):
            gt, auto = gt_rows[gi], auto_rows[ai]
            matched[str(gt["gt_object_id"])].append(
                (frame, str(auto["track_id"]), iou, auto)
            )
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in observations:
        grouped[row["gt_object_id"]].append(row)
    per_object = []
    association_links = []
    by_class: dict[str, list[dict[str, object]]] = defaultdict(list)
    for object_id, anchors in sorted(grouped.items()):
        anchors.sort(key=lambda row: int(row["frame_index"]))
        hits = matched.get(object_id, [])
        per_id = Counter(auto_id for _, auto_id, _, _ in hits)
        anchor_frames = [int(row["frame_index"]) for row in anchors]
        hit_frames = {frame for frame, _, _, _ in hits}
        ratio = len(hits) / len(anchors) if anchors else 0.0
        gt_class = anchors[0]["object_class"]
        status = coverage_status(len(hits), max(per_id.values(), default=0), len(anchors))
        result = {
            "gt_object_id": object_id,
            "object_class": gt_class,
            "anchors": len(anchors),
            "matched_anchors": len(hits),
            "coverage": ratio,
            "mt_pt_ml": trajectory_labels(ratio),
            "coverage_status": status,
            "auto_track_ids": len(per_id),
            "fragmentation_count": fragmentation_count(per_id),
            "maximum_consecutive_missing_anchors": maximum_missing_anchors(
                anchor_frames, hit_frames
            ),
            "class_match_count": sum(
                class_compatible(gt_class, auto["object_class"])
                for _, _, _, auto in hits
            ),
            "class_match_rate": (
                sum(class_compatible(gt_class, auto["object_class"])
                    for _, _, _, auto in hits) / len(hits) if hits else None
            ),
            "matched": bool(hits),
            "_matches": hits,
        }
        per_object.append(result)
        by_class[gt_class].append(result)
        if hits:
            for auto_id in sorted(per_id):
                link = [entry for entry in hits if entry[1] == auto_id]
                association_links.append({
                    "gt_object_id": object_id, "object_class": gt_class,
                    "auto_track_id": auto_id,
                    "first_frame": min(row[0] for row in link),
                    "last_frame": max(row[0] for row in link),
                    "match_score": float(np.mean([row[2] for row in link])),
                    "class_match": all(
                        class_compatible(gt_class, row[3]["object_class"])
                        for row in link
                    ),
                })
    def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
        coverages = [float(row["coverage"]) for row in rows]
        total = sum(int(row["anchors"]) for row in rows)
        hits = sum(int(row["matched_anchors"]) for row in rows)
        return {
            "objects": len(rows), "anchors": total, "matched_anchors": hits,
            "anchor_recall": hits / total if total else 0.0,
            "object_capture_rate": sum(bool(row["matched"]) for row in rows) / len(rows)
            if rows else 0.0,
            "coverage_mean": float(np.mean(coverages)) if coverages else 0.0,
            "coverage_median": float(np.median(coverages)) if coverages else 0.0,
            "coverage_p10": float(np.quantile(coverages, 0.1)) if coverages else 0.0,
            "mt_count": sum(row["mt_pt_ml"] == "MT" for row in rows),
            "pt_count": sum(row["mt_pt_ml"] == "PT" for row in rows),
            "ml_count": sum(row["mt_pt_ml"] == "ML" for row in rows),
            "complete_count": sum(row["coverage_status"] == "complete" for row in rows),
            "partial_count": sum(row["coverage_status"] == "partial" for row in rows),
            "missed_count": sum(row["coverage_status"] == "missed" for row in rows),
        }
    return per_object, {
        "overall": summarize(per_object),
        "by_class": {name: summarize(rows) for name, rows in sorted(by_class.items())},
    }, association_links


def evaluate_stage(
    observations: list[dict[str, str]],
    auto_rows: list[dict[str, object]],
    complete_frames: list[int],
    thresholds: list[float],
) -> dict[str, object]:
    auto_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in auto_rows:
        auto_by_frame[int(row["frame_index"])].append(row)
    gt_by_frame: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in observations:
        gt_by_frame[int(row["frame_index"])].append({
            **row, "box": tuple(float(row[key]) for key in ("x1", "y1", "x2", "y2")),
        })
    output: dict[str, object] = {"thresholds": {}, "per_object": {}, "associations": {}}
    for threshold in thresholds:
        key = f"iou_{threshold:.1f}"
        objects, object_summary, links = _object_metrics(observations, auto_by_frame, threshold)
        frames = _frame_metrics(
            complete_frames, gt_by_frame, auto_by_frame, threshold
        ) if complete_frames else {}
        frames["hota"] = _hota_metrics(complete_frames, gt_by_frame, auto_by_frame)
        output["thresholds"][key] = {"objects": object_summary, "frames": frames}
        output["per_object"][key] = objects
        output["associations"][key] = links
    output["auto_by_frame"] = auto_by_frame
    return output


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(config_path: Path, root: Path) -> dict[str, object]:
    config = _load_inputs(config_path)
    manifest, gt, stage_paths = _validate_inputs(config, root)
    gt_config = config["ground_truth"]
    run_config = config["automatic_run"]
    skip_rows = read_csv(
        root / str(gt_config["directory"]) / str(gt_config["skip_file"])
    )
    start, end = int(gt_config["start_frame_index"]), int(gt_config["end_frame_index"])
    observations = [
        row for row in gt["observations"]
        if start <= int(row["frame_index"]) <= end
        and row["in_scope"].lower() == "true"
    ]
    visibility = gt["visibility_intervals"]
    eligible_by_frame: dict[int, set[str]] = defaultdict(set)
    for frame in range(start, end + 1, int(gt_config["anchor_frame_step"])):
        for row in visibility:
            if (
                int(row["start_frame_index"]) <= frame <= int(row["end_frame_index"])
                and row["in_scope"].lower() == "true"
                and row["denominator_eligible"].lower() == "true"
            ):
                eligible_by_frame[frame].add(row["gt_object_id"])
    observed_by_frame: dict[int, set[str]] = defaultdict(set)
    for row in observations:
        observed_by_frame[int(row["frame_index"])].add(row["gt_object_id"])
    grid = list(range(start, end + 1, int(gt_config["anchor_frame_step"])))
    complete_frames = select_complete_frames(grid, eligible_by_frame, observed_by_frame)
    frame_step = int(run_config["frame_step"])
    sampled_frames = set(range(0, int(manifest["video"]["source_frame_count"]), frame_step))
    missing_anchor_frames = sorted(
        set(int(row["frame_index"]) for row in observations) - sampled_frames
    )
    if missing_anchor_frames:
        raise EvaluationError(f"GT anchors absent from automatic frame step: {missing_anchor_frames}")
    run_id = str(run_config["evaluation_run_id"])
    video_id = str(gt_config["video_id"])
    output_dir = root / "outputs/evaluation" / str(config["evaluation_run_id"])
    if output_dir.exists() and any(output_dir.iterdir()):
        raise EvaluationError(f"Evaluation output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    thresholds = [float(config["matching"]["iou_thresholds"][key])
                  for key in ("official", "sensitivity")]
    metrics: dict[str, object] = {
        "schema_version": "object_track_metrics_v1",
        "evaluation_run_id": str(config["evaluation_run_id"]),
        "automatic_evaluation_run_id": run_id,
        "video_id": video_id,
        "complete_frames": complete_frames,
        "complete_frame_count": len(complete_frames),
        "excluded_incomplete_grid_frames": sorted(set(grid) - set(complete_frames)),
        "excluded_reviewed_skips": skip_rows,
        "stages": {},
    }
    per_object_csv = []
    associations_csv = []
    audit_csv = []
    stage_data: dict[str, dict[str, object]] = {}
    manifest_gt = manifest
    auto_fps = float(manifest_gt["video"]["source_fps"])
    for stage in STAGES:
        path = stage_paths[stage]
        rows = _track_rows(path, start, end)
        data = evaluate_stage(observations, rows, complete_frames, thresholds)
        stage_data[stage] = data
        metrics["stages"][stage] = data["thresholds"]
        artifact_hash = sha256(path)
        for threshold in thresholds:
            threshold_key = f"iou_{threshold:.1f}"
            for obj in data["per_object"][threshold_key]:
                per_object_csv.append({
                    "evaluation_run_id": run_id, "stage": stage,
                    "iou_threshold": threshold, **{key: value for key, value in obj.items()
                        if not key.startswith("_")},
                    "maximum_consecutive_missing_seconds": (
                        obj["maximum_consecutive_missing_anchors"] * 30 / auto_fps
                    ),
                })
            if threshold == thresholds[0]:
                links = data["associations"][threshold_key]
                gt_ids = {row["gt_object_id"] for row in observations}
                objects_by_id = {row["gt_object_id"]: row for row in
                    data["per_object"][threshold_key]}
                matched_gt_by_auto: dict[str, set[str]] = defaultdict(set)
                for link in links:
                    matched_gt_by_auto[link["auto_track_id"]].add(link["gt_object_id"])
                for object_id in sorted(gt_ids):
                    obj = objects_by_id[object_id]
                    object_links = [link for link in links if link["gt_object_id"] == object_id]
                    if not object_links:
                        object_links = [{"auto_track_id": "", "first_frame": "",
                                         "last_frame": "", "match_score": ""}]
                    for link in object_links:
                        associations_csv.append({
                            "schema_version": "object_track_gt_v1",
                            "gt_dataset_id": manifest["gt_dataset_id"],
                            "evaluation_run_id": run_id, "video_id": video_id,
                            "stage": stage, "source_artifact_sha256": artifact_hash,
                            "gt_object_id": object_id,
                            "auto_track_id": link["auto_track_id"],
                            "match_start_frame_index": link["first_frame"],
                            "match_end_frame_index": link["last_frame"],
                            "match_start_timestamp_seconds": (
                                float(link["first_frame"]) / auto_fps if link["first_frame"] != "" else ""
                            ),
                            "match_end_timestamp_seconds": (
                                float(link["last_frame"]) / auto_fps if link["last_frame"] != "" else ""
                            ),
                            "association_status": "matched" if link["auto_track_id"] else "missed",
                            "coverage_status": obj["coverage_status"],
                            "fragmentation_status": "fragmented" if obj["fragmentation_count"] else
                                ("unfragmented" if link["auto_track_id"] else "not_applicable"),
                            "identity_status": "id_switch" if len(
                                matched_gt_by_auto.get(link["auto_track_id"], set())
                            ) > 1 else ("stable" if link["auto_track_id"] else "not_applicable"),
                            "class_match": (
                                ("match" if link["class_match"] else "mismatch")
                                if link["auto_track_id"] else "not_applicable"
                            ),
                            "matching_method": "automatic", "match_score": link["match_score"],
                            "reviewer": "", "review_status": "draft",
                            "review_timestamp_utc": "", "notes": "IoU >= 0.5; draft automatic candidate",
                        })
        all_ids: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            all_ids[str(row["track_id"])].append(row)
        linked_ids = {link["auto_track_id"] for link in data["associations"][f"iou_{thresholds[0]:.1f}"]}
        for auto_id, track_rows in all_ids.items():
            if auto_id not in linked_ids:
                audit_csv.append({
                    "schema_version": "object_track_gt_v1", "gt_dataset_id": manifest["gt_dataset_id"],
                    "evaluation_run_id": run_id, "video_id": video_id, "stage": stage,
                    "source_artifact_sha256": artifact_hash, "auto_track_id": auto_id,
                    "first_frame_index": min(row["frame_index"] for row in track_rows),
                    "last_frame_index": max(row["frame_index"] for row in track_rows),
                    "first_timestamp_seconds": min(row["frame_index"] for row in track_rows) / auto_fps,
                    "last_timestamp_seconds": max(row["frame_index"] for row in track_rows) / auto_fps,
                    "object_class_auto": track_rows[0]["object_class"],
                    "audit_status": "uncertain", "false_positive_reason": "",
                    "related_gt_object_ids": "", "reviewer": "", "review_status": "uncertain",
                    "review_timestamp_utc": "", "notes": "No automatic IoU>=0.5 association; review required",
                })
    official_key = f"iou_{thresholds[0]:.1f}"
    matched_gt_by_stage = {
        stage: {
            obj["gt_object_id"] for obj in stage_data[stage]["per_object"][official_key]
            if obj["matched"]
        }
        for stage in STAGES
    }
    raw_detected = matched_gt_by_stage["raw_tracker"]
    raw_links_by_gt: dict[str, set[str]] = defaultdict(set)
    for link in stage_data["raw_tracker"]["associations"][official_key]:
        raw_links_by_gt[link["gt_object_id"]].add(link["auto_track_id"])
    filter_summary = json.loads(
        (stage_paths["filtered"].parent / "filter_summary.json").read_text(
            encoding="utf-8"
        )
    )
    filter_track_metrics = filter_summary.get("track_metrics", {})
    stage_survival = []
    for stage in STAGES:
        survived = raw_detected & matched_gt_by_stage[stage]
        lost_from_raw = sorted(raw_detected - matched_gt_by_stage[stage])
        removal_reasons = {}
        if stage == "filtered":
            for object_id in lost_from_raw:
                removal_reasons[object_id] = sorted({
                    str(filter_track_metrics.get(auto_id, {}).get("decision", "not_recorded"))
                    for auto_id in raw_links_by_gt[object_id]
                })
        stage_survival.append({
            "evaluation_run_id": run_id,
            "stage": stage,
            "gt_objects_matched_in_stage": len(matched_gt_by_stage[stage]),
            "raw_matched_gt_denominator": len(raw_detected),
            "raw_to_stage_survival_rate": len(survived) / len(raw_detected)
            if raw_detected else 0.0,
            "gt_objects_surviving_from_raw": len(survived),
            "gt_objects_lost_from_raw": ";".join(lost_from_raw),
            "filter_removal_reasons": json.dumps(
                removal_reasons, ensure_ascii=False, sort_keys=True
            ),
        })
    merged_links = stage_data["merged"]["associations"][official_key]
    gt_by_merged_id: dict[str, set[str]] = defaultdict(set)
    for link in merged_links:
        gt_by_merged_id[link["auto_track_id"]].add(link["gt_object_id"])
    merge_collision_ids = sorted(
        track_id for track_id, gt_ids in gt_by_merged_id.items() if len(gt_ids) > 1
    )
    metrics["merge_diagnostics"] = {
        "potential_cross_gt_merged_ids": merge_collision_ids,
        "potential_cross_gt_merged_id_count": len(merge_collision_ids),
        "interpretation": "automatic review candidates; not adjudicated merge errors",
    }
    meta = {
        "environment": {"opencv": opencv_environment()},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "config_path": config_path.relative_to(root).as_posix(),
        "config_sha256": sha256(config_path),
        "automatic_run_id": run_id,
        "ground_truth_manifest_sha256": sha256(root / str(config["evidence"]["ground_truth_manifest"])),
        "reviewed_skips_path": (root / str(gt_config["directory"])
                                 / str(gt_config["skip_file"])).relative_to(root).as_posix(),
        "reviewed_skips_sha256": sha256(
            root / str(gt_config["directory"]) / str(gt_config["skip_file"])
        ),
        "source_artifacts": {stage: sha256(path) for stage, path in stage_paths.items()},
        "coordinate_system": "source_pixel", "unit": "px",
        "matching_method": "automatic", "review_status": "draft",
    }
    implementation_status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).splitlines()
    implementation_files = [
        config_path, root / "src/roundabout/evaluate_object_track.py",
        root / "configs/evaluation_object_track_v1.yaml", root / "pyproject.toml",
    ]
    for status_line in implementation_status:
        relative = status_line[3:].split(" -> ")[-1]
        candidate = root / relative
        if candidate.is_file() and candidate not in implementation_files:
            implementation_files.append(candidate)
    gt_dir = root / str(gt_config["directory"])
    evaluation_lineage = {
        "environment": meta["environment"],
        "evaluation_run_id": str(config["evaluation_run_id"]),
        "evaluation_implementation": {
            "git_commit": meta["git_commit"],
            "worktree_clean": not implementation_status,
            "status_porcelain": implementation_status,
            "file_sha256": {
                path.relative_to(root).as_posix(): sha256(path)
                for path in implementation_files
            },
        },
        "automatic_run": json.loads(
            (root / str(config["evidence"]["execution_lineage"])).read_text(
                encoding="utf-8"
            )
        ),
        "ground_truth": {
            "manifest_path": str(config["evidence"]["ground_truth_manifest"]),
            "manifest_sha256": meta["ground_truth_manifest_sha256"],
            "reviewed_skips_path": meta["reviewed_skips_path"],
            "reviewed_skips_sha256": meta["reviewed_skips_sha256"],
            "frozen_files": {
                key: {
                    "path": (gt_dir / str(name)).relative_to(root).as_posix(),
                    "sha256": sha256(gt_dir / str(name)),
                }
                for key, name in gt_config["frozen_files"].items()
            },
        },
        "evaluation_config_path": meta["config_path"],
        "evaluation_config_sha256": meta["config_sha256"],
    }
    files = {
        "metrics_summary.json": metrics,
        "per_object.csv": None,
        "gt_track_associations.csv": None,
        "auto_track_audit_candidates.csv": None,
        "stage_survival.csv": None,
        "run_lineage.json": evaluation_lineage,
    }
    for name, value in files.items():
        target = output_dir / name
        if value is not None:
            target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / f"{name}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    _write_csv(output_dir / "per_object.csv", [
        "evaluation_run_id", "stage", "iou_threshold", "gt_object_id", "object_class",
        "anchors", "matched_anchors", "coverage", "mt_pt_ml", "coverage_status",
        "auto_track_ids", "fragmentation_count", "maximum_consecutive_missing_anchors",
        "maximum_consecutive_missing_seconds", "class_match_count", "class_match_rate",
    ], per_object_csv)
    _write_csv(output_dir / "gt_track_associations.csv", ASSOCIATION_FIELDS, associations_csv)
    _write_csv(output_dir / "auto_track_audit_candidates.csv", AUDIT_FIELDS, audit_csv)
    _write_csv(output_dir / "stage_survival.csv", list(stage_survival[0]), stage_survival)
    for name in ("per_object.csv", "gt_track_associations.csv", "auto_track_audit_candidates.csv", "stage_survival.csv"):
        (output_dir / f"{name}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"output_dir": str(output_dir), "complete_frames": complete_frames}, indent=2))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/evaluation_object_track_v1.yaml")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    run(Path(args.config).resolve(), Path(args.root).resolve())


if __name__ == "__main__":
    main()
