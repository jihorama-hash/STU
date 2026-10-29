"""Build canonical object and visibility GT files from R01 review worksheets."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GT_ROOT = REPOSITORY_ROOT / "data/ground_truth/object_track_v1"
REVIEW_ROOT = GT_ROOT / "review"
OCCLUSION_REASON_MAP_PATH = REVIEW_ROOT / "occlusion_reason_map_R01.csv"
ALLOWED_OCCLUSION_REASONS = {
    "vegetation",
    "vehicle",
    "person",
    "structure",
    "frame_boundary",
    "image_quality",
    "ambiguous_identity",
    "other",
}

OBJECT_INPUT_FIELDS = (
    "gt_object_id",
    "object_class",
    "first_visible_frame_index",
    "last_visible_frame_index",
    "in_scope",
    "exclusion_reason",
    "notes",
)
VISIBILITY_INPUT_FIELDS = (
    "gt_object_id",
    "start_frame_index",
    "end_frame_index",
    "visibility_status",
    "occlusion_reason",
    "notes",
)
OBJECT_OUTPUT_FIELDS = (
    "schema_version",
    "gt_dataset_id",
    "video_id",
    "gt_object_id",
    "object_class",
    "first_visible_frame_index",
    "last_visible_frame_index",
    "first_visible_timestamp_seconds",
    "last_visible_timestamp_seconds",
    "origin_zone",
    "destination_zone",
    "in_scope",
    "exclusion_reason",
    "occlusion_summary",
    "reviewer",
    "review_status",
    "review_timestamp_utc",
    "notes",
)
VISIBILITY_OUTPUT_FIELDS = (
    "schema_version",
    "gt_dataset_id",
    "video_id",
    "gt_object_id",
    "visibility_interval_id",
    "start_frame_index",
    "end_frame_index",
    "start_timestamp_seconds",
    "end_timestamp_seconds",
    "visibility_status",
    "in_scope",
    "denominator_eligible",
    "occlusion_reason",
    "annotation_method",
    "reviewer",
    "review_status",
    "review_timestamp_utc",
    "notes",
)
VISIBILITY_STATUSES = {
    "visible",
    "partially_occluded",
    "fully_occluded",
    "not_observable",
}
DENOMINATOR_EXCLUDED_STATUSES = {"fully_occluded", "not_observable"}


class InputValidationError(ValueError):
    """Raised when working sheets cannot be converted without guessing."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def _read_csv(path: Path, expected_fields: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != expected_fields:
            raise InputValidationError(
                [
                    f"{path}: header must exactly match "
                    f"{','.join(expected_fields)}"
                ]
            )
        return [
            {field: (row.get(field) or "").strip() for field in expected_fields}
            for row in reader
        ]


def load_occlusion_reason_map(path: Path) -> dict[str, tuple[str, str]]:
    """Read and validate the explicit R01 reason mapping table."""
    rows = _read_csv(path, ("raw_value", "canonical_value", "description"))
    reason_map: dict[str, tuple[str, str]] = {}
    errors: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        raw_value = row["raw_value"]
        canonical_value = row["canonical_value"]
        if not raw_value:
            errors.append(f"{path}: row {row_number}: raw_value is required")
        elif raw_value in reason_map:
            errors.append(f"{path}: row {row_number}: duplicate raw_value {raw_value!r}")
        if canonical_value not in ALLOWED_OCCLUSION_REASONS:
            errors.append(
                f"{path}: row {row_number}: unsupported canonical_value "
                f"{canonical_value!r}"
            )
        if not row["description"]:
            errors.append(f"{path}: row {row_number}: description is required")
        reason_map[raw_value] = (canonical_value, row["description"])
    if errors:
        raise InputValidationError(errors)
    return reason_map


def _parse_bool(value: str, label: str, errors: list[str]) -> str:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        errors.append(f"{label}: expected TRUE/FALSE, got {value!r}")
        return ""
    # CSV booleans in the canonical schema are lowercase by definition.
    return normalized


def _parse_frame(value: str, label: str, errors: list[str]) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{label}: expected integer frame, got {value!r}")
        return None


