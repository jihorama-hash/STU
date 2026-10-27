"""Create a deterministic inventory for raw videos and the active configuration."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from .paths import resolve_project_path


CHUNK_SIZE = 8 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(video_dir: Path) -> list[dict[str, object]]:
    videos = sorted(
        path for path in video_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}
    )
    return [
        {
            "video_id": path.stem,
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in videos
    ]


def write_inventory(rows: list[dict[str, object]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["video_id", "filename", "size_bytes", "sha256"]
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/baseline.json")
    parser.add_argument("--output", default="manifests/raw_videos.csv")
    args = parser.parse_args()

    config_path = resolve_project_path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    video_dir = resolve_project_path(config["video_dir"])
    output_path = resolve_project_path(args.output)
    rows = build_inventory(video_dir)
    write_inventory(rows, output_path)
    print(f"Wrote {len(rows)} videos to {output_path}")


if __name__ == "__main__":
    main()
