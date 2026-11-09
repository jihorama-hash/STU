from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from roundabout.site_finetune_labels import (
    LabelValidationError,
    assert_frame_allowed,
    load_frame_whitelist,
    mask_outside_polygon,
    merge_boxes,
    validate_box_in_polygon,
    validate_label_record,
)


class SiteFinetuneLabelsTestCase(unittest.TestCase):
    def test_test_and_excluded_frames_cannot_enter_whitelist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "frames.csv"
            path.write_text(
                "clip_id,frame_index,split\nDJI_0486,100,test\n", encoding="utf-8"
            )
            with self.assertRaises(LabelValidationError):
                load_frame_whitelist(path)

    def test_only_explicit_train_and_validation_frames_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "frames.csv"
            path.write_text(
                "clip_id,frame_index,split\nDJI_0481,10,train\nDJI_0488,20,validation\n",
                encoding="utf-8",
            )
            whitelist = load_frame_whitelist(path)
            self.assertEqual(assert_frame_allowed(whitelist, "DJI_0481", 10)["split"], "train")
            with self.assertRaises(LabelValidationError):
                assert_frame_allowed(whitelist, "DJI_0486", 10)

    def test_outside_polygon_is_gray_but_label_pixels_are_preserved(self) -> None:
        frame = np.full((4, 4, 3), 200, dtype=np.uint8)
        polygon = np.zeros((4, 4), dtype=np.uint8)
        polygon[1:3, 1:3] = 255
        boxes = [{"x1": 0, "y1": 0, "x2": 1, "y2": 1}]
        masked = mask_outside_polygon(frame, polygon, boxes)
        self.assertTrue(np.all(masked[0, 0] == 200))
        self.assertTrue(np.all(masked[0, 1] == 96))
        self.assertTrue(np.all(masked[1, 1] == 200))

    def test_ignore_box_is_gray_and_visible_overlapping_box_is_restored(self) -> None:
        frame = np.full((6, 6, 3), 200, dtype=np.uint8)
        polygon = np.full((6, 6), 255, dtype=np.uint8)
        boxes = [
            {"x1": 1, "y1": 1, "x2": 5, "y2": 5, "ignore": True},
            {"x1": 3, "y1": 3, "x2": 6, "y2": 6, "ignore": False},
        ]
        masked = mask_outside_polygon(frame, polygon, boxes)
        self.assertTrue(np.all(masked[1, 1] == 96))
        self.assertTrue(np.all(masked[3, 3] == 200))

    def test_label_format_checks_bounds_class_and_attributes(self) -> None:
        record = {
            "object_id": "o1", "class_name": "person", "class_id": 0, "x1": 1, "y1": 2,
            "x2": 9, "y2": 12, "ignore": False, "attributes": ["umbrella"],
            "label_source": "manual", "revision_action": "new",
        }
        validate_label_record(record, 20, 20)
        with self.assertRaises(LabelValidationError):
            validate_label_record({**record, "x2": 21}, 20, 20)
        with self.assertRaises(LabelValidationError):
            validate_label_record({**record, "attributes": ["other"]}, 20, 20)

    def test_box_outside_analysis_polygon_is_blocked(self) -> None:
        polygon = np.zeros((20, 20), dtype=np.uint8)
        polygon[5:15, 5:15] = 255
        record = {"x1": 6, "y1": 6, "x2": 10, "y2": 10}
        validate_box_in_polygon(record, polygon)
        with self.assertRaises(LabelValidationError):
            validate_box_in_polygon({"x1": 0, "y1": 0, "x2": 2, "y2": 2}, polygon)

    def test_rider_and_two_wheeler_boxes_merge_into_one_vehicle_box(self) -> None:
        boxes = [
            {"object_id": "p1", "class_name": "person", "class_id": 0, "x1": 2, "y1": 3,
             "x2": 8, "y2": 15, "ignore": False, "attributes": ["pm"],
             "label_source": "model_draft", "revision_action": "new"},
            {"object_id": "m1", "class_name": "motorcycle", "class_id": 3, "x1": 5, "y1": 12,
             "x2": 18, "y2": 25, "ignore": False, "attributes": [],
             "label_source": "model_draft", "revision_action": "new"},
        ]
        merged = merge_boxes(boxes, ["p1", "m1"], "motorcycle")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["class_name"], "motorcycle")
        self.assertEqual(merged[0]["class_id"], 3)
        self.assertEqual([merged[0][k] for k in ("x1", "y1", "x2", "y2")], [2, 3, 18, 25])
        self.assertEqual(merged[0]["merged_from"], ["m1", "p1"])


if __name__ == "__main__":
    unittest.main()
