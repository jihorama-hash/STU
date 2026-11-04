from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roundabout.detect_frames import run_detection_frames, write_output_metadata


class DetectFramesTests(unittest.TestCase):
    def test_writes_meta_sidecar_with_output_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "detections.csv"
            output.write_text("frame_index\n1\n", encoding="utf-8")
            sidecar = write_output_metadata(output, {
                "generated_at_utc": "2026-11-04T00:00:00+00:00",
                "device": "cuda:0",
                "gpu_name": "test GPU",
                "frames": {"indices": [1], "count": 1},
                "coordinate_system": "source_pixel",
                "unit": "px",
                "review_status": "draft",
            })
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(sidecar.name, "detections.csv.meta.json")
            self.assertEqual(metadata["device"], "cuda:0")
            self.assertEqual(metadata["artifact_path"], output.as_posix())
            self.assertEqual(len(metadata["artifact_sha256"]), 64)

    @patch("roundabout.detect_frames.torch.cuda.is_available", return_value=False)
    def test_cuda_unavailable_fails_unless_cpu_is_explicit(self, _cuda_available) -> None:
        with self.assertRaisesRegex(RuntimeError, "Pass --allow-cpu"):
            run_detection_frames(
                Path("missing.mp4"), Path("out.csv"), Path("config.json"), [0]
            )


if __name__ == "__main__":
    unittest.main()
