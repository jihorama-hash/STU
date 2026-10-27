import unittest

from roundabout.schema import ConflictEvent


class ConflictEventTest(unittest.TestCase):
    def test_serialization_keeps_demo_fields(self) -> None:
        event = ConflictEvent(
            event_id="DJI_0482-0001",
            video_id="DJI_0482",
            timestamp_seconds=12.5,
            frame_index=375,
            conflict_type="pedestrian_vehicle",
            first_track_id=10,
            second_track_id=20,
            roi_id="crosswalk_east_entry",
            x=100.0,
            y=200.0,
            pet_seconds=0.8,
            ttc_seconds=None,
            crossing_angle_degrees=73.0,
        )
        payload = event.to_dict()
        self.assertEqual(payload["validation_status"], "unreviewed")
        self.assertEqual(payload["pet_seconds"], 0.8)


if __name__ == "__main__":
    unittest.main()
