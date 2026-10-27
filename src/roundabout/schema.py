"""Stable result schemas shared by analysis and the demo."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


ObjectClass = Literal[
    "person", "bicycle", "motorcycle", "car", "bus", "truck", "tricycle"
]
ConflictType = Literal["pedestrian_vehicle", "vehicle_vehicle"]
ValidationStatus = Literal["unreviewed", "confirmed", "rejected", "uncertain"]


@dataclass(frozen=True)
class TrackPoint:
    video_id: str
    frame_index: int
    timestamp_seconds: float
    track_id: int
    object_class: ObjectClass
    x: float
    y: float
    confidence: float
    coordinate_system: str


@dataclass(frozen=True)
class ConflictEvent:
    event_id: str
    video_id: str
    timestamp_seconds: float
    frame_index: int
    conflict_type: ConflictType
    first_track_id: int
    second_track_id: int
    roi_id: str
    x: float
    y: float
    pet_seconds: float | None
    ttc_seconds: float | None
    crossing_angle_degrees: float | None
    validation_status: ValidationStatus = "unreviewed"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
