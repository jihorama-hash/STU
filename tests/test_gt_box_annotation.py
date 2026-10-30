from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))
APP_PATH = REPOSITORY_ROOT / "apps/demo/gt_box_annotation.py"
SPEC = importlib.util.spec_from_file_location("gt_box_annotation", APP_PATH)
assert SPEC is not None and SPEC.loader is not None
annotation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = annotation
SPEC.loader.exec_module(annotation)


class GtBoxAnnotationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.manifest_path = self.root / "manifest.json"
        self.objects_path = self.root / "objects.csv"
        self.visibility_path = self.root / "visibility.csv"
        self.observations_path = self.root / "observations.csv"
        self.skips_path = self.root / "skips.csv"
        self.manifest = {
            "schema_version": "object_track_gt_v1",
            "gt_dataset_id": "pilot_v1",
            "pilot": {
                "evaluation_start_frame_index": 4196,
                "evaluation_end_frame_index": 5994,
            },
            "video": {
                "video_id": "DJI_0482",
                "source_fps": 30000 / 1001,
                "source_frame_count": 8721,
            },
            "sampling": {"frame_step": 2},
            "files": {
                "objects": "gt_objects.csv",
                "visibility_intervals": "gt_visibility_intervals.csv",
            },
        }
        self.objects = [
            {
                "schema_version": "object_track_gt_v1",
                "gt_dataset_id": "pilot_v1",
                "video_id": "DJI_0482",
                "gt_object_id": "P001",
                "object_class": "person",
                "first_visible_frame_index": "4196",
                "last_visible_frame_index": "4256",
                "in_scope": "true",
                "notes": "",
            }
        ]
        self.visibility = [
            self._visibility("4196", "4200", "visible", ""),
            self._visibility("4202", "4232", "partially_occluded", "vegetation"),
            self._visibility("4234", "4236", "fully_occluded", "structure"),
            self._visibility("4238", "4256", "visible", ""),
        ]
        self._write_rows(self.objects_path, annotation.OBJECT_HEADERS, self.objects)
        self._write_rows(self.visibility_path, annotation.VISIBILITY_HEADERS, self.visibility)
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _visibility(
        self, start: str, end: str, status: str, reason: str
    ) -> dict[str, str]:
        eligible = status in annotation.VISIBILITY_STATUSES
        return {
            "schema_version": "object_track_gt_v1",
            "gt_dataset_id": "pilot_v1",
            "video_id": "DJI_0482",
            "gt_object_id": "P001",
            "visibility_interval_id": f"P001_VI{start}",
            "start_frame_index": start,
            "end_frame_index": end,
            "visibility_status": status,
            "in_scope": "true",
            "denominator_eligible": str(eligible).lower(),
            "occlusion_reason": reason,
        }

    @staticmethod
    def _write_rows(
        path: Path, headers: tuple[str, ...], rows: list[dict[str, str]]
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def _state(self) -> annotation.AnnotationState:
        return annotation.AnnotationState.from_paths(
            self.manifest_path,
            self.objects_path,
            self.visibility_path,
            self.observations_path,
            self.skips_path,
        )

    def test_anchor_calculation_includes_endpoints_and_thirty_frame_steps(self) -> None:
        anchors = annotation.calculate_anchors(
            self.objects, self.visibility, annotation.EvaluationGrid()
        )["P001"]
        frames = [int(row["frame_index"]) for row in anchors]

        self.assertEqual(frames, [4196, 4200, 4202, 4226, 4232, 4238, 4256])
        self.assertNotIn(4234, frames)
        self.assertNotIn(4236, frames)

    def test_zoom_crop_and_pointer_coordinates_map_to_source_pixels(self) -> None:
        crop = annotation.calculate_crop(500, 400, 3)
        self.assertEqual(crop, {"left": 0, "top": 40, "width": 1280, "height": 720})
        source = annotation.canvas_to_source(500, 250, 1000, 500, crop)
        self.assertEqual(source, (640, 400))

    def test_zoom_center_uses_last_two_same_object_gt_boxes(self) -> None:
        rows = [
            {"frame_index": "4196", "x1": "10", "x2": "30", "y1": "20", "y2": "40"},
            {"frame_index": "4226", "x1": "20", "x2": "40", "y1": "30", "y2": "50"},
        ]
        self.assertEqual(annotation.predict_zoom_center(rows, 4256), (40, 50))

    def test_save_resume_and_copy_note(self) -> None:
        state = self._state()
        row = state.save_observation(
            "P001",
            4196,
            {"x1": 10, "y1": 20, "x2": 30, "y2": 60},
        )
        self.assertEqual(row["foot_x"], "20.0")
        self.assertEqual(row["foot_y"], "60.0")
        self.assertEqual(row["notes"], "")
        state.save_observation(
            "P001",
            4200,
            {"x1": 10, "y1": 20, "x2": 30, "y2": 60},
            copied_from_previous=True,
            foot={"x": 19, "y": 58},
            foot_adjusted=True,
        )
        resumed = self._state()
        self.assertEqual(resumed.summary()["observations"], 2)
        self.assertEqual(resumed.summary()["missing"], 5)
        second = resumed.current_observation("P001", 4200)
        self.assertIsNotNone(second)
        self.assertIn("copied_from_previous", second["notes"])
        self.assertIn("foot_adjusted", second["notes"])

    def test_skip_is_persisted_and_counts_as_resolved(self) -> None:
        state = self._state()
        state.save_skip("P001", 4196, "not_found", "not visible")
        resumed = self._state()
        self.assertEqual(resumed.summary()["skips"], 1)
        self.assertEqual(resumed.summary()["missing"], 6)
        self.assertEqual(resumed.current_skip("P001", 4196)["reason"], "not_found")

    def test_skip_summary_groups_frames_by_object_and_reason(self) -> None:
        state = self._state()
        state.save_skip("P001", 4238, "not_found", "off screen")
        state.save_skip(
            "P001", 4256, "occluded_more_than_marked", "fully obscured"
        )

        summary = annotation.format_skip_summary(self._state())

        self.assertIn("skip summary: 2행, 1개 객체", summary)
        self.assertIn("P001 (person): 2행", summary)
        self.assertIn("not_found (1): 4238", summary)
        self.assertIn("occluded_more_than_marked (1): 4256", summary)

    def test_state_payload_includes_resume_progress_and_user_gt_overlays(self) -> None:
        state = self._state()
        state.save_observation(
            "P001", 4196, {"x1": 10, "y1": 20, "x2": 30, "y2": 60}
        )
        payload = annotation.state_payload(state, "P001", 4200)
        self.assertEqual(payload["frameCount"], 8721)
        self.assertEqual(payload["summary"]["observations"], 1)
        self.assertIn("4196", payload["sameFrame"])
        self.assertEqual(payload["predictedCenter"]["4200"], (20.0, 40.0))

    def test_invalid_box_is_rejected(self) -> None:
        with self.assertRaisesRegex(annotation.AnnotationError, "positive size"):
            self._state().save_observation(
                "P001", 4196, {"x1": 10, "y1": 10, "x2": 10, "y2": 20}
            )

    def test_foot_point_outside_box_is_rejected(self) -> None:
        with self.assertRaisesRegex(annotation.AnnotationError, "foot point must lie inside"):
            self._state().save_observation(
                "P001",
                4196,
                {"x1": 10, "y1": 20, "x2": 30, "y2": 60},
                foot={"x": 31, "y": 60},
            )

    def test_validate_work_rejects_class_mismatch_duplicate_and_occluded_frame(self) -> None:
        state = self._state()
        row = state.save_observation(
            "P001", 4196, {"x1": 10, "y1": 20, "x2": 30, "y2": 60}
        )
        row["object_class"] = "car"
        state.observations.append(dict(row))
        with self.assertRaisesRegex(annotation.AnnotationError, "object_class|duplicate"):
            state.validate_work()

        state.observations = [
            {
                **row,
                "object_class": "person",
                "frame_index": "4234",
                "visibility_status": "fully_occluded",
            }
        ]
        with self.assertRaisesRegex(annotation.AnnotationError, "denominator-eligible"):
            state.validate_work()

    def test_page_and_code_do_not_reference_automatic_results(self) -> None:
        source = Path(annotation.__file__).read_text(encoding="utf-8")
        for forbidden in ("outputs/", "tracks.csv", "YOLO", "ByteTrack", "confidence"):
            self.assertNotIn(forbidden, source)
        self.assertIn("같은 프레임 다른 객체 박스", annotation.PAGE_HTML)
        self.assertIn("copied_from_previous", annotation.PAGE_HTML)
        self.assertIn('id="fullScreen"', annotation.PAGE_HTML)
        self.assertIn("width:100vw;height:100vh;max-width:none", annotation.PAGE_HTML)
        self.assertIn('detail.addEventListener("wheel"', annotation.PAGE_HTML)
        self.assertIn("Math.min(30,zoom*factor)", annotation.PAGE_HTML)
        self.assertIn("발점은 박스 안에서 클릭하세요", annotation.PAGE_HTML)
        self.assertIn('mode:"move"', annotation.PAGE_HTML)
        self.assertIn("drag.originalFoot.x+actualX", annotation.PAGE_HTML)
        self.assertIn('detail.style.cursor=box&&', annotation.PAGE_HTML)


if __name__ == "__main__":
    unittest.main()
