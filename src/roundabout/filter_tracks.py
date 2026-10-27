"""Apply conservative trajectory and roadway filters to tracked detections."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import cv2

from .paths import resolve_project_path


VEHICLE_CLASSES = {"bicycle", "motorcycle", "car", "bus", "truck", "tricycle"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--roadway-mask", required=True)
    parser.add_argument("--vehicle-exclusion-mask")
    parser.add_argument("--minimum-vehicle-exclusion-fraction", type=float, default=0.5)
    parser.add_argument("--minimum-duration", type=float, default=0.5)
    parser.add_argument("--minimum-spread", type=float, default=10.0)
    parser.add_argument("--minimum-vehicle-road-fraction", type=float, default=0.1)
    parser.add_argument("--outside-roadway-keep-spread", type=float, default=50.0)
    args = parser.parse_args()

    tracks_path = resolve_project_path(args.tracks)
    output_path = resolve_project_path(args.output)
    summary_path = resolve_project_path(args.summary)
    mask_path = resolve_project_path(args.roadway_mask)
    roadway_mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if roadway_mask is None:
        raise FileNotFoundError(mask_path)
    exclusion_mask = None
    exclusion_mask_path = None
    if args.vehicle_exclusion_mask:
        exclusion_mask_path = resolve_project_path(args.vehicle_exclusion_mask)
        exclusion_mask = cv2.imread(str(exclusion_mask_path), cv2.IMREAD_GRAYSCALE)
        if exclusion_mask is None:
            raise FileNotFoundError(exclusion_mask_path)
        if exclusion_mask.shape != roadway_mask.shape:
            raise ValueError("Vehicle exclusion mask must match roadway mask dimensions")

    tracks: dict[int, list[dict[str, str]]] = defaultdict(list)
    with tracks_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        for row in reader:
            tracks[int(row["track_id"])].append(row)
    if not fieldnames:
        raise ValueError("Track CSV has no header")

    kept: set[int] = set()
    removed_reasons: Counter[str] = Counter()
    track_metrics: dict[int, dict[str, object]] = {}
    for track_id, rows in tracks.items():
        rows.sort(key=lambda row: int(row["frame_index"]))
        object_class = rows[0]["object_class"]
        duration = (
            float(rows[-1]["timestamp_seconds"])
            - float(rows[0]["timestamp_seconds"])
        )
        xs = [float(row["foot_x"]) for row in rows]
        ys = [float(row["foot_y"]) for row in rows]
        spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        road_hits = 0
        exclusion_hits = 0
        for x, y in zip(xs, ys):
            pixel_x = min(roadway_mask.shape[1] - 1, max(0, round(x)))
            pixel_y = min(roadway_mask.shape[0] - 1, max(0, round(y)))
            road_hits += int(roadway_mask[pixel_y, pixel_x] > 0)
            if exclusion_mask is not None:
                exclusion_hits += int(exclusion_mask[pixel_y, pixel_x] > 0)
        road_fraction = road_hits / len(rows)
        exclusion_fraction = exclusion_hits / len(rows)

        reason = ""
        if duration < args.minimum_duration:
            reason = "duration"
        elif spread < args.minimum_spread:
            reason = "spatial_spread"
        elif (
            object_class in VEHICLE_CLASSES
            and exclusion_fraction >= args.minimum_vehicle_exclusion_fraction
        ):
            reason = "vehicle_exclusion_zone"
        elif (
            object_class in VEHICLE_CLASSES
            and road_fraction < args.minimum_vehicle_road_fraction
            and spread < args.outside_roadway_keep_spread
        ):
            reason = "vehicle_outside_roadway"
        else:
            kept.add(track_id)
        if reason:
            removed_reasons[reason] += 1
        track_metrics[track_id] = {
            "object_class": object_class,
            "duration_seconds": duration,
            "spatial_spread_pixels": spread,
            "road_fraction": road_fraction,
            "vehicle_exclusion_fraction": exclusion_fraction,
            "decision": "kept" if not reason else f"removed:{reason}",
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for track_id, rows in tracks.items():
            if track_id in kept:
                writer.writerows(rows)

    summary = {
        "source": str(tracks_path),
        "output": str(output_path),
        "input_tracks": len(tracks),
        "kept_tracks": len(kept),
        "removed_tracks": len(tracks) - len(kept),
        "removed_reasons": dict(removed_reasons),
        "parameters": {
            "minimum_duration": args.minimum_duration,
            "minimum_spread": args.minimum_spread,
            "minimum_vehicle_road_fraction": args.minimum_vehicle_road_fraction,
            "outside_roadway_keep_spread": args.outside_roadway_keep_spread,
            "roadway_mask": str(mask_path),
            "vehicle_exclusion_mask": (
                str(exclusion_mask_path) if exclusion_mask_path else None
            ),
            "minimum_vehicle_exclusion_fraction":
                args.minimum_vehicle_exclusion_fraction,
        },
        "track_metrics": track_metrics,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in summary.items()
                      if key != "track_metrics"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
