"""Prepare deterministic frame sampling pools and contact sheets for TASK-009."""
from __future__ import annotations

import csv
import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPLIT_CONFIG = ROOT / "configs/site_finetune_r01_v1.yaml"
OUT_DIR = ROOT / "outputs/task009/frame_review"
FRAME_LIST = ROOT / "data/training_labels/site_finetune_r01_v1/frame_list.csv"
FPS = 30000 / 1001
TRAIN_SPLIT = "train_candidate"
VAL_SPLIT = "validation_candidate"
HARD_SCENES = {
    "DJI_0481": [659, 1559, 2309],
    "DJI_0482": [500, 2600, 8000],
    "DJI_0483": [800, 1800, 4200],
    "DJI_0484": [300],
    "DJI_0485": [1200, 2400, 5000],
    "DJI_0487": [1500, 3500, 7500, 7900],
}


def ranges_for(config: dict, split: str) -> list[tuple[str, int, int]]:
    out = []
    for clip, record in config["clips"].items():
        for region in record["ranges"]:
            if region["split"] == split:
                out.append((clip, region["start"], region["end"]))
    return out


def stratified_points(ranges: list[tuple[str, int, int]], count: int) -> list[tuple[str, int]]:
    durations = [(clip, start, end, end - start) for clip, start, end in ranges]
    total = sum(item[3] for item in durations)
    result = []
    for index in range(count):
        position = (index + 0.5) * total / count
        for clip, start, end, length in durations:
            if position < length:
                result.append((clip, start + min(length - 1, int(position))))
                break
            position -= length
    return result


