"""궤적 최소 지속시간 필터 (Phase B Day2 2.4 대응, Work Plan 6.1절).

ghost 트랙(≤2점, 8편 평균 약 33%)을 걸러낸다: track_id별 (마지막 time_sec - 첫
time_sec) < --min-duration-sec 인 트랙을 tracks_pixel.csv에서 제거한다.

    python src/30_filter_min_duration_tracks.py \
        --tracks runs/before_l_mt09/DJI_0482/tracks_pixel.csv \
        --output runs/before_l_mt09/DJI_0482/tracks_pixel_filtered.csv
"""

from __future__ import annotations

from _paths import BASE

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drop tracks shorter than a minimum duration.")
    parser.add_argument("--tracks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-duration-sec", type=float, default=0.5)
    return parser.parse_args()


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def main() -> None:
    args = parse_args()

    with args.tracks.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise RuntimeError(f"No header row found in: {args.tracks}")
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    times_by_track: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        track_id = (row.get("track_id") or "").strip()
        times_by_track[track_id].append(parse_float(row.get("time_sec") or ""))

    kept_ids = {
        track_id
        for track_id, times in times_by_track.items()
        if max(times) - min(times) >= args.min_duration_sec
    }
    kept_rows = [row for row in rows if (row.get("track_id") or "").strip() in kept_ids]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept_rows)

    print(f"Tracks: {len(times_by_track)} -> {len(kept_ids)} (dropped {len(times_by_track) - len(kept_ids)})")
    print(f"Rows: {len(rows)} -> {len(kept_rows)}")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
