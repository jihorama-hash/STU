"""Summarize track continuity before manual review."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from .paths import resolve_project_path


def summarize(path: Path, minimum_duration: float) -> dict[str, object]:
    timestamps: dict[int, list[float]] = defaultdict(list)
    positions: dict[int, list[tuple[float, float]]] = defaultdict(list)
    classes: dict[int, str] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            track_id = int(row["track_id"])
            timestamps[track_id].append(float(row["timestamp_seconds"]))
            positions[track_id].append((float(row["foot_x"]), float(row["foot_y"])))
            classes[track_id] = row["object_class"]

    result: dict[str, object] = {}
    for object_class in sorted(set(classes.values())):
        ids = [track_id for track_id, name in classes.items() if name == object_class]
        durations = [
            max(timestamps[track_id]) - min(timestamps[track_id]) for track_id in ids
        ]
        points = [len(timestamps[track_id]) for track_id in ids]
        displacements = [
            math.hypot(
                positions[track_id][-1][0] - positions[track_id][0][0],
                positions[track_id][-1][1] - positions[track_id][0][1],
            )
            for track_id in ids
        ]
        short = sum(duration < minimum_duration for duration in durations)
        result[object_class] = {
            "tracks": len(ids),
            "observations": sum(points),
            "median_duration_seconds": statistics.median(durations),
            "mean_duration_seconds": statistics.mean(durations),
            "median_observations": statistics.median(points),
            "tracks_below_minimum": short,
            "tracks_below_minimum_percent": 100 * short / len(ids),
            "one_observation_tracks": sum(point_count == 1 for point_count in points),
            "tracks_at_least_5_seconds": sum(duration >= 5 for duration in durations),
            "median_net_displacement_pixels": statistics.median(displacements),
            "tracks_below_120px_displacement": sum(
                displacement < 120 for displacement in displacements
            ),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tracks")
    parser.add_argument("--minimum-duration", type=float, default=0.5)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = summarize(resolve_project_path(args.tracks), args.minimum_duration)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        destination = resolve_project_path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
