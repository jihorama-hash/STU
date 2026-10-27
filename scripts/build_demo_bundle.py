"""Build a portable precomputed demo bundle from reviewed COCO results."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default="outputs/analysis/independent/DJI_0482_220_280_yolo11m",
    )
    parser.add_argument("--output", default="outputs/demo/current")
    args = parser.parse_args()

    source = ROOT / args.source
    output = ROOT / args.output
    tracks_source = source / "filtered_tracks_merged.csv"
    if not tracks_source.is_file():
        tracks_source = source / "filtered_tracks.csv"
    review_source = source / "manual_review/review_results.csv"
    merged_risk_source = (
        ROOT / "outputs/analysis/baseline/DJI_0482_220_280_yolo11m_risk_merged"
    )
    risk_source = merged_risk_source if merged_risk_source.is_dir() else (
        ROOT / "outputs/analysis/baseline/DJI_0482_220_280_yolo11m_risk"
    )
    if not tracks_source.is_file() or not review_source.is_file():
        raise FileNotFoundError("Reviewed filtered tracks are required")

    with tracks_source.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    track_ids: dict[str, set[str]] = {}
    observations = Counter()
    for row in rows:
        object_class = row["object_class"]
        track_ids.setdefault(object_class, set()).add(row["track_id"])
        observations[object_class] += 1

    with review_source.open(encoding="utf-8", newline="") as stream:
        review = list(csv.DictReader(stream))
    real = sum(row["review_status"] == "real" for row in review)

    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tracks_source, output / "tracks.csv")
    shutil.copyfile(risk_source / "roi_summary.json", output / "roi_summary.json")
    shutil.copyfile(risk_source / "risk_summary.json", output / "risk_summary.json")
    shutil.copyfile(risk_source / "events.json", output / "events.json")
    validated_source = (
        ROOT
        / "outputs/analysis/baseline/"
        "DJI_0482_0_60_yolo11m_risk_merged/validated_events.json"
    )
    shutil.copyfile(validated_source, output / "validated_events.json")
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    event_sources = [
        {
            "event_id": "roundabout_entry_south-0003",
            "title": "남측 진입부 차량 상충 1",
            "clip": "assets/event_01.mp4",
            "frame_source": (
                ROOT / "outputs/analysis/baseline/DJI_0482_0_60_yolo11m_risk/"
                "manual_review_final/event_02_roundabout_entry_south-0003.jpg"
            ),
            "filmstrip_source": (
                ROOT / "outputs/analysis/baseline/DJI_0482_0_60_yolo11m_risk/"
                "manual_review_angle20/filmstrips/"
                "3_roundabout_entry_south-0003.jpg"
            ),
        },
        {
            "event_id": "roundabout_entry_south-0005",
            "title": "남측 진입부 차량 상충 2",
            "clip": "assets/event_02.mp4",
            "frame_source": (
                ROOT / "outputs/analysis/baseline/DJI_0482_0_60_yolo11m_risk/"
                "manual_review_final/event_04_roundabout_entry_south-0005.jpg"
            ),
            "filmstrip_source": (
                ROOT / "outputs/analysis/baseline/DJI_0482_0_60_yolo11m_risk/"
                "manual_review_angle20/filmstrips/"
                "4_roundabout_entry_south-0005.jpg"
            ),
        },
    ]
    event_assets = []
    for index, item in enumerate(event_sources, start=1):
        frame_name = f"event_{index:02d}_roi.jpg"
        filmstrip_name = f"event_{index:02d}_filmstrip.jpg"
        shutil.copyfile(item["frame_source"], assets / frame_name)
        shutil.copyfile(item["filmstrip_source"], assets / filmstrip_name)
        event_assets.append({
            "event_id": item["event_id"],
            "title": item["title"],
            "clip": item["clip"],
            "roi_frame": f"assets/{frame_name}",
            "filmstrip": f"assets/{filmstrip_name}",
        })
    (output / "event_assets.json").write_text(
        json.dumps(event_assets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "videos.json").write_text(
        json.dumps(
            [{
                "id": "DJI_0482_220_280",
                "source_video": "data/raw/before/DJI_0482.MP4",
                "start_seconds": 220.0,
                "end_seconds": 280.0,
                "availability": "workspace-only",
            }],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    risk_summary = json.loads(
        (risk_source / "risk_summary.json").read_text(encoding="utf-8")
    )
    summary = {
        "model": "COCO YOLO11m",
        "segment": "DJI_0482 220–280초",
        "tracks": sum(len(ids) for ids in track_ids.values()),
        "observations": len(rows),
        "by_class": {
            key: {
                "tracks": len(track_ids[key]),
                "observations": observations[key],
            }
            for key in sorted(track_ids)
        },
        "manual_review": {
            "sample_size": len(review),
            "real_objects": real,
            "sample_precision_percent": round(real / len(review) * 100, 1),
        },
        "conflict_events_status": "unreviewed",
        "pet_candidate_events": risk_summary["pet_candidate_events"],
        "track_continuation_applied": tracks_source.name == "filtered_tracks_merged.csv",
    }
    (output / "track_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = {
        "bundle_version": "1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "study_phase": "before",
        "validation_status": "track-validated",
        "config": "configs/baseline.json",
        "model": {
            "name": "COCO YOLO11m",
            "role": "default",
            "weights": "models/yolo11m.pt",
        },
        "videos": "videos.json",
        "tracks": "tracks.csv",
        "track_summary": "track_summary.json",
        "roi_summary": "roi_summary.json",
        "risk_summary": "risk_summary.json",
        "events": "events.json",
        "validated_events": "validated_events.json",
        "event_assets": "event_assets.json",
        "limitations": [
            "60초 독립 검증 구간의 사전 계산 결과",
            "보수적 단기 track continuation 병합 적용",
            "ROI 집계와 PET/TTC 후보는 수동검증 전 상태",
            "개선 전후 비교는 아직 산출되지 않음",
            "표본 precision은 전체 데이터의 불편 추정치가 아님",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
