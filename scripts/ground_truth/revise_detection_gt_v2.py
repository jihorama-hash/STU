"""Validate and canonicalize the isolated R01 detection-box GT v2 review."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "data/ground_truth/object_track_v1"
V2 = ROOT / "data/ground_truth/object_track_v2"
WORK = V2 / "review"
DATASET_ID = "DJI_0482_R01_detection_box_v2"
OBS_HEADERS = tuple(next(csv.reader((V1 / "gt_observations.template.csv").open(encoding="utf-8-sig")))) + (
    "ignore", "attributes", "label_source", "revision_action"
)
SKIP_HEADERS = ("gt_object_id", "frame_index", "reason", "notes")
ACTIONS = {"kept", "adjusted", "redrawn", "new"}
ATTRIBUTES = {"umbrella=true", "pm=true", "truncated=true"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rows(path: Path, headers: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != headers:
            raise ValueError(f"{path}: header must be {','.join(headers)}")
        rows = list(reader)
    return rows


def validate_work(observations_path: Path, skips_path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    observations = read_rows(observations_path, OBS_HEADERS)
    skips = read_rows(skips_path, SKIP_HEADERS)
    seen: set[tuple[str, str]] = set()
    errors: list[str] = []
    for i, row in enumerate(observations, 2):
        key = (row["gt_object_id"], row["frame_index"])
        if row["schema_version"] != "detection_box_gt_v2" or row["gt_dataset_id"] != DATASET_ID:
            errors.append(f"observation row {i}: v2 schema or dataset ID mismatch")
        if key in seen:
            errors.append(f"observation row {i}: duplicate object/frame {key}")
        seen.add(key)
        try:
            x1, y1, x2, y2 = (int(row[k]) for k in ("x1", "y1", "x2", "y2"))
            frame = int(row["frame_index"])
        except ValueError:
            errors.append(f"observation row {i}: frame/box coordinates must be integers")
            continue
        if frame < 0 or not (0 <= x1 < x2 <= 3840 and 0 <= y1 < y2 <= 2160):
            errors.append(f"observation row {i}: invalid frame or box bounds")
        if row["ignore"] not in {"true", "false"}:
            errors.append(f"observation row {i}: ignore must be true/false")
        if row["label_source"] not in {"manual", "v1_box"}:
            errors.append(f"observation row {i}: invalid label_source")
        if row["revision_action"] not in ACTIONS:
            errors.append(f"observation row {i}: invalid revision_action")
        if any(a not in ATTRIBUTES for a in row["attributes"].split(";") if a):
            errors.append(f"observation row {i}: unsupported attributes")
        if row["revision_action"] == "new" and row["label_source"] != "manual":
            errors.append(f"observation row {i}: new boxes must have label_source=manual")
    skip_keys: set[tuple[str, str]] = set()
    for i, row in enumerate(skips, 2):
        key = (row["gt_object_id"], row["frame_index"])
        if key in skip_keys:
            errors.append(f"skip row {i}: duplicate object/frame {key}")
        skip_keys.add(key)
        if key in seen:
            errors.append(f"skip row {i}: same anchor has an observation and skip")
        if row["reason"] not in {"not_found", "ambiguous_identity", "occluded_more_than_marked", "other"}:
            errors.append(f"skip row {i}: unsupported reason {row['reason']!r}")
    if errors:
        raise ValueError("\n".join(errors))
    return observations, skips


def _write_csv(path: Path, headers: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_canonical(observations: list[dict[str, str]], skips: list[dict[str, str]]) -> dict[str, str]:
    if len(observations) + len(skips) != 970:
        raise ValueError(f"expected all 970 anchors resolved; got {len(observations) + len(skips)}")
    out = V2 / "canonical"
    if out.exists() and (out / "ground_truth_manifest.json").exists():
        raise FileExistsError(f"Refusing to overwrite existing canonical GT v2: {out}")
    out.mkdir(parents=True, exist_ok=True)
    source_manifest = json.loads((V1 / "ground_truth_manifest.json").read_text(encoding="utf-8"))
    files: dict[str, Path] = {}
    for name in ("gt_objects.csv", "gt_visibility_intervals.csv"):
        rows = list(csv.DictReader((V1 / name).open(encoding="utf-8-sig", newline="")))
        for row in rows:
            row["schema_version"] = "detection_box_gt_v2"
            row["gt_dataset_id"] = DATASET_ID
        target = out / name
        _write_csv(target, tuple(rows[0].keys()), rows)
        files[name] = target
    for name, rows, headers in (
        ("gt_observations.csv", observations, OBS_HEADERS),
        ("gt_observation_skips.csv", skips, SKIP_HEADERS),
    ):
        normalized = []
        for source in rows:
            row = dict(source)
            if name == "gt_observations.csv":
                row["schema_version"] = "detection_box_gt_v2"
                row["gt_dataset_id"] = DATASET_ID
            normalized.append(row)
        target = out / name
        _write_csv(target, headers, normalized)
        files[name] = target
    manifest = dict(source_manifest)
    manifest.update({"schema_version": "detection_box_gt_v2", "gt_dataset_id": DATASET_ID,
                     "dataset_status": "draft", "frozen_version": "v2"})
    manifest["scope"]["object_classes"] = ["person", "bicycle", "car", "motorcycle", "bus", "truck"]
    manifest["files"] = {**manifest["files"], "objects": "canonical/gt_objects.csv",
                          "visibility_intervals": "canonical/gt_visibility_intervals.csv",
                          "observations": "canonical/gt_observations.csv"}
    manifest["files"]["observation_skips"] = "canonical/gt_observation_skips.csv"
    manifest["annotation"]["protocol_path"] = "docs/validation/DETECTION_LABEL_RULES.md"
    manifest["annotation"]["updated_at_utc"] = datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    manifest["frozen_files"] = {
        "objects": {"path": "canonical/gt_objects.csv", "row_count": sum(1 for _ in csv.DictReader((out / "gt_objects.csv").open(encoding="utf-8"))), "sha256": sha256(out / "gt_objects.csv")},
        "visibility_intervals": {"path": "canonical/gt_visibility_intervals.csv", "row_count": sum(1 for _ in csv.DictReader((out / "gt_visibility_intervals.csv").open(encoding="utf-8"))), "sha256": sha256(out / "gt_visibility_intervals.csv")},
        "observations": {"path": "canonical/gt_observations.csv", "row_count": len(observations), "sha256": sha256(out / "gt_observations.csv")},
        "observation_skips": {"path": "canonical/gt_observation_skips.csv", "row_count": len(skips), "sha256": sha256(out / "gt_observation_skips.csv")},
    }
    manifest_path = out / "ground_truth_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
    meta = {"created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "code_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "code_worktree_diff_sha256": hashlib.sha256(diff).hexdigest() if diff else None,
            "code_sha256": sha256(Path(__file__)), "input_sha256": {
                "v1_manifest": sha256(V1 / "ground_truth_manifest.json"),
                "v1_observations": sha256(V1 / "gt_observations.csv"),
                "v2_work_observations": sha256(WORK / "gt_observations_R01_v2.csv"),
                "v2_work_skips": sha256(WORK / "gt_observation_skips_R01_v2.csv")},
            "files": {path.name: sha256(path) for path in files.values()},
            "coordinate_system": "source_pixel", "unit": "px", "review_status": "draft"}
    for path in files.values():
        path.with_suffix(path.suffix + ".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "ground_truth_manifest.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {name: sha256(path) for name, path in files.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--build-canonical", action="store_true")
    args = parser.parse_args()
    observations, skips = validate_work(WORK / "gt_observations_R01_v2.csv", WORK / "gt_observation_skips_R01_v2.csv")
    print(f"v2 annotation validation: OK — observations={len(observations)}, skips={len(skips)}")
    if args.build_canonical:
        hashes = build_canonical(observations, skips)
        print(f"canonical GT v2 written: {V2 / 'canonical'}; files={len(hashes)}")
        for name, digest in hashes.items():
            print(f"sha256 {name} {digest}")


if __name__ == "__main__":
    main()