def read_frame(clip: str, frame_index: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(ROOT / f"data/raw/before/{clip}.MP4"))
    if not cap.isOpened():
        raise OSError(f"cannot open {clip}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise OSError(f"cannot read {clip} frame {frame_index}")
    return frame


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def create_contact_sheets(uniform: list[tuple[str, int]],
                          validation: list[tuple[str, int]],
                          hard: list[tuple[str, int]]) -> None:
    for pool_name, points in (("uniform_train", uniform), ("validation", validation)):
        for clip in sorted({clip for clip, _ in points}):
            rows = [(name, frame) for name, frame in points if name == clip]
            for offset in range(0, len(rows), 24):
                batch = rows[offset:offset + 24]
                thumbs = []
                for name, frame_index in batch:
                    image = read_frame(name, frame_index)
                    small = cv2.resize(image, (320, 180), interpolation=cv2.INTER_AREA)
                    cv2.putText(small, f"{name} f={frame_index}", (6, 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1,
                                cv2.LINE_AA)
                    thumbs.append(small)
                sheet = np.zeros((180 * math.ceil(len(thumbs) / 4), 320 * 4, 3), dtype=np.uint8)
                for i, thumb in enumerate(thumbs):
                    y, x = divmod(i, 4)
                    sheet[y * 180:(y + 1) * 180, x * 320:(x + 1) * 320] = thumb
                cv2.imwrite(str(OUT_DIR / f"{pool_name}_{clip}_{offset // 24 + 1:02d}.jpg"), sheet)
    thumbs = []
    for clip, frame_index in hard:
        image = read_frame(clip, frame_index)
        small = cv2.resize(image, (320, 180), interpolation=cv2.INTER_AREA)
        cv2.putText(small, f"{clip} f={frame_index}", (6, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)
        thumbs.append(small)
    sheet = np.zeros((180 * math.ceil(len(thumbs) / 4), 320 * 4, 3), dtype=np.uint8)
    for i, thumb in enumerate(thumbs):
        y, x = divmod(i, 4)
        sheet[y * 180:(y + 1) * 180, x * 320:(x + 1) * 320] = thumb
    cv2.imwrite(str(OUT_DIR / "hard_proposals.jpg"), sheet)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-thumbnails", action="store_true")
    args = parser.parse_args()
    config = yaml.safe_load(SPLIT_CONFIG.read_text(encoding="utf-8"))
    train_ranges = ranges_for(config, TRAIN_SPLIT)
    val_ranges = ranges_for(config, VAL_SPLIT)
    uniform = stratified_points(train_ranges, 68)
    validation = stratified_points(val_ranges, 15)
    hard = [(clip, frame) for clip, frames in HARD_SCENES.items() for frame in frames]
    if len(hard) != 17 or len(set(hard)) != 17:
        raise ValueError("the hard-scene sample must contain 17 unique frames")
    for clip, frame in hard:
        if not any(c == clip and start <= frame < end for c, start, end in train_ranges):
            raise ValueError(f"hard-scene frame is outside train candidates: {clip}@{frame}")
        if any(c == clip and abs(frame - f) < round(3 * FPS) for c, f in uniform):
            raise ValueError(f"hard-scene frame is too close to uniform sample: {clip}@{frame}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FRAME_LIST.parent.mkdir(parents=True, exist_ok=True)
    with FRAME_LIST.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["clip_id", "frame_index", "split", "selection_type", "scene_tags", "review_status"])
        writer.writeheader()
        for clip, frame in uniform:
            writer.writerow({"clip_id": clip, "frame_index": frame, "split": "train", "selection_type": "uniform", "scene_tags": "", "review_status": "approved_frozen_checkpoint_1"})
        for clip, frame in hard:
            tags = "tree_shadow;crosswalk_context"
            status = "approved_frozen_checkpoint_1"
            if (clip, frame) == ("DJI_0484", 300):
                tags += ";bus"
            if (clip, frame) in {("DJI_0485", 1200), ("DJI_0483", 4200)}:
                tags += ";two_wheeler"
            if (clip, frame) in {("DJI_0481", 659), ("DJI_0487", 1500)}:
                tags += ";crossing_pedestrian"
            writer.writerow({"clip_id": clip, "frame_index": frame, "split": "train", "selection_type": "hard_scene", "scene_tags": tags, "review_status": status})
        for clip, frame in validation:
            writer.writerow({"clip_id": clip, "frame_index": frame, "split": "validation", "selection_type": "uniform_validation", "scene_tags": "", "review_status": "approved_frozen_checkpoint_1"})
    if not args.skip_thumbnails:
        create_contact_sheets(uniform, validation, hard)

    frame_meta = {
        "code_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       capture_output=True, text=True, check=True).stdout.strip(),
        "generator": str(Path(__file__).relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__).resolve()),
        "split_config": str(SPLIT_CONFIG.relative_to(ROOT)),
        "split_config_sha256": sha256(SPLIT_CONFIG),
        "frame_count": len(uniform) + len(hard) + len(validation),
        "train_uniform_count": len(uniform),
        "train_hard_scene_count": len(hard),
        "validation_count": len(validation),
        "test_clip_opened": False,
        "thumbnails_regenerated": not args.skip_thumbnails,
        "review_status": "approved_frozen_checkpoint_1; user approval 2026-11-09",
        "coordinate_system": "source_frame_index",
        "unit": "frames",
    }
    frame_meta["output_sha256"] = sha256(FRAME_LIST)
    Path(str(FRAME_LIST) + ".meta.json").write_text(
        json.dumps(frame_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for image_path in OUT_DIR.rglob("*.jpg"):
        image_meta = {**frame_meta, "output_sha256": sha256(image_path),
                      "artifact": image_path.name}
        if image_path.parent.name == "full_resolution":
            match = re.fullmatch(r"(DJI_\d{4})_(\d+)\.jpg", image_path.name)
            if match:
                image_meta.update({
                    "source_video": f"data/raw/before/{match.group(1)}.MP4",
                    "representative_frame": int(match.group(2)),
                    "split": "train",
                    "preview_resolution": "full source frame",
                })
        Path(str(image_path) + ".meta.json").write_text(
            json.dumps(image_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps({
        "uniform_train_count": len(uniform),
        "validation_count": len(validation),
        "hard_candidate_count": len(hard),
        "hard_candidate_sheets": 1,
        "minimum_uniform_train_spacing_seconds": 3,
        "frame_list": str(FRAME_LIST.relative_to(ROOT)),
        "contact_sheets": str(OUT_DIR.relative_to(ROOT)),
        "test_clip_opened": False,
        "hard_rows_status": "17 approved frozen hard-scene samples",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
