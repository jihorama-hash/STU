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

    def test_stationary_repeated_boxes_derive_default_foot_from_stored_box(self) -> None:
        state = self._state()
        fractional_box = {"x1": 48.06, "y1": 245.1, "x2": 150.2, "y2": 291.78}
        stale_client_foot = {"x": 99.06, "y": 291.78}
        first = state.save_observation(
            "P001", 4196, fractional_box, foot=stale_client_foot
        )
        second = state.save_observation(
            "P001", 4200, fractional_box, foot=stale_client_foot
        )

        for row in (first, second):
            self.assertEqual((row["x1"], row["y1"], row["x2"], row["y2"]),
                             ("48", "245", "150", "292"))
            self.assertEqual(row["foot_x"], "99.0")
            self.assertEqual(row["foot_y"], "292.0")
        state.validate_work()

    def test_copy_after_save_recomputes_default_foot_and_records_copy(self) -> None:
        state = self._state()
        previous = state.save_observation(
            "P001",
            4196,
            {"x1": 10, "y1": 20, "x2": 30, "y2": 60},
        )
        copied = state.save_observation(
            "P001",
            4200,
            {"x1": 11.2, "y1": 21.1, "x2": 31.2, "y2": 61.4},
            foot={"x": float(previous["foot_x"]), "y": float(previous["foot_y"])},
            copied_from_previous=True,
        )

        self.assertEqual(copied["foot_x"], "21.0")
        self.assertEqual(copied["foot_y"], "61.0")
        self.assertIn("copied_from_previous", copied["notes"])
        self.assertNotIn("foot_adjusted", copied["notes"])
        state.validate_work()

    def test_moving_box_recomputes_default_foot_instead_of_reusing_old_point(self) -> None:
        state = self._state()
        previous = state.save_observation(
            "P001", 4196, {"x1": 10, "y1": 20, "x2": 30, "y2": 60}
        )
        moved = state.save_observation(
            "P001",
            4200,
            {"x1": 20.2, "y1": 35.4, "x2": 42.2, "y2": 78.4},
            foot={"x": float(previous["foot_x"]), "y": float(previous["foot_y"])},
        )

        self.assertEqual(moved["foot_x"], "31.0")
        self.assertEqual(moved["foot_y"], "78.0")
        self.assertIn("else foot=defaultFoot(box)", annotation.PAGE_HTML)
        state.validate_work()

    def test_zoom_scale_boundary_points_are_safe_after_box_rounding(self) -> None:
        state = self._state()
        for frame, zoom in zip((4196, 4200, 4202, 4226), (1, 3, 12, 30)):
            crop = {
                "left": 0,
                "top": 0,
                "width": round(3840 / zoom),
                "height": round(2160 / zoom),
            }
            canvas_width, canvas_height = 1280.0, 720.0
            first = annotation.canvas_to_source(
                50.4 * canvas_width / crop["width"],
                240.4 * canvas_height / crop["height"],
                canvas_width,
                canvas_height,
                crop,
            )
            last = annotation.canvas_to_source(
                150.3 * canvas_width / crop["width"],
                291.4 * canvas_height / crop["height"],
                canvas_width,
                canvas_height,
                crop,
            )
            row = state.save_observation(
                "P001",
                frame,
                {"x1": first[0], "y1": first[1], "x2": last[0], "y2": last[1]},
            )
            self.assertEqual(row["foot_y"], row["y2"] + ".0")
        state.validate_work()

    def test_f_adjusted_foot_point_remains_strict(self) -> None:
        with self.assertRaisesRegex(annotation.AnnotationError, "foot point must lie inside"):
            self._state().save_observation(
                "P001",
                4196,
                {"x1": 10, "y1": 20, "x2": 30, "y2": 60},
                foot={"x": 31, "y": 60},
                foot_adjusted=True,
            )

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

    def test_size_outliers_lists_rows_at_least_forty_percent_above_object_median(self) -> None:
        state = self._state()
        for frame, width in ((4196, 10), (4200, 10), (4202, 14)):
            state.save_observation(
                "P001",
                frame,
                {"x1": 10, "y1": 20, "x2": 10 + width, "y2": 40},
            )

        report = annotation.format_size_outliers(self._state())

        self.assertIn("size outliers: 1행", report)
        self.assertIn("P001 (person) frame 4202", report)
        self.assertIn("14x20 px; median 10x20 px; 폭 1.40x", report)

    def test_v_shortcut_copies_recomputes_saves_once_and_advances(self) -> None:
        html = annotation.PAGE_HTML
        self.assertIn('id="copySaveNext"', html)
        self.assertIn("function previousObservation()", html)
        self.assertIn("function setCopiedBox(prev)", html)
        self.assertIn("foot=defaultFoot(box);footAdjusted=false;copied=true", html)
        self.assertIn("async function copyPreviousSaveNext()", html)
        self.assertIn("await saveAndAdvance()", html)
        self.assertIn('e.key.toLowerCase()==="v")copyPreviousSaveNext()', html)

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
                foot_adjusted=True,
            )

    def test_foot_validation_allows_one_pixel_rounding_only_for_default(self) -> None:
        state = self._state()
        row = state.save_observation(
            "P001", 4196, {"x1": 10, "y1": 20, "x2": 30, "y2": 60}
        )
        row["foot_x"] = "30.75"
        state.observations = [row]
        state.validate_work()

        row["notes"] = "foot_adjusted"
        with self.assertRaisesRegex(annotation.AnnotationError, "foot point must lie inside"):
            state.validate_work()

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
        self.assertIn('id="copySaveNext"', annotation.PAGE_HTML)
        self.assertIn("C 복사 후 조정", annotation.PAGE_HTML)


if __name__ == "__main__":
    unittest.main()
