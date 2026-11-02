from __future__ import annotations

import copy
import csv
import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/ground_truth/build_canonical_observations_R01.py"
SPEC = importlib.util.spec_from_file_location("build_canonical_observations_R01", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)


def fixture():
    manifest = {
        "schema_version": "object_track_gt_v1",
        "gt_dataset_id": "pilot_v1",
        "video": {
            "video_id": "DJI_0482", "source_fps": 30000 / 1001,
            "coordinate_system": "source_pixel", "position_unit": "px",
        },
        "annotation": {"reviewers": ["R01"]},
    }
    objects = [{"gt_object_id": "P001", "object_class": "person", "in_scope": "true"}]
    visibility = [{
        "gt_object_id": "P001", "start_frame_index": "4196", "end_frame_index": "4200",
        "visibility_status": "visible",
    }]
    row = {field: "" for field in BUILDER.INPUT_FIELDS}
    row.update({
        "gt_object_id": "P001", "frame_index": "4196", "object_class": "wrong source value",
        "x1": "10.0", "y1": "20", "x2": "30", "y2": "60",
        "foot_x": "21.5", "foot_y": "58.5", "visibility_status": "wrong source value",
        "observation_method": "manual", "in_scope": "true", "review_timestamp_utc": "2026-10-30T00:00:00Z",
        "review_status": "draft", "notes": "human note",
    })
    return row, objects, visibility, manifest


class BuildCanonicalObservationsR01Test(unittest.TestCase):
    def test_preserves_manual_boxes_and_derives_canonical_fields(self):
        row, objects, visibility, manifest = fixture()
        result = BUILDER.build_rows([row], objects, visibility, manifest)[0]
        self.assertEqual([result[key] for key in ("x1", "y1", "x2", "y2")], ["10.0", "20", "30", "60"])
        self.assertEqual((result["foot_x"], result["foot_y"]), ("20.0", "60.0"))
        self.assertEqual(result["object_class"], "person")
        self.assertEqual(result["visibility_status"], "visible")
        self.assertEqual(result["timestamp_seconds"], repr(4196 / (30000 / 1001)))
        self.assertEqual(result["notes"], "human note")
        self.assertEqual(result["review_timestamp_utc"], "2026-10-30T00:00:00Z")
        self.assertEqual(result["review_status"], "draft")

    def test_keeps_human_adjusted_foot_point(self):
        row, objects, visibility, manifest = fixture()
        row.update({"foot_x": "21.5", "foot_y": "58.5", "notes": "foot_adjusted; copied_from_previous"})
        result = BUILDER.build_rows([row], objects, visibility, manifest)[0]
        self.assertEqual((result["foot_x"], result["foot_y"]), ("21.5", "58.5"))

    def test_rejects_duplicate_and_excluded_observations(self):
        row, objects, visibility, manifest = fixture()
        with self.assertRaisesRegex(BUILDER.InputValidationError, "duplicate observation"):
            BUILDER.build_rows([row, copy.deepcopy(row)], objects, visibility, manifest)
        visibility[0]["visibility_status"] = "fully_occluded"
        with self.assertRaisesRegex(BUILDER.InputValidationError, "denominator-excluded"):
            BUILDER.build_rows([row], objects, visibility, manifest)

    def test_repository_conversion_has_960_rows_and_is_repeatable(self):
        root = Path(__file__).parents[1] / "data/ground_truth/object_track_v1"
        args = (root / "review/gt_observations_R01.csv", root / "gt_objects.csv",
                root / "gt_visibility_intervals.csv", root / "ground_truth_manifest.json")
        source_rows = BUILDER.read_csv(args[0], BUILDER.INPUT_FIELDS)
        objects = BUILDER.read_csv(args[1], BUILDER.OBJECT_FIELDS)
        visibility = BUILDER.read_csv(args[2], BUILDER.VISIBILITY_FIELDS)
        manifest = json.loads(args[3].read_text(encoding="utf-8"))
        first = BUILDER.build_rows(source_rows, objects, visibility, manifest)
        second = BUILDER.build_rows(copy.deepcopy(source_rows), objects, visibility, copy.deepcopy(manifest))
        self.assertEqual(len(first), 960)
        self.assertEqual(first, second)
        self.assertEqual(len({(r["gt_object_id"], r["frame_index"]) for r in first}), 960)


if __name__ == "__main__":
    unittest.main()
