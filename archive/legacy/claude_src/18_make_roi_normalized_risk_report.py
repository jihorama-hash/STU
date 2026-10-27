from __future__ import annotations

from _paths import BASE

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


BASE_DIR = BASE

CLASS_KIND = {
    "person": "pedestrian",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create ROI-normalized risk table and report.")
    parser.add_argument("--ttc-events", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("pairs", nargs="+", help="source_video=tracks_csv=zones_json")
    return parser.parse_args()


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else BASE_DIR / path


def parse_float(value: str | int | float | None, default: float = 0.0) -> float:
    if value is None:
        return default
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


def parse_pair(value: str) -> tuple[str, Path, Path]:
    parts = value.split("=", 2)
    if len(parts) != 3:
        raise ValueError(f"Expected source_video=tracks_csv=zones_json, got: {value}")
    return parts[0], resolve(parts[1]), resolve(parts[2])


def read_zones(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)["zones"]


def read_tracks(path: Path, min_points: int = 2, min_duration_sec: float = 0.3) -> dict[str, list[dict]]:
    tracks: dict[str, list[dict]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            track_id = (row.get("track_id") or "").strip()
            class_name = (row.get("class_name") or "").strip()
            if not track_id or not class_name:
                continue
            tracks[track_id].append(
                {
                    "time_sec": parse_float(row.get("time_sec", "")),
                    "class_name": class_name,
                    "class_kind": CLASS_KIND.get(class_name, "other"),
                    "anchor_x": parse_float(row.get("anchor_x") or row.get("foot_x") or row.get("cx")),
                    "anchor_y": parse_float(row.get("anchor_y") or row.get("foot_y") or row.get("cy")),
                }
            )
    filtered = {}
    for track_id, rows in tracks.items():
        rows.sort(key=lambda item: item["time_sec"])
        if len(rows) < min_points:
            continue
        if rows[-1]["time_sec"] - rows[0]["time_sec"] < min_duration_sec:
            continue
        filtered[track_id] = rows
    return filtered


def count_entries(source_video: str, tracks_path: Path, zones_path: Path) -> list[dict]:
    tracks = read_tracks(tracks_path)
    zones = read_zones(zones_path)
    rows = []
    for zone in zones:
        roi_tracks = []
        for track_id, track_rows in tracks.items():
            inside = [
                row
                for row in track_rows
                if point_in_polygon(row["anchor_x"], row["anchor_y"], zone["polygon"])
            ]
            if not inside:
                continue
            class_counts: dict[str, int] = defaultdict(int)
            kind_counts: dict[str, int] = defaultdict(int)
            for row in inside:
                class_counts[row["class_name"]] += 1
                kind_counts[row["class_kind"]] += 1
            class_name = max(class_counts.items(), key=lambda item: item[1])[0]
            class_kind = max(kind_counts.items(), key=lambda item: item[1])[0]
            roi_tracks.append(
                {
                    "track_id": track_id,
                    "class_name": class_name,
                    "class_kind": class_kind,
                }
            )
        rows.append(
            {
                "source_video": source_video,
                "roi_id": zone["id"],
                "roi_name": zone.get("name", zone["id"]),
                "total_entries": len(roi_tracks),
                "pedestrian_entries": sum(1 for item in roi_tracks if item["class_kind"] == "pedestrian"),
                "vehicle_entries": sum(1 for item in roi_tracks if item["class_kind"] == "vehicle"),
                "other_entries": sum(1 for item in roi_tracks if item["class_kind"] == "other"),
            }
        )
    return rows


def read_ttc_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def safe_rate(numerator: float, denominator: float, multiplier: float) -> float:
    return round(numerator / denominator * multiplier, 3) if denominator else 0.0


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_tables(events: list[dict], entry_rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    entries_by_roi: dict[str, dict] = {}
    entry_by_video_roi: dict[tuple[str, str], dict] = {}
    for row in entry_rows:
        key = row["roi_id"]
        aggregate = entries_by_roi.setdefault(
            key,
            {
                "roi_id": row["roi_id"],
                "roi_name": row["roi_name"],
                "total_entries": 0,
                "pedestrian_entries": 0,
                "vehicle_entries": 0,
                "other_entries": 0,
            },
        )
        for field in ["total_entries", "pedestrian_entries", "vehicle_entries", "other_entries"]:
            aggregate[field] += int(row[field])
        entry_by_video_roi[(row["source_video"], row["roi_id"])] = row

    event_by_roi: dict[str, list[dict]] = defaultdict(list)
    event_by_video_roi: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        event_by_roi[event["roi_id"]].append(event)
        event_by_video_roi[(event["source_video"], event["roi_id"])].append(event)

    normalized_rows = []
    for roi_id, entry in entries_by_roi.items():
        items = event_by_roi.get(roi_id, [])
        critical = [item for item in items if item.get("critical_event") == "true"]
        final = [item for item in items if item.get("event_scope") == "final"]
        ped_vehicle_critical = [
            item for item in critical if item.get("conflict_type") == "pedestrian_vehicle"
        ]
        veh_vehicle_critical = [
            item for item in critical if item.get("conflict_type") == "vehicle_vehicle"
        ]
        total_risk_sum = sum(parse_float(item.get("total_risk_score", "")) for item in items)
        critical_risk_sum = sum(parse_float(item.get("total_risk_score", "")) for item in critical)
        total_entries = entry["total_entries"]
        pedestrian_entries = entry["pedestrian_entries"]
        vehicle_entries = entry["vehicle_entries"]
        opportunity = pedestrian_entries * vehicle_entries
        normalized_rows.append(
            {
                "roi_id": roi_id,
                "roi_name": entry["roi_name"],
                "total_entries": total_entries,
                "pedestrian_entries": pedestrian_entries,
                "vehicle_entries": vehicle_entries,
                "old_final_event_count": len(final),
                "critical_event_count": len(critical),
                "ped_vehicle_critical_events": len(ped_vehicle_critical),
                "veh_vehicle_critical_events": len(veh_vehicle_critical),
                "total_risk_score_sum": round(total_risk_sum, 3),
                "critical_risk_score_sum": round(critical_risk_sum, 3),
                "critical_events_per_1000_entries": safe_rate(len(critical), total_entries, 1000),
                "risk_score_per_1000_entries": safe_rate(total_risk_sum, total_entries, 1000),
                "critical_risk_score_per_1000_entries": safe_rate(
                    critical_risk_sum, total_entries, 1000
                ),
                "ped_vehicle_critical_per_1000_ped_entries": safe_rate(
                    len(ped_vehicle_critical), pedestrian_entries, 1000
                ),
                "veh_vehicle_critical_per_1000_vehicle_entries": safe_rate(
                    len(veh_vehicle_critical), vehicle_entries, 1000
                ),
                "conflict_opportunity_critical_per_100k": safe_rate(
                    len(ped_vehicle_critical), opportunity, 100000
                ),
            }
        )
    normalized_rows.sort(key=lambda row: row["critical_risk_score_per_1000_entries"], reverse=True)

    by_video_rows = []
    for key, entry in sorted(entry_by_video_roi.items()):
        items = event_by_video_roi.get(key, [])
        critical = [item for item in items if item.get("critical_event") == "true"]
        risk_sum = sum(parse_float(item.get("total_risk_score", "")) for item in items)
        by_video_rows.append(
            {
                "source_video": key[0],
                "roi_id": key[1],
                "roi_name": entry["roi_name"],
                "total_entries": entry["total_entries"],
                "pedestrian_entries": entry["pedestrian_entries"],
                "vehicle_entries": entry["vehicle_entries"],
                "event_count": len(items),
                "critical_event_count": len(critical),
                "total_risk_score_sum": round(risk_sum, 3),
                "critical_events_per_1000_entries": safe_rate(
                    len(critical), int(entry["total_entries"]), 1000
                ),
                "risk_score_per_1000_entries": safe_rate(
                    risk_sum, int(entry["total_entries"]), 1000
                ),
            }
        )

    return normalized_rows, by_video_rows, entry_rows


def write_report(path: Path, normalized_rows: list[dict], events: list[dict]) -> None:
    total_events = len(events)
    old_final = sum(1 for item in events if item.get("event_scope") == "final")
    critical = sum(1 for item in events if item.get("critical_event") == "true")
    lines = [
        "# Step10 PET+TTC Risk Analysis Summary",
        "",
        "## Scope",
        "",
        "- Source videos: DJI_0481 through DJI_0488, step10 detection outputs.",
        "- PET events combined across 8 videos.",
        "- TTC is an image-plane approximation from tracked pixel anchor points.",
        "- Total Risk Score uses normalized PET and TTC components.",
        "",
        "## Risk Formula",
        "",
        "`PET_component = max(0, (1.5 - PET_sec) / 1.5)`",
        "",
        "`TTC_component = max(0, (3.0 - TTC_sec) / 3.0)`",
        "",
        "`Total Risk Score = 100 * (0.6 * PET_component + 0.4 * TTC_component)`",
        "",
        "Critical event rule: `Total Risk Score >= 60`, `approaching == true`, and `TTC_sec <= 3.0`.",
        "",
        "## Event Counts",
        "",
        f"- Total PET events: {total_events}",
        f"- Previous PET-only final events: {old_final}",
        f"- PET+TTC critical events: {critical}",
        "",
        "## ROI-Normalized Risk",
        "",
        "Primary ranking uses `critical_risk_score_per_1000_entries`, which normalizes TTC-adjusted critical risk by ROI traffic exposure.",
        "",
        "| Rank | ROI | Entries | Critical Events | Critical / 1000 Entries | Critical Risk / 1000 Entries |",
        "| ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for index, row in enumerate(normalized_rows, start=1):
        lines.append(
            f"| {index} | {row['roi_id']} | {row['total_entries']} | "
            f"{row['critical_event_count']} | {row['critical_events_per_1000_entries']} | "
            f"{row['critical_risk_score_per_1000_entries']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Notes",
            "",
            "- Raw event counts identify where conflicts were frequent.",
            "- Normalized rates identify where conflicts were frequent relative to observed exposure.",
            "- `risk_score_per_1000_entries` includes all PET events; `critical_risk_score_per_1000_entries` focuses on TTC-supported critical events.",
            "- Pixel-based TTC should be interpreted as a comparative surrogate, not a calibrated physical TTC in meters.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    output_dir = resolve(args.output_dir)
    events = read_ttc_events(resolve(args.ttc_events))
    entry_rows = []
    sources = []
    for pair in args.pairs:
        source_video, tracks_path, zones_path = parse_pair(pair)
        if not tracks_path.exists():
            raise FileNotFoundError(tracks_path)
        if not zones_path.exists():
            raise FileNotFoundError(zones_path)
        entry_rows.extend(count_entries(source_video, tracks_path, zones_path))
        sources.append({"source_video": source_video, "tracks": str(tracks_path), "zones": str(zones_path)})

    normalized_rows, by_video_rows, raw_entry_rows = build_tables(events, entry_rows)
    write_csv(
        output_dir / "roi_normalized_risk_table.csv",
        normalized_rows,
        [
            "roi_id",
            "roi_name",
            "total_entries",
            "pedestrian_entries",
            "vehicle_entries",
            "old_final_event_count",
            "critical_event_count",
            "ped_vehicle_critical_events",
            "veh_vehicle_critical_events",
            "total_risk_score_sum",
            "critical_risk_score_sum",
            "critical_events_per_1000_entries",
            "risk_score_per_1000_entries",
            "critical_risk_score_per_1000_entries",
            "ped_vehicle_critical_per_1000_ped_entries",
            "veh_vehicle_critical_per_1000_vehicle_entries",
            "conflict_opportunity_critical_per_100k",
        ],
    )
    write_csv(
        output_dir / "roi_exposure_by_video.csv",
        by_video_rows,
        [
            "source_video",
            "roi_id",
            "roi_name",
            "total_entries",
            "pedestrian_entries",
            "vehicle_entries",
            "event_count",
            "critical_event_count",
            "total_risk_score_sum",
            "critical_events_per_1000_entries",
            "risk_score_per_1000_entries",
        ],
    )
    write_csv(
        output_dir / "roi_entry_counts_raw.csv",
        raw_entry_rows,
        [
            "source_video",
            "roi_id",
            "roi_name",
            "total_entries",
            "pedestrian_entries",
            "vehicle_entries",
            "other_entries",
        ],
    )
    write_report(output_dir / "step10_pet_ttc_risk_report.md", normalized_rows, events)
    (output_dir / "roi_normalized_metadata.json").write_text(
        json.dumps(
            {
                "entry_definition": "unique filtered track entering each ROI polygon at least once",
                "normalization_primary": "critical_risk_score_per_1000_entries",
                "sources": sources,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Saved normalized ROI outputs: {output_dir}")
    print("Top ROI:", normalized_rows[0]["roi_id"] if normalized_rows else "none")


if __name__ == "__main__":
    main()
