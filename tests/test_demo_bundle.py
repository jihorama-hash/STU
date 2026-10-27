import json
import tempfile
import unittest
from pathlib import Path

from roundabout.demo_bundle import load_bundle


class DemoBundleTest(unittest.TestCase):
    def test_valid_bundle_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "videos.json").write_text("[]", encoding="utf-8")
            (root / "events.json").write_text("[]", encoding="utf-8")
            (root / "tracks.csv").write_text("track_id\n", encoding="utf-8")
            (root / "track_summary.json").write_text("{}", encoding="utf-8")
            (root / "roi_summary.json").write_text("[]", encoding="utf-8")
            (root / "risk_summary.json").write_text("{}", encoding="utf-8")
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "bundle_version": "1",
                        "created_at": "2026-07-30T00:00:00Z",
                        "study_phase": "before",
                        "validation_status": "unreviewed",
                        "config": "baseline",
                        "videos": "videos.json",
                        "tracks": "tracks.csv",
                        "track_summary": "track_summary.json",
                        "roi_summary": "roi_summary.json",
                        "risk_summary": "risk_summary.json",
                        "events": "events.json",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_bundle(root).validation_status, "unreviewed")

    def test_missing_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "bundle_version": "1",
                        "created_at": "2026-07-30T00:00:00Z",
                        "study_phase": "before",
                        "validation_status": "unreviewed",
                        "config": "baseline",
                        "videos": "videos.json",
                        "tracks": "tracks.csv",
                        "track_summary": "track_summary.json",
                        "roi_summary": "roi_summary.json",
                        "risk_summary": "risk_summary.json",
                        "events": "events.json",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(FileNotFoundError):
                load_bundle(root)
