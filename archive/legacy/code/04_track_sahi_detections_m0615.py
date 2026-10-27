from __future__ import annotations

from _paths import BASE

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


DEFAULT_INPUT = BASE / "runs" / "DJI_0481_sahi_step10" / "detections_pixel.csv"
DEFAULT_OUTPUT = BASE / "runs" / "DJI_0481_sahi_step10" / "tracks_pixel.csv"

OUTPUT_FIELDS = [
    "frame_id",
    "time_sec",
    "track_id",
    "class_id",
    "class_name",
    "confidence",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "foot_x",
    "foot_y",
    "anchor_x",
    "anchor_y",
    "anchor_type",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign simple track ids to SAHI detection CSV output."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-distance", type=float, default=250.0)
    parser.add_argument("--min-iou", type=float, default=0.01)
    parser.add_argument("--max-age-sec", type=float, default=4.0)
    return parser.parse_args()


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_detections(path: Path) -> dict[int, list[dict]]:
    frames: dict[int, list[dict]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            frame_id = parse_int(row.get("frame_id", ""))
            x1 = parse_float(row.get("x1", ""))
            y1 = parse_float(row.get("y1", ""))
            x2 = parse_float(row.get("x2", ""))
            y2 = parse_float(row.get("y2", ""))
            cx = parse_float(row.get("cx", ""), (x1 + x2) / 2)
            cy = parse_float(row.get("cy", ""), (y1 + y2) / 2)
            foot_x = parse_float(row.get("foot_x", ""), cx)
            foot_y = parse_float(row.get("foot_y", ""), y2)
            frames[frame_id].append(
                {
                    "frame_id": frame_id,
                    "time_sec": parse_float(row.get("time_sec", "")),
                    "class_id": parse_int(row.get("class_id", "")),
                    "class_name": (row.get("class_name") or "").strip(),
                    "confidence": parse_float(row.get("confidence", "")),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "cx": cx,
                    "cy": cy,
                    "foot_x": foot_x,
                    "foot_y": foot_y,
                }
            )
    return frames


def iou(a: dict, b: dict) -> float:
    x1 = max(a["x1"], b["x1"])
    y1 = max(a["y1"], b["y1"])
    x2 = min(a["x2"], b["x2"])
    y2 = min(a["y2"], b["y2"])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a["x2"] - a["x1"]) * max(0.0, a["y2"] - a["y1"])
    area_b = max(0.0, b["x2"] - b["x1"]) * max(0.0, b["y2"] - b["y1"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def distance(a: dict, b: dict) -> float:
    return math.hypot(a["anchor_x"] - b["foot_x"], a["anchor_y"] - b["foot_y"])


def assign_tracks(
    frames: dict[int, list[dict]],
    max_distance: float,
    min_iou: float,
    max_age_sec: float,
) -> list[dict]:
    active: dict[int, dict] = {}
    next_track_id = 1
    rows: list[dict] = []

    for frame_id in sorted(frames):
        detections = sorted(frames[frame_id], key=lambda item: item["confidence"], reverse=True)
        if detections:
            now_sec = detections[0]["time_sec"]
            expired = [
                track_id
                for track_id, track in active.items()
                if now_sec - track["time_sec"] > max_age_sec
            ]
            for track_id in expired:
                del active[track_id]

        used_tracks = set()
        for det in detections:
            best_track_id = None
            best_score = -1.0
            for track_id, track in active.items():
                if track_id in used_tracks or track["class_id"] != det["class_id"]:
                    continue
                det_for_distance = {
                    "foot_x": det["foot_x"],
                    "foot_y": det["foot_y"],
                }
                dist = distance(track, det_for_distance)
                overlap = iou(track, det)
                if dist > max_distance and overlap < min_iou:
                    continue
                score = overlap * 1000.0 - dist
                if score > best_score:
                    best_score = score
                    best_track_id = track_id

            if best_track_id is None:
                best_track_id = next_track_id
                next_track_id += 1

            used_tracks.add(best_track_id)
            out = dict(det)
            out["track_id"] = best_track_id
            out["anchor_x"] = det["foot_x"]
            out["anchor_y"] = det["foot_y"]
            out["anchor_type"] = "foot_point"
            rows.append(out)
            active[best_track_id] = out

    rows.sort(key=lambda item: (item["frame_id"], item["track_id"]))
    return rows


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    frames = read_detections(args.input)
    rows = assign_tracks(
        frames=frames,
        max_distance=args.max_distance,
        min_iou=args.min_iou,
        max_age_sec=args.max_age_sec,
    )
    write_rows(args.output, rows)
    print(f"Input frames: {len(frames)}")
    print(f"Input detections: {sum(len(items) for items in frames.values())}")
    print(f"Tracked rows: {len(rows)}")
    print(f"Tracks: {len({row['track_id'] for row in rows})}")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
