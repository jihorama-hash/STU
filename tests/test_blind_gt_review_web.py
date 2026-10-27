from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


APP_PATH = Path(__file__).parents[1] / "apps" / "demo" / "blind_gt_review.py"
SPEC = importlib.util.spec_from_file_location("blind_gt_review_web", APP_PATH)
assert SPEC is not None and SPEC.loader is not None
WEB = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = WEB
SPEC.loader.exec_module(WEB)


class BlindGtReviewWebTest(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = WEB.EvaluationGrid()

    def test_frame_request_accepts_canonical_grid_frame(self) -> None:
        self.assertEqual(
            WEB.parse_frame_request("/api/frame/4196?quality=play", self.grid),
            (4196, "play"),
        )

    def test_frame_request_rejects_odd_frame(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside evaluation grid"):
            WEB.parse_frame_request("/api/frame/4197?quality=full", self.grid)

    def test_frame_request_rejects_unknown_quality(self) -> None:
        with self.assertRaisesRegex(ValueError, "quality must be play or full"):
            WEB.parse_frame_request("/api/frame/4196?quality=proxy", self.grid)

    def test_page_keeps_reset_separate_from_play_pause(self) -> None:
        self.assertIn('id="playPause"', WEB.PAGE_HTML)
        self.assertIn('id="goStart"', WEB.PAGE_HTML)
        self.assertIn("일시정지 후 재생하면 현재 프레임 다음부터 이어집니다", WEB.PAGE_HTML)

    def test_default_inputs_do_not_depend_on_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "pathlib.Path.cwd", return_value=Path(temp_dir)
        ):
            self.assertTrue(WEB.DEFAULT_VIDEO.is_absolute())
            self.assertTrue(WEB.DEFAULT_OBJECTS_WORKSHEET.is_absolute())
            self.assertTrue(WEB.DEFAULT_VISIBILITY_WORKSHEET.is_absolute())

    def test_open_browser_is_opt_in(self) -> None:
        with mock.patch.object(sys, "argv", [str(APP_PATH), "--open-browser"]):
            args = WEB.parse_args()

        self.assertTrue(args.open_browser)


if __name__ == "__main__":
    unittest.main()
