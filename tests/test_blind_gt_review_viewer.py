from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "blind_gt_review_viewer.py"
SPEC = importlib.util.spec_from_file_location("blind_gt_review_viewer", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
VIEWER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VIEWER
SPEC.loader.exec_module(VIEWER)


class BlindGtReviewViewerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = VIEWER.EvaluationGrid()

    def test_canonical_evaluation_grid(self) -> None:
        self.assertEqual(self.grid.frame_count, 900)
        self.assertTrue(self.grid.contains(4196))
        self.assertTrue(self.grid.contains(5994))
        self.assertFalse(self.grid.contains(4197))
        self.assertFalse(self.grid.contains(5996))
        self.assertAlmostEqual(self.grid.evaluation_fps, 15000 / 1001)

    def test_empty_working_sheets_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = root / "objects.csv"
            visibility = root / "visibility.csv"
            self._write_rows(objects, VIEWER.OBJECT_HEADERS, [])
            self._write_rows(visibility, VIEWER.VISIBILITY_HEADERS, [])

            warnings = VIEWER.validate_worksheets(objects, visibility, self.grid)

            self.assertEqual(warnings, [])

    def test_odd_frame_warns_without_modifying_worksheet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = root / "objects.csv"
            visibility = root / "visibility.csv"
            self._write_rows(
                objects,
                VIEWER.OBJECT_HEADERS,
                [["P001", "person", "4197", "4200", "true", "", ""]],
            )
            self._write_rows(visibility, VIEWER.VISIBILITY_HEADERS, [])
            before = objects.read_bytes()

            warnings = VIEWER.validate_worksheets(objects, visibility, self.grid)

            self.assertTrue(any("4197 is outside evaluation grid" in item for item in warnings))
            self.assertEqual(objects.read_bytes(), before)

    def test_visibility_status_and_grid_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = root / "objects.csv"
            visibility = root / "visibility.csv"
            self._write_rows(
                objects,
                VIEWER.OBJECT_HEADERS,
                [["C001", "car", "4196", "4300", "true", "", ""]],
            )
            self._write_rows(
                visibility,
                VIEWER.VISIBILITY_HEADERS,
                [["C001", "4196", "4299", "unclear", "", ""]],
            )

            warnings = VIEWER.validate_worksheets(objects, visibility, self.grid)

            self.assertTrue(any("4299 is outside evaluation grid" in item for item in warnings))
            self.assertTrue(any("unsupported 'unclear'" in item for item in warnings))

    def test_non_utf8_worksheet_reports_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = root / "objects.csv"
            visibility = root / "visibility.csv"
            objects.write_bytes(b"gt_object_id,notes\nP001,\xc7\xd1\xb1\xdb\n")
            self._write_rows(visibility, VIEWER.VISIBILITY_HEADERS, [])

            warnings = VIEWER.validate_worksheets(objects, visibility, self.grid)

            self.assertTrue(any("not valid UTF-8 CSV" in item for item in warnings))

    def test_frame_reader_serializes_decoder_access(self) -> None:
        reader = VIEWER.FrameReader.__new__(VIEWER.FrameReader)
        reader.lock = threading.RLock()
        state_lock = threading.Lock()
        active = 0
        maximum_active = 0

        def fake_read(frame_index: int) -> int:
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.01)
            with state_lock:
                active -= 1
            return frame_index

        reader._read_unlocked = fake_read
        threads = [threading.Thread(target=reader.read, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(maximum_active, 1)

    @staticmethod
    def _write_rows(path: Path, headers: tuple[str, ...], rows: list[list[str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
