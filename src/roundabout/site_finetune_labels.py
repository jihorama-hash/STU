"""Safety checks and label schema for the TASK-009 site fine-tuning pilot."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np


CLASS_IDS = {
    "person": 0,
    "bicycle": 1,
    "car": 2,
    "motorcycle": 3,
    "bus": 5,
    "truck": 7,
}
ALLOWED_SPLITS = {"train", "validation"}
ALLOWED_ATTRIBUTES = {"umbrella", "pm", "truncated"}
ALLOWED_SOURCES = {"model_draft", "manual"}
ALLOWED_ACTIONS = {"kept", "adjusted", "redrawn", "new"}


class LabelValidationError(ValueError):
    """Raised when a frame or label violates the training-label contract."""


def next_unique_object_id(boxes: list[dict[str, Any]], clip_id: str,
                         frame_index: int) -> str:
    """Return an unused frame-local ID for a newly drawn box."""
    prefix = f"{clip_id}_{frame_index}_"
    used = {str(box.get("object_id", "")) for box in boxes}
    suffixes = [
        int(match.group(1)) for object_id in used
        if (match := re.fullmatch(re.escape(prefix) + r"(\d+)", object_id))
    ]
    number = max(suffixes, default=0) + 1
    candidate = f"{prefix}{number:02d}"
    while candidate in used:
        number += 1
        candidate = f"{prefix}{number:02d}"
    return candidate


def reassign_duplicate_object_ids(boxes: list[dict[str, Any]], clip_id: str,
                                  frame_index: int) -> int:
    """Give duplicate IDs fresh values without changing any other box fields."""
    seen: set[str] = set()
    used = {str(box.get("object_id", "")) for box in boxes}
    changed = 0
    for box in boxes:
        object_id = str(box.get("object_id", ""))
        if object_id not in seen:
            seen.add(object_id)
            continue
        # Reserve all existing IDs while finding a new value, including IDs
        # that appear later in this list.
        fresh = next_unique_object_id([{"object_id": value} for value in used],
                                      clip_id, frame_index)
        box["object_id"] = fresh
        used.add(fresh)
        seen.add(fresh)
        changed += 1
    return changed


def box_iou(first: dict[str, Any], second: dict[str, Any]) -> float:
    """Compute intersection over union for source-coordinate boxes."""
    ix1 = max(float(first["x1"]), float(second["x1"]))
    iy1 = max(float(first["y1"]), float(second["y1"]))
    ix2 = min(float(first["x2"]), float(second["x2"]))
    iy2 = min(float(first["y2"]), float(second["y2"]))
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_first = (float(first["x2"]) - float(first["x1"])) * (
        float(first["y2"]) - float(first["y1"]))
    area_second = (float(second["x2"]) - float(second["x1"])) * (
        float(second["y2"]) - float(second["y1"]))
    union = area_first + area_second - intersection
    return intersection / union if union > 0 else 0.0


def suppress_duplicate_drafts(boxes: list[dict[str, Any]],
                              iou_threshold: float = 0.9) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Suppress class-agnostic near-duplicate model drafts by confidence."""
    if not 0.0 <= iou_threshold <= 1.0:
        raise ValueError("IoU threshold must be between 0 and 1")
    indexed_drafts = [(i, box) for i, box in enumerate(boxes)
                      if box.get("label_source") == "model_draft"]
    accepted: list[tuple[int, dict[str, Any]]] = []
    suppressed: list[tuple[int, dict[str, Any]]] = []
    for index, box in sorted(indexed_drafts,
                             key=lambda item: (-float(item[1].get("confidence", 0.0)), item[0])):
        if any(box_iou(box, keep) >= iou_threshold for _, keep in accepted):
            suppressed.append((index, box))
        else:
            accepted.append((index, box))
    retained_indexes = {index for index, _ in accepted}
    retained = [box for index, box in enumerate(boxes)
                if box.get("label_source") != "model_draft" or index in retained_indexes]
    return retained, [box for _, box in sorted(suppressed)]


def mark_frame_reviewed(frame: dict[str, Any], reviewed_at: str) -> None:
    """Mark a user-confirmed frame complete and retain untouched drafts as labels."""
    for label in frame.get("objects", []):
        if label.get("label_source") == "model_draft":
            label["label_source"] = "manual"
            label["revision_action"] = "kept"
    frame["reviewed"] = True
    frame["reviewed_at"] = reviewed_at


