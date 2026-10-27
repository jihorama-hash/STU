from __future__ import annotations

from _paths import BASE

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


DEFAULT_TRACKS = BASE / "runs" / "DJI_0481_sahi_step10" / "tracks_pixel.csv"
DEFAULT_ZONES = BASE / "runs" / "DJI_0481_sahi_step10" / "conflict_zones.json"
DEFAULT_OUTPUT = BASE / "runs" / "DJI_0481_sahi_step10" / "pet_events.csv"
DEFAULT_RISK_OUTPUT = BASE / "runs" / "DJI_0481_sahi_step10" / "pet_risk_by_roi.csv"

CLASS_KIND = {
    "person": "pedestrian",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
}

OUTPUT_FIELDS = [
    "event_id",
    "roi_id",
    "roi_name",
    "first_track_id",
    "first_class_name",
    "first_class_kind",
    "first_entry_sec",
    "first_exit_sec",
    "second_track_id",
    "second_class_name",
    "second_class_kind",
    "second_entry_sec",
    "second_exit_sec",
    "pet_sec",
    "event_scope",
    "conflict_type",
    "pet_score",
    "conflict_weight",
    "risk_score",
    "risk_level",
    "event_x",
    "event_y",
    "severity",
]

RISK_FIELDS = [
    "roi_id",
    "roi_name",
    "event_count",
    "final_event_count",
    "reference_event_count",
    "vehicle_vehicle_events",
    "pedestrian_vehicle_events",
    "risk_score_sum",
    "risk_score_max",
    "risk_score_avg",
    "avg_pet_sec",
    "min_pet_sec",
    "final_risk_level",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute PET events from tracked SAHI CSV.")
    parser.add_argument("--tracks", type=Path, default=DEFAULT_TRACKS)
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--risk-output", type=Path, default=DEFAULT_RISK_OUTPUT)
    parser.add_argument("--max-pet-sec", type=float, default=5.0)
    parser.add_argument(
        "--final-pet-sec",
        type=float,
        default=3.0,
        help="PET threshold for final risk events. Events above this and <= max-pet-sec are references.",
    )
    parser.add_argument("--near-sec", type=float, default=1.5)
    parser.add_argument("--caution-sec", type=float, default=3.0)
    parser.add_argument(
        "--vehicle-vehicle-weight",
        type=float,
        default=1.0,
        help="Risk multiplier for vehicle-vehicle PET events.",
    )
    parser.add_argument(
        "--pedestrian-vehicle-weight",
        type=float,
        default=1.5,
        help="Risk multiplier for pedestrian-vehicle PET events.",
    )
    return parser.parse_args()


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (
            (yj - yi) or 1e-9
        ) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def polygon_centroid(polygon: list[list[float]]) -> tuple[float, float]:
    if not polygon:
        return 0.0, 0.0
    return (
        sum(point[0] for point in polygon) / len(polygon),
        sum(point[1] for point in polygon) / len(polygon),
    )


def read_zones(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data["zones"]


def read_tracks(path: Path) -> dict[str, list[dict]]:
    tracks: dict[str, list[dict]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            track_id = (row.get("track_id") or "").strip()
            class_name = (row.get("class_name") or "").strip()
            if not track_id or not class_name:
                continue
            anchor_x = parse_float(row.get("anchor_x") or row.get("foot_x") or row.get("cx") or "")
            anchor_y = parse_float(row.get("anchor_y") or row.get("foot_y") or row.get("cy") or "")
            tracks[track_id].append(
                {
                    "track_id": track_id,
                    "frame_id": int(parse_float(row.get("frame_id", ""))),
                    "time_sec": parse_float(row.get("time_sec", "")),
                    "class_name": class_name,
                    "class_kind": CLASS_KIND.get(class_name, "other"),
                    "anchor_x": anchor_x,
                    "anchor_y": anchor_y,
                }
            )
    for rows in tracks.values():
        rows.sort(key=lambda item: item["time_sec"])
    return tracks


def build_intervals(tracks: dict[str, list[dict]], zones: list[dict]) -> list[dict]:
    intervals = []
    for zone in zones:
        polygon = zone["polygon"]
        zone_x, zone_y = polygon_centroid(polygon)
        for track_id, rows in tracks.items():
            inside_rows = [
                row
                for row in rows
                if point_in_polygon(row["anchor_x"], row["anchor_y"], polygon)
            ]
            if not inside_rows:
                continue
            class_name_counts: dict[str, int] = defaultdict(int)
            for row in inside_rows:
                class_name_counts[row["class_name"]] += 1
            class_name = max(class_name_counts.items(), key=lambda item: item[1])[0]
            event_x = sum(row["anchor_x"] for row in inside_rows) / len(inside_rows)
            event_y = sum(row["anchor_y"] for row in inside_rows) / len(inside_rows)
            intervals.append(
                {
                    "roi_id": zone["id"],
                    "roi_name": zone.get("name", zone["id"]),
                    "track_id": track_id,
                    "class_name": class_name,
                    "class_kind": CLASS_KIND.get(class_name, "other"),
                    "entry_sec": inside_rows[0]["time_sec"],
                    "exit_sec": inside_rows[-1]["time_sec"],
                    "event_x": event_x if event_x > 0 else zone_x,
                    "event_y": event_y if event_y > 0 else zone_y,
                }
            )
    intervals.sort(key=lambda item: (item["roi_id"], item["entry_sec"], item["track_id"]))
    return intervals


def severity(pet_sec: float, near_sec: float, caution_sec: float) -> str:
    if pet_sec <= near_sec:
        return "near_conflict"
    if pet_sec <= caution_sec:
        return "caution"
    return "normal"


def risk_level(score: float) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def conflict_type(first_kind: str, second_kind: str) -> str | None:
    kinds = {first_kind, second_kind}
    if kinds == {"pedestrian", "vehicle"}:
        return "pedestrian_vehicle"
    if first_kind == "vehicle" and second_kind == "vehicle":
        return "vehicle_vehicle"
    return None


def score_event(
    pet_sec: float,
    final_pet_sec: float,
    conflict: str,
    vehicle_vehicle_weight: float,
    pedestrian_vehicle_weight: float,
) -> tuple[float, float, float]:
    if final_pet_sec <= 0 or pet_sec > final_pet_sec:
        return 0.0, 0.0, 0.0
    pet_score = max(0.0, min(100.0, (final_pet_sec - pet_sec) / final_pet_sec * 100.0))
    if conflict == "pedestrian_vehicle":
        weight = pedestrian_vehicle_weight
    else:
        weight = vehicle_vehicle_weight
    risk_score = max(0.0, min(100.0, pet_score * weight))
    return round(pet_score, 3), round(weight, 3), round(risk_score, 3)


def compute_events(
    intervals: list[dict],
    max_pet_sec: float,
    final_pet_sec: float,
    near_sec: float,
    caution_sec: float,
    vehicle_vehicle_weight: float,
    pedestrian_vehicle_weight: float,
) -> list[dict]:
    by_zone: dict[str, list[dict]] = defaultdict(list)
    for interval in intervals:
        by_zone[interval["roi_id"]].append(interval)

    events = []
    event_id = 1
    for roi_id, zone_intervals in sorted(by_zone.items()):
        zone_intervals.sort(key=lambda item: (item["entry_sec"], item["exit_sec"]))
        for current_index, current in enumerate(zone_intervals):
            for previous in zone_intervals[:current_index]:
                if previous["track_id"] == current["track_id"]:
                    continue

                pet_sec = current["entry_sec"] - previous["exit_sec"]
                if pet_sec < 0 or pet_sec > max_pet_sec:
                    continue

                conflict = conflict_type(previous["class_kind"], current["class_kind"])
                if conflict is None:
                    continue

                event_scope = "final" if pet_sec <= final_pet_sec else "reference"
                pet_score, weight, risk_score = score_event(
                    pet_sec=pet_sec,
                    final_pet_sec=final_pet_sec,
                    conflict=conflict,
                    vehicle_vehicle_weight=vehicle_vehicle_weight,
                    pedestrian_vehicle_weight=pedestrian_vehicle_weight,
                )

                events.append(
                    {
                        "event_id": event_id,
                        "roi_id": roi_id,
                        "roi_name": current["roi_name"],
                        "first_track_id": previous["track_id"],
                        "first_class_name": previous["class_name"],
                        "first_class_kind": previous["class_kind"],
                        "first_entry_sec": previous["entry_sec"],
                        "first_exit_sec": previous["exit_sec"],
                        "second_track_id": current["track_id"],
                        "second_class_name": current["class_name"],
                        "second_class_kind": current["class_kind"],
                        "second_entry_sec": current["entry_sec"],
                        "second_exit_sec": current["exit_sec"],
                        "pet_sec": round(pet_sec, 3),
                        "event_scope": event_scope,
                        "conflict_type": conflict,
                        "pet_score": pet_score,
                        "conflict_weight": weight,
                        "risk_score": risk_score,
                        "risk_level": risk_level(risk_score),
                        "event_x": round((previous["event_x"] + current["event_x"]) / 2, 3),
                        "event_y": round((previous["event_y"] + current["event_y"]) / 2, 3),
                        "severity": severity(pet_sec, near_sec, caution_sec),
                    }
                )
                event_id += 1
    return events


def summarize_risk_by_roi(events: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["roi_id"]].append(event)

    rows = []
    for roi_id, roi_events in sorted(grouped.items()):
        final_events = [event for event in roi_events if event.get("event_scope") == "final"]
        scored_events = final_events or roi_events
        risk_scores = [float(event["risk_score"]) for event in scored_events]
        pet_values = [float(event["pet_sec"]) for event in scored_events]
        vehicle_vehicle_events = sum(
            1 for event in final_events if event["conflict_type"] == "vehicle_vehicle"
        )
        pedestrian_vehicle_events = sum(
            1 for event in final_events if event["conflict_type"] == "pedestrian_vehicle"
        )
        risk_sum = sum(risk_scores)
        rows.append(
            {
                "roi_id": roi_id,
                "roi_name": roi_events[0]["roi_name"],
                "event_count": len(roi_events),
                "final_event_count": len(final_events),
                "reference_event_count": len(roi_events) - len(final_events),
                "vehicle_vehicle_events": vehicle_vehicle_events,
                "pedestrian_vehicle_events": pedestrian_vehicle_events,
                "risk_score_sum": round(risk_sum, 3),
                "risk_score_max": round(max(risk_scores), 3),
                "risk_score_avg": round(risk_sum / len(risk_scores), 3),
                "avg_pet_sec": round(sum(pet_values) / len(pet_values), 3),
                "min_pet_sec": round(min(pet_values), 3),
                "final_risk_level": risk_level(max(risk_scores)),
            }
        )
    rows.sort(key=lambda item: item["risk_score_sum"], reverse=True)
    return rows


def write_events(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_risk_summary(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=RISK_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    zones = read_zones(args.zones)
    tracks = read_tracks(args.tracks)
    intervals = build_intervals(tracks, zones)
    events = compute_events(
        intervals=intervals,
        max_pet_sec=args.max_pet_sec,
        final_pet_sec=args.final_pet_sec,
        near_sec=args.near_sec,
        caution_sec=args.caution_sec,
        vehicle_vehicle_weight=args.vehicle_vehicle_weight,
        pedestrian_vehicle_weight=args.pedestrian_vehicle_weight,
    )
    risk_summary = summarize_risk_by_roi(events)
    write_events(args.output, events)
    write_risk_summary(args.risk_output, risk_summary)
    print(f"Tracks: {len(tracks)}")
    print(f"Zones: {len(zones)}")
    print(f"Zone intervals: {len(intervals)}")
    print(f"PET events: {len(events)}")
    print(f"Saved: {args.output}")
    print(f"Saved risk summary: {args.risk_output}")


if __name__ == "__main__":
    main()
