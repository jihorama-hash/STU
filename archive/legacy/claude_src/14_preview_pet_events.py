from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Draw PET event points on a video frame.")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zones", type=Path, default=None)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--include-reference", action="store_true")
    return parser.parse_args()


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_frame(video_path: Path, frame_id: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame {frame_id}: {video_path}")
    return frame


def read_events(path: Path, include_reference: bool) -> list[dict]:
    events = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row.get("event_scope") == "reference" and not include_reference:
                continue
            events.append(
                {
                    "event_id": row.get("event_id", ""),
                    "roi_id": row.get("roi_id", ""),
                    "pet_sec": parse_float(row.get("pet_sec", "")),
                    "risk_score": parse_float(row.get("risk_score", "")),
                    "risk_level": row.get("risk_level", ""),
                    "event_scope": row.get("event_scope", ""),
                    "conflict_type": row.get("conflict_type", ""),
                    "x": parse_float(row.get("event_x", "")),
                    "y": parse_float(row.get("event_y", "")),
                }
            )
    return events


def draw_zones(frame: np.ndarray, zones_path: Path) -> None:
    with zones_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    overlay = frame.copy()
    colors = [
        (0, 128, 255),
        (0, 200, 0),
        (255, 80, 80),
        (255, 0, 255),
        (0, 255, 255),
    ]
    for index, zone in enumerate(data.get("zones", [])):
        color = colors[index % len(colors)]
        pts = np.array(zone["polygon"], dtype=np.int32)
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=4, lineType=cv2.LINE_AA)
        label_xy = tuple(pts.mean(axis=0).astype(int))
        cv2.putText(
            frame,
            zone["id"],
            label_xy,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
            cv2.LINE_AA,
        )
    cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, dst=frame)


def color_for_event(event: dict) -> tuple[int, int, int]:
    if event["risk_level"] == "high":
        return (0, 0, 255)
    if event["risk_level"] == "medium":
        return (0, 165, 255)
    if event["risk_level"] == "low":
        return (0, 255, 255)
    return (180, 180, 180)


def draw_events(frame: np.ndarray, events: list[dict]) -> None:
    for event in sorted(events, key=lambda item: item["risk_score"]):
        x = int(round(event["x"]))
        y = int(round(event["y"]))
        color = color_for_event(event)
        radius = 11 if event["event_scope"] == "final" else 8
        cv2.circle(frame, (x, y), radius + 4, (0, 0, 0), -1, lineType=cv2.LINE_AA)
        cv2.circle(frame, (x, y), radius, color, -1, lineType=cv2.LINE_AA)
        cv2.circle(frame, (x, y), radius + 2, (255, 255, 255), 2, lineType=cv2.LINE_AA)

    for event in events:
        x = int(round(event["x"]))
        y = int(round(event["y"]))
        label = f"#{event['event_id']} PET {event['pet_sec']:.3g}s"
        (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        label_x = min(max(0, x + 14), frame.shape[1] - text_w - 12)
        label_y = min(max(text_h + 12, y - 12), frame.shape[0] - baseline - 8)
        cv2.rectangle(
            frame,
            (label_x - 6, label_y - text_h - baseline - 6),
            (label_x + text_w + 6, label_y + baseline + 6),
            (0, 0, 0),
            -1,
        )
        cv2.putText(
            frame,
            label,
            (label_x, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )


def draw_header(frame: np.ndarray, events: list[dict], source: Path) -> None:
    final_count = sum(1 for event in events if event["event_scope"] == "final")
    reference_count = len(events) - final_count
    text = f"{source.name} | events: {len(events)} | final: {final_count} | reference: {reference_count}"
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 64), (0, 0, 0), -1)
    cv2.putText(
        frame,
        text,
        (28, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def main() -> None:
    args = parse_args()
    frame = read_frame(args.video, args.frame)
    if args.zones is not None:
        draw_zones(frame, args.zones)
    events = read_events(args.events, args.include_reference)
    draw_events(frame, events)
    draw_header(frame, events, args.events)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), frame):
        raise RuntimeError(f"Could not write preview: {args.output}")
    print(f"Events drawn: {len(events)}")
    print(f"Preview saved: {args.output}")


if __name__ == "__main__":
    main()
