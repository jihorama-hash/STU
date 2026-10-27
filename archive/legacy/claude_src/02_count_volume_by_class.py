
from _paths import BASE
import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_INPUT = BASE / "runs" / "tracks_pixel.csv"
DEFAULT_OUTPUT_DIR = BASE / "runs"


CLASS_KIND = {
    "person": "pedestrian",
    "bicycle": "vehicle",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
}


def parse_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_track_rows(csv_path):
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"frame_id", "time_sec", "track_id", "class_name", "confidence"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns in {csv_path}: {sorted(missing)}")

        for row in reader:
            track_id = row.get("track_id", "").strip()
            class_name = row.get("class_name", "").strip()
            if not track_id or not class_name:
                continue

            yield {
                "track_id": track_id,
                "class_name": class_name,
                "time_sec": parse_float(row.get("time_sec")),
                "confidence": parse_float(row.get("confidence")),
            }


def summarize_tracks(rows, min_frames):
    tracks = {}

    for row in rows:
        track_id = row["track_id"]
        class_name = row["class_name"]
        time_sec = row["time_sec"]
        confidence = row["confidence"]

        if track_id not in tracks:
            tracks[track_id] = {
                "track_id": track_id,
                "first_seen_sec": time_sec,
                "last_seen_sec": time_sec,
                "frame_count": 0,
                "class_counts": Counter(),
                "confidence_sum_by_class": defaultdict(float),
            }

        track = tracks[track_id]
        track["first_seen_sec"] = min(track["first_seen_sec"], time_sec)
        track["last_seen_sec"] = max(track["last_seen_sec"], time_sec)
        track["frame_count"] += 1
        track["class_counts"][class_name] += 1
        track["confidence_sum_by_class"][class_name] += confidence

    summaries = []
    for track in tracks.values():
        if track["frame_count"] < min_frames:
            continue

        class_name = choose_representative_class(track)
        class_count = track["class_counts"][class_name]
        avg_confidence = track["confidence_sum_by_class"][class_name] / class_count

        summaries.append({
            "track_id": track["track_id"],
            "class_name": class_name,
            "class_kind": CLASS_KIND.get(class_name, "other"),
            "first_seen_sec": track["first_seen_sec"],
            "last_seen_sec": track["last_seen_sec"],
            "duration_sec": track["last_seen_sec"] - track["first_seen_sec"],
            "frame_count": track["frame_count"],
            "avg_confidence": avg_confidence,
        })

    summaries.sort(key=lambda item: (item["first_seen_sec"], item["track_id"]))
    return summaries


def choose_representative_class(track):
    def sort_key(item):
        class_name, frame_count = item
        avg_confidence = track["confidence_sum_by_class"][class_name] / frame_count
        return frame_count, avg_confidence

    return max(track["class_counts"].items(), key=sort_key)[0]


def count_by_class(track_summaries):
    counts = Counter(track["class_name"] for track in track_summaries)
    total = sum(counts.values())
    rows = []

    for class_name, count in sorted(counts.items()):
        share = (count / total * 100.0) if total else 0.0
        rows.append({
            "class_name": class_name,
            "class_kind": CLASS_KIND.get(class_name, "other"),
            "count": count,
            "share_percent": round(share, 2),
        })

    rows.append({
        "class_name": "TOTAL",
        "class_kind": "all",
        "count": total,
        "share_percent": 100.0 if total else 0.0,
    })
    return rows


def count_by_interval(track_summaries, bin_seconds):
    if bin_seconds <= 0:
        return []

    interval_counts = Counter()
    for track in track_summaries:
        interval_start = int(track["first_seen_sec"] // bin_seconds) * bin_seconds
        key = (interval_start, interval_start + bin_seconds, track["class_name"])
        interval_counts[key] += 1

    rows = []
    for (start, end, class_name), count in sorted(interval_counts.items()):
        rows.append({
            "interval_start_sec": start,
            "interval_end_sec": end,
            "class_name": class_name,
            "class_kind": CLASS_KIND.get(class_name, "other"),
            "count": count,
        })
    return rows


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Count traffic and pedestrian volumes by class from YOLO/ByteTrack CSV output."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input tracks_pixel.csv path.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for output CSVs.")
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Output filename prefix. Defaults to the input CSV stem.",
    )
    parser.add_argument(
        "--min-frames",
        type=int,
        default=3,
        help="Minimum number of detected frames required to count a track.",
    )
    parser.add_argument(
        "--bin-seconds",
        type=int,
        default=60,
        help="Time interval size for interval counts. Use 0 to skip interval output.",
    )
    args = parser.parse_args()

    track_summaries = summarize_tracks(read_track_rows(args.input), min_frames=args.min_frames)
    class_counts = count_by_class(track_summaries)
    interval_counts = count_by_interval(track_summaries, args.bin_seconds)

    output_prefix = args.output_prefix or args.input.stem
    track_summary_path = args.output_dir / f"{output_prefix}_volume_tracks_summary.csv"
    class_count_path = args.output_dir / f"{output_prefix}_volume_by_class.csv"
    interval_count_path = args.output_dir / f"{output_prefix}_volume_by_interval.csv"

    write_csv(
        track_summary_path,
        track_summaries,
        [
            "track_id",
            "class_name",
            "class_kind",
            "first_seen_sec",
            "last_seen_sec",
            "duration_sec",
            "frame_count",
            "avg_confidence",
        ],
    )
    write_csv(
        class_count_path,
        class_counts,
        ["class_name", "class_kind", "count", "share_percent"],
    )

    if args.bin_seconds > 0:
        write_csv(
            interval_count_path,
            interval_counts,
            ["interval_start_sec", "interval_end_sec", "class_name", "class_kind", "count"],
        )

    print(f"Input: {args.input}")
    print(f"Counted tracks: {len(track_summaries)}")
    print(f"Saved: {track_summary_path}")
    print(f"Saved: {class_count_path}")
    if args.bin_seconds > 0:
        print(f"Saved: {interval_count_path}")

    print("")
    print("Volume by class")
    for row in class_counts:
        print(f"- {row['class_name']}: {row['count']}")


if __name__ == "__main__":
    main()
