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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine step10 PET event CSVs and make heatmaps.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--background-video", type=Path, default=BASE_DIR / "record" / "DJI_0481.MP4")
    parser.add_argument("--cell-size", type=int, default=160)
    parser.add_argument("--radius", type=int, default=120)
    parser.add_argument("--alpha", type=float, default=0.55)
    parser.add_argument("--mask-threshold", type=int, default=4)
    parser.add_argument("event_files", nargs="+", type=Path)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else BASE_DIR / path


def parse_float(value: str | int | float | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def source_video_from_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("DJI_") and "sahi_step10" in part:
            return part.replace("_sahi_step10", "")
    return path.parent.parent.name


def read_events(path: Path) -> list[dict]:
    source_video = source_video_from_path(path)
    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            out = dict(row)
            out["source_video"] = source_video
            out["source_file"] = str(path)
            out["source_event_id"] = row.get("event_id", "")
            out["risk_score"] = parse_float(row.get("risk_score", ""))
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


def summarize_by_video(events: list[dict]) -> list[dict]:
    rows = []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["source_video"]].append(event)
    for source_video, items in sorted(grouped.items()):
        final_count = sum(1 for item in items if item.get("event_scope") == "final")
        reference_count = sum(1 for item in items if item.get("event_scope") == "reference")
        rows.append(
            {
                "source_video": source_video,
                "event_count": len(items),
                "final_event_count": final_count,
                "reference_event_count": reference_count,
                "risk_score_sum": round(sum(float(item["risk_score"]) for item in items), 3),
                "min_pet_sec": round(min(float(item["pet_sec"]) for item in items), 3) if items else "",
                "avg_pet_sec": round(sum(float(item["pet_sec"]) for item in items) / len(items), 3)
                if items
                else "",
            }
        )
    return rows


def summarize_by_roi(events: list[dict]) -> list[dict]:
    rows = []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event.get("roi_id", "")].append(event)
    for roi_id, items in sorted(grouped.items()):
        rows.append(
            {
                "roi_id": roi_id,
                "roi_name": items[0].get("roi_name", roi_id),
                "source_video_count": len({item["source_video"] for item in items}),
                "event_count": len(items),
                "final_event_count": sum(1 for item in items if item.get("event_scope") == "final"),
                "reference_event_count": sum(
                    1 for item in items if item.get("event_scope") == "reference"
                ),
                "risk_score_sum": round(sum(float(item["risk_score"]) for item in items), 3),
                "risk_score_max": round(max(float(item["risk_score"]) for item in items), 3),
                "avg_pet_sec": round(sum(float(item["pet_sec"]) for item in items) / len(items), 3),
                "min_pet_sec": round(min(float(item["pet_sec"]) for item in items), 3),
            }
        )
    rows.sort(key=lambda item: item["risk_score_sum"], reverse=True)
    return rows


def summarize_cells(events: list[dict], cell_size: int) -> list[dict]:
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for event in events:
        grouped[(int(float(event["event_x"]) // cell_size), int(float(event["event_y"]) // cell_size))].append(
            event
        )
    rows = []
    for (cell_x, cell_y), items in sorted(grouped.items()):
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
                "final_event_count": sum(1 for item in items if item.get("event_scope") == "final"),
                "reference_event_count": sum(
                    1 for item in items if item.get("event_scope") == "reference"
                ),
                "risk_score_sum": round(sum(float(item["risk_score"]) for item in items), 3),
                "risk_score_max": round(max(float(item["risk_score"]) for item in items), 3),
                "avg_pet_sec": round(sum(float(item["pet_sec"]) for item in items) / len(items), 3),
            }
        )
    rows.sort(key=lambda item: item["risk_score_sum"], reverse=True)
    return rows