def validate_inputs(
    object_rows: list[dict[str, str]],
    visibility_rows: list[dict[str, str]],
    manifest: dict,
) -> None:
    """Validate references, evaluation grid, reasons and interval coverage."""
    errors: list[str] = []
    pilot = manifest["pilot"]
    grid_start = int(pilot["evaluation_start_frame_index"])
    grid_end = int(pilot["evaluation_end_frame_index"])
    frame_step = int(manifest["sampling"]["frame_step"])
    classes = set(manifest["scope"]["object_classes"])
    object_map: dict[str, dict[str, str]] = {}

    for row_number, row in enumerate(object_rows, start=2):
        object_id = row["gt_object_id"]
        label = f"object worksheet row {row_number}"
        if not object_id:
            errors.append(f"{label}: gt_object_id is required")
        elif object_id in object_map:
            errors.append(f"{label}: duplicate gt_object_id {object_id!r}")
        else:
            object_map[object_id] = row
        if row["object_class"] not in classes:
            errors.append(
                f"{label}: unsupported object_class {row['object_class']!r}"
            )
        first = _parse_frame(row["first_visible_frame_index"], f"{label} first", errors)
        last = _parse_frame(row["last_visible_frame_index"], f"{label} last", errors)
        for name, frame in (("first", first), ("last", last)):
            if frame is not None and (
                frame < grid_start
                or frame > grid_end
                or (frame - grid_start) % frame_step != 0
            ):
                errors.append(
                    f"{label}: {name} frame {frame} is outside evaluation grid"
                )
        if first is not None and last is not None and first > last:
            errors.append(f"{label}: first frame {first} is after last frame {last}")
        in_scope = _parse_bool(row["in_scope"], f"{label} in_scope", errors)
        if in_scope == "false" and not row["exclusion_reason"]:
            errors.append(f"{label}: exclusion_reason is required when out of scope")

    intervals_by_object: dict[str, list[tuple[int, int, int, str]]] = defaultdict(list)
    for row_number, row in enumerate(visibility_rows, start=2):
        label = f"visibility worksheet row {row_number}"
        object_id = row["gt_object_id"]
        if object_id not in object_map:
            errors.append(f"{label}: unregistered gt_object_id {object_id!r}")
        start = _parse_frame(row["start_frame_index"], f"{label} start", errors)
        end = _parse_frame(row["end_frame_index"], f"{label} end", errors)
        for name, frame in (("start", start), ("end", end)):
            if frame is not None and (
                frame < grid_start
                or frame > grid_end
                or (frame - grid_start) % frame_step != 0
            ):
                errors.append(
                    f"{label}: {name} frame {frame} is outside evaluation grid"
                )
        status = row["visibility_status"]
        if status not in VISIBILITY_STATUSES:
            errors.append(f"{label}: unsupported visibility_status {status!r}")
        if status != "visible" and not row["occlusion_reason"]:
            errors.append(f"{label}: occlusion_reason is required for {status!r}")
        if start is not None and end is not None:
            if start > end:
                errors.append(f"{label}: start frame {start} is after end frame {end}")
            intervals_by_object[object_id].append((start, end, row_number, status))

    for object_id, obj in object_map.items():
        first = _parse_frame(
            obj["first_visible_frame_index"], f"{object_id} first", errors
        )
        last = _parse_frame(
            obj["last_visible_frame_index"], f"{object_id} last", errors
        )
        intervals = sorted(intervals_by_object.get(object_id, []))
        if not intervals:
            errors.append(f"{object_id}: no visibility intervals")
            continue
        if first is not None and intervals[0][0] != first:
            errors.append(
                f"{object_id}: first interval starts at {intervals[0][0]}, "
                f"expected {first}"
            )
        if last is not None and intervals[-1][1] != last:
            errors.append(
                f"{object_id}: last interval ends at {intervals[-1][1]}, "
                f"expected {last}"
            )
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] <= previous[1]:
                errors.append(
                    f"{object_id}: intervals at rows {previous[2]} and "
                    f"{current[2]} overlap"
                )
            elif current[0] != previous[1] + frame_step:
                errors.append(
                    f"{object_id}: gap between rows {previous[2]} and {current[2]}"
                )

    if errors:
        raise InputValidationError(errors)


def _timestamp(frame: int, source_fps: float) -> str:
    return repr(frame / source_fps)


def _occlusion_summary(statuses: set[str]) -> str:
    if statuses == {"visible"}:
        return "none"
    summary = {
        "partially_occluded": "partial",
        "fully_occluded": "full",
        "not_observable": "not_observable",
    }
    if len(statuses) == 1:
        return summary[next(iter(statuses))]
    return "mixed"


