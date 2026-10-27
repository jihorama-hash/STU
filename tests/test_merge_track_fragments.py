import unittest

from roundabout.merge_track_fragments import continuation_score, merge_fragments


def row(track_id: int, timestamp: float, x: float, y: float, object_class: str = "car"):
    return {
        "video_id": "test",
        "frame_index": str(round(timestamp * 10)),
        "timestamp_seconds": str(timestamp),
        "track_id": str(track_id),
        "object_class": object_class,
        "foot_x": str(x),
        "foot_y": str(y),
        "x1": str(x - 5),
        "y1": str(y - 10),
        "x2": str(x + 5),
        "y2": str(y),
    }


THRESHOLDS = {
    "maximum_gap_seconds": 0.75,
    "maximum_prediction_error_pixels": 20.0,
    "maximum_direction_change_degrees": 35.0,
    "maximum_speed_ratio": 2.0,
    "maximum_size_ratio": 2.0,
    "maximum_overlap_seconds": 0.75,
    "maximum_duplicate_distance_pixels": 40.0,
}


class MergeTrackFragmentsTest(unittest.TestCase):
    def test_accepts_motion_consistent_continuation(self):
        first = [row(1, 0.0, 0, 0), row(1, 0.5, 5, 0)]
        second = [row(2, 1.0, 10, 0), row(2, 1.5, 15, 0)]
        self.assertIsNotNone(continuation_score(first, second, **THRESHOLDS))

    def test_rejects_opposite_direction(self):
        first = [row(1, 0.0, 0, 0), row(1, 0.5, 5, 0)]
        second = [row(2, 1.0, 10, 0), row(2, 1.5, 5, 0)]
        self.assertIsNone(continuation_score(first, second, **THRESHOLDS))

    def test_preserves_original_id_and_uses_chain_root(self):
        rows = [
            row(1, 0.0, 0, 0), row(1, 0.5, 5, 0),
            row(2, 1.0, 10, 0), row(2, 1.5, 15, 0),
        ]
        merged, links = merge_fragments(rows, **THRESHOLDS)
        self.assertEqual({item["track_id"] for item in merged}, {"1"})
        self.assertEqual({item["original_track_id"] for item in merged}, {"1", "2"})
        self.assertEqual(len(links), 1)

    def test_merges_short_spatially_matching_overlap(self):
        first = [
            row(1, 0.0, 0, 0), row(1, 0.5, 5, 0), row(1, 1.0, 10, 0),
        ]
        second = [
            row(2, 0.5, 6, 1), row(2, 1.0, 11, 1), row(2, 1.5, 16, 1),
        ]
        merged, links = merge_fragments(first + second, **THRESHOLDS)
        self.assertEqual({item["track_id"] for item in merged}, {"1"})
        self.assertEqual(len(merged), 4)
        self.assertEqual(links[0]["shared_frames"], 2)

    def test_rejects_overlapping_distinct_objects(self):
        first = [
            row(1, 0.0, 0, 0), row(1, 0.5, 5, 0), row(1, 1.0, 10, 0),
        ]
        second = [
            row(2, 0.5, 60, 0), row(2, 1.0, 65, 0), row(2, 1.5, 70, 0),
        ]
        self.assertIsNone(continuation_score(first, second, **THRESHOLDS))


if __name__ == "__main__":
    unittest.main()