def load_frame_whitelist(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    """Load allowed frame IDs; test and excluded splits are rejected."""
    allowed: dict[tuple[str, int], dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            clip = row["clip_id"]
            frame = int(row["frame_index"])
            split = row["split"]
            if split not in ALLOWED_SPLITS:
                raise LabelValidationError(f"forbidden split in frame list: {split}")
            key = (clip, frame)
            if key in allowed:
                raise LabelValidationError(f"duplicate frame: {clip}@{frame}")
            allowed[key] = row
    return allowed


def assert_frame_allowed(
    whitelist: dict[tuple[str, int], dict[str, str]], clip_id: str, frame_index: int
) -> dict[str, str]:
    try:
        return whitelist[(clip_id, int(frame_index))]
    except KeyError as exc:
        raise LabelValidationError(
            f"frame is not in the approved train/validation list: {clip_id}@{frame_index}"
        ) from exc


def mask_outside_polygon(frame: np.ndarray, polygon_mask: np.ndarray,
                         boxes: list[dict[str, Any]], gray: int = 96) -> np.ndarray:
    """Gray outside the polygon while restoring pixels covered by labeled boxes."""
    if frame.ndim != 3 or polygon_mask.shape != frame.shape[:2]:
        raise LabelValidationError("frame and polygon mask dimensions must match")
    result = frame.copy()
    outside = polygon_mask == 0
    result[outside] = gray
    # Ignore boxes are explicitly masked, then valid labeled boxes are restored
    # last so an overlapping visible object remains available for learning.
    for obj in boxes:
        if not obj.get("ignore", False):
            continue
        x1, y1, x2, y2 = [int(round(float(obj[k]))) for k in ("x1", "y1", "x2", "y2")]
        x1, x2 = sorted((max(0, x1), min(frame.shape[1], x2)))
        y1, y2 = sorted((max(0, y1), min(frame.shape[0], y2)))
        if x2 > x1 and y2 > y1:
            result[y1:y2, x1:x2] = gray
    for obj in boxes:
        if obj.get("ignore", False):
            continue
        x1, y1, x2, y2 = [int(round(float(obj[k]))) for k in ("x1", "y1", "x2", "y2")]
        x1, x2 = sorted((max(0, x1), min(frame.shape[1], x2)))
        y1, y2 = sorted((max(0, y1), min(frame.shape[0], y2)))
        if x2 > x1 and y2 > y1:
            result[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
    return result


def validate_label_record(record: dict[str, Any], width: int, height: int) -> None:
    required = {"object_id", "class_name", "class_id", "x1", "y1", "x2", "y2", "ignore",
                "attributes", "label_source", "revision_action"}
    missing = required - record.keys()
    if missing:
        raise LabelValidationError(f"missing label fields: {sorted(missing)}")
    if record["class_name"] not in CLASS_IDS:
        raise LabelValidationError(f"unsupported class: {record['class_name']}")
    if record["class_id"] != CLASS_IDS[record["class_name"]]:
        raise LabelValidationError("class_id must preserve the approved COCO80 index")
    try:
        x1, y1, x2, y2 = (float(record[k]) for k in ("x1", "y1", "x2", "y2"))
    except (TypeError, ValueError) as exc:
        raise LabelValidationError("box coordinates must be numeric") from exc
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise LabelValidationError("box must be non-empty and within source frame bounds")
    if not isinstance(record["ignore"], bool):
        raise LabelValidationError("ignore must be boolean")
    if not isinstance(record["attributes"], list) or set(record["attributes"]) - ALLOWED_ATTRIBUTES:
        raise LabelValidationError("attributes must be a list of approved attribute names")
    if record["label_source"] not in ALLOWED_SOURCES:
        raise LabelValidationError("label_source must be model_draft or manual")
    if record["revision_action"] not in ALLOWED_ACTIONS:
        raise LabelValidationError("revision_action is not an approved value")


def validate_box_in_polygon(record: dict[str, Any], polygon_mask: np.ndarray) -> None:
    """Require the box center to lie inside the approved TASK-009 polygon."""
    x = int(round((float(record["x1"]) + float(record["x2"])) / 2))
    y = int(round((float(record["y1"]) + float(record["y2"])) / 2))
    x = min(polygon_mask.shape[1] - 1, max(0, x))
    y = min(polygon_mask.shape[0] - 1, max(0, y))
    if polygon_mask[y, x] == 0:
        raise LabelValidationError("box center is outside the approved analysis polygon")


def merge_boxes(boxes: list[dict[str, Any]], object_ids: list[str],
                target_class: str) -> list[dict[str, Any]]:
    """Replace selected boxes with one union box of a two-wheeler class."""
    if target_class not in {"motorcycle", "bicycle"}:
        raise LabelValidationError("merge target must be motorcycle or bicycle")
    selected = [box for box in boxes if box["object_id"] in set(object_ids)]
    if len(selected) < 2 or len(selected) != len(set(object_ids)):
        raise LabelValidationError("select at least two distinct existing boxes")
    merged = {
        "object_id": "merge-" + "-".join(sorted(object_ids)),
        "class_name": target_class,
        "class_id": CLASS_IDS[target_class],
        "x1": min(float(b["x1"]) for b in selected),
        "y1": min(float(b["y1"]) for b in selected),
        "x2": max(float(b["x2"]) for b in selected),
        "y2": max(float(b["y2"]) for b in selected),
        "ignore": any(bool(b["ignore"]) for b in selected),
        "attributes": sorted({a for b in selected for a in b.get("attributes", [])}),
        "label_source": "manual",
        "revision_action": "adjusted",
        "merged_from": sorted(object_ids),
    }
    return [b for b in boxes if b["object_id"] not in set(object_ids)] + [merged]


def load_label_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "site_finetune_frame_labels_v1", "frames": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "site_finetune_frame_labels_v1":
        raise LabelValidationError("unsupported label file schema")
    if not isinstance(payload.get("frames"), dict):
        raise LabelValidationError("frames must be a mapping")
    return payload


def polygon_from_mask(mask_path: Path, radius_px: int) -> np.ndarray:
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(mask_path)
    original = (mask > 0).astype(np.uint8) * 255
    if radius_px == 0:
        return original
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (radius_px * 2 + 1, radius_px * 2 + 1)
    )
    return cv2.dilate(original, kernel)
