from __future__ import annotations

from _paths import BASE

import argparse
import csv
from pathlib import Path


BASE_DIR = BASE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create pedestrian-vehicle ROI risk ranking.")
    parser.add_argument("--ttc-events", type=Path, required=True)
    parser.add_argument("--normalized-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else BASE_DIR / path


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> list[dict]:
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


def main() -> None:
    args = parse_args()
    events = read_csv(resolve(args.ttc_events))
    normalized = read_csv(resolve(args.normalized_table))

    exposure_by_roi = {row["roi_id"]: row for row in normalized}
    grouped: dict[str, list[dict]] = {}
    for event in events:
        if event.get("conflict_type") != "pedestrian_vehicle":
            continue
        grouped.setdefault(event["roi_id"], []).append(event)

    rows = []
    for roi_id, exposure in exposure_by_roi.items():
        items = grouped.get(roi_id, [])
        critical = [item for item in items if item.get("critical_event") == "true"]
        final = [item for item in items if item.get("event_scope") == "final"]
        total_entries = parse_float(exposure.get("total_entries", ""))
        pedestrian_entries = parse_float(exposure.get("pedestrian_entries", ""))
        vehicle_entries = parse_float(exposure.get("vehicle_entries", ""))
        opportunity = pedestrian_entries * vehicle_entries
        total_risk_sum = sum(parse_float(item.get("total_risk_score", "")) for item in items)
        critical_risk_sum = sum(parse_float(item.get("total_risk_score", "")) for item in critical)
        rows.append(
            {
                "roi_id": roi_id,
                "roi_name": exposure.get("roi_name", roi_id),
                "total_entries": int(total_entries),
                "pedestrian_entries": int(pedestrian_entries),
                "vehicle_entries": int(vehicle_entries),
                "ped_vehicle_event_count": len(items),
                "ped_vehicle_final_event_count": len(final),
                "ped_vehicle_critical_event_count": len(critical),
                "ped_vehicle_total_risk_score_sum": round(total_risk_sum, 3),
                "ped_vehicle_critical_risk_score_sum": round(critical_risk_sum, 3),
                "ped_vehicle_critical_per_1000_ped_entries": safe_rate(
                    len(critical), pedestrian_entries, 1000
                ),
                "ped_vehicle_critical_per_1000_vehicle_entries": safe_rate(
                    len(critical), vehicle_entries, 1000
                ),
                "ped_vehicle_critical_risk_per_1000_ped_entries": safe_rate(
                    critical_risk_sum, pedestrian_entries, 1000
                ),
                "ped_vehicle_total_risk_per_1000_ped_entries": safe_rate(
                    total_risk_sum, pedestrian_entries, 1000
                ),
                "ped_vehicle_critical_per_100k_conflict_opportunities": safe_rate(
                    len(critical), opportunity, 100000
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            row["ped_vehicle_critical_risk_per_1000_ped_entries"],
            row["ped_vehicle_critical_per_1000_ped_entries"],
        ),
        reverse=True,
    )

    fieldnames = [
        "roi_id",
        "roi_name",
        "total_entries",
        "pedestrian_entries",
        "vehicle_entries",
        "ped_vehicle_event_count",
        "ped_vehicle_final_event_count",
        "ped_vehicle_critical_event_count",
        "ped_vehicle_total_risk_score_sum",
        "ped_vehicle_critical_risk_score_sum",
        "ped_vehicle_critical_per_1000_ped_entries",
        "ped_vehicle_critical_per_1000_vehicle_entries",
        "ped_vehicle_critical_risk_per_1000_ped_entries",
        "ped_vehicle_total_risk_per_1000_ped_entries",
        "ped_vehicle_critical_per_100k_conflict_opportunities",
    ]
    write_csv(resolve(args.output), rows, fieldnames)

    lines = [
        "# Pedestrian-Vehicle ROI Risk Ranking",
        "",
        "This table ranks ROI risk using only pedestrian-vehicle conflicts.",
        "The primary ranking metric is `ped_vehicle_critical_risk_per_1000_ped_entries`.",
        "",
        "| Rank | ROI | Ped Entries | Vehicle Entries | Critical PV Events | Critical PV / 1000 Ped Entries | Critical PV Risk / 1000 Ped Entries |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"| {index} | {row['roi_id']} | {row['pedestrian_entries']} | "
            f"{row['vehicle_entries']} | {row['ped_vehicle_critical_event_count']} | "
            f"{row['ped_vehicle_critical_per_1000_ped_entries']} | "
            f"{row['ped_vehicle_critical_risk_per_1000_ped_entries']} |"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "",
            "- `pedestrian_entries` counts unique tracked pedestrians entering each ROI polygon.",
            "- `vehicle_entries` counts unique tracked vehicles entering each ROI polygon.",
            "- Critical events use the PET+TTC rule from the combined analysis.",
            "- Roundabout entry ROIs are retained because jaywalking pedestrians were observed there.",
            "",
        ]
    )
    resolve(args.report).parent.mkdir(parents=True, exist_ok=True)
    resolve(args.report).write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved: {resolve(args.output)}")
    print(f"Saved: {resolve(args.report)}")
    print("Top ROI:", rows[0]["roi_id"] if rows else "none")


if __name__ == "__main__":
    main()
