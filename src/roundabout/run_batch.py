"""Run the validated detection-to-risk pipeline with safe resume support."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .paths import project_root


STAGE_MODULES = {
    "detect": "roundabout.detect_track",
    "filter": "roundabout.filter_tracks",
    "merge": "roundabout.merge_track_fragments",
    "risk": "roundabout.analyze_risk",
}


class BatchConfigurationError(ValueError):
    """Raised when batch inputs or configuration are inconsistent."""


@dataclass(frozen=True)
class VideoJob:
    video_id: str
    filename: str
    video_sha256: str
    end_seconds: float
    video_path: Path
    roadway_mask: Path
    exclusion_mask: Path
    work_dir: Path
    risk_dir: Path


@dataclass(frozen=True)
class BatchSpec:
    root: Path
    config: dict[str, object]
    config_path: Path
    weights: Path
    zones: Path
    homographies: Path
    jobs: tuple[VideoJob, ...]


@dataclass(frozen=True)
class StagePlan:
    video_id: str
    name: str
    command: tuple[str, ...]
    outputs: tuple[Path, ...]
    signature: str
    validator: Callable[[], bool]


@dataclass(frozen=True)
class StageAction:
    plan: StagePlan
    run: bool
    reason: str


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchConfigurationError(f"Cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BatchConfigurationError(f"Expected a JSON object: {path}")
    return value


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise BatchConfigurationError(f"Missing {label}: {path}")
    return path


def _project_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _signature(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_batch_spec(
    config_path: str | Path,
    *,
    selected_videos: list[str] | None = None,
    root: Path | None = None,
) -> BatchSpec:
    root = (root or project_root()).resolve()
    config_file = _project_path(root, str(config_path))
    config = _read_json(_require_file(config_file, "configuration"))
    try:
        detection = config["detection"]
        calibration = config["calibration"]
        batch = config["batch"]
        assert isinstance(detection, dict)
        assert isinstance(calibration, dict)
        assert isinstance(batch, dict)
        weights = _project_path(root, str(detection["weights"]))
        zones = _project_path(root, str(calibration["zones"]))
        homographies = _project_path(root, str(calibration["homographies"]))
        mask_manifest_path = _project_path(root, str(calibration["mask_manifest"]))
        video_manifest_path = _project_path(root, str(batch["video_manifest"]))
        output_root = _project_path(root, str(batch["output_dir"]))
        configured_ids = [str(item) for item in batch["video_ids"]]
        end_seconds = batch["end_seconds"]
        assert isinstance(end_seconds, dict)
    except (KeyError, TypeError, AssertionError) as exc:
        raise BatchConfigurationError(f"Incomplete batch configuration: {exc}") from exc

    for path, label in (
        (weights, "model weights"),
        (zones, "ROI zones"),
        (homographies, "homographies"),
        (mask_manifest_path, "mask manifest"),
        (video_manifest_path, "video manifest"),
    ):
        _require_file(path, label)

    mask_manifest = _read_json(mask_manifest_path)
    mask_rows = mask_manifest.get("videos")
    if not isinstance(mask_rows, dict):
        raise BatchConfigurationError("Mask manifest has no 'videos' object")
    homography_rows = _read_json(homographies).get("videos")
    if not isinstance(homography_rows, dict):
        raise BatchConfigurationError("Homography file has no 'videos' object")

    with video_manifest_path.open(encoding="utf-8-sig", newline="") as stream:
        video_rows = {row["video_id"]: row for row in csv.DictReader(stream)}
    requested = selected_videos or configured_ids
    unknown = sorted(set(requested) - set(configured_ids))
    if unknown and selected_videos is None:
        raise BatchConfigurationError(f"Unknown configured videos: {', '.join(unknown)}")

    model_slug = weights.stem.lower()
    jobs = []
    for video_id in requested:
        if video_id not in video_rows:
            raise BatchConfigurationError(f"Video is absent from manifest: {video_id}")
        if video_id not in mask_rows:
            raise BatchConfigurationError(f"Masks are absent from manifest: {video_id}")
        if video_id not in homography_rows:
            raise BatchConfigurationError(f"Homography is absent: {video_id}")
        if video_id not in end_seconds:
            raise BatchConfigurationError(f"End time is not configured: {video_id}")
        row = video_rows[video_id]
        mask_row = mask_rows[video_id]
        if not isinstance(mask_row, dict):
            raise BatchConfigurationError(f"Invalid mask entry: {video_id}")
        video_path = _project_path(root, str(config["video_dir"])) / row["filename"]
        roadway_mask = mask_manifest_path.parent / str(mask_row["roadway_mask"])
        exclusion_mask = (
            mask_manifest_path.parent / str(mask_row["vehicle_exclusion_mask"])
        )
        _require_file(video_path, f"video {video_id}")
        _require_file(roadway_mask, f"roadway mask {video_id}")
        _require_file(exclusion_mask, f"vehicle exclusion mask {video_id}")
        if video_path.stat().st_size != int(row["size_bytes"]):
            raise BatchConfigurationError(f"Video size differs from manifest: {video_id}")
        duration = float(end_seconds[video_id])
        if duration <= 0:
            raise BatchConfigurationError(f"Invalid end time for {video_id}: {duration}")
        work_dir = output_root / f"{video_id}_{model_slug}"
        jobs.append(
            VideoJob(
                video_id=video_id,
                filename=row["filename"],
                video_sha256=row["sha256"],
                end_seconds=duration,
                video_path=video_path,
                roadway_mask=roadway_mask.resolve(),
                exclusion_mask=exclusion_mask.resolve(),
                work_dir=work_dir.resolve(),
                risk_dir=Path(f"{work_dir}_risk").resolve(),
            )
        )
    return BatchSpec(
        root=root,
        config=config,
        config_path=config_file,
        weights=weights,
        zones=zones,
        homographies=homographies,
        jobs=tuple(jobs),
    )


def _value_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, float):
        try:
            return abs(float(actual) - expected) <= 1e-6
        except (TypeError, ValueError):
            return False
    return actual == expected


def _mapping_matches(actual: object, expected: dict[str, object]) -> bool:
    return isinstance(actual, dict) and all(
        key in actual and _value_matches(actual[key], value)
        for key, value in expected.items()
    )


def _csv_has_columns(path: Path, required: set[str]) -> bool:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            columns = csv.DictReader(stream).fieldnames
    except OSError:
        return False
    return columns is not None and required.issubset(columns)


def _json_if_object(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _command_signature(
    command: tuple[str, ...], *, module_path: Path, inputs: dict[str, str]
) -> str:
    return _signature(
        {"command": command, "module_sha256": _sha256(module_path), "inputs": inputs}
    )


def build_stage_plans(spec: BatchSpec, job: VideoJob) -> tuple[StagePlan, ...]:
    config = spec.config
    detection = config["detection"]
    tracking = config["tracking"]
    conflicts = config["conflicts"]
    assert isinstance(detection, dict)
    assert isinstance(tracking, dict)
    assert isinstance(conflicts, dict)
    continuation = tracking["continuation"]
    assert isinstance(continuation, dict)

    root = spec.root
    # Keep the virtual-environment launcher instead of resolving its symlink to
    # the system interpreter; CUDA and analysis packages live in `.venv`.
    python = str(Path(sys.executable).absolute())
    video = _relative(root, job.video_path)
    weights = _relative(root, spec.weights)
    work_dir = _relative(root, job.work_dir)
    risk_dir = _relative(root, job.risk_dir)
    tracks = job.work_dir / "tracks.csv"
    filtered = job.work_dir / "filtered_tracks.csv"
    merged = job.work_dir / "filtered_tracks_merged.csv"
    summary = job.work_dir / "summary.json"
    filter_summary = job.work_dir / "filter_summary.json"
    continuation_report = job.work_dir / "continuation_report.json"

    detect_parameters = {
        "video": video,
        "model": weights,
        "output_dir": work_dir,
        "start_seconds": 0.0,
        "end_seconds": job.end_seconds,
        "frame_step": int(config["sampling"]["frame_step"]),
        "slice_width": int(detection["slice_width"]),
        "slice_height": int(detection["slice_height"]),
        "overlap": float(detection["slice_overlap"]),
        "image_size": int(detection["image_size"]),
        "confidence": float(detection["confidence"]),
        "nms_iou": float(detection["nms_iou"]),
        "lost_seconds": float(tracking["lost_seconds"]),
        "matching_threshold": float(tracking["matching_threshold"]),
        "class_profile": str(detection["class_profile"]),
    }
    detect_command = (
        python,
        "-m",
        STAGE_MODULES["detect"],
        "--video",
        video,
        "--model",
        weights,
        "--output-dir",
        work_dir,
        "--start-seconds",
        str(detect_parameters["start_seconds"]),
        "--end-seconds",
        str(detect_parameters["end_seconds"]),
        "--frame-step",
        str(detect_parameters["frame_step"]),
        "--slice-width",
        str(detect_parameters["slice_width"]),
        "--slice-height",
        str(detect_parameters["slice_height"]),
        "--overlap",
        str(detect_parameters["overlap"]),
        "--image-size",
        str(detect_parameters["image_size"]),
        "--confidence",
        str(detect_parameters["confidence"]),
        "--nms-iou",
        str(detect_parameters["nms_iou"]),
        "--lost-seconds",
        str(detect_parameters["lost_seconds"]),
        "--matching-threshold",
        str(detect_parameters["matching_threshold"]),
        "--class-profile",
        str(detect_parameters["class_profile"]),
    )

    def detect_valid() -> bool:
        data = _json_if_object(summary)
        try:
            source_fps = float(data["source_fps"]) if data else 0.0
            start_frame = math.floor(
                float(detect_parameters["start_seconds"]) * source_fps
            )
            end_frame = math.ceil(
                float(detect_parameters["end_seconds"]) * source_fps
            )
            frame_step = int(detect_parameters["frame_step"])
            expected_frames = max(
                0, (end_frame - start_frame + frame_step - 1) // frame_step
            )
        except (KeyError, TypeError, ValueError):
            expected_frames = -1
        return bool(
            data
            # Container duration can round one frame beyond the decodable EOF.
            and abs(int(data.get("processed_frames", -1)) - expected_frames) <= 1
            and int(data.get("processed_frames", 0)) > 0
            and _mapping_matches(data.get("parameters"), detect_parameters)
            and _csv_has_columns(
                tracks,
                {"video_id", "frame_index", "track_id", "object_class", "foot_x", "foot_y"},
            )
        )

    detect_signature = _command_signature(
        detect_command,
        module_path=root / "src/roundabout/detect_track.py",
        inputs={"video_sha256": job.video_sha256, "weights_sha256": _sha256(spec.weights)},
    )
    detect_plan = StagePlan(
        job.video_id,
        "detect",
        detect_command,
        (tracks, summary),
        detect_signature,
        detect_valid,
    )

    filter_parameters = {
        "minimum_duration": float(tracking["minimum_duration_seconds"]),
        "minimum_spread": float(tracking["minimum_spread_pixels"]),
        "minimum_vehicle_road_fraction": float(tracking["minimum_vehicle_road_fraction"]),
        "outside_roadway_keep_spread": float(tracking["outside_roadway_keep_spread_pixels"]),
        "roadway_mask": str(job.roadway_mask),
        "vehicle_exclusion_mask": str(job.exclusion_mask),
        "minimum_vehicle_exclusion_fraction": float(
            tracking["minimum_vehicle_exclusion_fraction"]
        ),
    }
    filter_command = (
        python,
        "-m",
        STAGE_MODULES["filter"],
        "--tracks",
        _relative(root, tracks),
        "--output",
        _relative(root, filtered),
        "--summary",
        _relative(root, filter_summary),
        "--roadway-mask",
        _relative(root, job.roadway_mask),
        "--vehicle-exclusion-mask",
        _relative(root, job.exclusion_mask),
        "--minimum-vehicle-exclusion-fraction",
        str(filter_parameters["minimum_vehicle_exclusion_fraction"]),
        "--minimum-duration",
        str(filter_parameters["minimum_duration"]),
        "--minimum-spread",
        str(filter_parameters["minimum_spread"]),
        "--minimum-vehicle-road-fraction",
        str(filter_parameters["minimum_vehicle_road_fraction"]),
        "--outside-roadway-keep-spread",
        str(filter_parameters["outside_roadway_keep_spread"]),
    )

    def filter_valid() -> bool:
        data = _json_if_object(filter_summary)
        return bool(
            data
            and _mapping_matches(data.get("parameters"), filter_parameters)
            and _csv_has_columns(filtered, {"video_id", "track_id", "foot_x", "foot_y"})
        )

    filter_signature = _command_signature(
        filter_command,
        module_path=root / "src/roundabout/filter_tracks.py",
        inputs={
            "upstream": detect_signature,
            "roadway_mask_sha256": _sha256(job.roadway_mask),
            "exclusion_mask_sha256": _sha256(job.exclusion_mask),
        },
    )
    filter_plan = StagePlan(
        job.video_id,
        "filter",
        filter_command,
        (filtered, filter_summary),
        filter_signature,
        filter_valid,
    )

    thresholds = {
        "maximum_gap_seconds": float(continuation["maximum_gap_seconds"]),
        "maximum_prediction_error_pixels": float(
            continuation["maximum_prediction_error_pixels"]
        ),
        "maximum_direction_change_degrees": float(
            continuation["maximum_direction_change_degrees"]
        ),
        "maximum_speed_ratio": float(continuation["maximum_speed_ratio"]),
        "maximum_size_ratio": float(continuation["maximum_size_ratio"]),
        "maximum_overlap_seconds": float(continuation["maximum_overlap_seconds"]),
        "maximum_duplicate_distance_pixels": float(
            continuation["maximum_duplicate_distance_pixels"]
        ),
    }
    merge_command_items = [
        python,
        "-m",
        STAGE_MODULES["merge"],
        "--tracks",
        _relative(root, filtered),
        "--output",
        _relative(root, merged),
        "--report",
        _relative(root, continuation_report),
    ]
    for key, value in thresholds.items():
        merge_command_items.extend((f"--{key.replace('_', '-')}", str(value)))
    merge_command = tuple(merge_command_items)

    def merge_valid() -> bool:
        data = _json_if_object(continuation_report)
        return bool(
            data
            and _mapping_matches(data.get("thresholds"), thresholds)
            and _csv_has_columns(
                merged, {"video_id", "track_id", "original_track_id", "foot_x", "foot_y"}
            )
        )

    merge_signature = _command_signature(
        merge_command,
        module_path=root / "src/roundabout/merge_track_fragments.py",
        inputs={"upstream": filter_signature},
    )
    merge_plan = StagePlan(
        job.video_id,
        "merge",
        merge_command,
        (merged, continuation_report),
        merge_signature,
        merge_valid,
    )

    risk_parameters = {
        "maximum_gap_seconds": float(conflicts["maximum_roi_gap_seconds"]),
        "maximum_pet_seconds": float(conflicts["maximum_candidate_pet_seconds"]),
        "minimum_crossing_angle_degrees": float(
            conflicts["minimum_crossing_angle_degrees"]
        ),
        "maximum_encroachment_distance_pixels": float(
            conflicts["maximum_encroachment_distance_pixels"]
        ),
    }
    risk_command = (
        python,
        "-m",
        STAGE_MODULES["risk"],
        "--tracks",
        _relative(root, merged),
        "--zones",
        _relative(root, spec.zones),
        "--homographies",
        _relative(root, spec.homographies),
        "--video-id",
        job.video_id,
        "--output-dir",
        risk_dir,
        "--maximum-gap-seconds",
        str(risk_parameters["maximum_gap_seconds"]),
        "--maximum-pet-seconds",
        str(risk_parameters["maximum_pet_seconds"]),
        "--minimum-crossing-angle-degrees",
        str(risk_parameters["minimum_crossing_angle_degrees"]),
        "--maximum-encroachment-distance-pixels",
        str(risk_parameters["maximum_encroachment_distance_pixels"]),
    )
    risk_summary = job.risk_dir / "risk_summary.json"
    roi_summary = job.risk_dir / "roi_summary.json"
    events = job.risk_dir / "events.json"

    def risk_valid() -> bool:
        data = _json_if_object(risk_summary)
        try:
            roi_value = json.loads(roi_summary.read_text(encoding="utf-8"))
            event_value = json.loads(events.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(
            data
            and data.get("source_video") == job.video_id
            and _value_matches(
                data.get("minimum_crossing_angle_degrees"),
                risk_parameters["minimum_crossing_angle_degrees"],
            )
            and _value_matches(
                data.get("maximum_encroachment_distance_pixels"),
                risk_parameters["maximum_encroachment_distance_pixels"],
            )
            and isinstance(roi_value, list)
            and isinstance(event_value, list)
        )

    risk_signature = _command_signature(
        risk_command,
        module_path=root / "src/roundabout/analyze_risk.py",
        inputs={
            "upstream": merge_signature,
            "zones_sha256": _sha256(spec.zones),
            "homographies_sha256": _sha256(spec.homographies),
        },
    )
    risk_plan = StagePlan(
        job.video_id,
        "risk",
        risk_command,
        (risk_summary, roi_summary, events),
        risk_signature,
        risk_valid,
    )
    return detect_plan, filter_plan, merge_plan, risk_plan


def _state_path(job: VideoJob) -> Path:
    return job.work_dir / "batch_state.json"


def _read_state(job: VideoJob) -> dict[str, object]:
    path = _state_path(job)
    if not path.exists():
        return {"video_id": job.video_id, "stages": {}}
    data = _json_if_object(path)
    if data is None or data.get("video_id") != job.video_id:
        return {"video_id": job.video_id, "stages": {}}
    if not isinstance(data.get("stages"), dict):
        data["stages"] = {}
    return data


def _write_state(job: VideoJob, state: dict[str, object]) -> None:
    job.work_dir.mkdir(parents=True, exist_ok=True)
    path = _state_path(job)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _artifact_hashes(plan: StagePlan) -> dict[str, str]:
    return {str(path): _sha256(path) for path in plan.outputs if path.is_file()}


def stage_is_complete(plan: StagePlan, state: dict[str, object]) -> bool:
    stages = state.get("stages", {})
    record = stages.get(plan.name) if isinstance(stages, dict) else None
    if isinstance(record, dict):
        if record.get("signature") != plan.signature:
            return False
        if record.get("status") != "complete":
            return plan.validator()
        recorded_hashes = record.get("artifacts")
        if not isinstance(recorded_hashes, dict):
            return False
        if any(
            not path.is_file() or recorded_hashes.get(str(path)) != _sha256(path)
            for path in plan.outputs
        ):
            return False
        return plan.validator()
    return plan.name != "risk" and plan.validator()


def decide_actions(
    plans: tuple[StagePlan, ...], state: dict[str, object], *, force: bool
) -> tuple[StageAction, ...]:
    rerun_downstream = force
    actions = []
    for plan in plans:
        complete = stage_is_complete(plan, state)
        if rerun_downstream:
            reason = "forced" if force and not actions else "upstream will run"
            actions.append(StageAction(plan, True, reason))
        elif complete:
            actions.append(StageAction(plan, False, "validated existing output"))
        else:
            actions.append(StageAction(plan, True, "missing, stale, or invalid output"))
            rerun_downstream = True
    return tuple(actions)


def _update_stage_state(
    job: VideoJob,
    state: dict[str, object],
    plan: StagePlan,
    status: str,
    *,
    artifacts: dict[str, str] | None = None,
    error: str | None = None,
) -> None:
    stages = state.setdefault("stages", {})
    assert isinstance(stages, dict)
    record: dict[str, object] = {
        "status": status,
        "signature": plan.signature,
        "command": list(plan.command),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if artifacts is not None:
        record["artifacts"] = artifacts
    if error is not None:
        record["error"] = error
    stages[plan.name] = record
    _write_state(job, state)


def run_batch(spec: BatchSpec, *, dry_run: bool, force: bool) -> int:
    run_count = 0
    skip_count = 0
    for job in spec.jobs:
        state = _read_state(job)
        plans = build_stage_plans(spec, job)
        actions = decide_actions(plans, state, force=force)
        for action in actions:
            prefix = "DRY-RUN" if dry_run else "BATCH"
            verb = "run" if action.run else "skip"
            print(
                f"[{prefix}] video={job.video_id} stage={action.plan.name} "
                f"action={verb} reason={action.reason}"
            )
            if not action.run:
                skip_count += 1
                stages = state.get("stages", {})
                record = stages.get(action.plan.name) if isinstance(stages, dict) else None
                if (
                    not dry_run
                    and isinstance(record, dict)
                    and record.get("status") != "complete"
                ):
                    _update_stage_state(
                        job,
                        state,
                        action.plan,
                        "complete",
                        artifacts=_artifact_hashes(action.plan),
                    )
                continue
            run_count += 1
            print(f"  {shlex.join(action.plan.command)}")
            if dry_run:
                continue
            _update_stage_state(job, state, action.plan, "running")
            environment = os.environ.copy()
            source_path = str(spec.root / "src")
            environment["PYTHONPATH"] = os.pathsep.join(
                item for item in (source_path, environment.get("PYTHONPATH")) if item
            )
            runtime = spec.root / ".runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            environment.setdefault("MPLCONFIGDIR", str(runtime / "matplotlib"))
            environment.setdefault("YOLO_CONFIG_DIR", str(runtime / "ultralytics"))
            try:
                subprocess.run(
                    action.plan.command,
                    cwd=spec.root,
                    env=environment,
                    check=True,
                )
                if not action.plan.validator():
                    raise RuntimeError("stage finished without valid expected outputs")
            except (subprocess.CalledProcessError, RuntimeError) as exc:
                _update_stage_state(
                    job, state, action.plan, "failed", error=str(exc)
                )
                raise
            _update_stage_state(
                job,
                state,
                action.plan,
                "complete",
                artifacts=_artifact_hashes(action.plan),
            )
    print(
        f"Batch plan complete: videos={len(spec.jobs)} run={run_count} "
        f"skip={skip_count} dry_run={str(dry_run).lower()}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or preview the resumable validated analysis batch."
    )
    parser.add_argument("--config", default="configs/baseline.json")
    parser.add_argument("--videos", nargs="+", help="Override configured video IDs")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writes")
    parser.add_argument("--force", action="store_true", help="Rerun all stages")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        spec = load_batch_spec(args.config, selected_videos=args.videos)
        raise SystemExit(run_batch(spec, dry_run=args.dry_run, force=args.force))
    except (BatchConfigurationError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Batch failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
