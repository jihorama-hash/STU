"""Export frames for manual review of provisional PET/TTC events."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--zones", required=True)
    parser.add_argument("--homographies", required=True)
    parser.add_argument("--video-id", default="DJI_0482")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    events = json.loads(Path(args.events).read_text(encoding="utf-8"))
    tracks = defaultdict(list)
    with Path(args.tracks).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            tracks[int(row["track_id"])].append(row)
    selected = [
        event for event in events
        if event["pet_seconds"] <= 1.5
        or (
            event["approaching"]
            and event["ttc_seconds"] is not None
            and event["ttc_seconds"] <= 3.0
        )
    ]
    best: dict[tuple[str, int, int], dict] = {}
    for event in selected:
        pair = tuple(sorted((event["first_track_id"], event["second_track_id"])))
        key = (event["roi_id"], *pair)
        current = best.get(key)
        if current is None or event["pet_seconds"] < current["pet_seconds"]:
            best[key] = event
    selected = sorted(best.values(), key=lambda event: event["timestamp_seconds"])

    zones = {
        zone["id"]: zone
        for zone in json.loads(Path(args.zones).read_text(encoding="utf-8"))["zones"]
    }
    homographies = json.loads(Path(args.homographies).read_text(encoding="utf-8"))
    source_to_reference = np.asarray(
        homographies["videos"][args.video_id]["h"], dtype=float
    )
    reference_to_source = np.linalg.inv(source_to_reference)

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(args.video)
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    manifest = []
    panels = []
    for index, event in enumerate(selected, start=1):
        frame_index = round(event["timestamp_seconds"] * fps)
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Could not read frame {frame_index}")
        zone = zones[event["roi_id"]]
        points = np.asarray(zone["polygon"], dtype=np.float32).reshape(1, -1, 2)
        polygon = cv2.perspectiveTransform(points, reference_to_source).round().astype(np.int32)[0]
        cv2.polylines(frame, [polygon], True, (0, 255, 255), 6, cv2.LINE_AA)

        reference_point = np.asarray(
            [[[event["x"], event["y"]]]], dtype=np.float32
        )
        source_point = cv2.perspectiveTransform(reference_point, reference_to_source)[0, 0]
        cv2.circle(frame, tuple(source_point.round().astype(int)), 18, (0, 0, 255), 5)
        for actor_index, track_id in enumerate(
            (event["first_track_id"], event["second_track_id"])
        ):
            actor_rows = tracks[track_id]
            if not actor_rows:
                continue
            actor = min(
                actor_rows,
                key=lambda row: abs(
                    float(row["timestamp_seconds"]) - event["timestamp_seconds"]
                ),
            )
            if abs(float(actor["timestamp_seconds"]) - event["timestamp_seconds"]) > 3.0:
                continue
            x1, y1, x2, y2 = (
                round(float(actor[key])) for key in ("x1", "y1", "x2", "y2")
            )
            color = (0, 255, 0) if actor_index == 0 else (255, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 6)
            cv2.putText(
                frame,
                f"{actor['object_class']} #{track_id}",
                (x1, max(40, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                color,
                3,
                cv2.LINE_AA,
            )
        label = (
            f"{index} t={event['timestamp_seconds']:.2f}s "
            f"tracks={event['first_track_id']}/{event['second_track_id']} "
            f"PET={event['pet_seconds']:.2f}s TTC={event['ttc_seconds']}"
        )
        cv2.putText(
            frame, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX,
            1.1, (0, 255, 255), 4, cv2.LINE_AA
        )
        filename = f"event_{index:02d}_{event['event_id']}.jpg"
        cv2.imwrite(str(output / filename), frame)
        manifest.append({
            "review_number": index,
            **event,
            "image": filename,
            "review_status": "",
            "review_notes": "",
        })
        panel_width = 720
        panels.append(cv2.resize(
            frame,
            (panel_width, round(frame.shape[0] * panel_width / frame.shape[1])),
        ))
    capture.release()

    if manifest:
        with (output / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=manifest[0].keys())
            writer.writeheader()
            writer.writerows(manifest)
        columns = 3
        panel_height = panels[0].shape[0]
        blank = np.zeros((panel_height, panels[0].shape[1], 3), dtype=np.uint8)
        rows = []
        for start in range(0, len(panels), columns):
            group = panels[start:start + columns]
            group += [blank] * (columns - len(group))
            rows.append(cv2.hconcat(group))
        cv2.imwrite(str(output / f"contact_sheet_{len(panels)}.jpg"), cv2.vconcat(rows))
    print(f"Exported {len(manifest)} event candidates to {output}")


if __name__ == "__main__":
    main()
