from __future__ import annotations

from _paths import BASE

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


BASE_DIR = BASE
OUTPUT_DIR = BASE_DIR / "runs" / "phaseA_step3_vs_step10"

STEP3_DIR = BASE_DIR / "runs" / "DJI_0482_sahi_step3_final"
STEP10_DIR = BASE_DIR / "runs" / "DJI_0482_sahi_step10"
ZONES = STEP3_DIR / "conflict_zones.json"  # 0481과 동일한 공통 ROI

VARIANTS = {
    "step3": {
        "detections": STEP3_DIR / "detections_pixel.csv",
        "tracks": STEP3_DIR / "tracks_pixel.csv",
        "events": STEP3_DIR / "final_m0615" / "pet_events_final.csv",
        "effective_fps": 29.97 / 3,
    },
    "step10": {
        "detections": STEP10_DIR / "detections_pixel.csv",
        "tracks": STEP10_DIR / "m0615_pet_deduped" / "tracks_pixel_m0615.csv",
        "events": STEP10_DIR / "m0615_pet_deduped_step3roi" / "pet_events_m0615_deduped_step3roi.csv",
        "effective_fps": 29.97 / 10,
    },
}

CLASS_KIND = {
    "person": "pedestrian",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
}

CLASSIFICATION = (
    STEP10_DIR / "m0615_pet_deduped_step3roi" / "step3_to_step10_pet_event_classification.csv"
)


def parse_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def point_in_polygon(x, y, polygon):
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def read_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def track_stats(rows):
    tracks = defaultdict(list)
    for row in rows:
        tracks[row["track_id"]].append(row)
    durations, points = [], []
    class_of_track = Counter()
    for track_rows in tracks.values():
        track_rows.sort(key=lambda r: parse_float(r["time_sec"]))
        durations.append(
            parse_float(track_rows[-1]["time_sec"]) - parse_float(track_rows[0]["time_sec"])
        )
        points.append(len(track_rows))
        names = Counter(r["class_name"] for r in track_rows)
        class_of_track[names.most_common(1)[0][0]] += 1
    durations.sort()
    n = len(durations)
    return {
        "track_count": n,
        "median_duration_sec": round(durations[n // 2], 2) if n else 0,
        "mean_duration_sec": round(sum(durations) / n, 2) if n else 0,
        "short_tracks_lt2s": sum(1 for d in durations if d < 2.0),
        "mean_points_per_track": round(sum(points) / n, 1) if n else 0,
        "tracks_by_class": dict(class_of_track),
    }, tracks


def roi_entries(tracks, zones):
    per_roi = {}
    for zone in zones:
        ped = veh = 0
        for track_rows in tracks.values():
            inside = [
                r
                for r in track_rows
                if point_in_polygon(
                    parse_float(r.get("anchor_x") or r.get("foot_x") or r.get("cx")),
                    parse_float(r.get("anchor_y") or r.get("foot_y") or r.get("cy")),
                    zone["polygon"],
                )
            ]
            if not inside:
                continue
            kinds = Counter(CLASS_KIND.get(r["class_name"], "other") for r in inside)
            kind = kinds.most_common(1)[0][0]
            if kind == "pedestrian":
                ped += 1
            elif kind == "vehicle":
                veh += 1
        per_roi[zone["id"]] = {"pedestrian_entries": ped, "vehicle_entries": veh}
    return per_roi


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zones = json.load(ZONES.open(encoding="utf-8"))["zones"]

    summary = {}
    entries_table = []
    for name, cfg in VARIANTS.items():
        detections = read_rows(cfg["detections"])
        det_by_class = Counter(r["class_name"] for r in detections)
        track_rows = read_rows(cfg["tracks"])
        stats, tracks = track_stats(track_rows)
        entries = roi_entries(tracks, zones)
        events = read_rows(cfg["events"])
        event_scope = Counter(r.get("event_scope", "") for r in events)
        event_type = Counter(r.get("conflict_type", "") for r in events)
        summary[name] = {
            "effective_fps": round(cfg["effective_fps"], 2),
            "detection_rows": len(detections),
            "detections_by_class": dict(det_by_class),
            **stats,
            "pet_events_total": len(events),
            "pet_events_by_scope": dict(event_scope),
            "pet_events_by_type": dict(event_type),
            "roi_entries": entries,
        }
        for roi_id, vals in entries.items():
            entries_table.append({"variant": name, "roi_id": roi_id, **vals})

    # 기존 이벤트 매칭 분류표 요약
    classification = Counter(r["status"] for r in read_rows(CLASSIFICATION))

    # step3 검출량이 프레임 수 3.33배인 점을 감안한 프레임당 검출률 비교
    for name in summary:
        frames = Counter()
        for r in read_rows(VARIANTS[name]["detections"]):
            frames[r["frame_id"]] += 1
        summary[name]["frames_with_detections"] = len(frames)
        summary[name]["detections_per_frame"] = round(
            summary[name]["detection_rows"] / max(len(frames), 1), 2
        )

    result = {
        "video": "DJI_0482",
        "zones": "step3/0481 공통 ROI (b39603e8)",
        "variants": summary,
        "step3_events_matched_in_step10": dict(classification),
    }
    (OUTPUT_DIR / "step3_vs_step10_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (OUTPUT_DIR / "roi_entries_comparison.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=["variant", "roi_id", "pedestrian_entries", "vehicle_entries"]
        )
        writer.writeheader()
        writer.writerows(entries_table)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
