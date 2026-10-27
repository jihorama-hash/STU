from __future__ import annotations

from _paths import BASE

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


BASE_DIR = BASE
DEFAULT_OUTPUT_DIR = BASE_DIR / "runs" / "combined_6videos_final"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine final PET events and create normalized average heatmap."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--background-video", type=Path, default=BASE_DIR / "record" / "DJI_0481.MP4")
    parser.add_argument("--cell-size", type=int, default=160)
    parser.add_argument("--radius", type=int, default=120)
    parser.add_argument("--alpha", type=float, default=0.55)
    parser.add_argument("--mask-threshold", type=int, default=4)
    parser.add_argument("event_files", nargs="+", type=Path)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else BASE_DIR / path


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_events(path: Path, video_id: str) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            risk = parse_float(row.get("risk_score", ""))
            if row.get("event_scope") != "final" or risk <= 0:
                continue
            out = dict(row)
            out["source_video"] = video_id
            out["source_event_id"] = row.get("event_id", "")
            out["risk_score"] = risk
            out["pet_sec"] = parse_float(row.get("pet_sec", ""))
            out["event_x"] = parse_float(row.get("event_x", ""))
            out["event_y"] = parse_float(row.get("event_y", ""))
            rows.append(out)
    return rows


def read_background(path: Path) -> np.ndarray:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open background video: {path}")
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read background frame: {path}")
    return frame


def add_heat(heat: np.ndarray, x: float, y: float, value: float, radius: int) -> None:
    height, width = heat.shape
    cx = int(round(x))
    cy = int(round(y))
    x1 = max(0, cx - radius)
    y1 = max(0, cy - radius)
    x2 = min(width, cx + radius + 1)
    y2 = min(height, cy + radius + 1)
    if x1 >= x2 or y1 >= y2:
        return
    yy, xx = np.ogrid[y1:y2, x1:x2]
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    sigma2 = (radius / 2.0) ** 2
    kernel = np.exp(-dist2 / (2.0 * sigma2)) * value
    heat[y1:y2, x1:x2] += np.where(dist2 <= radius**2, kernel, 0.0)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def summarize_roi(events: list[dict], video_count: int) -> list[dict]:
    grouped = defaultdict(list)
    for event in events:
        grouped[event["roi_id"]].append(event)
    rows = []
    for roi_id, items in sorted(grouped.items()):
        risks = [float(item["risk_score"]) for item in items]
        pets = [float(item["pet_sec"]) for item in items]
        rows.append(
            {
                "roi_id": roi_id,
                "roi_name": items[0].get("roi_name", roi_id),
                "source_video_count": len({item["source_video"] for item in items}),
                "event_count": len(items),
                "event_count_avg_per_video": round(len(items) / video_count, 3),
                "risk_score_sum": round(sum(risks), 3),
                "risk_score_avg_per_video": round(sum(risks) / video_count, 3),
                "risk_score_max": round(max(risks), 3),
                "risk_score_avg_event": round(sum(risks) / len(risks), 3),
                "avg_pet_sec": round(sum(pets) / len(pets), 3),
                "min_pet_sec": round(min(pets), 3),
                "vehicle_vehicle_events": sum(
                    1 for item in items if item.get("conflict_type") == "vehicle_vehicle"
                ),
                "pedestrian_vehicle_events": sum(
                    1 for item in items if item.get("conflict_type") == "pedestrian_vehicle"
                ),
            }
        )
    rows.sort(key=lambda item: item["risk_score_avg_per_video"], reverse=True)
    return rows


