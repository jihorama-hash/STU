"""Generate low-confidence TASK-009 draft boxes for the approved 100 frames."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from roundabout.detect_track import CLASS_PROFILES, detect_sliced, make_slices  # noqa: E402
from roundabout.site_finetune_labels import (  # noqa: E402
    assert_frame_allowed,
    load_frame_whitelist,
    mask_outside_polygon,
    polygon_from_mask,
    validate_box_in_polygon,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame-list", default="data/training_labels/site_finetune_r01_v1/frame_list.csv")
    parser.add_argument("--weights", default="models/yolo11m.pt")
    parser.add_argument("--output", default="data/training_labels/site_finetune_r01_v1/model_drafts.json")
    parser.add_argument("--confidence", type=float, default=0.05)
    parser.add_argument("--device", default="0")
    parser.add_argument("--radius", type=int, default=200)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable; draft inference was not run")
    if not 0 < args.confidence < 1:
        raise SystemExit("--confidence must be between 0 and 1")
    frame_list_path = ROOT / args.frame_list
    weights_path = ROOT / args.weights
    output_path = ROOT / args.output
    whitelist = load_frame_whitelist(frame_list_path)
    with frame_list_path.open(encoding="utf-8-sig", newline="") as stream:
        frame_rows = list(csv.DictReader(stream))
    model = YOLO(str(weights_path))
    profile = CLASS_PROFILES["coco"]
    rows = []
    for frame_row in frame_rows:
        clip = frame_row["clip_id"]
        frame_index = int(frame_row["frame_index"])
        approved = assert_frame_allowed(whitelist, clip, frame_index)
        if approved["split"] not in {"train", "validation"}:
            raise ValueError(f"forbidden frame in draft list: {clip}@{frame_index}")
        capture = cv2.VideoCapture(str(ROOT / f"data/raw/before/{clip}.MP4"))
        if not capture.isOpened():
            raise OSError(f"could not open {clip}")
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            raise OSError(f"could not read {clip}@{frame_index}")
        mask_id = "DJI_0483_Cut" if clip == "DJI_0483" else clip
        polygon = polygon_from_mask(
            ROOT / f"data/calibration/by_video/{mask_id}_roadway_mask.png", args.radius
        )
        inference_frame = mask_outside_polygon(frame, polygon, [], gray=96)
        slices = make_slices(frame.shape[1], frame.shape[0], 1024, 1024, 0.2)
        boxes, scores, class_ids, source_classes, source_names = detect_sliced(
            model, inference_frame, slices, args.confidence, 0.5, 1024,
            args.device, "coco",
        )
        objects = []
        for index, (box, score, class_id, source_class, source_name) in enumerate(
            zip(boxes, scores, class_ids, source_classes, source_names), start=1
        ):
            x1, y1, x2, y2 = map(float, box)
            record = {
                "object_id": f"{clip}_{frame_index}_draft_{index:03d}",
                "class_name": profile[int(source_class)][1],
                "source_class_id": int(source_class),
                "source_class_name": str(source_name),
                "class_id": int(class_id),
                "confidence": float(score),
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "ignore": False, "attributes": [],
                "label_source": "model_draft", "revision_action": "new",
            }
            try:
                validate_box_in_polygon(record, polygon)
            except ValueError:
                continue
            objects.append(record)
        rows.append({
            "clip_id": clip,
            "frame_index": frame_index,
            "split": approved["split"],
            "selection_type": frame_row["selection_type"],
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
            "objects": objects,
        })
        print(f"{clip}@{frame_index}: {len(objects)} draft boxes", flush=True)
    result = {
        "schema_version": "site_finetune_frame_labels_v1",
        "task": "TASK-009",
        "draft_only": True,
        "inference": {"weights": args.weights, "confidence": args.confidence,
                      "iou": 0.5, "slice": [1024, 1024], "overlap": 0.2,
                      "polygon_radius_px": args.radius},
        "frames": {f"{r['clip_id']}@{r['frame_index']}": r for r in rows},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": __import__("subprocess").run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True
        ).stdout.strip(),
        "frame_list": args.frame_list,
        "frame_list_sha256": sha256(frame_list_path),
        "weights_sha256": sha256(weights_path),
        "script_sha256": sha256(Path(__file__).resolve()),
        "output_sha256": sha256(output_path),
        "coordinate_system": "source_pixel",
        "unit": "pixels",
        "review_status": "unreviewed_model_draft",
        "frame_count": len(rows),
        "box_count": sum(len(row["objects"]) for row in rows),
    }
    Path(str(output_path) + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"frame_count": len(rows), "box_count": meta["box_count"],
                      "output": str(output_path.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
