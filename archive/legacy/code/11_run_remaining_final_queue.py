from __future__ import annotations

from _paths import BASE

import argparse
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = BASE
COMPLETED_0481_EVENTS = (
    BASE_DIR
    / "runs"
    / "DJI_0481_sahi_step10"
    / "m0615_pet_deduped"
    / "pet_events_m0615_deduped.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for DJI_0482, run remaining final analyses sequentially, then combine."
    )
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--frame-step", type=int, default=3)
    return parser.parse_args()


def run(args: list[str], log_path: Path) -> None:
    print(f"Running: {' '.join(args)}", flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"Running: {' '.join(args)}\n")
        log.flush()
        subprocess.run(args, cwd=BASE_DIR, check=True, stdout=log, stderr=log)


def wait_for(path: Path, poll_seconds: int) -> None:
    while not path.exists() or path.stat().st_size == 0:
        print(f"Waiting for {path}", flush=True)
        time.sleep(poll_seconds)
    print(f"Found {path}", flush=True)


def final_event_path(video_id: str) -> Path:
    return (
        BASE_DIR
        / "runs"
        / f"{video_id}_sahi_step3_final"
        / "final_m0615"
        / "pet_events_final.csv"
    )


def main() -> None:
    args = parse_args()
    queue_log = BASE_DIR / "runs" / "final_queue.log"

    if not COMPLETED_0481_EVENTS.exists():
        raise FileNotFoundError(f"Missing completed DJI_0481 events: {COMPLETED_0481_EVENTS}")

    wait_for(final_event_path("DJI_0482"), args.poll_seconds)

    remaining_videos = [
        ("DJI_0483_Cut", "DJI_0483_Cut.mp4"),
        ("DJI_0484", "DJI_0484.MP4"),
        ("DJI_0485", "DJI_0485.MP4"),
        ("DJI_0486", "DJI_0486.MP4"),
        ("DJI_0487", "DJI_0487.MP4"),
        ("DJI_0488", "DJI_0488.MP4"),
    ]

    for video_id, filename in remaining_videos:
        video = BASE_DIR / "record" / filename
        if not video.exists():
            raise FileNotFoundError(f"Missing video: {video}")
        output_events = final_event_path(video_id)
        if output_events.exists() and output_events.stat().st_size > 0:
            print(f"Skipping completed {video_id}: {output_events}", flush=True)
            continue
        run(
            [
                sys.executable,
                "-u",
                "src\\09_run_final_pet_pipeline.py",
                "--video",
                str(video),
                "--run-dir",
                str(BASE_DIR / "runs" / f"{video_id}_sahi_step3_final"),
                "--frame-step",
                str(args.frame_step),
            ],
            queue_log,
        )

    event_files = [
        COMPLETED_0481_EVENTS,
        final_event_path("DJI_0482"),
        final_event_path("DJI_0483_Cut"),
        final_event_path("DJI_0484"),
        final_event_path("DJI_0485"),
        final_event_path("DJI_0486"),
        final_event_path("DJI_0487"),
        final_event_path("DJI_0488"),
    ]
    run(
        [
            sys.executable,
            "-u",
            "src\\10_make_combined_pet_outputs.py",
            "--output-dir",
            str(BASE_DIR / "runs" / "combined_8videos_final"),
            "--background-video",
            str(BASE_DIR / "record" / "DJI_0481.MP4"),
            *[str(path) for path in event_files],
        ],
        queue_log,
    )
    print("Final queue completed.", flush=True)


if __name__ == "__main__":
    main()
