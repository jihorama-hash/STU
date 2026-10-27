from __future__ import annotations

import argparse
import csv
import importlib.util
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify how step3 PET events map to step10 PET events under the same ROI."
    )
    parser.add_argument("--step3-events", type=Path, required=True)
    parser.add_argument("--step3-tracks", type=Path, required=True)
    parser.add_argument("--step10-tracks", type=Path, required=True)
    parser.add_argument("--zones", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pet-sec", type=float, default=3.0)
    parser.add_argument("--final-pet-sec", type=float, default=1.5)
    parser.add_argument("--match-time-sec", type=float, default=1.0)
    parser.add_argument("--match-distance-px", type=float, default=350.0)
    parser.add_argument("--actor-time-sec", type=float, default=1.0)
    return parser.parse_args()


def load_pet_module():
    spec = importlib.util.spec_from_file_location("pet_m0615", "src/06_compute_pet_m0615.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load PET module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def event_time(event: dict) -> float:
    return parse_float(event.get("second_entry_sec", ""))


def event_distance(a: dict, b: dict) -> float:
    dx = parse_float(a.get("event_x", "")) - parse_float(b.get("event_x", ""))
    dy = parse_float(a.get("event_y", "")) - parse_float(b.get("event_y", ""))
    return (dx * dx + dy * dy) ** 0.5


def compatible_event(a: dict, b: dict, time_limit: float, distance_limit: float) -> bool:
    if a.get("roi_id") != b.get("roi_id"):
        return False
    if a.get("conflict_type") != b.get("conflict_type"):
        return False
    return abs(event_time(a) - event_time(b)) <= time_limit and event_distance(a, b) <= distance_limit


def best_event_match(target: dict, candidates: list[dict], time_limit: float, distance_limit: float):
    matches = [event for event in candidates if compatible_event(target, event, time_limit, distance_limit)]
    if not matches:
        return None
    return min(
        matches,
        key=lambda event: (
            abs(event_time(target) - event_time(event)),
            event_distance(target, event),
            abs(parse_float(target.get("pet_sec", "")) - parse_float(event.get("pet_sec", ""))),
        ),
    )


def interval_midpoint(interval: dict) -> float:
    return (parse_float(interval["entry_sec"]) + parse_float(interval["exit_sec"])) / 2.0


def actor_reference(event: dict, prefix: str) -> dict:
    return {
        "roi_id": event["roi_id"],
        "track_id": event[f"{prefix}_track_id"],
        "class_name": event[f"{prefix}_class_name"],
        "class_kind": event[f"{prefix}_class_kind"],
        "entry_sec": parse_float(event[f"{prefix}_entry_sec"]),
        "exit_sec": parse_float(event[f"{prefix}_exit_sec"]),
    }


def find_step3_interval(intervals: list[dict], ref: dict) -> dict | None:
    for interval in intervals:
        if interval["roi_id"] != ref["roi_id"]:
            continue
        if str(interval["track_id"]) != str(ref["track_id"]):
            continue
        if interval["class_kind"] != ref["class_kind"]:
            continue
        if abs(parse_float(interval["entry_sec"]) - ref["entry_sec"]) <= 0.15:
            return interval
    return None


def find_step10_actor_interval(
    step3_interval: dict | None,
    ref: dict,
    step10_intervals: list[dict],
    actor_time_sec: float,
) -> dict | None:
    center_time = (
        interval_midpoint(step3_interval)
        if step3_interval is not None
        else (ref["entry_sec"] + ref["exit_sec"]) / 2.0
    )
    candidates = []
    for interval in step10_intervals:
        if interval["roi_id"] != ref["roi_id"]:
            continue
        if interval["class_kind"] != ref["class_kind"]:
            continue
        if interval["class_name"] != ref["class_name"]:
            continue
        time_delta = abs(interval_midpoint(interval) - center_time)
        if time_delta > actor_time_sec:
            continue
        candidates.append((time_delta, interval))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def pair_pet(first: dict | None, second: dict | None) -> float | None:
    if first is None or second is None:
        return None
    return parse_float(second["entry_sec"]) - parse_float(first["exit_sec"])


def classify_missing(
    first10: dict | None,
    second10: dict | None,
    pet10: float | None,
    max_pet_sec: float,
) -> str:
    if first10 is None and second10 is None:
        return "both_actor_roi_intervals_missing"
    if first10 is None:
        return "first_actor_roi_interval_missing"
    if second10 is None:
        return "second_actor_roi_interval_missing"
    if pet10 is None:
        return "actor_interval_match_failed"
    if pet10 < 0:
        return "step10_actor_order_overlaps_or_reversed"
    if pet10 > max_pet_sec:
        return "step10_pet_exceeds_3s"
    return "both_actor_intervals_present_but_no_raw_pet_match"


def prepare_events(pet_module, tracks_path: Path, zones_path: Path, max_pet_sec: float, final_pet_sec: float):
    zones = pet_module.read_zones(zones_path)
    raw_tracks = pet_module.read_tracks(tracks_path)
    tracks = pet_module.filter_tracks(raw_tracks, 2, 0.3)
    intervals = pet_module.build_intervals(tracks, zones)
    raw_events = pet_module.compute_events(
        intervals=intervals,
        max_pet_sec=max_pet_sec,
        final_pet_sec=final_pet_sec,
        near_sec=1.5,
        caution_sec=3.0,
        vehicle_vehicle_weight=1.0,
        pedestrian_vehicle_weight=1.5,
    )
    deduped_events = pet_module.dedupe_events(raw_events, 1.0, 200.0)
    return intervals, raw_events, deduped_events


def main() -> None:
    args = parse_args()
    pet_module = load_pet_module()
    step3_events = read_csv(args.step3_events)
    step3_intervals, _, _ = prepare_events(
        pet_module,
        args.step3_tracks,
        args.zones,
        args.max_pet_sec,
        args.final_pet_sec,
    )
    step10_intervals, step10_raw_events, step10_deduped_events = prepare_events(
        pet_module,
        args.step10_tracks,
        args.zones,
        args.max_pet_sec,
        args.final_pet_sec,
    )

    rows = []
    for event in step3_events:
        dedup_match = best_event_match(
            event,
            step10_deduped_events,
            args.match_time_sec,
            args.match_distance_px,
        )
        raw_match = best_event_match(
            event,
            step10_raw_events,
            args.match_time_sec,
            args.match_distance_px,
        )

        first_ref = actor_reference(event, "first")
        second_ref = actor_reference(event, "second")
        first3 = find_step3_interval(step3_intervals, first_ref)
        second3 = find_step3_interval(step3_intervals, second_ref)
        first10 = find_step10_actor_interval(first3, first_ref, step10_intervals, args.actor_time_sec)
        second10 = find_step10_actor_interval(second3, second_ref, step10_intervals, args.actor_time_sec)
        inferred_pet10 = pair_pet(first10, second10)

        if dedup_match is not None:
            status = "matched_in_step10_deduped"
            match = dedup_match
        elif raw_match is not None:
            status = "present_before_dedupe_only"
            match = raw_match
        else:
            status = classify_missing(first10, second10, inferred_pet10, args.max_pet_sec)
            match = None

        rows.append(
            {
                "step3_event_id": event["event_id"],
                "status": status,
                "roi_id": event["roi_id"],
                "conflict_type": event["conflict_type"],
                "step3_scope": event["event_scope"],
                "step3_pet_sec": event["pet_sec"],
                "step3_second_entry_sec": event["second_entry_sec"],
                "step3_event_x": event["event_x"],
                "step3_event_y": event["event_y"],
                "step10_event_id": "" if match is None else match["event_id"],
                "step10_scope": "" if match is None else match["event_scope"],
                "step10_pet_sec": "" if match is None else match["pet_sec"],
                "step10_second_entry_sec": "" if match is None else match["second_entry_sec"],
                "step10_event_x": "" if match is None else match["event_x"],
                "step10_event_y": "" if match is None else match["event_y"],
                "event_time_delta_sec": ""
                if match is None
                else round(event_time(match) - event_time(event), 3),
                "event_distance_px": ""
                if match is None
                else round(event_distance(event, match), 1),
                "first_actor_step10_interval": "yes" if first10 is not None else "no",
                "second_actor_step10_interval": "yes" if second10 is not None else "no",
                "inferred_step10_pet_sec": "" if inferred_pet10 is None else round(inferred_pet10, 3),
                "first_step3_track_id": event["first_track_id"],
                "first_class_name": event["first_class_name"],
                "second_step3_track_id": event["second_track_id"],
                "second_class_name": event["second_class_name"],
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = list(rows[0].keys()) if rows else []
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    status_counts = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    print(f"Step3 events: {len(step3_events)}")
    print(f"Step10 raw events: {len(step10_raw_events)}")
    print(f"Step10 deduped events: {len(step10_deduped_events)}")
    for status, count in sorted(status_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{status}: {count}")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