def summarize_cells(events: list[dict], cell_size: int, video_count: int) -> list[dict]:
    grouped = defaultdict(list)
    for event in events:
        grouped[(int(event["event_x"] // cell_size), int(event["event_y"] // cell_size))].append(event)
    rows = []
    for (cell_x, cell_y), items in sorted(grouped.items()):
        risks = [float(item["risk_score"]) for item in items]
        pets = [float(item["pet_sec"]) for item in items]
        rows.append(
            {
                "cell_x": cell_x,
                "cell_y": cell_y,
                "x1": cell_x * cell_size,
                "y1": cell_y * cell_size,
                "x2": (cell_x + 1) * cell_size,
                "y2": (cell_y + 1) * cell_size,
                "source_video_count": len({item["source_video"] for item in items}),
                "event_count": len(items),
                "event_count_avg_per_video": round(len(items) / video_count, 3),
                "risk_score_sum": round(sum(risks), 3),
                "risk_score_avg_per_video": round(sum(risks) / video_count, 3),
                "risk_score_max": round(max(risks), 3),
                "risk_score_avg_event": round(sum(risks) / len(risks), 3),
                "avg_pet_sec": round(sum(pets) / len(pets), 3),
            }
        )
    rows.sort(key=lambda item: item["risk_score_avg_per_video"], reverse=True)
    return rows


def main() -> None:
    args = parse_args()
    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_files = [resolve(path) for path in args.event_files]

    all_events = []
    source_files = []
    for path in event_files:
        if not path.exists():
            raise FileNotFoundError(f"Missing event file: {path}")
        video_id = path.parts[-3] if len(path.parts) >= 3 else path.stem
        events = read_events(path, video_id)
        all_events.extend(events)
        source_files.append({"video_id": video_id, "path": str(path), "final_events": len(events)})

    video_count = len(event_files)
    event_fields = [
        "source_video",
        "source_event_id",
        "roi_id",
        "roi_name",
        "first_track_id",
        "first_class_name",
        "first_class_kind",
        "first_exit_sec",
        "second_track_id",
        "second_class_name",
        "second_class_kind",
        "second_entry_sec",
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
    write_csv(output_dir / "combined_pet_events_final.csv", all_events, event_fields)
    write_csv(
        output_dir / "combined_pet_risk_by_roi_normalized.csv",
        summarize_roi(all_events, video_count),
        [
            "roi_id",
            "roi_name",
            "source_video_count",
            "event_count",
            "event_count_avg_per_video",
            "risk_score_sum",
            "risk_score_avg_per_video",
            "risk_score_max",
            "risk_score_avg_event",
            "avg_pet_sec",
            "min_pet_sec",
            "vehicle_vehicle_events",
            "pedestrian_vehicle_events",
        ],
    )
    write_csv(
        output_dir / "combined_pet_heatmap_cells_normalized.csv",
        summarize_cells(all_events, args.cell_size, video_count),
        [
            "cell_x",
            "cell_y",
            "x1",
            "y1",
            "x2",
            "y2",
            "source_video_count",
            "event_count",
            "event_count_avg_per_video",
            "risk_score_sum",
            "risk_score_avg_per_video",
            "risk_score_max",
            "risk_score_avg_event",
            "avg_pet_sec",
        ],
    )

    background = read_background(resolve(args.background_video))
    heat = np.zeros(background.shape[:2], dtype=np.float32)
    for event in all_events:
        add_heat(
            heat,
            float(event["event_x"]),
            float(event["event_y"]),
            float(event["risk_score"]) / video_count,
            args.radius,
        )

    if heat.max() > 0:
        heat_norm = np.clip(heat / heat.max() * 255.0, 0, 255).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
        mask = heat_norm >= max(1, args.mask_threshold)
        blended = cv2.addWeighted(background, 1.0 - args.alpha, heat_color, args.alpha, 0)
        overlay = background.copy()
        overlay[mask] = blended[mask]
    else:
        overlay = background.copy()

    for event in all_events:
        cv2.circle(
            overlay,
            (int(round(float(event["event_x"]))), int(round(float(event["event_y"])))),
            8,
            (255, 255, 255),
            -1,
        )
        cv2.circle(
            overlay,
            (int(round(float(event["event_x"]))), int(round(float(event["event_y"])))),
            11,
            (0, 0, 0),
            2,
        )

    heatmap_path = output_dir / "combined_pet_heatmap_normalized.png"
    cv2.imwrite(str(heatmap_path), overlay)
    (output_dir / "combined_metadata.json").write_text(
        json.dumps(
            {
                "source_files": source_files,
                "video_count": video_count,
                "event_count": len(all_events),
                "normalization": "risk_score divided by number of included event files",
                "background_video": str(resolve(args.background_video)),
                "cell_size": args.cell_size,
                "radius": args.radius,
                "alpha": args.alpha,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Combined final events: {len(all_events)}")
    print(f"Saved: {heatmap_path}")


if __name__ == "__main__":
    main()
