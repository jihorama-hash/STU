from __future__ import annotations

from _paths import BASE

import argparse
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = BASE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run final frame-step 3 SAHI, tracking, PET, and heatmap for one DJI video."
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--frame-step", type=int, default=3)
    parser.add_argument("--conf", type=float, default=0.15)
    parser.add_argument("--slice-width", type=int, default=1024)
    parser.add_argument("--slice-height", type=int, default=1024)
    parser.add_argument("--overlap", type=float, default=0.20)
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--skip-detect", action="store_true")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else BASE_DIR / path


def run_command(args: list[str], stdout_path: Path | None = None, stderr_path: Path | None = None) -> None:
    print(f"Running: {' '.join(args)}", flush=True)
    if stdout_path is None or stderr_path is None:
        subprocess.run(args, cwd=BASE_DIR, check=True)
        return
    with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open(
        "a", encoding="utf-8"
    ) as stderr:
        subprocess.run(args, cwd=BASE_DIR, check=True, stdout=stdout, stderr=stderr)


def main() -> None:
    args = parse_args()
    video = resolve(args.video)
    run_dir = resolve(args.run_dir)
    final_dir = run_dir / "final_m0615"
    run_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")

    detections = run_dir / "detections_pixel.csv"
    tracks = run_dir / "tracks_pixel.csv"
    zones = run_dir / "conflict_zones.json"
    events = final_dir / "pet_events_final.csv"
    risk = final_dir / "pet_risk_by_roi_final.csv"
    heatmap = final_dir / "pet_heatmap_final.png"
    cells = final_dir / "pet_heatmap_cells_final.csv"

    started = time.perf_counter()
    if not args.skip_detect:
        run_command(
            [
                sys.executable,
                "-u",
                "src\\03_DJI0481_sahi_detect.py",
                "--video",
                str(video),
                "--all-frames",
                "--frame-step",
                str(args.frame_step),
                "--conf",
                str(args.conf),
                "--slice-width",
                str(args.slice_width),
                "--slice-height",
                str(args.slice_height),
                "--overlap",
                str(args.overlap),
                "--imgsz",
                str(args.imgsz),
                "--no-save-images",
                "--output-dir",
                str(run_dir),
            ],
            stdout_path=run_dir / "sahi_step3_stdout.log",
            stderr_path=run_dir / "sahi_step3_stderr.log",
        )

    run_command(
        [
            sys.executable,
            "-u",
            "src\\05_make_default_conflict_zones.py",
            "--output",
            str(zones),
            "--video",
            str(video),
            "--preview-output",
            str(run_dir / "conflict_zones_preview.jpg"),
        ],
        stdout_path=run_dir / "pet_pipeline_stdout.log",
        stderr_path=run_dir / "pet_pipeline_stderr.log",
    )
    run_command(
        [
            sys.executable,
            "-u",
            "src\\04_track_sahi_detections_m0615.py",
            "--input",
            str(detections),
            "--output",
            str(tracks),
        ],
        stdout_path=run_dir / "pet_pipeline_stdout.log",
        stderr_path=run_dir / "pet_pipeline_stderr.log",
    )
    run_command(
        [
            sys.executable,
            "-u",
            "src\\06_compute_pet_m0615.py",
            "--tracks",
            str(tracks),
            "--zones",
            str(zones),
            "--output",
            str(events),
            "--risk-output",
            str(risk),
            "--max-pet-sec",
            "3.0",
            "--final-pet-sec",
            "1.5",
        ],
        stdout_path=run_dir / "pet_pipeline_stdout.log",
        stderr_path=run_dir / "pet_pipeline_stderr.log",
    )
    run_command(
        [
            sys.executable,
            "-u",
            "src\\07_make_pet_heatmap.py",
            "--events",
            str(events),
            "--video",
            str(video),
            "--output",
            str(heatmap),
            "--cells-output",
            str(cells),
            "--radius",
            "120",
            "--alpha",
            "0.55",
            "--cell-size",
            "160",
        ],
        stdout_path=run_dir / "pet_pipeline_stdout.log",
        stderr_path=run_dir / "pet_pipeline_stderr.log",
    )

    elapsed = time.perf_counter() - started
    (final_dir / "run_metadata.txt").write_text(
        "\n".join(
            [
                f"video={video}",
                f"run_dir={run_dir}",
                f"frame_step={args.frame_step}",
                f"conf={args.conf}",
                f"slice_width={args.slice_width}",
                f"slice_height={args.slice_height}",
                f"overlap={args.overlap}",
                f"imgsz={args.imgsz}",
                "model=yolo11m.pt",
                "max_pet_sec=3.0",
                "final_pet_sec=1.5",
                "pet_logic=06_compute_pet_m0615.py",
                f"elapsed_sec={elapsed:.1f}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Final PET pipeline completed in {elapsed:.1f}s: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
