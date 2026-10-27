"""Conservatively join track fragments separated by short detection gaps."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from .paths import resolve_project_path


def _time(row: dict[str, str]) -> float:
    return float(row["timestamp_seconds"])


def _point(row: dict[str, str]) -> tuple[float, float]:
    return float(row["foot_x"]), float(row["foot_y"])


def _velocity(
    rows: list[dict[str, str]], *, from_end: bool, observations: int = 6
) -> tuple[float, float] | None:
    sample = rows[-observations:] if from_end else rows[:observations]
    if len(sample) < 2:
        return None
    dt = _time(sample[-1]) - _time(sample[0])
    if dt <= 0:
        return None
    x1, y1 = _point(sample[0])
    x2, y2 = _point(sample[-1])
    return (x2 - x1) / dt, (y2 - y1) / dt


def _size_ratio(first: dict[str, str], second: dict[str, str]) -> float:
    dimensions = (
        float(first["x2"]) - float(first["x1"]),
        float(first["y2"]) - float(first["y1"]),
        float(second["x2"]) - float(second["x1"]),
        float(second["y2"]) - float(second["y1"]),
    )
    if min(dimensions) <= 0:
        return math.inf
    width1, height1, width2, height2 = dimensions
    return max(width1 / width2, width2 / width1, height1 / height2, height2 / height1)


def continuation_score(
    first: list[dict[str, str]],
    second: list[dict[str, str]],
    *,
    maximum_gap_seconds: float,
    maximum_prediction_error_pixels: float,
    maximum_direction_change_degrees: float,
    maximum_speed_ratio: float,
    maximum_size_ratio: float,
    maximum_overlap_seconds: float = 0.75,
    maximum_duplicate_distance_pixels: float = 40.0,
) -> dict[str, float] | None:
    """Return diagnostics when two fragments satisfy every continuation gate."""
    if first[0]["object_class"] != second[0]["object_class"]:
        return None
    gap = _time(second[0]) - _time(first[-1])
    if _time(second[0]) <= _time(first[0]) or _time(second[-1]) <= _time(first[-1]):
        return None
    if gap < 0:
        overlap = -gap
        if overlap > maximum_overlap_seconds:
            return None
        first_by_frame = {int(row["frame_index"]): row for row in first}
        second_by_frame = {int(row["frame_index"]): row for row in second}
        shared = sorted(first_by_frame.keys() & second_by_frame.keys())
        if len(shared) < 2:
            return None
        distances = [
            math.dist(_point(first_by_frame[frame]), _point(second_by_frame[frame]))
            for frame in shared
        ]
        median_distance = statistics.median(distances)
        size_ratio = statistics.median(
            _size_ratio(first_by_frame[frame], second_by_frame[frame])
            for frame in shared
        )
        if (
            median_distance > maximum_duplicate_distance_pixels
            or size_ratio > maximum_size_ratio
        ):
            return None
        return {
            "gap_seconds": round(gap, 6),
            "overlap_seconds": round(overlap, 6),
            "shared_frames": len(shared),
            "duplicate_distance_pixels": round(median_distance, 3),
            "size_ratio": round(size_ratio, 3),
            "score": median_distance / maximum_duplicate_distance_pixels
            + (size_ratio - 1) / (maximum_size_ratio - 1),
        }
    if gap == 0 or gap > maximum_gap_seconds:
        return None
    first_velocity = _velocity(first, from_end=True)
    second_velocity = _velocity(second, from_end=False)
    if first_velocity is None or second_velocity is None:
        return None
    first_speed = math.hypot(*first_velocity)
    second_speed = math.hypot(*second_velocity)
    if min(first_speed, second_speed) < 1e-6:
        return None
    cosine = max(
        -1.0,
        min(
            1.0,
            (
                first_velocity[0] * second_velocity[0]
                + first_velocity[1] * second_velocity[1]
            )
            / (first_speed * second_speed),
        ),
    )
    direction_change = math.degrees(math.acos(cosine))
    speed_ratio = max(first_speed, second_speed) / min(first_speed, second_speed)
    end_x, end_y = _point(first[-1])
    start_x, start_y = _point(second[0])
    prediction_error = math.hypot(
        start_x - (end_x + first_velocity[0] * gap),
        start_y - (end_y + first_velocity[1] * gap),
    )
    size_ratio = _size_ratio(first[-1], second[0])
    if (
        prediction_error > maximum_prediction_error_pixels
        or direction_change > maximum_direction_change_degrees
        or speed_ratio > maximum_speed_ratio
        or size_ratio > maximum_size_ratio
    ):
        return None
    return {
        "gap_seconds": round(gap, 6),
        "prediction_error_pixels": round(prediction_error, 3),
        "direction_change_degrees": round(direction_change, 3),
        "speed_ratio": round(speed_ratio, 3),
        "size_ratio": round(size_ratio, 3),
        "score": prediction_error / maximum_prediction_error_pixels
        + direction_change / maximum_direction_change_degrees
        + (speed_ratio - 1) / (maximum_speed_ratio - 1)
        + (size_ratio - 1) / (maximum_size_ratio - 1),
    }


def merge_fragments(
    rows: list[dict[str, str]], **thresholds: float
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    tracks: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        tracks[int(row["track_id"])].append(row)
    for track_rows in tracks.values():
        track_rows.sort(key=_time)

    candidates = []
    ids = sorted(tracks)
    for first_id in ids:
        for second_id in ids:
            if first_id == second_id:
                continue
            diagnostics = continuation_score(
                tracks[first_id], tracks[second_id], **thresholds
            )
            if diagnostics is not None:
                candidates.append((float(diagnostics["score"]), first_id, second_id, diagnostics))

    predecessor: dict[int, int] = {}
    successor: dict[int, int] = {}
    accepted = []
    for _, first_id, second_id, diagnostics in sorted(candidates):
        if first_id in successor or second_id in predecessor:
            continue
        successor[first_id] = second_id
        predecessor[second_id] = first_id
        accepted.append({
            "from_track_id": first_id,
            "to_track_id": second_id,
            **diagnostics,
        })

    merged_id = {}
    for track_id in ids:
        root = track_id
        while root in predecessor:
            root = predecessor[root]
        merged_id[track_id] = root

    output_by_frame_and_track: dict[tuple[int, int], dict[str, str]] = {}
    for row in rows:
        updated = dict(row)
        original_id = int(row["track_id"])
        updated["original_track_id"] = str(original_id)
        updated["track_id"] = str(merged_id[original_id])
        key = (int(updated["frame_index"]), int(updated["track_id"]))
        existing = output_by_frame_and_track.get(key)
        if existing is None or float(updated.get("confidence", 0)) > float(
            existing.get("confidence", 0)
        ):
            output_by_frame_and_track[key] = updated
    output = list(output_by_frame_and_track.values())
    output.sort(key=lambda row: (int(row["frame_index"]), int(row["track_id"])))
    return output, accepted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--maximum-gap-seconds", type=float, default=0.75)
    parser.add_argument("--maximum-prediction-error-pixels", type=float, default=70.0)
    parser.add_argument("--maximum-direction-change-degrees", type=float, default=35.0)
    parser.add_argument("--maximum-speed-ratio", type=float, default=2.0)
    parser.add_argument("--maximum-size-ratio", type=float, default=2.0)
    parser.add_argument("--maximum-overlap-seconds", type=float, default=0.75)
    parser.add_argument("--maximum-duplicate-distance-pixels", type=float, default=40.0)
    args = parser.parse_args()
    source = resolve_project_path(args.tracks)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    thresholds = {
        key: value for key, value in vars(args).items()
        if key.startswith("maximum_")
    }
    merged, links = merge_fragments(rows, **thresholds)
    output = resolve_project_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) + ["original_track_id"]
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)
    input_ids = {row["track_id"] for row in rows}
    output_ids = {row["track_id"] for row in merged}
    report = {
        "source": str(source),
        "output": str(output),
        "input_tracks": len(input_ids),
        "merged_tracks": len(output_ids),
        "accepted_links": len(links),
        "thresholds": thresholds,
        "links": links,
    }
    resolve_project_path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in (
        "input_tracks", "merged_tracks", "accepted_links"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
