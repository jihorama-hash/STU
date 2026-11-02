from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GT = ROOT / "data/ground_truth/object_track_v1"
REVIEW = GT / "review"
BACKUP = ROOT / "outputs/diagnostics/R01_visibility_backup_20261102_final"
INPUTS = {
    "inventory": REVIEW / "gate3a2_object_inventory_R01.csv",
    "visibility": REVIEW / "gate3a2_visibility_R01.csv",
    "observations": REVIEW / "gt_observations_R01.csv",
    "skips": REVIEW / "gt_observation_skips_R01.csv",
    "reason_map": REVIEW / "occlusion_reason_map_R01.csv",
    "canonical_objects": GT / "gt_objects.csv",
    "canonical_visibility": GT / "gt_visibility_intervals.csv",
    "manifest": GT / "ground_truth_manifest.json",
}

# These intervals are derived from the user's reviewed skip decisions. Ranges
# represent consecutive frames where the target identity or location could not
# be established; original skip rows are retained in the backup.
EXCLUSIONS = {
    "P002": [(4678, 4792, "frame_boundary", "screen exit; original note: 화면 밖으로 나가서 안 보임")],
    "P004": [(4930, 5000, "tree", "reviewed not_found anchors: 4930,4946,4976,5000")],
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


def split_visibility(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[tuple[str, int], tuple[str, str]]]:
    by_object: dict[str, list[tuple[int, int, str, str, str]]] = {}
    for object_id, intervals in EXCLUSIONS.items():
        for start, end, reason, note in intervals:
            by_object.setdefault(object_id, []).append((start, end, reason, note, ""))

    new_rows: list[dict[str, str]] = []
    targeted: dict[tuple[str, int], tuple[str, str]] = {}
    for row in rows:
        object_id = row["gt_object_id"]
        start, end = int(row["start_frame_index"]), int(row["end_frame_index"])
        cuts = sorted(
            (max(start, lo), min(end, hi), reason, note)
            for lo, hi, reason, note, _ in by_object.get(object_id, [])
            if lo <= end and hi >= start
        )
        cursor = start

        def add_piece(piece_start: int, piece_end: int, status: str, reason: str, note: str) -> None:
            if piece_start > piece_end:
                return
            piece = dict(row)
            piece["start_frame_index"] = str(piece_start)
            piece["end_frame_index"] = str(piece_end)
            piece["visibility_status"] = status
            piece["occlusion_reason"] = reason
            if note:
                piece["notes"] = "; ".join(filter(None, [row.get("notes", ""), note]))
            new_rows.append(piece)
            if status == "not_observable":
                for frame in range(piece_start, piece_end + 1, 2):
                    targeted[(object_id, frame)] = (reason, note)

        for cut_start, cut_end, reason, note in cuts:
            if cut_start > cursor:
                add_piece(cursor, cut_start - 2, row["visibility_status"], row["occlusion_reason"], "")
            add_piece(cut_start, cut_end, "not_observable", reason, note)
            cursor = cut_end + 2
        if cursor <= end:
            add_piece(cursor, end, row["visibility_status"], row["occlusion_reason"], "")
    return new_rows, targeted


def main() -> None:
    if BACKUP.exists():
        raise SystemExit(f"backup already exists; refusing to overwrite: {BACKUP}")
    fields = {key: read_csv(path)[0] for key, path in INPUTS.items() if path.suffix == ".csv"}
    tables = {key: read_csv(path)[1] for key, path in INPUTS.items() if path.suffix == ".csv"}
    original_skips = tables["skips"]
    obs_keys = {(r["gt_object_id"], int(r["frame_index"])) for r in tables["observations"]}
    skip_keys = {(r["gt_object_id"], int(r["frame_index"])) for r in original_skips}

    new_visibility, excluded_keys = split_visibility(tables["visibility"])
    skip_keys_to_drop = {
        ("P002", 4706), ("P002", 4736), ("P002", 4766), ("P002", 4792),
        ("P004", 4930), ("P004", 4946), ("P004", 4976), ("P004", 5000),
    }
    if not skip_keys_to_drop.issubset(skip_keys):
        raise RuntimeError(f"expected skip rows are missing: {sorted(skip_keys_to_drop - skip_keys)}")
    if not skip_keys_to_drop.issubset(excluded_keys):
        raise RuntimeError("visibility exclusions do not cover all selected skip rows")
    if skip_keys & obs_keys:
        raise RuntimeError("a skip frame also has an observation")
    # Preserve all source and canonical inputs before changing any review data.
    BACKUP.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for key, path in INPUTS.items():
        target = BACKUP / path.name
        shutil.copy2(path, target)
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except subprocess.CalledProcessError:
        commit = "unknown"
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": commit,
        "source_file_hashes_sha256": hashes,
        "review_status": "diagnostic_backup_before_user-authorized_reconciliation",
        "gt_modified": False,
    }
    (BACKUP / "backup.meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    reason_fields = fields["reason_map"]
    reason_map = tables["reason_map"]
    existing = {row["raw_value"] for row in reason_map}
    additions = [
        {
            "raw_value": "frame_boundary",
            "canonical_value": "frame_boundary",
            "description": "화면 경계로 객체 위치 또는 동일성을 신뢰성 있게 판독할 수 없음.",
        },
    ]
    reason_map.extend(row for row in additions if row["raw_value"] not in existing)

    retained_skips = [
        row for row in original_skips
        if (row["gt_object_id"], int(row["frame_index"])) not in excluded_keys
    ]
    write_csv(REVIEW / "gate3a2_visibility_R01.csv", fields["visibility"], new_visibility)
    write_csv(REVIEW / "gt_observation_skips_R01.csv", fields["skips"], retained_skips)
    write_csv(REVIEW / "occlusion_reason_map_R01.csv", reason_fields, reason_map)
    print(f"excluded_skip_rows={len(original_skips) - len(retained_skips)}")
    print(f"remaining_skip_rows={len(retained_skips)}")
    print(f"new_visibility_rows={len(new_visibility)}")
    print(f"backup={BACKUP}")


if __name__ == "__main__":
    main()
