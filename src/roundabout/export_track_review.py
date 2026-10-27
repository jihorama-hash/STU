"""Export deterministic track samples for human continuity review."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from .paths import resolve_project_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--minimum-duration", type=float, default=0.5)
    parser.add_argument("--person-samples", type=int, default=20)
    parser.add_argument("--vehicle-samples", type=int, default=10)
    args = parser.parse_args()

    video_path = resolve_project_path(args.video)
    tracks_path = resolve_project_path(args.tracks)
    output_dir = resolve_project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tracks: dict[int, list[dict[str, str]]] = defaultdict(list)
    with tracks_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            tracks[int(row["track_id"])].append(row)

    eligible: list[tuple[int, str, float]] = []
    for track_id, rows in tracks.items():
        rows.sort(key=lambda row: int(row["frame_index"]))
        duration = (
            float(rows[-1]["timestamp_seconds"]) - float(rows[0]["timestamp_seconds"])
        )
        if duration >= args.minimum_duration:
            eligible.append((track_id, rows[0]["object_class"], duration))

    def evenly_select(items: list[tuple[int, str, float]], count: int) -> list[int]:
        ordered = sorted(items, key=lambda item: (item[2], item[0]))
        if len(ordered) <= count:
            return [item[0] for item in ordered]
        indices = np.linspace(0, len(ordered) - 1, count).round().astype(int)
        return [ordered[index][0] for index in indices]

    person_ids = evenly_select(
        [item for item in eligible if item[1] == "person"], args.person_samples
    )
    vehicle_ids = evenly_select(
        [item for item in eligible if item[1] != "person"], args.vehicle_samples
    )
    selected = person_ids + vehicle_ids

    capture = cv2.VideoCapture(str(video_path))
    manifest_rows: list[dict[str, object]] = []
    for sample_number, track_id in enumerate(selected, start=1):
        rows = tracks[track_id]
        middle = rows[len(rows) // 2]
        frame_index = int(middle["frame_index"])
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Could not read frame {frame_index}")
        points = np.asarray(
            [
                [round(float(row["foot_x"])), round(float(row["foot_y"]))]
                for row in rows
            ],
            dtype=np.int32,
        )
        if len(points) > 1:
            cv2.polylines(frame, [points], False, (0, 255, 255), 5, cv2.LINE_AA)
        x1, y1, x2, y2 = (
            round(float(middle[key])) for key in ("x1", "y1", "x2", "y2")
        )
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 5)
        label = f"{middle['object_class']} #{track_id}"
        cv2.putText(
            frame, label, (x1, max(40, y1 - 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3, cv2.LINE_AA,
        )
        filename = f"sample_{sample_number:02d}_track_{track_id}.jpg"
        cv2.imwrite(
            str(output_dir / filename), frame, [cv2.IMWRITE_JPEG_QUALITY, 90]
        )
        manifest_rows.append({
            "sample_number": sample_number,
            "track_id": track_id,
            "object_class": middle["object_class"],
            "start_seconds": rows[0]["timestamp_seconds"],
            "end_seconds": rows[-1]["timestamp_seconds"],
            "duration_seconds": (
                float(rows[-1]["timestamp_seconds"])
                - float(rows[0]["timestamp_seconds"])
            ),
            "observations": len(rows),
            "image": filename,
            "review_status": "",
            "review_notes": "",
        })
    capture.release()

    with (output_dir / "manifest.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=manifest_rows[0].keys())
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"Exported {len(manifest_rows)} review samples to {output_dir}")


if __name__ == "__main__":
    main()
