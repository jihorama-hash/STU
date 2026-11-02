"""Convert the R01 position worksheet to canonical observation GT."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GT_ROOT = ROOT / "data/ground_truth/object_track_v1"
INPUT_FIELDS = (
    "schema_version", "gt_dataset_id", "video_id", "gt_object_id",
    "frame_index", "timestamp_seconds", "object_class", "x1", "y1", "x2",
    "y2", "foot_x", "foot_y", "coordinate_system", "position_unit",
    "visibility_status", "observation_method", "interpolation_span_frames",
    "in_scope", "reviewer", "review_status", "review_timestamp_utc", "notes",
)
OUTPUT_FIELDS = INPUT_FIELDS
OBJECT_FIELDS = (
    "schema_version", "gt_dataset_id", "video_id", "gt_object_id", "object_class",
    "first_visible_frame_index", "last_visible_frame_index",
    "first_visible_timestamp_seconds", "last_visible_timestamp_seconds",
    "origin_zone", "destination_zone", "in_scope", "exclusion_reason",
    "occlusion_summary", "reviewer", "review_status", "review_timestamp_utc", "notes",
)
VISIBILITY_FIELDS = (
    "schema_version", "gt_dataset_id", "video_id", "gt_object_id",
    "visibility_interval_id", "start_frame_index", "end_frame_index",
    "start_timestamp_seconds", "end_timestamp_seconds", "visibility_status",
    "in_scope", "denominator_eligible", "occlusion_reason", "annotation_method",
    "reviewer", "review_status", "review_timestamp_utc", "notes",
)


class InputValidationError(ValueError):
    """Raised when an observation worksheet cannot be converted safely."""


def read_csv(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != fields:
            raise InputValidationError(f"{path}: header must match template")
        return [{field: (row.get(field) or "").strip() for field in fields}
                for row in reader]


def build_rows(
    input_rows: list[dict[str, str]],
    objects: list[dict[str, str]],
    visibility: list[dict[str, str]],
    manifest: dict,
) -> list[dict[str, str]]:
    """Derive canonical metadata while retaining manual positions and notes."""
    errors: list[str] = []
    object_map = {row["gt_object_id"]: row for row in objects}
    if len(object_map) != len(objects):
        errors.append("canonical objects contain duplicate gt_object_id")
    intervals: dict[str, list[dict[str, str]]] = {}
    for interval in visibility:
        intervals.setdefault(interval["gt_object_id"], []).append(interval)
    for rows in intervals.values():
        rows.sort(key=lambda row: int(row["start_frame_index"]))

    for number, row in enumerate(input_rows, start=2):
        label = f"observation row {number}"
        object_id = row["gt_object_id"]
        if object_id not in object_map:
            errors.append(f"{label}: unknown gt_object_id {object_id!r}")
            continue
        try:
            frame = int(row["frame_index"])
            coords = [float(row[key]) for key in ("x1", "y1", "x2", "y2")]
        except ValueError:
            errors.append(f"{label}: frame and box coordinates must be numeric")
            continue
        if not all(math.isfinite(value) for value in coords):
            errors.append(f"{label}: box coordinates must be finite")
        if not row["gt_object_id"] or frame < 0:
            errors.append(f"{label}: object id and nonnegative frame are required")
        if coords[0] >= coords[2] or coords[1] >= coords[3]:
            errors.append(f"{label}: box must have positive width and height")
        if not row["x1"] or not row["y1"] or not row["x2"] or not row["y2"]:
            errors.append(f"{label}: box coordinates are required")
        adjusted_foot = "foot_adjusted" in {
            part.strip() for part in row["notes"].split(";")
        }
        for key in (("foot_x", "foot_y") if adjusted_foot else ()):
            if not row[key]:
                errors.append(f"{label}: {key} is required in the R01 worksheet")
        if not row["review_timestamp_utc"]:
            errors.append(f"{label}: review_timestamp_utc is required in the R01 worksheet")
        if row["observation_method"] != "manual":
            errors.append(f"{label}: only manual observations are supported")
        matching = [iv for iv in intervals.get(object_id, [])
                    if int(iv["start_frame_index"]) <= frame <= int(iv["end_frame_index"])]
        if len(matching) != 1:
            errors.append(f"{label}: frame {frame} must match one visibility interval")
        elif matching[0]["visibility_status"] in {"fully_occluded", "not_observable"}:
            errors.append(f"{label}: observation falls in denominator-excluded visibility")

    if errors:
        raise InputValidationError("\n".join(errors))

    source_fps = float(manifest["video"]["source_fps"])
    if source_fps <= 0:
        raise InputValidationError("manifest video.source_fps must be positive")
    common = {
        "schema_version": manifest["schema_version"],
        "gt_dataset_id": manifest["gt_dataset_id"],
        "video_id": manifest["video"]["video_id"],
    }
    reviewer = manifest["annotation"]["reviewers"][0]
    result: list[dict[str, str]] = []
    seen: set[tuple[str, int]] = set()
    ordered_rows = sorted(
        input_rows,
        key=lambda item: (item["gt_object_id"], int(item["frame_index"])),
    )
    for row in ordered_rows:
        object_id = row["gt_object_id"]
        frame = int(row["frame_index"])
        key = (object_id, frame)
        if key in seen:
            raise InputValidationError(f"duplicate observation {object_id} frame {frame}")
        seen.add(key)
        obj = object_map[object_id]
        interval = next(iv for iv in intervals[object_id]
                        if int(iv["start_frame_index"]) <= frame <= int(iv["end_frame_index"]))
        if "foot_adjusted" in {part.strip() for part in row["notes"].split(";")}:
            foot_x, foot_y = row["foot_x"], row["foot_y"]
        else:
            foot_x = repr((float(row["x1"]) + float(row["x2"])) / 2)
            foot_y = repr(float(row["y2"]))
        result.append({
            **common,
            "gt_object_id": object_id,
            "frame_index": str(frame),
            "timestamp_seconds": repr(frame / source_fps),
            "object_class": obj["object_class"],
            "x1": row["x1"], "y1": row["y1"], "x2": row["x2"], "y2": row["y2"],
            "foot_x": foot_x, "foot_y": foot_y,
            "coordinate_system": manifest["video"]["coordinate_system"],
            "position_unit": manifest["video"]["position_unit"],
            "visibility_status": interval["visibility_status"],
            "observation_method": "manual",
            "interpolation_span_frames": "",
            "in_scope": obj["in_scope"].lower(),
            "reviewer": reviewer,
            "review_status": "draft",
            # The viewer records this provenance timestamp in the source worksheet.
            "review_timestamp_utc": row["review_timestamp_utc"],
            "notes": row["notes"],
        })
    return result


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def convert(
    input_path: Path,
    objects_path: Path,
    visibility_path: Path,
    manifest_path: Path,
    output_path: Path,
) -> list[dict[str, str]]:
    rows = read_csv(input_path, INPUT_FIELDS)
    objects = read_csv(objects_path, OBJECT_FIELDS)
    visibility = read_csv(visibility_path, VISIBILITY_FIELDS)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = build_rows(rows, objects, visibility, manifest)
    write_csv(output_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=GT_ROOT / "review/gt_observations_R01.csv"
    )
    parser.add_argument("--objects", type=Path, default=GT_ROOT / "gt_objects.csv")
    parser.add_argument(
        "--visibility", type=Path, default=GT_ROOT / "gt_visibility_intervals.csv"
    )
    parser.add_argument("--manifest", type=Path, default=GT_ROOT / "ground_truth_manifest.json")
    parser.add_argument("--output", type=Path, default=GT_ROOT / "gt_observations.csv")
    args = parser.parse_args()
    try:
        rows = convert(args.input, args.objects, args.visibility, args.manifest, args.output)
    except (InputValidationError, KeyError, ValueError) as exc:
        raise SystemExit(f"Observation conversion failed: {exc}") from exc
    print(f"Wrote {len(rows)} canonical observation rows to {args.output}")


if __name__ == "__main__":
    main()
