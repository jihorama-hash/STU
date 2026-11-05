from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from roundabout.detect_frames import detection_frame_indices, detection_tile_ids
from roundabout.evaluate_detection import (
    DetectionEvaluationError, average_precision, build_ignore_ground_truth,
    complete_detection_frames, configured_average_precision,
    decompose_tracker_loss, detection_metrics,
    load_validated_detection_artifact, validate_inference_metadata,
    load_evaluation_config, rider_inside_vehicle_sensitivity,
)


class DetectionEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gt = [{
            "frame_index": 10, "object_class": "person",
            "box": [0.0, 0.0, 10.0, 10.0],
        }]
        self.detections = [{
            "frame_index": 10, "object_class": "person", "confidence": 0.9,
            "box": [0.0, 0.0, 10.0, 10.0],
        }, {
            "frame_index": 10, "object_class": "person", "confidence": 0.8,
            "box": [20.0, 20.0, 30.0, 30.0],
        }]

    def test_rider_inside_vehicle_uses_config_and_counts_only_unmatched_people(self) -> None:
        config_path = Path(__file__).parents[1] / "configs/evaluation_detection_v2.yaml"
        config = load_evaluation_config(config_path)
        rule = config["matching"]["rider_inside_vehicle"]
        self.assertEqual(rule["evidence"], "C")
        self.assertEqual(rule["containment_threshold"], 0.5)
        detections = [
            {"frame_index": 10, "object_class": "person", "box": [0, 0, 10, 10]},
            {"frame_index": 10, "object_class": "person", "box": [0, 0, 10, 10]},
            {"frame_index": 10, "object_class": "car", "box": [0, 0, 10, 10]},
        ]
        vehicles = [{
            "frame_index": 10, "object_class": "motorcycle", "box": [0, 0, 6, 10],
        }]
        counts = rider_inside_vehicle_sensitivity(
            detections, {1}, vehicles, config,
        )
        self.assertEqual(counts, {0.3: 1, 0.5: 1, 0.7: 0})

    def test_operating_point_precision_recall_and_complete_frames(self) -> None:
        scores = detection_metrics(
            self.gt, self.detections, {10}, 0.85, 0.5,
        )
        self.assertEqual(scores["person"]["tp"], 1)
        self.assertEqual(scores["person"]["fp"], 0)
        self.assertEqual(scores["person"]["recall"], 1.0)
        scores = detection_metrics(self.gt, self.detections, {11}, 0.01, 0.5)
        self.assertEqual(scores["person"]["tp"], 0)
        self.assertEqual(scores["person"]["fp"], 0)

    def test_average_precision_matches_hand_calculation(self) -> None:
        gt = [
            {"frame_index": 10, "object_class": "person", "box": [0, 0, 10, 10]},
            {"frame_index": 10, "object_class": "person", "box": [20, 0, 30, 10]},
        ]
        detections = [
            {"frame_index": 10, "object_class": "person", "confidence": 0.9,
             "box": [0, 0, 10, 10]},
            {"frame_index": 10, "object_class": "person", "confidence": 0.8,
             "box": [40, 0, 50, 10]},
            {"frame_index": 10, "object_class": "person", "confidence": 0.7,
             "box": [20, 0, 30, 10]},
        ]
        ap = average_precision(gt, detections, 0.5, "person", max_detections=5000)
        self.assertAlmostEqual(ap, 0.8350, places=4)

    def test_coco_ap_keeps_more_than_one_hundred_frame_detections(self) -> None:
        gt = [{"frame_index": 10, "object_class": "person", "box": [0, 0, 10, 10]}]
        detections = [
            {"frame_index": 10, "object_class": "person", "confidence": 1 - i / 200,
             "box": [20 + 12 * i, 20, 30 + 12 * i, 30]}
            for i in range(100)
        ]
        detections.append({
            "frame_index": 10, "object_class": "person", "confidence": 0.1,
            "box": [0, 0, 10, 10],
        })
        ap = average_precision(gt, detections, 0.5, "person", max_detections=5000)
        self.assertGreater(ap, 0.0)
        self.assertLess(ap, 0.02)

    def test_class_compatibility_accepts_car_alias(self) -> None:
        gt = [{"frame_index": 1, "object_class": "car", "box": [0, 0, 2, 2]}]
        det = [{"frame_index": 1, "object_class": "truck", "confidence": 0.9,
                "box": [0, 0, 2, 2]}]
        self.assertEqual(detection_metrics(gt, det, {1}, 0.15, 0.5)["car"]["tp"], 1)

    def test_ignore_overlap_does_not_count_as_false_positive(self) -> None:
        det = [{"frame_index": 10, "object_class": "person", "confidence": 0.9,
                "box": [20.0, 20.0, 30.0, 30.0]}]
        scores = detection_metrics(
            self.gt, det, {10}, 0.15, 0.5,
            ignore_ground_truth=[{
                "frame_index": 10, "object_class": "person", "iscrowd": 1,
                "box": [20, 20, 30, 30],
            }],
        )
        self.assertEqual(scores["person"]["fp"], 0)
        self.assertEqual(scores["person"]["ignored_detections"], 1)
        ap = average_precision(
            self.gt, det, 0.5, "person", max_detections=5000,
            ignore_ground_truth=[{
                "frame_index": 10, "object_class": "person", "iscrowd": 1,
                "box": [20, 20, 30, 30],
            }],
        )
        self.assertAlmostEqual(ap, 0.0)

    def test_ignore_ground_truth_is_interpolated_and_marked_crowd(self) -> None:
        observations = [
            {"gt_object_id": "P1", "frame_index": 0, "object_class": "person",
             "observation_method": "manual", "x1": 0, "y1": 0, "x2": 10, "y2": 10},
            {"gt_object_id": "P1", "frame_index": 20, "object_class": "person",
             "observation_method": "manual", "x1": 20, "y1": 0, "x2": 30, "y2": 10},
        ]
        visibility = [{
            "gt_object_id": "P1", "start_frame_index": 10,
            "end_frame_index": 10, "visibility_status": "fully_occluded",
            "in_scope": "true",
        }]
        objects = [{"gt_object_id": "P1", "object_class": "person"}]
        ignores, unresolved = build_ignore_ground_truth(
            observations, objects, visibility, [], {10}
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(ignores[0]["box"], [10.0, 0.0, 20.0, 10.0])
        self.assertEqual(ignores[0]["iscrowd"], 1)

    def test_tile_inclusion_is_reported(self) -> None:
        slices = [(0, 0, 10, 10), (8, 0, 18, 10)]
        self.assertEqual(detection_tile_ids([7, 2, 11, 6], slices), [1, 2])

    def test_complete_frames_reuse_object_track_definition(self) -> None:
        visibility = [{
            "gt_object_id": "P1", "start_frame_index": "10",
            "end_frame_index": "20", "in_scope": "true",
            "denominator_eligible": "true",
        }]
        observations = [{"gt_object_id": "P1", "frame_index": "10"}]
        self.assertEqual(complete_detection_frames([10, 20], visibility, observations), [10])

    def test_detection_frames_union_grid_and_all_gt_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gt_observations.csv"
            path.write_text(
                "frame_index\n10\n12\n12\n28\n", encoding="utf-8"
            )
            self.assertEqual(detection_frame_indices(path, 10, 30, 10, 10, 3), [10, 12, 20, 28, 30])

    def test_yaml_inference_mismatch_stops_evaluation(self) -> None:
        config = {
            "inference": {
                "model": "YOLO11m", "weights": "models/yolo11m.pt",
                "class_profile": "coco", "slice_width": 1024,
                "slice_height": 1024, "slice_overlap": 0.2,
                "image_size": 1024, "nms_iou": 0.5, "pass_id": "A",
            },
            "ground_truth": {"confidence_floor": 0.01},
            "frames": {"max_detections_per_tile": 300},
        }
        meta = {
            "detector_settings": {
                **config["inference"], "max_det_per_tile": 300,
            },
            "confidence_threshold": 0.01,
        }
        validate_inference_metadata(config, meta)
        meta["detector_settings"]["slice_width"] = 768
        with self.assertRaises(DetectionEvaluationError):
            validate_inference_metadata(config, meta)

    def test_artifact_loader_checks_meta_before_reading_csv(self) -> None:
        config = {
            "inference": {
                "model": "YOLO11m", "weights": "models/yolo11m.pt",
                "class_profile": "coco", "slice_width": 1024,
                "slice_height": 1024, "slice_overlap": 0.2,
                "image_size": 1024, "nms_iou": 0.5, "pass_id": "A",
            },
            "ground_truth": {"confidence_floor": 0.01},
            "frames": {"max_detections_per_tile": 300},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            yaml_path = root / "evaluation.yaml"
            meta_path = root / "detections.csv.meta.json"
            csv_path = root / "detections.csv"
            yaml_path.write_text(json.dumps(config), encoding="utf-8")
            meta_path.write_text(json.dumps({
                "detector_settings": {
                    **config["inference"], "slice_width": 768,
                    "max_det_per_tile": 300,
                },
                "confidence_threshold": 0.01,
            }), encoding="utf-8")
            with self.assertRaises(DetectionEvaluationError):
                load_validated_detection_artifact(yaml_path, csv_path, meta_path)

    def test_configured_ap_uses_yaml_max_dets(self) -> None:
        config = {"matching": {"coco": {"max_detections": 5000}}}
        ap = configured_average_precision(
            config, self.gt, self.detections, 0.5, "person",
        )
        self.assertAlmostEqual(ap, 1.0)

    def test_tracker_loss_decomposition_uses_compatible_class_match(self) -> None:
        gt = [{"frame_index": 10, "gt_object_id": "C1", "object_class": "car",
               "box": [0, 0, 10, 10]}]
        det = [{"frame_index": 10, "object_class": "truck", "confidence": 0.3,
                "box": [0, 0, 10, 10]}]
        tracks = [{"frame_index": 10, "object_class": "car", "confidence": 0.3,
                   "box": [0, 0, 10, 10]}]
        rows = decompose_tracker_loss(gt, det, tracks, {10}, 0.15, 0.25, 0.5)
        self.assertEqual(rows[0]["category"], "④_tracker_match")

    def test_tracker_match_without_detection_match_is_reproducibility_anomaly(self) -> None:
        gt = [{"frame_index": 10, "gt_object_id": "C1", "object_class": "car",
               "box": [0, 0, 10, 10]}]
        detections = [{"frame_index": 10, "object_class": "car", "confidence": 0.3,
                       "box": [20, 20, 30, 30]}]
        tracks = [{"frame_index": 10, "object_class": "car", "confidence": 0.3,
                   "box": [0, 0, 10, 10]}]
        rows = decompose_tracker_loss(gt, detections, tracks, {10}, 0.15, 0.25, 0.5)
        self.assertEqual(
            rows[0]["category"],
            "reproducibility_anomaly_tracker_without_conf_ge_0_15_match",
        )


if __name__ == "__main__":
    unittest.main()
