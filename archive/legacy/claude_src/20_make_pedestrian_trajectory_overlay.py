from __future__ import annotations

from _paths import BASE

import argparse
import csv
import hashlib
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


BASE_DIR = BASE
DEFAULT_OUTPUT_DIR = BASE_DIR / "runs" / "pedestrian_trajectory_overlay"
DEFAULT_BACKGROUND_VIDEO = BASE_DIR / "record" / "DJI_0481.MP4"
DEFAULT_TRACK_FILES = [
    BASE_DIR / "runs" / "DJI_0481_sahi_step10" / "tracks_pixel.csv",
    BASE_DIR / "runs" / "DJI_0482_sahi_step10" / "m0615_pet_deduped" / "tracks_pixel_m0615.csv",
    BASE_DIR / "runs" / "DJI_0483_Cut_sahi_step10" / "m0615_pet_deduped" / "tracks_pixel_m0615.csv",
    BASE_DIR / "runs" / "DJI_0484_sahi_step10" / "m0617_pet_deduped" / "tracks_pixel_m0615.csv",
    BASE_DIR / "runs" / "DJI_0485_sahi_step10" / "m0617_pet_deduped" / "tracks_pixel_m0615.csv",
    BASE_DIR / "runs" / "DJI_0486_sahi_step10" / "m0617_pet_deduped" / "tracks_pixel_m0615.csv",
    BASE_DIR / "runs" / "DJI_0487_sahi_step10" / "m0618_pet_deduped" / "tracks_pixel_m0615.csv",
    BASE_DIR / "runs" / "DJI_0488_sahi_step10" / "m0618_pet_deduped" / "tracks_pixel_m0615.csv",
]

SUMMARY_FIELDS = [
    "source_video",
    "source_file",
    "track_id",
    "segment_id",
    "point_count",
    "start_frame",
    "end_frame",
    "start_time_sec",
    "end_time_sec",
    "duration_sec",
    "start_x",
    "start_y",
    "end_x",
    "end_y",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Draw pedestrian track trajectories from tracks_pixel CSVs on one image."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--background-video", type=Path, default=DEFAULT_BACKGROUND_VIDEO)
    parser.add_argument("--background-frame", type=int, default=0)
    parser.add_argument("--min-points", type=int, default=3)
    parser.add_argument("--min-duration-sec", type=float, default=0.0)
    parser.add_argument("--max-step-distance-px", type=float, default=0.0)
    parser.add_argument("--max-gap-sec", type=float, default=0.0)
    parser.add_argument("--line-thickness", type=int, default=2)
    parser.add_argument("--alpha", type=float, default=0.72)
    parser.add_argument("--draw-endpoints", action="store_true", default=True)
    parser.add_argument("--no-endpoints", dest="draw_endpoints", action="store_false")
    parser.add_argument("track_files", nargs="*", type=Path, default=DEFAULT_TRACK_FILES)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else BASE_DIR / path