def draw_heatmap(
    background: np.ndarray,
    events: list[dict],
    output_path: Path,
    radius: int,
    alpha: float,
    mask_threshold: int,
) -> None:
    heat = np.zeros(background.shape[:2], dtype=np.float32)
    for event in events:
        value = max(float(event["risk_score"]), 0.01)
        add_heat(heat, float(event["event_x"]), float(event["event_y"]), value, radius)

    if heat.max() > 0:
        heat_norm = np.clip(heat / heat.max() * 255.0, 0, 255).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
        mask = heat_norm >= max(1, mask_threshold)
        blended = cv2.addWeighted(background, 1.0 - alpha, heat_color, alpha, 0)
        overlay = background.copy()
        overlay[mask] = blended[mask]
    else:
        overlay = background.copy()

    for event in events:
        x = int(round(float(event["event_x"])))
        y = int(round(float(event["event_y"])))
        color = (255, 255, 255) if event.get("event_scope") == "final" else (180, 180, 180)
        cv2.circle(overlay, (x, y), 8, color, -1, lineType=cv2.LINE_AA)
        cv2.circle(overlay, (x, y), 11, (0, 0, 0), 2, lineType=cv2.LINE_AA)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), overlay):
        raise RuntimeError(f"Could not write heatmap: {output_path}")


def main() -> None:
    args = parse_args()
    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_files = [resolve(path) for path in args.event_files]

    all_events: list[dict] = []
    source_files = []
    for path in event_files:
        if not path.exists():
            raise FileNotFoundError(f"Missing event file: {path}")
        events = read_events(path)
        all_events.extend(events)
        source_files.append(
            {
                "source_video": source_video_from_path(path),
                "path": str(path),
                "events": len(events),
                "final_events": sum(1 for event in events if event.get("event_scope") == "final"),
                "reference_events": sum(1 for event in events if event.get("event_scope") == "reference"),
            }
        )

    if not all_events:
        raise RuntimeError("No events found.")

    fieldnames = [
        "source_video",
        "source_file",
        "source_event_id",
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
    final_events = [event for event in all_events if event.get("event_scope") == "final"]

    write_csv(output_dir / "combined_step10_pet_events_all.csv", all_events, fieldnames)
    write_csv(output_dir / "combined_step10_pet_events_final.csv", final_events, fieldnames)
    write_csv(
        output_dir / "combined_step10_summary_by_video.csv",
        summarize_by_video(all_events),
        ["source_video", "event_count", "final_event_count", "reference_event_count", "risk_score_sum", "min_pet_sec", "avg_pet_sec"],
    )
    write_csv(
        output_dir / "combined_step10_summary_by_roi.csv",
        summarize_by_roi(all_events),
        [
            "roi_id",
            "roi_name",
            "source_video_count",
            "event_count",
            "final_event_count",
            "reference_event_count",
            "risk_score_sum",
            "risk_score_max",
            "avg_pet_sec",
            "min_pet_sec",
        ],
    )
    write_csv(
        output_dir / "combined_step10_heatmap_cells_all.csv",
        summarize_cells(all_events, args.cell_size),
        [
            "cell_x",
            "cell_y",
            "x1",
            "y1",
            "x2",
            "y2",
            "source_video_count",
            "event_count",
            "final_event_count",
            "reference_event_count",
            "risk_score_sum",
            "risk_score_max",
            "avg_pet_sec",
        ],
    )

    background = read_background(resolve(args.background_video))
    draw_heatmap(
        background,
        all_events,
        output_dir / "combined_step10_pet_heatmap_all_events.png",
        args.radius,
        args.alpha,
        args.mask_threshold,
    )
    draw_heatmap(
        background,
        final_events,
        output_dir / "combined_step10_pet_heatmap_final_events.png",
        args.radius,
        args.alpha,
        args.mask_threshold,
    )
    (output_dir / "combined_step10_metadata.json").write_text(
        json.dumps(
            {
                "source_files": source_files,
                "video_count": len(event_files),
                "event_count": len(all_events),
                "final_event_count": len(final_events),
                "reference_event_count": len(all_events) - len(final_events),
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
    print(f"Combined videos: {len(event_files)}")
    print(f"Combined all events: {len(all_events)}")
    print(f"Combined final events: {len(final_events)}")
    print(f"Saved output dir: {output_dir}")


if __name__ == "__main__":
    main()
