import unittest
import hashlib
import tempfile
from pathlib import Path

from roundabout.evaluate_object_track import (
    box_iou,
    class_compatible,
    count_id_switches,
    coverage_status,
    evaluate_stage,
    fragmentation_count,
    match_frame,
    maximum_missing_anchors,
    select_complete_frames,
    trajectory_labels,
    verify_frozen_hash,
    EvaluationError,
)


def gt(object_id="g1", frame=0, box=(0, 0, 10, 10), object_class="person"):
    return {
        "gt_object_id": object_id, "frame_index": frame,
        "object_class": object_class, "x1": str(box[0]), "y1": str(box[1]),
        "x2": str(box[2]), "y2": str(box[3]), "box": tuple(float(v) for v in box),
    }


def auto(track_id="1", frame=0, box=(0, 0, 10, 10), object_class="person"):
    return {
        "track_id": track_id, "frame_index": frame, "object_class": object_class,
        "box": tuple(float(value) for value in box),
    }


class ObjectTrackEvaluationTest(unittest.TestCase):
    def test_iou_and_exact_threshold_match(self):
        self.assertAlmostEqual(box_iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)
        # Intersection=50, union=100.
        self.assertAlmostEqual(box_iou((0, 0, 10, 10), (0, 0, 5, 10)), 0.5)
        matches = match_frame([gt()], [auto(box=(0, 0, 5, 10))], 0.5)
        self.assertEqual(len(matches), 1)
        self.assertAlmostEqual(matches[0][2], 0.5)

    def test_assignment_is_one_to_one(self):
        matches = match_frame(
            [gt("g1"), gt("g2", box=(1, 0, 11, 10))],
            [auto("a1"), auto("a2")],
            0.3,
        )
        self.assertEqual(len(matches), 2)
        self.assertEqual(len({match[0] for match in matches}), 2)
        self.assertEqual(len({match[1] for match in matches}), 2)

    def test_below_threshold_pairs_are_zeroed_before_assignment(self):
        gt_boxes = [gt("g1", box=(8, 2, 20, 10)), gt("g2", box=(14, 4, 26, 12))]
        auto_boxes = [auto("a1", box=(4, 4, 16, 10)), auto("a2", box=(12, 2, 22, 10))]
        # Raw-IoU assignment chooses the diagonal (0.4, 0.375), then rejects
        # both. Zeroing sub-threshold edges first lets the valid 0.571 edge win.
        matches = match_frame(gt_boxes, auto_boxes, 0.5)
        self.assertEqual([(gt_index, auto_index) for gt_index, auto_index, _ in matches], [(0, 1)])

    def test_mt_pt_ml_boundaries(self):
        self.assertEqual(trajectory_labels(0.8), "MT")
        self.assertEqual(trajectory_labels(0.2), "PT")
        self.assertEqual(trajectory_labels(0.1999), "ML")

    def test_complete_partial_missed_boundaries(self):
        self.assertEqual(coverage_status(8, 8, 10), "complete")
        self.assertEqual(coverage_status(8, 7, 10), "partial")
        self.assertEqual(coverage_status(0, 0, 10), "missed")

    def test_fragmentation_and_id_switch_count(self):
        self.assertEqual(fragmentation_count(["a", "a", "b"]), 1)
        self.assertEqual(count_id_switches([("g", "a"), ("g", "a"), ("g", "b")]), 1)

    def test_missing_anchor_run_and_complete_frame_selection(self):
        self.assertEqual(maximum_missing_anchors([1, 2, 3, 4], {1, 4}), 2)
        self.assertEqual(
            select_complete_frames(
                [1, 2], {1: {"a", "b"}, 2: {"a"}},
                {1: {"a", "b"}, 2: {"a"}},
            ),
            [1, 2],
        )
        self.assertEqual(
            select_complete_frames([1], {1: {"a", "b"}}, {1: {"a"}}), []
        )

    def test_class_compatibility_table(self):
        self.assertTrue(class_compatible("person", "person"))
        self.assertTrue(class_compatible("car", "bus"))
        self.assertTrue(class_compatible("car", "truck"))
        self.assertTrue(class_compatible("motorcycle", "motorcycle"))
        self.assertTrue(class_compatible("bicycle", "bicycle"))
        self.assertFalse(class_compatible("motorcycle", "bicycle"))

    def test_frozen_ground_truth_hash_mismatch_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gt.csv"
            path.write_text("frozen bytes", encoding="utf-8")
            expected = hashlib.sha256(b"different bytes").hexdigest()
            with self.assertRaisesRegex(EvaluationError, "SHA-256 mismatch"):
                verify_frozen_hash(path, expected)

    def test_perfect_prediction_has_hota_and_idf1_one(self):
        observations = [gt(frame=0), gt(frame=1)]
        predictions = [auto(frame=0), auto(frame=1)]
        result = evaluate_stage(observations, predictions, [0, 1], [0.5])
        metrics = result["thresholds"]["iou_0.5"]["frames"]
        self.assertEqual(metrics["idf1"], 1.0)
        self.assertEqual(metrics["hota"]["HOTA"]["alpha_mean"], 1.0)
        self.assertEqual(metrics["hota"]["HOTA"]["alpha_0_5"], 1.0)


if __name__ == "__main__":
    unittest.main()
