from __future__ import annotations

from _paths import BASE

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


DEFAULT_EVENTS = BASE / "runs" / "DJI_0481_sahi_step10" / "pet_events.csv"
DEFAULT_VIDEO = BASE / "record" / "DJI_0481.MP4"
DEFAULT_OUTPUT = BASE / "runs" / "DJI_0481_sahi_step10" / "pet_heatmap.png"
DEFAULT_CELLS = BASE / "runs" / "DJI_0481_sahi_step10" / "pet_heatmap_cells.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create PET risk heatmap overlay.")
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cells-output", type=Path, default=DEFAULT_CELLS)
    parser.add_argument("--background-frame", type=int, default=0)
    parser.add_argument("--pet-threshold-sec", type=float, default=5.0)
    parser.add_argument(
        "--include-reference",
        action="store_true",
        help="Include reference PET events in the heatmap if they have positive risk_score.",
    )
    parser.add_argument("--radius", type=int, default=120)
    parser.add_argument("--alpha", type=float, default=0.55)
    parser.add_argument("--cell-size", type=int, default=160)
    parser.add_argument(
        "--mask-threshold",
        type=int,
        default=4,
        help="Minimum normalized heat value to draw. Higher values trim faint heat edges.",
    )
    return parser.parse_args()


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_background(video_path: Path, frame_id: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame {frame_id} from {video_path}")
    return frame


def read_events(path: Path, threshold: float, include_reference: bool) -> list[dict]:
    events = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            pet_sec = parse_float(row.get("pet_sec", ""))
            x = parse_float(row.get("event_x", ""))
            y = parse_float(row.get("event_y", ""))
            if pet_sec > threshold:
                continue
            event_scope = row.get("event_scope", "final")
            if event_scope == "reference" and not include_reference:
                continue
            if "risk_score" in row:
                risk_score = parse_float(row.get("risk_score", ""))
            else:
                risk_score = max(0.0, threshold - pet_sec)
            if risk_score <= 0:
                continue
            events.append(
                {
                    "event_id": row.get("event_id", ""),
                    "pet_sec": pet_sec,
                    "event_scope": event_scope,
                    "conflict_type": row.get("conflict_type", ""),
                    "risk_score": risk_score,
                    "risk_level": row.get("risk_level", ""),
                    "event_x": x,
                    "event_y": y,
                    "severity": row.get("severity", ""),
                }
            )
    return events


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
    circle = dist2 <= radius**2
    kernel = np.exp(-dist2 / (2.0 * sigma2)) * value
    heat[y1:y2, x1:x2] += np.where(circle, kernel, 0.0)


def write_cells(path: Path, events: list[dict], cell_size: int) -> None:
    cells = defaultdict(
        lambda: {
            "count": 0,
            "vehicle_vehicle_events": 0,
            "pedestrian_vehicle_events": 0,
            "risk_sum": 0.0,
            "risk_max": 0.0,
            "pet_sum": 0.0,
        }
    )
    for event in events:
        cell_x = int(event["event_x"] // cell_size)
        cell_y = int(event["event_y"] // cell_size)
        risk = event["risk_score"]
        cell = cells[(cell_x, cell_y)]
        cell["count"] += 1
        if event["conflict_type"] == "vehicle_vehicle":
            cell["vehicle_vehicle_events"] += 1
        elif event["conflict_type"] == "pedestrian_vehicle":
            cell["pedestrian_vehicle_events"] += 1
        cell["risk_sum"] += risk
        cell["risk_max"] = max(cell["risk_max"], risk)
        cell["pet_sum"] += event["pet_sec"]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = [
            "cell_x",
            "cell_y",
            "x1",
            "y1",
            "x2",
            "y2",
            "event_count",
            "vehicle_vehicle_events",
            "pedestrian_vehicle_events",
            "risk_score_sum",
            "risk_score_max",
            "risk_score_avg",
            "avg_pet_sec",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for (cell_x, cell_y), values in sorted(cells.items()):
            writer.writerow(
                {
                    "cell_x": cell_x,
                    "cell_y": cell_y,
                    "x1": cell_x * cell_size,
                    "y1": cell_y * cell_size,
                    "x2": (cell_x + 1) * cell_size,
                    "y2": (cell_y + 1) * cell_size,
                    "event_count": values["count"],
                    "vehicle_vehicle_events": values["vehicle_vehicle_events"],
                    "pedestrian_vehicle_events": values["pedestrian_vehicle_events"],
                    "risk_score_sum": round(values["risk_sum"], 3),
                    "risk_score_max": round(values["risk_max"], 3),
                    "risk_score_avg": round(values["risk_sum"] / values["count"], 3),
                    "avg_pet_sec": round(values["pet_sum"] / values["count"], 3),
                }
            )


def main() -> None:
    args = parse_args()
    background = read_background(args.video, args.background_frame)
    events = read_events(args.events, args.pet_threshold_sec, args.include_reference)
    heat = np.zeros(background.shape[:2], dtype=np.float32)

    for event in events:
        add_heat(heat, event["event_x"], event["event_y"], event["risk_score"], args.radius)

    if heat.max() > 0:
        heat_norm = np.clip(heat / heat.max() * 255.0, 0, 255).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
        mask = heat_norm >= max(1, args.mask_threshold)
        overlay = background.copy()
        blended = cv2.addWeighted(background, 1.0 - args.alpha, heat_color, args.alpha, 0)
        overlay[mask] = blended[mask]
    else:
        overlay = background.copy()

    for event in events:
        x = int(round(event["event_x"]))
        y = int(round(event["event_y"]))
        cv2.circle(overlay, (x, y), 8, (255, 255, 255), -1)
        cv2.circle(overlay, (x, y), 11, (0, 0, 0), 2)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), overlay)
    write_cells(args.cells_output, events, args.cell_size)

    print(f"Events used: {len(events)}")
    print(f"Saved heatmap: {args.output}")
    print(f"Saved cells: {args.cells_output}")


if __name__ == "__main__":
    main()
