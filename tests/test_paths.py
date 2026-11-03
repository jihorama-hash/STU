import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roundabout.paths import display_project_path
from roundabout.run_batch import _project_path, _relative


class ProjectPathTest(unittest.TestCase):
    def test_symlink_path_keeps_project_relative_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project"
            external = base / "external"
            (project / "data").mkdir(parents=True)
            (external / "before").mkdir(parents=True)
            (external / "before" / "clip.mp4").touch()
            (project / "data" / "raw").symlink_to(external, target_is_directory=True)

            with patch.dict(os.environ, {"ROUNDABOUT_PROJECT_ROOT": str(project)}):
                self.assertEqual(
                    display_project_path("data/raw/before/clip.mp4"),
                    "data/raw/before/clip.mp4",
                )
                resolved_lexically = _project_path(
                    project, "data/raw/before/clip.mp4"
                )
                self.assertEqual(
                    _relative(project, resolved_lexically),
                    "data/raw/before/clip.mp4",
                )
                self.assertEqual(
                    display_project_path(external / "before" / "clip.mp4"),
                    str(external / "before" / "clip.mp4"),
                )


if __name__ == "__main__":
    unittest.main()
