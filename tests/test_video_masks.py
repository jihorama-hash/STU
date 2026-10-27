import unittest

import numpy as np

from roundabout.video_masks import (
    reference_to_source_matrix,
    source_to_source_matrix,
    warp_binary_mask,
)


class VideoMasksTest(unittest.TestCase):
    def test_identity_reference_transform(self):
        identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        np.testing.assert_allclose(reference_to_source_matrix(identity), np.eye(3))

    def test_source_to_source_composition(self):
        origin = [[1, 0, 10], [0, 1, 5], [0, 0, 1]]
        target = [[1, 0, 3], [0, 1, 2], [0, 0, 1]]
        expected = [[1, 0, 7], [0, 1, 3], [0, 0, 1]]
        np.testing.assert_allclose(
            source_to_source_matrix(origin, target), expected
        )

    def test_binary_mask_stays_binary(self):
        mask = np.zeros((8, 8), dtype=np.uint8)
        mask[2:4, 2:4] = 255
        warped = warp_binary_mask(mask, np.eye(3))
        self.assertEqual(set(np.unique(warped)), {0, 255})
        np.testing.assert_array_equal(warped, mask)


if __name__ == "__main__":
    unittest.main()
