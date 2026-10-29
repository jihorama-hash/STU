from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / "scripts/ground_truth/build_canonical_gt.py"
SPEC = importlib.util.spec_from_file_location("build_canonical_gt", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)
InputValidationError = BUILDER.InputValidationError
build_canonical_rows = BUILDER.build_canonical_rows


def make_manifest() -> dict:
    return {
        "schema_version": "object_track_gt_v1",
        "gt_dataset_id": "pilot_v1",
        "pilot": {
            "evaluation_start_frame_index": 4196,
            "evaluation_end_frame_index": 5994,
        },
        "sampling": {"frame_step": 2},
        "video": {"video_id": "DJI_0482", "source_fps": 30000 / 1001},
        "scope": {"object_classes": ["person", "car"]},
        "annotation": {"reviewers": ["R01"]},
    }


def make_object(**updates: str) -> dict[str, str]:
    row = {
        "gt_object_id": "P001",
        "object_class": "person",
        "first_visible_frame_index": "4196",
        "last_visible_frame_index": "4200",
        "in_scope": "TRUE",
        "exclusion_reason": "",
        "notes": "start note",
    }
    row.update(updates)
    return row


def make_intervals() -> list[dict[str, str]]:
    return [
        {
            "gt_object_id": "P001",
            "start_frame_index": "4196",
            "end_frame_index": "4198",
            "visibility_status": "visible",
            "occlusion_reason": "",
            "notes": "visible note",
        },
        {
            "gt_object_id": "P001",
            "start_frame_index": "4200",
            "end_frame_index": "4200",
            "visibility_status": "fully_occluded",
            "occlusion_reason": "tree",
            "notes": "occlusion note",
        },
    ]


class BuildCanonicalGtTest(unittest.TestCase):
    def test_normal_conversion_preserves_manual_values_and_adds_generated_fields(
        self,
    ) -> None:
        objects, visibility = build_canonical_rows(
            [make_object()], make_intervals(), make_manifest()
        )

        self.assertEqual(objects[0]["gt_object_id"], "P001")
        self.assertEqual(objects[0]["notes"], "start note")
        self.assertEqual(objects[0]["in_scope"], "true")
        self.assertEqual(objects[0]["occlusion_summary"], "mixed")
        self.assertEqual(objects[0]["review_status"], "draft")
        self.assertEqual(objects[0]["review_timestamp_utc"], "")
        self.assertEqual(visibility[0]["visibility_interval_id"], "P001_VI001")
        self.assertEqual(visibility[1]["visibility_interval_id"], "P001_VI002")
        self.assertEqual(visibility[1]["denominator_eligible"], "false")
        self.assertEqual(visibility[1]["occlusion_reason"], "vegetation")
        self.assertEqual(
            visibility[1]["notes"],
            "occlusion note; original_occlusion_reason=tree",
        )

    def test_reason_map_applies_all_user_mappings(self) -> None:
        rows = [
            {
                "gt_object_id": "P001",
                "start_frame_index": "4196",
                "end_frame_index": "4196",
                "visibility_status": "visible",
                "occlusion_reason": "",
                "notes": "",
            },
            {
                "gt_object_id": "P001",
                "start_frame_index": "4198",
                "end_frame_index": "4198",
                "visibility_status": "partially_occluded",
                "occlusion_reason": "tree",
                "notes": "",
            },
            {
                "gt_object_id": "P001",
                "start_frame_index": "4200",
                "end_frame_index": "4200",
                "visibility_status": "fully_occluded",
                "occlusion_reason": "reflector",
                "notes": "",
            },
        ]
        # Add canopy to the middle state to cover both structure sources.
        rows[1]["occlusion_reason"] = "canopy"
        _, visibility = build_canonical_rows(
            [make_object()],
            rows,
            make_manifest(),
            {"canopy": ("structure", "fixture mapping"),
             "reflector": ("structure", "fixture mapping")},
        )
        self.assertEqual(
            [row["occlusion_reason"] for row in visibility],
            ["", "structure", "structure"],
        )
        self.assertEqual(
            visibility[1]["notes"], "original_occlusion_reason=canopy"
        )
        self.assertEqual(
            visibility[2]["notes"], "original_occlusion_reason=reflector"
        )

    def test_unmapped_reason_is_rejected(self) -> None:
        with self.assertRaisesRegex(InputValidationError, "unmapped occlusion_reason 'tree'"):
            build_canonical_rows(
                [make_object()],
                make_intervals(),
                make_manifest(),
                {"canopy": ("structure", "fixture mapping")},
            )

    def test_overlap_is_rejected(self) -> None:
        rows = make_intervals()
        rows[1]["start_frame_index"] = "4198"
        with self.assertRaisesRegex(InputValidationError, "overlap"):
            build_canonical_rows([make_object()], rows, make_manifest())

    def test_gap_is_rejected(self) -> None:
        rows = make_intervals()
        rows[1]["start_frame_index"] = "4202"
        rows[1]["end_frame_index"] = "4202"
        with self.assertRaisesRegex(InputValidationError, "gap"):
            build_canonical_rows(
                [make_object(last_visible_frame_index="4202")],
                rows,
                make_manifest(),
            )

    def test_frame_outside_grid_is_rejected(self) -> None:
        rows = make_intervals()
        rows[0]["start_frame_index"] = "4197"
        with self.assertRaisesRegex(InputValidationError, "outside evaluation grid"):
            build_canonical_rows([make_object()], rows, make_manifest())

    def test_missing_occlusion_reason_is_rejected(self) -> None:
        rows = make_intervals()
        rows[1]["occlusion_reason"] = ""
        with self.assertRaisesRegex(
            InputValidationError, "occlusion_reason is required"
        ):
            build_canonical_rows([make_object()], rows, make_manifest())

    def test_unregistered_object_id_is_rejected(self) -> None:
        rows = make_intervals()
        rows[1]["gt_object_id"] = "P999"
        with self.assertRaisesRegex(InputValidationError, "unregistered gt_object_id"):
            build_canonical_rows([make_object()], rows, make_manifest())

    def test_output_is_deterministic_for_same_inputs(self) -> None:
        args = ([make_object()], make_intervals(), make_manifest())
        first = build_canonical_rows(*args)
        second = build_canonical_rows(
            copy.deepcopy(args[0]),
            copy.deepcopy(args[1]),
            copy.deepcopy(args[2]),
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
