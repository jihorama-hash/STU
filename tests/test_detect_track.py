import unittest

import numpy as np

from roundabout.detect_track import (
    CLASS_PROFILES,
    classwise_nms,
    make_slices,
    match_source_details,
)


class DetectionUtilitiesTest(unittest.TestCase):
    def test_4k_slices_cover_edges(self) -> None:
        slices = make_slices(3840, 2160, 1024, 1024, 0.2)
        self.assertEqual(len(slices), 15)
        self.assertEqual(max(item[2] for item in slices), 3840)
        self.assertEqual(max(item[3] for item in slices), 2160)

    def test_nms_does_not_suppress_different_classes(self) -> None:
        boxes = np.asarray([[0, 0, 10, 10], [0, 0, 10, 10]], dtype=np.float32)
        scores = np.asarray([0.9, 0.8], dtype=np.float32)
        classes = np.asarray([0, 2], dtype=int)
        keep = classwise_nms(boxes, scores, classes, 0.5)
        self.assertEqual(set(keep.tolist()), {0, 1})

    def test_visdrone_person_classes_are_merged_before_tracking(self) -> None:
        profile = CLASS_PROFILES["visdrone"]
        self.assertEqual(profile[0][:2], (0, "person"))
        self.assertEqual(profile[1][:2], (0, "person"))
        self.assertNotEqual(profile[0][2], profile[1][2])

    def test_visdrone_source_detail_is_preserved(self) -> None:
        profile = CLASS_PROFILES["visdrone"]
        self.assertEqual(profile[4], (2, "car", "van"))
        self.assertEqual(profile[7], (10, "tricycle", "awning-tricycle"))

    def test_source_detail_is_recovered_by_box_overlap(self) -> None:
        tracked = np.asarray([[1, 1, 11, 11]], dtype=np.float32)
        detections = np.asarray(
            [[20, 20, 30, 30], [0, 0, 10, 10]], dtype=np.float32
        )
        details = match_source_details(
            tracked,
            detections,
            np.asarray([1, 0]),
            np.asarray(["people", "pedestrian"], dtype=object),
        )
        self.assertEqual(details, [(0, "pedestrian")])
