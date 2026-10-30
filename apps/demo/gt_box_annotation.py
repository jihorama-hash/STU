"""Blind manual box entry for the R01 object-track ground truth pilot."""

from __future__ import annotations

import argparse
import csv
import json
import math
import threading
from collections import defaultdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2

from scripts.blind_gt_review_viewer import DEFAULT_VIDEO, EvaluationGrid, FrameReader


ROOT = Path(__file__).resolve().parents[2]
GT_ROOT = ROOT / "data/ground_truth/object_track_v1"
REVIEW_ROOT = GT_ROOT / "review"
MANIFEST_PATH = GT_ROOT / "ground_truth_manifest.json"
OBJECTS_PATH = GT_ROOT / "gt_objects.csv"
VISIBILITY_PATH = GT_ROOT / "gt_visibility_intervals.csv"
OBSERVATIONS_PATH = REVIEW_ROOT / "gt_observations_R01.csv"
SKIPS_PATH = REVIEW_ROOT / "gt_observation_skips_R01.csv"
OBSERVATION_TEMPLATE = GT_ROOT / "gt_observations.template.csv"
OBJECT_TEMPLATE = GT_ROOT / "gt_objects.template.csv"
VISIBILITY_TEMPLATE = GT_ROOT / "gt_visibility_intervals.template.csv"
OBSERVATION_HEADERS = tuple(
    next(csv.reader(OBSERVATION_TEMPLATE.open(encoding="utf-8-sig")))
)
OBJECT_HEADERS = tuple(next(csv.reader(OBJECT_TEMPLATE.open(encoding="utf-8-sig"))))
VISIBILITY_HEADERS = tuple(
    next(csv.reader(VISIBILITY_TEMPLATE.open(encoding="utf-8-sig")))
)
SKIP_HEADERS = ("gt_object_id", "frame_index", "reason", "notes")
SKIP_REASONS = {
    "not_found",
    "ambiguous_identity",
    "occluded_more_than_marked",
    "other",
}
VISIBILITY_STATUSES = {"visible", "partially_occluded"}
EXCLUDED_VISIBILITY_STATUSES = {"fully_occluded", "not_observable"}
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
ALLOWED_CLASSES = {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
FRAME_WIDTH = 3840
FRAME_HEIGHT = 2160
PLAYBACK_WIDTH = 1280
REVIEWER = "R01"


class AnnotationError(ValueError):
    """Raised when canonical GT or annotation work files are invalid."""


def _read_csv(path: Path, headers: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise AnnotationError(f"required CSV is missing: {path}")
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != headers:
                raise AnnotationError(
                    f"{path}: header must match template: {','.join(headers)}"
                )
            rows = []
            for row in reader:
                if None in row:
                    raise AnnotationError(f"{path}: row has extra columns")
                rows.append({key: (value or "").strip() for key, value in row.items()})
            return rows
    except UnicodeDecodeError as exc:
        raise AnnotationError(f"{path}: CSV must be UTF-8") from exc
    except csv.Error as exc:
        raise AnnotationError(f"{path}: invalid CSV: {exc}") from exc


def _integer(value: str, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AnnotationError(f"{label}: expected integer, got {value!r}") from exc


def _number(value: str, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AnnotationError(f"{label}: expected number, got {value!r}") from exc
    if not math.isfinite(result):
        raise AnnotationError(f"{label}: expected finite number")
    return result


def calculate_anchors(
    objects: list[dict[str, str]],
    visibility: list[dict[str, str]],
    grid: EvaluationGrid,
    interval_seconds: int = 1,
) -> dict[str, list[dict[str, object]]]:
    """Return interval endpoints and fixed one-second anchors for eligible GT."""
    if not objects:
        raise AnnotationError("gt_objects.csv contains no objects")
    object_map = {row["gt_object_id"]: row for row in objects}
    if len(object_map) != len(objects):
        raise AnnotationError("gt_objects.csv contains duplicate gt_object_id")
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_intervals: dict[str, list[tuple[int, int]]] = defaultdict(list)
    step = round(grid.source_fps * interval_seconds / grid.frame_step) * grid.frame_step

    for row_number, row in enumerate(objects, start=2):
        object_id = row["gt_object_id"]
        object_class = row["object_class"]
        if not object_id or object_class not in ALLOWED_CLASSES:
            raise AnnotationError(f"gt_objects.csv row {row_number}: invalid ID or class")
        if row["in_scope"].lower() not in {"true", "false"}:
            raise AnnotationError(f"{object_id}: invalid in_scope")
        first = _integer(row["first_visible_frame_index"], f"{object_id} first frame")
        last = _integer(row["last_visible_frame_index"], f"{object_id} last frame")
        if first > last or not grid.contains(first) or not grid.contains(last):
            raise AnnotationError(f"{object_id}: invalid object frame bounds")

    for row_number, row in enumerate(visibility, start=2):
        object_id = row["gt_object_id"]
        if object_id not in object_map:
            raise AnnotationError(f"visibility row {row_number}: unknown object {object_id!r}")
        start = _integer(row["start_frame_index"], f"visibility row {row_number} start")
        end = _integer(row["end_frame_index"], f"visibility row {row_number} end")
        if start > end or not grid.contains(start) or not grid.contains(end):
            raise AnnotationError(f"visibility row {row_number}: invalid frame bounds")
        if row["visibility_status"] not in VISIBILITY_STATUSES | EXCLUDED_VISIBILITY_STATUSES:
            raise AnnotationError(f"visibility row {row_number}: unsupported status")
        if row["occlusion_reason"] and row["occlusion_reason"] not in ALLOWED_OCCLUSION_REASONS:
            raise AnnotationError(f"visibility row {row_number}: unsupported occlusion reason")
        object_row = object_map[object_id]
        object_first = int(object_row["first_visible_frame_index"])
        object_last = int(object_row["last_visible_frame_index"])
        if start < object_first or end > object_last:
            raise AnnotationError(f"{object_id}: interval lies outside object bounds")
        if row["in_scope"].lower() != object_row["in_scope"].lower():
            raise AnnotationError(f"{object_id}: visibility in_scope mismatch")
        eligible = (
            object_row["in_scope"].lower() == "true"
            and row["visibility_status"] in VISIBILITY_STATUSES
        )
        if row["denominator_eligible"].lower() != str(eligible).lower():
            raise AnnotationError(f"{object_id}: denominator_eligible mismatch")
        if row["visibility_status"] != "visible" and not row["occlusion_reason"]:
            raise AnnotationError(f"{object_id}: occlusion reason is required")
        seen_intervals[object_id].append((start, end))
        if not eligible:
            continue
        frame_set = {start, end}
        first_periodic = grid.start_frame + math.ceil(
            (start - grid.start_frame) / step
        ) * step
        frame_set.update(range(first_periodic, end + 1, step))
        for frame_index in sorted(frame_set):
            if start <= frame_index <= end and grid.contains(frame_index):
                grouped[object_id].append(
                    {
                        "frame_index": frame_index,
                        "visibility_status": row["visibility_status"],
                        "in_scope": row["in_scope"].lower(),
                    }
                )

    for object_id, object_row in object_map.items():
        intervals = sorted(seen_intervals.get(object_id, []))
        if not intervals:
            raise AnnotationError(f"{object_id}: no visibility intervals")
        if intervals[0][0] != int(object_row["first_visible_frame_index"]):
            raise AnnotationError(f"{object_id}: first interval does not match object start")
        if intervals[-1][1] != int(object_row["last_visible_frame_index"]):
            raise AnnotationError(f"{object_id}: last interval does not match object end")
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] != previous[1] + grid.frame_step:
                raise AnnotationError(f"{object_id}: intervals overlap or have a gap")
    for object_id in grouped:
        unique: dict[int, dict[str, object]] = {}
        for anchor in grouped[object_id]:
            frame_index = int(anchor["frame_index"])
            if frame_index in unique:
                raise AnnotationError(f"{object_id}: duplicate generated anchor {frame_index}")
            unique[frame_index] = anchor
        grouped[object_id] = [unique[index] for index in sorted(unique)]
    return {row["gt_object_id"]: grouped.get(row["gt_object_id"], []) for row in objects}


def calculate_crop(
    center_x: float,
    center_y: float,
    zoom: float,
    width: int = FRAME_WIDTH,
    height: int = FRAME_HEIGHT,
) -> dict[str, int]:
    """Calculate a centered source-pixel crop matching the 16:9 viewer."""
    zoom = max(1.0, min(12.0, float(zoom)))
    crop_width = max(1, round(width / zoom))
    crop_height = max(1, round(height / zoom))
    left = round(center_x - crop_width / 2)
    top = round(center_y - crop_height / 2)
    left = min(max(0, left), width - crop_width)
    top = min(max(0, top), height - crop_height)
    return {"left": left, "top": top, "width": crop_width, "height": crop_height}


def canvas_to_source(
    x: float,
    y: float,
    canvas_width: float,
    canvas_height: float,
    crop: dict[str, int],
) -> tuple[float, float]:
    """Convert a pointer point in the displayed crop to source-pixel coordinates."""
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("canvas dimensions must be positive")
    source_x = crop["left"] + x * crop["width"] / canvas_width
    source_y = crop["top"] + y * crop["height"] / canvas_height
    return source_x, source_y


def predict_zoom_center(
    observations: list[dict[str, str]],
    frame_index: int,
) -> tuple[float, float] | None:
    """Extrapolate a center using only the same object's last two GT boxes."""
    prior = sorted(
        (row for row in observations if int(row["frame_index"]) < frame_index),
        key=lambda row: int(row["frame_index"]),
    )[-2:]
    if not prior:
        return None
    centers = [
        (
            (float(row["x1"]) + float(row["x2"])) / 2,
            (float(row["y1"]) + float(row["y2"])) / 2,
        )
        for row in prior
    ]
    if len(prior) == 1:
        return centers[-1]
    frame_a = int(prior[0]["frame_index"])
    frame_b = int(prior[1]["frame_index"])
    if frame_b == frame_a:
        return centers[-1]
    ratio = (frame_index - frame_b) / (frame_b - frame_a)
    return (
        centers[1][0] + (centers[1][0] - centers[0][0]) * ratio,
        centers[1][1] + (centers[1][1] - centers[0][1]) * ratio,
    )


def _append_note(notes: str, token: str) -> str:
    parts = [part.strip() for part in notes.split(";") if part.strip()]
    if token not in parts:
        parts.append(token)
    return "; ".join(parts)


class AnnotationState:
    """Validated canonical data plus durable work-in-progress observations."""

    def __init__(
        self,
        manifest: dict[str, object],
        objects: list[dict[str, str]],
        visibility: list[dict[str, str]],
        observations_path: Path = OBSERVATIONS_PATH,
        skips_path: Path = SKIPS_PATH,
        grid: EvaluationGrid | None = None,
    ) -> None:
        self.manifest = manifest
        self.objects = objects
        self.visibility = visibility
        self.observations_path = observations_path
        self.skips_path = skips_path
        self.grid = grid or EvaluationGrid()
        self.anchors = calculate_anchors(objects, visibility, self.grid)
        self.object_map = {row["gt_object_id"]: row for row in objects}
        self.intervals_by_object: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in visibility:
            self.intervals_by_object[row["gt_object_id"]].append(row)
        self.lock = threading.RLock()
        self.observations = self._load_work(
            observations_path, OBSERVATION_HEADERS, "observations"
        )
        self.skips = self._load_work(skips_path, SKIP_HEADERS, "skips")
        self.validate_work()

    @classmethod
    def from_paths(
        cls,
        manifest_path: Path = MANIFEST_PATH,
        objects_path: Path = OBJECTS_PATH,
        visibility_path: Path = VISIBILITY_PATH,
        observations_path: Path = OBSERVATIONS_PATH,
        skips_path: Path = SKIPS_PATH,
        grid: EvaluationGrid | None = None,
    ) -> "AnnotationState":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        objects = _read_csv(objects_path, OBJECT_HEADERS)
        visibility = _read_csv(visibility_path, VISIBILITY_HEADERS)
        state = cls(
            manifest,
            objects,
            visibility,
            observations_path,
            skips_path,
            grid,
        )
        state._validate_metadata()
        return state

    def _load_work(
        self,
        path: Path,
        headers: tuple[str, ...],
        label: str,
    ) -> list[dict[str, str]]:
        if not path.exists():
            return []
        try:
            return _read_csv(path, headers)
        except AnnotationError as exc:
            raise AnnotationError(f"invalid {label} work file: {exc}") from exc

    def _validate_metadata(self) -> None:
        expected = {
            "schema_version": self.manifest["schema_version"],
            "gt_dataset_id": self.manifest["gt_dataset_id"],
            "video_id": self.manifest["video"]["video_id"],
        }
        for path, rows in (
            (OBJECTS_PATH, self.objects),
            (VISIBILITY_PATH, self.visibility),
        ):
            for line_number, row in enumerate(rows, start=2):
                for field, value in expected.items():
                    if row[field] != value:
                        raise AnnotationError(
                            f"{path}:{line_number}: {field} does not match manifest"
                        )
        pilot = self.manifest["pilot"]
        sampling = self.manifest["sampling"]
        files = self.manifest["files"]
        if Path(str(files["objects"])).name != OBJECTS_PATH.name:
            raise AnnotationError("manifest files.objects does not identify gt_objects.csv")
        if Path(str(files["visibility_intervals"])).name != VISIBILITY_PATH.name:
            raise AnnotationError(
                "manifest files.visibility_intervals does not identify gt_visibility_intervals.csv"
            )
        if int(pilot["evaluation_start_frame_index"]) != self.grid.start_frame:
            raise AnnotationError("manifest evaluation start does not match supported grid")
        if int(pilot["evaluation_end_frame_index"]) != self.grid.end_frame:
            raise AnnotationError("manifest evaluation end does not match supported grid")
        if int(sampling["frame_step"]) != self.grid.frame_step:
            raise AnnotationError("manifest frame_step does not match supported grid")
        if abs(float(self.manifest["video"]["source_fps"]) - self.grid.source_fps) > 1e-3:
            raise AnnotationError("manifest source_fps does not match supported video")

    def interval_at(self, object_id: str, frame_index: int) -> dict[str, str] | None:
        for row in self.intervals_by_object.get(object_id, []):
            if int(row["start_frame_index"]) <= frame_index <= int(row["end_frame_index"]):
                return row
        return None

    def _anchor_keys(self) -> set[tuple[str, int]]:
        return {
            (object_id, int(anchor["frame_index"]))
            for object_id, anchors in self.anchors.items()
            for anchor in anchors
        }

    def validate_work(self) -> None:
        object_map = self.object_map
        seen: set[tuple[str, int]] = set()
        errors: list[str] = []
        for line_number, row in enumerate(self.observations, start=2):
            object_id = row["gt_object_id"]
            key_label = f"observation row {line_number}"
            if object_id not in object_map:
                errors.append(f"{key_label}: unknown gt_object_id {object_id!r}")
                continue
            try:
                frame = _integer(row["frame_index"], f"{key_label} frame_index")
                x1 = _number(row["x1"], f"{key_label} x1")
                y1 = _number(row["y1"], f"{key_label} y1")
                x2 = _number(row["x2"], f"{key_label} x2")
                y2 = _number(row["y2"], f"{key_label} y2")
                foot_x = _number(row["foot_x"], f"{key_label} foot_x")
                foot_y = _number(row["foot_y"], f"{key_label} foot_y")
            except AnnotationError as exc:
                errors.append(str(exc))
                continue
            key = (object_id, frame)
            if key in seen:
                errors.append(f"{key_label}: duplicate object/frame {key}")
            seen.add(key)
            obj = object_map[object_id]
            interval = self.interval_at(object_id, frame)
            if interval is None or interval["denominator_eligible"].lower() != "true":
                errors.append(f"{key_label}: frame is outside denominator-eligible intervals")
            if row["object_class"] != obj["object_class"]:
                errors.append(f"{key_label}: object_class does not match GT object")
            expected_metadata = {
                "schema_version": self.manifest["schema_version"],
                "gt_dataset_id": self.manifest["gt_dataset_id"],
                "video_id": self.manifest["video"]["video_id"],
            }
            for field, expected in expected_metadata.items():
                if row[field] != expected:
                    errors.append(f"{key_label}: {field} does not match manifest")
            expected_time = frame / self.grid.source_fps
            try:
                if not math.isclose(
                    _number(row["timestamp_seconds"], f"{key_label} timestamp_seconds"),
                    expected_time,
                    rel_tol=0,
                    abs_tol=1e-9,
                ):
                    errors.append(f"{key_label}: timestamp_seconds does not match frame/FPS")
            except AnnotationError as exc:
                errors.append(str(exc))
            if row["visibility_status"] not in VISIBILITY_STATUSES:
                errors.append(f"{key_label}: visibility_status is not observable")
            elif interval and row["visibility_status"] != interval["visibility_status"]:
                errors.append(f"{key_label}: visibility_status does not match canonical GT")
            if row["coordinate_system"] != "source_pixel" or row["position_unit"] != "px":
                errors.append(f"{key_label}: coordinate system or unit is invalid")
            if row["observation_method"] != "manual":
                errors.append(f"{key_label}: only manual observations are allowed")
            if row["interpolation_span_frames"]:
                errors.append(f"{key_label}: manual observations must not have interpolation span")
            if not (0 <= x1 < x2 <= FRAME_WIDTH and 0 <= y1 < y2 <= FRAME_HEIGHT):
                errors.append(f"{key_label}: box is outside frame or has nonpositive size")
            if not (x1 <= foot_x <= x2 and y1 <= foot_y <= y2):
                errors.append(f"{key_label}: foot point must lie inside box")
            if row["in_scope"].lower() != obj["in_scope"].lower():
                errors.append(f"{key_label}: in_scope does not match object")

        skip_seen: set[tuple[str, int]] = set()
        for line_number, row in enumerate(self.skips, start=2):
            object_id = row["gt_object_id"]
            if object_id not in object_map:
                errors.append(f"skip row {line_number}: unknown gt_object_id {object_id!r}")
                continue
            try:
                frame = _integer(row["frame_index"], f"skip row {line_number} frame_index")
            except AnnotationError as exc:
                errors.append(str(exc))
                continue
            key = (object_id, frame)
            if key in skip_seen:
                errors.append(f"skip row {line_number}: duplicate object/frame {key}")
            skip_seen.add(key)
            if key not in self._anchor_keys():
                errors.append(f"skip row {line_number}: frame is not an eligible anchor")
            if row["reason"] not in SKIP_REASONS:
                errors.append(f"skip row {line_number}: unsupported reason {row['reason']!r}")
            if key in seen:
                errors.append(f"skip row {line_number}: anchor has both observation and skip")
        if errors:
            raise AnnotationError("\n".join(errors))

    def summary(self) -> dict[str, object]:
        keys = self._anchor_keys()
        observed = {(row["gt_object_id"], int(row["frame_index"])) for row in self.observations}
        skipped = {(row["gt_object_id"], int(row["frame_index"])) for row in self.skips}
        resolved = observed | skipped
        object_status = []
        for obj in self.objects:
            object_id = obj["gt_object_id"]
            total = len(self.anchors[object_id])
            done = sum((object_id, frame) in resolved for frame in map(
                lambda item: int(item["frame_index"]), self.anchors[object_id]
            ))
            object_status.append(
                {
                    "gt_object_id": object_id,
                    "object_class": obj["object_class"],
                    "notes": obj["notes"],
                    "total": total,
                    "done": done,
                    "complete": done == total,
                }
            )
        return {
            "objects": object_status,
            "anchors": len(keys),
            "observations": len(observed),
            "skips": len(skipped),
            "missing": len(keys - resolved),
        }

    def object_observations(self, object_id: str) -> list[dict[str, str]]:
        return sorted(
            (row for row in self.observations if row["gt_object_id"] == object_id),
            key=lambda row: int(row["frame_index"]),
        )

    def current_observation(self, object_id: str, frame_index: int) -> dict[str, str] | None:
        return next(
            (
                row
                for row in self.observations
                if row["gt_object_id"] == object_id
                and int(row["frame_index"]) == frame_index
            ),
            None,
        )

    def current_skip(self, object_id: str, frame_index: int) -> dict[str, str] | None:
        return next(
            (
                row
                for row in self.skips
                if row["gt_object_id"] == object_id
                and int(row["frame_index"]) == frame_index
            ),
            None,
        )

    def save_observation(
        self,
        object_id: str,
        frame_index: int,
        box: dict[str, float],
        foot: dict[str, float] | None = None,
        notes: str = "",
        copied_from_previous: bool = False,
        foot_adjusted: bool = False,
    ) -> dict[str, str]:
        with self.lock:
            if object_id not in self.object_map:
                raise AnnotationError(f"unknown gt_object_id {object_id!r}")
            anchor_keys = self._anchor_keys()
            if (object_id, frame_index) not in anchor_keys:
                raise AnnotationError("frame is not an eligible anchor for this object")
            interval = self.interval_at(object_id, frame_index)
            if interval is None or interval["visibility_status"] not in VISIBILITY_STATUSES:
                raise AnnotationError("observation frame is not visible or partially occluded")
            x1 = round(_number(str(box.get("x1")), "x1"))
            y1 = round(_number(str(box.get("y1")), "y1"))
            x2 = round(_number(str(box.get("x2")), "x2"))
            y2 = round(_number(str(box.get("y2")), "y2"))
            if not (0 <= x1 < x2 <= FRAME_WIDTH and 0 <= y1 < y2 <= FRAME_HEIGHT):
                raise AnnotationError("box must have positive size inside the 3840x2160 frame")
            foot_x = float(foot["x"]) if foot else (x1 + x2) / 2
            foot_y = float(foot["y"]) if foot else float(y2)
            if not (x1 <= foot_x <= x2 and y1 <= foot_y <= y2):
                raise AnnotationError("foot point must lie inside the box")
            if foot_adjusted:
                notes = _append_note(notes, "foot_adjusted")
            if copied_from_previous:
                notes = _append_note(notes, "copied_from_previous")
            object_row = self.object_map[object_id]
            row = {
                "schema_version": str(self.manifest["schema_version"]),
                "gt_dataset_id": str(self.manifest["gt_dataset_id"]),
                "video_id": str(self.manifest["video"]["video_id"]),
                "gt_object_id": object_id,
                "frame_index": str(frame_index),
                "timestamp_seconds": repr(frame_index / self.grid.source_fps),
                "object_class": object_row["object_class"],
                "x1": str(x1),
                "y1": str(y1),
                "x2": str(x2),
                "y2": str(y2),
                "foot_x": repr(foot_x),
                "foot_y": repr(foot_y),
                "coordinate_system": "source_pixel",
                "position_unit": "px",
                "visibility_status": interval["visibility_status"],
                "observation_method": "manual",
                "interpolation_span_frames": "",
                "in_scope": object_row["in_scope"].lower(),
                "reviewer": REVIEWER,
                "review_status": "draft",
                "review_timestamp_utc": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "notes": notes,
            }
            self.skips = [
                item
                for item in self.skips
                if not (item["gt_object_id"] == object_id and int(item["frame_index"]) == frame_index)
            ]
            self._write(self.skips_path, SKIP_HEADERS, self.skips)
            self.observations = [
                item
                for item in self.observations
                if not (item["gt_object_id"] == object_id and int(item["frame_index"]) == frame_index)
            ]
            self.observations.append(row)
            self.observations.sort(key=lambda item: (item["gt_object_id"], int(item["frame_index"])))
            self._write(self.observations_path, OBSERVATION_HEADERS, self.observations)
            return row

    def save_skip(self, object_id: str, frame_index: int, reason: str, notes: str = "") -> dict[str, str]:
        with self.lock:
            if object_id not in self.object_map or (object_id, frame_index) not in self._anchor_keys():
                raise AnnotationError("skip must refer to an eligible anchor")
            if reason not in SKIP_REASONS:
                raise AnnotationError(f"unsupported skip reason {reason!r}")
            self.observations = [
                item
                for item in self.observations
                if not (item["gt_object_id"] == object_id and int(item["frame_index"]) == frame_index)
            ]
            self.skips = [
                item
                for item in self.skips
                if not (item["gt_object_id"] == object_id and int(item["frame_index"]) == frame_index)
            ]
            row = {
                "gt_object_id": object_id,
                "frame_index": str(frame_index),
                "reason": reason,
                "notes": notes.strip(),
            }
            self.skips.append(row)
            self.skips.sort(key=lambda item: (item["gt_object_id"], int(item["frame_index"])))
            self._write(self.observations_path, OBSERVATION_HEADERS, self.observations)
            self._write(self.skips_path, SKIP_HEADERS, self.skips)
            return row

    @staticmethod
    def _write(path: Path, headers: tuple[str, ...], rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)


def _observation_frame_in_interval(state: AnnotationState, row: dict[str, str]) -> bool:
    interval = state.interval_at(row["gt_object_id"], int(row["frame_index"]))
    return bool(interval and interval["denominator_eligible"].lower() == "true")


def validate_only(state: AnnotationState) -> dict[str, int]:
    """Validate all work rows and report entered, skipped, and missing anchors."""
    state.validate_work()
    summary = state.summary()
    print(
        "annotation validation: OK — "
        f"anchors={summary['anchors']}, observations={summary['observations']}, "
        f"skips={summary['skips']}, missing={summary['missing']}"
    )
    return {
        "anchors": int(summary["anchors"]),
        "observations": int(summary["observations"]),
        "skips": int(summary["skips"]),
        "missing": int(summary["missing"]),
    }


def format_skip_summary(state: AnnotationState) -> str:
    """Validate and format skip rows grouped by object and reason."""
    state.validate_work()
    if not state.skips:
        return "skip summary: 건너뛰기 행이 없습니다."

    grouped: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for row in state.skips:
        grouped[row["gt_object_id"]][row["reason"]].append(int(row["frame_index"]))

    object_classes = {row["gt_object_id"]: row["object_class"] for row in state.objects}
    lines = [
        f"skip summary: {len(state.skips)}행, {len(grouped)}개 객체",
    ]
    reason_order = (
        "not_found",
        "occluded_more_than_marked",
        "ambiguous_identity",
        "other",
    )
    for object_id in (row["gt_object_id"] for row in state.objects if row["gt_object_id"] in grouped):
        reasons = grouped[object_id]
        count = sum(len(frames) for frames in reasons.values())
        lines.append(f"{object_id} ({object_classes[object_id]}): {count}행")
        for reason in reason_order:
            frames = sorted(reasons.get(reason, []))
            if frames:
                frame_list = ", ".join(str(frame) for frame in frames)
                lines.append(f"  {reason} ({len(frames)}): {frame_list}")
    return "\n".join(lines)


def skip_summary_only(state: AnnotationState) -> None:
    """Print the validated skip summary without opening the source video."""
    print(format_skip_summary(state))


PAGE_HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>R01 블라인드 GT 위치 입력</title>
<style>
:root{color-scheme:dark;--bg:#101319;--panel:#1b202a;--line:#3b4657;--text:#f4f6fa;--muted:#b4bdca;--blue:#63b5ff;--yellow:#ffd166;--red:#ff8585}
*{box-sizing:border-box}html,body{width:100%;height:100%;overflow:hidden}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,"Segoe UI",sans-serif}main{width:100vw;height:100vh;max-width:none;margin:0;padding:6px;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;gap:6px}
header,.panel,.toolbar{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px;margin:0}header{display:grid;grid-template-columns:minmax(180px,1fr) auto auto auto;align-items:center;gap:12px}.meta{color:var(--muted);font-size:.92rem}.progress{font-variant-numeric:tabular-nums}
.views{display:grid;grid-template-columns:minmax(0,.82fr) minmax(0,1.18fr);gap:8px;min-height:0}.panel{display:flex;flex-direction:column;min-width:0;min-height:0}.panel h2{font-size:1rem;margin:0 0 6px}.canvas-wrap{position:relative;flex:1;min-height:0;background:#050608;overflow:hidden;border:1px solid var(--line);touch-action:none;display:flex;align-items:center;justify-content:center}.canvas-wrap canvas{display:block;max-width:100%;max-height:100%;cursor:crosshair}.canvas-wrap.overview canvas{cursor:move}.legend{color:var(--muted);font-size:.82rem;margin-top:5px}.toolbar{display:flex;gap:6px;align-items:center;flex-wrap:wrap}button,select,input,textarea{font:inherit;color:var(--text);background:#252d39;border:1px solid var(--line);border-radius:5px;padding:7px}button{cursor:pointer}button:hover{border-color:var(--blue)}button.primary{background:#14578c}.status{min-height:1.5em;color:var(--muted)}.status.error{color:var(--red)}.badge{padding:3px 8px;border:1px solid var(--line);border-radius:20px}.modal{position:fixed;inset:0;background:#0009;display:none;place-items:center;z-index:4}.modal.open{display:grid}.dialog{width:min(480px,calc(100vw - 30px));padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:10px}.dialog label{display:block;margin:12px 0 5px}.dialog textarea{width:100%;min-height:70px}.off{display:none!important}
@media(max-width:1000px){html,body{height:auto;min-height:100%;overflow:auto}main{width:100%;height:auto;min-height:100vh;grid-template-rows:auto auto auto auto}.views{grid-template-columns:1fr}.canvas-wrap{min-height:30vh}header{grid-template-columns:1fr}.toolbar{gap:5px}}
</style></head><body><main>
<header><div><strong>블라인드 GT 위치 입력</strong><div id="objectInfo" class="meta"></div></div>
<div><label for="objectSelect">객체</label> <select id="objectSelect"></select></div>
<div class="progress"><span id="objectProgress"></span><br><span id="totalProgress" class="meta"></span></div><button id="fullScreen">⛶ 전체 화면</button></header>
<section class="toolbar"><span id="anchorLabel" class="badge"></span><span id="visibilityLabel" class="badge"></span>
<button id="prevAnchor">← 이전 앵커</button><button id="nextAnchor">다음 앵커 →</button>
<button id="zoomOut">− 축소</button><button id="zoomIn">+ 확대</button><button id="zoomReset">0 화면 맞춤</button>
<button id="playAround">P ±1초 재생</button><label><input id="showOthers" type="checkbox" checked> 같은 프레임 다른 객체 박스</label>
<button id="copyPrevious">C 직전 박스 복사</button><button id="editFoot">F 발점 수정</button>
<button id="undo">Ctrl+Z 되돌리기</button><button id="redraw">박스 다시 그리기</button><button id="skipButton">K 건너뛰기</button><button id="saveNext" class="primary">Enter 저장 후 다음</button></section>
<section class="views"><div class="panel"><h2>전체 원본 프레임</h2><div class="canvas-wrap overview"><canvas id="overview"></canvas></div><div class="legend">전체 프레임을 클릭하면 확대 중심을 옮깁니다. 파란 사각형은 현재 확대 범위입니다.</div></div>
<div class="panel"><h2>확대 입력창 <span id="zoomLabel" class="meta"></span></h2><div class="canvas-wrap"><canvas id="detail"></canvas></div><div class="legend">박스 안을 드래그하면 박스와 발점이 함께 이동합니다. 박스 밖을 드래그하면 새 박스를 그립니다. 마우스 휠로 포인터 위치를 중심으로 최대 30배까지 확대할 수 있습니다. 발점만 바꾸려면 F를 누르고 박스 안을 클릭합니다.</div></div></section>
<section class="toolbar"><label>메모 <input id="observationNotes" type="text" placeholder="선택 메모"></label><span id="dirtyLabel" class="badge">저장됨</span><span id="status" class="status"></span></section>
<div id="skipModal" class="modal"><div class="dialog"><h2>이 앵커 건너뛰기</h2><label for="skipReason">사유</label><select id="skipReason"><option value="">사유 선택</option><option value="not_found">객체를 찾을 수 없음</option><option value="ambiguous_identity">동일 객체인지 모호함</option><option value="occluded_more_than_marked">기록된 것보다 더 가려짐</option><option value="other">기타</option></select><label for="skipNotes">메모</label><textarea id="skipNotes"></textarea><div class="toolbar"><button id="cancelSkip">취소</button><button id="confirmSkip" class="primary">건너뛰기 저장</button></div></div></div>
</main><script>
"use strict";
const overview=document.getElementById("overview"),detail=document.getElementById("detail"),ctxO=overview.getContext("2d"),ctxD=detail.getContext("2d");
let state=null, objectIndex=0, anchorIndex=0, frame=null, visibility=null, image=null, imageUrl=null, observations=[], others=[], saved=null, previous=null, skip=null;
let zoom=1, center={x:1920,y:1080}, crop=null, box=null, foot=null, dirty=false, drag=null, footMode=false, footAdjusted=false, showOthers=true, copied=false, undoStack=[], playing=false, playbackToken=0;
const objectSelect=document.getElementById("objectSelect"), statusEl=document.getElementById("status");
function key(o,f){return `${o}:${f}`}
function setStatus(message,error=false){statusEl.textContent=message;statusEl.classList.toggle("error",error)}
async function request(url,options={}){const r=await fetch(url,{cache:"no-store",...options});if(!r.ok){const d=await r.json().catch(()=>({error:r.statusText}));throw new Error(d.error||r.statusText)}return r}
function currentObject(){return state.objects[objectIndex]}
function currentAnchor(){return currentObject().anchors[anchorIndex]}
function firstPendingIndex(o){const rows=[...o.observations,...o.skips],done=new Set(rows.map(r=>+r.frame_index));const ix=o.anchors.findIndex(a=>!done.has(+a.frame_index));return ix<0?Math.max(0,o.anchors.length-1):ix}
function updateDirty(){const notes=document.getElementById("observationNotes").value;let matchesSaved=false;if(saved&&box){matchesSaved=box.x1===+saved.x1&&box.y1===+saved.y1&&box.x2===+saved.x2&&box.y2===+saved.y2&&foot&&foot.x===+saved.foot_x&&foot.y===+saved.foot_y&&notes===saved.notes&&copied===saved.notes.includes("copied_from_previous")&&footAdjusted===saved.notes.includes("foot_adjusted")}const matchesSkip=!!skip&&!box&&!foot&&!notes;const empty=!saved&&!skip&&!box&&!foot&&!copied&&!footAdjusted&&!notes;dirty=!(matchesSaved||matchesSkip||empty);document.getElementById("dirtyLabel").textContent=dirty?"저장 전 변경 있음":"저장됨";document.getElementById("dirtyLabel").style.color=dirty?"#ffd166":""}
function markSaved(){dirty=false;undoStack=[];document.getElementById("dirtyLabel").textContent="저장됨";document.getElementById("dirtyLabel").style.color=""}
function fitZoom(){zoom=currentObject().object_class==="person"||currentObject().object_class==="bicycle"?3:1}
window.calculateCrop=(cx,cy,z)=>{const w=Math.max(1,Math.round(3840/z)),h=Math.max(1,Math.round(2160/z));return {left:Math.min(Math.max(0,Math.round(cx-w/2)),3840-w),top:Math.min(Math.max(0,Math.round(cy-h/2)),2160-h),width:w,height:h}}
function drawBox(ctx,b,color,line=4,alpha=1,label=""){if(!b)return;ctx.save();ctx.globalAlpha=alpha;ctx.strokeStyle=color;ctx.lineWidth=line;ctx.strokeRect(b.x1,b.y1,b.x2-b.x1,b.y2-b.y1);if(label){ctx.font=`${Math.max(18,line*5)}px sans-serif`;ctx.lineWidth=3;ctx.strokeStyle="#000";ctx.strokeText(label,b.x1,b.y1-5);ctx.fillStyle=color;ctx.fillText(label,b.x1,b.y1-5)}ctx.restore()}
function drawPoint(ctx,p,color){if(!p)return;ctx.save();ctx.fillStyle=color;ctx.beginPath();ctx.arc(p.x,p.y,Math.max(5,detail.width/500),0,Math.PI*2);ctx.fill();ctx.restore()}
function sourceRectForDisplay(canvas){const r=canvas.getBoundingClientRect();return {left:r.left,top:r.top,width:r.width,height:r.height}}
function render(){if(!image||!crop)return;overview.width=3840;overview.height=2160;ctxO.drawImage(image,0,0,3840,2160);if(showOthers){for(const row of others){drawBox(ctxO,{x1:+row.x1,y1:+row.y1,x2:+row.x2,y2:+row.y2},"#bbb",7,.42,row.gt_object_id)}}if(saved)drawBox(ctxO,{x1:+saved.x1,y1:+saved.y1,x2:+saved.x2,y2:+saved.y2},"#58c0ff",9,.65,currentObject().gt_object_id);if(box)drawBox(ctxO,box,"#ffcf58",10,1);
ctxO.save();ctxO.strokeStyle="#4cc9f0";ctxO.lineWidth=9;ctxO.strokeRect(crop.left,crop.top,crop.width,crop.height);ctxO.restore();
detail.width=crop.width;detail.height=crop.height;ctxD.drawImage(image,crop.left,crop.top,crop.width,crop.height,0,0,crop.width,crop.height);
if(showOthers){for(const row of others){drawBox(ctxD,{x1:+row.x1-crop.left,y1:+row.y1-crop.top,x2:+row.x2-crop.left,y2:+row.y2-crop.top},"#bbb",5,.4,row.gt_object_id)}}
if(previous)drawBox(ctxD,{x1:+previous.x1-crop.left,y1:+previous.y1-crop.top,x2:+previous.x2-crop.left,y2:+previous.y2-crop.top},"#68d7ff",6,.32,"직전");
if(box)drawBox(ctxD,{x1:box.x1-crop.left,y1:box.y1-crop.top,x2:box.x2-crop.left,y2:box.y2-crop.top},"#ffd166",7,1,currentObject().gt_object_id);
if(previous)drawPoint(ctxD,{x:+previous.foot_x-crop.left,y:+previous.foot_y-crop.top},"#68d7ff");if(foot)drawPoint(ctxD,{x:foot.x-crop.left,y:foot.y-crop.top},"#ff5678");
document.getElementById("zoomLabel").textContent=`${zoom.toFixed(1)}× · source ${crop.width}×${crop.height}`}
function updateObjectInfo(){const o=currentObject(),anchors=o.anchors;document.getElementById("objectInfo").textContent=`${o.gt_object_id} · ${o.object_class}${o.notes?" · "+o.notes:""}`;document.getElementById("objectProgress").textContent=`객체 ${o.done}/${o.total} ${o.complete?"완료":"미완료"}`;document.getElementById("totalProgress").textContent=`전체 ${state.summary.observations+state.summary.skips}/${state.summary.anchors} · 미입력 ${state.summary.missing}`;objectSelect.value=o.gt_object_id;if(!anchors.length){document.getElementById("anchorLabel").textContent="분모 포함 앵커 없음";return}document.getElementById("anchorLabel").textContent=`앵커 ${anchorIndex+1}/${anchors.length} · source frame ${frame}`;document.getElementById("visibilityLabel").textContent=visibility||""}
function restoreAnchor(){const a=currentAnchor();if(!a){box=null;saved=null;previous=null;skip=null;observations=[];others=[];visibility="";updateObjectInfo();render();return}frame=+a.frame_index;const o=currentObject();const savedForAnchor=o.observations.find(r=>+r.frame_index===frame)||null;const skipped=o.skips.find(r=>+r.frame_index===frame)||null;saved=savedForAnchor;skip=skipped;box=saved?{x1:+saved.x1,y1:+saved.y1,x2:+saved.x2,y2:+saved.y2}:null;foot=saved?{x:+saved.foot_x,y:+saved.foot_y}:null;copied=!!(saved&&saved.notes.includes("copied_from_previous"));footAdjusted=!!(saved&&saved.notes.includes("foot_adjusted"));document.getElementById("observationNotes").value=saved?saved.notes:"";const prior=o.observations.filter(r=>+r.frame_index<frame);observations=prior;previous=prior.length?prior[prior.length-1]:null;visibility=a.visibility_status;others=(state.sameFrame[String(frame)]||[]).filter(r=>r.gt_object_id!==o.gt_object_id);const centerGuess=state.predictedCenter[String(frame)];if(saved){center={x:(+saved.x1 + +saved.x2)/2,y:(+saved.y1 + +saved.y2)/2}}else if(centerGuess){center={x:centerGuess[0],y:centerGuess[1]}}else if(previous){center={x:(+previous.x1 + +previous.x2)/2,y:(+previous.y1 + +previous.y2)/2}}else{center={x:1920,y:1080}}crop=window.calculateCrop(center.x,center.y,zoom);markSaved();updateObjectInfo();loadFrame();}
async function loadFrame(quality="full",sourceFrame=frame){try{const url=`/api/frame/${sourceFrame}?quality=${quality}&left=${crop.left}&top=${crop.top}&width=${crop.width}&height=${crop.height}`;const r=await request(url);const blob=await r.blob();const nextUrl=URL.createObjectURL(blob);const next=new Image();await new Promise((resolve,reject)=>{next.onload=resolve;next.onerror=reject;next.src=nextUrl});if(imageUrl)URL.revokeObjectURL(imageUrl);imageUrl=nextUrl;image=next;if(quality==="play"){detail.width=1280;detail.height=Math.round(1280*crop.height/crop.width);ctxD.drawImage(image,0,0,detail.width,detail.height);document.getElementById("anchorLabel").textContent=`원본 재생 · frame ${sourceFrame}`;return}render();updateObjectInfo()}catch(e){setStatus(e.message,true)}}
function payload(){return {gt_object_id:currentObject().gt_object_id,frame_index:frame,box,foot,notes:document.getElementById("observationNotes").value,copied_from_previous:copied,foot_adjusted:footAdjusted}}
function localCanLeave(){if(!dirty)return true;return window.confirm("저장되지 않은 입력이 있습니다. 저장하지 않고 이동할까요?")}
function refreshObjectList(){const select=document.getElementById("objectSelect");select.innerHTML=state.objects.map(o=>`<option value="${o.gt_object_id}">${o.complete?"✓":"○"} ${o.gt_object_id} · ${o.object_class} (${o.done}/${o.total})</option>`).join("");select.value=currentObject().gt_object_id}
async function reloadState(){const r=await request(`/api/state?object_id=${encodeURIComponent(currentObject().gt_object_id)}&frame_index=${frame||0}`);state=await r.json();refreshObjectList()}
async function moveAnchor(delta){if(!localCanLeave())return;const list=currentObject().anchors;const next=Math.max(0,Math.min(list.length-1,anchorIndex+delta));if(next===anchorIndex)return;anchorIndex=next;await reloadState();restoreAnchor()}
async function moveObject(delta){if(!localCanLeave())return;const next=Math.max(0,Math.min(state.objects.length-1,objectIndex+delta));if(next===objectIndex)return;objectIndex=next;anchorIndex=firstPendingIndex(currentObject());fitZoom();await reloadState();restoreAnchor()}
async function moveToObject(id){if(!localCanLeave()){objectSelect.value=currentObject().gt_object_id;return}const found=state.objects.findIndex(o=>o.gt_object_id===id);if(found<0)return;objectIndex=found;anchorIndex=firstPendingIndex(currentObject());fitZoom();await reloadState();restoreAnchor()}
async function saveAndAdvance(){if(skip){if(anchorIndex<currentObject().anchors.length-1){anchorIndex++;await reloadState();restoreAnchor()}else{setStatus("현재 객체의 마지막 앵커입니다.")}return}if(!box)return setStatus("박스가 없습니다. 드래그로 입력하거나 K로 건너뛰기 사유를 선택하세요.",true);if(foot&&(foot.x<box.x1||foot.x>box.x2||foot.y<box.y1||foot.y>box.y2))return setStatus("발점이 박스 밖입니다. F를 누르고 확대창에서 박스 안을 클릭하세요.",true);try{const r=await request("/api/observation",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload())});const savedRow=await r.json();saved=savedRow.row;dirty=false;markSaved();setStatus("관측행 저장됨");await reloadState();if(anchorIndex<currentObject().anchors.length-1){anchorIndex++;restoreAnchor()}else{updateObjectInfo()}}catch(e){setStatus(e.message,true)}}
function markUndo(){undoStack.push({box:box?{...box}:null,foot:foot?{...foot}:null,skip:skip?{...skip}:null,copied,footAdjusted,notes:document.getElementById("observationNotes").value});if(undoStack.length>10)undoStack.shift()}
function undo(){if(!undoStack.length)return setStatus("되돌릴 입력이 없습니다.");const s=undoStack.pop();box=s.box;foot=s.foot;skip=s.skip;copied=s.copied;footAdjusted=s.footAdjusted;document.getElementById("observationNotes").value=s.notes;updateDirty();render()}
function drawRectStart(e){const r=detail.getBoundingClientRect();const scaleX=crop.width/r.width,scaleY=crop.height/r.height;const x=(e.clientX-r.left)*scaleX+crop.left,y=(e.clientY-r.top)*scaleY+crop.top;return {x,y}}
function zoomAroundPointer(e,factor){if(!crop)return;const r=detail.getBoundingClientRect(),p=drawRectStart(e),ratioX=(e.clientX-r.left)/r.width,ratioY=(e.clientY-r.top)/r.height;zoom=Math.max(1,Math.min(30,zoom*factor));const w=Math.round(3840/zoom),h=Math.round(2160/zoom);center={x:p.x+(0.5-ratioX)*w,y:p.y+(0.5-ratioY)*h};crop=window.calculateCrop(center.x,center.y,zoom);render();setStatus(`확대 ${zoom.toFixed(1)}× · 휠로 확대/축소`)}
detail.addEventListener("wheel",e=>{e.preventDefault();zoomAroundPointer(e,e.deltaY<0?1.2:1/1.2)},{passive:false});
detail.addEventListener("pointerdown",e=>{if(playing)return;detail.setPointerCapture(e.pointerId);const p=drawRectStart(e);if(footMode){if(!box){footMode=false;return setStatus("먼저 박스를 그린 뒤 F를 눌러 발점을 수정하세요.",true)}if(p.x<box.x1||p.x>box.x2||p.y<box.y1||p.y>box.y2)return setStatus("발점은 박스 안에서 클릭하세요. 확대하려면 마우스 휠을 사용하세요.",true);markUndo();foot=p;footAdjusted=true;footMode=false;updateDirty();render();setStatus("발점 수정됨");return}markUndo();const inBox=box&&p.x>=box.x1&&p.x<=box.x2&&p.y>=box.y1&&p.y<=box.y2;drag=inBox?{mode:"move",start:p,current:p,originalBox:{...box},originalFoot:foot?{...foot}:null,changed:false}:{mode:"draw",start:p,current:p,changed:false}});
detail.addEventListener("pointermove",e=>{if(!drag){const p=drawRectStart(e);detail.style.cursor=box&&p.x>=box.x1&&p.x<=box.x2&&p.y>=box.y1&&p.y<=box.y2?"move":"crosshair";return}drag.current=drawRectStart(e);const dx=drag.current.x-drag.start.x,dy=drag.current.y-drag.start.y;if(Math.abs(dx)+Math.abs(dy)<1)return;drag.changed=true;skip=null;if(drag.mode==="move"){const b=drag.originalBox,w=b.x2-b.x1,h=b.y2-b.y1,x1=Math.min(Math.max(0,b.x1+dx),3840-w),y1=Math.min(Math.max(0,b.y1+dy),2160-h),actualX=x1-b.x1,actualY=y1-b.y1;box={x1,y1,x2:x1+w,y2:y1+h};if(drag.originalFoot)foot={x:drag.originalFoot.x+actualX,y:drag.originalFoot.y+actualY}}else{const a=drag.start,b=drag.current;footAdjusted=false;box={x1:Math.min(a.x,b.x),y1:Math.min(a.y,b.y),x2:Math.max(a.x,b.x),y2:Math.max(a.y,b.y)};foot={x:(box.x1+box.x2)/2,y:box.y2}}updateDirty();render()});
detail.addEventListener("pointerup",()=>{if(!drag)return;const changed=drag.changed,mode=drag.mode;drag=null;if(changed&&box&&box.x2-box.x1>=1&&box.y2-box.y1>=1){updateDirty();setStatus(mode==="move"?"박스와 발점을 함께 이동했습니다 · Enter로 저장":"박스 입력됨 · Enter로 저장")}else{if(!changed)undoStack.pop();else if(mode==="draw"){box=null;foot=null;updateDirty()}render()}});
overview.addEventListener("click",e=>{if(playing)return;const r=overview.getBoundingClientRect();const p=drawRectStartForOverview(e,r);center=p;crop=window.calculateCrop?window.calculateCrop(center.x,center.y,zoom):{left:Math.max(0,Math.round(center.x-1920/zoom)),top:Math.max(0,Math.round(center.y-1080/zoom)),width:Math.round(3840/zoom),height:Math.round(2160/zoom)};render()});
function drawRectStartForOverview(e,r){return {x:(e.clientX-r.left)*3840/r.width,y:(e.clientY-r.top)*2160/r.height}}
document.getElementById("showOthers").addEventListener("change",e=>{showOthers=e.target.checked;render()});
document.getElementById("objectSelect").addEventListener("change",e=>moveToObject(e.target.value));
document.getElementById("prevAnchor").onclick=()=>moveAnchor(-1);document.getElementById("nextAnchor").onclick=()=>moveAnchor(1);
document.getElementById("zoomIn").onclick=()=>{zoom=Math.min(12,zoom*1.5);crop=window.calculateCrop?window.calculateCrop(center.x,center.y,zoom):crop;render()};
document.getElementById("zoomOut").onclick=()=>{zoom=Math.max(1,zoom/1.5);crop=window.calculateCrop?window.calculateCrop(center.x,center.y,zoom):crop;render()};
document.getElementById("zoomReset").onclick=()=>{fitZoom();crop=window.calculateCrop?window.calculateCrop(center.x,center.y,zoom):crop;render()};
document.getElementById("editFoot").onclick=()=>{footMode=!footMode;setStatus(footMode?"확대 입력창에서 새 발점을 클릭하세요.":"발점 수정 모드를 종료했습니다.")};
document.getElementById("redraw").onclick=()=>{markUndo();box=null;foot=null;skip=null;copied=false;footAdjusted=false;updateDirty();render()};document.getElementById("undo").onclick=undo;
document.getElementById("copyPrevious").onclick=()=>{const prev=currentObject().observations.filter(r=>+r.frame_index<frame).sort((a,b)=>+b.frame_index-+a.frame_index)[0];if(!prev)return setStatus("복사할 직전 GT 박스가 없습니다.",true);markUndo();skip=null;box={x1:+prev.x1,y1:+prev.y1,x2:+prev.x2,y2:+prev.y2};foot={x:+prev.foot_x,y:+prev.foot_y};copied=true;footAdjusted=prev.notes.includes("foot_adjusted");updateDirty();render();setStatus("직전 박스를 복사했습니다. Enter로 확정하면 notes에 copied_from_previous가 기록됩니다.")};
document.getElementById("saveNext").onclick=saveAndAdvance;
document.getElementById("observationNotes").addEventListener("input",updateDirty);
document.getElementById("skipButton").onclick=()=>{if(!localCanLeave())return;document.getElementById("skipModal").classList.add("open")};document.getElementById("cancelSkip").onclick=()=>document.getElementById("skipModal").classList.remove("open");
document.getElementById("confirmSkip").onclick=async()=>{const reason=document.getElementById("skipReason").value;if(!reason)return setStatus("건너뛰기 사유를 선택하세요.",true);try{await request("/api/skip",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({gt_object_id:currentObject().gt_object_id,frame_index:frame,reason,notes:document.getElementById("skipNotes").value})});document.getElementById("skipModal").classList.remove("open");skip={reason};await reloadState();if(anchorIndex<currentObject().anchors.length-1){anchorIndex++;fitZoom();restoreAnchor()}else{updateObjectInfo();setStatus("건너뛰기 저장됨")}}catch(e){setStatus(e.message,true)}};
async function playAround(){if(playing){playing=false;playbackToken++;await loadFrame("full");return}if(dirty&&!localCanLeave())return;playing=true;const token=++playbackToken;const radius=Math.round(state.sourceFps),first=Math.max(0,frame-radius),last=Math.min(state.frameCount-1,frame+radius),started=performance.now();for(let f=first;f<=last;f++){if(!playing||token!==playbackToken)break;await loadFrame("play",f);const delay=started+(f-first+1)*1000/state.sourceFps-performance.now();if(delay>0)await new Promise(r=>setTimeout(r,delay))}playing=false;if(token===playbackToken){await loadFrame("full");setStatus("원본 ±1초 재생이 끝났습니다.")}}
document.getElementById("playAround").onclick=playAround;
document.getElementById("fullScreen").onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}catch(e){setStatus(`전체 화면 전환 실패: ${e.message}`,true)}};
window.addEventListener("resize",()=>{if(image)render()});document.addEventListener("fullscreenchange",()=>{if(image)render()});
document.addEventListener("keydown",e=>{if(["INPUT","TEXTAREA","SELECT"].includes(e.target.tagName))return;if(e.key==="ArrowLeft")moveAnchor(-1);else if(e.key==="ArrowRight")moveAnchor(1);else if(e.key==="Enter"){e.preventDefault();saveAndAdvance()}else if(e.key.toLowerCase()==="k")document.getElementById("skipButton").click();else if(e.key.toLowerCase()==="n")moveObject(e.shiftKey?-1:1);else if(e.key.toLowerCase()==="f")document.getElementById("editFoot").click();else if(e.key.toLowerCase()==="c")document.getElementById("copyPrevious").click();else if(e.key.toLowerCase()==="p")playAround();else if(e.ctrlKey&&e.key.toLowerCase()==="z"){e.preventDefault();undo()}else if(e.key==="+")document.getElementById("zoomIn").click();else if(e.key==="-")document.getElementById("zoomOut").click();else if(e.key==="0")document.getElementById("zoomReset").click();else if(e.key==="Escape"){drag=null;footMode=false;setStatus("현재 동작을 취소했습니다.")}});
window.addEventListener("beforeunload",e=>{if(dirty){e.preventDefault();e.returnValue=""}});
async function init(){try{const r=await request("/api/state");state=await r.json();if(!state.objects.length)throw new Error("입력할 객체가 없습니다.");objectIndex=state.resume.objectIndex;anchorIndex=state.resume.anchorIndex;fitZoom();await reloadState();refreshObjectList();restoreAnchor()}catch(e){setStatus(e.message,true)}}
init();
</script></body></html>"""


def state_payload(state: AnnotationState, object_id: str = "", frame_index: int = 0) -> dict[str, object]:
    summary = state.summary()
    status_by_obj = {row["gt_object_id"]: row for row in summary["objects"]}
    objects = []
    resume_object = 0
    resume_anchor = 0
    for index, obj in enumerate(state.objects):
        object_key = obj["gt_object_id"]
        anchors = state.anchors[object_key]
        saved_rows = state.object_observations(object_key)
        skips = [r for r in state.skips if r["gt_object_id"] == object_key]
        objects.append(
            {
                **status_by_obj[object_key],
                "anchors": anchors,
                "observations": saved_rows,
                "skips": skips,
            }
        )
        if object_key == object_id:
            resume_object = index
            existing = {(r["gt_object_id"], int(r["frame_index"])) for r in state.observations + state.skips}
            unresolved = [
                i
                for i, anchor in enumerate(anchors)
                if (object_key, int(anchor["frame_index"])) not in existing
            ]
            resume_anchor = unresolved[0] if unresolved else max(0, len(anchors) - 1)
    if not object_id:
        existing = {(r["gt_object_id"], int(r["frame_index"])) for r in state.observations + state.skips}
        first_pending = next(
            (
                (i, j)
                for i, obj in enumerate(objects)
                for j, anchor in enumerate(obj["anchors"])
                if (obj["gt_object_id"], int(anchor["frame_index"])) not in existing
            ),
            (0, 0),
        )
        resume_object, resume_anchor = first_pending
    all_observations = state.observations
    same_frame = defaultdict(list)
    for row in all_observations:
        same_frame[row["frame_index"]].append(row)
    predicted: dict[int, tuple[float, float]] = {}
    if object_id in state.object_map:
        for anchor in state.anchors[object_id]:
            frame = int(anchor["frame_index"])
            center = predict_zoom_center(state.object_observations(object_id), frame)
            if center:
                predicted[frame] = center
    video_metadata = state.manifest["video"]
    return {
        "objects": objects,
        "summary": summary,
        "sourceFps": state.grid.source_fps,
        "frameCount": int(video_metadata["source_frame_count"]),
        "resume": {
            "objectIndex": resume_object,
            "anchorIndex": resume_anchor,
            "observations": objects[resume_object]["observations"] if objects else [],
            "skips": objects[resume_object]["skips"] if objects else [],
        },
        "sameFrame": {key: rows for key, rows in same_frame.items()},
        "predictedCenter": {str(frame): center for frame, center in predicted.items()},
        "currentFrame": frame_index,
    }


class AnnotationServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: AnnotationState, reader: FrameReader) -> None:
        super().__init__(address, AnnotationHandler)
        self.state = state
        self.reader = reader


class AnnotationHandler(BaseHTTPRequestHandler):
    server: AnnotationServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            return self._send(HTTPStatus.OK, PAGE_HTML.encode(), "text/html; charset=utf-8")
        if parsed.path == "/api/state":
            object_id = query.get("object_id", [""])[0]
            try:
                frame = int(query.get("frame_index", ["0"])[0])
                return self._json(HTTPStatus.OK, state_payload(self.server.state, object_id, frame))
            except (ValueError, AnnotationError) as exc:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        if parsed.path.startswith("/api/frame/"):
            return self._frame(parsed.path, query)
        if parsed.path == "/healthz":
            return self._json(HTTPStatus.OK, {"status": "ok"})
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/observation":
                row = self.server.state.save_observation(
                    payload["gt_object_id"],
                    int(payload["frame_index"]),
                    payload["box"],
                    payload.get("foot"),
                    str(payload.get("notes", "")),
                    bool(payload.get("copied_from_previous", False)),
                    bool(payload.get("foot_adjusted", False)),
                )
                return self._json(HTTPStatus.OK, {"row": row})
            if self.path == "/api/skip":
                row = self.server.state.save_skip(
                    payload["gt_object_id"],
                    int(payload["frame_index"]),
                    payload["reason"],
                    str(payload.get("notes", "")),
                )
                return self._json(HTTPStatus.OK, {"row": row})
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError, AnnotationError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _frame(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            frame_index = int(path.removeprefix("/api/frame/"))
            if frame_index < 0 or frame_index >= self.server.reader.frame_count:
                raise ValueError("source frame is outside video")
            quality = query.get("quality", ["full"])[0]
            if quality not in {"full", "play"}:
                raise ValueError("quality must be full or play")
            frame = self.server.reader.read(frame_index)
            if quality == "play":
                left = int(query.get("left", ["0"])[0])
                top = int(query.get("top", ["0"])[0])
                width = int(query.get("width", [str(frame.shape[1])])[0])
                height = int(query.get("height", [str(frame.shape[0])])[0])
                if left < 0 or top < 0 or width < 1 or height < 1 or left + width > frame.shape[1] or top + height > frame.shape[0]:
                    raise ValueError("playback crop is outside frame")
                frame = frame[top : top + height, left : left + width]
                out_height = max(1, round(frame.shape[0] * PLAYBACK_WIDTH / frame.shape[1]))
                frame = cv2.resize(frame, (PLAYBACK_WIDTH, out_height), interpolation=cv2.INTER_AREA)
                jpeg_quality = 86
            else:
                jpeg_quality = 94
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
            if not ok:
                raise RuntimeError("cannot encode frame")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Source-Frame", str(frame_index))
            self.end_headers()
            self.wfile.write(encoded.tobytes())
        except (ValueError, RuntimeError, OSError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _json(self, status: HTTPStatus, payload: object) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message: str, *args: object) -> None:
        print(f"blind box input: {self.address_string()} {message % args}")


def run_box_mode(args: argparse.Namespace) -> None:
    state = AnnotationState.from_paths()
    if args.validate_only:
        validate_only(state)
        return
    if args.skip_summary:
        skip_summary_only(state)
        return
    reader = FrameReader(args.video, cache_size=4)
    if (reader.width, reader.height) != (FRAME_WIDTH, FRAME_HEIGHT):
        raise SystemExit(f"blind pilot requires {FRAME_WIDTH}x{FRAME_HEIGHT}; got {reader.width}x{reader.height}")
    if abs(reader.fps - state.grid.source_fps) > 1e-3:
        raise SystemExit(f"video FPS {reader.fps} does not match manifest {state.grid.source_fps}")
    if reader.frame_count < state.grid.end_frame + 1:
        raise SystemExit(f"video does not contain evaluation frame {state.grid.end_frame}")
    server = AnnotationServer((args.host, args.port), state, reader)
    print(f"blind GT box input: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        reader.close()
