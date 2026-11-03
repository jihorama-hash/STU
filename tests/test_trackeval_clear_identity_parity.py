import unittest

import numpy as np

from roundabout.third_party.clear import CLEAR
from roundabout.third_party.identity import Identity


class TrackEvalClearIdentityParityTest(unittest.TestCase):
    def test_official_clear_and_identity_reference_example(self):
        # Fixed reference values from TrackEval 12c8791b on this same sequence.
        data = {
            "num_timesteps": 3,
            "num_gt_dets": 5,
            "num_tracker_dets": 6,
            "num_gt_ids": 2,
            "num_tracker_ids": 3,
            "gt_ids": [np.array([0, 1]), np.array([0, 1]), np.array([0])],
            "tracker_ids": [np.array([0, 1]), np.array([1, 0]), np.array([0, 2])],
            "similarity_scores": [
                np.array([[0.9, 0.1], [0.1, 0.9]]),
                np.array([[0.8, 0.7], [0.75, 0.1]]),
                np.array([[0.49, 0.8]]),
            ],
        }
        clear = CLEAR({"THRESHOLD": 0.5}).eval_sequence(data)
        identity = Identity({"THRESHOLD": 0.5}).eval_sequence(data)
        self.assertEqual(clear["CLR_TP"], 5)
        self.assertEqual(clear["CLR_FP"], 1)
        self.assertEqual(clear["CLR_FN"], 0)
        self.assertEqual(clear["IDSW"], 1)
        self.assertAlmostEqual(clear["MOTA"], 0.6)
        self.assertEqual(identity["IDTP"], 4)
        self.assertEqual(identity["IDFN"], 1)
        self.assertEqual(identity["IDFP"], 2)
        self.assertAlmostEqual(identity["IDF1"], 8 / 11)


if __name__ == "__main__":
    unittest.main()
