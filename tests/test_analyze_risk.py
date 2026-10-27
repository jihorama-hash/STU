import unittest

from roundabout.analyze_risk import (
    crossing_angle_for_pair,
    point_in_polygon,
    transform_point,
)


class AnalyzeRiskTest(unittest.TestCase):
    def test_point_in_polygon(self) -> None:
        polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
        self.assertTrue(point_in_polygon(5, 5, polygon))
        self.assertFalse(point_in_polygon(15, 5, polygon))

    def test_identity_homography(self) -> None:
        matrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.assertEqual(transform_point(matrix, 12.5, 7.5), (12.5, 7.5))

    def test_crossing_angle(self) -> None:
        tracks = {
            1: [
                {"timestamp": 0.0, "x": 0.0, "y": 0.0},
                {"timestamp": 1.0, "x": 1.0, "y": 0.0},
            ],
            2: [
                {"timestamp": 0.0, "x": 0.0, "y": 0.0},
                {"timestamp": 1.0, "x": 0.0, "y": 1.0},
            ],
        }
        first = {"track_id": 1}
        second = {"track_id": 2, "entry_seconds": 1.0}
        self.assertAlmostEqual(
            crossing_angle_for_pair(tracks, first, second), 90.0
        )
