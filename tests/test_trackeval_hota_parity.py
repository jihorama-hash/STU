import unittest

import numpy as np
from roundabout.third_party.hota import HOTA


class TrackEvalHotaParityTest(unittest.TestCase):
    def test_small_sample_matches_upstream_master_golden(self):
        """All 19 alpha values match upstream master 12c8791 and the fork."""
        frames = [
            (np.array([0, 1]), np.array([0, 1]), np.array([[0.90, 0.10], [0.10, 0.80]])),
            (np.array([0, 1]), np.array([0, 2]), np.array([[0.70, 0.10], [0.20, 0.55]])),
            (np.array([0]), np.array([0, 1]), np.array([[0.65, 0.10]])),
        ]
        sample = {
            "num_timesteps": 3,
            "num_gt_dets": 5,
            "num_tracker_dets": 6,
            "num_gt_ids": 2,
            "num_tracker_ids": 3,
            "gt_ids": [frame[0] for frame in frames],
            "tracker_ids": [frame[1] for frame in frames],
            "similarity_scores": [frame[2] for frame in frames],
        }
        result = HOTA().eval_sequence(sample)
        expected = {
            "HOTA": [
                0.7993052538854533, 0.7993052538854533, 0.7993052538854533,
                0.7993052538854533, 0.7993052538854533, 0.7993052538854533,
                0.7993052538854533, 0.7993052538854533, 0.7993052538854533,
                0.7993052538854533, 0.7993052538854533, 0.6900655593423543,
                0.6900655593423543, 0.408248290463863, 0.24343224778007383,
                0.24343224778007383, 0.14142135623730953, 0.14142135623730953, 0.0,
            ],
            "DetA": [
                0.8333333333333334, 0.8333333333333334, 0.8333333333333334,
                0.8333333333333334, 0.8333333333333334, 0.8333333333333334,
                0.8333333333333334, 0.8333333333333334, 0.8333333333333334,
                0.8333333333333334, 0.8333333333333334, 0.5714285714285714,
                0.5714285714285714, 0.375, 0.2222222222222222, 0.2222222222222222,
                0.1, 0.1, 0.0,
            ],
            "AssA": [
                0.7666666666666667, 0.7666666666666667, 0.7666666666666667,
                0.7666666666666667, 0.7666666666666667, 0.7666666666666667,
                0.7666666666666667, 0.7666666666666667, 0.7666666666666667,
                0.7666666666666667, 0.7666666666666667, 0.8333333333333334,
                0.8333333333333334, 0.4444444444444444, 0.26666666666666666,
                0.26666666666666666, 0.2, 0.2, 0.0,
            ],
            "LocA": [
                0.72, 0.72, 0.72, 0.72, 0.72, 0.72, 0.72, 0.72, 0.72, 0.72,
                0.72, 0.7625000000000001, 0.7625000000000001, 0.8000000000000002,
                0.8500000000000001, 0.8500000000000001, 0.9, 0.9, 1.0,
            ],
        }
        for metric, expected_values in expected.items():
            self.assertEqual(len(result[metric]), 19)
            np.testing.assert_allclose(result[metric], expected_values, rtol=0, atol=1e-15)


if __name__ == "__main__":
    unittest.main()
