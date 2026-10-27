from __future__ import annotations

from _paths import BASE

import argparse
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = BASE
DEFAULT_RUN_DIR = BASE_DIR / "runs" / "DJI_0481_sahi_step10"
DEFAULT_VIDEO = BASE_DIR / "record" / "DJI_0481.MP4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run tracking, default ROI, PET, and heatmap after step10 SAHI detection."
    )
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--max-wait-hours", type=float, default=8.0)
    return parser.parse_args()


def run_command(args: list[str]) -> None:
    print(f"Running: {' '.join(args)}", flush=True)
    subprocess.run(args, cwd=BASE_DIR, check=True)


def wait_for_detections(path: Path, poll_seconds: int, max_wait_hours: float) -> None:
    deadline = time.time() + max_wait_hours * 3600.0
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            print(f"Found detections: {path}", flush=True)
            return
        print(f"Waiting for detections: {path}", flush=True)
        time.sleep(poll_seconds)
    raise TimeoutError(f"Timed out waiting for {path}")


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir
    if not run_dir.is_absolute():
        run_dir = BASE_DIR / run_dir
    detections = run_dir / "detections_pixel.csv"

    if args.wait:
        wait_for_detections(detections, args.poll_seconds, args.max_wait_hours)

    run_command(
        [
            sys.executable,
            "src\\05_make_default_conflict_zones.py",
            "--output",
            str(run_dir / "conflict_zones.json"),
        ]
    )
    run_command(
        [
            sys.executable,
            "src\\04_track_sahi_detections.py",
            "--input",
            str(detections),
            "--output",
            str(run_dir / "tracks_pixel.csv"),
        ]
    )
    run_command(
        [
            sys.executable,
            "src\\06_compute_pet.py",
            "--tracks",
            str(run_dir / "tracks_pixel.csv"),
            "--zones",
            str(run_dir / "conflict_zones.json"),
            "--output",
            str(run_dir / "pet_events.csv"),
            "--risk-output",
            str(run_dir / "pet_risk_by_roi.csv"),
        ]
    )
    run_command(
        [
            sys.executable,
            "src\\07_make_pet_heatmap.py",
            "--events",
            str(run_dir / "pet_events.csv"),
            "--video",
            str(args.video),
            "--output",
            str(run_dir / "pet_heatmap.png"),
            "--cells-output",
            str(run_dir / "pet_heatmap_cells.csv"),
        ]
    )
    print("Step10 PET pipeline completed.", flush=True)


if __name__ == "__main__":
    main()
