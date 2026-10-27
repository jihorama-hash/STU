from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).parents[1] / "scripts" / "build_blind_gt_windows_bundle.py"
)
SPEC = importlib.util.spec_from_file_location("build_blind_gt_windows_bundle", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
BUNDLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUNDLE)


class BlindGtWindowsBundleTest(unittest.TestCase):
    def test_bundle_contains_only_approved_review_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "bundle"

            copied = BUNDLE.build_bundle(output)

            self.assertIn(
                Path(
                    "data/ground_truth/object_track_v1/review/"
                    "gate3a2_object_inventory_R01.csv"
                ),
                copied,
            )
            self.assertIn(
                Path(
                    "data/ground_truth/object_track_v1/review/"
                    "gate3a2_visibility_R01.csv"
                ),
                copied,
            )
            self.assertFalse((output / "Object_Review.xlsx").exists())
            self.assertFalse(any(output.rglob("*_T.csv")))
            self.assertFalse((output / BUNDLE.SOURCE_VIDEO).exists())
            self.assertTrue(
                (
                    output
                    / BUNDLE.SOURCE_VIDEO.parent
                    / "COPY_DJI_0482_MP4_HERE.txt"
                ).is_file()
            )

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "bundle"
            output.mkdir()

            with self.assertRaises(FileExistsError):
                BUNDLE.build_bundle(output)


if __name__ == "__main__":
    unittest.main()
