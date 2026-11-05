from __future__ import annotations

import csv
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ground_truth/revise_detection_gt_v2.py"
SPEC = importlib.util.spec_from_file_location("revise_detection_gt_v2", SCRIPT)
assert SPEC and SPEC.loader
revision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(revision)


class DetectionGtV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.observations = self.root / "observations.csv"
        self.skips = self.root / "skips.csv"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_work(self, observations: list[dict[str, str]], skips: list[dict[str, str]] | None = None) -> None:
        with self.observations.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=revision.OBS_HEADERS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(observations)
        with self.skips.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=revision.SKIP_HEADERS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(skips or [])

    def row(self, **updates: str) -> dict[str, str]:
        row = {key: "" for key in revision.OBS_HEADERS}
        row.update({"schema_version": "detection_box_gt_v2",
                    "gt_dataset_id": revision.DATASET_ID,
                    "video_id": "DJI_0482", "gt_object_id": "P001", "frame_index": "4196", "x1": "10", "y1": "20",
                    "x2": "30", "y2": "60", "ignore": "false", "label_source": "v1_box",
                    "revision_action": "kept"})
        row.update(updates)
        return row

    def test_ignore_box_is_valid_and_remains_an_observation(self) -> None:
        self.write_work([self.row(ignore="true")])
        observations, skips = revision.validate_work(self.observations, self.skips)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["ignore"], "true")
        self.assertEqual(skips, [])

    def test_invalid_revision_fields_and_box_bounds_are_rejected(self) -> None:
        bad = self.row(revision_action="copied", x2="3841")
        self.write_work([bad])
        with self.assertRaisesRegex(ValueError, "invalid frame or box bounds"):
            revision.validate_work(self.observations, self.skips)

    def test_duplicate_anchor_and_observation_skip_collision_are_rejected(self) -> None:
        self.write_work([self.row()], [{"gt_object_id": "P001", "frame_index": "4196",
                                      "reason": "not_found", "notes": ""}])
        with self.assertRaisesRegex(ValueError, "observation and skip"):
            revision.validate_work(self.observations, self.skips)

    def test_v1_canonical_files_keep_frozen_hashes(self) -> None:
        expected = {
            "gt_observations.csv": "2cd303f453919d0021797ae528fac5f22661ab851c9116b884bd642e4fb31658",
            "ground_truth_manifest.json": "d9d3139a918c42f93b26f52a8967e7b1bcd923cedf6cf89f8998f67169affc3b",
            "gt_objects.csv": "23bc09061015f3f57340e35c5eb0c6782a3cb608d5effd444aa59cedfa7bfee8",
            "gt_visibility_intervals.csv": "9190a8deec308ff74d5563509f54caebc5f9f4dce50ba87d9e0a6122f82757dd",
        }
        for name, digest in expected.items():
            path = ROOT / "data/ground_truth/object_track_v1" / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