def build_canonical_rows(
    object_rows: list[dict[str, str]],
    visibility_rows: list[dict[str, str]],
    manifest: dict,
    reason_map: dict[str, tuple[str, str]] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Convert validated worksheet rows into canonical CSV row dictionaries."""
    validate_inputs(object_rows, visibility_rows, manifest)
    if reason_map is None:
        reason_map = load_occlusion_reason_map(OCCLUSION_REASON_MAP_PATH)
    unmapped_reasons = sorted(
        {
            row["occlusion_reason"]
            for row in visibility_rows
            if row["occlusion_reason"]
            and row["occlusion_reason"] not in reason_map
        }
    )
    if unmapped_reasons:
        raise InputValidationError(
            [f"unmapped occlusion_reason {value!r}" for value in unmapped_reasons]
        )
    source_fps = float(manifest["video"]["source_fps"])
    common = {
        "schema_version": manifest["schema_version"],
        "gt_dataset_id": manifest["gt_dataset_id"],
        "video_id": manifest["video"]["video_id"],
    }
    reviewer = manifest["annotation"]["reviewers"][0]
    statuses_by_object: dict[str, set[str]] = defaultdict(set)
    ordered_visibility = sorted(
        visibility_rows,
        key=lambda row: (
            row["gt_object_id"],
            int(row["start_frame_index"]),
            int(row["end_frame_index"]),
        ),
    )
    for row in ordered_visibility:
        statuses_by_object[row["gt_object_id"]].add(row["visibility_status"])

    canonical_objects: list[dict[str, str]] = []
    for row in object_rows:
        first = int(row["first_visible_frame_index"])
        last = int(row["last_visible_frame_index"])
        in_scope = _parse_bool(row["in_scope"], row["gt_object_id"], [])
        canonical_objects.append(
            {
                **common,
                "gt_object_id": row["gt_object_id"],
                "object_class": row["object_class"],
                "first_visible_frame_index": str(first),
                "last_visible_frame_index": str(last),
                "first_visible_timestamp_seconds": _timestamp(first, source_fps),
                "last_visible_timestamp_seconds": _timestamp(last, source_fps),
                "origin_zone": "",
                "destination_zone": "",
                "in_scope": in_scope,
                "exclusion_reason": row["exclusion_reason"],
                "occlusion_summary": _occlusion_summary(
                    statuses_by_object[row["gt_object_id"]]
                ),
                "reviewer": reviewer,
                "review_status": "draft",
                "review_timestamp_utc": "",
                "notes": row["notes"],
            }
        )

    interval_numbers: dict[str, int] = defaultdict(int)
    canonical_visibility: list[dict[str, str]] = []
    for row in ordered_visibility:
        object_id = row["gt_object_id"]
        interval_numbers[object_id] += 1
        start = int(row["start_frame_index"])
        end = int(row["end_frame_index"])
        source_object = next(
            obj for obj in object_rows if obj["gt_object_id"] == object_id
        )
        in_scope = _parse_bool(
            source_object["in_scope"],
            f"{object_id} in_scope",
            [],
        )
        eligible = (
            in_scope == "true"
            and row["visibility_status"] not in DENOMINATOR_EXCLUDED_STATUSES
        )
        raw_reason = row["occlusion_reason"]
        canonical_reason = reason_map[raw_reason][0] if raw_reason else ""
        notes = row["notes"]
        if raw_reason:
            original_reason_note = f"original_occlusion_reason={raw_reason}"
            notes = f"{notes}; {original_reason_note}" if notes else original_reason_note
        canonical_visibility.append(
            {
                **common,
                "gt_object_id": object_id,
                "visibility_interval_id": (
                    f"{object_id}_VI{interval_numbers[object_id]:03d}"
                ),
                "start_frame_index": str(start),
                "end_frame_index": str(end),
                "start_timestamp_seconds": _timestamp(start, source_fps),
                "end_timestamp_seconds": _timestamp(end, source_fps),
                "visibility_status": row["visibility_status"],
                "in_scope": in_scope,
                "denominator_eligible": str(eligible).lower(),
                "occlusion_reason": canonical_reason,
                "annotation_method": "manual",
                "reviewer": reviewer,
                "review_status": "draft",
                "review_timestamp_utc": "",
                "notes": notes,
            }
        )
    return canonical_objects, canonical_visibility


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def convert(
    object_path: Path,
    visibility_path: Path,
    manifest_path: Path,
    objects_output: Path,
    visibility_output: Path,
    reason_map_path: Path = OCCLUSION_REASON_MAP_PATH,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Validate all inputs, then write canonical files and update the manifest."""
    object_rows = _read_csv(object_path, OBJECT_INPUT_FIELDS)
    visibility_rows = _read_csv(visibility_path, VISIBILITY_INPUT_FIELDS)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reason_map = load_occlusion_reason_map(reason_map_path)
    object_output_rows, visibility_output_rows = build_canonical_rows(
        object_rows, visibility_rows, manifest, reason_map
    )

    # All worksheet checks complete before any destination is changed.
    _write_csv(objects_output, OBJECT_OUTPUT_FIELDS, object_output_rows)
    _write_csv(visibility_output, VISIBILITY_OUTPUT_FIELDS, visibility_output_rows)
    manifest.setdefault("annotation", {})["updated_at_utc"] = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return object_output_rows, visibility_output_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--object-worksheet",
        type=Path,
        default=REVIEW_ROOT / "gate3a2_object_inventory_R01.csv",
    )
    parser.add_argument(
        "--visibility-worksheet",
        type=Path,
        default=REVIEW_ROOT / "gate3a2_visibility_R01.csv",
    )
    parser.add_argument(
        "--manifest", type=Path, default=GT_ROOT / "ground_truth_manifest.json"
    )
    parser.add_argument(
        "--objects-output", type=Path, default=GT_ROOT / "gt_objects.csv"
    )
    parser.add_argument(
        "--visibility-output",
        type=Path,
        default=GT_ROOT / "gt_visibility_intervals.csv",
    )
    parser.add_argument(
        "--occlusion-reason-map",
        type=Path,
        default=OCCLUSION_REASON_MAP_PATH,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        objects, visibility = convert(
            args.object_worksheet,
            args.visibility_worksheet,
            args.manifest,
            args.objects_output,
            args.visibility_output,
            args.occlusion_reason_map,
        )
    except InputValidationError as exc:
        raise SystemExit(
            f"Input validation failed; no canonical files written:\n{exc}"
        ) from exc
    print(f"Wrote {len(objects)} object rows and {len(visibility)} visibility rows.")


if __name__ == "__main__":
    main()
