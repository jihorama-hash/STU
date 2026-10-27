"""Render legacy manual references beside baseline and experiment candidates."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import cv2

from .paths import resolve_project_path


VEHICLE_CLASSES = {"bicycle", "motorcycle", "car", "bus", "truck", "tricycle"}


def load_tracks(path: Path) -> dict[int, list[dict[str, str]]]:
    tracks: dict[int, list[dict[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            tracks[int(row["track_id"])].append(row)
    return tracks


def is_compatible(reference_class: str, candidate_class: str) -> bool:
    if reference_class == "person":
        return candidate_class == "person"
    return candidate_class in VEHICLE_CLASSES


def draw_candidates(
    frame,
    tracks: dict[int, list[dict[str, str]]],
    timestamp: float,
    reference_class: str,
    title: str,
) -> tuple[object, int]:
    output = frame.copy()
    tolerance = 0.08
    candidates = 0
    for track_id, rows in tracks.items():
        compatible = [
            row for row in rows
            if is_compatible(reference_class, row["object_class"])
            and abs(float(row["timestamp_seconds"]) - timestamp) <= tolerance
        ]
        if not compatible:
            continue
        row = min(
            compatible,
            key=lambda item: abs(float(item["timestamp_seconds"]) - timestamp),
        )
        x1, y1, x2, y2 = (
            round(float(row[key])) for key in ("x1", "y1", "x2", "y2")
        )
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 255, 0), 5)
        cv2.putText(
            output,
            f"{row['object_class']} #{track_id}",
            (x1, max(40, y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            3,
            cv2.LINE_AA,
        )
        candidates += 1
    cv2.putText(
        output,
        f"{title} | t={timestamp:.2f}s | candidates={candidates}",
        (30, 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        (0, 255, 255),
        4,
        cv2.LINE_AA,
    )
    return output, candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--reference-manifest", required=True)
    parser.add_argument("--reference-images", required=True)
    parser.add_argument("--baseline-tracks", required=True)
    parser.add_argument("--experiment-tracks", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start-seconds", type=float, required=True)
    parser.add_argument("--end-seconds", type=float, required=True)
    args = parser.parse_args()

    video_path = resolve_project_path(args.video)
    manifest_path = resolve_project_path(args.reference_manifest)
    reference_dir = resolve_project_path(args.reference_images)
    output_dir = resolve_project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = load_tracks(resolve_project_path(args.baseline_tracks))
    experiment = load_tracks(resolve_project_path(args.experiment_tracks))

    with manifest_path.open(encoding="utf-8-sig", newline="") as stream:
        references = [
            row for row in csv.DictReader(stream)
            if float(row["end_sec"]) >= args.start_seconds
            and float(row["start_sec"]) < args.end_seconds
        ]

    capture = cv2.VideoCapture(str(video_path))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    results: list[dict[str, object]] = []
    for index, reference in enumerate(references, start=1):
        midpoint = (
            max(float(reference["start_sec"]), args.start_seconds)
            + min(float(reference["end_sec"]), args.end_seconds)
        ) / 2
        frame_index = round(midpoint * fps)
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Could not read frame {frame_index}")

        legacy = cv2.imread(str(reference_dir / reference["image"]))
        if legacy is None:
            raise FileNotFoundError(reference_dir / reference["image"])
        baseline_frame, baseline_count = draw_candidates(
            frame, baseline, midpoint, reference["class"], "COCO baseline"
        )
        experiment_frame, experiment_count = draw_candidates(
            frame, experiment, midpoint, reference["class"], "VisDrone V2"
        )
        width = 1280
        panels = [
            cv2.resize(image, (width, round(image.shape[0] * width / image.shape[1])))
            for image in (legacy, baseline_frame, experiment_frame)
        ]
        comparison = cv2.vconcat(panels)
        filename = (
            f"reference_{index:02d}_{reference['class']}_"
            f"legacy_{reference['track_id']}.jpg"
        )
        cv2.imwrite(str(output_dir / filename), comparison)
        results.append({
            "reference_number": index,
            "legacy_track_id": reference["track_id"],
            "reference_class": reference["class"],
            "reference_start_seconds": reference["start_sec"],
            "reference_end_seconds": reference["end_sec"],
            "comparison_timestamp_seconds": midpoint,
            "baseline_candidates": baseline_count,
            "visdrone_candidates": experiment_count,
            "image": filename,
            "baseline_match": "",
            "visdrone_match": "",
            "notes": "",
        })
    capture.release()

    with (output_dir / "manifest.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"Exported {len(results)} reference comparisons to {output_dir}")


if __name__ == "__main__":
    main()
