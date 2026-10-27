"""Compute ROI exposure and provisional PET/TTC events from filtered tracks."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .paths import resolve_project_path


VEHICLES = {"bicycle", "motorcycle", "car", "bus", "truck", "tricycle"}


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        xi, yi = current
        xj, yj = previous
        if (yi > y) != (yj > y):
            boundary = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            if x < boundary:
                inside = not inside
        previous = current
    return inside


def transform_point(matrix: list[list[float]], x: float, y: float) -> tuple[float, float]:
    denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if abs(denominator) < 1e-12:
        raise ValueError("Homography maps point to infinity")
    return (
        (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
        (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator,
    )


def class_kind(object_class: str) -> str:
    if object_class == "person":
        return "pedestrian"
    if object_class in VEHICLES:
        return "vehicle"
    return "other"


def load_tracks(path: Path, matrix: list[list[float]]) -> dict[int, list[dict[str, object]]]:
    tracks: dict[int, list[dict[str, object]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            x, y = transform_point(matrix, float(row["foot_x"]), float(row["foot_y"]))
            tracks[int(row["track_id"])].append({
                "timestamp": float(row["timestamp_seconds"]),
                "frame_index": int(row["frame_index"]),
                "object_class": row["object_class"],
                "x": x,
                "y": y,
            })
    for rows in tracks.values():
        rows.sort(key=lambda item: float(item["timestamp"]))
    return tracks


def build_intervals(
    tracks: dict[int, list[dict[str, object]]],
    zones: list[dict[str, object]],
    maximum_gap_seconds: float,
) -> list[dict[str, object]]:
    intervals: list[dict[str, object]] = []
    for zone in zones:
        polygon = zone["polygon"]
        for track_id, rows in tracks.items():
            inside = [
                row for row in rows
                if point_in_polygon(float(row["x"]), float(row["y"]), polygon)
            ]
            groups: list[list[dict[str, object]]] = []
            for row in inside:
                if (
                    not groups
                    or float(row["timestamp"]) - float(groups[-1][-1]["timestamp"])
                    > maximum_gap_seconds
                ):
                    groups.append([row])
                else:
                    groups[-1].append(row)
            for group_index, group in enumerate(groups, start=1):
                classes = Counter(str(row["object_class"]) for row in group)
                object_class = classes.most_common(1)[0][0]
                intervals.append({
                    "roi_id": zone["id"],
                    "roi_name": zone.get("name", zone["id"]),
                    "roi_parent": zone.get("parent"),
                    "roi_side": zone.get("side"),
                    "track_id": track_id,
                    "visit_index": group_index,
                    "object_class": object_class,
                    "class_kind": class_kind(object_class),
                    "entry_seconds": float(group[0]["timestamp"]),
                    "exit_seconds": float(group[-1]["timestamp"]),
                    "entry_frame": int(group[0]["frame_index"]),
                    "exit_frame": int(group[-1]["frame_index"]),
                    "event_x": sum(float(row["x"]) for row in group) / len(group),
                    "event_y": sum(float(row["y"]) for row in group) / len(group),
                    "points": [
                        (float(row["x"]), float(row["y"])) for row in group
                    ],
                })
    return sorted(
        intervals,
        key=lambda row: (str(row["roi_id"]), float(row["entry_seconds"])),
    )


def summarize_rois(
    zones: list[dict[str, object]],
    intervals: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows = []
    for zone in zones:
        visits = [item for item in intervals if item["roi_id"] == zone["id"]]
        unique = {
            (item["track_id"], item["class_kind"], item["object_class"])
            for item in visits
        }
        rows.append({
            "roi_id": zone["id"],
            "roi_name": zone.get("name", zone["id"]),
            "roi_parent": zone.get("parent"),
            "roi_side": zone.get("side"),
            "unique_tracks": len({item[0] for item in unique}),
            "pedestrian_tracks": sum(item[1] == "pedestrian" for item in unique),
            "vehicle_tracks": sum(item[1] == "vehicle" for item in unique),
            "visit_count": len(visits),
        })
    return rows


def state_at(rows: list[dict[str, object]], timestamp: float) -> tuple[float, float, float, float] | None:
    if len(rows) < 2:
        return None
    index = min(
        range(len(rows)),
        key=lambda item: abs(float(rows[item]["timestamp"]) - timestamp),
    )
    if index == 0:
        first, second = rows[0], rows[1]
    else:
        first, second = rows[index - 1], rows[index]
    dt = float(second["timestamp"]) - float(first["timestamp"])
    if dt <= 0:
        return None
    vx = (float(second["x"]) - float(first["x"])) / dt
    vy = (float(second["y"]) - float(first["y"])) / dt
    return float(second["x"]), float(second["y"]), vx, vy


def ttc_for_pair(
    tracks: dict[int, list[dict[str, object]]],
    first: dict[str, object],
    second: dict[str, object],
) -> tuple[float | None, bool, float | None]:
    timestamp = float(second["entry_seconds"])
    first_state = state_at(tracks[int(first["track_id"])], timestamp)
    second_state = state_at(tracks[int(second["track_id"])], timestamp)
    if first_state is None or second_state is None:
        return None, False, None
    x1, y1, vx1, vy1 = first_state
    x2, y2, vx2, vy2 = second_state
    rx, ry = x2 - x1, y2 - y1
    rvx, rvy = vx2 - vx1, vy2 - vy1
    speed_squared = rvx * rvx + rvy * rvy
    closing = rx * rvx + ry * rvy
    if speed_squared < 1e-6 or closing >= 0:
        return None, False, math.hypot(rx, ry)
    return -closing / speed_squared, True, math.hypot(rx, ry)


def crossing_angle_for_pair(
    tracks: dict[int, list[dict[str, object]]],
    first: dict[str, object],
    second: dict[str, object],
) -> float | None:
    timestamp = float(second["entry_seconds"])
    first_state = state_at(tracks[int(first["track_id"])], timestamp)
    second_state = state_at(tracks[int(second["track_id"])], timestamp)
    if first_state is None or second_state is None:
        return None
    _, _, vx1, vy1 = first_state
    _, _, vx2, vy2 = second_state
    speed1 = math.hypot(vx1, vy1)
    speed2 = math.hypot(vx2, vy2)
    if speed1 < 1e-6 or speed2 < 1e-6:
        return None
    cosine = max(-1.0, min(1.0, (vx1 * vx2 + vy1 * vy2) / (speed1 * speed2)))
    return math.degrees(math.acos(cosine))


def compute_events(
    intervals: list[dict[str, object]],
    tracks: dict[int, list[dict[str, object]]],
    maximum_pet_seconds: float,
    minimum_crossing_angle_degrees: float,
    maximum_encroachment_distance_pixels: float,
    video_id: str = "DJI_0482",
) -> list[dict[str, object]]:
    by_roi: dict[str, list[dict[str, object]]] = defaultdict(list)
    for interval in intervals:
        by_roi[str(interval["roi_id"])].append(interval)
    events = []
    for roi_id, visits in sorted(by_roi.items()):
        visits.sort(key=lambda row: float(row["entry_seconds"]))
        for index, second in enumerate(visits):
            for first in visits[:index]:
                if first["track_id"] == second["track_id"]:
                    continue
                kinds = {first["class_kind"], second["class_kind"]}
                if kinds == {"pedestrian", "vehicle"}:
                    conflict_type = "pedestrian_vehicle"
                elif first["class_kind"] == second["class_kind"] == "vehicle":
                    conflict_type = "vehicle_vehicle"
                else:
                    continue
                pet = float(second["entry_seconds"]) - float(first["exit_seconds"])
                if not 0 <= pet <= maximum_pet_seconds:
                    continue
                crossing_angle = crossing_angle_for_pair(tracks, first, second)
                if (
                    crossing_angle is None
                    or crossing_angle < minimum_crossing_angle_degrees
                ):
                    continue
                closest_first, closest_second = min(
                    (
                        (first_point, second_point)
                        for first_point in first["points"]
                        for second_point in second["points"]
                    ),
                    key=lambda pair: math.hypot(
                        pair[0][0] - pair[1][0], pair[0][1] - pair[1][1]
                    ),
                )
                encroachment_distance = math.hypot(
                    closest_first[0] - closest_second[0],
                    closest_first[1] - closest_second[1],
                )
                if encroachment_distance > maximum_encroachment_distance_pixels:
                    continue
                ttc, approaching, distance = ttc_for_pair(tracks, first, second)
                events.append({
                    "event_id": f"{roi_id}-{len(events) + 1:04d}",
                    "video_id": video_id,
                    "timestamp_seconds": float(second["entry_seconds"]),
                    "frame_index": int(second["entry_frame"]),
                    "conflict_type": conflict_type,
                    "first_track_id": int(first["track_id"]),
                    "second_track_id": int(second["track_id"]),
                    "roi_id": roi_id,
                    "x": round((closest_first[0] + closest_second[0]) / 2, 3),
                    "y": round((closest_first[1] + closest_second[1]) / 2, 3),
                    "pet_seconds": round(pet, 3),
                    "ttc_seconds": round(ttc, 3) if ttc is not None else None,
                    "approaching": approaching,
                    "distance_pixels": round(distance, 3) if distance is not None else None,
                    "encroachment_distance_pixels": round(encroachment_distance, 3),
                    "crossing_angle_degrees": round(crossing_angle, 3),
                    "validation_status": "unreviewed",
                })
    return events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--zones", required=True)
    parser.add_argument("--homographies", required=True)
    parser.add_argument("--video-id", default="DJI_0482")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--maximum-gap-seconds", type=float, default=0.25)
    parser.add_argument("--maximum-pet-seconds", type=float, default=5.0)
    parser.add_argument("--minimum-crossing-angle-degrees", type=float, default=20.0)
    parser.add_argument(
        "--maximum-encroachment-distance-pixels", type=float, default=160.0
    )
    args = parser.parse_args()

    zones_data = json.loads(resolve_project_path(args.zones).read_text(encoding="utf-8"))
    homographies = json.loads(
        resolve_project_path(args.homographies).read_text(encoding="utf-8")
    )
    matrix = homographies["videos"][args.video_id]["h"]
    tracks = load_tracks(resolve_project_path(args.tracks), matrix)
    intervals = build_intervals(tracks, zones_data["zones"], args.maximum_gap_seconds)
    roi_summary = summarize_rois(zones_data["zones"], intervals)
    events = compute_events(
        intervals,
        tracks,
        args.maximum_pet_seconds,
        args.minimum_crossing_angle_degrees,
        args.maximum_encroachment_distance_pixels,
        args.video_id,
    )

    output = resolve_project_path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "roi_summary.json").write_text(
        json.dumps(roi_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "risk_summary.json").write_text(
        json.dumps({
            "coordinate_reference": homographies["reference"],
            "source_video": args.video_id,
            "track_count": len(tracks),
            "roi_visit_intervals": len(intervals),
            "pet_candidate_events": len(events),
            "approaching_ttc_events": sum(event["approaching"] for event in events),
            "validation_status": "unreviewed",
            "minimum_crossing_angle_degrees":
                args.minimum_crossing_angle_degrees,
            "maximum_encroachment_distance_pixels":
                args.maximum_encroachment_distance_pixels,
            "limitations": [
                "ROI definitions and alignment originate from legacy calibration",
                "PET candidates require manual event validation",
                "TTC is an image-plane approximation in pixels",
                "Crossing angle is an image-plane velocity estimate",
            ],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "tracks": len(tracks),
        "roi_intervals": len(intervals),
        "events": len(events),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