def parse_float(value: str | int | float | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value: str | int | float | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def source_video_from_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("DJI_") and "sahi" in part:
            return part.replace("_sahi_step10", "").replace("_sahi_step3_final", "")
    return path.parent.name


def color_for_key(key: str) -> tuple[int, int, int]:
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    hue = int(digest[0]) % 180
    sat = 170 + int(digest[1]) % 70
    val = 210 + int(digest[2]) % 45
    hsv = np.array([[[hue, sat, val]]], dtype=np.uint8)
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def read_background(video_path: Path, frame_index: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open background video: {video_path}")
    if frame_index > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame {frame_index} from {video_path}")
    return frame


def read_pedestrian_tracks(path: Path) -> list[dict]:
    source_video = source_video_from_path(path)
    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            class_name = (row.get("class_name") or "").strip().lower()
            if class_name != "person":
                continue
            rows.append(
                {
                    "source_video": source_video,
                    "source_file": str(path),
                    "track_id": str(row.get("track_id", "")).strip(),
                    "frame_id": parse_int(row.get("frame_id")),
                    "time_sec": parse_float(row.get("time_sec")),
                    "x": parse_float(row.get("foot_x"), parse_float(row.get("cx"))),
                    "y": parse_float(row.get("foot_y"), parse_float(row.get("cy"))),
                }
            )
    return rows


def split_points(
    points: list[dict],
    max_step_distance_px: float,
    max_gap_sec: float,
) -> list[list[dict]]:
    if not points:
        return []
    segments = [[points[0]]]
    for prev, current in zip(points, points[1:]):
        step_distance = ((current["x"] - prev["x"]) ** 2 + (current["y"] - prev["y"]) ** 2) ** 0.5
        gap_sec = current["time_sec"] - prev["time_sec"]
        should_split = False
        if max_step_distance_px > 0 and step_distance > max_step_distance_px:
            should_split = True
        if max_gap_sec > 0 and gap_sec > max_gap_sec:
            should_split = True
        if should_split:
            segments.append([])
        segments[-1].append(current)
    return segments


def build_trajectories(
    rows: list[dict],
    min_points: int,
    min_duration_sec: float,
    max_step_distance_px: float,
    max_gap_sec: float,
) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["source_video"], row["source_file"], row["track_id"])
        grouped[key].append(row)

    trajectories = []
    for (source_video, source_file, track_id), points in grouped.items():
        points = sorted(points, key=lambda item: (item["frame_id"], item["time_sec"]))
        for segment_index, segment_points in enumerate(
            split_points(points, max_step_distance_px, max_gap_sec),
            start=1,
        ):
            if len(segment_points) < min_points:
                continue
            duration = segment_points[-1]["time_sec"] - segment_points[0]["time_sec"]
            if duration < min_duration_sec:
                continue
            trajectories.append(
                {
                    "source_video": source_video,
                    "source_file": source_file,
                    "track_id": track_id,
                    "segment_id": segment_index,
                    "points": segment_points,
                    "duration_sec": duration,
                }
            )

    trajectories.sort(
        key=lambda item: (item["source_video"], int(item["track_id"] or 0), item["segment_id"])
    )
    return trajectories


def trajectory_summary(trajectory: dict) -> dict:
    points = trajectory["points"]
    first = points[0]
    last = points[-1]
    return {
        "source_video": trajectory["source_video"],
        "source_file": trajectory["source_file"],
        "track_id": trajectory["track_id"],
        "segment_id": trajectory["segment_id"],
        "point_count": len(points),
        "start_frame": first["frame_id"],
        "end_frame": last["frame_id"],
        "start_time_sec": round(first["time_sec"], 3),
        "end_time_sec": round(last["time_sec"], 3),
        "duration_sec": round(trajectory["duration_sec"], 3),
        "start_x": round(first["x"], 2),
        "start_y": round(first["y"], 2),
        "end_x": round(last["x"], 2),
        "end_y": round(last["y"], 2),
    }


def draw_trajectories(
    background: np.ndarray,
    trajectories: list[dict],
    output_path: Path,
    alpha: float,
    line_thickness: int,
    draw_endpoints: bool,
    color_by_track: bool,
) -> None:
    overlay = background.copy()
    height, width = background.shape[:2]

    for trajectory in trajectories:
        key = (
            f"{trajectory['source_video']}:{trajectory['track_id']}"
            if color_by_track
            else trajectory["source_video"]
        )
        color = color_for_key(key)
        points = np.array(
            [
                [int(round(point["x"])), int(round(point["y"]))]
                for point in trajectory["points"]
                if 0 <= point["x"] < width and 0 <= point["y"] < height
            ],
            dtype=np.int32,
        )
        if len(points) < 2:
            continue
        cv2.polylines(
            overlay,
            [points.reshape((-1, 1, 2))],
            isClosed=False,
            color=color,
            thickness=line_thickness,
            lineType=cv2.LINE_AA,
        )
        if draw_endpoints:
            start = tuple(points[0])
            end = tuple(points[-1])
            cv2.circle(overlay, start, max(3, line_thickness + 2), (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(overlay, end, max(4, line_thickness + 3), color, -1, cv2.LINE_AA)

    blended = cv2.addWeighted(background, 1.0 - alpha, overlay, alpha, 0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), blended):
        raise RuntimeError(f"Could not write image: {output_path}")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    output_dir = resolve(args.output_dir)
    track_files = [resolve(path) for path in args.track_files]
    missing = [path for path in track_files if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing track CSV files:\n" + "\n".join(str(path) for path in missing))

    rows: list[dict] = []
    for path in track_files:
        rows.extend(read_pedestrian_tracks(path))

    trajectories = build_trajectories(
        rows=rows,
        min_points=max(2, args.min_points),
        min_duration_sec=args.min_duration_sec,
        max_step_distance_px=args.max_step_distance_px,
        max_gap_sec=args.max_gap_sec,
    )
    background = read_background(resolve(args.background_video), args.background_frame)

    summary_rows = [trajectory_summary(trajectory) for trajectory in trajectories]
    write_csv(output_dir / "pedestrian_trajectory_summary.csv", summary_rows)

    draw_trajectories(
        background=background,
        trajectories=trajectories,
        output_path=output_dir / "pedestrian_trajectories_all.png",
        alpha=args.alpha,
        line_thickness=args.line_thickness,
        draw_endpoints=args.draw_endpoints,
        color_by_track=False,
    )
    draw_trajectories(
        background=background,
        trajectories=trajectories,
        output_path=output_dir / "pedestrian_trajectories_all_track_colors.png",
        alpha=args.alpha,
        line_thickness=args.line_thickness,
        draw_endpoints=args.draw_endpoints,
        color_by_track=True,
    )

    for source_video in sorted({trajectory["source_video"] for trajectory in trajectories}):
        video_trajectories = [
            trajectory for trajectory in trajectories if trajectory["source_video"] == source_video
        ]
        draw_trajectories(
            background=background,
            trajectories=video_trajectories,
            output_path=output_dir / f"pedestrian_trajectories_{source_video}.png",
            alpha=args.alpha,
            line_thickness=args.line_thickness,
            draw_endpoints=args.draw_endpoints,
            color_by_track=True,
        )

    print(f"Input files: {len(track_files)}")
    print(f"Pedestrian points: {len(rows)}")
    print(f"Trajectories: {len(trajectories)}")
    print(f"Saved: {output_dir}")


if __name__ == "__main__":
    main()
