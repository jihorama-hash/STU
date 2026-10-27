"""Create five-frame temporal strips for unresolved event candidates."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import cv2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--reviews", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    tracks = defaultdict(list)
    with Path(args.tracks).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            tracks[int(row["track_id"])].append(row)
    with Path(args.manifest).open(encoding="utf-8-sig", newline="") as stream:
        events = {row["event_id"]: row for row in csv.DictReader(stream)}
    with Path(args.reviews).open(encoding="utf-8-sig", newline="") as stream:
        review_rows = [
            row for row in csv.DictReader(stream)
            if row["review_status"] == "needs_clip_review"
        ]

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(args.video)
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    for review in review_rows:
        event = events[review["event_id"]]
        timestamp = float(event["timestamp_seconds"])
        actor_ids = [int(event["first_track_id"]), int(event["second_track_id"])]
        panels = []
        for offset in (-2.0, -1.0, 0.0, 1.0, 2.0):
            target = timestamp + offset
            capture.set(cv2.CAP_PROP_POS_FRAMES, round(target * fps))
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Could not read t={target}")
            for actor_index, track_id in enumerate(actor_ids):
                actor = min(
                    tracks[track_id],
                    key=lambda row: abs(float(row["timestamp_seconds"]) - target),
                )
                if abs(float(actor["timestamp_seconds"]) - target) > 0.25:
                    continue
                x1, y1, x2, y2 = (
                    round(float(actor[key])) for key in ("x1", "y1", "x2", "y2")
                )
                color = (0, 255, 0) if actor_index == 0 else (255, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 6)
                cv2.putText(
                    frame, f"{actor['object_class']} #{track_id}",
                    (x1, max(40, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, color, 3, cv2.LINE_AA,
                )
            cv2.putText(
                frame, f"{event['event_id']} | offset {offset:+.1f}s",
                (25, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                (0, 255, 255), 4, cv2.LINE_AA,
            )
            width = 640
            panels.append(cv2.resize(
                frame, (width, round(frame.shape[0] * width / frame.shape[1]))
            ))
        cv2.imwrite(
            str(output / f"{review['review_number']}_{event['event_id']}.jpg"),
            cv2.hconcat(panels),
        )
    capture.release()
    print(f"Exported {len(review_rows)} filmstrips to {output}")


if __name__ == "__main__":
    main()
